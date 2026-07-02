"""锁定服务。

* ``lock(gid, uid, wid)`` 消耗 lock_item，限期锁定 7 天
* ``unlock(gid, uid, wid)`` 主动解锁
* ``is_locked(ownership)`` 检查是否锁定
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..models.ownership import Ownership
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import OwnershipStore, ProfileStore
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.marry")

__all__ = ["MarryService", "MarryResult"]

# 锁定卡默认锁定天数
LOCK_DAYS = 7


@dataclass
class MarryResult:
    ok: bool
    reason: str = ""
    msg: str = ""


class MarryService:
    """锁定服务。"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks | None = None):
        self._paths = paths
        self._config = config
        self._locks = locks

    async def lock(
        self, gid: str, uid: str, wid: str, nick: str = ""
    ) -> MarryResult:
        """使用锁定卡，限期锁定 7 天"""
        if self._locks:
            async with self._locks.acquire(gid):
                return self._lock_inner(gid, uid, wid, nick)
        return self._lock_inner(gid, uid, wid, nick)

    def _lock_inner(self, gid: str, uid: str, wid: str, nick: str) -> MarryResult:
        store = OwnershipStore(self._paths, gid)
        ownerships = store.load_all()
        ownership = store.find_by_wid(wid, ownerships)
        if not ownership:
            return MarryResult(ok=False, reason="not_found", msg="未找到该老婆")
        if ownership.uid != uid:
            return MarryResult(ok=False, reason="not_owner", msg="这不是你的老婆")

        # 清除过期锁
        self.clear_expired_lock(ownership)

        # 已永久锁定
        if ownership.is_locked and ownership.lock_expires_at is None:
            return MarryResult(ok=False, reason="already_married", msg="已永久锁定，无需再锁")

        # 已限期锁定
        if self.is_locked(ownership):
            return MarryResult(ok=False, reason="already_locked", msg="老婆正在锁定中")

        # 检查并消耗锁定卡
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.initial_coins
        )
        if profile.inventory.get("lock_item", 0) <= 0:
            return MarryResult(ok=False, reason="no_item", msg="没有锁定卡，去商城购买吧~")

        profile.inventory["lock_item"] -= 1
        profile_store.save_all(profiles)

        # 限期锁定
        ownership.is_locked = True
        ownership.lock_expires_at = int(time.time()) + LOCK_DAYS * 86400
        store.save_all(ownerships)

        logger.debug("lock: gid=%s uid=%s wid=%s -> locked for %d days", gid, uid, wid, LOCK_DAYS)
        return MarryResult(ok=True, msg=f"锁定成功！消耗 1 张锁定卡，老婆锁定 {LOCK_DAYS} 天 🔒")

    async def unlock(self, gid: str, uid: str, wid: str) -> MarryResult:
        """主动解锁"""
        if self._locks:
            async with self._locks.acquire(gid):
                return self._unlock_inner(gid, uid, wid)
        return self._unlock_inner(gid, uid, wid)

    def _unlock_inner(self, gid: str, uid: str, wid: str) -> MarryResult:
        store = OwnershipStore(self._paths, gid)
        ownerships = store.load_all()
        ownership = store.find_by_wid(wid, ownerships)
        if not ownership:
            return MarryResult(ok=False, reason="not_found", msg="未找到该老婆")
        if ownership.uid != uid:
            return MarryResult(ok=False, reason="not_owner", msg="这不是你的老婆")
        if not ownership.is_locked:
            return MarryResult(ok=False, reason="not_locked", msg="老婆没有被锁定")

        ownership.is_locked = False
        ownership.lock_expires_at = None
        store.save_all(ownerships)

        logger.debug("unlock: gid=%s uid=%s wid=%s -> unlocked", gid, uid, wid)
        return MarryResult(ok=True, msg="解锁成功！老婆已解除锁定 🔓")

    @staticmethod
    def is_locked(ownership: Ownership) -> bool:
        """检查老婆是否处于锁定状态（纯检查，不修改 ownership）"""
        if not ownership.is_locked:
            return False
        # 永久锁定
        if ownership.lock_expires_at is None:
            return True
        # 限期锁定：检查是否过期
        return ownership.lock_expires_at > int(time.time())

    @staticmethod
    def clear_expired_lock(ownership: Ownership) -> bool:
        """清除过期的限期锁定。返回 True 表示确实清除了一个过期锁。"""
        if not ownership.is_locked:
            return False
        if ownership.lock_expires_at is None:
            return False  # 永久锁定不清除
        if ownership.lock_expires_at > int(time.time()):
            return False  # 未过期
        ownership.is_locked = False
        ownership.lock_expires_at = None
        return True

    # ---------- 同步别名（测试/无锁场景兼容） ----------

    def lock_sync(
        self, gid: str, uid: str, wid: str, nick: str = ""
    ) -> MarryResult:
        """同步版 lock（不经过锁）。"""
        return self._lock_inner(gid, uid, wid, nick)

    def unlock_sync(self, gid: str, uid: str, wid: str) -> MarryResult:
        """同步版 unlock（不经过锁）。"""
        return self._unlock_inner(gid, uid, wid)
