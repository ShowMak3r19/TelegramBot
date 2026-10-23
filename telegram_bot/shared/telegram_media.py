from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow declared in requirements.
    Image = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MOTION_FRAME_WIDTH = 1280

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
MOTION_IMAGE_SUFFIXES = {".gif"}
STATIC_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CONVERTIBLE_GIF_SUFFIXES = VIDEO_SUFFIXES | MOTION_IMAGE_SUFFIXES | {".webp"}
TGS_STICKER_SUFFIXES = {".tgs"}
TGS_STICKER_MIME_TYPES = {"application/x-tgsticker"}

MIME_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "application/x-tgsticker": ".tgs",
}


def media_document(message: Any) -> Any:
    return getattr(getattr(message, "media", None), "document", None) or getattr(message, "document", None)


def media_mime_type(message: Any) -> str:
    document = media_document(message)
    file = getattr(message, "file", None)
    return str(getattr(document, "mime_type", "") or getattr(file, "mime_type", "") or "").lower()


def media_file_name(message: Any) -> str:
    document = media_document(message)
    for attr in getattr(document, "attributes", []) or []:
        file_name = getattr(attr, "file_name", "")
        if file_name:
            return str(file_name).lower()

    file = getattr(message, "file", None)
    name = getattr(file, "name", "") if file else ""
    if name:
        return str(name).lower()

    ext = _normalize_extension(getattr(file, "ext", "") if file else "")
    if ext:
        return f"telegram-media{ext}"

    suffix = MIME_SUFFIXES.get(media_mime_type(message), "")
    return f"telegram-media{suffix}" if suffix else ""


def media_file_suffix(message: Any) -> str:
    suffix = Path(media_file_name(message)).suffix.lower()
    if suffix:
        return suffix

    file = getattr(message, "file", None)
    file_ext = _normalize_extension(getattr(file, "ext", "") if file else "")
    if file_ext:
        return file_ext
    return MIME_SUFFIXES.get(media_mime_type(message), "")


def media_has_sticker_attribute(message: Any) -> bool:
    if bool(getattr(message, "sticker", False)):
        return True
    document = media_document(message)
    for attr in getattr(document, "attributes", []) or []:
        class_name = attr.__class__.__name__.lower()
        if "sticker" in class_name:
            return True
    return False


def media_is_tgs_sticker(message: Any) -> bool:
    return media_mime_type(message) in TGS_STICKER_MIME_TYPES or media_file_suffix(message) in TGS_STICKER_SUFFIXES


def media_is_motion(message: Any) -> bool:
    if media_is_tgs_sticker(message):
        return False
    mime_type = media_mime_type(message)
    if mime_type.startswith("video/") or mime_type == "image/gif":
        return True
    return media_file_suffix(message) in VIDEO_SUFFIXES | MOTION_IMAGE_SUFFIXES


def media_may_be_video(message: Any) -> bool:
    if media_is_tgs_sticker(message):
        return False
    mime_type = media_mime_type(message)
    if mime_type.startswith("video/"):
        return True
    return media_file_suffix(message) in VIDEO_SUFFIXES


def media_can_convert_to_gif(message: Any) -> bool:
    if media_is_tgs_sticker(message):
        return False
    mime_type = media_mime_type(message)
    if mime_type.startswith("video/") or mime_type in {"image/gif", "image/webp"}:
        return True
    return media_file_suffix(message) in CONVERTIBLE_GIF_SUFFIXES


def _normalize_extension(value: Any) -> str:
    ext = str(value or "").strip().lower()
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


def media_size_bytes(message: Any) -> int:
    document = getattr(getattr(message, "media", None), "document", None) or getattr(message, "document", None)
    file = getattr(message, "file", None)
    for value in (getattr(document, "size", 0), getattr(file, "size", 0) if file else 0):
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return 0


def convert_image_bytes_to_jpeg(media: bytes) -> bytes | None:
    if Image is None:
        return None
    try:
        with Image.open(io.BytesIO(media)) as image:
            try:
                image.seek(0)
            except EOFError:
                pass
            image.thumbnail((2048, 2048))
            if image.mode in {"RGBA", "LA", "P"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                background.alpha_composite(rgba)
                image = background.convert("RGB")
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90, optimize=True)
            return output.getvalue()
    except Exception:
        return None


def extract_first_frame_from_path_as_jpeg(media_path: Path) -> bytes | None:
    if not shutil.which("ffmpeg"):
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="tg_ai_first_frame_") as tmp:
            output_path = Path(tmp) / "frame.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(media_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale='min({MOTION_FRAME_WIDTH},iw)':-2:flags=lanczos",
                    "-q:v",
                    "3",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
            if output_path.exists() and output_path.stat().st_size:
                return output_path.read_bytes()
    except Exception:
        logger.exception("Failed to extract first frame from media path for AI input")
    return None


def extract_video_first_frame_as_jpeg(media: bytes, suffix: str) -> bytes | None:
    if not shutil.which("ffmpeg"):
        return None
    suffix = suffix if suffix.startswith(".") and len(suffix) <= 8 else ".bin"
    try:
        with tempfile.TemporaryDirectory(prefix="tg_ai_media_") as tmp:
            input_path = Path(tmp) / f"input{suffix}"
            input_path.write_bytes(media)
            return extract_first_frame_from_path_as_jpeg(input_path)
    except Exception:
        logger.exception("Failed to extract first frame for AI media input")
    return None


def media_bytes_to_responses_image_url(media: bytes, target: Any) -> tuple[str, str | None]:
    jpeg = convert_image_bytes_to_jpeg(media)
    if jpeg is None and media_may_be_video(target):
        jpeg = extract_video_first_frame_as_jpeg(media, media_file_suffix(target))
    if jpeg is None:
        return "", "UNSUPPORTED_MEDIA"
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("utf-8"), None


def probe_motion_media_duration_seconds(media_path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        return max(0.0, float(result.stdout.strip() or "0"))
    except Exception:
        return 0.0


def representative_frame_positions(duration_seconds: float, max_frames: int) -> list[float]:
    max_frames = max(1, int(max_frames))
    if duration_seconds <= 0:
        return [float(index) for index in range(max_frames)]
    frame_count = min(max_frames, max(1, int(duration_seconds / 2) + 1))
    return [max(0.0, duration_seconds * (index + 0.5) / frame_count) for index in range(frame_count)]


def extract_motion_media_frames_as_jpegs(media_path: Path, max_frames: int) -> list[bytes]:
    if not shutil.which("ffmpeg") or max_frames <= 0:
        return []

    duration = probe_motion_media_duration_seconds(media_path)
    positions = representative_frame_positions(duration, max_frames)
    frames: list[bytes] = []
    with tempfile.TemporaryDirectory(prefix="tg_ai_frames_") as tmp:
        tmp_path = Path(tmp)
        for index, position in enumerate(positions, start=1):
            output_path = tmp_path / f"frame_{index:02d}.jpg"
            command = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{position:.3f}",
                "-i",
                str(media_path),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({MOTION_FRAME_WIDTH},iw)':-2:flags=lanczos",
                "-q:v",
                "3",
                str(output_path),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=30)
            except Exception:
                logger.info("AI motion keyframe extract failed path=%s position=%.3f", media_path, position)
                continue
            if output_path.exists() and output_path.stat().st_size:
                frames.append(output_path.read_bytes())

    if frames:
        logger.info("AI motion media extracted frames=%s duration=%.3f path=%s", len(frames), duration, media_path)
        return frames[:max_frames]

    first_frame = extract_first_frame_from_path_as_jpeg(media_path)
    return [first_frame] if first_frame else []
