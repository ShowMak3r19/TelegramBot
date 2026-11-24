"""MagnetBoard（sehuatang-crawler）适配层：登录并调用「数据交换中心 → 导入数据」接口。

接口来自其前端：POST /api/auth/login（Cookie 会话）与 POST /api/data/import（multipart）。
功能模块只依赖 import_csv_sync，便于替换为直连数据库等其他实现。
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from telegram_bot.shared.net import ensure_http_url

logger = logging.getLogger(__name__)


class MagnetBoardError(RuntimeError):
    pass


# 与 /api/data/export 导出的表头一致；导入时 id 不能为空但会被忽略（入库使用自增 id），按 url 去重
CSV_COLUMNS = (
    "id,title,content,url,images,magnets,code,size,is_uncensored,author,forum_id,forum_type,magnet_hash,"
    "published_at,created_at,source_site,duration,resolution,format,language,subtitles,cover_url,"
    "local_cover_path,screenshot_urls,local_screenshot_paths,poster_urls,tags,categories,download_count,"
    "view_count,rating,in_emby,emby_item_id,emby_checked_at,image_download_status,image_retry_count,"
    "image_last_attempt_at,image_error_message,is_downloaded"
).split(",")
_CSV_DEFAULTS = {"images": "[]", "is_uncensored": "False", "subtitles": "False", "is_downloaded": "False"}


def write_import_csv(rows: Iterable[dict[str, Any]], path: Path, columns: list[str] | None = None) -> int:
    """按 MagnetBoard 导出格式写 CSV，未给出的列用默认值/留空，返回行数。columns 默认为 CSV_COLUMNS。"""
    count = 0
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns or CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            data = {**_CSV_DEFAULTS, **row}
            for key in ("magnets", "images", "tags"):
                if isinstance(data.get(key), list):
                    data[key] = json.dumps(data[key], ensure_ascii=False)
            writer.writerow(data)
            count += 1
    return count


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
        headers = _login(client, base, username, password)
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


def import_resource_csv_sync(
    base_url: str,
    username: str,
    password: str,
    file_path: Path,
    file_name: str,
    *,
    update_existing: bool = False,
    timeout: float = 1800.0,
    poll_seconds: float = 2.0,
    sleep: Any = None,
) -> dict[str, Any]:
    """外部来源资源导入（2026-10-26 起的 MagnetBoard 新接口）：提交导入任务并等待完成。

    与 /api/data/import 相比：会写 forum_name 并由服务端计算 import_identity，支持 update_existing
    更新已有记录；auto_push=false 即“仅入库，不自动推送”。返回 {"success": True, "data": stats}。
    """
    import time
    import uuid

    import httpx

    wait = sleep or time.sleep
    base = ensure_http_url(base_url).rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0), follow_redirects=False) as client:
        headers = _login(client, base, username, password)
        params = {
            "submission_key": uuid.uuid4().hex,  # 防止同一次提交被重复创建
            "update_existing": "true" if update_existing else "false",
            "auto_push": "false",
        }
        with Path(file_path).open("rb") as fh:
            response = client.post(
                f"{base}/api/data/import-jobs",
                params=params,
                headers=headers,
                files={"file": (file_name, fh, "text/csv")},
            )
        job = _json_or_empty(response)
        if response.status_code >= 400 or not job.get("id"):
            raise MagnetBoardError(f"MagnetBoard 创建导入任务失败（{response.status_code}）：{_error_text(job, response)}")
        deadline = time.monotonic() + timeout
        while True:
            status = job.get("status")
            if status == "completed":
                return {"success": True, "data": job.get("stats") or {}}
            if status in {"failed", "cancelled", "canceled", "aborted", "error"}:
                stats = job.get("stats") or {}
                detail = stats.get("message") or json.dumps(stats.get("errors") or [], ensure_ascii=False)[:200]
                raise MagnetBoardError(f"MagnetBoard 导入任务{status}：{detail}")
            if time.monotonic() > deadline:
                raise MagnetBoardError(f"MagnetBoard 导入任务超时（{job.get('id')}）")
            wait(poll_seconds)
            result = client.get(f"{base}/api/data/import-jobs/{job['id']}", headers=headers)
            payload = _json_or_empty(result)
            if result.status_code >= 400 or payload.get("success") is False:
                raise MagnetBoardError(f"MagnetBoard 查询导入进度失败（{result.status_code}）：{_error_text(payload, result)}")
            # 实测直接返回任务对象；前端代码按 {success, data} 取，两种都兼容
            job = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if not job.get("id"):
                raise MagnetBoardError("MagnetBoard 导入进度返回格式无法识别")


def enrich_images_sync(
    base_url: str,
    username: str,
    password: str,
    rows: list[dict[str, Any]],
    *,
    exclude_source: str,
    timeout: float = 30.0,
    workers: int = 4,
) -> dict[str, int]:
    """按番号给 rows 补 cover_url/images（就地修改）：先复用库内其他来源同番号记录的图，再查 JavDB 封面。

    单条查询失败只跳过该条，不影响导入。返回 {"local": n, "javdb": n, "missing": n}。
    """
    import httpx

    from concurrent.futures import ThreadPoolExecutor

    stats = {"local": 0, "javdb": 0, "missing": 0}
    base = ensure_http_url(base_url).rstrip("/")
    codes = sorted({str(row.get("code") or "").strip().upper() for row in rows} - {""})
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False) as client:
        headers = _login(client, base, username, password)
        # 本地按番号搜索单次约 2 秒，全量时并发查询
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            found_by_code = dict(zip(codes, pool.map(lambda code: _find_images(client, base, headers, code, exclude_source), codes)))
        for row in rows:
            found = found_by_code.get(str(row.get("code") or "").strip().upper())
            if found is None:
                stats["missing"] += 1
                continue
            source, row["cover_url"], images = found
            row["images"] = json.dumps(images, ensure_ascii=False)
            stats[source] += 1
    return stats


def _find_images(client: Any, base: str, headers: dict[str, str], code: str, exclude_source: str) -> tuple[str, str, list[str]] | None:
    """返回 (来源 local/javdb, 封面, 图片列表)。"""
    try:
        response = client.get(f"{base}/api/magnets", params={"q": code, "page": 1, "page_size": 20}, headers=headers)
        items = ((_json_or_empty(response).get("data") or {}).get("data")) or []
        for item in items:
            if not isinstance(item, dict) or str(item.get("code") or "").upper() != code.upper():
                continue
            if item.get("source_site") == exclude_source or not item.get("cover_url"):
                continue
            images = item.get("images") if isinstance(item.get("images"), list) else []
            return "local", str(item["cover_url"]), [str(url) for url in images if url] or [str(item["cover_url"])]
    except Exception:
        logger.warning("MagnetBoard local image lookup failed for %s", code, exc_info=True)
    try:
        response = client.get(f"{base}/api/javdb/search/movies", params={"keyword": code, "limit": 5}, headers=headers)
        payload = _json_or_empty(response)
        movies = (payload.get("data") or {}).get("movies") or payload.get("movies") or []
        for movie in movies:
            if isinstance(movie, dict) and str(movie.get("number") or "").upper() == code.upper() and movie.get("cover_url"):
                return "javdb", str(movie["cover_url"]), [str(movie["cover_url"])]
    except Exception:
        logger.warning("MagnetBoard JavDB lookup failed for %s", code, exc_info=True)
    return None


def export_csv_sync(
    base_url: str,
    username: str,
    password: str,
    *,
    source_site: str,
    timeout: float = 300.0,
) -> str:
    """调用「数据交换中心 → 导出数据」，返回指定来源的 CSV 文本。"""
    import httpx

    base = ensure_http_url(base_url).rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False) as client:
        headers = _login(client, base, username, password)
        response = client.post(f"{base}/api/data/export", json={"source_site": source_site}, headers=headers)
        if response.status_code >= 400:
            raise MagnetBoardError(f"MagnetBoard 导出失败（{response.status_code}）：{_error_text(_json_or_empty(response), response)}")
        return response.content.decode("utf-8-sig")


def delete_source_records_sync(
    base_url: str,
    username: str,
    password: str,
    *,
    source_site: str,
    timeout: float = 300.0,
    chunk: int = 200,
    url_prefix: str = "",
) -> int:
    """删除某来源的全部记录（导入接口不支持更新已有记录，重建时先删后导）。返回删除条数。

    记录 id 取自导出 CSV，只删 source_site 匹配的行；给了 url_prefix 时只删 url 以它开头的行
    （频道来源，不动同来源的 AVDB 记录）。
    """
    import httpx

    if not source_site or source_site in {"sehuatang", "agaghhh"}:
        raise MagnetBoardError(f"拒绝删除来源 {source_site!r} 的记录")
    base = ensure_http_url(base_url).rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False) as client:
        headers = _login(client, base, username, password)
        response = client.post(f"{base}/api/data/export", json={"source_site": source_site}, headers=headers)
        if response.status_code >= 400:
            raise MagnetBoardError(f"MagnetBoard 导出失败（{response.status_code}）")
        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
        ids = [
            int(row["id"])
            for row in reader
            if row.get("source_site") == source_site
            and (row.get("url") or "").startswith(url_prefix)
            and str(row.get("id") or "").isdigit()
        ]
        _batch_delete(client, base, headers, ids, chunk)
        return len(ids)


def delete_records_sync(
    base_url: str,
    username: str,
    password: str,
    record_ids: list[int],
    *,
    timeout: float = 300.0,
) -> int:
    """按 MagnetBoard 记录 id 批量删除，返回请求删除的条数。"""
    import httpx

    if not record_ids:
        return 0
    base = ensure_http_url(base_url).rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False) as client:
        headers = _login(client, base, username, password)
        _batch_delete(client, base, headers, [int(item) for item in record_ids], 200)
    return len(record_ids)


def _batch_delete(client: Any, base: str, headers: dict[str, str], ids: list[int], chunk: int) -> None:
    for start in range(0, len(ids), chunk):
        result = client.post(f"{base}/api/magnets/batch-delete", json={"record_ids": ids[start : start + chunk]}, headers=headers)
        payload = _json_or_empty(result)
        if result.status_code >= 400 or payload.get("success") is False:
            raise MagnetBoardError(f"MagnetBoard 批量删除失败（{result.status_code}）：{_error_text(payload, result)}")


def _login(client: Any, base: str, username: str, password: str) -> dict[str, str]:
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
    return headers


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
