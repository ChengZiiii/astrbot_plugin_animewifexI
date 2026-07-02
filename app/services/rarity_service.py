"""稀有度抽卡服务（Phase 3 完整实现）。

* ``roll_rarity()`` 根据 ``rarity_weights`` 加权随机
* 保底机制：``pity_counter`` 连续 N 次未达 ``pity_min_rarity`` 强制保底
* 首次抽到新角色自动写入 ``wives_master``（按 hash 派生稀有度）
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["RarityService"]


class RarityService:
    """稀有度抽卡业务（Phase 3 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 3 实现：稀有度抽卡")
