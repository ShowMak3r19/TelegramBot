from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from telegram_bot.config import AIConfig, TelegramConfig, UserProfileConfig, user_profile_config_from_dict
from telegram_bot.persistence import ChatHistoryStore
from telegram_bot.shared.ai_messages import (
    aclose_anthropic,
    anthropic_create_message,
    build_openai_chat_messages,
    collect_anthropic_text_and_sources,
    collect_chat_completions_text_and_sources,
    is_anthropic_provider,
    is_chat_completions_provider,
    make_async_anthropic_client,
)
from telegram_bot.shared.ai_responses import (
    AsyncOpenAI,
    collect_response_text_and_sources,
    extract_usage_counts,
)
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.telegram_io import (
    event_message,
    get_reply_message,
    is_edited_event,
    is_outgoing,
    message_text,
    safe_edit_message,
)

from .base import ModuleCard
from .user_profile_analytics import (
    ProfileAnalytics,
    compute_profile_analytics,
    filter_noise_samples,
    format_analytics_display_lines,
    format_analytics_for_prompt,
    format_sample_time_tag,
    select_informative_samples,
    with_resolved_peer_labels,
)

logger = logging.getLogger(__name__)

PROFILE_SYSTEM_PROMPT = """
你是 Telegram 群聊行为观察员，擅长从客观行为数据与真实发言中抓住一个人最鲜明的独特性、反差和群聊生态位。
安全边界：这是基于有限群聊样本的娱乐性观察，不是心理评估。不得推断健康、疾病、宗教、政治立场、性取向、族裔、财务状况、精确位置、犯罪倾向等敏感属性，不使用诊断性标签；不得编造原话、消息 ID、人际关系或样本外事实。
区分度铁律（极其重要）：
1. 必须通过“遮名测试”：如果把名字遮住，某句评价套到群里另一个普通群友身上也成立，就删掉重写！
2. 严禁万金油算命套话：禁止泛泛使用“表面高冷实则话痨”“隐形气氛组”“隐藏大佬”“嘴硬心软”“存在感强”“热爱生活/分享”“幽默风趣”“佛系”等空洞标签，除非紧跟无法替代的具体反差证据。
3. 必须结合【本地客观行为指纹】中的具体数据（作息、字数与群内百分位、回复/提问习惯、专属高频词、口头禅、互动搭子、跨群或跨时期反差），把数字和真实原话融进观察里。
4. 兴趣话题必须写到具体细分点（具体作品/工具/梗/习惯），禁止只写“日常闲聊”“科技数码”等空泛大类。
5. 评分必须依据行为指纹锚点拉开 1-5 星梯度，低于群平均就老实给 1-2 星，极端突出才给 5 星，禁止全员 4-5 星。
仅输出一个 JSON 对象，不要 Markdown、HTML、代码块或额外说明。
""".strip()

PROFILE_EXTRACT_SYSTEM_PROMPT = """
你是客观的群聊语料事实提取员。任务是从这一批消息中挖掘该用户最独特、最具体、可验证的行为线索与高能名场面，供后续全局画像汇总。
不要写空泛的人设评价或套话，要尽量保留具体名词、高频口头禅、互动姿态、争议/反差点以及最有辨识度的原话 message_id。
安全边界：不得推断健康、疾病、宗教、政治立场、性取向、族裔、财务状况、精确位置、犯罪倾向等敏感属性，不得编造不存在的 message_id 或样本外事实。
仅输出一个 JSON 对象，不要 Markdown、HTML、代码块或额外说明。
""".strip()

_JSON_SCHEMA = {
    "archetype": "6-16字专属群聊生态位称号（基于具体行为/作息/反差，拒绝泛泛外号）",
    "tagline": "一句话精准灵魂摘要（点破此人最独特的反差或执念）",
    "personality": [
        {"title": "有区分度的小标题", "analysis": "结合行为数据/专属词/具体例子的分析", "evidence_ids": [123]},
    ],
    "interests": [{"topic": "具体细分话题/执念", "detail": "样本中的具体表现与态度"}],
    "quotes": [{"message_id": 123, "comment": "这句话为什么只有他会说/体现了什么反差"}],
    "ratings": [{"dimension": "有对比意义的维度", "score": 2, "comment": "结合数据锚点的简短点评"}],
    "verdict": ["可验证的独特规律、反差或跨群/跨时期变化"],
    "closing": "一句精准、好笑且不套路的收尾",
}

_CHUNK_EXTRACT_SCHEMA = {
    "period": "本批时间范围简述",
    "habits": ["本批观察到的具体说话习惯/口头禅/句式特点（带具体例子）"],
    "topics": [{"topic": "具体细分话题/名词/作品/工具", "stance": "他的具体态度、偏好或做过什么"}],
    "moments": [{"message_id": 123, "why": "为什么有辨识度、好笑或体现反差"}],
    "social_style": "本批与其他群友的互动姿态（如爱抬杠/爱科普/爱求资源/爱接梗/自言自语）",
    "tone_note": "本批整体情绪与活跃特点",
}

_PROFILE_PROMPT_PAYLOAD_MAX_CHARS = 95_000
_PROFILE_PROMPT_TEXT_LIMIT = 320
_PROFILE_ALL_CHUNK_MAX_CHARS = 75_000
_PROFILE_REDUCE_MAX_CHARS = 75_000
_PROFILE_ANALYTICS_DB_LIMIT = 500
_PROFILE_BASELINE_LIMIT = 5000
_RICH_MESSAGE_MAX_CHARS = 32_768

_SENSITIVE_OUTPUT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"心理诊断|精神疾病|抑郁(?:症)?|焦虑症|人格障碍|双相障碍|躁郁|自闭症|注意力缺陷|ADHD|depress(?:ion|ed)?|bipolar|autis(?:m|tic)?|diagnos(?:is|ed)?",
        r"性取向|同性恋|异性恋|双性恋|跨性别|sexual\s*orientation|\bgay\b|\blesbian\b|transgender",
        r"政治立场|政治倾向|偏左|偏右|左翼|右翼|保守派|自由派|political\s*(?:leaning|belief|affiliation)",
        r"宗教信仰|(?:是|属于).{0,4}(?:佛教徒|基督徒|穆斯林)|religious\s*(?:belief|affiliation)",
        r"族裔|种族归属|民族身份|ethnicity|racial\s*identity",
        r"财务状况|经济状况|收入水平|个人负债|financial\s*status|income\s*level",
        r"精确位置|家庭住址|家住.{0,12}(?:路|街|号)|home\s*address|exact\s*location",
        r"犯罪倾向|暴力倾向|criminal\s*tendency|propensity\s*for\s*violence",
    )
)


@dataclass(frozen=True)
class ProfileCommand:
    target_ref: str
    sample_size: int
    all_history: bool = False
    history_scope: str = ""


@dataclass(frozen=True)
class ProfileSample:
    message_id: int
    date: datetime | None
    text: str
    kind: str
    link: str = ""
    source_label: str = ""
    chat_id: int | None = None
    raw_message_id: int | None = None
    reply_to_message_id: int | None = None
    reply_context: str = ""
    reply_to_sender_id: int | None = None


@dataclass(frozen=True)
class ProfileChatScope:
    chat_id: int
    title: str
    username: str = ""


@dataclass(frozen=True)
class ProfilePersonality:
    title: str
    analysis: str
    evidence_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ProfileInterest:
    topic: str
    detail: str = ""


@dataclass(frozen=True)
class ProfileQuote:
    message_id: int
    text: str
    comment: str = ""
    link: str = ""
    reply_context: str = ""


@dataclass(frozen=True)
class ProfileRating:
    dimension: str
    score: int
    comment: str = ""


@dataclass(frozen=True)
class ProfileResult:
    tagline: str
    personality: list[ProfilePersonality]
    interests: list[ProfileInterest]
    quotes: list[ProfileQuote]
    ratings: list[ProfileRating]
    verdict: list[str]
    closing: str
    archetype: str = ""


class UserProfileModule:
    def __init__(
        self,
        card: ModuleCard,
        config: UserProfileConfig,
        ai_config: AIConfig,
        project_root: Path | None = None,
        chat_history: ChatHistoryStore | None = None,
        telegram_config: TelegramConfig | None = None,
    ) -> None:
        self.card = card
        self.config = config
        self.ai_config = ai_config
        self.project_root = project_root
        self.chat_history = chat_history
        self.telegram_config = telegram_config
        self.usage_path = self._resolve_path("runtime/data/ai_usage.jsonl")
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._active_messages: set[tuple[str, str]] = set()
        self._sync_card_config()

    async def start(self) -> None:
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"
        tasks = list(self._active_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_tasks.clear()

    async def handle_message(self, event: Any) -> HandlerResult:
        if not is_outgoing(event):
            return HandlerResult.ignored(self.card.id)
        if is_edited_event(event):
            return HandlerResult.ignored(self.card.id)

        message = event_message(event)
        command = extract_profile_command(message_text(message), bool(getattr(message, "is_reply", False)), self.config)
        if command is None:
            return HandlerResult.ignored(self.card.id)

        msg_key = (str(getattr(message, "chat_id", "")), str(getattr(message, "id", "")))
        if msg_key[1] and msg_key in self._active_messages:
            return HandlerResult.ignored(self.card.id)
        if msg_key[1]:
            self._active_messages.add(msg_key)
        try:
            return await self._handle_profile_command(event, message, command)
        finally:
            self._active_messages.discard(msg_key)

    async def _handle_profile_command(self, event: Any, message: Any, command: ProfileCommand) -> HandlerResult:

        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        client = getattr(event, "client", None)
        if not _is_group_chat_id(chat_id):
            await safe_edit_message(message, format_profile_status("用户画像只能在群聊中生成。"), parse_mode="html")
            return HandlerResult.handled(self.card.id, "private chat rejected")
        if client is None or not hasattr(client, "iter_messages"):
            await safe_edit_message(message, format_profile_status("当前 Telegram 客户端无法读取群历史。"), parse_mode="html")
            return HandlerResult.handled(self.card.id, "history unavailable")

        request_started_at = time.monotonic()
        message_id = getattr(message, "id", None)
        logger.info(
            "User profile command accepted: chat_id=%s message_id=%s target_ref=%s requested_samples=%s history_scope=%s is_reply=%s",
            chat_id,
            message_id,
            command.target_ref or "reply",
            "all" if command.all_history else command.sample_size,
            command.history_scope or "recent_local",
            bool(getattr(message, "is_reply", False)),
        )
        await safe_edit_message(
            message,
            format_profile_progress(
                "① 正在识别目标群友……",
                "本消息会自动更新，请勿重复发送命令。",
            ),
            parse_mode="html",
            link_preview=False,
        )

        try:
            target, replied = await self._resolve_target(event, command)
        except Exception as exc:
            await safe_edit_message(message, format_profile_status(str(exc)), parse_mode="html")
            return HandlerResult.handled(self.card.id, "target unresolved")
        if target is None:
            await safe_edit_message(message, format_profile_hint(self.config), parse_mode="html")
            return HandlerResult.handled(self.card.id, "target missing")

        replied_sender_id = getattr(replied, "sender_id", None) if replied is not None else None
        if isinstance(replied_sender_id, int) and replied_sender_id < 0:
            target_id = replied_sender_id
        else:
            target_id = _entity_id(target) or replied_sender_id
        if target_id is None:
            await safe_edit_message(message, format_profile_status("无法识别目标群友。"), parse_mode="html")
            return HandlerResult.handled(self.card.id, "target unresolved")

        target_label = profile_target_label(target, target_id)
        logger.info(
            "User profile target resolved: chat_id=%s message_id=%s target_id=%s target=%s latency_ms=%s",
            chat_id,
            message_id,
            target_id,
            target_label,
            int((time.monotonic() - request_started_at) * 1000),
        )
        chat_username = await _resolve_chat_username(event)
        history_scope = command.history_scope or ("local" if command.all_history else "")
        monitored_chats = (
            self._monitored_profile_chats(chat_id, chat_username)
            if history_scope == "all"
            else []
        )
        if history_scope == "all":
            target_label = f"{target_label} · 跨群"
        elif history_scope == "local":
            target_label = f"{target_label} · 本群"
        status_message = message
        phase = "publish_initial_status"

        try:
            status_message = await self._edit_or_send(
                event,
                status_message,
                replied,
                format_profile_progress(
                    (
                        f"② 正在从数据库读取 {target_label} 在 {len(monitored_chats)} 个监控群的全部已归档发言……"
                        if history_scope == "all"
                        else f"② 正在从数据库读取 {target_label} 在当前群的全部已归档发言……"
                        if history_scope == "local"
                        else f"② 正在读取 {target_label} 的最近 {command.sample_size} 条发言……"
                    ),
                    "本消息会自动更新，请勿重复发送命令。",
                ),
                phase=phase,
            )
            phase = "collect_samples"
            sample_started_at = time.monotonic()
            archived_samples: list[ProfileSample] = []
            analytics_pool: list[ProfileSample] = []
            group_recent_messages: list[Any] = []
            noise_stats = (0, 0, 0, 0)  # raw_count, filtered_noise, bot_cmd, ritual
            backfill_complete = True
            completed_backfill_groups = 0
            chat_history_enabled = self.chat_history is not None and bool(self.chat_history.config.enabled)
            if command.all_history and not chat_history_enabled:
                raise ValueError("聊天数据库未启用，无法执行全量历史分析。")
            if chat_history_enabled and self.chat_history is not None:
                store = self.chat_history

                def _query_archive() -> tuple[
                    list[ProfileSample],
                    list[ProfileSample],
                    list[Any],
                    tuple[int, int, int, int],
                    bool,
                    int,
                ]:
                    recent_chat = store.get_recent_chat_messages(chat_id, _PROFILE_BASELINE_LIMIT)
                    if history_scope == "all":
                        raw_rows = collect_archived_profile_samples_across_chats(
                            store,
                            monitored_chats,
                            target_id,
                            self.config.command_prefixes,
                        )
                        clean_rows, f_cnt, b_cnt, r_cnt = filter_noise_samples(
                            raw_rows,
                            min_required=self.config.min_required_samples,
                        )
                        enriched = _enrich_samples_with_reply_context(store, clean_rows)
                        completed = sum(
                            bool(state and state.is_complete)
                            for item in monitored_chats
                            if (state := store.get_backfill_state(item.chat_id)) is not None
                        )
                        return (
                            enriched,
                            enriched,
                            recent_chat,
                            (len(raw_rows), f_cnt, b_cnt, r_cnt),
                            bool(monitored_chats) and completed == len(monitored_chats),
                            completed,
                        )

                    fetch_limit = (
                        None
                        if command.all_history
                        else max(command.sample_size * 3, _PROFILE_ANALYTICS_DB_LIMIT)
                    )
                    raw_rows = collect_archived_profile_samples(
                        store,
                        chat_id,
                        target_id,
                        fetch_limit,
                        self.config.command_prefixes,
                        chat_username,
                    )
                    clean_rows, f_cnt, b_cnt, r_cnt = filter_noise_samples(
                        raw_rows,
                        min_required=self.config.min_required_samples,
                    )
                    pool_limit = None if command.all_history else max(command.sample_size, _PROFILE_ANALYTICS_DB_LIMIT)
                    pool = clean_rows if pool_limit is None else clean_rows[-pool_limit:]
                    enriched_pool = _enrich_samples_with_reply_context(store, pool)
                    selected_rows = enriched_pool if command.all_history else enriched_pool[-command.sample_size :]
                    complete = True
                    if history_scope == "local":
                        backfill_state = store.get_backfill_state(chat_id)
                        complete = bool(backfill_state and backfill_state.is_complete)
                    return (
                        selected_rows,
                        enriched_pool,
                        recent_chat,
                        (len(raw_rows), f_cnt, b_cnt, r_cnt),
                        complete,
                        0,
                    )

                try:
                    (
                        archived_samples,
                        analytics_pool,
                        group_recent_messages,
                        noise_stats,
                        backfill_complete,
                        completed_backfill_groups,
                    ) = await asyncio.to_thread(_query_archive)
                except Exception as exc:
                    if command.all_history:
                        raise RuntimeError(f"读取本地聊天归档失败：{exc}") from exc
                    logger.exception(
                        "User profile database sample query failed; falling back to Telegram: chat_id=%s target_id=%s",
                        chat_id,
                        target_id,
                    )

            telegram_samples: list[ProfileSample] = []
            if not command.all_history and len(archived_samples) < command.sample_size:
                raw_tg_samples = await collect_profile_samples(
                    client,
                    chat_id,
                    target_id,
                    command.sample_size,
                    self.config.command_prefixes,
                    chat_username,
                )
                telegram_samples, tg_f, tg_b, tg_r = filter_noise_samples(
                    raw_tg_samples,
                    min_required=self.config.min_required_samples,
                )
                if not archived_samples:
                    noise_stats = (len(raw_tg_samples), tg_f, tg_b, tg_r)
            samples = (
                archived_samples
                if command.all_history
                else merge_profile_samples(archived_samples, telegram_samples, command.sample_size)
            )
            logger.info(
                "User profile samples collected: chat_id=%s message_id=%s target_id=%s valid_samples=%s database_samples=%s telegram_samples=%s requested_samples=%s latency_ms=%s",
                chat_id,
                message_id,
                target_id,
                len(samples),
                len(archived_samples),
                len(telegram_samples),
                "all" if command.all_history else command.sample_size,
                int((time.monotonic() - sample_started_at) * 1000),
            )
            if len(samples) < self.config.min_required_samples:
                phase = "publish_insufficient_samples"
                await self._edit_or_send(
                    event,
                    status_message,
                    replied,
                    format_profile_status(
                        f"只找到 {len(samples)} 条有效样本，至少需要 {self.config.min_required_samples} 条才生成画像。"
                    ),
                    phase=phase,
                )
                return HandlerResult.handled(self.card.id, "insufficient samples")

            phase = "compute_analytics"
            fingerprint_samples = analytics_pool if len(analytics_pool) >= len(samples) else samples
            raw_count, filtered_noise, bot_cmd_cnt, ritual_cnt = noise_stats
            analytics = await asyncio.to_thread(
                compute_profile_analytics,
                fingerprint_samples,
                raw_count=raw_count or len(fingerprint_samples),
                filtered_noise_count=filtered_noise,
                bot_cmd_count=bot_cmd_cnt,
                ritual_count=ritual_cnt,
                target_user_id=target_id,
                group_recent_messages=group_recent_messages or None,
            )
            peer_ids = list(
                dict.fromkeys(
                    [peer.user_id for peer in analytics.top_replied_to]
                    + [peer.user_id for peer in analytics.top_replied_by]
                )
            )[:4]
            if peer_ids:
                resolved_peers = await self._resolve_peer_labels(client, peer_ids)
                analytics = with_resolved_peer_labels(analytics, resolved_peers)

            provider = self.ai_config.reply_provider
            phase = "publish_ai_status"
            if command.all_history:
                phase = "ai_all_history"
                raw_result, total_tokens, status_message = await self._generate_all_history_profile(
                    event,
                    status_message,
                    replied,
                    target_label,
                    samples,
                    backfill_complete=backfill_complete,
                    history_scope=history_scope,
                    monitored_group_count=len(monitored_chats),
                    completed_backfill_groups=completed_backfill_groups,
                    analytics=analytics,
                )
            else:
                prompt_samples = select_profile_prompt_samples(
                    samples,
                    distinctive_terms=analytics.distinctive_terms,
                )
                fingerprint_hint = (
                    f"行为指纹已覆盖近期 {analytics.analyzed_count} 条发言与本群相对基准。"
                    if analytics.analyzed_count > len(samples) or analytics.baseline is not None
                    else (
                        "全部样本原文都会交给模型。"
                        if len(prompt_samples) == len(samples)
                        else f"统计覆盖全部样本，并按信息密度与时间轴精选 {len(prompt_samples)} 条代表性原文。"
                    )
                )
                status_message = await self._edit_or_send(
                    event,
                    status_message,
                    replied,
                    format_profile_progress(
                        f"③ 已读取 {len(samples)} 条有效样本，正在请求 {provider.model or 'AI 模型'} 分析……",
                        fingerprint_hint,
                        f"最长等待 {self.config.timeout_seconds:g} 秒，超时会自动停止并显示原因。",
                    ),
                    phase=phase,
                )
                prompt = build_profile_prompt(
                    target_label,
                    samples,
                    self.config,
                    prompt_samples,
                    analytics=analytics,
                )
                logger.info(
                    "User profile prompt ready: chat_id=%s message_id=%s target_id=%s total_samples=%s prompt_samples=%s prompt_chars=%s",
                    chat_id,
                    message_id,
                    target_id,
                    len(samples),
                    len(prompt_samples),
                    len(prompt),
                )
                phase = "ai_request"
                raw_result, total_tokens = await self._generate_profile_with_timeout(prompt)
            phase = "normalize_result"
            profile = normalize_profile_result(raw_result, samples)
            if command.all_history and not backfill_complete:
                profile = add_profile_coverage_warning(profile, history_scope)
            phase = "publish_result"
            rich_published = False
            rich_delivery = ""
            try:
                rendered_markdown = render_profile_rich_markdown(
                    profile,
                    target_label=target_label,
                    samples=samples,
                    model=self.ai_config.reply_provider.model,
                    total_tokens=total_tokens,
                    analytics=analytics,
                )
                rich_published = await self._try_edit_profile_rich_blocks(
                    event,
                    status_message,
                    profile,
                    target_label=target_label,
                    samples=samples,
                    model=self.ai_config.reply_provider.model,
                    total_tokens=total_tokens,
                    analytics=analytics,
                )
                if rich_published:
                    rich_delivery = "rich_blocks_edit"
                else:
                    rich_published = await self._try_send_profile_rich_blocks(
                        event,
                        status_message,
                        profile,
                        target_label=target_label,
                        samples=samples,
                        model=self.ai_config.reply_provider.model,
                        total_tokens=total_tokens,
                        analytics=analytics,
                    )
                    if rich_published:
                        rich_delivery = "rich_blocks_send"
                if not rich_published:
                    rich_published = await self._try_edit_profile_rich_message(
                        event,
                        status_message,
                        rendered_markdown,
                    )
                    if rich_published:
                        rich_delivery = "rich_markdown_edit"
                    else:
                        rich_published = await self._try_send_profile_rich_message(
                            event,
                            status_message,
                            rendered_markdown,
                        )
                        if rich_published:
                            rich_delivery = "rich_markdown_send"
            except Exception:
                logger.warning(
                    "User profile Rich Markdown rendering failed; falling back to Telegram HTML",
                    exc_info=True,
                )

            if rich_published:
                published_message = status_message
                delivery = rich_delivery
            else:
                rendered_html = render_profile_html(
                    profile,
                    target_label=target_label,
                    samples=samples,
                    model=self.ai_config.reply_provider.model,
                    total_tokens=total_tokens,
                    analytics=analytics,
                )
                published_message = await self._edit_or_send(
                    event,
                    status_message,
                    replied,
                    rendered_html,
                    phase=phase,
                )
                delivery = "html_edit" if published_message is status_message else "html_fallback_send"
            self.card.metrics["generated"] = int(self.card.metrics.get("generated", 0)) + 1
            self.card.metrics["last_target"] = target_label
            self.card.metrics["last_sample_count"] = len(samples)
            logger.info(
                "User profile analysis completed: chat_id=%s message_id=%s target_id=%s samples=%s total_tokens=%s latency_ms=%s delivery=%s",
                chat_id,
                message_id,
                target_id,
                len(samples),
                total_tokens,
                int((time.monotonic() - request_started_at) * 1000),
                delivery,
            )
            return HandlerResult.handled(self.card.id, "profile generated")
        except Exception as exc:
            logger.exception(
                "User profile analysis failed: chat_id=%s message_id=%s target_id=%s phase=%s latency_ms=%s error=%s",
                chat_id,
                message_id,
                target_id,
                phase,
                int((time.monotonic() - request_started_at) * 1000),
                exc,
            )
            self.card.metrics["failures"] = int(self.card.metrics.get("failures", 0)) + 1
            try:
                await self._edit_or_send(
                    event,
                    status_message,
                    replied,
                    format_profile_status(f"生成失败：{_clip(str(exc), 420)}"),
                    phase="publish_failure",
                )
            except Exception:
                logger.exception(
                    "User profile failure status could not be published: chat_id=%s message_id=%s target_id=%s",
                    chat_id,
                    message_id,
                    target_id,
                )
            return HandlerResult.handled(self.card.id, "profile generation failed")

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("user_profile", values)
        if not isinstance(data, dict):
            return
        self.config = user_profile_config_from_dict({**asdict(self.config), **data})
        self._sync_card_config()

    async def _resolve_target(self, event: Any, command: ProfileCommand) -> tuple[Any | None, Any | None]:
        message = event_message(event)
        client = getattr(event, "client", None)
        if command.target_ref and client is not None and hasattr(client, "get_entity"):
            lookup: Any = command.target_ref.strip()
            if re.fullmatch(r"-?\d+", lookup):
                lookup = int(lookup)
            try:
                return await client.get_entity(lookup), None
            except Exception as exc:
                raise ValueError(f"找不到目标用户 {command.target_ref}") from exc

        replied = await get_reply_message(message)
        if replied is not None:
            target = getattr(replied, "sender", None)
            if target is None and hasattr(replied, "get_sender"):
                try:
                    target = await replied.get_sender()
                except Exception:
                    logger.exception("Failed to resolve replied sender for user profile")
            sender_id = getattr(replied, "sender_id", None)
            if target is None and sender_id is not None and client is not None and hasattr(client, "get_entity"):
                try:
                    target = await client.get_entity(sender_id)
                except Exception:
                    logger.warning("Failed to get_entity for replied sender_id=%s; using fallback", sender_id)
            if target is None and sender_id is not None:
                target = _FallbackEntity(sender_id)
            return target, replied

        return None, None

    async def _edit_or_send(
        self,
        event: Any,
        message: Any,
        replied: Any,
        rendered: str,
        *,
        phase: str,
    ) -> Any:
        if await safe_edit_message(message, rendered, parse_mode="html", link_preview=False):
            return message

        client = getattr(event, "client", None)
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        if client is None or not hasattr(client, "send_message"):
            raise RuntimeError(f"无法更新画像消息，且当前客户端不支持补发结果（阶段：{phase}）。")

        kwargs: dict[str, Any] = {"parse_mode": "html", "link_preview": False}
        reply_id = getattr(replied, "id", None)
        if reply_id is not None:
            kwargs["reply_to"] = reply_id
        logger.warning(
            "User profile message edit failed; sending fallback: chat_id=%s message_id=%s phase=%s",
            chat_id,
            getattr(message, "id", None),
            phase,
        )
        return await client.send_message(chat_id, rendered, **kwargs)

    async def _try_edit_profile_rich_message(self, event: Any, message: Any, markdown: str) -> bool:
        rich_message = self._build_profile_rich_markdown(markdown)
        if rich_message is None:
            return False
        return await self._try_edit_profile_rich_payload(event, message, rich_message, source="markdown")

    async def _try_send_profile_rich_message(self, event: Any, message: Any, markdown: str) -> bool:
        rich_message = self._build_profile_rich_markdown(markdown)
        if rich_message is None:
            return False
        return await self._try_send_profile_rich_payload(event, message, rich_message, source="markdown")

    def _build_profile_rich_markdown(self, markdown: str) -> Any | None:
        try:
            import telethon
            from telethon import types

            rich_message_type = getattr(types, "InputRichMessageMarkdown", None)
            if rich_message_type is None:
                logger.warning(
                    "User profile rich Markdown unavailable: telethon_version=%s has_markdown_type=False. "
                    "Update the NAS environment with ./nas-conda-setup.sh and restart the process.",
                    getattr(telethon, "__version__", "unknown"),
                )
                return None
            return rich_message_type(markdown=markdown)
        except Exception:
            logger.warning("User profile rich Markdown construction failed", exc_info=True)
            return None

    async def _try_edit_profile_rich_blocks(
        self,
        event: Any,
        message: Any,
        profile: ProfileResult,
        *,
        target_label: str,
        samples: list[ProfileSample],
        model: str,
        total_tokens: int,
        analytics: ProfileAnalytics | None = None,
    ) -> bool:
        rich_message = self._build_profile_rich_blocks(
            profile,
            target_label=target_label,
            samples=samples,
            model=model,
            total_tokens=total_tokens,
            analytics=analytics,
        )
        if rich_message is None:
            return False
        return await self._try_edit_profile_rich_payload(event, message, rich_message, source="blocks")

    async def _try_send_profile_rich_blocks(
        self,
        event: Any,
        message: Any,
        profile: ProfileResult,
        *,
        target_label: str,
        samples: list[ProfileSample],
        model: str,
        total_tokens: int,
        analytics: ProfileAnalytics | None = None,
    ) -> bool:
        rich_message = self._build_profile_rich_blocks(
            profile,
            target_label=target_label,
            samples=samples,
            model=model,
            total_tokens=total_tokens,
            analytics=analytics,
        )
        if rich_message is None:
            return False
        return await self._try_send_profile_rich_payload(event, message, rich_message, source="blocks")

    def _build_profile_rich_blocks(
        self,
        profile: ProfileResult,
        *,
        target_label: str,
        samples: list[ProfileSample],
        model: str,
        total_tokens: int,
        analytics: ProfileAnalytics | None = None,
    ) -> Any | None:
        try:
            import telethon
            from telethon import types

            if not hasattr(types, "InputRichMessage") or not hasattr(types, "PageBlockTable"):
                logger.warning(
                    "User profile explicit rich blocks unavailable: telethon_version=%s. "
                    "Update the NAS environment with ./nas-conda-setup.sh and restart the process.",
                    getattr(telethon, "__version__", "unknown"),
                )
                return None
            return build_profile_rich_message(
                profile,
                target_label=target_label,
                samples=samples,
                model=model,
                total_tokens=total_tokens,
                rich_types=types,
                analytics=analytics,
            )
        except Exception:
            logger.warning("User profile explicit rich block construction failed", exc_info=True)
            return None

    async def _try_edit_profile_rich_payload(
        self,
        event: Any,
        message: Any,
        rich_message: Any,
        *,
        source: str,
    ) -> bool:
        client = getattr(event, "client", None)
        if client is None:
            logger.warning("User profile rich message unavailable: Telegram client is missing")
            return False
        if not callable(client) or not hasattr(client, "get_input_entity"):
            logger.warning(
                "User profile rich message unavailable: client_type=%s callable=%s has_get_input_entity=%s",
                type(client).__name__,
                callable(client),
                hasattr(client, "get_input_entity"),
            )
            return False

        message_id = _positive_int(getattr(message, "id", None))
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        if message_id is None or chat_id is None:
            return False

        try:
            import telethon
            from telethon import functions

            edit_request_type = getattr(getattr(functions, "messages", None), "EditMessageRequest", None)
            edit_supports_rich_message = _request_supports_parameter(edit_request_type, "rich_message")
            if edit_request_type is None or not edit_supports_rich_message:
                logger.warning(
                    "User profile rich message unavailable: telethon_version=%s has_rich_edit=%s. "
                    "Update the NAS environment with ./nas-conda-setup.sh and restart the process.",
                    getattr(telethon, "__version__", "unknown"),
                    edit_supports_rich_message,
                )
                return False

            input_peer = await client.get_input_entity(chat_id)
            await client(
                edit_request_type(
                    peer=input_peer,
                    id=message_id,
                    message="",
                    rich_message=rich_message,
                )
            )
            return True
        except Exception:
            logger.warning(
                "User profile rich message edit failed: source=%s chat_id=%s message_id=%s",
                source,
                chat_id,
                message_id,
                exc_info=True,
            )
            return False

    async def _try_send_profile_rich_payload(
        self,
        event: Any,
        message: Any,
        rich_message: Any,
        *,
        source: str,
    ) -> bool:
        client = getattr(event, "client", None)
        if client is None:
            logger.warning("User profile rich message send unavailable: Telegram client is missing")
            return False
        if not callable(client) or not hasattr(client, "get_input_entity"):
            logger.warning(
                "User profile rich message send unavailable: client_type=%s callable=%s has_get_input_entity=%s",
                type(client).__name__,
                callable(client),
                hasattr(client, "get_input_entity"),
            )
            return False

        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        if chat_id is None:
            return False

        try:
            import telethon
            from telethon import functions, types

            send_request_type = getattr(getattr(functions, "messages", None), "SendMessageRequest", None)
            send_supports_rich_message = _request_supports_parameter(send_request_type, "rich_message")
            if send_request_type is None or not send_supports_rich_message:
                logger.warning(
                    "User profile rich message send unavailable: telethon_version=%s has_rich_send=%s. "
                    "Update the NAS environment with ./nas-conda-setup.sh and restart the process.",
                    getattr(telethon, "__version__", "unknown"),
                    send_supports_rich_message,
                )
                return False

            input_peer = await client.get_input_entity(chat_id)
            request_kwargs: dict[str, Any] = {
                "peer": input_peer,
                "message": "",
                "random_id": secrets.randbits(63) or 1,
                "rich_message": rich_message,
            }
            reply_to_message_id = _positive_int(getattr(message, "reply_to_msg_id", None))
            input_reply_type = getattr(types, "InputReplyToMessage", None)
            if reply_to_message_id is not None and input_reply_type is not None:
                request_kwargs["reply_to"] = input_reply_type(reply_to_msg_id=reply_to_message_id)

            await client(send_request_type(**request_kwargs))
            await self._delete_profile_status_after_rich_send(message, chat_id=chat_id, source=source)
            return True
        except Exception:
            logger.warning(
                "User profile rich message send failed: source=%s chat_id=%s status_message_id=%s",
                source,
                chat_id,
                getattr(message, "id", None),
                exc_info=True,
            )
            return False

    async def _delete_profile_status_after_rich_send(self, message: Any, *, chat_id: Any, source: str) -> None:
        delete_message = getattr(message, "delete", None)
        if not callable(delete_message):
            logger.warning(
                "User profile rich message sent but status message cannot be deleted: source=%s chat_id=%s message_id=%s",
                source,
                chat_id,
                getattr(message, "id", None),
            )
            return
        try:
            result = delete_message()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.warning(
                "User profile rich message sent but status message deletion failed: source=%s chat_id=%s message_id=%s",
                source,
                chat_id,
                getattr(message, "id", None),
                exc_info=True,
            )

    async def _resolve_peer_labels(
        self,
        client: Any,
        peer_ids: list[int],
    ) -> dict[int, tuple[str, bool]]:
        if client is None or not hasattr(client, "get_entity"):
            return {}
        resolved: dict[int, tuple[str, bool]] = {}
        for uid in peer_ids[:4]:
            try:
                entity = await asyncio.wait_for(client.get_entity(uid), timeout=2.0)
            except Exception:
                continue
            if entity is None:
                continue
            label = profile_target_label(entity, uid)
            if label == f"用户 {uid}":
                continue
            resolved[uid] = (label, bool(getattr(entity, "bot", False)))
        return resolved

    async def _generate_all_history_profile(
        self,
        event: Any,
        status_message: Any,
        replied: Any,
        target_label: str,
        samples: list[ProfileSample],
        *,
        backfill_complete: bool,
        history_scope: str,
        monitored_group_count: int,
        completed_backfill_groups: int,
        analytics: ProfileAnalytics | None = None,
    ) -> tuple[dict[str, Any], int, Any]:
        chunks = chunk_profile_samples(samples)
        provider = self.ai_config.reply_provider
        if history_scope == "all":
            coverage_line = (
                f"{monitored_group_count} 个监控群均已回填完成，本次覆盖跨群全部文字消息。"
                if backfill_complete
                else f"⚠ 已完成回填 {completed_backfill_groups}/{monitored_group_count} 个群，本次先覆盖所有群当前已归档的文字消息。"
            )
        else:
            coverage_line = (
                "当前群历史回填已完成，本次覆盖本群全部文字消息。"
                if backfill_complete
                else "⚠ 当前群历史回填尚未完成，本次先覆盖本群当前已归档的全部文字消息。"
            )
        total_tokens = 0
        summaries: list[dict[str, Any]] = []

        for index, chunk in enumerate(chunks, start=1):
            status_message = await self._edit_or_send(
                event,
                status_message,
                replied,
                format_profile_progress(
                    f"③ 全量分析 {index}/{len(chunks)}：正在提取第 {index} 批事实素材……",
                    f"共 {len(samples)} 条有效文字，所有消息都会逐批交给 {provider.model or 'AI 模型'}。",
                    coverage_line,
                ),
                phase=f"ai_all_chunk_{index}",
            )
            prompt = build_profile_chunk_prompt(
                target_label,
                chunk,
                self.config,
                chunk_index=index,
                total_chunks=len(chunks),
                total_samples=len(samples),
            )
            logger.info(
                "User profile all-history chunk ready: target=%s chunk=%s/%s samples=%s prompt_chars=%s",
                target_label,
                index,
                len(chunks),
                len(chunk),
                len(prompt),
            )
            raw, used_tokens = await self._generate_profile_with_timeout(
                prompt,
                system_prompt=PROFILE_EXTRACT_SYSTEM_PROMPT,
            )
            total_tokens += used_tokens
            summaries.append(normalize_chunk_extract(raw, chunk))

        reduce_level = 1
        while True:
            groups = chunk_profile_summaries(summaries)
            if len(groups) == 1:
                status_message = await self._edit_or_send(
                    event,
                    status_message,
                    replied,
                    format_profile_progress(
                        "④ 所有历史消息均已分析，正在生成最终用户画像……",
                        f"正在结合全局行为指纹与 {len(chunks)} 批事实素材生成画像，最终引用仍由本地原文校验。",
                        coverage_line,
                    ),
                    phase="ai_all_final_reduce",
                )
                prompt = build_profile_reduce_prompt(
                    target_label,
                    samples,
                    groups[0],
                    self.config,
                    final=True,
                    reduce_level=reduce_level,
                    analytics=analytics,
                )
                raw, used_tokens = await self._generate_profile_with_timeout(prompt)
                total_tokens += used_tokens
                return raw, total_tokens, status_message

            reduced: list[dict[str, Any]] = []
            for index, group in enumerate(groups, start=1):
                status_message = await self._edit_or_send(
                    event,
                    status_message,
                    replied,
                    format_profile_progress(
                        f"④ 分层汇总 {reduce_level}：正在合并 {index}/{len(groups)}……",
                        f"已完整处理 {len(samples)} 条消息，正在压缩局部事实卡片以适配模型上下文。",
                        coverage_line,
                    ),
                    phase=f"ai_all_reduce_{reduce_level}_{index}",
                )
                prompt = build_profile_reduce_prompt(
                    target_label,
                    samples,
                    group,
                    self.config,
                    final=False,
                    reduce_level=reduce_level,
                    analytics=analytics,
                )
                raw, used_tokens = await self._generate_profile_with_timeout(
                    prompt,
                    system_prompt=PROFILE_EXTRACT_SYSTEM_PROMPT,
                )
                total_tokens += used_tokens
                reduced.append(normalize_chunk_extract(raw, samples, max_moments=12))
            summaries = reduced
            reduce_level += 1

    async def _generate_profile_with_timeout(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        timeout_seconds = max(0.001, float(self.config.timeout_seconds))
        started_at = time.monotonic()
        if system_prompt is not None and _callable_supports_parameter(self._generate_profile, "system_prompt"):
            coro = self._generate_profile(prompt, system_prompt=system_prompt)
        else:
            coro = self._generate_profile(prompt)
        task = asyncio.create_task(coro)
        self._active_tasks.add(task)
        try:
            done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
            if task in done:
                return await task
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            self._active_tasks.discard(task)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        provider = self.ai_config.reply_provider
        if is_anthropic_provider(provider.provider_type):
            protocol = "messages"
        elif is_chat_completions_provider(provider.provider_type):
            protocol = "chat_completions"
        else:
            protocol = "responses"
        error = f"AI 分析超过 {timeout_seconds:g} 秒，已自动停止。请检查 AI 服务状态或适当调高超时。"
        self._record_ai_usage(protocol, provider.model, False, started_at, error=error)
        logger.warning(
            "User profile AI request timed out: protocol=%s model=%s timeout_seconds=%s prompt_chars=%s",
            protocol,
            provider.model or "unknown",
            timeout_seconds,
            len(prompt),
        )
        raise TimeoutError(error)

    async def _generate_profile(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        provider = self.ai_config.reply_provider
        if not provider.api_key:
            raise ValueError("请先在管理后台的 AI 服务配置中填写回复服务 API Key。")
        if not provider.model:
            raise ValueError("请先在管理后台的 AI 服务配置中填写回复模型。")

        effective_system = system_prompt or PROFILE_SYSTEM_PROMPT
        started_at = time.monotonic()
        use_anthropic = is_anthropic_provider(provider.provider_type)
        use_chat_completions = is_chat_completions_provider(provider.provider_type)
        if use_anthropic:
            protocol = "messages"
        elif use_chat_completions:
            protocol = "chat_completions"
        else:
            protocol = "responses"
        response: Any = None
        logger.info(
            "User profile AI request started: protocol=%s model=%s timeout_seconds=%s max_tokens=%s prompt_chars=%s",
            protocol,
            provider.model,
            self.config.timeout_seconds,
            self.config.max_tokens,
            len(prompt),
        )
        try:
            if use_anthropic:
                response = await self._call_anthropic(prompt, effective_system)
                answer, _ = collect_anthropic_text_and_sources(response)
            elif use_chat_completions:
                response = await self._call_openai_chat_completions(prompt, effective_system)
                answer, _ = collect_chat_completions_text_and_sources(response)
            else:
                response = await self._call_openai(prompt, effective_system)
                answer, _ = collect_response_text_and_sources(response)
            parsed = parse_profile_json(answer)
            counts = extract_usage_counts(response)
            self._record_ai_usage(protocol, provider.model, True, started_at, response)
            logger.info(
                "User profile AI request completed: protocol=%s model=%s latency_ms=%s total_tokens=%s response_chars=%s",
                protocol,
                provider.model,
                int((time.monotonic() - started_at) * 1000),
                counts["total_tokens"],
                len(answer),
            )
            return parsed, counts["total_tokens"]
        except Exception as exc:
            self._record_ai_usage(protocol, provider.model, False, started_at, response, str(exc))
            logger.warning(
                "User profile AI request failed: protocol=%s model=%s latency_ms=%s error_type=%s error=%s",
                protocol,
                provider.model,
                int((time.monotonic() - started_at) * 1000),
                type(exc).__name__,
                _clip(str(exc), 300),
            )
            raise

    async def _call_openai(self, prompt: str, system_prompt: str = PROFILE_SYSTEM_PROMPT) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError("缺少 openai 依赖，请重新安装 requirements.txt。")
        provider = self.ai_config.reply_provider
        client_kwargs: dict[str, Any] = {"api_key": provider.api_key, "timeout": self.config.timeout_seconds}
        if provider.base_url.strip():
            client_kwargs["base_url"] = provider.base_url.rstrip("/")
        client = AsyncOpenAI(**client_kwargs)
        try:
            return await client.responses.create(
                model=provider.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                store=False,
                max_output_tokens=self.config.max_tokens,
            )
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def _call_openai_chat_completions(self, prompt: str, system_prompt: str = PROFILE_SYSTEM_PROMPT) -> Any:
        if AsyncOpenAI is None:
            raise RuntimeError("缺少 openai 依赖，请重新安装 requirements.txt。")
        provider = self.ai_config.reply_provider
        client_kwargs: dict[str, Any] = {"api_key": provider.api_key, "timeout": self.config.timeout_seconds}
        if provider.base_url.strip():
            client_kwargs["base_url"] = provider.base_url.rstrip("/")
        client = AsyncOpenAI(**client_kwargs)
        try:
            return await client.chat.completions.create(
                model=provider.model,
                messages=build_openai_chat_messages(
                    prompt,
                    [],
                    "",
                    system_prompt=system_prompt,
                ),
                max_tokens=self.config.max_tokens,
            )
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def _call_anthropic(self, prompt: str, system_prompt: str = PROFILE_SYSTEM_PROMPT) -> Any:
        provider = self.ai_config.reply_provider
        client = make_async_anthropic_client(provider.api_key, provider.base_url, self.config.timeout_seconds)
        try:
            return await anthropic_create_message(
                client,
                {
                    "model": provider.model,
                    "max_tokens": self.config.max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        finally:
            await aclose_anthropic(client)

    def _record_ai_usage(
        self,
        protocol: str,
        model: str,
        success: bool,
        started_at: float,
        source: Any = None,
        error: str = "",
    ) -> None:
        now = time.time()
        record = {
            "ts": now,
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
            "day": time.strftime("%Y-%m-%d", time.localtime(now)),
            "feature": "user_profile",
            "provider": protocol,
            "model": model or "unknown",
            "success": bool(success),
            "latency_ms": int(max(0, (time.monotonic() - started_at) * 1000)),
            **extract_usage_counts(source),
        }
        if error:
            record["error"] = error[:800]
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            with self.usage_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            logger.exception("Failed to write user profile AI usage stats")

    def _sync_card_config(self) -> None:
        self.card.config = asdict(self.config)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute() or self.project_root is None:
            return path
        return self.project_root / path

    def _monitored_profile_chats(
        self,
        current_chat_id: Any,
        current_chat_username: str,
    ) -> list[ProfileChatScope]:
        chats: list[ProfileChatScope] = []
        configured_groups = self.telegram_config.monitored_groups if self.telegram_config is not None else []
        configured_meta = self.telegram_config.monitored_group_meta if self.telegram_config is not None else {}
        for raw_chat_id in configured_groups:
            try:
                numeric_chat_id = int(str(raw_chat_id).strip())
            except (TypeError, ValueError):
                logger.warning("User profile skipped non-numeric monitored chat: %s", raw_chat_id)
                continue
            metadata = configured_meta.get(str(raw_chat_id).strip(), {})
            title = str(metadata.get("title") or numeric_chat_id).strip()
            username = str(metadata.get("username") or "").strip().lstrip("@")
            if numeric_chat_id == current_chat_id and not username:
                username = current_chat_username
            if all(item.chat_id != numeric_chat_id for item in chats):
                chats.append(ProfileChatScope(numeric_chat_id, title, username))
        if chats:
            return chats
        try:
            numeric_current_chat_id = int(current_chat_id)
        except (TypeError, ValueError):
            return []
        return [
            ProfileChatScope(
                numeric_current_chat_id,
                str(numeric_current_chat_id),
                current_chat_username,
            )
        ]


@dataclass(frozen=True)
class _FallbackEntity:
    id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""


def extract_profile_command(text: str, is_reply: bool, config: UserProfileConfig) -> ProfileCommand | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    matched_prefix = ""
    raw_arguments: str | None = None
    for prefix in sorted((item.strip() for item in config.command_prefixes if item.strip()), key=len, reverse=True):
        if stripped == prefix:
            matched_prefix = prefix
            raw_arguments = ""
            break
        if stripped.startswith(prefix + " ") or stripped.startswith(prefix + "\n"):
            matched_prefix = prefix
            raw_arguments = stripped[len(prefix) :].strip()
            break
    if raw_arguments is None:
        return None

    tokens = raw_arguments.split()
    sample_size = config.default_sample_size
    all_history = False
    history_scope = ""
    if tokens and tokens[-1].lower() in {"all", "local"}:
        all_history = True
        history_scope = tokens[-1].lower()
        tokens.pop()
    elif tokens and re.fullmatch(r"\d+", tokens[-1]):
        requested = int(tokens[-1])
        if is_reply or len(tokens) > 1:
            sample_size = max(config.min_sample_size, min(requested, config.max_sample_size))
            tokens.pop()
    target_ref = tokens[0] if tokens else ""
    is_symbol_prefix = matched_prefix.startswith(("/", ".", ","))
    if not is_symbol_prefix and not is_reply:
        if not target_ref or not (target_ref.startswith("@") or re.fullmatch(r"-?\d+", target_ref)):
            return None
    return ProfileCommand(
        target_ref=target_ref,
        sample_size=sample_size,
        all_history=all_history,
        history_scope=history_scope,
    )


def collect_archived_profile_samples(
    store: ChatHistoryStore,
    chat_id: Any,
    target: Any,
    sample_size: int | None,
    command_prefixes: list[str],
    chat_username: str = "",
) -> list[ProfileSample]:
    scan_limit = None if sample_size is None else max(sample_size, min(sample_size * 3, 5000))
    stored = store.get_user_messages(chat_id, target, scan_limit)
    samples: list[ProfileSample] = []
    for item in stored:
        if _matches_any_command(item.text, command_prefixes):
            continue
        samples.append(
            ProfileSample(
                message_id=item.message_id,
                date=item.sent_at,
                text=item.text if sample_size is None else _clip(item.text, 480),
                kind="text",
                link=build_message_link(chat_id, item.message_id, chat_username),
                chat_id=item.chat_id,
                raw_message_id=item.message_id,
                reply_to_message_id=item.reply_to_message_id,
            )
        )
    return samples if sample_size is None else samples[-sample_size:]


def collect_archived_profile_samples_across_chats(
    store: ChatHistoryStore,
    chats: list[ProfileChatScope],
    target: Any,
    command_prefixes: list[str],
) -> list[ProfileSample]:
    """Build globally unique evidence IDs while retaining each source message link."""
    by_chat_id = {item.chat_id: item for item in chats}
    stored = store.get_user_messages_across_chats(list(by_chat_id), target)
    samples: list[ProfileSample] = []
    for item in stored:
        if _matches_any_command(item.text, command_prefixes):
            continue
        source = by_chat_id.get(item.chat_id)
        if source is None:
            continue
        samples.append(
            ProfileSample(
                message_id=len(samples) + 1,
                date=item.sent_at,
                text=item.text,
                kind="text",
                link=build_message_link(item.chat_id, item.message_id, source.username),
                source_label=source.title,
                chat_id=item.chat_id,
                raw_message_id=item.message_id,
                reply_to_message_id=item.reply_to_message_id,
            )
        )
    return samples


def _enrich_samples_with_reply_context(
    store: ChatHistoryStore,
    samples: list[ProfileSample],
    *,
    max_lookup_ids: int = 2000,
) -> list[ProfileSample]:
    """Attach concise replied-to snippet and sender ID from local SQLite by primary key."""
    if not samples:
        return []
    ids_by_chat: dict[int, list[int]] = {}
    for sample in reversed(samples):
        if sample.chat_id is None or sample.reply_to_message_id is None:
            continue
        bucket = ids_by_chat.setdefault(sample.chat_id, [])
        if len(bucket) < max_lookup_ids:
            bucket.append(sample.reply_to_message_id)
    if not ids_by_chat:
        return samples

    replied_lookup: dict[tuple[int, int], Any] = {}
    for cid, msg_ids in ids_by_chat.items():
        found = store.get_messages_by_ids(cid, msg_ids)
        for mid, stored_msg in found.items():
            replied_lookup[(cid, mid)] = stored_msg
    if not replied_lookup:
        return samples

    enriched: list[ProfileSample] = []
    for sample in samples:
        if sample.chat_id is None or sample.reply_to_message_id is None:
            enriched.append(sample)
            continue
        parent = replied_lookup.get((sample.chat_id, sample.reply_to_message_id))
        if parent is None:
            enriched.append(sample)
            continue
        enriched.append(
            ProfileSample(
                message_id=sample.message_id,
                date=sample.date,
                text=sample.text,
                kind=sample.kind,
                link=sample.link,
                source_label=sample.source_label,
                chat_id=sample.chat_id,
                raw_message_id=sample.raw_message_id,
                reply_to_message_id=sample.reply_to_message_id,
                reply_context=_clip(parent.text, 44),
                reply_to_sender_id=parent.sender_id,
            )
        )
    return enriched


def merge_profile_samples(
    archived_samples: list[ProfileSample],
    telegram_samples: list[ProfileSample],
    sample_size: int,
) -> list[ProfileSample]:
    by_message_id = {sample.message_id: sample for sample in archived_samples}
    for sample in telegram_samples:
        by_message_id[sample.message_id] = sample
    ordered = sorted(by_message_id.values(), key=lambda sample: sample.message_id)
    return ordered[-max(1, sample_size) :]


async def collect_profile_samples(
    client: Any,
    chat_id: Any,
    target: Any,
    sample_size: int,
    command_prefixes: list[str],
    chat_username: str = "",
) -> list[ProfileSample]:
    samples: list[ProfileSample] = []
    scan_limit = max(sample_size, min(sample_size * 3, 5000))
    numeric_chat_id = _as_int_or_none(chat_id)
    async for item in client.iter_messages(chat_id, from_user=target, limit=scan_limit):
        raw_text = message_text(item)
        if raw_text and _matches_any_command(raw_text, command_prefixes):
            continue
        kind = profile_message_kind(item)
        if not raw_text and kind == "text":
            continue
        sample_text = raw_text or profile_media_marker(kind)
        if not sample_text:
            continue
        message_id = _positive_int(getattr(item, "id", None))
        if message_id is None:
            continue
        samples.append(
            ProfileSample(
                message_id=message_id,
                date=getattr(item, "date", None) if isinstance(getattr(item, "date", None), datetime) else None,
                text=_clip(sample_text, 480),
                kind=kind,
                link=build_message_link(chat_id, message_id, chat_username),
                chat_id=numeric_chat_id,
                raw_message_id=message_id,
                reply_to_message_id=_positive_int(getattr(item, "reply_to_msg_id", None)),
            )
        )
        if len(samples) >= sample_size:
            break
    return list(reversed(samples))


def profile_message_kind(message: Any) -> str:
    for attr, kind in (
        ("sticker", "sticker"),
        ("photo", "photo"),
        ("video", "video"),
        ("voice", "voice"),
        ("gif", "gif"),
    ):
        if getattr(message, attr, None):
            return kind
    return "media" if getattr(message, "media", None) else "text"


def profile_media_marker(kind: str) -> str:
    return {
        "sticker": "[贴纸]",
        "photo": "[图片]",
        "video": "[视频]",
        "voice": "[语音]",
        "gif": "[GIF]",
        "media": "[媒体]",
    }.get(kind, "")


def build_message_link(chat_id: Any, message_id: int, chat_username: str = "") -> str:
    username = (chat_username or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}/{message_id}"
    try:
        numeric_chat_id = int(chat_id)
    except (TypeError, ValueError):
        return ""
    raw = str(abs(numeric_chat_id))
    if not raw.startswith("100") or len(raw) <= 3:
        return ""
    return f"https://t.me/c/{raw[3:]}/{message_id}"


def select_profile_prompt_samples(
    samples: list[ProfileSample],
    *,
    distinctive_terms: list[str] | tuple[str, ...] = (),
) -> list[ProfileSample]:
    """Keep full time coverage while favoring high-information samples within budget."""
    if not samples:
        return []
    if _profile_payload_length(samples) <= _PROFILE_PROMPT_PAYLOAD_MAX_CHARS:
        return list(samples)

    low = 2
    high = len(samples) - 1
    selected = select_informative_samples(samples, 2, distinctive_terms=distinctive_terms)
    while low <= high:
        count = (low + high) // 2
        candidate = select_informative_samples(samples, count, distinctive_terms=distinctive_terms)
        if _profile_payload_length(candidate) <= _PROFILE_PROMPT_PAYLOAD_MAX_CHARS:
            selected = candidate
            low = count + 1
        else:
            high = count - 1
    return selected


def _sample_context_tag(sample: ProfileSample) -> str:
    parts: list[str] = []
    if sample.source_label:
        parts.append(sample.source_label)
    if sample.kind != "text":
        parts.append(sample.kind)
    if sample.reply_context:
        parts.append(f"回:{_clip(sample.reply_context, 36)}")
    return "|".join(parts)


def _sample_wire_row(sample: ProfileSample, *, full_text: bool = False) -> list[Any]:
    text = sample.text if full_text else _clip(sample.text, _PROFILE_PROMPT_TEXT_LIMIT)
    return [sample.message_id, format_sample_time_tag(sample.date), _sample_context_tag(sample), text]


def _profile_prompt_payload(samples: list[ProfileSample]) -> list[list[Any]]:
    return [_sample_wire_row(sample, full_text=False) for sample in samples]


def _profile_payload_length(samples: list[ProfileSample]) -> int:
    return len(json.dumps(_profile_prompt_payload(samples), ensure_ascii=False, separators=(",", ":")))


def chunk_profile_samples(
    samples: list[ProfileSample],
    max_chars: int = _PROFILE_ALL_CHUNK_MAX_CHARS,
) -> list[list[ProfileSample]]:
    """Split every message into bounded chronological chunks without sampling or dropping text."""
    if not samples:
        return []
    budget = max(1000, int(max_chars))
    chunks: list[list[ProfileSample]] = []
    current: list[ProfileSample] = []
    current_chars = 2
    for sample in samples:
        encoded = json.dumps(
            _sample_wire_row(sample, full_text=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        added_chars = len(encoded) + (1 if current else 0)
        if current and current_chars + added_chars > budget:
            chunks.append(current)
            current = []
            current_chars = 2
            added_chars = len(encoded)
        current.append(sample)
        current_chars += added_chars
    if current:
        chunks.append(current)
    return chunks


def chunk_profile_summaries(
    summaries: list[dict[str, Any]],
    max_chars: int = _PROFILE_REDUCE_MAX_CHARS,
) -> list[list[dict[str, Any]]]:
    if not summaries:
        return [[]]
    budget = max(1000, int(max_chars))
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 2
    for summary in summaries:
        encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        added_chars = len(encoded) + (1 if current else 0)
        if current and current_chars + added_chars > budget:
            groups.append(current)
            current = []
            current_chars = 2
            added_chars = len(encoded)
        current.append(summary)
        current_chars += added_chars
    if current:
        groups.append(current)
    return groups


def build_profile_prompt(
    target_label: str,
    samples: list[ProfileSample],
    config: UserProfileConfig,
    prompt_samples: list[ProfileSample] | None = None,
    *,
    analytics: ProfileAnalytics | None = None,
) -> str:
    text_lengths = [len(sample.text) for sample in samples if sample.kind == "text" and sample.text]
    average_length = round(sum(text_lengths) / len(text_lengths), 1) if text_lengths else 0
    sticker_count = sum(sample.kind == "sticker" for sample in samples)
    media_count = sum(sample.kind != "text" for sample in samples)
    effective_analytics = analytics if analytics is not None else compute_profile_analytics(samples)
    evidence_samples = (
        prompt_samples
        if prompt_samples is not None
        else select_profile_prompt_samples(samples, distinctive_terms=effective_analytics.distinctive_terms)
    )
    payload = _profile_prompt_payload(evidence_samples)
    analytics_block = format_analytics_for_prompt(effective_analytics)
    return (
        f"目标：{target_label}\n"
        f"样本数：{len(samples)}\n"
        f"提供给模型的代表性消息：{len(evidence_samples)} 条\n"
        f"时间范围：{format_sample_date_range(samples)}\n"
        f"纯文本平均长度：{average_length} 字\n"
        f"贴纸：{sticker_count} 条（{_percentage(sticker_count, len(samples))}）\n"
        f"全部媒体：{media_count} 条（{_percentage(media_count, len(samples))}）\n\n"
        f"{analytics_block}\n\n"
        f"写作风格：{config.style_prompt}\n"
        "安全边界：不得推断敏感属性、使用诊断性标签或把有限样本写成永久人格。\n"
        "输出要求：1 个专属生态位 archetype、1 句灵魂摘要 tagline、3 个高区分度性格速写、3–5 个具体细分兴趣/话题、"
        "3 条最具辨识度的代表语录、4 个严格按锚点拉开 1–5 星差距的评分维度和 3–4 个独特规律/反差总评。"
        "evidence_ids 和 quotes.message_id 只能使用下方存在的 id。\n"
        f"严格 JSON 结构：{json.dumps(_JSON_SCHEMA, ensure_ascii=False)}\n\n"
        "消息样本每项依次为 [evidence_id, 北京时间, 上下文(群名/媒体/回:被回复前情), text]：\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def build_profile_chunk_prompt(
    target_label: str,
    samples: list[ProfileSample],
    config: UserProfileConfig,
    *,
    chunk_index: int,
    total_chunks: int,
    total_samples: int,
) -> str:
    payload = [_sample_wire_row(sample, full_text=True) for sample in samples]
    return (
        f"目标：{target_label}\n"
        f"全量历史总消息数：{total_samples}\n"
        f"当前批次：{chunk_index}/{total_chunks}\n"
        f"当前批次消息数：{len(samples)}\n"
        f"当前批次时间范围：{format_sample_date_range(samples)}\n\n"
        "任务：从本批消息中提取具体事实素材与高能原话 ID，供最终汇总使用。不要写空泛人设套话。\n"
        "当前批次的每条消息都已完整提供，不得忽略或编造 message_id。\n"
        "安全边界：不得推断敏感属性、使用诊断性标签或编造样本外事实。\n"
        "请输出：3–6 条具体说话习惯/口头禅（带具体例子）、3–6 个具体细分话题与态度、"
        "最多 8 条最有辨识度/笑点/反差的 moments（只需填 message_id 和 why，本地会自动回填原文），以及互动姿态与情绪特点。\n"
        f"严格 JSON 结构：{json.dumps(_CHUNK_EXTRACT_SCHEMA, ensure_ascii=False)}\n\n"
        "消息样本每项依次为 [evidence_id, 北京时间, 上下文(群名/媒体/回:被回复前情), text]：\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def build_profile_reduce_prompt(
    target_label: str,
    samples: list[ProfileSample],
    summaries: list[dict[str, Any]],
    config: UserProfileConfig,
    *,
    final: bool,
    reduce_level: int,
    analytics: ProfileAnalytics | None = None,
) -> str:
    text_lengths = [len(sample.text) for sample in samples if sample.kind == "text" and sample.text]
    average_length = round(sum(text_lengths) / len(text_lengths), 1) if text_lengths else 0
    if not final:
        return (
            f"目标：{target_label}\n"
            f"全量历史消息数：{len(samples)}\n"
            f"全量时间范围：{format_sample_date_range(samples)}\n"
            f"汇总层级：{reduce_level}\n"
            "当前任务：合并多批事实素材卡片，保留具体名词、高频口头禅、反差线索和最具辨识度的 moments（保留真实 message_id），不要退化成抽象套话。\n"
            "安全边界：不得推断敏感属性、使用诊断性标签或编造不存在的 message_id。\n"
            f"严格 JSON 结构：{json.dumps(_CHUNK_EXTRACT_SCHEMA, ensure_ascii=False)}\n\n"
            "待合并的事实素材卡片：\n"
            f"{json.dumps(summaries, ensure_ascii=False, separators=(',', ':'))}"
        )

    effective_analytics = analytics if analytics is not None else compute_profile_analytics(samples)
    analytics_block = format_analytics_for_prompt(effective_analytics)
    return (
        f"目标：{target_label}\n"
        f"全量历史消息数：{len(samples)}\n"
        f"全量时间范围：{format_sample_date_range(samples)}\n"
        f"纯文本平均长度：{average_length} 字\n"
        f"汇总层级：{reduce_level}\n"
        "当前任务：结合【全局客观行为指纹】与下方各时期的真实事实素材卡片，一次性生成极具区分度的最终用户画像。\n\n"
        f"{analytics_block}\n\n"
        f"写作风格：{config.style_prompt}\n"
        "下方每张卡片均来自对全部历史消息的逐条提取，moments 中已由本地数据库回填真实原话、时间与回复前情。\n"
        "请充分利用跨时间/跨群反差、具体名词、口头禅与高能原话，严格遵守遮名测试，拒绝万金油算命文案。\n"
        "不得创造素材卡片中不存在的 message_id。最终原文会由本地数据库再次校验。\n"
        "安全边界：不得推断敏感属性、使用诊断性标签或把群聊表现写成永久人格。\n"
        "请输出：1 个专属生态位 archetype、1 句灵魂摘要 tagline、3 个高区分度性格速写、3–5 个具体细分兴趣/话题、"
        "3 条代表语录、4 个严格按锚点拉开 1–5 星差距的评分维度和 3–4 个独特规律/变化总评。\n"
        f"严格 JSON 结构：{json.dumps(_JSON_SCHEMA, ensure_ascii=False)}\n\n"
        "各时期事实素材卡片：\n"
        f"{json.dumps(summaries, ensure_ascii=False, separators=(',', ':'))}"
    )


def normalize_chunk_extract(
    raw: dict[str, Any],
    samples: list[ProfileSample],
    *,
    max_moments: int = 8,
) -> dict[str, Any]:
    """Normalize a Map-stage fact card and hydrate every moment with verified local text."""
    sample_by_id = {sample.message_id: sample for sample in samples}
    valid_ids = set(sample_by_id)

    period = _clip(_string_value(raw.get("period")), 48) or format_sample_date_range(samples)
    habits = [_clip(_string_value(item), 120) for item in _list_value(raw.get("habits"))[:6]]
    habits = [item for item in habits if item]
    # 兼容旧版或测试 stub 返回 personality/interests/quotes 的情形
    if not habits and raw.get("personality"):
        for item in _list_value(raw.get("personality"))[:4]:
            if isinstance(item, dict):
                title = _clip(_string_value(item.get("title")), 40)
                analysis = _clip(_string_value(item.get("analysis")), 100)
                if title or analysis:
                    habits.append(f"{title}：{analysis}" if title and analysis else (title or analysis))

    topics: list[dict[str, str]] = []
    raw_topics = _list_value(raw.get("topics")) or _list_value(raw.get("interests"))
    for item in raw_topics[:6]:
        if isinstance(item, dict):
            topic = _clip(_string_value(item.get("topic")), 40)
            stance = _clip(_string_value(item.get("stance") or item.get("detail")), 90)
        else:
            topic = _clip(_string_value(item), 60)
            stance = ""
        if topic:
            topics.append({"topic": topic, "stance": stance})

    moments: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    raw_moments = _list_value(raw.get("moments")) or _list_value(raw.get("quotes"))
    for item in raw_moments:
        if not isinstance(item, dict):
            continue
        mid = _positive_int(item.get("message_id"))
        if mid not in valid_ids or mid in seen_ids:
            continue
        sample = sample_by_id[mid]
        moment: dict[str, Any] = {
            "message_id": mid,
            "time": format_sample_time_tag(sample.date),
            "text": _clip(sample.text, 160),
            "why": _clip(_string_value(item.get("why") or item.get("comment")), 90),
        }
        ctx = _sample_context_tag(sample)
        if ctx:
            moment["ctx"] = ctx
        moments.append(moment)
        seen_ids.add(mid)
        if len(moments) >= max_moments:
            break

    # 若旧 stub 的 personality 带有 evidence_ids 也补进候选 moments，避免丢证据
    if len(moments) < max_moments and raw.get("personality"):
        for item in _list_value(raw.get("personality")):
            if not isinstance(item, dict):
                continue
            for mid in _valid_message_ids(item.get("evidence_ids"), valid_ids, 2):
                if mid in seen_ids:
                    continue
                sample = sample_by_id[mid]
                moment = {
                    "message_id": mid,
                    "time": format_sample_time_tag(sample.date),
                    "text": _clip(sample.text, 160),
                    "why": _clip(_string_value(item.get("title")), 60),
                }
                ctx = _sample_context_tag(sample)
                if ctx:
                    moment["ctx"] = ctx
                moments.append(moment)
                seen_ids.add(mid)
                if len(moments) >= max_moments:
                    break
            if len(moments) >= max_moments:
                break

    if not moments:
        for sample in [item for item in samples if item.text][:3]:
            moment = {
                "message_id": sample.message_id,
                "time": format_sample_time_tag(sample.date),
                "text": _clip(sample.text, 160),
                "why": "批次样本原话",
            }
            ctx = _sample_context_tag(sample)
            if ctx:
                moment["ctx"] = ctx
            moments.append(moment)

    social_style = _clip(_string_value(raw.get("social_style") or raw.get("tagline")), 120)
    tone_note = _clip(_string_value(raw.get("tone_note") or raw.get("closing")), 120)
    card = {
        "period": period,
        "habits": habits,
        "topics": topics,
        "moments": moments,
        "social_style": social_style,
        "tone_note": tone_note,
    }
    _ensure_texts_safe(
        [
            period,
            social_style,
            tone_note,
            *habits,
            *(part for item in topics for part in (item["topic"], item["stance"])),
            *(item["why"] for item in moments),
        ]
    )
    return card


def profile_result_to_summary(result: ProfileResult) -> dict[str, Any]:
    return {
        "archetype": result.archetype,
        "tagline": result.tagline,
        "personality": [
            {
                "title": item.title,
                "analysis": item.analysis,
                "evidence_ids": item.evidence_ids,
            }
            for item in result.personality
        ],
        "interests": [
            {"topic": item.topic, "detail": item.detail}
            for item in result.interests
        ],
        "quotes": [
            {
                "message_id": item.message_id,
                "text": item.text,
                "comment": item.comment,
                **({"reply_context": item.reply_context} if item.reply_context else {}),
            }
            for item in result.quotes
        ],
        "ratings": [
            {"dimension": item.dimension, "score": item.score, "comment": item.comment}
            for item in result.ratings
        ],
        "verdict": result.verdict,
        "closing": result.closing,
    }


def add_profile_coverage_warning(result: ProfileResult, history_scope: str = "local") -> ProfileResult:
    warning = (
        "⚠ 部分监控群的历史回填尚未完成，本次跨群画像仅覆盖各群当前已归档的文字消息。"
        if history_scope == "all"
        else "⚠ 当前群历史回填尚未完成，本次本群画像仅覆盖当前已归档的文字消息。"
    )
    if warning in result.verdict:
        return result
    return ProfileResult(
        tagline=result.tagline,
        personality=result.personality,
        interests=result.interests,
        quotes=result.quotes,
        ratings=result.ratings,
        verdict=[warning, *result.verdict],
        closing=result.closing,
        archetype=result.archetype,
    )


def parse_profile_json(value: str) -> dict[str, Any]:
    text = (value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 未返回可读取的画像 JSON。")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("AI 返回的画像 JSON 格式无效。") from exc
    if not isinstance(parsed, dict):
        raise ValueError("AI 返回的画像结构无效。")
    return parsed


def normalize_profile_result(raw: dict[str, Any], samples: list[ProfileSample]) -> ProfileResult:
    sample_by_id = {sample.message_id: sample for sample in samples}
    valid_ids = set(sample_by_id)

    archetype = _clip(_string_value(raw.get("archetype")), 36)

    personality: list[ProfilePersonality] = []
    for item in _list_value(raw.get("personality"))[:3]:
        if not isinstance(item, dict):
            continue
        title = _clip(_string_value(item.get("title")), 48)
        analysis = _clip(_string_value(item.get("analysis")), 240)
        if not title or not analysis:
            continue
        evidence_ids = _valid_message_ids(item.get("evidence_ids"), valid_ids, 3)
        personality.append(ProfilePersonality(title, analysis, evidence_ids))

    interests: list[ProfileInterest] = []
    for item in _list_value(raw.get("interests"))[:5]:
        if isinstance(item, dict):
            topic = _clip(_string_value(item.get("topic")), 44)
            detail = _clip(_string_value(item.get("detail")), 90)
        else:
            topic = _clip(_string_value(item), 90)
            detail = ""
        if topic:
            interests.append(ProfileInterest(topic, detail))

    quotes: list[ProfileQuote] = []
    seen_quote_ids: set[int] = set()
    for item in _list_value(raw.get("quotes")):
        if not isinstance(item, dict):
            continue
        message_id = _positive_int(item.get("message_id"))
        if message_id not in valid_ids or message_id in seen_quote_ids:
            continue
        sample = sample_by_id[message_id]
        quotes.append(
            ProfileQuote(
                message_id=message_id,
                text=_clip(sample.text, 150),
                comment=_clip(_string_value(item.get("comment")), 100),
                link=sample.link,
                reply_context=_clip(sample.reply_context, 44) if sample.reply_context else "",
            )
        )
        seen_quote_ids.add(message_id)
        if len(quotes) >= 3:
            break
    if not quotes:
        for sample in [item for item in samples if item.text][:3]:
            quotes.append(
                ProfileQuote(
                    sample.message_id,
                    _clip(sample.text, 150),
                    "样本原话。",
                    sample.link,
                    _clip(sample.reply_context, 44) if sample.reply_context else "",
                )
            )

    verdict = [_clip(_string_value(item), 90) for item in _list_value(raw.get("verdict"))[:4]]
    verdict = [item for item in verdict if item]
    ratings: list[ProfileRating] = []
    for item in _list_value(raw.get("ratings"))[:4]:
        if not isinstance(item, dict):
            continue
        dimension = _clip(_string_value(item.get("dimension")), 32)
        score = _bounded_int(item.get("score"), 1, 5)
        comment = _clip(_string_value(item.get("comment")), 80)
        if dimension and score is not None:
            ratings.append(ProfileRating(dimension, score, comment))
    tagline = _clip(_string_value(raw.get("tagline")), 160) or "一份基于近期群聊样本的发言风格速写。"
    closing = _clip(_string_value(raw.get("closing")), 180)
    if not personality:
        personality = [ProfilePersonality("群聊切片", "样本暂时不足以形成更细的风格分类。", [])]
    if not interests:
        interests = [ProfileInterest("日常群聊", "话题分布较分散。")]
    if not verdict:
        verdict = ["本结果仅代表当前样本中的群聊表现。"]
    if not ratings:
        fallback_dimensions = ("群聊参与", "风格辨识", "气氛贡献")
        ratings = [
            ProfileRating(dimension, 3, comment)
            for dimension, comment in zip(fallback_dimensions, verdict)
        ]
    profile = ProfileResult(tagline, personality, interests, quotes, ratings, verdict, closing, archetype)
    ensure_profile_safety(profile)
    return profile


def _ensure_texts_safe(parts: list[str]) -> None:
    combined = "\n".join(part for part in parts if part)
    if any(pattern.search(combined) for pattern in _SENSITIVE_OUTPUT_PATTERNS):
        raise ValueError("AI 画像包含不适合公开的敏感属性推断，已拒绝发送。")


def ensure_profile_safety(profile: ProfileResult) -> None:
    ai_text = [profile.archetype, profile.tagline, profile.closing, *profile.verdict]
    for item in profile.personality:
        ai_text.extend((item.title, item.analysis))
    for item in profile.interests:
        ai_text.extend((item.topic, item.detail))
    ai_text.extend(item.comment for item in profile.quotes)
    for item in profile.ratings:
        ai_text.extend((item.dimension, item.comment))
    _ensure_texts_safe(ai_text)


def _fingerprint_heading(analytics: ProfileAnalytics, sample_count: int) -> str:
    if analytics.analyzed_count > sample_count:
        return f"🧬 行为指纹（近 {analytics.analyzed_count} 条）"
    return "🧬 行为指纹"


def render_profile_html(
    result: ProfileResult,
    *,
    target_label: str,
    samples: list[ProfileSample],
    model: str,
    total_tokens: int,
    analytics: ProfileAnalytics | None = None,
) -> str:
    detail_lines: list[str] = []
    if analytics is not None:
        fp_lines = format_analytics_display_lines(analytics)[:4]
        if fp_lines:
            detail_lines.append(f"<b>{_escape_clip(_fingerprint_heading(analytics, len(samples)), 36)}</b>")
            detail_lines.extend(_escape_clip(line, 66) for line in fp_lines)
            detail_lines.append("")

    detail_lines.append("🧩 <b>性格速写</b>")
    sample_by_id = {sample.message_id: sample for sample in samples}
    for trait in result.personality[:3]:
        detail_lines.extend(
            [
                "",
                f"<b>“{_escape_clip(trait.title, 42)}”</b>",
                _escape_clip(trait.analysis, 180) + _render_evidence_links(trait.evidence_ids, sample_by_id),
            ]
        )

    detail_lines.extend(["", "🎯 <b>兴趣与话题</b>"])
    for item in result.interests[:5]:
        line = f"• <b>{_escape_clip(item.topic, 34)}</b>"
        if item.detail:
            line += f" — {_escape_clip(item.detail, 60)}"
        detail_lines.append(line)

    detail_lines.extend(["", "💬 <b>代表语录</b>"])
    for quote in result.quotes[:3]:
        link = _message_anchor(quote.link)
        detail_lines.append("")
        if quote.reply_context:
            detail_lines.append(f"<i>↪ 回「{_escape_clip(quote.reply_context, 34)}」</i>")
        detail_lines.append(f"“{_escape_clip(quote.text, 96)}”{link}")
        if quote.comment:
            detail_lines.append(f"<i>—— {_escape_clip(quote.comment, 68)}</i>")

    detail_lines.extend(["", "⭐ <b>总评</b>"])
    detail_lines.extend(f"• {_escape_clip(item, 64)}" for item in result.verdict[:4])
    if result.closing:
        detail_lines.extend(["", _escape_clip(result.closing, 100)])

    token_text = f"{max(int(total_tokens or 0), 0):,} tokens" if total_tokens else "tokens 未返回"
    archetype_line = f"🎭 <b>{_escape_clip(result.archetype, 44)}</b>\n" if result.archetype else ""
    rendered = (
        f"<b>👤 用户画像：{_escape_clip(target_label, 64)}</b>\n"
        f"<code>样本 {len(samples)} 条</code> ｜ <code>时间范围 {format_sample_date_range(samples)}</code>\n"
        f"{archetype_line}"
        f"<blockquote>{_escape_clip(result.tagline, 130)}</blockquote>\n"
        "<i>点击展开详情</i>\n"
        "<blockquote expandable>"
        + "\n".join(detail_lines)
        + "</blockquote>\n"
        f"<i>Powered by {_escape_clip(model or '未知模型', 80)} ｜ {token_text}</i>"
    )
    if len(rendered) > 4000 or _visible_html_length(rendered) > 3600:
        raise ValueError("画像富文本超过 Telegram 安全长度，已停止发送。")
    return rendered


def render_profile_rich_markdown(
    result: ProfileResult,
    *,
    target_label: str,
    samples: list[ProfileSample],
    model: str,
    total_tokens: int,
    analytics: ProfileAnalytics | None = None,
) -> str:
    sample_by_id = {sample.message_id: sample for sample in samples}
    lines = [
        f"# 👤 用户画像：{_escape_rich_markdown(target_label)}",
        "",
        f"样本 **{len(samples)} 条** ｜ 时间范围 **{_escape_rich_markdown(format_sample_date_range(samples))}**",
    ]
    if result.archetype:
        lines.extend(["", f"🎭 **{_escape_rich_markdown(result.archetype)}**"])
    lines.extend(
        [
            "",
            f"> {_escape_rich_markdown(result.tagline)}",
            "",
            "<details open><summary>点击展开详情</summary>",
        ]
    )

    if analytics is not None:
        fp_lines = format_analytics_display_lines(analytics)
        if fp_lines:
            lines.extend(["", f"## {_escape_rich_markdown(_fingerprint_heading(analytics, len(samples)))}", ""])
            lines.extend(f"- {_escape_rich_markdown(line)}" for line in fp_lines)

    lines.extend(["", "## 🧩 性格速写"])

    for trait in result.personality:
        lines.extend(
            [
                "",
                f"### “{_escape_rich_markdown(trait.title)}”",
                "",
                _escape_rich_markdown(trait.analysis)
                + _render_rich_evidence_links(trait.evidence_ids, sample_by_id),
            ]
        )

    lines.extend(
        [
            "",
            "## 🎯 兴趣与话题",
            "",
            "| 领域 | 证据与表现 |",
            "|:---|:---|",
        ]
    )
    for item in result.interests:
        detail = item.detail or "从当前样本中多次出现。"
        lines.append(
            f"| {_escape_rich_markdown(item.topic, table_cell=True)} "
            f"| {_escape_rich_markdown(detail, table_cell=True)} |"
        )

    lines.extend(["", "## 💬 代表语录"])
    for quote in result.quotes:
        link = _rich_message_link(quote.link)
        lines.append("")
        if quote.reply_context:
            lines.append(f"> ↪ 回「{_escape_rich_markdown(quote.reply_context)}」")
        lines.append(f"> “{_escape_rich_markdown(quote.text)}”{link}")
        if quote.comment:
            lines.append(f"> —— {_escape_rich_markdown(quote.comment)}")

    lines.extend(
        [
            "",
            "## ⭐ 总评",
            "",
            "| 维度 | 评分 | 点评 |",
            "|:---|:---:|:---|",
        ]
    )
    for rating in result.ratings:
        lines.append(
            f"| {_escape_rich_markdown(rating.dimension, table_cell=True)} "
            f"| {'⭐' * rating.score} "
            f"| {_escape_rich_markdown(rating.comment or '仅代表当前样本。', table_cell=True)} |"
        )
    if result.verdict:
        lines.append("")
        lines.extend(f"- {_escape_rich_markdown(item)}" for item in result.verdict)

    if result.closing:
        lines.extend(["", _escape_rich_markdown(result.closing)])
    token_text = f"{max(int(total_tokens or 0), 0):,} tokens" if total_tokens else "tokens 未返回"
    lines.extend(
        [
            "",
            f"<footer>Powered by {_escape_rich_markdown(model or '未知模型')} ｜ {token_text}</footer>",
            "</details>",
        ]
    )
    rendered = "\n".join(lines)
    if len(rendered) > _RICH_MESSAGE_MAX_CHARS:
        raise ValueError("画像 Rich Markdown 超过 Telegram 允许的 32,768 字符。")
    return rendered


def build_profile_rich_message(
    result: ProfileResult,
    *,
    target_label: str,
    samples: list[ProfileSample],
    model: str,
    total_tokens: int,
    rich_types: Any,
    analytics: ProfileAnalytics | None = None,
) -> Any:
    def plain(value: Any) -> Any:
        return rich_types.TextPlain(text=str(value or ""))

    def empty() -> Any:
        return rich_types.TextEmpty()

    def concat(items: list[Any]) -> Any:
        return rich_types.TextConcat(texts=items)

    def linked_text(value: str, links: list[str]) -> Any:
        parts = [plain(value)]
        for link in links:
            if not link:
                continue
            parts.extend(
                [
                    plain(" "),
                    rich_types.TextUrl(text=plain("↗"), url=link, webpage_id=0),
                ]
            )
        return parts[0] if len(parts) == 1 else concat(parts)

    def header_cell(value: str) -> Any:
        return rich_types.PageTableCell(
            header=True,
            align_center=True,
            valign_middle=True,
            text=plain(value),
        )

    def body_cell(value: str, *, centered: bool = False) -> Any:
        return rich_types.PageTableCell(
            align_center=True if centered else None,
            valign_middle=True,
            text=plain(value),
        )

    sample_by_id = {sample.message_id: sample for sample in samples}
    detail_blocks: list[Any] = []
    if analytics is not None:
        fp_lines = format_analytics_display_lines(analytics)
        if fp_lines:
            detail_blocks.append(rich_types.PageBlockHeader(text=plain(_fingerprint_heading(analytics, len(samples)))))
            for line in fp_lines:
                detail_blocks.append(rich_types.PageBlockParagraph(text=plain(line)))

    detail_blocks.append(rich_types.PageBlockHeader(text=plain("🧩 性格速写")))
    for trait in result.personality:
        evidence_links = [
            sample_by_id[message_id].link
            for message_id in trait.evidence_ids
            if message_id in sample_by_id and sample_by_id[message_id].link
        ]
        detail_blocks.extend(
            [
                rich_types.PageBlockSubheader(text=plain(f"“{trait.title}”")),
                rich_types.PageBlockParagraph(text=linked_text(trait.analysis, evidence_links)),
            ]
        )

    interest_rows = [
        rich_types.PageTableRow(cells=[header_cell("领域"), header_cell("证据与表现")])
    ]
    interest_rows.extend(
        rich_types.PageTableRow(
            cells=[
                body_cell(item.topic),
                body_cell(item.detail or "从当前样本中多次出现。"),
            ]
        )
        for item in result.interests
    )
    detail_blocks.extend(
        [
            rich_types.PageBlockHeader(text=plain("🎯 兴趣与话题")),
            rich_types.PageBlockTable(
                title=empty(),
                rows=interest_rows,
                bordered=True,
                striped=True,
            ),
            rich_types.PageBlockHeader(text=plain("💬 代表语录")),
        ]
    )

    for quote in result.quotes:
        quote_body = f"“{quote.text}”"
        if quote.reply_context:
            quote_body = f"↪ 回「{quote.reply_context}」\n{quote_body}"
        caption = (
            rich_types.TextItalic(text=plain(f"—— {quote.comment}"))
            if quote.comment
            else empty()
        )
        detail_blocks.append(
            rich_types.PageBlockBlockquote(
                text=linked_text(quote_body, [quote.link] if quote.link else []),
                caption=caption,
            )
        )

    rating_rows = [
        rich_types.PageTableRow(
            cells=[header_cell("维度"), header_cell("评分"), header_cell("点评")]
        )
    ]
    rating_rows.extend(
        rich_types.PageTableRow(
            cells=[
                body_cell(rating.dimension),
                body_cell("⭐" * rating.score, centered=True),
                body_cell(rating.comment or "仅代表当前样本。"),
            ]
        )
        for rating in result.ratings
    )
    detail_blocks.extend(
        [
            rich_types.PageBlockHeader(text=plain("⭐ 总评")),
            rich_types.PageBlockTable(
                title=empty(),
                rows=rating_rows,
                bordered=True,
                striped=True,
            ),
        ]
    )
    for item in result.verdict:
        detail_blocks.append(rich_types.PageBlockParagraph(text=plain(f"• {item}")))
    if result.closing:
        detail_blocks.append(rich_types.PageBlockParagraph(text=plain(result.closing)))

    token_text = f"{max(int(total_tokens or 0), 0):,} tokens" if total_tokens else "tokens 未返回"
    blocks: list[Any] = [
        rich_types.PageBlockTitle(text=plain(f"👤 用户画像：{target_label}")),
        rich_types.PageBlockParagraph(
            text=concat(
                [
                    rich_types.TextBold(text=plain(f"样本 {len(samples)} 条")),
                    plain(" ｜ "),
                    rich_types.TextBold(text=plain(f"时间范围 {format_sample_date_range(samples)}")),
                ]
            )
        ),
    ]
    if result.archetype:
        blocks.append(
            rich_types.PageBlockParagraph(
                text=rich_types.TextBold(text=plain(f"🎭 {result.archetype}"))
            )
        )
    blocks.extend(
        [
            rich_types.PageBlockBlockquote(text=plain(result.tagline), caption=empty()),
            rich_types.PageBlockDetails(
                blocks=detail_blocks,
                title=plain("点击展开详情"),
                open=True,
            ),
            rich_types.PageBlockFooter(text=plain(f"Powered by {model or '未知模型'} ｜ {token_text}")),
        ]
    )
    return rich_types.InputRichMessage(blocks=blocks, noautolink=True)


def format_sample_date_range(samples: list[ProfileSample]) -> str:
    dates = sorted(sample.date for sample in samples if sample.date is not None)
    if not dates:
        return "未知"
    fmt = "%Y-%m-%d" if dates[0].year != dates[-1].year else "%m-%d"
    start = dates[0].strftime(fmt)
    end = dates[-1].strftime(fmt)
    return start if start == end else f"{start} ~ {end}"


def format_profile_progress(*lines: str) -> str:
    detail = "\n".join(_escape(line) for line in lines if line)
    return f"<b>⏳ 用户画像分析中</b>\n<blockquote expandable>{detail}</blockquote>"


def format_profile_status(text: str) -> str:
    return f"<b>👤 用户画像</b>\n<blockquote expandable>{_escape(text)}</blockquote>"


def format_profile_hint(config: UserProfileConfig) -> str:
    prefix = config.command_prefixes[0] if config.command_prefixes else "/profile"
    all_prefix = next((item for item in config.command_prefixes if item in {"/fx", ".fx"}), prefix)
    return (
        "<b>👤 用户画像</b>\n"
        "<blockquote expandable>"
        "请回复一位群友的消息后发送 "
        f"<code>{_escape(prefix)}</code>，或使用 <code>{_escape(prefix)} @username</code>。\n"
        f"可在末尾指定样本数，例如 <code>{_escape(prefix)} 80</code>；"
        f"使用 <code>{_escape(all_prefix)} all</code> 分析所有监控群的跨群历史，"
        f"使用 <code>{_escape(all_prefix)} local</code> 只分析当前群全部历史。"
        "</blockquote>"
    )


def profile_target_label(target: Any, target_id: Any) -> str:
    username = _string_value(getattr(target, "username", "")).lstrip("@")
    if username:
        return f"@{username}"
    name = " ".join(
        part for part in (_string_value(getattr(target, "first_name", "")), _string_value(getattr(target, "last_name", ""))) if part
    ).strip()
    return name or f"用户 {target_id}"


async def _resolve_chat_username(event: Any) -> str:
    chat = getattr(event, "chat", None)
    if chat is None and hasattr(event, "get_chat"):
        try:
            chat = await event.get_chat()
        except Exception:
            logger.exception("Failed to resolve chat username for profile links")
    return _string_value(getattr(chat, "username", "")).lstrip("@") if chat is not None else ""


def _render_evidence_links(ids: list[int], sample_by_id: dict[int, ProfileSample]) -> str:
    links = [_message_anchor(sample_by_id[item].link) for item in ids if item in sample_by_id and sample_by_id[item].link]
    links = [item for item in links if item]
    return " " + " ".join(links) if links else ""


def _render_rich_evidence_links(ids: list[int], sample_by_id: dict[int, ProfileSample]) -> str:
    links = [
        _rich_message_link(sample_by_id[item].link).strip()
        for item in ids
        if item in sample_by_id and sample_by_id[item].link
    ]
    links = [item for item in links if item]
    return " " + " ".join(links) if links else ""


def _message_anchor(link: str) -> str:
    if not link:
        return ""
    return f" <a href='{html.escape(link, quote=True)}'>↗️</a>"


def _rich_message_link(link: str) -> str:
    if not link:
        return ""
    return f" [↗]({link})"


def _valid_message_ids(value: Any, valid_ids: set[int], limit: int) -> list[int]:
    output: list[int] = []
    for item in _list_value(value):
        message_id = _positive_int(item)
        if message_id in valid_ids and message_id not in output:
            output.append(message_id)
        if len(output) >= limit:
            break
    return output


def _matches_any_command(text: str, prefixes: list[str]) -> bool:
    stripped = text.strip()
    return any(
        stripped == prefix or stripped.startswith(prefix + " ") or stripped.startswith(prefix + "\n")
        for prefix in prefixes
        if prefix
    )


def _entity_id(entity: Any) -> int | None:
    return _positive_int(getattr(entity, "id", None))


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _callable_supports_parameter(func: Any, parameter: str) -> bool:
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if parameter in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _request_supports_parameter(request_type: Any, parameter: str) -> bool:
    if request_type is None:
        return False
    if parameter in getattr(request_type, "__annotations__", {}):
        return True
    try:
        return parameter in inspect.signature(request_type).parameters
    except (TypeError, ValueError):
        return False


def _bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return min(max(parsed, minimum), maximum)


def _is_group_chat_id(chat_id: Any) -> bool:
    try:
        return int(chat_id) < 0
    except (TypeError, ValueError):
        return False


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_value(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)].rstrip() + "…"


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def _escape_rich_markdown(value: Any, *, table_cell: bool = False) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    escaped = html.escape(compact, quote=False)
    escaped = re.sub(r"([\\`*_{}\[\]()~])", r"\\\1", escaped)
    escaped = re.sub(r"^(#{1,6}|[+-]|\d+\.)", r"\\\1", escaped)
    if table_cell:
        escaped = escaped.replace("|", r"\|")
    return escaped


def _escape_clip(value: Any, escaped_limit: int) -> str:
    source = str(value or "")
    parts: list[str] = []
    used = 0
    truncated = False
    for character in source:
        escaped = html.escape(character, quote=False)
        if used + len(escaped) > max(escaped_limit - 1, 0):
            truncated = True
            break
        parts.append(escaped)
        used += len(escaped)
    if truncated and escaped_limit > 0:
        parts.append("…")
    return "".join(parts)


def _visible_html_length(value: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", value)))


def _percentage(count: int, total: int) -> str:
    return f"{(count / total * 100):.1f}%" if total else "0%"
