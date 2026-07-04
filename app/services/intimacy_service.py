"""亲密度服务（Phase 2 完整实现）。

Phase 1 仅提供占位接口，避免命令层导入失败。Phase 2 接入：

* 零点循环：所有持有老婆 +``intimacy_per_day``
* 命令 ``老婆 摸头 <编号>`` / ``老婆 送礼 <编号>``
* 亲密度阈值校验（PK/互动等玩法复用）
* 被牛走时清零（已在 :meth:`OwnershipStore.transfer` 内置）
"""

from __future__ import annotations

from typing import Optional

from ..models import Ownership, UserProfile
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["IntimacyService"]


class IntimacyService:
    """亲密度业务（Phase 2 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 2 实现：亲密度系统")

    async def pet(self, gid: str, uid: str, ownership_index: int) -> dict:
        """摸头：消耗币 + 加亲密度（Phase 2）"""
        raise NotImplementedError

    async def gift(self, gid: str, uid: str, ownership_index: int) -> dict:
        """送礼：高消耗 + 大幅加亲密度（Phase 2）"""
        raise NotImplementedError
