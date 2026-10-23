"""MagnetBoard（sehuatang-crawler）适配层：登录并调用「数据交换中心 → 导入数据」接口。

接口来自其前端：POST /api/auth/login（Cookie 会话）与 POST /api/data/import（multipart）。
功能模块只依赖 import_csv_sync，便于替换为直连数据库等其他实现。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from telegram_bot.shared.net import ensure_http_url

logger = logging.getLogger(__name__)


class MagnetBoardError(RuntimeError):
    pass


def import_csv_sync(
    base_url: str,
    username: str,
    password: str,
    file_path: Path,
    file_name: str,
    *,
    update_existing: bool = False,
    skip_duplicates: bool = True,
    timeout: float = 1800.0,
) -> dict[str, Any]:
    """同步登录并上传 CSV，返回导入接口的 JSON。请在 asyncio.to_thread 中调用。"""
    import httpx  # openai SDK 的依赖，运行环境已安装

    base = ensure_http_url(base_url).rstrip("/")
    # 上传/导入耗时随文件大小增长，读超时放宽到 timeout；连接超时保持较短
    client_timeout = httpx.Timeout(timeout, connect=15.0)
    with httpx.Client(timeout=client_timeout, follow_redirects=False) as client:
        login = client.post(
            f"{base}/api/auth/login",
            json={"username": username, "password": password, "remember_me": False},
        )
        login_data = _json_or_empty(login)
        if login.status_code >= 400 or login_data.get("success") is False:
            raise MagnetBoardError(f"MagnetBoard 登录失败（{login.status_code}）：{_error_text(login_data, login)}")

        headers: dict[str, str] = {}
        token = login_data.get("access_token") or login_data.get("token")
        if isinstance(token, str) and token:
            headers["Authorization"] = f"Bearer {token}"

        with Path(file_path).open("rb") as fh:
            response = client.post(
                f"{base}/api/data/import",
                headers=headers,
                files={"file": (file_name, fh, "text/csv")},
                data={
                    "update_existing": "true" if update_existing else "false",
                    "skip_duplicates": "true" if skip_duplicates else "false",
                },
            )
        payload = _json_or_empty(response)
        if response.status_code >= 400 or payload.get("success") is False:
            raise MagnetBoardError(f"MagnetBoard 导入失败（{response.status_code}）：{_error_text(payload, response)}")
        return payload


def summarize_import_result(payload: dict[str, Any], limit: int = 300) -> str:
    """把导入接口返回压缩成一行日志/状态文本。"""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    text = json.dumps(data, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _json_or_empty(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {"data": data}


def _error_text(payload: dict[str, Any], response: Any) -> str:
    for key in ("detail", "message", "error"):
        value = payload.get(key)
        if value:
            return str(value)
    return str(getattr(response, "text", "") or "")[:200] or "未知错误"
