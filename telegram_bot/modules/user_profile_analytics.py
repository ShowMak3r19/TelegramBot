from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

TZ_CN = timezone(timedelta(hours=8))

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]{3,32}")
_BOT_CMD_RE = re.compile(r"^[/.,!！\-]\s*[A-Za-z0-9_\u4e00-\u9fff@]{1,48}(?:\s+\S{1,32})?$")
_SHARE_BOILERPLATE_RE = re.compile(
    r"(?:长按)?复制(?:此链接|本段|口令|打开)?|(?:直接)?打开(?:抖音|小红书|哔哩哔哩|b站|淘宝|京东|拼多多|微信|快手)(?:搜索|查看|看看)?|看看【[^】]{0,20}】的作品",
    re.IGNORECASE,
)
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]{1,20}")
_HAN_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_PURE_SYMBOL_OR_NUM_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)
_QUESTION_END_RE = re.compile(r"[?？]|(?:吗|么|呢|咋样|怎么弄|怎么办|靠谱吗|好用吗|求问|请问|有人用过|有没有)[!！。.~～]*$")
_EMOTION_RE = re.compile(
    r"[!！]{1,}|哈哈+|笑死|卧槽|我操|我靠|离谱|牛逼|牛皮|绝了|无语|崩溃|太强|好家伙|绷不住|典中典|麻了|寄了|草+|666+|nb|lmao|wtf",
    re.IGNORECASE,
)

# 泛泛的礼貌/应答词不计入“个人特色口头禅”
_GENERIC_CATCHPHRASES = frozenset(
    {
        "哈哈",
        "哈哈哈",
        "哈哈哈哈",
        "哈哈哈哈哈",
        "嗯嗯",
        "好的",
        "好吧",
        "是的",
        "对的",
        "可以",
        "谢谢",
        "感谢",
        "收到",
        "明白",
        "知道",
        "知道了",
        "没事",
        "没问题",
        "不是",
        "没有",
        "什么",
        "怎么",
        "可以的",
        "行吧",
        "好滴",
        "好好好",
    }
)

# 仅过滤无个人辨识度的纯机械仪式/bot 触发短语；保留真实情绪口头禅（如“确实”“笑死”）
_RITUAL_EXACT_TEXTS = frozenset(
    {
        "签到",
        "打卡",
        "掉落",
        "出题",
        "抢红包",
        "领红包",
        "红包",
        "抽奖",
        "刮刮卡",
        "领福利",
        "绑定",
        "查询",
        "积分",
        "余额",
        "排行",
        "排行榜",
        "菜单",
        "帮助",
        "help",
        "start",
        "ping",
        "test",
        "+1",
        "-1",
        "+2",
        "1",
        "0",
        "ok",
    }
)

# 中文常见虚词/通用高频词（不进入个人主题特色词）
_TERM_STOP_WORDS = frozenset(
    {
        "这个", "那个", "就是", "不是", "可以", "没有", "一下", "一个", "什么", "怎么",
        "为什么", "然后", "现在", "还是", "但是", "因为", "所以", "如果", "已经", "应该",
        "可能", "感觉", "不要", "知道", "看看", "你们", "我们", "他们", "自己", "直接",
        "觉得", "其实", "不过", "而且", "或者", "虽然", "时候", "东西", "地方", "问题",
        "今天", "昨天", "明天", "最近", "一直", "一般", "一点", "一起", "好像", "有点",
        "真的", "确实", "哈哈", "哈哈哈", "哈哈哈哈", "呵呵", "嗯嗯", "好的", "可以的",
        "没事", "不用", "不行", "不错", "厉害", "这样", "那样", "这里", "那里", "里面",
        "外面", "上面", "下面", "前面", "后面", "需要", "使用", "进行", "主要", "内容",
        "消息", "回复", "群里", "群友", "大家", "别人", "人家", "出来", "进来", "过来",
        "过去", "起来", "下来", "回去", "回来", "开始", "结束", "完成", "正常", "默认",
        "左右", "大概", "基本", "完全", "特别", "非常", "比较", "稍微", "顺便", "赶紧",
        "居然", "竟然", "果然", "肯定", "必须", "只能", "只要", "只有", "为了", "关于",
        "对于", "通过", "根据", "按照", "比如", "例如", "总之", "另外", "还有", "以及",
        "the", "and", "for", "with", "this", "that", "you", "are", "not", "but", "from",
        "have", "has", "was", "were", "will", "would", "can", "could", "should", "just",
        "like", "what", "when", "where", "how", "why", "who", "http", "https", "www",
        "com", "net", "org", "cn", "html", "htm", "php", "jpg", "png", "gif", "mp4",
        "webp", "true", "false", "null", "none", "undefined", "bot", "telegram",
    }
)

# 中文 n-gram 边缘虚字：避免无分词器抽出“的电脑”“显卡了”这类碎片
_BOUNDARY_FUNCTION_CHARS = frozenset(
    "的了呢吗吧啊呀哦嘛呗着过是在有和与跟把被让给就都也还很太真好不没会能要去来到上下里中一这那我你他她它每各某本该此其之而及或若且但并却又再刚曾将正已只才挺蛮超最更"
)


@dataclass(frozen=True)
class InteractionPeer:
    user_id: int
    count: int
    label: str = ""
    is_bot: bool = False


@dataclass(frozen=True)
class GroupBreakdownItem:
    label: str
    count: int
    share_pct: float
    avg_length: float
    reply_ratio: float
    top_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineShift:
    early_range: str
    recent_range: str
    early_avg_length: float
    recent_avg_length: float
    early_reply_ratio: float
    recent_reply_ratio: float
    early_night_ratio: float
    recent_night_ratio: float
    early_terms: list[str] = field(default_factory=list)
    recent_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GroupBaselineSummary:
    sample_messages: int
    active_users: int
    median_length: float
    median_reply_ratio: float
    median_question_ratio: float
    median_night_ratio: float
    median_workday_ratio: float
    length_percentile: int | None = None
    reply_percentile: int | None = None
    question_percentile: int | None = None
    night_percentile: int | None = None
    workday_percentile: int | None = None
    activity_percentile: int | None = None


@dataclass(frozen=True)
class ProfileAnalytics:
    analyzed_count: int
    raw_count: int
    filtered_noise_count: int
    bot_cmd_count: int
    ritual_count: int
    avg_length: float
    median_length: float
    short_msg_ratio: float
    long_msg_ratio: float
    reply_ratio: float
    question_ratio: float
    exclamation_ratio: float
    url_ratio: float
    repeat_ratio: float
    bot_interaction_ratio: float
    sticker_ratio: float
    media_ratio: float
    workday_ratio: float
    evening_ratio: float
    night_ratio: float
    morning_ratio: float
    peak_hour: int | None
    active_days: int
    avg_per_active_day: float
    max_single_day: int
    schedule_label: str
    distinctive_terms: list[str] = field(default_factory=list)
    catchphrases: list[str] = field(default_factory=list)
    top_replied_to: list[InteractionPeer] = field(default_factory=list)
    top_replied_by: list[InteractionPeer] = field(default_factory=list)
    group_breakdown: list[GroupBreakdownItem] = field(default_factory=list)
    timeline_shift: TimelineShift | None = None
    baseline: GroupBaselineSummary | None = None
    rating_anchors: dict[str, str] = field(default_factory=dict)


def classify_message_noise(text: str) -> str:
    """Classify low-signal mechanical messages while keeping expressive chat phrases."""
    stripped = (text or "").strip()
    if not stripped:
        return "ritual"
    lowered = stripped.lower()
    if lowered in _RITUAL_EXACT_TEXTS:
        return "ritual"
    if len(stripped) <= 6 and _PURE_SYMBOL_OR_NUM_RE.fullmatch(stripped):
        return "ritual"
    if "\n" not in stripped and _BOT_CMD_RE.fullmatch(stripped):
        if not stripped.startswith(("http://", "https://", "//", "...", "--", "- ")):
            # 排除负数字（如 -5）以外的短横线命令（如 -re, -q）
            if not (stripped.startswith("-") and len(stripped) > 1 and stripped[1].isdigit()):
                return "bot_cmd"
    if re.fullmatch(r"/[a-zA-Z0-9_]+(?:@[a-zA-Z0-9_]+)?(?:\s+.*)?", stripped) and len(stripped) <= 64:
        return "bot_cmd"
    return ""


def filter_noise_samples(
    samples: Sequence[Any],
    *,
    min_required: int,
) -> tuple[list[Any], int, int, int]:
    """Filter mechanical bot/ritual noise; fall back to raw samples if too few remain."""
    kept: list[Any] = []
    bot_cmd_count = 0
    ritual_count = 0
    for sample in samples:
        kind = getattr(sample, "kind", "text")
        if kind != "text":
            kept.append(sample)
            continue
        noise_kind = classify_message_noise(getattr(sample, "text", ""))
        if noise_kind == "bot_cmd":
            bot_cmd_count += 1
            continue
        if noise_kind == "ritual":
            ritual_count += 1
            continue
        kept.append(sample)

    filtered_noise = bot_cmd_count + ritual_count
    if len(kept) >= max(1, int(min_required)):
        return kept, filtered_noise, bot_cmd_count, ritual_count
    return list(samples), 0, bot_cmd_count, ritual_count


def _to_cn_time(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(TZ_CN)
    return dt.astimezone(TZ_CN)


def format_sample_time_tag(dt: datetime | None) -> str:
    local = _to_cn_time(dt)
    if local is None:
        return ""
    return local.strftime("%m-%d %H:%M")


def extract_terms_from_text(text: str) -> list[str]:
    """Extract clean ASCII/tech terms and boundary-filtered Chinese 2-4 grams."""
    cleaned = _URL_RE.sub(" ", text or "")
    cleaned = _MENTION_RE.sub(" ", cleaned)
    cleaned = _SHARE_BOILERPLATE_RE.sub(" ", cleaned)
    tokens: list[str] = []

    for match in _ASCII_TOKEN_RE.finditer(cleaned):
        word = match.group(0).strip("._+-").lower()
        if len(word) < 2 or word in _TERM_STOP_WORDS or word.isdigit():
            continue
        if re.fullmatch(r"[a-z]{1,2}", word) and word not in {"ai", "pt", "qb", "ui", "os", "go", "js", "ts", "py", "ip", "tv", "pc", "vr"}:
            continue
        tokens.append(word)

    for match in _HAN_RUN_RE.finditer(cleaned):
        segment = match.group(0)
        seg_len = len(segment)
        if seg_len <= 4:
            if (
                segment not in _TERM_STOP_WORDS
                and segment[0] not in _BOUNDARY_FUNCTION_CHARS
                and segment[-1] not in _BOUNDARY_FUNCTION_CHARS
            ):
                tokens.append(segment)
            continue
        for size in (2, 3, 4):
            for idx in range(0, seg_len - size + 1):
                gram = segment[idx : idx + size]
                if gram in _TERM_STOP_WORDS:
                    continue
                if gram[0] in _BOUNDARY_FUNCTION_CHARS or gram[-1] in _BOUNDARY_FUNCTION_CHARS:
                    continue
                tokens.append(gram)
    return tokens


def _prune_subsumed_terms(counts: Counter[str], *, ratio: float = 0.72) -> Counter[str]:
    """Suppress fragment n-grams mostly contained inside a longer frequent Chinese term."""
    han_terms = [
        (term, count)
        for term, count in counts.items()
        if count >= 2 and _HAN_RUN_RE.fullmatch(term) and len(term) >= 3
    ]
    han_terms.sort(key=lambda item: (-len(item[0]), -item[1]))
    suppressed: set[str] = set()
    for longer, longer_count in han_terms:
        if longer in suppressed:
            continue
        for size in range(2, len(longer)):
            for idx in range(0, len(longer) - size + 1):
                sub = longer[idx : idx + size]
                sub_count = counts.get(sub, 0)
                if sub_count and longer_count / sub_count >= ratio:
                    suppressed.add(sub)
    return Counter({term: count for term, count in counts.items() if term not in suppressed})


def extract_distinctive_terms(
    user_texts: Sequence[str],
    group_background_texts: Sequence[str] | None = None,
    *,
    top_k: int = 8,
) -> list[str]:
    """Compute distinctive user terms using smoothed log-odds ratio vs group background."""
    user_counts: Counter[str] = Counter()
    for text in user_texts:
        # 每条消息内同词去重，避免单条刷屏撑爆词频
        user_counts.update(set(extract_terms_from_text(text)))
    if not user_counts:
        return []

    pruned_user = _prune_subsumed_terms(user_counts)
    min_count = 3 if len(user_texts) >= 40 else 2
    candidates = {term: count for term, count in pruned_user.items() if count >= min_count}
    if not candidates and min_count > 2:
        candidates = {term: count for term, count in pruned_user.items() if count >= 2}
    if not candidates:
        return []

    if not group_background_texts:
        ranked = sorted(candidates.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
        return _select_non_overlapping_terms([term for term, _ in ranked], top_k)

    bg_counts: Counter[str] = Counter()
    for text in group_background_texts:
        bg_counts.update(set(extract_terms_from_text(text)))

    total_u = max(sum(pruned_user.values()), 1)
    total_b = max(sum(bg_counts.values()), 1)
    vocab_size = max(len(set(pruned_user) | set(bg_counts)), 1)
    alpha_w = 0.5
    alpha_0 = alpha_w * vocab_size

    scored: list[tuple[float, int, str]] = []
    for term, u_cnt in candidates.items():
        b_cnt = bg_counts.get(term, 0)
        u_rate = u_cnt / total_u
        b_rate = (b_cnt + 0.5) / (total_b + 0.5 * vocab_size)
        lift = u_rate / max(b_rate, 1e-9)
        if lift < 1.35 and b_cnt > 0:
            continue
        p_u = (u_cnt + alpha_w) / (total_u + alpha_0)
        p_b = (b_cnt + alpha_w) / (total_b + alpha_0)
        logit_u = math.log(p_u / max(1.0 - p_u, 1e-9))
        logit_b = math.log(p_b / max(1.0 - p_b, 1e-9))
        variance = (1.0 / (u_cnt + alpha_w)) + (1.0 / (b_cnt + alpha_w))
        z_score = (logit_u - logit_b) / math.sqrt(variance)
        if z_score > 0.4:
            scored.append((z_score, u_cnt, term))

    if not scored:
        ranked = sorted(candidates.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
        return _select_non_overlapping_terms([term for term, _ in ranked], top_k)

    scored.sort(key=lambda item: (-item[0], -item[1], -len(item[2]), item[2]))
    return _select_non_overlapping_terms([term for _, _, term in scored], top_k)


def _has_han_overlap(a: str, b: str) -> bool:
    if not (_HAN_RUN_RE.fullmatch(a) and _HAN_RUN_RE.fullmatch(b)):
        return False
    for size in range(2, min(len(a), len(b)) + 1):
        for idx in range(0, len(a) - size + 1):
            if a[idx : idx + size] in b:
                return True
    return False


def _select_non_overlapping_terms(terms: Sequence[str], top_k: int) -> list[str]:
    selected: list[str] = []
    for term in terms:
        if any(term in existing or existing in term or _has_han_overlap(term, existing) for existing in selected):
            continue
        selected.append(term)
        if len(selected) >= top_k:
            break
    return selected


def extract_catchphrases(
    user_texts: Sequence[str],
    group_background_texts: Sequence[str] | None = None,
    *,
    top_k: int = 5,
) -> list[str]:
    """Extract repeated short expressions / verbal tics specific to this user."""
    user_phrases: Counter[str] = Counter()
    for raw in user_texts:
        compact = re.sub(r"\s+", " ", (raw or "").strip())
        if not compact or _URL_RE.search(compact):
            continue
        norm = compact.strip("。.,，!！?？~～… ").lower()
        if norm in _GENERIC_CATCHPHRASES or re.fullmatch(r"哈{2,}", norm):
            continue
        if 2 <= len(norm) <= 8 and not _PURE_SYMBOL_OR_NUM_RE.fullmatch(norm):
            if classify_message_noise(norm) == "":
                user_phrases[norm] += 1

    min_hits = 3 if len(user_texts) >= 40 else 2
    candidates = {phrase: cnt for phrase, cnt in user_phrases.items() if cnt >= min_hits}
    if not candidates:
        return []

    if not group_background_texts:
        return [phrase for phrase, _ in sorted(candidates.items(), key=lambda x: (-x[1], x[0]))[:top_k]]

    bg_phrases: Counter[str] = Counter()
    for raw in group_background_texts:
        compact = re.sub(r"\s+", " ", (raw or "").strip())
        norm = compact.strip("。.,，!！?？~～… ").lower()
        if norm in candidates:
            bg_phrases[norm] += 1

    total_u = max(len(user_texts), 1)
    total_b = max(len(group_background_texts), 1)
    scored: list[tuple[float, int, str]] = []
    for phrase, u_cnt in candidates.items():
        u_rate = u_cnt / total_u
        b_rate = (bg_phrases.get(phrase, 0) + 1.0) / (total_b + 100.0)
        lift = u_rate / max(b_rate, 1e-9)
        if lift >= 1.4 or u_cnt >= 5:
            scored.append((lift * math.log1p(u_cnt), u_cnt, phrase))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [phrase for _, _, phrase in scored[:top_k]]


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile_rank(value: float, peers: Sequence[float]) -> int | None:
    if len(peers) < 4:
        return None
    below = sum(1 for item in peers if item < value)
    equal = sum(1 for item in peers if item == value)
    pct = round((below + 0.5 * equal) / len(peers) * 100)
    return max(1, min(99, int(pct)))


def _infer_schedule_label(
    workday_ratio: float,
    evening_ratio: float,
    night_ratio: float,
    morning_ratio: float,
    peak_hour: int | None,
) -> str:
    if peak_hour is None:
        return "作息样本不足"
    if night_ratio >= 0.22:
        return f"深夜常驻型（凌晨占 {night_ratio * 100:.0f}%）"
    if workday_ratio >= 0.65 and night_ratio <= 0.06:
        return f"带薪摸鱼型（工作日白天占 {workday_ratio * 100:.0f}%）"
    if evening_ratio >= 0.50:
        return f"下班复活型（晚间占 {evening_ratio * 100:.0f}%）"
    if morning_ratio >= 0.25:
        return f"早八勤快型（清晨占 {morning_ratio * 100:.0f}%）"
    if workday_ratio >= 0.48:
        return f"白班偏多型（峰值 {peak_hour:02d}:00）"
    return f"全天候出没型（峰值 {peak_hour:02d}:00）"


def _anchor_stars(ratio_or_pct: float, thresholds: tuple[float, float, float, float]) -> int:
    t1, t2, t3, t4 = thresholds
    if ratio_or_pct >= t4:
        return 5
    if ratio_or_pct >= t3:
        return 4
    if ratio_or_pct >= t2:
        return 3
    if ratio_or_pct >= t1:
        return 2
    return 1


def _build_rating_anchors(
    *,
    avg_length: float,
    reply_ratio: float,
    question_ratio: float,
    night_ratio: float,
    workday_ratio: float,
    baseline: GroupBaselineSummary | None,
) -> dict[str, str]:
    anchors: dict[str, str] = {}
    if baseline is not None and baseline.length_percentile is not None:
        star = _anchor_stars(baseline.length_percentile, (20, 45, 70, 88))
        anchors["表达篇幅"] = f"约 {star} 星（均长 {avg_length:.1f} 字，高于本群 {baseline.length_percentile}%）"
    else:
        star = _anchor_stars(avg_length, (8, 16, 28, 45))
        anchors["表达篇幅"] = f"约 {star} 星（均长 {avg_length:.1f} 字）"

    if baseline is not None and baseline.reply_percentile is not None:
        star = _anchor_stars(baseline.reply_percentile, (20, 45, 70, 88))
        anchors["接话捧哏欲"] = f"约 {star} 星（回复率 {reply_ratio * 100:.0f}%，高于本群 {baseline.reply_percentile}%）"
    else:
        star = _anchor_stars(reply_ratio, (0.08, 0.18, 0.30, 0.45))
        anchors["接话捧哏欲"] = f"约 {star} 星（回复率 {reply_ratio * 100:.0f}%）"

    night_star = _anchor_stars(night_ratio, (0.03, 0.08, 0.16, 0.28))
    anchors["熬夜浓度"] = f"约 {night_star} 星（0–5 点占 {night_ratio * 100:.0f}%）"

    work_star = _anchor_stars(workday_ratio, (0.28, 0.45, 0.62, 0.78))
    anchors["摸鱼浓度"] = f"约 {work_star} 星（工作日白天占 {workday_ratio * 100:.0f}%）"

    q_star = _anchor_stars(question_ratio, (0.04, 0.10, 0.18, 0.28))
    anchors["提问好奇度"] = f"约 {q_star} 星（疑问句占 {question_ratio * 100:.0f}%）"
    return anchors


def compute_profile_analytics(
    samples: Sequence[Any],
    *,
    raw_count: int | None = None,
    filtered_noise_count: int = 0,
    bot_cmd_count: int = 0,
    ritual_count: int = 0,
    target_user_id: int | None = None,
    group_recent_messages: Sequence[Any] | None = None,
    peer_labels: dict[int, tuple[str, bool]] | None = None,
) -> ProfileAnalytics:
    """Compute objective, high-differentiation behavioral fingerprints for a user."""
    total_analyzed = len(samples)
    effective_raw = max(total_analyzed, int(raw_count if raw_count is not None else total_analyzed + filtered_noise_count))
    text_samples = [s for s in samples if getattr(s, "kind", "text") == "text" and getattr(s, "text", "")]
    texts = [getattr(s, "text", "") for s in text_samples]
    lengths = [len(t) for t in texts]

    avg_length = round(sum(lengths) / len(lengths), 1) if lengths else 0.0
    median_length = round(_median([float(x) for x in lengths]), 1) if lengths else 0.0
    short_msg_ratio = sum(1 for x in lengths if x <= 6) / len(lengths) if lengths else 0.0
    long_msg_ratio = sum(1 for x in lengths if x >= 40) / len(lengths) if lengths else 0.0

    reply_count = sum(1 for s in samples if getattr(s, "reply_to_message_id", None) is not None)
    reply_ratio = reply_count / total_analyzed if total_analyzed else 0.0

    question_count = sum(1 for t in texts if _QUESTION_END_RE.search(t))
    question_ratio = question_count / len(texts) if texts else 0.0

    exclamation_count = sum(1 for t in texts if _EMOTION_RE.search(t))
    exclamation_ratio = exclamation_count / len(texts) if texts else 0.0

    url_count = sum(1 for t in texts if _URL_RE.search(t))
    url_ratio = url_count / len(texts) if texts else 0.0

    normalized_texts = [re.sub(r"\s+", " ", t.strip()).lower() for t in texts if t.strip()]
    unique_texts = len(set(normalized_texts))
    repeat_ratio = (len(normalized_texts) - unique_texts) / len(normalized_texts) if normalized_texts else 0.0

    bot_interaction_ratio = (bot_cmd_count + ritual_count) / effective_raw if effective_raw else 0.0
    sticker_ratio = sum(1 for s in samples if getattr(s, "kind", "text") == "sticker") / total_analyzed if total_analyzed else 0.0
    media_ratio = sum(1 for s in samples if getattr(s, "kind", "text") != "text") / total_analyzed if total_analyzed else 0.0

    # 时区作息分布（UTC+8）
    hour_counts: Counter[int] = Counter()
    day_counts: Counter[str] = Counter()
    workday_daytime = 0
    dated_total = 0
    for s in samples:
        local = _to_cn_time(getattr(s, "date", None))
        if local is None:
            continue
        dated_total += 1
        hour_counts[local.hour] += 1
        day_counts[local.strftime("%Y-%m-%d")] += 1
        if local.weekday() < 5 and 9 <= local.hour < 18:
            workday_daytime += 1

    night_count = sum(hour_counts[h] for h in range(0, 6))
    morning_count = sum(hour_counts[h] for h in range(6, 9))
    evening_count = sum(hour_counts[h] for h in range(18, 24))
    workday_ratio = workday_daytime / dated_total if dated_total else 0.0
    night_ratio = night_count / dated_total if dated_total else 0.0
    morning_ratio = morning_count / dated_total if dated_total else 0.0
    evening_ratio = evening_count / dated_total if dated_total else 0.0
    peak_hour = hour_counts.most_common(1)[0][0] if hour_counts else None
    active_days = len(day_counts)
    avg_per_active_day = round(dated_total / active_days, 1) if active_days else 0.0
    max_single_day = max(day_counts.values()) if day_counts else 0
    schedule_label = _infer_schedule_label(workday_ratio, evening_ratio, night_ratio, morning_ratio, peak_hour)

    # 群内相对基线 & 背景文本（排除目标用户自己和明显重复播报号）
    bg_texts: list[str] = []
    baseline: GroupBaselineSummary | None = None
    replied_by_counter: Counter[int] = Counter()

    if group_recent_messages:
        group_chat_ids = {
            cid for m in group_recent_messages if (cid := getattr(m, "chat_id", None)) is not None
        }
        target_msg_keys: set[tuple[int | None, int]] = set()
        target_msg_ids_fallback: set[int] = set()
        for s in samples:
            raw_id = getattr(s, "raw_message_id", None) or getattr(s, "message_id", None)
            if raw_id is None:
                continue
            s_chat_id = getattr(s, "chat_id", None)
            if s_chat_id is not None:
                target_msg_keys.add((s_chat_id, raw_id))
            else:
                target_msg_ids_fallback.add(raw_id)

        per_sender_msgs: dict[int, list[Any]] = defaultdict(list)
        for msg in group_recent_messages:
            sid = getattr(msg, "sender_id", None)
            if sid is not None:
                per_sender_msgs[sid].append(msg)
            reply_id = getattr(msg, "reply_to_message_id", None)
            msg_chat_id = getattr(msg, "chat_id", None)
            is_reply_to_target = False
            if reply_id is not None:
                if msg_chat_id is not None and group_chat_ids:
                    is_reply_to_target = (msg_chat_id, reply_id) in target_msg_keys or (
                        not target_msg_keys and reply_id in target_msg_ids_fallback
                    )
                else:
                    is_reply_to_target = reply_id in target_msg_ids_fallback or any(
                        mid == reply_id for _, mid in target_msg_keys
                    )
            if (
                target_user_id is not None
                and sid is not None
                and sid != target_user_id
                and is_reply_to_target
            ):
                replied_by_counter[sid] += 1

        total_group = len(group_recent_messages)
        peer_lengths: list[float] = []
        peer_replies: list[float] = []
        peer_questions: list[float] = []
        peer_nights: list[float] = []
        peer_workdays: list[float] = []
        peer_counts: list[float] = []
        target_recent_count = 0

        for sid, msgs in per_sender_msgs.items():
            # 排除疑似单人占超 45% 的刷屏播报 Bot
            if total_group >= 100 and len(msgs) / total_group > 0.45:
                continue
            clean_msgs = [m for m in msgs if classify_message_noise(getattr(m, "text", "")) == ""]
            if sid == target_user_id:
                target_recent_count = len(clean_msgs)
            else:
                bg_texts.extend(getattr(m, "text", "") for m in clean_msgs)
            if len(clean_msgs) < 5:
                continue
            c_texts = [getattr(m, "text", "") for m in clean_msgs]
            c_len = sum(len(t) for t in c_texts) / len(c_texts)
            c_rep = sum(1 for m in clean_msgs if getattr(m, "reply_to_message_id", None) is not None) / len(clean_msgs)
            c_q = sum(1 for t in c_texts if _QUESTION_END_RE.search(t)) / len(c_texts)
            c_dated = 0
            c_night = 0
            c_work = 0
            for m in clean_msgs:
                local = _to_cn_time(getattr(m, "date", None) or getattr(m, "sent_at", None))
                if local is None:
                    continue
                c_dated += 1
                if 0 <= local.hour < 6:
                    c_night += 1
                if local.weekday() < 5 and 9 <= local.hour < 18:
                    c_work += 1
            peer_lengths.append(c_len)
            peer_replies.append(c_rep)
            peer_questions.append(c_q)
            peer_nights.append(c_night / c_dated if c_dated else 0.0)
            peer_workdays.append(c_work / c_dated if c_dated else 0.0)
            peer_counts.append(float(len(clean_msgs)))

        if len(peer_lengths) >= 4:
            baseline = GroupBaselineSummary(
                sample_messages=total_group,
                active_users=len(peer_lengths),
                median_length=round(_median(peer_lengths), 1),
                median_reply_ratio=_median(peer_replies),
                median_question_ratio=_median(peer_questions),
                median_night_ratio=_median(peer_nights),
                median_workday_ratio=_median(peer_workdays),
                length_percentile=_percentile_rank(avg_length, peer_lengths),
                reply_percentile=_percentile_rank(reply_ratio, peer_replies),
                question_percentile=_percentile_rank(question_ratio, peer_questions),
                night_percentile=_percentile_rank(night_ratio, peer_nights),
                workday_percentile=_percentile_rank(workday_ratio, peer_workdays),
                activity_percentile=_percentile_rank(float(target_recent_count), peer_counts)
                if target_recent_count > 0
                else None,
            )

    distinctive_terms = extract_distinctive_terms(texts, bg_texts or None, top_k=8)
    catchphrases = extract_catchphrases(texts, bg_texts or None, top_k=5)

    # 互动搭子统计
    replied_to_counter: Counter[int] = Counter()
    for s in samples:
        rsid = getattr(s, "reply_to_sender_id", None)
        if rsid is not None and rsid != target_user_id:
            replied_to_counter[rsid] += 1

    labels_map = peer_labels or {}
    top_replied_to = [
        InteractionPeer(
            user_id=uid,
            count=cnt,
            label=labels_map.get(uid, ("", False))[0],
            is_bot=labels_map.get(uid, ("", False))[1],
        )
        for uid, cnt in replied_to_counter.most_common(3)
        if cnt >= 2
    ]
    top_replied_by = [
        InteractionPeer(
            user_id=uid,
            count=cnt,
            label=labels_map.get(uid, ("", False))[0],
            is_bot=labels_map.get(uid, ("", False))[1],
        )
        for uid, cnt in replied_by_counter.most_common(3)
        if cnt >= 2
    ]

    # 跨群分布对比
    by_source: dict[str, list[Any]] = defaultdict(list)
    for s in samples:
        label = getattr(s, "source_label", "") or ""
        if label:
            by_source[label].append(s)
    group_breakdown: list[GroupBreakdownItem] = []
    if len(by_source) >= 2:
        ordered_groups = sorted(by_source.items(), key=lambda item: -len(item[1]))[:4]
        for label, g_samples in ordered_groups:
            g_texts = [getattr(s, "text", "") for s in g_samples if getattr(s, "text", "")]
            other_texts = [
                getattr(s, "text", "")
                for other_label, other_samples in by_source.items()
                if other_label != label
                for s in other_samples
                if getattr(s, "text", "")
            ]
            g_avg_len = round(sum(len(t) for t in g_texts) / len(g_texts), 1) if g_texts else 0.0
            g_reply = sum(1 for s in g_samples if getattr(s, "reply_to_message_id", None) is not None) / len(g_samples)
            g_terms = extract_distinctive_terms(g_texts, other_texts or None, top_k=3)
            group_breakdown.append(
                GroupBreakdownItem(
                    label=label,
                    count=len(g_samples),
                    share_pct=round(len(g_samples) / max(total_analyzed, 1) * 100, 1),
                    avg_length=g_avg_len,
                    reply_ratio=g_reply,
                    top_terms=g_terms,
                )
            )

    # 时间线演变（跨度 >= 21 天且样本 >= 60）
    timeline_shift: TimelineShift | None = None
    dated_samples = [s for s in samples if getattr(s, "date", None) is not None]
    if len(dated_samples) >= 60:
        ordered_dated = sorted(dated_samples, key=lambda s: getattr(s, "date"))
        first_dt = _to_cn_time(getattr(ordered_dated[0], "date"))
        last_dt = _to_cn_time(getattr(ordered_dated[-1], "date"))
        if first_dt and last_dt and (last_dt - first_dt).days >= 21:
            split = len(ordered_dated) // 2
            early = ordered_dated[:split]
            recent = ordered_dated[split:]
            early_texts = [getattr(s, "text", "") for s in early if getattr(s, "text", "")]
            recent_texts = [getattr(s, "text", "") for s in recent if getattr(s, "text", "")]
            early_night = sum(1 for s in early if 0 <= (_to_cn_time(getattr(s, "date")).hour) < 6) / len(early)
            recent_night = sum(1 for s in recent if 0 <= (_to_cn_time(getattr(s, "date")).hour) < 6) / len(recent)
            timeline_shift = TimelineShift(
                early_range=_format_date_span(early),
                recent_range=_format_date_span(recent),
                early_avg_length=round(sum(len(t) for t in early_texts) / max(len(early_texts), 1), 1),
                recent_avg_length=round(sum(len(t) for t in recent_texts) / max(len(recent_texts), 1), 1),
                early_reply_ratio=sum(1 for s in early if getattr(s, "reply_to_message_id", None) is not None) / len(early),
                recent_reply_ratio=sum(1 for s in recent if getattr(s, "reply_to_message_id", None) is not None) / len(recent),
                early_night_ratio=early_night,
                recent_night_ratio=recent_night,
                early_terms=extract_distinctive_terms(early_texts, recent_texts, top_k=4),
                recent_terms=extract_distinctive_terms(recent_texts, early_texts, top_k=4),
            )

    rating_anchors = _build_rating_anchors(
        avg_length=avg_length,
        reply_ratio=reply_ratio,
        question_ratio=question_ratio,
        night_ratio=night_ratio,
        workday_ratio=workday_ratio,
        baseline=baseline,
    )

    return ProfileAnalytics(
        analyzed_count=total_analyzed,
        raw_count=effective_raw,
        filtered_noise_count=filtered_noise_count,
        bot_cmd_count=bot_cmd_count,
        ritual_count=ritual_count,
        avg_length=avg_length,
        median_length=median_length,
        short_msg_ratio=short_msg_ratio,
        long_msg_ratio=long_msg_ratio,
        reply_ratio=reply_ratio,
        question_ratio=question_ratio,
        exclamation_ratio=exclamation_ratio,
        url_ratio=url_ratio,
        repeat_ratio=repeat_ratio,
        bot_interaction_ratio=bot_interaction_ratio,
        sticker_ratio=sticker_ratio,
        media_ratio=media_ratio,
        workday_ratio=workday_ratio,
        evening_ratio=evening_ratio,
        night_ratio=night_ratio,
        morning_ratio=morning_ratio,
        peak_hour=peak_hour,
        active_days=active_days,
        avg_per_active_day=avg_per_active_day,
        max_single_day=max_single_day,
        schedule_label=schedule_label,
        distinctive_terms=distinctive_terms,
        catchphrases=catchphrases,
        top_replied_to=top_replied_to,
        top_replied_by=top_replied_by,
        group_breakdown=group_breakdown,
        timeline_shift=timeline_shift,
        baseline=baseline,
        rating_anchors=rating_anchors,
    )


def _format_date_span(samples: Sequence[Any]) -> str:
    dates = [_to_cn_time(getattr(s, "date", None)) for s in samples]
    valid = sorted(d for d in dates if d is not None)
    if not valid:
        return "未知"
    fmt = "%Y-%m-%d" if valid[0].year != valid[-1].year else "%m-%d"
    start = valid[0].strftime(fmt)
    end = valid[-1].strftime(fmt)
    return start if start == end else f"{start}~{end}"


def with_resolved_peer_labels(
    analytics: ProfileAnalytics,
    labels: dict[int, tuple[str, bool]],
) -> ProfileAnalytics:
    if not labels:
        return analytics
    replied_to = [
        InteractionPeer(
            user_id=peer.user_id,
            count=peer.count,
            label=labels.get(peer.user_id, (peer.label, peer.is_bot))[0],
            is_bot=labels.get(peer.user_id, (peer.label, peer.is_bot))[1],
        )
        for peer in analytics.top_replied_to
    ]
    replied_by = [
        InteractionPeer(
            user_id=peer.user_id,
            count=peer.count,
            label=labels.get(peer.user_id, (peer.label, peer.is_bot))[0],
            is_bot=labels.get(peer.user_id, (peer.label, peer.is_bot))[1],
        )
        for peer in analytics.top_replied_by
    ]
    return ProfileAnalytics(
        analyzed_count=analytics.analyzed_count,
        raw_count=analytics.raw_count,
        filtered_noise_count=analytics.filtered_noise_count,
        bot_cmd_count=analytics.bot_cmd_count,
        ritual_count=analytics.ritual_count,
        avg_length=analytics.avg_length,
        median_length=analytics.median_length,
        short_msg_ratio=analytics.short_msg_ratio,
        long_msg_ratio=analytics.long_msg_ratio,
        reply_ratio=analytics.reply_ratio,
        question_ratio=analytics.question_ratio,
        exclamation_ratio=analytics.exclamation_ratio,
        url_ratio=analytics.url_ratio,
        repeat_ratio=analytics.repeat_ratio,
        bot_interaction_ratio=analytics.bot_interaction_ratio,
        sticker_ratio=analytics.sticker_ratio,
        media_ratio=analytics.media_ratio,
        workday_ratio=analytics.workday_ratio,
        evening_ratio=analytics.evening_ratio,
        night_ratio=analytics.night_ratio,
        morning_ratio=analytics.morning_ratio,
        peak_hour=analytics.peak_hour,
        active_days=analytics.active_days,
        avg_per_active_day=analytics.avg_per_active_day,
        max_single_day=analytics.max_single_day,
        schedule_label=analytics.schedule_label,
        distinctive_terms=analytics.distinctive_terms,
        catchphrases=analytics.catchphrases,
        top_replied_to=replied_to,
        top_replied_by=replied_by,
        group_breakdown=analytics.group_breakdown,
        timeline_shift=analytics.timeline_shift,
        baseline=analytics.baseline,
        rating_anchors=analytics.rating_anchors,
    )


def format_analytics_for_prompt(analytics: ProfileAnalytics) -> str:
    """Format objective behavioral fingerprints into a dense factual block for LLM prompts."""
    lines: list[str] = ["【本地客观行为指纹（硬事实，分析时请优先引用，禁止无视或编造）】"]
    length_note = f"均长 {analytics.avg_length} 字（中位 {analytics.median_length} 字，≤6字短句 {analytics.short_msg_ratio * 100:.0f}%，≥40字长文 {analytics.long_msg_ratio * 100:.0f}%）"
    if analytics.baseline and analytics.baseline.length_percentile is not None:
        length_note += f"；高于本群 {analytics.baseline.length_percentile}% 的活跃群友（本群中位 {analytics.baseline.median_length} 字）"
    lines.append(f"- 表达长度：{length_note}")

    if analytics.peak_hour is not None:
        sched = (
            f"{analytics.schedule_label}｜工作日白天(09-18) {analytics.workday_ratio * 100:.0f}%"
            f" / 晚间(18-24) {analytics.evening_ratio * 100:.0f}%"
            f" / 深夜(00-06) {analytics.night_ratio * 100:.0f}%"
            f"｜活跃 {analytics.active_days} 天（活跃日均 {analytics.avg_per_active_day} 条，单日峰值 {analytics.max_single_day} 条）"
        )
        if analytics.baseline and analytics.baseline.night_percentile is not None:
            sched += f"；熬夜度高于本群 {analytics.baseline.night_percentile}%"
        lines.append(f"- 作息节律：{sched}")

    interact = (
        f"回复接话率 {analytics.reply_ratio * 100:.0f}%"
        f"｜疑问提问率 {analytics.question_ratio * 100:.0f}%"
        f"｜情绪词占比 {analytics.exclamation_ratio * 100:.0f}%"
        f"｜重复句率 {analytics.repeat_ratio * 100:.0f}%"
    )
    if analytics.url_ratio >= 0.03:
        interact += f"｜发链接率 {analytics.url_ratio * 100:.0f}%"
    if analytics.baseline:
        extras: list[str] = []
        if analytics.baseline.reply_percentile is not None:
            extras.append(f"回复率高于本群 {analytics.baseline.reply_percentile}%")
        if analytics.baseline.question_percentile is not None:
            extras.append(f"提问率高于本群 {analytics.baseline.question_percentile}%")
        if analytics.baseline.activity_percentile is not None:
            extras.append(f"近期话痨度高于本群 {analytics.baseline.activity_percentile}%")
        if extras:
            interact += "（" + "，".join(extras) + "）"
    lines.append(f"- 互动习惯：{interact}")

    if analytics.bot_interaction_ratio >= 0.03 or analytics.filtered_noise_count > 0:
        lines.append(
            f"- 机械/Bot 交互：原始 {analytics.raw_count} 条中含指令 {analytics.bot_cmd_count} 条、"
            f"抽奖/签到等仪式短语 {analytics.ritual_count} 条（合计占比 {analytics.bot_interaction_ratio * 100:.0f}%，已从下方语义样本尽量洗净）"
        )

    if analytics.distinctive_terms:
        lines.append("- 相对本群个人专属高频词（已剔除全群公用热词）：" + "、".join(analytics.distinctive_terms))
    if analytics.catchphrases:
        lines.append("- 个人惯用口头禅/短句：" + "、".join(f"「{item}」" for item in analytics.catchphrases))

    named_to = [p for p in analytics.top_replied_to if p.label]
    named_by = [p for p in analytics.top_replied_by if p.label]
    if named_to or named_by:
        parts: list[str] = []
        if named_to:
            parts.append(
                "最常回复 " + "、".join(f"{p.label}{'(Bot)' if p.is_bot else ''}({p.count}次)" for p in named_to)
            )
        if named_by:
            parts.append(
                "最常被 " + "、".join(f"{p.label}{'(Bot)' if p.is_bot else ''}({p.count}次)" for p in named_by) + " 回复"
            )
        lines.append("- 群内互动搭子：" + "；".join(parts))

    if analytics.group_breakdown:
        g_parts = []
        for item in analytics.group_breakdown:
            terms_note = f"，偏爱词：{'/'.join(item.top_terms)}" if item.top_terms else ""
            g_parts.append(f"{item.label}({item.share_pct:.0f}%，均{item.avg_length}字，回复率{item.reply_ratio * 100:.0f}%{terms_note})")
        lines.append("- 跨群分布反差：" + " ｜ ".join(g_parts))

    if analytics.timeline_shift:
        ts = analytics.timeline_shift
        early_terms = "/".join(ts.early_terms) if ts.early_terms else "无明显偏重"
        recent_terms = "/".join(ts.recent_terms) if ts.recent_terms else "无明显偏重"
        lines.append(
            f"- 跨时期演变：早期({ts.early_range}) 均{ts.early_avg_length}字/回复{ts.early_reply_ratio * 100:.0f}%/深夜{ts.early_night_ratio * 100:.0f}% [高频:{early_terms}] "
            f"→ 近期({ts.recent_range}) 均{ts.recent_avg_length}字/回复{ts.recent_reply_ratio * 100:.0f}%/深夜{ts.recent_night_ratio * 100:.0f}% [高频:{recent_terms}]"
        )

    if analytics.rating_anchors:
        anchor_text = "；".join(f"{k}:{v}" for k, v in analytics.rating_anchors.items())
        lines.append(f"- 客观评分锚点（请据此拉开 1-5 星差距，禁止全员 4-5 星）：{anchor_text}")

    return "\n".join(lines)


def format_analytics_display_lines(analytics: ProfileAnalytics) -> list[str]:
    """Build concise, high-signal display lines for Telegram profile cards."""
    lines: list[str] = []
    # 1. 节奏与作息
    part1: list[str] = [f"均长 {analytics.avg_length} 字"]
    if analytics.baseline and analytics.baseline.length_percentile is not None:
        pct = analytics.baseline.length_percentile
        part1[0] += f"（{'高于' if pct >= 50 else '短于'}本群 {pct if pct >= 50 else 100 - pct}%）"
    if analytics.peak_hour is not None:
        part1.append(f"峰值 {analytics.peak_hour:02d}:00")
        part1.append(f"白天 {analytics.workday_ratio * 100:.0f}% / 深夜 {analytics.night_ratio * 100:.0f}%")
    lines.append("⏱ " + " · ".join(part1))

    # 2. 互动特征
    part2: list[str] = [f"回复率 {analytics.reply_ratio * 100:.0f}%"]
    if analytics.baseline and analytics.baseline.reply_percentile is not None:
        part2[0] += f"（前 {max(1, 100 - analytics.baseline.reply_percentile)}%）" if analytics.baseline.reply_percentile >= 70 else ""
    part2.append(f"提问率 {analytics.question_ratio * 100:.0f}%")
    if analytics.bot_interaction_ratio >= 0.08:
        part2.append(f"Bot/抽奖占比 {analytics.bot_interaction_ratio * 100:.0f}%")
    elif analytics.active_days >= 2:
        part2.append(f"活跃 {analytics.active_days} 天")
    lines.append("💬 " + " · ".join(part2))

    # 3. 个人专属词 & 口头禅
    vocab_parts: list[str] = []
    if analytics.distinctive_terms:
        vocab_parts.append("专属词：" + " / ".join(analytics.distinctive_terms[:6]))
    if analytics.catchphrases:
        vocab_parts.append("口头禅：" + " / ".join(f"「{p}」" for p in analytics.catchphrases[:3]))
    if vocab_parts:
        lines.append("🏷 " + " ｜ ".join(vocab_parts))

    # 4. 互动搭子
    named_to = [p for p in analytics.top_replied_to if p.label][:2]
    named_by = [p for p in analytics.top_replied_by if p.label][:2]
    if named_to or named_by:
        social_parts: list[str] = []
        if named_to:
            social_parts.append("常回复 " + "、".join(f"{p.label}({p.count})" for p in named_to))
        if named_by:
            social_parts.append("常被 " + "、".join(f"{p.label}({p.count})" for p in named_by) + " 回复")
        lines.append("🤝 " + " ｜ ".join(social_parts))

    # 5. 跨群分布
    if analytics.group_breakdown:
        g_line = " · ".join(
            f"{item.label} {item.share_pct:.0f}%(均{item.avg_length}字)"
            for item in analytics.group_breakdown[:3]
        )
        lines.append("🌐 " + g_line)

    return lines


def select_informative_samples(
    samples: Sequence[Any],
    count: int,
    *,
    distinctive_terms: Sequence[str] = (),
) -> list[Any]:
    """Stratified chronological sampling preferring high-information messages while keeping ends."""
    total = len(samples)
    if count >= total:
        return list(samples)
    if count <= 1:
        return [samples[-1]]
    if count == 2:
        return [samples[0], samples[-1]]

    terms_lower = [t.lower() for t in distinctive_terms if t]
    seen_counts: Counter[str] = Counter(
        re.sub(r"\s+", " ", (getattr(s, "text", "") or "").strip()).lower()
        for s in samples
    )

    def _score(sample: Any) -> float:
        text = getattr(sample, "text", "") or ""
        norm = re.sub(r"\s+", " ", text.strip()).lower()
        score = 0.0
        length = len(text)
        if 15 <= length <= 220:
            score += 4.0
        elif 8 <= length < 15 or length > 220:
            score += 2.0
        elif length <= 4:
            score -= 2.0
        if getattr(sample, "reply_context", ""):
            score += 3.0
        if terms_lower:
            hits = sum(1 for term in terms_lower if term in norm)
            score += min(hits * 3.0, 9.0)
        if _QUESTION_END_RE.search(text):
            score += 1.0
        if seen_counts.get(norm, 1) > 1:
            score -= min(4.0, float(seen_counts[norm] - 1))
        else:
            score += 1.5
        return score

    middle = list(samples[1:-1])
    target_middle = count - 2
    bucket_count = min(target_middle, max(1, target_middle))
    chosen_indices: list[int] = []
    # 将中间区间均匀划分为 target_middle 个时间桶，每桶选信息得分最高的一条
    step = len(middle) / bucket_count
    for b in range(bucket_count):
        start = int(b * step)
        end = int((b + 1) * step)
        if end <= start:
            end = min(len(middle), start + 1)
        if start >= len(middle):
            break
        best_idx = max(range(start, end), key=lambda idx: (_score(middle[idx]), idx))
        chosen_indices.append(best_idx)

    selected = [samples[0]]
    selected.extend(middle[idx] for idx in sorted(set(chosen_indices)))
    selected.append(samples[-1])
    return selected
