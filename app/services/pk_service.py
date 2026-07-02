"""PK 战斗服务（Phase 3 完整实现）。

战力公式（参考 ROADMAP.md §5.4）：

``power = base_stats.atk + base_stats.def + base_stats.hp * 0.5 + intimacy * 2``

加入 ±20% 随机扰动，高战力胜，平局随机。
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["PkService"]


class PkService:
    """老婆 PK 业务（Phase 3 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 3 实现：PK 战斗")
