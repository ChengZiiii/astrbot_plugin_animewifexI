"""经济服务：余额、签到、收支。

Phase 3 核心服务，为任务系统、商城、PK 等提供基础经济能力。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ..models.profile import UserProfile
from ..storage.paths import Paths
from ..storage.stores import ProfileStore
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.economy")

__all__ = ["EconomyService"]


class EconomyService:
    """老婆币经济服务。"""

    def __init__(self, paths: Paths, config: PluginConfig):
        self._paths = paths
        self._config = config

    def balance(self, gid: str, uid: str) -> int:
        """查询用户余额（不存在返回 0）。"""
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)
        return profile.coins if profile else 0

    def earn(
        self,
        gid: str,
        uid: str,
        amount: int,
        nick: str = "",
        reason: str = "",
    ) -> int:
        """发放老婆币，返回发放后余额。"""
        if amount <= 0:
            return self.balance(gid, uid)

        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.default_capacity, self._config.initial_coins
        )
        profile.coins += amount
        store.save_all(profiles)

        logger.debug("earn: gid=%s uid=%s amount=%d reason=%s -> balance=%d",
                      gid, uid, amount, reason, profile.coins)
        return profile.coins

    def spend(
        self,
        gid: str,
        uid: str,
        amount: int,
        nick: str = "",
        reason: str = "",
    ) -> bool:
        """扣除老婆币。余额不足返回 False，不扣款。"""
        if amount <= 0:
            return True

        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.default_capacity, self._config.initial_coins
        )

        if profile.coins < amount:
            logger.debug("spend: gid=%s uid=%s amount=%d reason=%s -> INSUFFICIENT (balance=%d)",
                         gid, uid, amount, reason, profile.coins)
            return False

        profile.coins -= amount
        store.save_all(profiles)

        logger.debug("spend: gid=%s uid=%s amount=%d reason=%s -> balance=%d",
                      gid, uid, amount, reason, profile.coins)
        return True

    def daily_checkin(self, gid: str, uid: str, nick: str = "") -> Optional[int]:
        """每日签到。返回发放金额，已签到返回 None。"""
        today = self._today()
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.default_capacity, self._config.initial_coins
        )

        if profile.last_checkin_date == today:
            logger.debug("daily_checkin: gid=%s uid=%s already checked in", gid, uid)
            return None

        reward = self._config.daily_checkin_coins
        profile.coins += reward
        profile.last_checkin_date = today
        store.save_all(profiles)

        logger.debug("daily_checkin: gid=%s uid=%s reward=%d -> balance=%d",
                      gid, uid, reward, profile.coins)
        return reward

    def has_checked_in(self, gid: str, uid: str) -> bool:
        """查询今日是否已签到。"""
        today = self._today()
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)
        return profile is not None and profile.last_checkin_date == today

    def add_coins_to_profile(
        self, profile: UserProfile, amount: int
    ) -> UserProfile:
        """直接给 profile 加币（不落盘，调用方负责 save）。"""
        profile.coins += amount
        return profile

    def deduct_coins_from_profile(
        self, profile: UserProfile, amount: int
    ) -> bool:
        """直接从 profile 扣币（不落盘）。余额不足返回 False。"""
        if profile.coins < amount:
            return False
        profile.coins -= amount
        return True

    def _today(self) -> str:
        """获取今日日期字符串（YYYY-MM-DD）。"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
