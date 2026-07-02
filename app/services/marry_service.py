"""求婚/锁定服务。

* ``propose(gid, uid, wid)`` 校验亲密度 ≥ 阈值、扣币、永久锁定
* ``lock(gid, uid, wid)`` 消耗 lock_item，限期锁定 7 天
* ``unlock(gid, uid, wid)`` 主动解锁
* ``is_locked(ownership)`` 检查是否锁定（含过期判断）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..models.ownership import Ownership
from ..models.profile import UserProfile
from ..storage.paths import Paths
from ..storage.stores import OwnershipStore, ProfileStore
from .economy_service import EconomyService
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
    """求婚/锁定服务。"""

    def __init__(self, paths: Paths, config: PluginConfig):
        self._paths = paths
        self._config = config
        self._economy = EconomyService(paths, config)

    def propose(
        self, gid: str, uid: str, wid: str, nick: str = ""
    ) -> MarryResult:
        """求婚：永久锁定（消耗 marry_coin_cost 币 + 亲密度 ≥ 阈值）"""
        store = OwnershipStore(self._paths, gid)
        ownerships = store.load_all()
        ownership = store.find_by_wid(wid, ownerships)
        if not ownership:
            return MarryResult(ok=False, reason="not_found", msg="未找到该老婆")
        if ownership.uid != uid:
            return MarryResult(ok=False, reason="not_owner", msg="这不是你的老婆")
        if ownership.is_locked and ownership.lock_expires_at is None:
            return MarryResult(ok=False, reason="already_married", msg="已经求婚过了")

        # 检查亲密度
        if ownership.intimacy < self._config.intimacy_marry_threshold:
            return MarryResult(
                ok=False,
                reason="intimacy_low",
                msg=f"亲密度不足（需要 {self._config.intimacy_marry_threshold}，当前 {ownership.intimacy}）",
            )

        # 扣币
        cost = self._config.marry_coin_cost
        if not self._economy.spend(gid, uid, cost, nick, "propose"):
            return MarryResult(
                ok=False,
                reason="insufficient",
                msg=f"余额不足（需要 {cost} 币）",
            )

        # 永久锁定
        ownership.is_locked = True
        ownership.lock_expires_at = None
        store.save_all(ownerships)

        logger.debug("propose: gid=%s uid=%s wid=%s -> locked permanently", gid, uid, wid)
        return MarryResult(ok=True, msg=f"求婚成功！花费 {cost} 币，老婆已永久锁定 💍")

    def lock(
        self, gid: str, uid: str, wid: str, nick: str = ""
    ) -> MarryResult:
        """使用锁定卡，限期锁定 7 天"""
        store = OwnershipStore(self._paths, gid)
        ownerships = store.load_all()
        ownership = store.find_by_wid(wid, ownerships)
        if not ownership:
            return MarryResult(ok=False, reason="not_found", msg="未找到该老婆")
        if ownership.uid != uid:
            return MarryResult(ok=False, reason="not_owner", msg="这不是你的老婆")

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
            profiles, uid, nick, self._config.default_capacity, self._config.initial_coins
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

    def unlock(self, gid: str, uid: str, wid: str) -> MarryResult:
        """主动解锁"""
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
        """检查老婆是否处于锁定状态（含过期判断）"""
        if not ownership.is_locked:
            return False
        # 永久锁定
        if ownership.lock_expires_at is None:
            return True
        # 限期锁定：检查是否过期
        if ownership.lock_expires_at > int(time.time()):
            return True
        # 过期自动解锁
        ownership.is_locked = False
        ownership.lock_expires_at = None
        return False
