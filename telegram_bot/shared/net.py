from __future__ import annotations

import urllib.parse

ALLOWED_URL_SCHEMES = ("http", "https")


def ensure_http_url(url: str) -> str:
    """校验外部请求 URL 仅允许 http/https，阻断 file://、gopher:// 等危险 scheme。

    私网地址默认放行（兼容局域网自建服务场景），只做 scheme/host 强校验。
    返回去除首尾空白后的 URL，非法时抛 ValueError。
    """
    candidate = str(url or "").strip()
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"不允许的 URL scheme：{parsed.scheme or '(空)'}")
    if not parsed.netloc:
        raise ValueError("URL 缺少主机名")
    return candidate
