"""群组级异步锁池：保护单群所有持久化文件的并发读写。

沿用 v2.x 的并发模型：每群一把 :class:`asyncio.Lock`，所有 service 方法
内部走 ``async with locks.acquire(gid):`` 进入临界区。
"""

from __future__ import annotations

import asyncio
from typing import Dict

__all__ = ["GroupLocks"]


class GroupLocks:
    """按群 ID 维护 :class:`asyncio.Lock` 的池子

    * 第一次访问某群时自动创建对应锁；
    * 锁对象在事件循环生命周期内常驻，重复获取返回同一实例。
    """

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}

    def acquire(self, gid: str) -> asyncio.Lock:
        """获取或创建群组级状态锁"""
        lock = self._locks.get(gid)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[gid] = lock
        return lock

    def known_groups(self):
        """返回已知群 ID 列表（用于定时清理遍历）"""
        return list(self._locks.keys())
