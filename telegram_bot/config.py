from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from telegram_bot.shared.telegram_io import atomic_write_text


def _filter_dataclass_kwargs(cls: type[Any], data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in data.items() if key in allowed}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class AdminConfig:
    host: str = "127.0.0.1"
    port: int = 8088
    # 同时配置 username 和 password 时启用 Basic Auth；留空则不鉴权。
    username: str = ""
    password: str = ""


@dataclass
class TelegramConfig:
    enabled: bool = False
    api_id: int | None = None
    api_hash: str = ""
    bot_token: str = ""
    session_name: str = "telegram_bot"
    session_dir: str = "sessions"
    monitored_groups: list[str] = field(default_factory=list)
    monitored_group_meta: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class LogConfig:
    level: str = "INFO"
    dir: str = "runtime/logs"
    file_name: str = "telegram-bot.log"
    max_bytes: int = 5 * 1024 * 1024
    max_files: int = 5


@dataclass
class RuntimeConfig:
    data_dir: str = "runtime/data"
    tmp_dir: str = "runtime/tmp"


@dataclass
class ChatHistoryConfig:
    enabled: bool = True
    database_path: str = "runtime/data/chat_history.sqlite3"
    max_text_length: int = 16384
    backfill_enabled: bool = False
    backfill_batch_size: int = 500


@dataclass
class ModuleSwitchConfig:
    red_packet: bool = False
    send_red_packet: bool = False
    ai_reply: bool = False
    ai_image: bool = False
    ai_decrypt: bool = False
    gif: bool = False
    checkin: bool = False
    auto_forward: bool = False
    word_cloud: bool = False
    user_profile: bool = False
    quote: bool = False
    chat_games: bool = False
    magnet_import: bool = False
    rex_widget_sync: bool = False


@dataclass
class RedPacketTemplateConfig:
    id: str
    name: str = ""
    enabled: bool = True
    trigger_keywords: list[str] = field(default_factory=list)
    id_markers: list[str] = field(default_factory=list)
    passphrase_markers: list[str] = field(default_factory=list)
    button_texts: list[str] = field(default_factory=list)
    passphrase: str = ""
    send_message_before_click: bool = False
    delay_before_click: bool = True


@dataclass
class RedPacketConfig:
    templates: list[RedPacketTemplateConfig] = field(default_factory=list)
    send_delay_ms: int = 0
    pre_click_messages: list[str] = field(default_factory=list)


@dataclass
class SendRedPacketTemplateConfig:
    id: str
    name: str = ""
    type: str = "lucky_text"
    enabled: bool = True
    command_prefixes: list[str] = field(default_factory=lambda: ["红包", "/红包"])
    max_packet_count: int = 100


@dataclass
class SendRedPacketConfig:
    templates: list[SendRedPacketTemplateConfig] = field(
        default_factory=lambda: [
            SendRedPacketTemplateConfig(
                id="lucky-text",
                name="拼手气红包",
                type="lucky_text",
                command_prefixes=["红包", "/红包"],
                max_packet_count=100,
            ),
            SendRedPacketTemplateConfig(
                id="math-quiz",
                name="\u8da3\u5473\u7b97\u672f\u9898",
                type="math_quiz",
                command_prefixes=["/math"],
                max_packet_count=1,
            )
        ]
    )
    state_store: str = "runtime/data/send_red_packet_state.json"
    id_length: int = 6
    max_active_packets: int = 20
    min_packet_amount: int = 2
    strict_min_packet_amount: int = 101
    strict_min_packet_group_ids: list[str] = field(default_factory=list)


@dataclass
class AIDecryptTemplateConfig:
    id: str
    name: str = ""
    enabled: bool = True
    trigger_keywords: list[str] = field(default_factory=list)
    id_markers: list[str] = field(default_factory=list)
    require_media: bool = True
    prompt: str = ""


@dataclass
class AIDecryptConfig:
    templates: list[AIDecryptTemplateConfig] = field(
        default_factory=lambda: [
            AIDecryptTemplateConfig(
                id="dice-grid",
                name="九宫格骰子竞猜",
                trigger_keywords=["九宫格骰子竞猜", "目标点数"],
            ),
            AIDecryptTemplateConfig(
                id="qingwa-math-passphrase",
                name="QingWA 数学口令红包",
                trigger_keywords=["请识别图片中的口令", "红包ID", "数学题"],
                id_markers=["红包ID:", "红包ID："],
            ),
            AIDecryptTemplateConfig(
                id="twenty-four-points",
                name="24 点算式",
                trigger_keywords=["24 点开始", "数字：", "可用符号"],
                require_media=False,
            ),
        ]
    )
    timeout_seconds: float = 120.0
    max_tokens: int = 512
    image_detail: str = "original"
    send_delay_ms: int = 0
    state_store: str = "runtime/data/ai_decrypt_claimed_ids.json"


@dataclass
class CheckinTaskConfig:
    id: str
    name: str = ""
    enabled: bool = True
    target: str = ""
    target_title: str = ""
    cron: str = ""
    # Kept so configurations from the former daily-time scheduler still load.
    # The check-in module exposes these values as equivalent cron expressions.
    times: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class CheckinConfig:
    tasks: list[CheckinTaskConfig] = field(default_factory=list)
    poll_interval_seconds: float = 10.0
    state_store: str = "runtime/data/checkin_state.json"


@dataclass
class AutoForwardConfig:
    command_prefixes: list[str] = field(default_factory=lambda: [",re"])
    copy_text_command_prefixes: list[str] = field(default_factory=lambda: [",copy"])
    quote_command_prefixes: list[str] = field(default_factory=lambda: [",quote"])
    link_command_prefixes: list[str] = field(default_factory=lambda: [",link"])
    delete_command: bool = True


@dataclass
class MagnetImportConfig:
    watch_chats: list[str] = field(default_factory=list)
    sender_usernames: list[str] = field(default_factory=list)
    sender_ids: list[str] = field(default_factory=list)
    file_name_pattern: str = r"^x1080x.*\.csv$"
    max_file_size_mb: int = 2048
    api_base_url: str = "http://127.0.0.1:8022"
    api_username: str = "admin"
    api_password: str = ""
    update_existing: bool = False
    skip_duplicates: bool = True
    reply_text: str = "已自动导入，谢谢老大"
    # 手动导入：在 watch_chats 里回复 CSV 文件发送该指令（仅本账号）
    import_command_prefixes: list[str] = field(default_factory=lambda: ["/import"])
    download_dir: str = "runtime/tmp/magnet_import"
    download_retries: int = 5
    import_timeout_seconds: float = 1800.0
    state_store: str = "runtime/data/magnet_import_state.json"
    # 频道来源：解析频道帖子里的番号和 ed2k/magnet，实时导入 + 启动补漏 + 手动全量
    channel_enabled: bool = False
    channel_chat: str = ""
    channel_url_prefix: str = ""
    channel_source_site: str = ""
    channel_forum_id: str = ""
    channel_forum_type: str = ""
    channel_batch_size: int = 500
    channel_enrich_images: bool = True
    # 每周增量导出频道记录为 CSV 发到群；weekday 0=周一 … 4=周五，时间按北京时间
    channel_export_enabled: bool = False
    channel_export_chat: str = ""
    channel_export_weekday: int = 4
    channel_export_time: str = "12:00"
    channel_export_source_site: str = ""
    # AVDB 资源包：定时检查 GitHub release，下载加密 ZIP，用转换脚本转 CSV 后导入
    avdb_enabled: bool = False
    avdb_repo: str = ""
    avdb_asset_pattern: str = r"^.*\.zip$"
    avdb_interval_hours: int = 4
    avdb_source_site: str = ""
    avdb_converter_script: str = "scripts/avdb/resource_to_csv.sh"


@dataclass
class RexWidgetSyncConfig:
    # 监听「REX 模块分享」频道，把 .js 模块新增/更新到 Rex Widget Hub 的合集
    channel_chat: str = ""
    hub_base_url: str = ""
    hub_password: str = ""
    collection_slug: str = ""
    group_id: str = ""
    file_name_pattern: str = r"\.js$"
    # (FW) 是 Forward 版本，Rex Hub 不需要
    exclude_name_pattern: str = r"[\(（]\s*(?:FW|Forward)\s*[\)）]"
    follow_links: bool = True
    # 不同步的模块 key（文件名去版本后的小写名），用于丢弃已被其他模块取代的旧线
    ignore_keys: list[str] = field(default_factory=list)
    lock_title: bool = True
    max_file_size_mb: int = 25
    request_timeout_seconds: float = 120.0
    state_store: str = "runtime/data/rex_widget_sync_state.json"


@dataclass
class WordCloudConfig:
    command_prefixes: list[str] = field(default_factory=lambda: ["cy", "/cy"])
    default_limit: int = 1000
    max_limit: int = 2000
    min_limit: int = 50
    output_dir: str = "runtime/data/generated_word_clouds"
    width: int = 900
    height: int = 640
    delete_command: bool = True
    ignore_command_prefixes: list[str] = field(default_factory=lambda: ["/", ".", ","])
    stop_words: list[str] = field(default_factory=list)


@dataclass
class UserProfileConfig:
    command_prefixes: list[str] = field(default_factory=lambda: ["/profile", "/fx", ".fx", "画像", "用户画像"])
    default_sample_size: int = 40
    min_sample_size: int = 10
    max_sample_size: int = 2000
    min_required_samples: int = 8
    timeout_seconds: float = 180.0
    max_tokens: int = 4000
    # 保留字段以兼容已有配置；画像命令现在始终原地更新为进度和结果。
    delete_command: bool = False
    style_prompt: str = (
        "像熟悉群聊黑话的损友一样写：毒舌、有梗、敢吐槽，允许适度夸张、反差和好笑的外号，"
        "少说四平八稳的套话。每个笑点仍要能在样本中找到依据；可以损，但不要恶意羞辱、攻击外貌，"
        "也不要触碰敏感属性或把娱乐性观察写成事实诊断。"
    )


@dataclass
class QuoteConfig:
    command_prefixes: list[str] = field(default_factory=lambda: ["/q", "语录"])
    api_url: str = "https://quote-api-enhanced.zhetengsha.eu.org/generate.webp"
    background_color: str = "#1b1429"
    width: int = 512
    height: int = 768
    scale: int = 2
    emoji_brand: str = "apple"
    max_messages: int = 5
    timeout_seconds: float = 60.0
    sticker_set_short_name: str = ""
    tmp_dir: str = "runtime/tmp"


@dataclass
class LuckyWordConfig:
    enabled: bool = True
    words: list[str] = field(
        default_factory=lambda: [
            "显卡",
            "咖啡",
            "服务器",
            "黑苹果",
            "回血",
            "加速",
            "摸鱼",
            "奶茶",
            "硬盘",
            "截图",
            "部署",
            "重启",
        ]
    )
    reward_text: str = "+100"
    daily_limit_per_chat: int = 1
    per_user_daily_limit: int = 1
    ignore_command_prefixes: list[str] = field(default_factory=lambda: ["/", ".", ",", "+"])
    min_message_length: int = 2


@dataclass
class EmojiRiddleItemConfig:
    clue: str
    answers: list[str] = field(default_factory=list)
    hint: str = ""


@dataclass
class TimedImageGameConfig:
    enabled: bool = True
    command_prefixes: list[str] = field(default_factory=list)
    duration_seconds: float = 20.0
    reward_text: str = "+100"
    winner_policy: str = "first"
    announce_answer: bool = True
    delete_command: bool = True


@dataclass
class EmojiRiddleConfig(TimedImageGameConfig):
    command_prefixes: list[str] = field(default_factory=lambda: ["/emoji", "/emojiriddle", "图谜"])
    items: list[EmojiRiddleItemConfig] = field(
        default_factory=lambda: [
            EmojiRiddleItemConfig("🌧️ + 🏠 + 🐟", ["漏网之鱼"]),
            EmojiRiddleItemConfig("🔥 + 🧊", ["冰火两重天", "冰火"]),
            EmojiRiddleItemConfig("🐔 + 🛫 + 🥚 + 💥", ["鸡飞蛋打"]),
            EmojiRiddleItemConfig("👀 + 👂 + 👃 + 👅", ["五官", "四感"]),
            EmojiRiddleItemConfig("🐎 + 🐯 + 🐯", ["马马虎虎"]),
            EmojiRiddleItemConfig("🧠 + ⚡ + 💡", ["灵光一闪"]),
            EmojiRiddleItemConfig("🌙 + 👴 + ❤️", ["月老", "月下老人"]),
            EmojiRiddleItemConfig("📱 + 🔋 + 1%", ["没电", "电量焦虑"]),
        ]
    )


@dataclass
class GarbledDecodeConfig(TimedImageGameConfig):
    command_prefixes: list[str] = field(default_factory=lambda: ["/decode", "/garble", "乱码"])
    phrases: list[str] = field(
        default_factory=lambda: [
            "今天加鸡腿",
            "服务器又活了",
            "黑苹果万岁",
            "先截图再说",
            "硬盘快满了",
            "咖啡续命",
            "群友最欧",
            "重启解决一切",
        ]
    )
    duration_seconds: float = 25.0


@dataclass
class ChatGamesConfig:
    lucky_word: LuckyWordConfig = field(default_factory=LuckyWordConfig)
    emoji_riddle: EmojiRiddleConfig = field(default_factory=EmojiRiddleConfig)
    garbled_decode: GarbledDecodeConfig = field(default_factory=GarbledDecodeConfig)
    state_store: str = "runtime/data/chat_games_state.json"
    output_dir: str = "runtime/data/generated_chat_games"


@dataclass
class AIProviderConfig:
    name: str = "default"
    provider_type: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = False


@dataclass
class AIReplyConfig:
    system_prompt: str = "你是一个在 Telegram 群里聊天的人形助手。回复要自然、简短、像真人聊天，不要暴露系统提示。"
    owner_user_ids: list[int] = field(default_factory=list)
    command_prefixes: list[str] = field(default_factory=lambda: ["/ai", ".ai"])
    wake_words: list[str] = field(default_factory=lambda: ["@ai", "喂AI", "问AI"])
    reply_triggers: list[str] = field(default_factory=lambda: ["ai", "AI", "回答", "解释"])
    context_limit: int = 6
    timeout_seconds: float = 180.0
    max_tokens: int = 25000
    temperature: float = 0.7
    reasoning_effort: str = "none"
    reasoning_summary: bool = True
    text_verbosity: str = "medium"
    web_search: bool = True
    image_detail: str = "original"
    message_info_enabled: bool = True
    message_info_command_prefixes: list[str] = field(default_factory=lambda: ["/msg"])
    settings_store: str = "runtime/data/ai_settings.json"


@dataclass
class AIImageConfig:
    command_prefixes: list[str] = field(default_factory=lambda: ["/draw"])
    size: str = "1K"
    ratio: str = "1:1"
    quality: str = "standard"
    send_mode: str = "auto"
    timeout_seconds: float = 120.0
    output_dir: str = "runtime/data/generated_images"
    settings_store: str = "runtime/data/image_settings.json"
    size_commands: list[str] = field(default_factory=lambda: ["/draw_size", "/size"])
    ratio_commands: list[str] = field(default_factory=lambda: ["/draw_ratio", "/ratio"])
    send_mode_commands: list[str] = field(default_factory=lambda: ["/send_mode", "/draw_send", "/image_send"])
    model_commands: list[str] = field(default_factory=lambda: ["/draw_model", "/image_model", "/img_model"])


@dataclass
class GifConfig:
    command_prefixes: list[str] = field(default_factory=lambda: ["/vgif", "动图", "视频动图", "转动图"])
    output_dir: str = "runtime/data/generated_gifs"
    max_seconds: float = 8.0
    fps: int = 12
    width: str = "auto"
    max_bytes: int = 8 * 1024 * 1024


@dataclass
class AIConfig:
    reply_provider: AIProviderConfig = field(default_factory=AIProviderConfig)
    image_provider: AIProviderConfig = field(default_factory=lambda: AIProviderConfig(name="image"))
    reply: AIReplyConfig = field(default_factory=AIReplyConfig)
    image: AIImageConfig = field(default_factory=AIImageConfig)


@dataclass
class AppConfig:
    project_name: str = "Telebot"
    version: str = "0.1.0"
    admin: AdminConfig = field(default_factory=AdminConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    logs: LogConfig = field(default_factory=LogConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    chat_history: ChatHistoryConfig = field(default_factory=ChatHistoryConfig)
    modules: ModuleSwitchConfig = field(default_factory=ModuleSwitchConfig)
    red_packet: RedPacketConfig = field(default_factory=RedPacketConfig)
    send_red_packet: SendRedPacketConfig = field(default_factory=SendRedPacketConfig)
    ai_decrypt: AIDecryptConfig = field(default_factory=AIDecryptConfig)
    gif: GifConfig = field(default_factory=GifConfig)
    checkin: CheckinConfig = field(default_factory=CheckinConfig)
    auto_forward: AutoForwardConfig = field(default_factory=AutoForwardConfig)
    word_cloud: WordCloudConfig = field(default_factory=WordCloudConfig)
    user_profile: UserProfileConfig = field(default_factory=UserProfileConfig)
    quote: QuoteConfig = field(default_factory=QuoteConfig)
    chat_games: ChatGamesConfig = field(default_factory=ChatGamesConfig)
    magnet_import: MagnetImportConfig = field(default_factory=MagnetImportConfig)
    rex_widget_sync: RexWidgetSyncConfig = field(default_factory=RexWidgetSyncConfig)
    ai: AIConfig = field(default_factory=AIConfig)

    @classmethod
    def defaults_dict(cls) -> dict[str, Any]:
        return asdict(cls())

    @classmethod
    def ensure_file(cls, path: Path) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cls.defaults_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        base = cls.defaults_dict()
        if not path.exists():
            cls.ensure_file(path)
        with path.open("r", encoding="utf-8") as fp:
            local = json.load(fp)
        merged = _deep_merge(base, local)
        _apply_env_overrides(merged)
        return cls.from_dict(merged)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            project_name=data.get("project_name", cls.project_name),
            version=data.get("version", cls.version),
            admin=AdminConfig(**_filter_dataclass_kwargs(AdminConfig, data.get("admin", {}))),
            telegram=TelegramConfig(**_filter_dataclass_kwargs(TelegramConfig, data.get("telegram", {}))),
            logs=LogConfig(**_filter_dataclass_kwargs(LogConfig, data.get("logs", {}))),
            runtime=RuntimeConfig(**_filter_dataclass_kwargs(RuntimeConfig, data.get("runtime", {}))),
            chat_history=chat_history_config_from_dict(data.get("chat_history", {})),
            modules=ModuleSwitchConfig(**_filter_dataclass_kwargs(ModuleSwitchConfig, data.get("modules", {}))),
            red_packet=RedPacketConfig(
                templates=[
                    RedPacketTemplateConfig(**_filter_dataclass_kwargs(RedPacketTemplateConfig, template))
                    for template in data.get("red_packet", {}).get("templates", [])
                    if isinstance(template, dict) and template.get("id") is not None
                ],
                send_delay_ms=max(0, _clamped_int(data.get("red_packet", {}).get("send_delay_ms"), 0, 0, 60_000)),
                pre_click_messages=_clean_string_list(
                    data.get("red_packet", {}).get("pre_click_messages")
                ),
            ),
            send_red_packet=_send_red_packet_config_from_dict(data.get("send_red_packet", {})),
            ai_decrypt=_ai_decrypt_config_from_dict(data.get("ai_decrypt", {})),
            checkin=CheckinConfig(
                tasks=[
                    CheckinTaskConfig(**_filter_dataclass_kwargs(CheckinTaskConfig, task))
                    for task in data.get("checkin", {}).get("tasks", [])
                    if isinstance(task, dict) and task.get("id") is not None
                ],
                poll_interval_seconds=max(
                    1.0,
                    min(_float_or_default(data.get("checkin", {}).get("poll_interval_seconds"), 10.0), 30.0),
                ),
                state_store=str(data.get("checkin", {}).get("state_store") or "runtime/data/checkin_state.json"),
            ),
            auto_forward=_auto_forward_config_from_dict(data.get("auto_forward", {})),
            word_cloud=_word_cloud_config_from_dict(data.get("word_cloud", {})),
            user_profile=user_profile_config_from_dict(data.get("user_profile", {})),
            quote=_quote_config_from_dict(data.get("quote", {})),
            chat_games=_chat_games_config_from_dict(data.get("chat_games", {})),
            magnet_import=magnet_import_config_from_dict(data.get("magnet_import", {})),
            rex_widget_sync=rex_widget_sync_config_from_dict(data.get("rex_widget_sync", {})),
            gif=GifConfig(**_filter_dataclass_kwargs(GifConfig, data.get("gif", {}))),
            ai=AIConfig(
                reply_provider=AIProviderConfig(
                    **_filter_dataclass_kwargs(AIProviderConfig, data.get("ai", {}).get("reply_provider", {}))
                ),
                image_provider=AIProviderConfig(
                    **_filter_dataclass_kwargs(AIProviderConfig, data.get("ai", {}).get("image_provider", {}))
                ),
                reply=AIReplyConfig(**_filter_dataclass_kwargs(AIReplyConfig, data.get("ai", {}).get("reply", {}))),
                image=AIImageConfig(**_filter_dataclass_kwargs(AIImageConfig, data.get("ai", {}).get("image", {}))),
            ),
        )

    def save(self, path: Path) -> None:
        atomic_write_text(
            path,
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for provider in (data["ai"]["reply_provider"], data["ai"]["image_provider"]):
            if provider.get("api_key"):
                provider["api_key"] = _mask_secret(provider["api_key"])
        if data["telegram"].get("api_hash"):
            data["telegram"]["api_hash"] = _mask_secret(data["telegram"]["api_hash"])
        if data["telegram"].get("bot_token"):
            data["telegram"]["bot_token"] = _mask_secret(data["telegram"]["bot_token"])
        if data["admin"].get("password"):
            data["admin"]["password"] = _mask_secret(data["admin"]["password"])
        if data["magnet_import"].get("api_password"):
            data["magnet_import"]["api_password"] = _mask_secret(data["magnet_import"]["api_password"])
        if data["rex_widget_sync"].get("hub_password"):
            data["rex_widget_sync"]["hub_password"] = _mask_secret(data["rex_widget_sync"]["hub_password"])
        return data


def _apply_env_overrides(config: dict[str, Any]) -> None:
    env_map = {
        "TGBOT_ADMIN_HOST": ("admin", "host", "str"),
        "TGBOT_ADMIN_PORT": ("admin", "port", "int"),
        "TGBOT_ADMIN_USERNAME": ("admin", "username", "str"),
        "TGBOT_ADMIN_PASSWORD": ("admin", "password", "str"),
        "TGBOT_TELEGRAM_API_ID": ("telegram", "api_id", "int"),
        "TGBOT_TELEGRAM_API_HASH": ("telegram", "api_hash", "str"),
        "TGBOT_TELEGRAM_BOT_TOKEN": ("telegram", "bot_token", "str"),
        "TGBOT_TELEGRAM_ENABLED": ("telegram", "enabled", "bool"),
        "TGBOT_LOG_LEVEL": ("logs", "level", "str"),
    }
    for env_name, (section, key, kind) in env_map.items():
        raw = os.getenv(env_name)
        if raw is None:
            continue
        config[section][key] = _coerce_env_value(raw, kind)


def _coerce_env_value(value: str, kind: str = "auto") -> Any:
    if kind == "str":
        return value
    if kind == "bool":
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        return bool(value.strip())
    if kind == "int":
        try:
            return int(value.strip())
        except ValueError:
            return value
    lowered = value.lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    try:
        return int(value)
    except ValueError:
        return value


def chat_history_config_from_dict(data: Any) -> ChatHistoryConfig:
    defaults = ChatHistoryConfig()
    if not isinstance(data, dict):
        return defaults
    return ChatHistoryConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        database_path=str(data.get("database_path") or defaults.database_path).strip() or defaults.database_path,
        max_text_length=max(
            1024,
            min(int(data.get("max_text_length") or defaults.max_text_length), 65536),
        ),
        backfill_enabled=bool(data.get("backfill_enabled", defaults.backfill_enabled)),
        backfill_batch_size=max(
            50,
            min(int(data.get("backfill_batch_size") or defaults.backfill_batch_size), 5000),
        ),
    )


def _ai_decrypt_config_from_dict(data: Any) -> AIDecryptConfig:
    defaults = AIDecryptConfig()
    if not isinstance(data, dict):
        return defaults
    raw_templates = data.get("templates")
    templates = defaults.templates
    if isinstance(raw_templates, list):
        templates = [
            AIDecryptTemplateConfig(**template)
            for template in raw_templates
            if isinstance(template, dict)
        ]
    templates = _ensure_ai_decrypt_builtin_templates(templates)
    return AIDecryptConfig(
        templates=templates,
        timeout_seconds=float(data.get("timeout_seconds") or defaults.timeout_seconds),
        max_tokens=int(data.get("max_tokens") or defaults.max_tokens),
        image_detail=str(data.get("image_detail") or defaults.image_detail),
        send_delay_ms=int(data.get("send_delay_ms") or defaults.send_delay_ms),
        state_store=str(data.get("state_store") or defaults.state_store),
    )


def _ensure_ai_decrypt_builtin_templates(
    templates: list[AIDecryptTemplateConfig],
) -> list[AIDecryptTemplateConfig]:
    if any(template.id == "twenty-four-points" for template in templates):
        return templates
    return [
        *templates,
        AIDecryptTemplateConfig(
            id="twenty-four-points",
            name="24 点算式",
            trigger_keywords=["24 点开始", "数字：", "可用符号"],
            require_media=False,
        ),
    ]


def _send_red_packet_config_from_dict(data: Any) -> SendRedPacketConfig:
    defaults = SendRedPacketConfig()
    if not isinstance(data, dict):
        return defaults
    templates = defaults.templates
    if isinstance(data.get("templates"), list):
        templates = [
            _send_red_packet_template_from_dict(item)
            for item in data["templates"]
            if isinstance(item, dict)
        ]
    elif isinstance(data.get("command_prefixes"), list):
        templates = [
            SendRedPacketTemplateConfig(
                id="lucky-text",
                name="拼手气口令红包",
                type="lucky_text",
                command_prefixes=[str(item).strip() for item in data["command_prefixes"] if str(item).strip()],
                max_packet_count=max(1, min(int(data.get("max_packet_count") or 100), 1000)),
            )
        ]
    templates = _ensure_send_red_packet_builtin_templates(templates)
    return SendRedPacketConfig(
        templates=templates,
        state_store=str(data.get("state_store") or defaults.state_store),
        id_length=max(4, min(int(data.get("id_length") or defaults.id_length), 12)),
        max_active_packets=max(1, min(int(data.get("max_active_packets") or defaults.max_active_packets), 200)),
        min_packet_amount=max(2, min(int(data.get("min_packet_amount") or defaults.min_packet_amount), 1_000_000)),
        strict_min_packet_amount=max(
            2,
            min(int(data.get("strict_min_packet_amount") or defaults.strict_min_packet_amount), 1_000_000),
        ),
        strict_min_packet_group_ids=[
            str(item).strip()
            for item in data.get("strict_min_packet_group_ids", defaults.strict_min_packet_group_ids)
            if str(item).strip()
        ]
        if isinstance(data.get("strict_min_packet_group_ids", defaults.strict_min_packet_group_ids), list)
        else list(defaults.strict_min_packet_group_ids),
    )


def _send_red_packet_template_from_dict(data: dict[str, Any]) -> SendRedPacketTemplateConfig:
    return SendRedPacketTemplateConfig(
        id=str(data.get("id") or "").strip(),
        name=str(data.get("name") or "").strip(),
        type=str(data.get("type") or "lucky_text").strip(),
        enabled=bool(data.get("enabled", True)),
        command_prefixes=[str(item).strip() for item in data.get("command_prefixes", []) if str(item).strip()]
        if isinstance(data.get("command_prefixes"), list)
        else [],
        max_packet_count=max(1, min(int(data.get("max_packet_count") or 100), 1000)),
    )


def _ensure_send_red_packet_builtin_templates(
    templates: list[SendRedPacketTemplateConfig],
) -> list[SendRedPacketTemplateConfig]:
    if any(template.type == "math_quiz" for template in templates):
        return templates
    return [
        *templates,
        SendRedPacketTemplateConfig(
            id="math-quiz",
            name="\u8da3\u5473\u7b97\u672f\u9898",
            type="math_quiz",
            command_prefixes=["/math"],
            max_packet_count=1,
        ),
    ]


def _auto_forward_config_from_dict(data: Any) -> AutoForwardConfig:
    defaults = AutoForwardConfig()
    if not isinstance(data, dict):
        return defaults
    prefixes = _list_or_default(data.get("command_prefixes"), defaults.command_prefixes)
    copy_prefixes = _list_or_default(data.get("copy_text_command_prefixes"), defaults.copy_text_command_prefixes)
    quote_prefixes = _list_or_default(data.get("quote_command_prefixes"), defaults.quote_command_prefixes)
    link_prefixes = _list_or_default(data.get("link_command_prefixes"), defaults.link_command_prefixes)
    return AutoForwardConfig(
        command_prefixes=prefixes,
        copy_text_command_prefixes=copy_prefixes,
        quote_command_prefixes=quote_prefixes,
        link_command_prefixes=link_prefixes,
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
    )


def _clock(value: Any, default: str) -> str:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return default
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def rex_widget_sync_config_from_dict(data: Any) -> RexWidgetSyncConfig:
    defaults = RexWidgetSyncConfig()
    if not isinstance(data, dict):
        return defaults

    def _text(key: str) -> str:
        value = data.get(key, getattr(defaults, key))
        return str(value if value is not None else "").strip()

    def _pattern(key: str) -> str:
        value = _text(key)
        try:
            re.compile(value)
        except re.error:
            return getattr(defaults, key)
        return value

    try:
        size = int(data.get("max_file_size_mb", defaults.max_file_size_mb))
    except (TypeError, ValueError):
        size = defaults.max_file_size_mb
    try:
        timeout = float(data.get("request_timeout_seconds", defaults.request_timeout_seconds))
    except (TypeError, ValueError):
        timeout = defaults.request_timeout_seconds
    return RexWidgetSyncConfig(
        channel_chat=_text("channel_chat"),
        hub_base_url=(_text("hub_base_url") or defaults.hub_base_url).rstrip("/"),
        hub_password=str(data.get("hub_password", defaults.hub_password) or ""),
        collection_slug=_text("collection_slug") or defaults.collection_slug,
        group_id=_text("group_id"),
        file_name_pattern=_pattern("file_name_pattern") or defaults.file_name_pattern,
        exclude_name_pattern=_pattern("exclude_name_pattern"),
        follow_links=bool(data.get("follow_links", defaults.follow_links)),
        ignore_keys=[item.lower() for item in _clean_string_list(data.get("ignore_keys", []))],
        lock_title=bool(data.get("lock_title", defaults.lock_title)),
        max_file_size_mb=max(1, min(25, size)),
        request_timeout_seconds=max(10.0, min(600.0, timeout)),
        state_store=_text("state_store") or defaults.state_store,
    )


def magnet_import_config_from_dict(data: Any) -> MagnetImportConfig:
    defaults = MagnetImportConfig()
    if not isinstance(data, dict):
        return defaults

    def _int(key: str, low: int, high: int) -> int:
        try:
            value = int(data.get(key, getattr(defaults, key)))
        except (TypeError, ValueError):
            value = getattr(defaults, key)
        return max(low, min(high, value))

    try:
        timeout = float(data.get("import_timeout_seconds", defaults.import_timeout_seconds))
    except (TypeError, ValueError):
        timeout = defaults.import_timeout_seconds
    watch_chats = data.get("watch_chats")
    return MagnetImportConfig(
        watch_chats=_clean_string_list(watch_chats) if isinstance(watch_chats, list) else list(defaults.watch_chats),
        sender_usernames=[
            item.lstrip("@") for item in _clean_string_list(data.get("sender_usernames", defaults.sender_usernames))
        ],
        sender_ids=_clean_string_list(data.get("sender_ids", defaults.sender_ids)),
        file_name_pattern=str(data.get("file_name_pattern") or defaults.file_name_pattern).strip(),
        max_file_size_mb=_int("max_file_size_mb", 1, 4096),
        api_base_url=str(data.get("api_base_url") or defaults.api_base_url).strip().rstrip("/"),
        api_username=str(data.get("api_username", defaults.api_username) or "").strip(),
        api_password=str(data.get("api_password", defaults.api_password) or ""),
        update_existing=bool(data.get("update_existing", defaults.update_existing)),
        skip_duplicates=bool(data.get("skip_duplicates", defaults.skip_duplicates)),
        reply_text=str(defaults.reply_text if data.get("reply_text") is None else data.get("reply_text")),
        import_command_prefixes=_clean_string_list(data.get("import_command_prefixes")) or list(defaults.import_command_prefixes),
        download_dir=str(data.get("download_dir") or defaults.download_dir).strip(),
        download_retries=_int("download_retries", 1, 20),
        import_timeout_seconds=max(30.0, min(7200.0, timeout)),
        state_store=str(data.get("state_store") or defaults.state_store).strip(),
        channel_enabled=bool(data.get("channel_enabled", defaults.channel_enabled)),
        channel_chat=str(data.get("channel_chat") or defaults.channel_chat).strip(),
        channel_url_prefix=str(data.get("channel_url_prefix") or defaults.channel_url_prefix).strip().rstrip("/"),
        channel_source_site=str(data.get("channel_source_site") or defaults.channel_source_site).strip()[:50],
        channel_forum_id=str(data.get("channel_forum_id") or defaults.channel_forum_id).strip()[:20],
        channel_forum_type=str(data.get("channel_forum_type") or defaults.channel_forum_type).strip()[:20],
        channel_batch_size=_int("channel_batch_size", 10, 5000),
        channel_enrich_images=bool(data.get("channel_enrich_images", defaults.channel_enrich_images)),
        channel_export_enabled=bool(data.get("channel_export_enabled", defaults.channel_export_enabled)),
        channel_export_chat=str(data.get("channel_export_chat") or defaults.channel_export_chat).strip(),
        channel_export_weekday=_int("channel_export_weekday", 0, 6),
        channel_export_time=_clock(data.get("channel_export_time"), defaults.channel_export_time),
        channel_export_source_site=str(
            data.get("channel_export_source_site") or defaults.channel_export_source_site
        ).strip()[:50],
        avdb_enabled=bool(data.get("avdb_enabled", defaults.avdb_enabled)),
        avdb_repo=str(data.get("avdb_repo") or defaults.avdb_repo).strip().strip("/"),
        avdb_asset_pattern=str(data.get("avdb_asset_pattern") or defaults.avdb_asset_pattern).strip(),
        avdb_interval_hours=_int("avdb_interval_hours", 1, 168),
        avdb_source_site=str(data.get("avdb_source_site") or defaults.avdb_source_site).strip()[:50],
        avdb_converter_script=str(data.get("avdb_converter_script") or defaults.avdb_converter_script).strip(),
    )


def _word_cloud_config_from_dict(data: Any) -> WordCloudConfig:
    defaults = WordCloudConfig()
    if not isinstance(data, dict):
        return defaults
    max_limit = max(50, min(int(data.get("max_limit") or defaults.max_limit), 10000))
    min_limit = max(10, min(int(data.get("min_limit") or defaults.min_limit), max_limit))
    return WordCloudConfig(
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        default_limit=max(min_limit, min(int(data.get("default_limit") or defaults.default_limit), max_limit)),
        max_limit=max_limit,
        min_limit=min_limit,
        output_dir=str(data.get("output_dir") or defaults.output_dir),
        width=max(480, min(int(data.get("width") or defaults.width), 2400)),
        height=max(360, min(int(data.get("height") or defaults.height), 1800)),
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
        ignore_command_prefixes=_list_or_default(data.get("ignore_command_prefixes"), defaults.ignore_command_prefixes),
        stop_words=_list_or_default(data.get("stop_words"), defaults.stop_words),
    )


def user_profile_config_from_dict(data: Any) -> UserProfileConfig:
    defaults = UserProfileConfig()
    if not isinstance(data, dict):
        return defaults
    max_sample_size = max(10, min(int(data.get("max_sample_size") or defaults.max_sample_size), 2000))
    min_sample_size = max(3, min(int(data.get("min_sample_size") or defaults.min_sample_size), max_sample_size))
    default_sample_size = max(
        min_sample_size,
        min(int(data.get("default_sample_size") or defaults.default_sample_size), max_sample_size),
    )
    min_required_samples = max(
        3,
        min(int(data.get("min_required_samples") or defaults.min_required_samples), default_sample_size),
    )
    return UserProfileConfig(
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        default_sample_size=default_sample_size,
        min_sample_size=min_sample_size,
        max_sample_size=max_sample_size,
        min_required_samples=min_required_samples,
        timeout_seconds=max(5.0, min(float(data.get("timeout_seconds") or defaults.timeout_seconds), 600.0)),
        max_tokens=max(512, min(int(data.get("max_tokens") or defaults.max_tokens), 12000)),
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
        style_prompt=str(data.get("style_prompt") or defaults.style_prompt).strip() or defaults.style_prompt,
    )


def _quote_config_from_dict(data: Any) -> QuoteConfig:
    defaults = QuoteConfig()
    if not isinstance(data, dict):
        return defaults
    return QuoteConfig(
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        api_url=str(data.get("api_url") or defaults.api_url),
        background_color=str(data.get("background_color") or defaults.background_color),
        width=max(256, min(int(data.get("width") or defaults.width), 2048)),
        height=max(256, min(int(data.get("height") or defaults.height), 4096)),
        scale=max(1, min(int(data.get("scale") or defaults.scale), 4)),
        emoji_brand=str(data.get("emoji_brand") or defaults.emoji_brand),
        max_messages=max(1, min(int(data.get("max_messages") or defaults.max_messages), 10)),
        timeout_seconds=max(5.0, min(float(data.get("timeout_seconds") or defaults.timeout_seconds), 300.0)),
        sticker_set_short_name=str(data.get("sticker_set_short_name") or ""),
        tmp_dir=str(data.get("tmp_dir") or defaults.tmp_dir),
    )


def _lucky_word_config_from_dict(data: Any) -> LuckyWordConfig:
    defaults = LuckyWordConfig()
    if not isinstance(data, dict):
        return defaults
    return LuckyWordConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        words=_list_or_default(data.get("words"), defaults.words),
        reward_text=str(data.get("reward_text") or defaults.reward_text).strip() or defaults.reward_text,
        daily_limit_per_chat=_clamped_int(data.get("daily_limit_per_chat"), defaults.daily_limit_per_chat, 0, 50),
        per_user_daily_limit=_clamped_int(data.get("per_user_daily_limit"), defaults.per_user_daily_limit, 0, 20),
        ignore_command_prefixes=_list_or_default(data.get("ignore_command_prefixes"), defaults.ignore_command_prefixes),
        min_message_length=_clamped_int(data.get("min_message_length"), defaults.min_message_length, 1, 80),
    )


def _emoji_riddle_item_from_dict(data: Any) -> EmojiRiddleItemConfig | None:
    if not isinstance(data, dict):
        return None
    clue = str(data.get("clue") or "").strip()
    answers = _clean_string_list(data.get("answers"))
    if not clue or not answers:
        return None
    return EmojiRiddleItemConfig(clue=clue, answers=answers, hint=str(data.get("hint") or "").strip())


def _emoji_riddle_config_from_dict(data: Any) -> EmojiRiddleConfig:
    defaults = EmojiRiddleConfig()
    if not isinstance(data, dict):
        return defaults
    items = [
        item
        for raw in data.get("items", [])
        if (item := _emoji_riddle_item_from_dict(raw)) is not None
    ] if isinstance(data.get("items"), list) else defaults.items
    return EmojiRiddleConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        duration_seconds=max(5.0, min(float(data.get("duration_seconds") or defaults.duration_seconds), 300.0)),
        reward_text=str(data.get("reward_text") or defaults.reward_text).strip() or defaults.reward_text,
        winner_policy=_winner_policy(data.get("winner_policy"), defaults.winner_policy),
        announce_answer=bool(data.get("announce_answer", defaults.announce_answer)),
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
        items=items or defaults.items,
    )


def _garbled_decode_config_from_dict(data: Any) -> GarbledDecodeConfig:
    defaults = GarbledDecodeConfig()
    if not isinstance(data, dict):
        return defaults
    return GarbledDecodeConfig(
        enabled=bool(data.get("enabled", defaults.enabled)),
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        duration_seconds=max(5.0, min(float(data.get("duration_seconds") or defaults.duration_seconds), 300.0)),
        reward_text=str(data.get("reward_text") or defaults.reward_text).strip() or defaults.reward_text,
        winner_policy=_winner_policy(data.get("winner_policy"), defaults.winner_policy),
        announce_answer=bool(data.get("announce_answer", defaults.announce_answer)),
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
        phrases=_list_or_default(data.get("phrases"), defaults.phrases),
    )


def _chat_games_config_from_dict(data: Any) -> ChatGamesConfig:
    defaults = ChatGamesConfig()
    if not isinstance(data, dict):
        return defaults
    return ChatGamesConfig(
        lucky_word=_lucky_word_config_from_dict(data.get("lucky_word")),
        emoji_riddle=_emoji_riddle_config_from_dict(data.get("emoji_riddle")),
        garbled_decode=_garbled_decode_config_from_dict(data.get("garbled_decode")),
        state_store=str(data.get("state_store") or defaults.state_store),
        output_dir=str(data.get("output_dir") or defaults.output_dir),
    )


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _winner_policy(value: Any, default: str) -> str:
    text = str(value or default).strip().lower()
    return text if text in {"first", "random"} else default


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamped_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, min(parsed, maximum))


def _list_or_default(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or list(default)


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}***{value[-3:]}"
