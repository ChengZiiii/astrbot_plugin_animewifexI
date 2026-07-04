"""打工服务：启动、结算、截胡与第二波扩展。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

try:
    from astrbot.api import logger
except Exception:
    import logging
    logger = logging.getLogger("astrbot_plugin_animewifex")

from ..models.enums import Action
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    OwnershipStore,
    ProfileStore,
)
from ..utils.time import get_today, now_ts
from .plugin_config import PluginConfig

__all__ = [
    "WorkService",
    "WorkStartResult",
    "WorkSettleResult",
    "WorkContractResult",
    "WorkPartnerResult",
]


@dataclass
class WorkStartResult:
    """打工启动结果"""

    ok: bool
    mode: str = ""
    reason: str = ""
    start_cost: int = 0
    ends_at: float = 0.0
    coin_balance: int = 0
    wid: str = ""


@dataclass
class WorkSettleResult:
    """打工结算结果"""

    ok: bool
    reward: int = 0
    intimacy_gain: int = 0
    streak: int = 0
    reason: str = ""
    coin_balance: int = 0
    wid: str = ""
    mode: str = ""
    contract_used: bool = False
    contract_voided: bool = False
    partner_bonus_used: bool = False
    partner_broken: bool = False
    insurance_used: bool = False
    insurance_bonus_coins: int = 0


@dataclass
class WorkContractResult:
    """打工合约预约结果。"""

    ok: bool
    reason: str = ""
    mode: str = ""
    coin_balance: int = 0


@dataclass
class WorkPartnerResult:
    """打工搭档绑定结果。"""

    ok: bool
    reason: str = ""
    partner_uid: str = ""


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

    @staticmethod
    def _clear_partner_link(profiles: dict[str, object], uid: str) -> bool:
        """清空用户及其互绑对象的搭档关系。"""
        profile = profiles.get(uid)
        if profile is None or not getattr(profile, "work_partner_uid", ""):
            return False

        partner_uid = str(getattr(profile, "work_partner_uid", "") or "")
        partner_profile = profiles.get(partner_uid)
        profile.work_partner_uid = ""
        profile.work_partner_date = ""

        if partner_profile is not None and getattr(partner_profile, "work_partner_uid", "") == uid:
            partner_profile.work_partner_uid = ""
            partner_profile.work_partner_date = ""
        return True

    @staticmethod
    def _has_partner_bonus(
        profiles: dict[str, object],
        activity_logs: dict[str, object],
        uid: str,
        today: str,
    ) -> bool:
        """判断用户今日是否满足打工搭档收益加成。"""
        profile = profiles.get(uid)
        if profile is None:
            return False

        partner_uid = str(getattr(profile, "work_partner_uid", "") or "")
        partner_date = str(getattr(profile, "work_partner_date", "") or "")
        if not partner_uid or partner_date != today:
            return False

        partner_profile = profiles.get(partner_uid)
        if partner_profile is None:
            return False
        if getattr(partner_profile, "work_partner_uid", "") != uid:
            return False
        if getattr(partner_profile, "work_partner_date", "") != today:
            return False

        log = activity_logs.get(uid)
        partner_log = activity_logs.get(partner_uid)
        if not hasattr(log, "days") or not hasattr(partner_log, "days"):
            return False

        my_starts = int(log.days.get(today, {}).get(Action.WORK_START, 0) or 0)
        partner_starts = int(partner_log.days.get(today, {}).get(Action.WORK_START, 0) or 0)
        return my_starts > 0 and partner_starts > 0

    async def reserve_work_contract(
        self,
        gid: str,
        uid: str,
        nick: str,
        mode: str,
    ) -> WorkContractResult:
        """预约下一次指定模式的打工合约。"""
        mode_config = self._config.work_modes.get(mode)
        if not mode_config:
            return WorkContractResult(ok=False, reason="invalid_mode")

        async with self._locks.acquire(gid):
            profile_store = self._profile_store(gid)
            profiles = profile_store.load_all()
            profile = ProfileStore.get_or_create(profiles, uid, nick, self._config.initial_coins)

            if profile.work_contract_reserved:
                return WorkContractResult(
                    ok=False,
                    reason="already_reserved",
                    mode=profile.work_contract_reserved,
                    coin_balance=profile.coins,
                )

            if profile.coins < self._config.work_contract_cost:
                return WorkContractResult(
                    ok=False,
                    reason="not_enough_coins",
                    coin_balance=profile.coins,
                )

            profile.coins -= self._config.work_contract_cost
            profile.work_contract_reserved = mode
            profile_store.save_all(profiles)
            return WorkContractResult(
                ok=True,
                mode=mode,
                coin_balance=profile.coins,
            )

    async def set_work_partner(
        self,
        gid: str,
        uid: str,
        partner_uid: str,
        nick: str,
        partner_nick: str,
        today: str,
    ) -> WorkPartnerResult:
        """绑定今日打工搭档。

        每日可绑定次数受 ``work_partner_daily_limit`` 控制；每次新绑定会先解除
        发起人当天原有的搭档关系（互绑对象也会被清空），再建立新互绑。
        """
        if not partner_uid or partner_uid == uid:
            return WorkPartnerResult(ok=False, reason="invalid_target")

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            ownerships = ownership_store.load_all()
            if not any(o.uid == uid for o in ownerships):
                return WorkPartnerResult(ok=False, reason="no_wife")
            if not any(o.uid == partner_uid for o in ownerships):
                return WorkPartnerResult(ok=False, reason="target_no_wife")

            profile_store = self._profile_store(gid)
            profiles = profile_store.load_all()
            profile = ProfileStore.get_or_create(profiles, uid, nick, self._config.initial_coins)
            partner_profile = ProfileStore.get_or_create(
                profiles, partner_uid, partner_nick, self._config.initial_coins
            )

            if profile.work_partner_uid == partner_uid and profile.work_partner_date == today:
                return WorkPartnerResult(ok=False, reason="already_partner", partner_uid=partner_uid)

            # 跨天重置发起人计数
            if profile.work_partner_count_date != today:
                profile.work_partner_count_date = today
                profile.work_partner_count = 0

            limit = max(1, self._config.work_partner_daily_limit)
            if profile.work_partner_count >= limit:
                return WorkPartnerResult(ok=False, reason="daily_limit")

            # 解除发起人当天原有搭档关系（双向清理）
            if profile.work_partner_date == today and profile.work_partner_uid:
                old_partner_uid = str(profile.work_partner_uid)
                old_partner_profile = profiles.get(old_partner_uid)
                if (
                    old_partner_profile is not None
                    and getattr(old_partner_profile, "work_partner_uid", "") == uid
                ):
                    old_partner_profile.work_partner_uid = ""
                    old_partner_profile.work_partner_date = ""

            # 对方若已与别人互绑则拒绝
            if (
                partner_profile.work_partner_date == today
                and partner_profile.work_partner_uid
                and partner_profile.work_partner_uid != uid
            ):
                return WorkPartnerResult(ok=False, reason="target_has_partner")

            profile.work_partner_uid = partner_uid
            profile.work_partner_date = today
            profile.work_partner_count += 1
            partner_profile.work_partner_uid = uid
            partner_profile.work_partner_date = today
            profile_store.save_all(profiles)
            return WorkPartnerResult(ok=True, partner_uid=partner_uid)

    async def start_work(
        self,
        gid: str,
        uid: str,
        nick: str,
        mode: str,
        today: str,
        selected_wid: str | None = None,
        umo: str = "",
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

            # 检查有可用老婆
            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None:
                return WorkStartResult(ok=False, reason="no_wife")

            selected = ownership_store.find_by_wid(selected_wid, ownerships) if selected_wid else primary
            if selected_wid and (selected is None or selected.uid != uid):
                return WorkStartResult(ok=False, reason="wife_not_found")

            # 检查同时打工上限
            working_count = sum(1 for o in ownerships if o.uid == uid and o.is_working)
            max_concurrent = max(1, self._config.work_max_concurrent)
            if working_count >= max_concurrent:
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
            selected.is_working = True
            selected.work_mode = mode
            selected.work_started_at = ts
            selected.work_ends_at = ts + duration
            selected.work_umo = umo

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
                ends_at=selected.work_ends_at,
                coin_balance=profile.coins,
                wid=selected.wid,
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
            activity_logs = activity_store.load_all()

            result = self._resolve_due_work_inner(
                gid, uid, nick, today, ownerships, profiles, activity_logs
            )
            if result is None:
                return None

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)
            return result

    def _resolve_due_work_inner(
        self,
        gid: str,
        uid: str,
        nick: str,
        today: str,
        ownerships: list[object],
        profiles: dict[str, object],
        activity_logs: dict[str, object],
    ) -> Optional[WorkSettleResult]:
        working = next((o for o in ownerships if o.uid == uid and o.is_working), None)
        if working is None:
            return None

        ts = now_ts()
        if ts < working.work_ends_at:
            return None

        mode = working.work_mode
        mode_config = self._config.work_modes.get(mode, {})
        profile = ProfileStore.get_or_create(profiles, uid, nick, coins=self._config.initial_coins)

        from ..utils.time import get_week_key, is_next_day
        from datetime import timezone

        if profile.work_last_settle_date and is_next_day(profile.work_last_settle_date, today):
            profile.work_streak += 1
        elif profile.work_last_settle_date != today:
            profile.work_streak = 1

        import random

        reward_min = mode_config.get("reward_min", 20)
        reward_max = mode_config.get("reward_max", 40)
        base_reward = random.randint(reward_min, reward_max)
        streak_bonus = 1.0 + (profile.work_streak - 1) * self._config.work_streak_bonus
        reward = int(base_reward * streak_bonus)

        contract_used = profile.work_contract_reserved == mode
        if contract_used:
            reward = int(reward * self._config.work_contract_reward_multiplier)
            profile.work_contract_reserved = ""

        partner_bonus_used = self._has_partner_bonus(profiles, activity_logs, uid, today)
        if partner_bonus_used:
            reward = int(reward * (1 + self._config.work_partner_bonus))

        intimacy_gain = mode_config.get("intimacy_gain", 5)
        working.intimacy = min(self._config.intimacy_max, working.intimacy + intimacy_gain)
        self.clear_work_state(working)

        profile.coins += reward
        profile.work_last_settle_date = today

        current_week = get_week_key(timezone.utc)
        if profile.work_week_key != current_week:
            profile.work_week_key = current_week
            profile.work_week_income = 0
        profile.work_week_income += reward

        ActivityStore.log(activity_logs, uid, today, Action.WORK_COMPLETE, 1)

        return WorkSettleResult(
            ok=True,
            reward=reward,
            intimacy_gain=intimacy_gain,
            streak=profile.work_streak,
            coin_balance=profile.coins,
            wid=working.wid,
            mode=mode,
            contract_used=contract_used,
            partner_bonus_used=partner_bonus_used,
        )

    async def resolve_stolen_work(
        self,
        gid: str,
        uid: str,
        today: str,
        selected_wid: str | None = None,
        attacker_uid: str | None = None,
        attacker_nick: str = "",
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
            activity_logs = activity_store.load_all()

            result = self._resolve_stolen_work_inner(
                gid,
                uid,
                today,
                ownerships,
                profiles,
                activity_logs,
                selected_wid=selected_wid,
                attacker_uid=attacker_uid,
                attacker_nick=attacker_nick,
            )
            if result is None:
                return None

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)
            return result

    def _resolve_stolen_work_inner(
        self,
        gid: str,
        uid: str,
        today: str,
        ownerships: list[object],
        profiles: dict[str, object],
        activity_logs: dict[str, object],
        selected_wid: str | None = None,
        attacker_uid: str | None = None,
        attacker_nick: str = "",
    ) -> Optional[WorkSettleResult]:
        ownership_store = self._ownership_store(gid)
        working = ownership_store.find_by_wid(selected_wid, ownerships) if selected_wid else next(
            (o for o in ownerships if o.uid == uid and o.is_working),
            None,
        )
        if working is None or working.uid != uid or not working.is_working:
            return None

        mode = working.work_mode
        mode_config = self._config.work_modes.get(mode, {})
        victim_profile = ProfileStore.get_or_create(profiles, uid, "", self._config.initial_coins)

        ts = now_ts()
        elapsed = ts - working.work_started_at
        total = working.work_ends_at - working.work_started_at
        progress = min(1.0, elapsed / total) if total > 0 else 0

        import random

        reward_min = mode_config.get("reward_min", 20)
        reward_max = mode_config.get("reward_max", 40)
        base_reward = random.randint(reward_min, reward_max)
        reward = int(base_reward * progress)

        contract_voided = victim_profile.work_contract_reserved == mode
        if contract_voided:
            victim_profile.work_contract_reserved = ""

        partner_broken = self._clear_partner_link(profiles, uid)

        recipient_balance = 0
        if attacker_uid:
            attacker_profile = ProfileStore.get_or_create(
                profiles, attacker_uid, attacker_nick, self._config.initial_coins
            )
            attacker_profile.coins += reward
            recipient_balance = attacker_profile.coins

        insurance_used = False
        insurance_bonus_coins = 0
        if victim_profile.inventory.get("insurance_card", 0) > 0:
            victim_profile.inventory["insurance_card"] = max(
                0, victim_profile.inventory.get("insurance_card", 0) - 1
            )
            insurance_bonus_coins = 20
            victim_profile.coins += insurance_bonus_coins
            victim_profile.inventory["revenge_token"] = victim_profile.inventory.get("revenge_token", 0) + 1
            insurance_used = True

        self.clear_work_state(working)
        ActivityStore.log(activity_logs, uid, today, Action.WORK_STOLEN, 1)

        return WorkSettleResult(
            ok=True,
            reward=reward,
            reason="stolen",
            wid=working.wid,
            mode=mode,
            coin_balance=recipient_balance,
            contract_voided=contract_voided,
            partner_broken=partner_broken,
            insurance_used=insurance_used,
            insurance_bonus_coins=insurance_bonus_coins,
        )

    def clear_work_state(self, ownership) -> None:
        """清空打工状态（独立封装）"""
        ownership.is_working = False
        ownership.work_mode = ""
        ownership.work_started_at = 0
        ownership.work_ends_at = 0
        ownership.work_umo = ""

    async def settle_all_due(self) -> list[tuple[str, "WorkSettleResult"]]:
        """扫描所有群，结算到期的打工。返回 [(umo, result), ...]"""
        results: list[tuple[str, WorkSettleResult]] = []
        groups_dir = self._paths.groups_dir
        if not os.path.isdir(groups_dir):
            return results

        today = get_today(ZoneInfo("Asia/Shanghai"))

        for gid in os.listdir(groups_dir):
            gid_path = os.path.join(groups_dir, gid)
            if not os.path.isdir(gid_path):
                continue
            ownership_file = os.path.join(gid_path, "ownership.json")
            if not os.path.isfile(ownership_file):
                continue

            try:
                ownership_store = OwnershipStore(self._paths, gid)
                ownerships = ownership_store.load_all()
                profile_store = self._profile_store(gid)
                profiles = profile_store.load_all()
                activity_store = self._activity_store(gid)
                activity_logs = activity_store.load_all()

                for o in ownerships:
                    if not o.is_working:
                        continue
                    ts = now_ts()
                    if ts < o.work_ends_at:
                        continue

                    profile = profiles.get(o.uid)
                    nick = profile.nick if profile else ""

                    result = self._resolve_due_work_inner(
                        gid, o.uid, nick, today, ownerships, profiles, activity_logs
                    )
                    if result and result.ok:
                        ownership_store.save_all(ownerships)
                        profile_store.save_all(profiles)
                        activity_store.save_all(activity_logs)
                        results.append((o.work_umo, result))
            except Exception:
                logger.error(f"结算群 {gid} 的到期打工失败")
                continue

        return results
