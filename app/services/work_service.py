"""打工服务：启动、结算、截胡。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models.enums import Action
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    OwnershipStore,
    ProfileStore,
)
from ..utils.time import now_ts
from .plugin_config import PluginConfig

__all__ = ["WorkService", "WorkStartResult", "WorkSettleResult"]


@dataclass
class WorkStartResult:
    """打工启动结果"""

    ok: bool
    mode: str = ""
    reason: str = ""
    start_cost: int = 0
    ends_at: float = 0.0
    coin_balance: int = 0


@dataclass
class WorkSettleResult:
    """打工结算结果"""

    ok: bool
    reward: int = 0
    intimacy_gain: int = 0
    streak: int = 0
    reason: str = ""
    coin_balance: int = 0


class WorkService:
    """打工系统服务"""

    def __init__(
        self,
        paths: Paths,
        config: PluginConfig,
        locks: GroupLocks,
    ):
        self._paths = paths
        self._config = config
        self._locks = locks

    def _ownership_store(self, gid: str) -> OwnershipStore:
        return OwnershipStore(self._paths, gid)

    def _profile_store(self, gid: str) -> ProfileStore:
        return ProfileStore(self._paths, gid)

    def _activity_store(self, gid: str) -> ActivityStore:
        return ActivityStore(self._paths, gid)

    async def start_work(
        self,
        gid: str,
        uid: str,
        nick: str,
        mode: str,
        today: str,
    ) -> WorkStartResult:
        """启动打工

        检查：功能开启、模式合法、有主老婆、未在打工、余额足够。
        扣启动费，写 is_working/work_mode/work_started_at/work_ends_at。
        """
        if not self._config.work_enabled:
            return WorkStartResult(ok=False, reason="disabled")

        mode_config = self._config.work_modes.get(mode)
        if not mode_config:
            return WorkStartResult(ok=False, reason="invalid_mode")

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            # 检查有主老婆
            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None:
                return WorkStartResult(ok=False, reason="no_wife")

            # 检查未在打工
            if primary.is_working:
                return WorkStartResult(ok=False, reason="already_working")

            # 获取用户档案
            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                coins=self._config.initial_coins,
            )

            # 检查余额足够
            start_cost = mode_config.get("start_cost", 0)
            if profile.coins < start_cost:
                return WorkStartResult(
                    ok=False, reason="not_enough_coins",
                    coin_balance=profile.coins,
                )

            # 扣启动费
            profile.coins -= start_cost

            # 设置打工状态
            ts = now_ts()
            duration = mode_config.get("duration", 14400)
            primary.is_working = True
            primary.work_mode = mode
            primary.work_started_at = ts
            primary.work_ends_at = ts + duration

            # 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.WORK_START, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return WorkStartResult(
                ok=True,
                mode=mode,
                start_cost=start_cost,
                ends_at=primary.work_ends_at,
                coin_balance=profile.coins,
            )

    async def resolve_due_work(
        self,
        gid: str,
        uid: str,
        nick: str,
        today: str,
    ) -> Optional[WorkSettleResult]:
        """结算到期的打工

        时间到后结算收益，增加亲密度，更新 work_streak/work_week_income。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None or not primary.is_working:
                return None

            # 检查是否到期
            ts = now_ts()
            if ts < primary.work_ends_at:
                return None

            mode_config = self._config.work_modes.get(primary.work_mode, {})
            duration = mode_config.get("duration", 14400)

            # 计算收益（含连续打工加成）
            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                coins=self._config.initial_coins,
            )

            # 检查是否跨天（连续打工判断）
            from ..utils.time import is_next_day
            if profile.work_last_settle_date and is_next_day(profile.work_last_settle_date, today):
                profile.work_streak += 1
            elif profile.work_last_settle_date != today:
                profile.work_streak = 1

            # 收益计算
            import random
            reward_min = mode_config.get("reward_min", 20)
            reward_max = mode_config.get("reward_max", 40)
            base_reward = random.randint(reward_min, reward_max)
            streak_bonus = 1.0 + (profile.work_streak - 1) * self._config.work_streak_bonus
            reward = int(base_reward * streak_bonus)

            # 亲密度增加
            intimacy_gain = mode_config.get("intimacy_gain", 5)
            primary.intimacy = min(
                self._config.intimacy_max,
                primary.intimacy + intimacy_gain,
            )

            # 清空打工状态
            primary.is_working = False
            primary.work_mode = ""
            primary.work_started_at = 0
            primary.work_ends_at = 0

            # 更新档案
            profile.coins += reward
            profile.work_last_settle_date = today

            # 周收入统计（按周 key 重置）
            from ..utils.time import get_week_key
            from datetime import timezone
            current_week = get_week_key(timezone.utc)
            if profile.work_week_key != current_week:
                profile.work_week_key = current_week
                profile.work_week_income = 0
            profile.work_week_income += reward

            # 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.WORK_COMPLETE, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return WorkSettleResult(
                ok=True,
                reward=reward,
                intimacy_gain=intimacy_gain,
                streak=profile.work_streak,
                coin_balance=profile.coins,
            )

    async def resolve_stolen_work(
        self,
        gid: str,
        uid: str,
        today: str,
    ) -> Optional[WorkSettleResult]:
        """打工中被牛时的结算

        收益给攻击者，清空原状态。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None or not primary.is_working:
                return None

            mode_config = self._config.work_modes.get(primary.work_mode, {})
            duration = mode_config.get("duration", 14400)

            # 计算已打工时间的比例收益
            ts = now_ts()
            elapsed = ts - primary.work_started_at
            total = primary.work_ends_at - primary.work_started_at
            progress = min(1.0, elapsed / total) if total > 0 else 0

            reward_min = mode_config.get("reward_min", 20)
            reward_max = mode_config.get("reward_max", 40)
            import random
            base_reward = random.randint(reward_min, reward_max)
            reward = int(base_reward * progress)

            # 清空打工状态
            primary.is_working = False
            primary.work_mode = ""
            primary.work_started_at = 0
            primary.work_ends_at = 0

            # 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.WORK_STOLEN, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return WorkSettleResult(
                ok=True,
                reward=reward,
                reason="stolen",
            )

    def clear_work_state(self, ownership) -> None:
        """清空打工状态（独立封装）"""
        ownership.is_working = False
        ownership.work_mode = ""
        ownership.work_started_at = 0
        ownership.work_ends_at = 0
