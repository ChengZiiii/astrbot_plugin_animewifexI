"""NTR + 复仇服务（Phase 2 接入复仇机制）。

Phase 1 中基础 NTR 由 :class:`OwnershipService.try_ntr` 直接处理（保留 v2.x 语义）。
Phase 2 复仇机制扩展：

* profile.last_ntr_by 字段已在 Phase 1 写入（NTR 成功时）
* 复仇命令 ``老婆 复仇 @x`` 走独立路径，检测复仇窗口 + 倍率
"""

from __future__ import annotations

from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["NtrService"]


class NtrService:
    """NTR 复仇分支（Phase 2 实现）"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks):
        self._paths = paths
        self._config = config
        self._locks = locks
        raise NotImplementedError("Phase 2 实现：复仇机制")
