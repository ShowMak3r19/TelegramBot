from __future__ import annotations

import base64
import binascii
import io
import json
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from telegram_bot.shared.telegram_io import atomic_write_text

UI_PREFERENCES_FILENAME = "ui_preferences.json"
UI_WALLPAPERS_DIRNAME = "ui_wallpapers"
UI_SKINS_DIRNAME = "ui_skins"
MAX_WALLPAPER_BYTES = 8 * 1024 * 1024
MAX_WALLPAPER_BODY_BYTES = 12 * 1024 * 1024
MAX_SKIN_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_SKIN_BODY_BYTES = 24 * 1024 * 1024

_ALLOWED_THEMES = {"dark", "light"}
_ALLOWED_DENSITIES = {"compact", "comfortable", "spacious"}
_ALLOWED_ACCENTS = {"emerald", "indigo", "crimson", "amber", "violet", "sky"}
_ALLOWED_WALLPAPER_TYPES = {"preset", "upload", "url", "skin", "none"}
_ALLOWED_AMBIENT_EFFECTS = {"aurora", "stardust", "mesh", "none"}
_DISALLOWED_SIDEBAR_ITEMS = {"logs"}
_SAFE_WALLPAPER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(png|jpg|jpeg|webp|gif)$")
_SAFE_SKIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
_DATA_URL_RE = re.compile(r"^data:[^;]+;base64,(?P<b64>.+)$", re.S)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def default_ui_preferences() -> dict[str, Any]:
    return {
        "version": 1,
        "theme": "dark",
        "density": "comfortable",
        "sidebarCollapsed": False,
        "appearance": {
            "accent": "crimson",
            "wallpaperType": "preset",
            "wallpaperPreset": "warm-dusk",
            "wallpaperUrl": "",
            "skinId": "",
            "showSkinAvatar": True,
            "wallpaperOpacity": 68,
            "glassOpacity": 56,
            "glassBlur": 18,
            "ambientEffect": "aurora",
            "mouseParallax": True,
            "cardSpotlight": True,
        },
        "sidebarLayout": None,
        "dashboardShortcuts": None,
    }


def resolve_ui_paths(app: Any) -> tuple[Path, Path]:
    project_root = Path(getattr(app, "project_root", Path.cwd()))
    runtime_cfg = getattr(getattr(app, "config", None), "runtime", None)
    data_dir_rel = getattr(runtime_cfg, "data_dir", "runtime/data") or "runtime/data"
    data_dir = Path(data_dir_rel)
    if not data_dir.is_absolute():
        data_dir = project_root / data_dir
    return data_dir / UI_PREFERENCES_FILENAME, data_dir / UI_WALLPAPERS_DIRNAME


def resolve_skins_dir(app_or_prefs_path: Any) -> Path:
    if isinstance(app_or_prefs_path, Path):
        return app_or_prefs_path.parent / UI_SKINS_DIRNAME
    prefs_path, _wp_dir = resolve_ui_paths(app_or_prefs_path)
    return prefs_path.parent / UI_SKINS_DIRNAME


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _sanitize_sidebar_layout(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None or not isinstance(raw, list):
        return None
    groups: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for idx, group in enumerate(raw[:30]):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or f"group_{idx + 1}").strip()[:48]
        title = str(group.get("title") or "").strip()[:40]
        raw_items = group.get("items")
        items: list[str] = []
        if isinstance(raw_items, list):
            for item in raw_items[:64]:
                key = str(item or "").strip()[:64]
                if key and key not in seen_items and key not in _DISALLOWED_SIDEBAR_ITEMS:
                    seen_items.add(key)
                    items.append(key)
        groups.append({"id": group_id or f"group_{idx + 1}", "title": title, "items": items})
    return groups


def _sanitize_shortcuts(raw: Any) -> list[str] | None:
    if raw is None or not isinstance(raw, list):
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw[:12]:
        key = str(item or "").strip()[:64]
        if key and key not in seen:
            seen.add(key)
            cleaned.append(key)
    return cleaned


def _sanitize_wallpaper_url(raw: Any) -> str:
    value = str(raw or "").strip()[:2048]
    if not value:
        return ""
    if (
        value.startswith("/api/ui/wallpapers/")
        or value.startswith("/api/ui/skins/")
        or value.startswith("https://")
        or value.startswith("http://")
    ):
        return value
    return ""


def _sanitize_skin_id(raw: Any) -> str:
    value = str(raw or "").strip()
    return value if _SAFE_SKIN_ID_RE.match(value) else ""


def _merge_preferences(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base))
    if not isinstance(patch, dict):
        return merged

    if patch.get("theme") in _ALLOWED_THEMES:
        merged["theme"] = patch["theme"]
    if patch.get("density") in _ALLOWED_DENSITIES:
        merged["density"] = patch["density"]
    if "sidebarCollapsed" in patch:
        merged["sidebarCollapsed"] = bool(patch["sidebarCollapsed"])

    raw_appearance = patch.get("appearance")
    if isinstance(raw_appearance, dict):
        app_cfg = merged["appearance"]
        if raw_appearance.get("accent") in _ALLOWED_ACCENTS:
            app_cfg["accent"] = raw_appearance["accent"]
        if raw_appearance.get("wallpaperType") in _ALLOWED_WALLPAPER_TYPES:
            app_cfg["wallpaperType"] = raw_appearance["wallpaperType"]
        if isinstance(raw_appearance.get("wallpaperPreset"), str):
            app_cfg["wallpaperPreset"] = raw_appearance["wallpaperPreset"].strip()[:64] or "warm-dusk"
        if "wallpaperUrl" in raw_appearance:
            app_cfg["wallpaperUrl"] = _sanitize_wallpaper_url(raw_appearance["wallpaperUrl"])
        if "skinId" in raw_appearance:
            app_cfg["skinId"] = _sanitize_skin_id(raw_appearance["skinId"])
        if "showSkinAvatar" in raw_appearance:
            app_cfg["showSkinAvatar"] = bool(raw_appearance["showSkinAvatar"])
        if "wallpaperOpacity" in raw_appearance:
            app_cfg["wallpaperOpacity"] = _clamp_int(raw_appearance["wallpaperOpacity"], 0, 100, app_cfg["wallpaperOpacity"])
        if "glassOpacity" in raw_appearance:
            app_cfg["glassOpacity"] = _clamp_int(raw_appearance["glassOpacity"], 20, 95, app_cfg["glassOpacity"])
        if "glassBlur" in raw_appearance:
            app_cfg["glassBlur"] = _clamp_int(raw_appearance["glassBlur"], 0, 36, app_cfg["glassBlur"])
        if raw_appearance.get("ambientEffect") in _ALLOWED_AMBIENT_EFFECTS:
            app_cfg["ambientEffect"] = raw_appearance["ambientEffect"]
        if "mouseParallax" in raw_appearance:
            app_cfg["mouseParallax"] = bool(raw_appearance["mouseParallax"])
        if "cardSpotlight" in raw_appearance:
            app_cfg["cardSpotlight"] = bool(raw_appearance["cardSpotlight"])

    if "sidebarLayout" in patch:
        merged["sidebarLayout"] = _sanitize_sidebar_layout(patch["sidebarLayout"])
    if "dashboardShortcuts" in patch:
        merged["dashboardShortcuts"] = _sanitize_shortcuts(patch["dashboardShortcuts"])

    return merged


def list_wallpapers(wallpapers_dir: Path) -> list[dict[str, Any]]:
    if not wallpapers_dir.exists() or not wallpapers_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in wallpapers_dir.iterdir():
        if not path.is_file() or not _SAFE_WALLPAPER_NAME_RE.match(path.name):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": path.name,
                "url": f"/api/ui/wallpapers/{path.name}",
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    entries.sort(key=lambda item: (item["mtime"], item["name"]), reverse=True)
    return entries


def _detect_image_extension(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def _normalize_skin_meta(raw: dict[str, Any], fallback_name: str = "自定义皮肤") -> dict[str, Any]:
    name = str(raw.get("name") or fallback_name).strip()[:40] or fallback_name
    description = str(raw.get("description") or "").strip()[:120]
    raw_candidates = raw.get("candidates")
    candidates: list[str] = []
    if isinstance(raw_candidates, list):
        for item in raw_candidates[:12]:
            color = str(item or "").strip().lower()
            if _HEX_COLOR_RE.match(color):
                candidates.append(color)
    if not candidates:
        candidates = ["#c06359", "#2e2521", "#97635d", "#d5b49e", "#5b4740", "#f0d8d0"]
    accent_index = _clamp_int(raw.get("accent_index", 0), 0, len(candidates) - 1, 0)
    secondary_index = _clamp_int(raw.get("secondary_index", len(candidates) - 1), 0, len(candidates) - 1, len(candidates) - 1)
    raw_avatar = raw.get("avatar") if isinstance(raw.get("avatar"), dict) else {}
    avatar = {
        "cx": round(_clamp_float(raw_avatar.get("cx", 0.5), 0.05, 0.95, 0.5), 4),
        "cy": round(_clamp_float(raw_avatar.get("cy", 0.35), 0.05, 0.95, 0.35), 4),
        "r": round(_clamp_float(raw_avatar.get("r", 0.2), 0.06, 0.5, 0.2), 4),
    }
    return {
        "format": 1,
        "name": name,
        "description": description,
        "candidates": candidates,
        "accent_index": accent_index,
        "secondary_index": secondary_index,
        "avatar": avatar,
    }


def _find_skin_bg_file(skin_dir: Path) -> Path | None:
    for ext in ("webp", "png", "jpg", "jpeg", "gif"):
        candidate = skin_dir / f"background.{ext}"
        if candidate.is_file():
            return candidate
    return None


def _generate_skin_avatar(bg_bytes: bytes, avatar: dict[str, float], target_path: Path) -> bool:
    try:
        from PIL import Image
    except Exception:
        return False
    try:
        with Image.open(io.BytesIO(bg_bytes)) as img:
            rgba = img.convert("RGBA")
            w, h = rgba.size
            cx = avatar.get("cx", 0.5) * w
            cy = avatar.get("cy", 0.35) * h
            radius_px = max(32.0, avatar.get("r", 0.2) * min(w, h) * 1.15)
            half = min(radius_px, min(w, h) / 2.0)
            left = max(0.0, min(w - half * 2, cx - half))
            top = max(0.0, min(h - half * 2, cy - half))
            box = (int(round(left)), int(round(top)), int(round(left + half * 2)), int(round(top + half * 2)))
            cropped = rgba.crop(box).resize((256, 256), Image.Resampling.LANCZOS)
            tmp_path = target_path.with_suffix(".tmp.webp")
            cropped.save(tmp_path, format="WEBP", quality=90)
            tmp_path.replace(target_path)
            return True
    except Exception:
        return False


def _skin_record(skin_dir: Path) -> dict[str, Any] | None:
    meta_file = skin_dir / "skin.json"
    bg_file = _find_skin_bg_file(skin_dir)
    if not meta_file.is_file() or bg_file is None:
        return None
    try:
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        stat = meta_file.stat()
    except Exception:
        return None
    meta = _normalize_skin_meta(raw, fallback_name=skin_dir.name)
    skin_id = skin_dir.name
    avatar_file = skin_dir / "avatar.webp"
    has_avatar = avatar_file.is_file()
    return {
        "id": skin_id,
        **meta,
        "background_url": f"/api/ui/skins/{skin_id}/background",
        "avatar_url": f"/api/ui/skins/{skin_id}/avatar" if has_avatar else f"/api/ui/skins/{skin_id}/background",
        "export_url": f"/api/ui/skins/{skin_id}/export",
        "size": bg_file.stat().st_size,
        "mtime": int(stat.st_mtime),
    }


def list_skins(skins_dir: Path) -> list[dict[str, Any]]:
    if not skins_dir.exists() or not skins_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for entry in skins_dir.iterdir():
        if not entry.is_dir() or not _SAFE_SKIN_ID_RE.match(entry.name):
            continue
        rec = _skin_record(entry)
        if rec is not None:
            items.append(rec)
    items.sort(key=lambda item: (item["mtime"], item["id"]), reverse=True)
    return items


def import_mvskin_bytes(skins_dir: Path, filename: str, raw_bytes: bytes, skin_id: str | None = None) -> dict[str, Any]:
    if not raw_bytes:
        raise ValueError("皮肤文件内容为空")
    if len(raw_bytes) > MAX_SKIN_ARCHIVE_BYTES:
        raise ValueError("皮肤包不能超过 16 MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("无效的 .mvskin 皮肤包（非 ZIP 格式）") from exc

    with zf:
        skin_json_bytes: bytes | None = None
        bg_bytes: bytes | None = None
        for info in zf.infolist():
            if info.is_dir():
                continue
            member_name = info.filename.replace("\\", "/").strip("/")
            if "/" in member_name or ".." in member_name:
                continue
            if member_name == "skin.json":
                if info.file_size > 256 * 1024:
                    raise ValueError("skin.json 体积异常过大")
                skin_json_bytes = zf.read(info)
            elif member_name.startswith("background.") and bg_bytes is None:
                if info.file_size > MAX_SKIN_ARCHIVE_BYTES:
                    raise ValueError("皮肤背景图不能超过 16 MB")
                bg_bytes = zf.read(info)

    if skin_json_bytes is None:
        raise ValueError("皮肤包缺少 skin.json")
    if bg_bytes is None:
        raise ValueError("皮肤包缺少 background 背景图")

    ext = _detect_image_extension(bg_bytes)
    if ext is None:
        raise ValueError("皮肤背景图格式不受支持（需 WebP/PNG/JPEG/GIF）")

    try:
        parsed_meta = json.loads(skin_json_bytes.decode("utf-8"))
        if not isinstance(parsed_meta, dict):
            raise ValueError("skin.json 格式不正确")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("skin.json 解析失败") from exc

    fallback_name = Path(str(filename or "skin")).stem or "自定义皮肤"
    meta = _normalize_skin_meta(parsed_meta, fallback_name=fallback_name)

    if skin_id and _SAFE_SKIN_ID_RE.match(skin_id):
        resolved_id = skin_id
    else:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", fallback_name).strip("-")[:20] or "skin"
        resolved_id = f"mv_{int(time.time())}_{secrets.token_hex(3)}_{slug}"
        resolved_id = re.sub(r"[^A-Za-z0-9_-]", "", resolved_id)[:64]

    target_dir = skins_dir / resolved_id
    target_dir.mkdir(parents=True, exist_ok=True)
    # Remove any old background.* extensions if re-importing into same ID
    for old_bg in target_dir.glob("background.*"):
        try:
            old_bg.unlink()
        except OSError:
            pass

    bg_path = target_dir / f"background.{ext}"
    tmp_bg = target_dir / f".background.{ext}.tmp"
    tmp_bg.write_bytes(bg_bytes)
    tmp_bg.replace(bg_path)

    atomic_write_text(target_dir / "skin.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    _generate_skin_avatar(bg_bytes, meta["avatar"], target_dir / "avatar.webp")

    record = _skin_record(target_dir)
    if record is None:
        raise RuntimeError("皮肤写入后校验失败")
    return {"skin": record, "skins": list_skins(skins_dir)}


def import_mvskin_base64(skins_dir: Path, filename: str, data_b64: str) -> dict[str, Any]:
    raw_text = str(data_b64 or "").strip()
    if not raw_text:
        raise ValueError("缺少皮肤包数据")
    match = _DATA_URL_RE.match(raw_text)
    b64_payload = match.group("b64").strip() if match else raw_text
    try:
        raw_bytes = base64.b64decode(b64_payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("皮肤包 Base64 编码无效") from exc
    return import_mvskin_bytes(skins_dir, filename, raw_bytes)


def update_skin_meta(skins_dir: Path, skin_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    safe_id = _sanitize_skin_id(skin_id)
    if not safe_id:
        raise ValueError("无效的皮肤 ID")
    target_dir = (skins_dir / safe_id).resolve()
    root = skins_dir.resolve()
    if root not in target_dir.parents or not target_dir.is_dir():
        raise ValueError("皮肤不存在")
    meta_file = target_dir / "skin.json"
    if not meta_file.is_file():
        raise ValueError("皮肤元数据缺失")
    current = json.loads(meta_file.read_text(encoding="utf-8"))
    if not isinstance(current, dict):
        current = {}
    merged_raw = dict(current)
    for key in ("name", "description", "accent_index", "secondary_index", "avatar"):
        if key in patch:
            merged_raw[key] = patch[key]
    meta = _normalize_skin_meta(merged_raw, fallback_name=current.get("name", safe_id))
    atomic_write_text(meta_file, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    if "avatar" in patch:
        bg_file = _find_skin_bg_file(target_dir)
        if bg_file is not None:
            _generate_skin_avatar(bg_file.read_bytes(), meta["avatar"], target_dir / "avatar.webp")
    record = _skin_record(target_dir)
    if record is None:
        raise ValueError("皮肤更新后不可用")
    return {"skin": record, "skins": list_skins(skins_dir)}


def delete_skin(skins_dir: Path, skin_id: str) -> list[dict[str, Any]]:
    safe_id = _sanitize_skin_id(skin_id)
    if safe_id:
        root = skins_dir.resolve()
        target_dir = (root / safe_id).resolve()
        if root in target_dir.parents and target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
    return list_skins(skins_dir)


def resolve_skin_asset(skins_dir: Path, skin_id: str, asset: str) -> Path | None:
    safe_id = _sanitize_skin_id(skin_id)
    if not safe_id:
        return None
    root = skins_dir.resolve()
    target_dir = (root / safe_id).resolve()
    if root not in target_dir.parents or not target_dir.is_dir():
        return None
    if asset == "background":
        return _find_skin_bg_file(target_dir)
    if asset == "avatar":
        avatar_file = target_dir / "avatar.webp"
        return avatar_file if avatar_file.is_file() else _find_skin_bg_file(target_dir)
    return None


def export_mvskin_bytes(skins_dir: Path, skin_id: str) -> tuple[str, bytes] | None:
    safe_id = _sanitize_skin_id(skin_id)
    if not safe_id:
        return None
    root = skins_dir.resolve()
    target_dir = (root / safe_id).resolve()
    if root not in target_dir.parents or not target_dir.is_dir():
        return None
    meta_file = target_dir / "skin.json"
    bg_file = _find_skin_bg_file(target_dir)
    if not meta_file.is_file() or bg_file is None:
        return None
    meta = _normalize_skin_meta(json.loads(meta_file.read_text(encoding="utf-8")), fallback_name=safe_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("skin.json", json.dumps(meta, ensure_ascii=False))
        zf.writestr(bg_file.name, bg_file.read_bytes())
    safe_download = re.sub(r'[\\/:*?"<>|]+', "_", meta["name"]).strip() or safe_id
    return f"{safe_download}.mvskin", buf.getvalue()


def load_ui_preferences(prefs_path: Path, wallpapers_dir: Path, skins_dir: Path | None = None) -> dict[str, Any]:
    base = default_ui_preferences()
    if prefs_path.exists() and prefs_path.is_file():
        try:
            stored = json.loads(prefs_path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                base = _merge_preferences(base, stored)
        except Exception:
            pass
    resolved_skins = skins_dir if skins_dir is not None else resolve_skins_dir(prefs_path)
    base["wallpapers"] = list_wallpapers(wallpapers_dir)
    base["skins"] = list_skins(resolved_skins)
    return base


def save_ui_preferences(
    prefs_path: Path, wallpapers_dir: Path, patch: dict[str, Any], skins_dir: Path | None = None
) -> dict[str, Any]:
    resolved_skins = skins_dir if skins_dir is not None else resolve_skins_dir(prefs_path)
    current = load_ui_preferences(prefs_path, wallpapers_dir, resolved_skins)
    current.pop("wallpapers", None)
    current.pop("skins", None)
    updated = _merge_preferences(current, patch)
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(prefs_path, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
    updated["wallpapers"] = list_wallpapers(wallpapers_dir)
    updated["skins"] = list_skins(resolved_skins)
    return updated


def save_uploaded_wallpaper(wallpapers_dir: Path, filename: str, data_url: str) -> dict[str, Any]:
    raw_data = str(data_url or "").strip()
    if not raw_data:
        raise ValueError("缺少图片内容")
    match = _DATA_URL_RE.match(raw_data)
    b64_text = match.group("b64").strip() if match else raw_data
    try:
        payload = base64.b64decode(b64_text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片 Base64 编码无效") from exc
    if not payload:
        raise ValueError("图片内容为空")
    if len(payload) > MAX_WALLPAPER_BYTES:
        raise ValueError("图片不能超过 8 MB")
    ext = _detect_image_extension(payload)
    if ext is None:
        raise ValueError("仅支持 PNG、JPEG、WebP 或 GIF 图片")

    wallpapers_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(str(filename or "wallpaper")).stem).strip("-")[:28] or "wallpaper"
    target_name = f"wp-{int(time.time())}-{secrets.token_hex(4)}-{safe_stem}.{ext}"
    target_path = wallpapers_dir / target_name
    tmp_path = wallpapers_dir / f".{target_name}.tmp"
    tmp_path.write_bytes(payload)
    tmp_path.replace(target_path)

    return {
        "name": target_name,
        "url": f"/api/ui/wallpapers/{target_name}",
        "size": len(payload),
        "wallpapers": list_wallpapers(wallpapers_dir),
    }


def resolve_wallpaper_file(wallpapers_dir: Path, name: str) -> Path | None:
    candidate_name = str(name or "").strip()
    if not _SAFE_WALLPAPER_NAME_RE.match(candidate_name):
        return None
    root = wallpapers_dir.resolve()
    target = (root / candidate_name).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target


def delete_uploaded_wallpaper(wallpapers_dir: Path, name: str) -> list[dict[str, Any]]:
    target = resolve_wallpaper_file(wallpapers_dir, name)
    if target is not None:
        try:
            target.unlink()
        except OSError:
            pass
    return list_wallpapers(wallpapers_dir)
