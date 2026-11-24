"""导入前的 CSV 校对：按 MagnetBoard 导出格式检查表头、丢坏行、文件内去重，再写成标准格式。

支持两类互斥格式：
- magnets（磁力主表）：用于自动监听与手动 /import，导入 /api/data/import。
- posts（色花综合帖子）：仅在 allow_posts=True（手动 /import）时允许，标准化为精确 20 列，导入 /api/posts/import。
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from telegram_bot.shared.magnet_post_parser import link_hashes, normalize_magnet_hash
from telegram_bot.shared.magnetboard_api import CSV_COLUMNS, POST_CSV_COLUMNS, write_import_csv, write_posts_csv

# 去重依据与 MagnetBoard 一致：url，或（url 为空时）magnet_hash + source_site，所以两者至少要有一列
REQUIRED_COLUMNS = ("title", "magnets")
DEDUPE_COLUMNS = ("url", "magnet_hash")
# 2026-10 起新版导出多出的列，文件里有就原样保留
EXTRA_COLUMNS = ("forum_name", "import_identity")
KNOWN_COLUMNS = (*CSV_COLUMNS, *EXTRA_COLUMNS)

# 色花综合帖子表（posts）判别规则：含 title + original_url + 至少一个帖子专属列，且不含磁力主表专属列
POST_REQUIRED_COLUMNS = ("title", "original_url")
POST_MARKER_COLUMNS = frozenset({
    "tid",
    "board_name",
    "board_id",
    "type_id",
    "type_name",
    "magnet_link",
    "preview_image",
    "attachments",
    "is_read",
    "is_locked",
    "subscription_id",
})
MAGNET_EXCLUSIVE_COLUMNS = frozenset({"magnets", "source_site", "magnet_hash"})
KNOWN_POST_COLUMNS = tuple(POST_CSV_COLUMNS)

BAD_REASONS = {
    "columns": "列数不符",
    "title": "缺标题",
    "magnets": "磁力格式错误",
    "no_link": "无磁力/链接",
    "original_url": "缺原帖链接",
}


class CsvFormatError(ValueError):
    pass


@dataclass
class CsvCheckResult:
    kind: str = "magnets"
    total: int = 0
    written: int = 0
    duplicates: int = 0
    bad: Counter = field(default_factory=Counter)
    unknown_columns: list[str] = field(default_factory=list)
    rehashed: int = 0

    @property
    def bad_total(self) -> int:
        return sum(self.bad.values())

    def describe(self) -> str:
        text = f"共 {self.total} 行，有效 {self.written} 行，文件内重复 {self.duplicates} 行，坏行 {self.bad_total} 行"
        if self.bad:
            text += "（" + "、".join(f"{BAD_REASONS.get(k, k)} {v}" for k, v in self.bad.most_common()) + "）"
        if self.rehashed:
            text += f"；magnet_hash 改为文件 MD4 {self.rehashed} 行"
        if self.unknown_columns:
            text += f"；忽略未知列：{', '.join(self.unknown_columns[:8])}"
            if len(self.unknown_columns) > 8:
                text += " 等"
        return text


def normalize_import_csv(
    src: Path,
    dest: Path,
    hash_sources: frozenset[str] = frozenset(),
    *,
    allow_posts: bool = False,
) -> CsvCheckResult:
    """校对 src 并把有效、去重后的行按导出格式写到 dest（无 BOM）。表头不合格抛 CsvFormatError。

    hash_sources 内来源的行，magnet_hash 改为 momo 口径的文件 MD4（第三方导出常填消息号/资源编号）。
    allow_posts=True 时同时识别色花综合帖子 CSV（posts），并规范化为 /api/posts/import 要求的精确 20 列。
    """
    csv.field_size_limit(2**31 - 1)  # 帖子正文可能很长
    result = CsvCheckResult()
    with Path(src).open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = [name.strip() for name in next(reader)]
        except StopIteration:
            raise CsvFormatError("文件是空的") from None
        except UnicodeDecodeError:
            raise CsvFormatError("不是 UTF-8 编码") from None
        kind = _check_header(header, result, allow_posts=allow_posts)
        try:
            if kind == "posts":
                result.written = write_posts_csv(_clean_post_rows(reader, header, result), dest)
            else:
                columns = [*CSV_COLUMNS, *(name for name in EXTRA_COLUMNS if name in header)]
                result.written = write_import_csv(_clean_rows(reader, header, result, hash_sources), dest, columns)
        except UnicodeDecodeError:
            raise CsvFormatError("不是 UTF-8 编码") from None
    return result


def _check_header(header: list[str], result: CsvCheckResult, *, allow_posts: bool = False) -> str:
    columns = set(header)
    if len(columns) != len(header):
        raise CsvFormatError("表头有重复列名")
    is_posts = (
        all(name in columns for name in POST_REQUIRED_COLUMNS)
        and bool(columns & POST_MARKER_COLUMNS)
        and not (columns & MAGNET_EXCLUSIVE_COLUMNS)
    )
    if is_posts:
        if not allow_posts:
            raise CsvFormatError("检测到色花综合帖子格式，自动监听仅支持磁力主表 CSV，请使用手动 /import 导入")
        result.kind = "posts"
        known = set(KNOWN_POST_COLUMNS)
        result.unknown_columns = [name for name in header if name not in known]
        return "posts"
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if not columns & set(DEDUPE_COLUMNS):
        missing.append(" 或 ".join(DEDUPE_COLUMNS))
    if missing:
        expected = "MagnetBoard 磁力或色花综合帖子导出格式" if allow_posts else "MagnetBoard 导出格式"
        raise CsvFormatError(f"缺少必需列：{', '.join(missing)}（需为{expected}）")
    result.kind = "magnets"
    known = set(KNOWN_COLUMNS)
    result.unknown_columns = [name for name in header if name not in known]
    return "magnets"


def _clean_rows(
    reader: Any, header: list[str], result: CsvCheckResult, hash_sources: frozenset[str] = frozenset()
) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    for values in reader:
        if not any(value.strip() for value in values):
            continue  # 空行不计数
        result.total += 1
        if len(values) != len(header):
            result.bad["columns"] += 1
            continue
        row = {name: value.strip() for name, value in zip(header, values) if name in KNOWN_COLUMNS}
        if not row.get("title"):
            result.bad["title"] += 1
            continue
        links = _parse_magnets(row.get("magnets", ""))
        if links is None:
            result.bad["magnets"] += 1
            continue
        url = row.get("url", "")
        if not links and not url:
            result.bad["no_link"] += 1
            continue
        probe = {"source_site": row.get("source_site"), "magnet_hash": row.get("magnet_hash"), "magnets": links}
        if normalize_magnet_hash(probe, hash_sources):
            row["magnet_hash"] = probe["magnet_hash"]
            result.rehashed += 1
        key = _dedupe_key(row, links)
        if key in seen:
            result.duplicates += 1
            continue
        seen.add(key)
        row["magnets"] = links
        row["id"] = row.get("id") or str(result.total)  # 导入接口要求 id 非空，值本身会被忽略
        # 空字符串会盖掉 write_import_csv 的默认值，交给它补
        yield {key: value for key, value in row.items() if value != ""}


def _parse_magnets(value: str) -> list[str] | None:
    """返回链接列表；JSON 写坏了返回 None。裸链接（换行/空白分隔）也接受。"""
    if not value:
        return []
    if value.startswith("["):
        try:
            data = json.loads(value)
        except ValueError:
            return None
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            return None
        return [item.strip() for item in data if item.strip()]
    parts = value.split()
    if all(part.lower().startswith(("magnet:", "ed2k:")) for part in parts):
        return parts
    return None


def _dedupe_key(row: dict[str, str], links: list[str]) -> str:
    """与 MagnetBoard 判重口径一致：同 url 为同一条；无 url 时按 magnet_hash + source_site。

    同一磁力出现在不同帖子（url 不同）是不同记录，不合并。两者都没有时退回按文件 hash/链接。
    """
    if row.get("url"):
        return f"url:{row['url']}"
    if row.get("magnet_hash"):
        return f"mh:{row.get('source_site', '')}:{row['magnet_hash']}"
    return "links:" + "|".join(sorted(link_hashes("\n".join(links)) or links))


def _clean_post_rows(reader: Any, header: list[str], result: CsvCheckResult) -> Iterator[dict[str, Any]]:
    known = set(KNOWN_POST_COLUMNS)
    seen: set[str] = set()
    for values in reader:
        if not any(value.strip() for value in values):
            continue  # 空行不计数
        result.total += 1
        if len(values) != len(header):
            result.bad["columns"] += 1
            continue
        row = {name: value.strip() for name, value in zip(header, values) if name in known}
        if not row.get("title"):
            result.bad["title"] += 1
            continue
        if not row.get("original_url"):
            result.bad["original_url"] += 1
            continue
        key = _post_dedupe_key(row)
        if key in seen:
            result.duplicates += 1
            continue
        seen.add(key)
        # 空字符串交给 write_posts_csv 补默认值（如 images/attachments/bool），其余保留原值
        yield {k: v for k, v in row.items() if v != ""}


def _post_dedupe_key(row: dict[str, str]) -> str:
    """与 MagnetBoard /api/posts/import 一致：tid（整数）优先，original_url 兜底去重。"""
    tid = _parse_int_str(row.get("tid", ""))
    if tid is not None:
        return f"tid:{tid}"
    return f"url:{row['original_url']}"


def _parse_int_str(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    try:
        return str(int(text))
    except ValueError:
        return None
