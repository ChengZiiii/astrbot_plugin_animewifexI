"""求婚/锁定服务（Phase 3 完整实现）。

* 求婚：校验亲密度 ≥ 阈值、扣 ``marry_coin_cost``、设置 ``is_locked=True``
* 限期锁定：消耗 ``lock_item``
* 复活药水 / 保护符装备
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["MarryService"]


class MarryService:
    """求婚/锁定业务（Phase 3 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 3 实现：求婚/锁定")
