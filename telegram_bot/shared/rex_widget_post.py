"""解析「REX 模块分享」频道帖子：从文件名 + 文案得出模块身份、版本和展示标题。

频道发的 .js 多为 REXENC 加密，读不到 WidgetMetadata，只能靠文件名和文案：
- 文件名常带版本号且每版不同（"pornhub 2.2.7.js"、"JAVASS-v1.0.9.js"），去掉版本后作为身份 key；
- 文案首几行写版本（"PornHub v2.2.7 模块"、"版本 v1.10.6"、"女同混合聚合（lesbian.mix）1.0.4"）。
文件名和文案版本不一致时取较高者（实测有帖子文案写旧版本号）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_VER = r"\d+(?:\.\d+)+"
_REX_TAG = re.compile(r"[\(（\[]\s*rex\s*[\)）\]]", re.IGNORECASE)
_LABELED = re.compile(rf"(?:版本|version|ver)\s*[:：]?\s*v?\s*({_VER})", re.IGNORECASE)
_V_PREFIX = re.compile(rf"(?<![A-Za-z])v\s?({_VER})", re.IGNORECASE)
_BARE = re.compile(rf"(?<![\w.])({_VER})(?![\w.])")
_FILE_SEP_VER = re.compile(rf"(?:[\s_\-]+v?|v)({_VER})[\s._\-]*$", re.IGNORECASE)
_FILE_LOOSE_VER = re.compile(rf"[\s._\-]*v?({_VER})[\s._\-]*$", re.IGNORECASE)
_TITLE_NOISE = re.compile(rf"(?<![A-Za-z])v?\s?{_VER}|模块|模組|更新日志|更新说明|更新内容|更新$", re.IGNORECASE)
# 版本号后常见的平台/构建后缀："AVDB 2.1.3-REX"、"AVDB 2.1.1 Rex版"、"Stripchat-v6.1.3-rexenc"、"xx.enc"
_SUFFIX_TAG = re.compile(r"[\s._\-]+(?:rex版|rexenc|rex|enc|stable)$", re.IGNORECASE)
_TRIM = " ._-·|:：,，"


@dataclass(frozen=True)
class WidgetPost:
    key: str          # 身份：去版本、去 (rex) 标记后的小写文件名
    filename: str     # 上传到 Hub 用的原文件名
    version: str      # 可能为空
    title: str        # Hub 展示标题


def parse_widget_post(filename: str, caption: str = "") -> WidgetPost:
    name = unicodedata.normalize("NFKC", filename or "").strip()
    stem = re.sub(r"\.js$", "", name, flags=re.IGNORECASE)
    stem = _strip_tags(_REX_TAG.sub(" ", stem))
    cap_version = caption_version(caption)

    file_version = ""
    if cap_version and stem.endswith(cap_version):
        file_version = cap_version
        stem = stem[: -len(cap_version)].rstrip(_TRIM)
        stem = re.sub(r"(?<![A-Za-z])v$", "", stem, flags=re.IGNORECASE)  # 只去独立的 v，保留 PubJAV 的 V
    else:
        match = _FILE_SEP_VER.search(stem) or _FILE_LOOSE_VER.search(stem)
        if match and match.start() > 0:
            file_version = match.group(1)
            stem = stem[: match.start()]
    stem = _strip_tags(stem)
    key = re.sub(r"\s+", " ", stem).lower() or name.lower()
    version = max_version(cap_version, file_version)
    return WidgetPost(key=key, filename=name, version=version, title=caption_title(caption) or stem or name)


def _strip_tags(stem: str) -> str:
    stem = stem.strip(_TRIM)
    while True:
        cleaned = _SUFFIX_TAG.sub("", stem).strip(_TRIM)
        if cleaned == stem or not cleaned:
            return stem
        stem = cleaned


_CODE_VERSION = re.compile(rb"WidgetMetadata[\s\S]{0,4000}?[\"']?\bversion[\"']?\s*:\s*[\"']([^\"'\r\n]{1,64})[\"']")


def code_version(content: bytes) -> str:
    """未加密模块：从 WidgetMetadata 的 version 字段取版本（只看前 256KB）。"""
    match = _CODE_VERSION.search(bytes(content[:262144]))
    if not match:
        return ""
    return match.group(1).decode("utf-8", errors="ignore").strip().lstrip("vV")


def caption_version(caption: str) -> str:
    lines = _lines(caption)[:6]
    for pattern in (_LABELED, _V_PREFIX):
        for line in lines:
            match = pattern.search(line)
            if match:
                return match.group(1)
    if lines:
        match = _BARE.search(lines[0])
        if match:
            return match.group(1)
    return ""


def caption_title(caption: str) -> str:
    lines = _lines(caption)
    if not lines:
        return ""
    title = _TITLE_NOISE.sub(" ", lines[0])
    title = re.sub(r"#\S+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(_TRIM)
    if not title or len(title) > 40 or "http" in title.lower():
        return ""
    return title


def version_tuple(version: str) -> tuple[int, ...]:
    cleaned = str(version or "").strip().lstrip("vV")
    if not cleaned or not re.fullmatch(_VER + r"|\d+", cleaned):
        return ()
    parts = [int(p) for p in cleaned.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def max_version(*versions: str) -> str:
    valid = [v for v in versions if version_tuple(v)]
    return max(valid, key=version_tuple) if valid else ""


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _lines(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "")
    return [line.strip() for line in normalized.splitlines() if line.strip()]
