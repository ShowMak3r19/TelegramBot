from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def build_ai_usage_stats(path: Path, range_key: str = "today") -> dict[str, Any]:
    normalized = range_key if range_key in {"today", "7d", "30d", "all"} else "today"
    now = time.time()
    start_ts = _range_start(normalized, now)
    items: list[dict[str, Any]] = []

    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = float(item.get("ts") or now)
                if start_ts is not None and ts < start_ts:
                    continue
                item["ts"] = ts
                items.append(item)

    summary = {
        "requests": 0,
        "success": 0,
        "failed": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
        "total_latency_ms": 0,
        "avg_latency_ms": 0,
        "success_rate": 0,
        "rpm": 0,
        "tpm": 0,
    }
    models: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}
    series: dict[str, dict[str, Any]] = {}

    for item in items:
        success = bool(item.get("success", True))
        model_key = str(item.get("model") or "unknown")
        feature_key = str(item.get("feature") or "unknown")
        bucket_key = _bucket_key(float(item["ts"]), normalized)
        latency = _int(item.get("latency_ms"))
        input_tokens = _int(item.get("input_tokens") or item.get("prompt_tokens"))
        output_tokens = _int(item.get("output_tokens") or item.get("completion_tokens"))
        total_tokens = _int(item.get("total_tokens")) or input_tokens + output_tokens
        cached_tokens = _int(item.get("cached_tokens"))
        reasoning_tokens = _int(item.get("reasoning_tokens"))

        _add_row(summary, success, latency, input_tokens, output_tokens, total_tokens, cached_tokens, reasoning_tokens)
        _add_row(
            models.setdefault(model_key, _empty_row({"model": model_key})),
            success,
            latency,
            input_tokens,
            output_tokens,
            total_tokens,
            cached_tokens,
            reasoning_tokens,
        )
        _add_row(
            features.setdefault(feature_key, _empty_row({"feature": feature_key})),
            success,
            latency,
            input_tokens,
            output_tokens,
            total_tokens,
            cached_tokens,
            reasoning_tokens,
        )
        bucket = series.setdefault(bucket_key, {"bucket": bucket_key, "requests": 0, "total_tokens": 0})
        bucket["requests"] += 1
        bucket["total_tokens"] += total_tokens

    _finish_row(summary, now, start_ts)
    for row in models.values():
        _finish_row(row, now, start_ts)
    for row in features.values():
        _finish_row(row, now, start_ts)

    return {
        "range": normalized,
        "summary": summary,
        "series": sorted(series.values(), key=lambda row: row["bucket"]),
        "models": sorted(models.values(), key=lambda row: row["total_tokens"], reverse=True),
        "features": sorted(features.values(), key=lambda row: row["total_tokens"], reverse=True),
    }


def _empty_row(extra: dict[str, Any]) -> dict[str, Any]:
    row = {
        "requests": 0,
        "success": 0,
        "failed": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
        "total_latency_ms": 0,
        "avg_latency_ms": 0,
        "success_rate": 0,
        "rpm": 0,
        "tpm": 0,
    }
    row.update(extra)
    return row


def _add_row(
    row: dict[str, Any],
    success: bool,
    latency: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cached_tokens: int,
    reasoning_tokens: int,
) -> None:
    row["requests"] += 1
    row["success" if success else "failed"] += 1
    row["input_tokens"] += input_tokens
    row["output_tokens"] += output_tokens
    row["total_tokens"] += total_tokens
    row["cached_tokens"] += cached_tokens
    row["reasoning_tokens"] += reasoning_tokens
    row["total_latency_ms"] += latency


def _finish_row(row: dict[str, Any], now: float, start_ts: float | None) -> None:
    requests = max(int(row.get("requests") or 0), 0)
    if requests:
        row["avg_latency_ms"] = round(row["total_latency_ms"] / requests)
        row["success_rate"] = round((row["success"] / requests) * 100, 1)
    minutes = max(((now - (start_ts or now)) / 60), 1)
    row["rpm"] = round(row["requests"] / minutes, 2)
    row["tpm"] = round(row["total_tokens"] / minutes, 2)


def _range_start(range_key: str, now: float) -> float | None:
    if range_key == "today":
        local = time.localtime(now)
        return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, local.tm_wday, local.tm_yday, local.tm_isdst))
    if range_key == "7d":
        return now - 7 * 86400
    if range_key == "30d":
        return now - 30 * 86400
    return None


def _bucket_key(ts: float, range_key: str) -> str:
    fmt = "%H:%M" if range_key == "today" else "%m-%d"
    return time.strftime(fmt, time.localtime(ts))


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0
