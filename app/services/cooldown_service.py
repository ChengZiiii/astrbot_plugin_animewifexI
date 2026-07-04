"""通用冷却服务：内存表，进程重启后重置。

适用场景：NTR / 抽老婆 / 交换 / PK 等动作的"按动作按用户按群"冷却。

.. note::

    冷却表不持久化（参考 ROADMAP.md §2.2 内存模型）。重启后所有冷却清空，
    即重启后立即可再次触发对应动作。这是有意为之——避免长冷却被卡死。

    若调用方同时有"每日次数限额"语义（如 NTR 每日 3 次），应使用持久化的
    records 机制，本服务只负责"距上次触发是否满 N 秒"判断。
"""

from __future__ import annotations

import time
from typing import Dict

from ..storage.locks import GroupLocks

__all__ = ["CooldownService"]


class CooldownService:
    """按 ``gid × uid × action`` 维护上次触发时间戳的内存表"""

    def __init__(self, locks: GroupLocks):
        self._locks = locks
        # 结构：{gid: {uid: {action: ts}}}
        self._table: Dict[str, Dict[str, Dict[str, float]]] = {}

    def check(self, gid: str, uid: str, action: str, cooldown_seconds: int) -> bool:
        """查询是否已过冷却

        返回 ``True`` 表示可以触发（已过冷却或从未触发过）；
        ``False`` 表示仍在冷却中。
        """
        if cooldown_seconds <= 0:
            return True
        last = self._lookup(gid, uid, action)
        if last is None:
            return True
        return (time.time() - last) >= cooldown_seconds

    def remaining(self, gid: str, uid: str, action: str, cooldown_seconds: int) -> int:
        """剩余冷却秒数（已过冷却返回 0）"""
        if cooldown_seconds <= 0:
            return 0
        last = self._lookup(gid, uid, action)
        if last is None:
            return 0
        diff = cooldown_seconds - (time.time() - last)
        return max(0, int(diff))

    def update(self, gid: str, uid: str, action: str, ts: "float | None" = None) -> None:
        """记录最新触发时间戳（默认当前时间）"""
        timestamp = float(ts) if ts is not None else time.time()
        self._table.setdefault(gid, {}).setdefault(uid, {})[action] = timestamp

    def reset(self, gid: str, uid: str, action: str) -> None:
        """清除某条冷却记录（管理员重置用）"""
        grp = self._table.get(gid)
        if not grp:
            return
        user = grp.get(uid)
        if not user:
            return
        user.pop(action, None)
        if not user:
            grp.pop(uid, None)
        if not grp:
            self._table.pop(gid, None)

    # ---------- 内部 ----------

    def _lookup(self, gid: str, uid: str, action: str):
        return self._table.get(gid, {}).get(uid, {}).get(action)
