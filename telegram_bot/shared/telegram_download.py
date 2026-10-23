"""大文件下载：Telethon iter_download 分块写入 .part，失败后断点续传。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Telethon 要求 request_size 为 4KB 倍数且整除 512KB；续传偏移按它对齐
REQUEST_SIZE = 512 * 1024


async def download_document_resumable(
    client: Any,
    message: Any,
    dest: Path,
    *,
    retries: int = 5,
    refetch: Callable[[], Awaitable[Any]] | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    request_size: int = REQUEST_SIZE,
) -> int:
    """下载消息里的文档到 dest，返回字节数。refetch 用于重试前刷新过期的 file_reference。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    expected = document_size(message)
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            offset = part.stat().st_size if part.exists() else 0
            offset -= offset % request_size
            with part.open("r+b" if part.exists() else "wb") as fh:
                fh.truncate(offset)
                fh.seek(offset)
                kwargs: dict[str, Any] = {"offset": offset, "request_size": request_size}
                if expected:
                    kwargs["file_size"] = expected
                async for chunk in client.iter_download(_media_of(message), **kwargs):
                    fh.write(chunk)
            size = part.stat().st_size
            if expected and size != expected:
                raise IOError(f"下载不完整：{size}/{expected} 字节")
            part.replace(dest)
            return size
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt >= attempts:
                raise
            delay = min(30.0, 2.0 ** attempt)
            done = part.stat().st_size if part.exists() else 0
            logger.warning(
                "Document download failed (attempt %s/%s, %s/%s bytes), retry in %.0fs: %s",
                attempt, attempts, done, expected or "?", delay, exc,
            )
            await sleep(delay)
            if refetch is not None:
                try:
                    message = await refetch() or message
                except Exception:
                    logger.warning("Refetching message before download retry failed", exc_info=True)
    raise RuntimeError("unreachable")


def document_size(message: Any) -> int:
    file = getattr(message, "file", None)
    size = getattr(file, "size", None) or getattr(getattr(message, "document", None), "size", None)
    try:
        return int(size or 0)
    except (TypeError, ValueError):
        return 0


def document_name(message: Any) -> str:
    file = getattr(message, "file", None)
    return str(getattr(file, "name", "") or "")


def _media_of(message: Any) -> Any:
    return getattr(message, "document", None) or getattr(message, "media", None) or message
