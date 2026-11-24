"""解析频道里"番号 标题 + 简介 + ed2k/magnet 链接"格式的资源帖。

番号按 MagnetBoard 的写法规范化：去掉数字前缀（259LUXU-1835 → LUXU-1835），
FC2 统一为 FC2PPV-xxxx，无横杠的文件名写法补齐（ssni056 → SSNI-056）。
文件名/标题带修复/破解标记（restored、restore、LTX、-U、破解、_PJ）视为无码破解。

example_channel 格式（2026-11）：`🎬 标题` / `#LTX #番号 #98T ...` / ed2k / `#发布_时间`。
番号取自标签，title 去掉开头符号和番号前缀，其余标签（去掉 LTX、番号、发布_*）写入 tags，与 AVDB 记录一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ED2K_RE = re.compile(r"ed2k://\|file\|[^|\r\n]+\|\d+\|[0-9A-Fa-f]{32}\|(?:[^\s|]*\|)*/?", re.IGNORECASE)
_MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[^\s\"'<>]+", re.IGNORECASE)
_FC2_RE = re.compile(r"FC2[-_ ]?PPV[-_ ]?(\d{5,8})", re.IGNORECASE)
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])\d{0,4}([A-Za-z]{2,8})-(\d{2,6})(?![0-9])")
# 文件名里常见的无横杠写法：ssni056、mide307
_COMPACT_CODE_RE = re.compile(r"(?<![A-Za-z0-9])\d{0,4}([A-Za-z]{2,8})(\d{3,5})(?![0-9])")
_ED2K_HASH_RE = re.compile(r"ed2k://\|file\|[^|\r\n]+\|\d+\|([0-9A-Fa-f]{32})\|", re.IGNORECASE)
_BTIH_RE = re.compile(r"magnet:\?xt=urn:btih:([0-9A-Za-z]{32,40})", re.IGNORECASE)
_LEADING_SYMBOLS_RE = re.compile(r"^[^\w\[【(（「『～〜]+")
_HASHTAG_LINE_RE = re.compile(r"^#\S+(?:\s+#\S+)*$")
_SKIP_TAGS = {"ltx"}
_UNCENSORED_RE = re.compile(r"restored?|ltx|破解|[-_](?:u|pj)(?=[-_.\s]|$)", re.IGNORECASE)


@dataclass
class MagnetPost:
    code: str
    title: str
    content: str
    links: list[str] = field(default_factory=list)
    size_bytes: int = 0
    is_uncensored: bool = False
    link_hashes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def parse_magnet_post(text: str) -> MagnetPost | None:
    """没有 ed2k/magnet 链接的消息返回 None。"""
    text = text or ""
    links = _unique([m.group(0) for m in _ED2K_RE.finditer(text)] + [m.group(0) for m in _MAGNET_RE.finditer(text)])
    if not links:
        return None
    body_lines = [line.strip() for line in text.splitlines()]
    body_lines = [line for line in body_lines if line and not _is_link_line(line)]
    # 标签行（整行都是 #xxx）：番号和 tags 的来源，不进 title/content
    hashtags = _unique([tag for line in body_lines if _HASHTAG_LINE_RE.match(line) for tag in line.replace("#", " ").split()])
    body_lines = [line for line in body_lines if not _HASHTAG_LINE_RE.match(line)]
    file_names = [_ed2k_name(link) for link in links if link.lower().startswith("ed2k://")]

    title = body_lines[0] if body_lines else (file_names[0] if file_names else "")
    title = _LEADING_SYMBOLS_RE.sub("", title)  # 去掉 "🔗 SONE-164"、"🎬 标题" 这类开头符号
    content = "\n".join(body_lines[1:])
    tag_codes = [extract_code(tag) for tag in hashtags if not tag.startswith("发布_")]
    code = next((item for item in tag_codes if item), "")
    tags = [
        tag for tag in hashtags
        if tag.lower() not in _SKIP_TAGS and not tag.startswith("发布_") and extract_code(tag) != code
    ]
    if code and " " in title and extract_code(title.split(" ", 1)[0]) == code:
        title = title.split(" ", 1)[1].strip()  # 标签已给出番号："MIDA-837 标题" → "标题"
    if not code:
        code = extract_code(title) if body_lines else ""
    if not code:
        for name in file_names:
            code = extract_code(name, allow_compact=True)
            if code:
                break
    uncensored = any(_UNCENSORED_RE.search(name) for name in [title, *file_names])
    return MagnetPost(
        code=code,
        title=title[:500],
        content=content,
        links=links,
        size_bytes=_ed2k_size(links),
        is_uncensored=uncensored,
        link_hashes=link_hashes(text),
        tags=tags,
    )


def link_hashes(text: str) -> list[str]:
    """文本里所有 ed2k 文件 hash 和磁力 btih（小写），用于判断"同一个文件"。"""
    hashes = [f"ed2k:{m.group(1).lower()}" for m in _ED2K_HASH_RE.finditer(text or "")]
    hashes += [f"btih:{m.group(1).lower()}" for m in _BTIH_RE.finditer(text or "")]
    return _unique(hashes)


def primary_file_hash(text: str) -> str:
    """momo 口径的 magnet_hash：第一个 ed2k 的 MD4（小写 32 位）；没有 ed2k 时取第一个磁力 btih（小写）。

    momo 按 (magnet_hash, source_site) 唯一去重（2026-11-06 实测 url 不同也会跳过），
    其他来源（如 ltx_watch）写的是真实 MD4，所以本项目写入/导出的 ltx 记录统一用它。
    """
    match = _ED2K_HASH_RE.search(text or "")
    if match:
        return match.group(1).lower()
    match = _BTIH_RE.search(text or "")
    return match.group(1).lower() if match else ""


def normalize_magnet_hash(row: dict, sources: set[str] | frozenset[str]) -> bool:
    """row 来源在 sources 内且能从 magnets 取到文件 hash 时，把 magnet_hash 改成 momo 口径，返回是否改动。"""
    if row.get("source_site") not in sources:
        return False
    magnets = row.get("magnets")
    file_hash = primary_file_hash("\n".join(magnets) if isinstance(magnets, list) else str(magnets or ""))
    if not file_hash or row.get("magnet_hash") == file_hash:
        return False
    row["magnet_hash"] = file_hash
    return True


def extract_code(text: str, *, allow_compact: bool = False) -> str:
    text = text or ""
    if allow_compact:
        # 文件名：去掉 www.98T.la@ 站点前缀和 [LTX] 这类标签
        text = re.sub(r"\[[^\]]*\]", " ", re.sub(r"^.*@", "", text))
    fc2 = _FC2_RE.search(text)
    if fc2:
        return f"FC2PPV-{fc2.group(1)}"
    match = _CODE_RE.search(text)
    if match:
        return f"{match.group(1).upper()}-{match.group(2)}"
    if allow_compact:
        match = _COMPACT_CODE_RE.search(text)
        if match:
            return f"{match.group(1).upper()}-{match.group(2)}"
    return ""


def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return ""
    gb = size_bytes / 1024**3
    return f"{gb:.2f} GB" if gb >= 1 else f"{size_bytes / 1024**2:.2f} MB"


def _is_link_line(line: str) -> bool:
    lower = line.lower()
    return lower.startswith("ed2k://") or lower.startswith("magnet:?")


def _ed2k_name(link: str) -> str:
    parts = link.split("|")
    return parts[2] if len(parts) > 2 else ""


def _ed2k_size(links: list[str]) -> int:
    for link in links:
        parts = link.split("|")
        if link.lower().startswith("ed2k://") and len(parts) > 3 and parts[3].isdigit():
            return int(parts[3])
    return 0


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
