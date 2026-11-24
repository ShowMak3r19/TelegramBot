from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from telegram_bot.admin.server import AdminServer
from telegram_bot.admin.ui_preferences import (
    delete_skin,
    delete_uploaded_wallpaper,
    export_mvskin_bytes,
    import_mvskin_bytes,
    load_ui_preferences,
    resolve_skin_asset,
    resolve_wallpaper_file,
    save_ui_preferences,
    save_uploaded_wallpaper,
    update_skin_meta,
)
from telegram_bot.config import AppConfig

import io
import zipfile

# Minimal valid 1x1 transparent PNG
_SAMPLE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
_SAMPLE_PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(_SAMPLE_PNG).decode("ascii")


def test_ui_preferences_roundtrip_and_sanitization(tmp_path: Path) -> None:
    prefs_path = tmp_path / "ui_preferences.json"
    wp_dir = tmp_path / "ui_wallpapers"

    initial = load_ui_preferences(prefs_path, wp_dir)
    assert initial["theme"] == "dark"
    assert initial["appearance"]["ambientEffect"] == "aurora"
    assert initial["wallpapers"] == []

    updated = save_ui_preferences(
        prefs_path,
        wp_dir,
        {
            "theme": "light",
            "density": "compact",
            "sidebarCollapsed": True,
            "appearance": {
                "accent": "crimson",
                "wallpaperType": "url",
                "wallpaperUrl": "https://example.com/bg.webp",
                "wallpaperOpacity": 999,
                "glassOpacity": 10,
                "glassBlur": 24,
                "ambientEffect": "stardust",
                "mouseParallax": False,
                "cardSpotlight": True,
            },
            "sidebarLayout": [
                {"id": "g1", "title": "常用", "items": ["dashboard", "moduleRedPacket", "dashboard"]},
                {"id": "g2", "title": "", "items": ["settings"]},
            ],
        },
    )
    assert updated["theme"] == "light"
    assert updated["density"] == "compact"
    assert updated["sidebarCollapsed"] is True
    assert updated["appearance"]["accent"] == "crimson"
    assert updated["appearance"]["wallpaperOpacity"] == 100
    assert updated["appearance"]["glassOpacity"] == 20
    assert updated["appearance"]["glassBlur"] == 24
    assert updated["appearance"]["ambientEffect"] == "stardust"
    assert updated["appearance"]["mouseParallax"] is False
    assert updated["sidebarLayout"] == [
        {"id": "g1", "title": "常用", "items": ["dashboard", "moduleRedPacket"]},
        {"id": "g2", "title": "", "items": ["settings"]},
    ]

    reloaded = load_ui_preferences(prefs_path, wp_dir)
    assert reloaded["theme"] == "light"
    assert reloaded["sidebarLayout"][0]["items"] == ["dashboard", "moduleRedPacket"]


def test_ui_wallpaper_upload_validation_and_delete(tmp_path: Path) -> None:
    wp_dir = tmp_path / "ui_wallpapers"

    saved = save_uploaded_wallpaper(wp_dir, "my sunset.png", _SAMPLE_PNG_DATA_URL)
    assert saved["name"].endswith(".png")
    assert saved["url"] == f"/api/ui/wallpapers/{saved['name']}"
    assert len(saved["wallpapers"]) == 1

    resolved = resolve_wallpaper_file(wp_dir, saved["name"])
    assert resolved is not None
    assert resolved.read_bytes() == _SAMPLE_PNG

    # Reject path traversal and invalid image magic bytes
    assert resolve_wallpaper_file(wp_dir, "../secret.png") is None
    try:
        save_uploaded_wallpaper(wp_dir, "bad.png", "data:image/png;base64," + base64.b64encode(b"not-an-image").decode("ascii"))
    except ValueError as exc:
        assert "仅支持" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-image bytes")

    remaining = delete_uploaded_wallpaper(wp_dir, saved["name"])
    assert remaining == []
    assert resolve_wallpaper_file(wp_dir, saved["name"]) is None


def test_admin_server_ui_preferences_and_wallpaper_http_endpoints(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.admin.host = "127.0.0.1"
    cfg.admin.port = 0
    cfg.runtime.data_dir = str(tmp_path / "data")
    fake_app = SimpleNamespace(config=cfg, project_root=tmp_path)

    server = AdminServer(fake_app)
    server.start()
    try:
        assert server.httpd is not None
        port = server.httpd.server_address[1]
        base = f"http://127.0.0.1:{port}"

        with urllib.request.urlopen(f"{base}/api/ui/preferences") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["theme"] == "dark"
            assert data["wallpapers"] == []

        req = urllib.request.Request(
            f"{base}/api/ui/preferences",
            data=json.dumps({"theme": "light", "appearance": {"accent": "indigo"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req) as resp:
            put_res = json.loads(resp.read().decode("utf-8"))
            assert put_res["ok"] is True
            assert put_res["preferences"]["theme"] == "light"
            assert put_res["preferences"]["appearance"]["accent"] == "indigo"

        upload_req = urllib.request.Request(
            f"{base}/api/ui/wallpaper",
            data=json.dumps({"filename": "cover.png", "data_url": _SAMPLE_PNG_DATA_URL}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(upload_req) as resp:
            up_res = json.loads(resp.read().decode("utf-8"))
            assert up_res["ok"] is True
            wp_url = up_res["wallpaper"]["url"]
            wp_name = up_res["wallpaper"]["name"]

        with urllib.request.urlopen(f"{base}{wp_url}") as resp:
            assert resp.headers.get("Content-Type") == "image/png"
            assert resp.read() == _SAMPLE_PNG

        del_req = urllib.request.Request(
            f"{base}/api/ui/wallpaper/delete",
            data=json.dumps({"name": wp_name}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(del_req) as resp:
            del_res = json.loads(resp.read().decode("utf-8"))
            assert del_res["ok"] is True
            assert del_res["wallpapers"] == []

        try:
            urllib.request.urlopen(f"{base}{wp_url}")
        except urllib.error.HTTPError as err:
            assert err.code == 404
        else:
            raise AssertionError("Expected 404 after wallpaper deletion")
    finally:
        server.stop()


def _make_sample_mvskin(name: str = "测试皮肤") -> bytes:
    buf = io.BytesIO()
    meta = {
        "format": 1,
        "name": name,
        "description": "柔和夜幕测试",
        "candidates": ["#b28f78", "#2e2521", "#97635d", "#d5b49e", "#5b4740", "#f0d8d0"],
        "accent_index": 2,
        "secondary_index": 5,
        "avatar": {"cx": 0.5, "cy": 0.35, "r": 0.2},
    }
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("skin.json", json.dumps(meta, ensure_ascii=False))
        zf.writestr("background.png", _SAMPLE_PNG)
    return buf.getvalue()


def test_mvskin_import_update_export_and_delete(tmp_path: Path) -> None:
    skins_dir = tmp_path / "ui_skins"
    raw = _make_sample_mvskin("存存测试")

    res = import_mvskin_bytes(skins_dir, "存存测试.mvskin", raw, skin_id="mv_test")
    skin = res["skin"]
    assert skin["id"] == "mv_test"
    assert skin["name"] == "存存测试"
    assert skin["accent_index"] == 2
    assert skin["background_url"] == "/api/ui/skins/mv_test/background"
    assert resolve_skin_asset(skins_dir, "mv_test", "background") is not None
    assert resolve_skin_asset(skins_dir, "../escape", "background") is None

    updated = update_skin_meta(skins_dir, "mv_test", {"accent_index": 4, "description": "新描述"})
    assert updated["skin"]["accent_index"] == 4
    assert updated["skin"]["description"] == "新描述"

    exported = export_mvskin_bytes(skins_dir, "mv_test")
    assert exported is not None
    dl_name, dl_bytes = exported
    assert dl_name.endswith(".mvskin")
    with zipfile.ZipFile(io.BytesIO(dl_bytes)) as zf:
        assert "skin.json" in zf.namelist()
        exported_meta = json.loads(zf.read("skin.json").decode("utf-8"))
        assert exported_meta["accent_index"] == 4

    remaining = delete_skin(skins_dir, "mv_test")
    assert remaining == []
    assert resolve_skin_asset(skins_dir, "mv_test", "background") is None


def test_admin_server_mvskin_http_endpoints(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.admin.host = "127.0.0.1"
    cfg.admin.port = 0
    cfg.runtime.data_dir = str(tmp_path / "data")
    fake_app = SimpleNamespace(config=cfg, project_root=tmp_path)

    server = AdminServer(fake_app)
    server.start()
    try:
        assert server.httpd is not None
        port = server.httpd.server_address[1]
        base = f"http://127.0.0.1:{port}"

        raw_b64 = base64.b64encode(_make_sample_mvskin("小田测试")).decode("ascii")
        imp_req = urllib.request.Request(
            f"{base}/api/ui/skins/import",
            data=json.dumps({"filename": "小田测试.mvskin", "data_b64": raw_b64}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(imp_req) as resp:
            imp_res = json.loads(resp.read().decode("utf-8"))
            assert imp_res["ok"] is True
            skin_id = imp_res["skin"]["id"]
            assert imp_res["skin"]["name"] == "小田测试"

        with urllib.request.urlopen(f"{base}/api/ui/skins/{skin_id}/background") as resp:
            assert resp.read() == _SAMPLE_PNG

        with urllib.request.urlopen(f"{base}/api/ui/skins/{skin_id}/export") as resp:
            assert resp.headers.get("Content-Type") == "application/zip"
            assert zipfile.is_zipfile(io.BytesIO(resp.read()))

        upd_req = urllib.request.Request(
            f"{base}/api/ui/skins/update",
            data=json.dumps({"id": skin_id, "accent_index": 3}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(upd_req) as resp:
            upd_res = json.loads(resp.read().decode("utf-8"))
            assert upd_res["ok"] is True
            assert upd_res["skin"]["accent_index"] == 3

        del_req = urllib.request.Request(
            f"{base}/api/ui/skins/delete",
            data=json.dumps({"id": skin_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(del_req) as resp:
            del_res = json.loads(resp.read().decode("utf-8"))
            assert del_res["ok"] is True
            assert del_res["skins"] == []
    finally:
        server.stop()


def test_admin_server_static_cache_revalidation(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.admin.host = "127.0.0.1"
    cfg.admin.port = 0
    cfg.runtime.data_dir = str(tmp_path / "data")
    fake_app = SimpleNamespace(config=cfg, project_root=tmp_path)

    server = AdminServer(fake_app)
    server.start()
    try:
        assert server.httpd is not None
        port = server.httpd.server_address[1]
        base = f"http://127.0.0.1:{port}"

        with urllib.request.urlopen(f"{base}/") as resp:
            assert resp.headers.get("Cache-Control") == "no-cache, must-revalidate"
            etag = resp.headers.get("ETag")
            assert etag

        req_304 = urllib.request.Request(f"{base}/", headers={"If-None-Match": etag})
        try:
            urllib.request.urlopen(req_304)
            assert False, "expected 304 Not Modified"
        except urllib.error.HTTPError as exc:
            assert exc.code == 304
            assert exc.headers.get("ETag") == etag
            assert exc.headers.get("Cache-Control") == "no-cache, must-revalidate"
    finally:
        server.stop()


def test_sidebar_layout_strips_logs_and_survives_partial_updates(tmp_path: Path) -> None:
    prefs_path = tmp_path / "ui_preferences.json"
    wp_dir = tmp_path / "ui_wallpapers"

    saved = save_ui_preferences(
        prefs_path,
        wp_dir,
        {
            "sidebarLayout": [
                {"id": "g1", "title": "常用", "items": ["dashboard", "logs", "moduleAiReply"]},
            ]
        },
    )
    assert saved["sidebarLayout"] == [
        {"id": "g1", "title": "常用", "items": ["dashboard", "moduleAiReply"]},
    ]

    # Updating appearance/theme without sidebarLayout must NOT reset the persisted arrangement
    after_theme = save_ui_preferences(
        prefs_path,
        wp_dir,
        {"theme": "light", "appearance": {"skinId": "mv_xiaotian"}},
    )
    assert after_theme["theme"] == "light"
    assert after_theme["sidebarLayout"] == [
        {"id": "g1", "title": "常用", "items": ["dashboard", "moduleAiReply"]},
    ]

    static_dir = Path(__file__).resolve().parents[1] / "telegram_bot" / "admin" / "static"
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    assert 'data-view="logs"' not in index_html
    assert 'id="topbarLogsBtn"' in index_html
    assert 'id="toggleLogAutoScrollBtn"' in index_html
