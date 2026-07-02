"""排行榜聚合服务（Phase 2 完整实现）。

支持：

* 日榜（``days=1``）、周榜（``days=7``）、总榜（从 ``profile.total_*`` 读取）
* 按动作过滤：牛 / 被牛 / PK / 收集
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["LeaderboardService"]


class LeaderboardService:
    """榜单聚合业务（Phase 2 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 2 实现：榜单聚合")
