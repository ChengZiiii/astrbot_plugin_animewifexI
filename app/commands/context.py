"""命令上下文：聚合所有 service + 配置 + 路径，供命令处理器复用。

设计：

* 一次插件初始化只创建一份 :class:`CommandContext`，所有命令共享；
* ``today`` 通过方法动态计算（长生命周期避免跨午夜缓存陈旧日期）；
* 命令处理器签名：``async def handler(event, ctx) -> AsyncGenerator``，
  统一 ``yield event.plain_result(...)`` / ``event.chain_result(...)`` 输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from ..services.cooldown_service import CooldownService
from ..services.lifespan_service import LifespanService
from ..services.ownership_service import OwnershipService
from ..services.plugin_config import PluginConfig
from ..services.wife_service import WifeService
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..utils.time import get_today

__all__ = ["CommandContext"]


@dataclass
class CommandContext:
    """命令处理器共享的上下文"""

    paths: Paths
    config: PluginConfig
    locks: GroupLocks
    ownership_service: OwnershipService
    wife_service: WifeService
    cooldown_service: CooldownService
    tz: ZoneInfo
    context: Optional[Any] = None  # AstrBot Context — 主动消息推送用，由 plugin.py 注入
    # Phase 6 / 寿命系统
    lifespan_service: Optional[LifespanService] = None

    def today(self) -> str:
        """获取当前时区的今日日期字符串"""
        return get_today(self.tz)
