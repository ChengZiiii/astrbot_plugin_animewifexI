"""经济服务：余额、签到、收支与周宝箱。

Phase 3 核心服务，为任务系统、商城、PK 等提供基础经济能力。
Phase 4 新增：连续签到奖励。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..models.enums import Action
from ..models.profile import UserProfile
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import ActivityStore, ProfileStore
from ..utils.time import get_week_key, is_next_day
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.economy")

DEBT_FLOOR = -500  # 硬封顶：余额永远 ≥ -500


def try_deduct(current_coins: int, amount: int) -> tuple[bool, int]:
    """扣款后余额不能 < DEBT_FLOOR (-500)。

    Returns:
        (success: bool, new_balance: int)
        如果会触底，返回 (False, current_coins) 且不做任何操作。
    """
    if current_coins - amount < DEBT_FLOOR:
        return False, current_coins
    return True, current_coins - amount


def apply_income(current_coins: int, income: int) -> int:
    """优先抵债：余额为负时收入先填坑，再入正余额。"""
    return current_coins + income


__all__ = ["DEBT_FLOOR", "try_deduct", "apply_income", "EconomyService", "WeeklySurpriseBoxResult"]


@dataclass
class WeeklySurpriseBoxResult:
    """每周惊喜宝箱奖励。"""

    coins: int
    item: str | None = None


class EconomyService:
    """老婆币经济服务。"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks | None = None):
        self._paths = paths
        self._config = config
        self._locks = locks

    def balance(self, gid: str, uid: str) -> int:
        """查询用户余额（不存在返回 0）。"""
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)
        return profile.coins if profile else 0

    async def earn(
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

        if self._locks:
            async with self._locks.acquire(gid):
                return self._earn_inner(gid, uid, amount, nick, reason)
        return self._earn_inner(gid, uid, amount, nick, reason)

    def _earn_inner(self, gid: str, uid: str, amount: int, nick: str, reason: str) -> int:
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.initial_coins
        )
        profile.coins = apply_income(profile.coins, amount)
        store.save_all(profiles)

        logger.debug("earn: gid=%s uid=%s amount=%d reason=%s -> balance=%d",
                      gid, uid, amount, reason, profile.coins)
        return profile.coins

    async def spend(
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

        if self._locks:
            async with self._locks.acquire(gid):
                return self._spend_inner(gid, uid, amount, nick, reason)
        return self._spend_inner(gid, uid, amount, nick, reason)

    def _spend_inner(self, gid: str, uid: str, amount: int, nick: str, reason: str) -> bool:
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.initial_coins
        )

        success, new_balance = try_deduct(profile.coins, amount)
        if not success:
            logger.debug("spend: gid=%s uid=%s amount=%d reason=%s -> INSUFFICIENT (balance=%d, floor=%d)",
                         gid, uid, amount, reason, profile.coins, DEBT_FLOOR)
            return False

        profile.coins = new_balance
        store.save_all(profiles)

        logger.debug("spend: gid=%s uid=%s amount=%d reason=%s -> balance=%d",
                      gid, uid, amount, reason, profile.coins)
        return True

    async def daily_checkin(self, gid: str, uid: str, nick: str = "") -> Optional[Tuple[int, int, Optional[str]]]:
        """每日签到。返回 (base_reward, bonus_coins, bonus_item)，已签到返回 None。"""
        if self._locks:
            async with self._locks.acquire(gid):
                return self._daily_checkin_inner(gid, uid, nick)
        return self._daily_checkin_inner(gid, uid, nick)

    def _daily_checkin_inner(self, gid: str, uid: str, nick: str) -> Optional[Tuple[int, int, Optional[str]]]:
        """每日签到核心逻辑。

        返回 (base_reward, bonus_coins, bonus_item) 或 None（已签到）。
        """
        today = self._today()
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.initial_coins
        )

        if profile.last_checkin_date == today:
            logger.debug("daily_checkin: gid=%s uid=%s already checked in", gid, uid)
            return None

        # 连签判断
        if is_next_day(profile.last_checkin_date, today):
            profile.streak_days += 1
        else:
            profile.streak_days = 1

        # 基础奖励
        reward = self._config.daily_checkin_coins
        bonus_coins = 0
        bonus_item = None

        # 第 3 天额外奖励
        if profile.streak_days == 3:
            bonus_coins += self._config.checkin_streak_3day_bonus

        # 第 7 天额外奖励 + 道具
        if profile.streak_days == 7:
            bonus_coins += self._config.checkin_streak_7day_bonus
            bonus_item = self._config.checkin_streak_7day_item
            profile.inventory[bonus_item] = profile.inventory.get(bonus_item, 0) + 1
            profile.streak_days = 0  # 重置连签天数

        total_reward = reward + bonus_coins
        profile.coins += total_reward
        profile.last_checkin_date = today

        # 写活动日志
        activity_store = ActivityStore(self._paths, gid)
        activity_logs = activity_store.load_all()
        ActivityStore.log(activity_logs, uid, today, Action.CHECKIN)
        activity_store.save_all(activity_logs)

        store.save_all(profiles)

        logger.debug("daily_checkin: gid=%s uid=%s streak=%d reward=%d bonus=%d -> balance=%d",
                      gid, uid, profile.streak_days, reward, bonus_coins, profile.coins)
        return (reward, bonus_coins, bonus_item)

    def has_checked_in(self, gid: str, uid: str) -> bool:
        """查询今日是否已签到。"""
        today = self._today()
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)
        return profile is not None and profile.last_checkin_date == today

    async def claim_weekly_surprise_box(
        self,
        gid: str,
        uid: str,
        nick: str = "",
    ) -> Optional[WeeklySurpriseBoxResult]:
        """懒触发领取本周惊喜宝箱。"""
        if self._locks:
            async with self._locks.acquire(gid):
                return self._claim_weekly_surprise_box_inner(gid, uid, nick)
        return self._claim_weekly_surprise_box_inner(gid, uid, nick)

    def _claim_weekly_surprise_box_inner(
        self,
        gid: str,
        uid: str,
        nick: str,
    ) -> Optional[WeeklySurpriseBoxResult]:
        from datetime import datetime, timezone

        current_week = get_week_key(timezone.utc)
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()
        profile = ProfileStore.get_or_create(profiles, uid, nick, self._config.initial_coins)

        if profile.weekly_box_claimed_week == current_week:
            return None

        activity_store = ActivityStore(self._paths, gid)
        logs = activity_store.load_all()
        log = logs.get(uid)
        if log is None or not hasattr(log, "days"):
            return None

        checkin_days = 0
        for day, actions in log.days.items():
            try:
                day_obj = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            iso = day_obj.isocalendar()
            day_week = f"{iso[0]}-W{iso[1]:02d}"
            if day_week != current_week:
                continue
            if int(actions.get(Action.CHECKIN, 0) or 0) > 0:
                checkin_days += 1

        required = int(self._config.weekly_surprise_box.get("min_checkin_days", 0) or 0)
        if checkin_days < required:
            return None

        coins = int(self._config.weekly_surprise_box.get("coins", 0) or 0)
        item = str(self._config.weekly_surprise_box.get("item", "") or "") or None
        profile.coins += coins
        if item:
            profile.inventory[item] = profile.inventory.get(item, 0) + 1
        profile.weekly_box_claimed_week = current_week
        profile_store.save_all(profiles)
        return WeeklySurpriseBoxResult(coins=coins, item=item)

    def add_coins_to_profile(
        self, profile: UserProfile, amount: int
    ) -> UserProfile:
        """直接给 profile 加币（不落盘，调用方负责 save）。"""
        profile.coins = apply_income(profile.coins, amount)
        return profile

    def deduct_coins_from_profile(
        self, profile: UserProfile, amount: int
    ) -> bool:
        """直接从 profile 扣币（不落盘）。余额不足或触底返回 False。"""
        success, new_balance = try_deduct(profile.coins, amount)
        if not success:
            return False
        profile.coins = new_balance
        return True

    # ---------- 同步别名（测试/无锁场景兼容） ----------

    def earn_sync(
        self, gid: str, uid: str, amount: int, nick: str = "", reason: str = ""
    ) -> int:
        """同步版 earn（不经过锁）。"""
        if amount <= 0:
            return self.balance(gid, uid)
        return self._earn_inner(gid, uid, amount, nick, reason)

    def spend_sync(
        self, gid: str, uid: str, amount: int, nick: str = "", reason: str = ""
    ) -> bool:
        """同步版 spend（不经过锁）。"""
        if amount <= 0:
            return True
        return self._spend_inner(gid, uid, amount, nick, reason)

    def daily_checkin_sync(self, gid: str, uid: str, nick: str = "") -> Optional[Tuple[int, int, Optional[str]]]:
        """同步版 daily_checkin（不经过锁）。"""
        return self._daily_checkin_inner(gid, uid, nick)

    def claim_weekly_surprise_box_sync(
        self,
        gid: str,
        uid: str,
        nick: str = "",
    ) -> Optional[tuple[int, str | None]]:
        """同步版周宝箱领取。"""
        result = self._claim_weekly_surprise_box_inner(gid, uid, nick)
        if result is None:
            return None
        return (result.coins, result.item)

    def _today(self) -> str:
        """获取今日日期字符串（YYYY-MM-DD）。"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
