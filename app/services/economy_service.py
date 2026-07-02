"""经济服务（Phase 3 完整实现）。

Phase 1 仅占位。Phase 3 接入：

* 余额查询、扣款、收入
* 每日签到
* 任务系统
* 商城购买
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["EconomyService"]


class EconomyService:
    """老婆币业务（Phase 3 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 3 实现：经济系统")
