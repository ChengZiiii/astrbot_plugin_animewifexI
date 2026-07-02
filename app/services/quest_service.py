"""每日任务服务（Phase 3 完整实现）。

每日任务模板（参考 ROADMAP.md §5.1）：

* 抽老婆 1 次
* 参与 PK 1 次
* 被牛 0 次
* 牛成功 1 次

完成自动发币，写入 ``profile.quest_completed_date`` 防重领。
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["QuestService"]


class QuestService:
    """每日任务业务（Phase 3 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 3 实现：每日任务")
