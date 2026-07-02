"""PK 战斗服务。

战力公式：``power = base_stats.atk + base_stats.def + base_stats.hp * 0.5 + intimacy * 2``

加入 ±20% 随机扰动，高战力胜，平局随机。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Optional

from ..models.enums import Action, AcquireVia
from ..models.ownership import Ownership
from ..models.profile import UserProfile
from ..models.wife import WifeMeta
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    DailyCountStore,
    OwnershipStore,
    ProfileStore,
    WivesMasterStore,
)
from .cooldown_service import CooldownService
from .economy_service import EconomyService
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.pk")

__all__ = ["PkService", "PkResult"]


@dataclass
class PkResult:
    ok: bool
    reason: str = ""
    msg: str = ""
    # 战斗详情
    attacker_name: str = ""
    defender_name: str = ""
    attacker_power: float = 0
    defender_power: float = 0
    winner_uid: str = ""
    winner_nick: str = ""
    reward: int = 0


class PkService:
    """PK 战斗服务。"""

    def __init__(self, paths: Paths, config: PluginConfig, cooldown: Optional[CooldownService] = None):
        self._paths = paths
        self._config = config
        self._cooldown = cooldown
        self._rng = random.Random()
        self._economy = EconomyService(paths, config)

    def set_rng(self, rng: random.Random) -> None:
        self._rng = rng

    def pk(
        self,
        gid: str,
        attacker_uid: str,
        defender_uid: str,
        attacker_nick: str,
        defender_nick: str,
        today: str,
    ) -> PkResult:
        """发起 PK：attacker vs defender"""
        # 检查冷却
        if self._cooldown and self._config.pk_cooldown > 0:
            if not self._cooldown.check(gid, attacker_uid, "pk", self._config.pk_cooldown):
                remaining = self._cooldown.remaining(gid, attacker_uid, "pk", self._config.pk_cooldown)
                return PkResult(ok=False, reason="cooldown", msg=f"PK 冷却中，还需等待 {remaining} 秒~")

        # 检查每日次数
        daily_store = DailyCountStore(self._paths, gid)
        daily_data = daily_store.load_all()
        today_count = DailyCountStore.get_count(daily_data, attacker_uid, "pk", today)
        if today_count >= self._config.pk_max_per_day:
            return PkResult(ok=False, reason="limit", msg=f"今天已经 PK 了 {self._config.pk_max_per_day} 次啦，明天再来吧~")

        # 获取双方主老婆
        ownership_store = OwnershipStore(self._paths, gid)
        ownerships = ownership_store.load_all()

        atk_primary = ownership_store.get_primary(attacker_uid, ownerships)
        def_primary = ownership_store.get_primary(defender_uid, ownerships)

        if not atk_primary:
            return PkResult(ok=False, reason="no_wife", msg="你还没有老婆，先去抽一个吧~")
        if not def_primary:
            return PkResult(ok=False, reason="target_no_wife", msg="对方还没有老婆~")

        # 获取老婆元数据
        wives = WivesMasterStore(self._paths).load_all()
        atk_wife = wives.get(atk_primary.wid)
        def_wife = wives.get(def_primary.wid)

        atk_name = atk_wife.chara or atk_wife.img if atk_wife else "未知"
        def_name = def_wife.chara or def_wife.img if def_wife else "未知"

        # 计算战力
        atk_power = self._calc_power(atk_wife, atk_primary)
        def_power = self._calc_power(def_wife, def_primary)

        # 随机扰动 ±20%
        atk_final = atk_power * self._rng.uniform(0.8, 1.2)
        def_final = def_power * self._rng.uniform(0.8, 1.2)

        # 判定胜负
        if atk_final > def_final:
            winner_uid = attacker_uid
            winner_nick = attacker_nick
        elif def_final > atk_final:
            winner_uid = defender_uid
            winner_nick = defender_nick
        else:
            # 平局随机
            winner_uid = self._rng.choice([attacker_uid, defender_uid])
            winner_nick = attacker_nick if winner_uid == attacker_uid else defender_nick

        # 发放奖励
        reward = self._config.pk_winner_reward
        self._economy.earn(gid, winner_uid, reward, winner_nick, "pk_win")

        # 双方图鉴互通（胜方收集对方 wid）
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()
        winner_profile = ProfileStore.get_or_create(
            profiles, winner_uid, winner_nick,
            self._config.default_capacity, self._config.initial_coins
        )
        loser_wid = def_primary.wid if winner_uid == attacker_uid else atk_primary.wid
        if loser_wid not in winner_profile.collection:
            winner_profile.collection.append(loser_wid)
        profile_store.save_all(profiles)

        # 记录活动日志
        activity_store = ActivityStore(self._paths, gid)
        activity_logs = activity_store.load_all()
        ActivityStore.log(activity_logs, attacker_uid, today, Action.PK_WIN if winner_uid == attacker_uid else Action.PK_LOST, 1)
        ActivityStore.log(activity_logs, defender_uid, today, Action.PK_LOST if winner_uid == attacker_uid else Action.PK_WIN, 1)
        activity_store.save_all(activity_logs)

        # 记录每日次数
        DailyCountStore.increment(daily_data, attacker_uid, "pk", today)
        daily_store.save_all(daily_data)

        # 更新冷却
        if self._cooldown and self._config.pk_cooldown > 0:
            self._cooldown.update(gid, attacker_uid, "pk")

        return PkResult(
            ok=True,
            msg="",  # 调用方根据详情格式化
            attacker_name=atk_name,
            defender_name=def_name,
            attacker_power=atk_power,
            defender_power=def_power,
            winner_uid=winner_uid,
            winner_nick=winner_nick,
            reward=reward,
        )

    @staticmethod
    def _calc_power(wife: Optional[WifeMeta], ownership: Optional[Ownership]) -> float:
        """计算战力：base_stats + intimacy 加成"""
        if not wife:
            return 0
        stats = wife.base_stats
        intimacy = ownership.intimacy if ownership else 0
        return stats.atk + stats.defense + stats.hp * 0.5 + intimacy * 2
