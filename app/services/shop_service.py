"""商城服务（Phase 3 完整实现）。

道具清单：

* ``reroll_ticket``     - 抵扣换老婆消耗
* ``capacity_expansion`` - 扩容 +1
* ``lock_item``         - 限期锁定
* ``revive_potion``     - 被牛后复活
* ``protection_charm``  - 24h 免疫一次 NTR
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["ShopService"]


class ShopService:
    """商城业务（Phase 3 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 3 实现：商城")
