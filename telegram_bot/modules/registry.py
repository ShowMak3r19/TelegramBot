from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from telegram_bot.config import AppConfig
from telegram_bot.persistence import ChatHistoryStore
from telegram_bot.shared.contracts import HandlerResult

from .ai_decrypt import AIDecryptModule
from .ai_image import AIImageModule
from .ai_reply import AIReplyModule
from .auto_forward import AutoForwardModule
from .base import FeatureModule, ModuleCard
from .chat_games import ChatGamesModule
from .checkin import CheckinModule
from .gif import GifModule
from .magnet_import import MagnetImportModule
from .red_packet import RedPacketModule
from .quote import QuoteModule
from .send_red_packet import SendRedPacketModule
from .user_profile import UserProfileModule
from .word_cloud import WordCloudModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, FeatureModule] = {}

    def register(self, module: FeatureModule) -> None:
        if module.card.id in self._modules:
            raise ValueError(f"Duplicate module id: {module.card.id}")
        self._modules[module.card.id] = module
        logger.info("Registered module: %s", module.card.id)

    def all(self) -> list[FeatureModule]:
        return list(self._modules.values())

    def get(self, module_id: str) -> FeatureModule | None:
        return self._modules.get(module_id)

    def cards(self) -> list[dict[str, Any]]:
        return [module.card.__dict__ for module in self.all()]

    async def start_enabled(self) -> None:
        for module in self.all():
            if module.card.enabled:
                await module.start()

    async def stop_all(self) -> None:
        for module in self.all():
            await module.stop()

    async def dispatch_message(self, message: Any) -> list[HandlerResult]:
        results: list[HandlerResult] = []
        for module in self.all():
            if not module.card.enabled:
                continue
            result = await module.handle_message(message)
            results.append(result)
            if result.status == "handled":
                break
        return results


def create_default_registry(
    config: AppConfig,
    project_root: Path | None = None,
    chat_history: ChatHistoryStore | None = None,
) -> ModuleRegistry:
    registry = ModuleRegistry()
    claimed_ids_path = _claimed_ids_path(config, project_root)
    registry.register(
        MagnetImportModule(
            ModuleCard(
                id="magnet_import",
                name="磁力数据导入",
                description="监听指定群/用户发送的 CSV 数据文件，自动下载导入 MagnetBoard 数据交换中心并回复致谢。",
                category="automation",
                enabled=config.modules.magnet_import,
            ),
            config.magnet_import,
            project_root,
        )
    )
    registry.register(
        RedPacketModule(
            ModuleCard(
                id="red_packet",
                name="自动抢红包",
                description="按模板匹配红包/抽奖消息，动态提取口令并避免重复领取。",
                category="automation",
                enabled=config.modules.red_packet,
            ),
            config.red_packet,
            claimed_ids_path,
        )
    )
    registry.register(
        SendRedPacketModule(
            ModuleCard(
                id="send_red_packet",
                name="发红包模块",
                description="用红包指令创建拼手气红包，按预随机金额分配给输入口令的用户。",
                category="automation",
                enabled=config.modules.send_red_packet,
                config=asdict(config.send_red_packet),
            ),
            config.send_red_packet,
            project_root,
        )
    )
    registry.register(
        AIReplyModule(
            ModuleCard(
                id="ai_reply",
                name="AI 自动回复",
                description="群组消息、回复触发和上下文管理的 AI 对话模块。",
                category="ai",
                enabled=config.modules.ai_reply,
                config={
                    "provider": config.ai.reply_provider.name,
                    "provider_type": config.ai.reply_provider.provider_type,
                    "model": config.ai.reply_provider.model,
                },
            ),
            config.ai,
            project_root,
        )
    )
    registry.register(
        UserProfileModule(
            ModuleCard(
                id="user_profile",
                name="群友画像",
                description="抽取指定群友的近期发言，生成带原消息论据的富文本群聊人设。",
                category="ai",
                enabled=config.modules.user_profile,
                config=asdict(config.user_profile),
            ),
            config.user_profile,
            config.ai,
            project_root,
            chat_history,
            config.telegram,
        )
    )
    registry.register(
        AIImageModule(
            ModuleCard(
                id="ai_image",
                name="AI 生图",
                description="文本生图、参考图生图和发送策略的图像模块。",
                category="ai",
                enabled=config.modules.ai_image,
                config={
                    "provider": config.ai.image_provider.name,
                    "provider_type": config.ai.image_provider.provider_type,
                    "model": config.ai.image_provider.model,
                },
            ),
            config.ai,
            project_root,
        )
    )
    registry.register(
        AIDecryptModule(
            ModuleCard(
                id="ai_decrypt",
                name="AI 解密",
                description="识别红包解密游戏图片和题目文本，调用 AI 解题后自动发送答案。",
                category="ai",
                enabled=config.modules.ai_decrypt,
            ),
            config.ai_decrypt,
            config.ai,
            project_root,
        )
    )
    registry.register(
        GifModule(
            ModuleCard(
                id="gif",
                name="GIF动图",
                description="回复视频/GIF/WebP 后按时间段截取并转换为 GIF 动图。",
                category="media",
                enabled=config.modules.gif,
                config=asdict(config.gif) if hasattr(config, "gif") else {},
            ),
            config.gif,
            project_root,
        )
    )
    registry.register(
        CheckinModule(
            ModuleCard(
                id="checkin",
                name="自动签到",
                description="按 Cron 配置向指定群组或 Bot 自动发送签到消息。",
                category="automation",
                enabled=config.modules.checkin,
                config=asdict(config.checkin) if hasattr(config, "checkin") else {},
            ),
            config.checkin,
            project_root,
        )
    )
    registry.register(
        AutoForwardModule(
            ModuleCard(
                id="auto_forward",
                name="\u81ea\u52a8\u8f6c\u53d1",
                description="\u56de\u590d\u67d0\u6761\u6d88\u606f\u53d1\u9001 ,re\uff0c\u81ea\u52a8\u5c06\u88ab\u56de\u590d\u6d88\u606f\u8f6c\u53d1\u56de\u5f53\u524d\u804a\u5929\u3002",
                category="automation",
                enabled=config.modules.auto_forward,
                config=asdict(config.auto_forward),
            ),
            config.auto_forward,
        )
    )
    registry.register(
        WordCloudModule(
            ModuleCard(
                id="word_cloud",
                name="词云",
                description="按指令统计当前群最近消息，生成每个群独立的热词云图片。",
                category="media",
                enabled=config.modules.word_cloud,
                config=asdict(config.word_cloud),
            ),
            config.word_cloud,
            project_root,
        )
    )
    registry.register(
        QuoteModule(
            ModuleCard(
                id="quote",
                name="语录贴纸",
                description="回复消息用 /q 或 语录 指令生成语录贴纸，支持多条、引用块、假语录、保存贴纸包。",
                category="media",
                enabled=config.modules.quote,
                config=asdict(config.quote),
            ),
            config.quote,
            project_root,
        )
    )
    registry.register(
        ChatGamesModule(
            ModuleCard(
                id="chat_games",
                name="聊天小游戏",
                description="今日幸运词、Emoji 图谜和乱码解码；中奖时回复命中消息 +100，兼容群内现有积分机器人。",
                category="game",
                enabled=config.modules.chat_games,
                config=asdict(config.chat_games),
            ),
            config.chat_games,
            project_root,
        )
    )
    return registry


def _claimed_ids_path(config: AppConfig, project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    data_dir = Path(config.runtime.data_dir)
    if not data_dir.is_absolute():
        data_dir = project_root / data_dir
    return data_dir / "red_packet_claimed_ids.json"
