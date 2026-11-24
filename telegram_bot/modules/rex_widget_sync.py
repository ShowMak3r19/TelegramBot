from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from telegram_bot.config import RexWidgetSyncConfig, rex_widget_sync_config_from_dict
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.rex_hub_api import RexHubClient
from telegram_bot.shared.rex_widget_post import WidgetPost, code_version, is_newer, parse_widget_post
from telegram_bot.shared.telegram_io import atomic_write_text, is_edited_event

from .base import ModuleCard

logger = logging.getLogger(__name__)

HistoryReader = Callable[..., AsyncIterator[Any]]
HubFactory = Callable[[RexWidgetSyncConfig], Any]
_HISTORY_LIMIT = 50
_FOREIGN_ENC = re.compile(rb"^(?:\xef\xbb\xbf)?\s*FWENC\w*\s*$")  # Forward 加密格式，Rex 无法解密


class _Skip(Exception):
    pass


def _is_rexenc(data: bytes) -> bool:
    return bytes(data[:16]).lstrip(b"\xef\xbb\xbf").split(b"\n", 1)[0].strip() == b"REXENC"


_LINK = re.compile(r"https?://t\.me/(?:c/(\d+)|([A-Za-z]\w{3,}))/(\d+)")


@dataclass
class Candidate:
    message_id: int       # 频道帖子 id（游标用）
    source: Any           # 实际带文件的消息（可能是帖子里链接指向的消息）
    post: WidgetPost
    size: int


def _default_hub(config: RexWidgetSyncConfig) -> RexHubClient:
    return RexHubClient(config.hub_base_url, config.hub_password, timeout=config.request_timeout_seconds)


class RexWidgetSyncModule:
    """监听 REX 模块分享频道，把新模块/新版本同步到 Rex Widget Hub 并加入指定合集。

    身份：文件名去版本后的 key（加密模块 Hub 只认完整文件名，每版文件名都变）；
    本地 state 记录 key → Hub 模块 id/版本，丢失时按 Hub 模块文件名的 key 兜底匹配。
    更新判定：双方都有版本号时只在版本更高时替换；任一方无版本号时按内容 hash 判断。
    """

    def __init__(
        self,
        card: ModuleCard,
        config: RexWidgetSyncConfig,
        project_root: Path | None = None,
        *,
        hub_factory: HubFactory = _default_hub,
    ) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root or Path.cwd()
        self._hub_factory = hub_factory
        self.history_reader: HistoryReader | None = None
        self._state = self._load_state()
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._scan_task: asyncio.Task | None = None
        self._scanning = False
        self._running = False
        self._sync_card_config()
        self._refresh_metrics()

    # ---- 生命周期 ----
    def set_history_reader(self, reader: HistoryReader) -> None:
        self.history_reader = reader

    async def start(self) -> None:
        self._running = True
        self.card.status = "running"
        self._sync_chat()
        if int(self._state.get("last_message_id", 0)) > 0:
            self.request_scan(full=False)  # 只补漏；首次启用不自动回溯，由后台手动全量

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks) + ([self._scan_task] if self._scan_task else [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._scan_task = None
        self._scanning = False
        self.card.status = "stopped"
        self._refresh_metrics()

    async def wait_idle(self) -> None:
        while self._tasks or (self._scan_task and not self._scan_task.done()):
            await asyncio.gather(*list(self._tasks), *([self._scan_task] if self._scan_task else []), return_exceptions=True)

    @property
    def scanning(self) -> bool:
        return self._scanning

    # ---- 消息入口 ----
    async def handle_message(self, event: Any) -> HandlerResult:
        if is_edited_event(event):
            return HandlerResult.ignored(self.card.id)
        message = getattr(event, "message", event)
        chat_id = str(getattr(message, "chat_id", getattr(event, "chat_id", "")) or "")
        if not self.config.channel_chat or chat_id != self.config.channel_chat:
            return HandlerResult.ignored(self.card.id)
        message_id = int(getattr(message, "id", 0) or 0)
        caption = str(getattr(message, "message", None) or getattr(message, "text", "") or "")
        has_candidate = self._file_ok(message) or (self.config.follow_links and _LINK.search(caption) is not None)
        if not has_candidate:
            if not self._scanning:
                self._advance(message_id, failed=False)
            return HandlerResult.ignored(self.card.id)
        task = asyncio.create_task(self._process_live(message, message_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return HandlerResult.handled(self.card.id, "rex widget post queued", {"message_id": message_id})

    def request_scan(self, *, full: bool) -> bool:
        """full=True 从频道第一条开始；否则从上次游标补漏。已在扫描或不可用时返回 False。"""
        if not self._running or self.history_reader is None or self.scanning or (
            self._scan_task is not None and not self._scan_task.done()
        ):
            return False
        self._sync_chat()
        if full:
            min_id = 0
        else:
            min_id = int(self._state.get("last_message_id", 0))
            pending = int(self._state.get("pending_from", 0))
            if pending:
                min_id = min(min_id, pending - 1)
        loop = asyncio.get_running_loop()
        self._scan_task = loop.create_task(self._scan(min_id, full))
        self._scanning = True
        self._refresh_metrics()
        return True

    async def _process_live(self, message: Any, message_id: int) -> None:
        try:
            candidates = await self._extract(message)
            failed = await self._apply(candidates) if candidates else 0
            if not self._scanning or failed:
                self._advance(message_id, failed=bool(failed), advance_cursor=not self._scanning)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Rex widget sync failed for message %s", message_id)
            self._advance(message_id, failed=True, advance_cursor=not self._scanning)
            self._log("failed", f"#{message_id}", str(exc)[:200])

    async def _scan(self, min_id: int, full: bool) -> None:
        label = "全量同步" if full else "补漏"
        best: dict[str, Candidate] = {}
        scanned = 0
        max_id = min_id
        pending_before = int(self._state.get("pending_from", 0))
        try:
            assert self.history_reader is not None
            async for message in self.history_reader(self.config.channel_chat, min_id=min_id):
                scanned += 1
                max_id = max(max_id, int(getattr(message, "id", 0) or 0))
                for cand in await self._extract(message):
                    current = best.get(cand.post.key)
                    # 同一模块只保留最新一版：版本更高者胜；任一方无版本号时取更晚的帖子
                    if (
                        current is None
                        or not (current.post.version and cand.post.version)
                        or not is_newer(current.post.version, cand.post.version)
                    ):
                        best[cand.post.key] = cand
            ordered = sorted(best.values(), key=lambda c: c.message_id)
            failed = await self._apply(ordered) if ordered else 0
            if max_id > min_id:
                self._advance(
                    max_id,
                    failed=bool(failed),
                    earliest=min_id + 1,
                    expected_pending=pending_before,
                )
            elif not failed and pending_before and int(self._state.get("pending_from", 0)) == pending_before:
                self._state.pop("pending_from", None)
                self._save_state()
            self._log("scan", label, f"扫描 {scanned} 条，候选 {len(ordered)} 个模块，失败 {failed}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Rex widget %s failed", label)
            self._log("failed", label, str(exc)[:200])
        finally:
            self._scanning = False
            self._refresh_metrics()

    # ---- 解析 ----
    async def _extract(self, message: Any) -> list[Candidate]:
        message_id = int(getattr(message, "id", 0) or 0)
        caption = str(getattr(message, "message", None) or getattr(message, "text", "") or "")
        sources: list[Any] = []
        if self._file_ok(message):
            sources.append(message)
        elif self.config.follow_links:
            sources.extend(await self._linked_files(message, caption))
        ignored = set(self.config.ignore_keys)
        result = []
        for source in sources:
            file = getattr(source, "file", None)
            post = parse_widget_post(str(getattr(file, "name", "") or ""), caption)
            if post.key in ignored:
                continue
            result.append(
                Candidate(message_id=message_id, source=source, post=post, size=int(getattr(file, "size", 0) or 0))
            )
        return result

    def _file_ok(self, message: Any) -> bool:
        file = getattr(message, "file", None)
        name = str(getattr(file, "name", "") or "")
        if not name:
            return False
        try:
            if not re.search(self.config.file_name_pattern, name, re.IGNORECASE):
                return False
            if self.config.exclude_name_pattern and re.search(self.config.exclude_name_pattern, name, re.IGNORECASE):
                return False
        except re.error:
            logger.warning("Invalid rex widget file name pattern")
            return False
        size = int(getattr(file, "size", 0) or 0)
        return size <= self.config.max_file_size_mb * 1024 * 1024

    async def _linked_files(self, message: Any, caption: str) -> list[Any]:
        """帖子没附件但给了 t.me 消息链接（如「模块地址：https://t.me/c/…/…」）时，取链接消息里的文件。"""
        client = getattr(message, "client", None)
        if client is None or not hasattr(client, "get_messages"):
            return []
        lines = [line for line in caption.splitlines() if _LINK.search(line)]
        preferred = [line for line in lines if "模块" in line] or lines
        found = []
        rpc_calls = 0
        for line in preferred[:3]:
            for match in _LINK.finditer(line):
                if rpc_calls >= 3:
                    return found[:3]
                rpc_calls += 1
                internal, username, msg_id = match.groups()
                entity: Any = int(f"-100{internal}") if internal else username
                try:
                    linked = await client.get_messages(entity, ids=int(msg_id))
                except Exception:
                    logger.info("Rex widget linked message unavailable: %s", match.group(0))
                    continue
                if linked is not None and self._file_ok(linked):
                    found.append(linked)
        return found[:3]

    # ---- 同步到 Hub ----
    async def _apply(self, candidates: list[Candidate]) -> int:
        """返回失败数。Hub 操作串行执行，避免同一模块并发替换。"""
        if not self.config.hub_password:
            for cand in candidates:
                self._log("failed", cand.post.title, "未配置 Hub 管理密码")
            return len(candidates)
        failed = 0
        async with self._lock:
            hub = await asyncio.to_thread(self._hub_factory, self.config)
            try:
                modules = await asyncio.to_thread(hub.list_modules)
                collection = await asyncio.to_thread(hub.find_collection, self.config.collection_slug)
                members = set(collection.get("moduleIds") or [])
                by_id = {str(m.get("id")): m for m in modules}
                for cand in candidates:
                    try:
                        await self._apply_one(hub, cand, by_id, members, str(collection.get("id")))
                        self._save_state()
                    except asyncio.CancelledError:
                        raise
                    except _Skip as exc:
                        self._log("skipped", cand.post.title, f"#{cand.message_id} {cand.post.filename}：{exc}")
                    except Exception as exc:
                        failed += 1
                        logger.warning("Rex widget sync failed: %s", cand.post.filename, exc_info=True)
                        self._log("failed", cand.post.title, f"#{cand.message_id} {cand.post.filename}：{str(exc)[:200]}")
            finally:
                await asyncio.to_thread(hub.close)
        self._save_state()
        return failed

    async def _apply_one(self, hub: Any, cand: Candidate, by_id: dict[str, dict], members: set, collection_id: str) -> None:
        post = cand.post
        entries = self._entries()
        entry = entries.get(post.key) or {}
        target = by_id.get(str(entry.get("hub_id") or ""))
        if target is None:
            entry = {}
            target = self._match_hub(post.key, by_id)
        current_version = str(entry.get("version") or (target or {}).get("version") or "")

        content = await self._download(cand)
        encrypted = _is_rexenc(content)
        if not encrypted:
            # 未加密模块以代码 WidgetMetadata 为准：Hub 和 Rex 都按代码里的 id/version 校验，
            # 文案里的版本常与代码不一致（1.0 vs 1.0.0），不能拿来覆盖
            post = cand.post = replace(post, version=code_version(content))
        if target is not None:
            if post.version and current_version:
                if not is_newer(post.version, current_version):
                    await asyncio.to_thread(self._ensure_member, hub, members, collection_id, str(target["id"]))
                    self._log("skipped", post.title, f"v{post.version} 不高于已有 v{current_version}")
                    return
            else:
                digest = hashlib.sha256(content).hexdigest()
                if digest in {entry.get("hash"), target.get("content_hash")}:
                    await asyncio.to_thread(self._ensure_member, hub, members, collection_id, str(target["id"]))
                    self._log("skipped", post.title, "内容未变化")
                    return
        if target is None:
            result = await asyncio.to_thread(hub.upload_new, post.filename, content, group_id=self.config.group_id)
            action = "added" if result.get("status") == "added" else "updated"
        else:
            old_module_id = str(target["id"])
            subscribed = bool(target.get("source_managed") or target.get("source_url"))
            result = await asyncio.to_thread(
                hub.replace, old_module_id, post.filename, content, mode="manual" if subscribed else ""
            )
            action = "updated"
            if not encrypted:
                result = await asyncio.to_thread(
                    self._rebuild_if_id_changed, hub, str(result["module_id"]), post, content, members, by_id
                )
        module_id = str(result["module_id"])
        if encrypted:
            # 只有加密模块 Hub 读不到元信息，才用帖子标题/版本补；未加密模块保持 Hub 从代码读到的值
            await asyncio.to_thread(
                hub.update_meta, module_id, title=post.title, version=post.version, lock_title=self.config.lock_title
            )
        await asyncio.to_thread(self._ensure_member, hub, members, collection_id, module_id)
        by_id[module_id] = {"id": module_id, "filename": post.filename, "version": post.version,
                            "content_hash": hashlib.sha256(content).hexdigest()}
        entries[post.key] = {
            "hub_id": module_id,
            "version": post.version,
            "filename": post.filename,
            "title": post.title,
            "hash": hashlib.sha256(content).hexdigest(),
            "message_id": cand.message_id,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        counters = self._state.setdefault("counters", {})
        counters[action] = int(counters.get(action, 0)) + 1
        old = f"v{current_version} → " if action == "updated" and current_version else ""
        self._log(action, post.title, f"#{cand.message_id} {old}v{post.version or '?'}（{post.filename}）")

    def _rebuild_if_id_changed(
        self,
        hub: Any,
        module_id: str,
        post: WidgetPost,
        content: bytes,
        members: set,
        by_id: dict[str, dict] | None = None,
    ) -> dict:
        """Hub 替换文件时会更新 metadata_id（按代码解析），但对外的 widget_id 保持创建时的值。
        代码 id 变了时合集仍输出旧 id，Rex 会报模块信息校验失败，只能删掉重建。
        旧版是加密模块时 widget_id 就是 Hub uuid，换成明文后同样要重建。"""
        mod = next((m for m in hub.list_modules() if str(m.get("id")) == module_id), None)
        if not mod:
            return {"module_id": module_id}
        new_id, old_id = str(mod.get("metadata_id") or ""), str(mod.get("widget_id") or "")
        if not new_id or not old_id or old_id == new_id:
            return {"module_id": module_id}
        logger.info("Rex widget id changed %s -> %s, recreating %s", old_id, new_id, post.filename)
        hub.delete_module(module_id)
        members.discard(module_id)
        if by_id is not None:
            by_id.pop(module_id, None)
        return hub.upload_new(post.filename, content, group_id=self.config.group_id)

    def _ensure_member(self, hub: Any, members: set, collection_id: str, module_id: str) -> None:
        if module_id in members:
            return
        hub.append_to_collection(collection_id, module_id)
        members.add(module_id)

    def _match_hub(self, key: str, by_id: dict[str, dict]) -> dict | None:
        def hub_key(mod: dict) -> str:
            # Hub 里的版本号（本模块写入）帮助剥离 "anime1.2.1.0" 这类无分隔符的版本
            version = str(mod.get("version") or "")
            return parse_widget_post(str(mod.get("filename") or ""), f"v{version}" if version else "").key

        matches = [m for m in by_id.values() if hub_key(m) == key]
        return matches[0] if len(matches) == 1 else None

    async def _download(self, cand: Candidate) -> bytes:
        data = await cand.source.download_media(file=bytes)
        if not data:
            raise RuntimeError("下载文件失败")
        max_bytes = self.config.max_file_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise _Skip(f"文件大小超过 {self.config.max_file_size_mb} MB，已跳过")
        head = bytes(data).split(b"\n", 1)[0]
        if _FOREIGN_ENC.match(head):
            raise _Skip("Forward 加密格式（FWENC），Rex 不可用，已跳过")
        if not _is_rexenc(data) and b"WidgetMetadata" not in data:
            raise _Skip("没有 WidgetMetadata，不是 Rex 模块（可能是 Worker/工具脚本），已跳过")
        return bytes(data)

    # ---- 状态 ----
    def _sync_chat(self) -> None:
        if self._state.get("chat") == self.config.channel_chat:
            return
        for key in ("last_message_id", "pending_from"):
            self._state.pop(key, None)
        self._state["chat"] = self.config.channel_chat
        self._save_state()

    def _advance(
        self,
        message_id: int,
        *,
        failed: bool,
        earliest: int | None = None,
        advance_cursor: bool = True,
        expected_pending: int | None = None,
    ) -> None:
        if failed:
            first = earliest or message_id
            pending = int(self._state.get("pending_from", 0))
            self._state["pending_from"] = min(pending, first) if pending else first
        elif earliest is not None:
            current_pending = int(self._state.get("pending_from", 0))
            if current_pending and (
                expected_pending is None or current_pending == expected_pending or message_id >= current_pending
            ):
                self._state.pop("pending_from", None)  # 补漏/全量成功覆盖了之前失败的区间
        if advance_cursor and message_id > int(self._state.get("last_message_id", 0)):
            self._state["last_message_id"] = message_id
        self._save_state()
        self._refresh_metrics()

    def _entries(self) -> dict[str, Any]:
        if not isinstance(self._state.get("modules"), dict):
            self._state["modules"] = {}
        return self._state["modules"]

    def _log(self, status: str, title: str, detail: str) -> None:
        item = {"status": status, "title": title, "detail": detail, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        history = self._state.setdefault("history", [])
        history.insert(0, item)
        del history[_HISTORY_LIMIT:]
        self._state["last"] = item
        logger.info("Rex widget sync %s: %s %s", status, title, detail)
        self._refresh_metrics()

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.project_root / path

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self._resolve(self.config.state_store).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self) -> None:
        path = self._resolve(self.config.state_store)
        try:
            atomic_write_text(path, json.dumps(self._state, ensure_ascii=False, indent=2))
        except OSError:
            logger.warning("Failed to save rex widget sync state", exc_info=True)

    def _refresh_metrics(self) -> None:
        counters = self._state.get("counters") or {}
        self.card.metrics = {
            "added": int(counters.get("added", 0)),
            "updated": int(counters.get("updated", 0)),
            "tracked": len(self._state.get("modules") or {}),
            "last_message_id": int(self._state.get("last_message_id", 0)),
            "pending_from": int(self._state.get("pending_from", 0)),
            "scanning": self.scanning,
            "last": self._state.get("last") or {},
            "history": list(self._state.get("history") or [])[:20],
        }

    # ---- 配置 ----
    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("rex_widget_sync", values)
        if not isinstance(data, dict):
            return
        data = dict(data)
        if not str(data.get("hub_password") or ""):
            data.pop("hub_password", None)  # 后台不回显密码，留空表示保持原值
        prev_chat = self.config.channel_chat
        self.config = rex_widget_sync_config_from_dict({**asdict(self.config), **data})
        if self.config.channel_chat != prev_chat:
            self._sync_chat()
        self._sync_card_config()
        self._refresh_metrics()

    def _sync_card_config(self) -> None:
        config = asdict(self.config)
        config["hub_password"] = ""
        config["has_hub_password"] = bool(self.config.hub_password)
        self.card.config = config
