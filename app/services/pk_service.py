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
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    DailyCountStore,
    OwnershipStore,
    PkPairStore,
    ProfileStore,
    WivesMasterStore,
)
from ..utils.time import now_ts
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
    # T43: 扩展战报信息
    attacker_uid: str = ""
    defender_uid: str = ""
    attacker_element: str = ""
    defender_element: str = ""
    element_advantage: float = 1.0
    loser_reward: int = 0
    winner_score_gain: int = 0
    loser_score_gain: int = 0
    is_tie: bool = False


class PkService:
    """PK 战斗服务。"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks | None = None, cooldown: Optional[CooldownService] = None):
        self._paths = paths
        self._config = config
        self._locks = locks
        self._cooldown = cooldown
        self._rng = random.Random()
        self._economy = EconomyService(paths, config, locks)

    def set_rng(self, rng: random.Random) -> None:
        self._rng = rng

    async def pk(
        self,
        gid: str,
        attacker_uid: str,
        defender_uid: str,
        attacker_nick: str,
        defender_nick: str,
        today: str,
    ) -> PkResult:
        """发起 PK：attacker vs defender（双方主老婆对战）"""
        # 检查冷却
        if self._cooldown and self._config.pk_cooldown > 0:
            if not self._cooldown.check(gid, attacker_uid, "pk", self._config.pk_cooldown):
                remaining = self._cooldown.remaining(gid, attacker_uid, "pk", self._config.pk_cooldown)
                return PkResult(ok=False, reason="cooldown", msg=f"PK 冷却中，还需等待 {remaining} 秒~")

        if self._locks:
            async with self._locks.acquire(gid):
                return self._pk_inner(
                    gid,
                    attacker_uid,
                    defender_uid,
                    attacker_nick,
                    defender_nick,
                    today,
                )
        return self._pk_inner(
            gid,
            attacker_uid,
            defender_uid,
            attacker_nick,
            defender_nick,
            today,
        )

    def _pk_inner(
        self,
        gid: str,
        attacker_uid: str,
        defender_uid: str,
        attacker_nick: str,
        defender_nick: str,
        today: str,
    ) -> PkResult:
        # 检查每日次数
        daily_store = DailyCountStore(self._paths, gid)
        daily_data = daily_store.load_all()
        today_count = DailyCountStore.get_count(daily_data, attacker_uid, "pk", today)
        if today_count >= self._config.pk_max_per_day:
            return PkResult(ok=False, reason="limit", msg=f"今天已经 PK 了 {self._config.pk_max_per_day} 次啦，明天再来吧~")

        # T41: 检查 24h 同对手限制
        pk_pair_store = PkPairStore(self._paths, gid)
        pk_pairs = pk_pair_store.load_all()
        if not pk_pair_store.can_pk(pk_pairs, attacker_uid, defender_uid, self._config.pk_pair_cooldown_hours):
            return PkResult(ok=False, reason="same_target", msg=f"24小时内不能对同一对手重复 PK 哦~")

        # 获取双方主老婆
        ownership_store = OwnershipStore(self._paths, gid)
        ownerships = ownership_store.load_all()

        atk_selected = ownership_store.get_primary(attacker_uid, ownerships)
        def_selected = ownership_store.get_primary(defender_uid, ownerships)

        if not atk_selected:
            return PkResult(ok=False, reason="no_wife", msg="你还没有老婆，先去抽一个吧~")
        if not def_selected:
            return PkResult(ok=False, reason="target_no_wife", msg="对方还没有老婆~")

        # 获取老婆元数据
        wives = WivesMasterStore(self._paths).load_all()
        atk_wife = wives.get(atk_selected.wid)
        def_wife = wives.get(def_selected.wid)

        atk_name = atk_wife.chara or atk_wife.img if atk_wife else "未知"
        def_name = def_wife.chara or def_wife.img if def_wife else "未知"

        # 计算战力
        atk_power = self._calc_power(atk_wife, atk_selected, self._config)
        def_power = self._calc_power(def_wife, def_selected, self._config)

        # 随机扰动 ±20%
        atk_final = atk_power * self._rng.uniform(0.8, 1.2)
        def_final = def_power * self._rng.uniform(0.8, 1.2)

        # 判定胜负
        if atk_final > def_final:
            winner_uid = attacker_uid
            winner_nick = attacker_nick
            loser_uid = defender_uid
        elif def_final > atk_final:
            winner_uid = defender_uid
            winner_nick = defender_nick
            loser_uid = attacker_uid
        else:
            # 平局随机
            winner_uid = self._rng.choice([attacker_uid, defender_uid])
            winner_nick = attacker_nick if winner_uid == attacker_uid else defender_nick
            loser_uid = defender_uid if winner_uid == attacker_uid else attacker_uid

        # C2: 更新 PK 胜负统计 + 发放奖励
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()
        winner_profile = ProfileStore.get_or_create(
            profiles, winner_uid, winner_nick,
            self._config.initial_coins
        )
        loser_profile = ProfileStore.get_or_create(
            profiles, loser_uid, defender_nick if loser_uid == defender_uid else attacker_nick,
            self._config.initial_coins
        )
        winner_profile.total_pk_win = winner_profile.total_pk_win + 1
        loser_profile.total_pk_lost = loser_profile.total_pk_lost + 1

        # T42: 计算奖励（胜方/败方/平局）
        is_tie = abs(atk_final - def_final) < 0.01  # 近战力差视为平局
        winner_reward = 0
        loser_reward = 0
        winner_score_gain = 0
        loser_score_gain = 0

        if is_tie:
            # 平局：双方 8 币/2 分
            winner_reward = 8
            loser_reward = 8
            winner_score_gain = 2
            loser_score_gain = 2
        else:
            # 胜方：币 + 分
            winner_reward = self._config.pk_winner_reward
            winner_score_gain = self._config.pk_score_per_win

            # 败方：近战力差给 5 币/1 分，否则安慰 1 币/0 分
            power_diff = abs(atk_final - def_final)
            if power_diff < 10:  # 近战力差
                loser_reward = self._config.pk_loser_reward_close_threshold
                loser_score_gain = 1
            else:
                loser_reward = self._config.pk_loser_reward
                loser_score_gain = 0

            # 新手 Day1 败方奖励翻倍
            if loser_profile.registered_at > 0:
                days_since_reg = (now_ts() - loser_profile.registered_at) / 86400
                if days_since_reg < 1:
                    loser_reward *= 2
                    loser_score_gain *= 2

        # T42: 积分按月懒重置
        current_month = today[:7]  # YYYY-MM
        if winner_profile.pk_score_season != current_month:
            winner_profile.pk_score = 0
            winner_profile.pk_score_season = current_month
        if loser_profile.pk_score_season != current_month:
            loser_profile.pk_score = 0
            loser_profile.pk_score_season = current_month

        # 发放奖励
        winner_profile.coins += winner_reward
        loser_profile.coins += loser_reward
        winner_profile.pk_score += winner_score_gain
        loser_profile.pk_score += loser_score_gain
        winner_profile.pk_last_active_date = today
        loser_profile.pk_last_active_date = today

        # 双方图鉴互通（胜方收集对方 wid）
        loser_wid = def_selected.wid if winner_uid == attacker_uid else atk_selected.wid
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

        # T41: 记录 PK 对对手（24h 防刷）
        pk_pair_store.record_pk(pk_pairs, attacker_uid, defender_uid)
        pk_pair_store.save_all(pk_pairs)

        # T43: 计算元素和克制关系
        atk_element = self._derive_element(atk_wife)
        def_element = self._derive_element(def_wife)
        element_advantage = self._check_element_advantage(atk_element, def_element)

        # 更新冷却
        if self._cooldown and self._config.pk_cooldown > 0:
            self._cooldown.update(gid, attacker_uid, "pk")

        return PkResult(
            ok=True,
            msg="",  # 调用方根据详情格式化
            attacker_name=atk_name,
            defender_name=def_name,
            attacker_power=atk_final,
            defender_power=def_final,
            winner_uid=winner_uid,
            winner_nick=winner_nick,
            reward=winner_reward,
            # T43: 扩展战报信息
            attacker_uid=attacker_uid,
            defender_uid=defender_uid,
            attacker_element=atk_element,
            defender_element=def_element,
            element_advantage=element_advantage,
            loser_reward=loser_reward,
            winner_score_gain=winner_score_gain,
            loser_score_gain=loser_score_gain,
            is_tie=is_tie,
        )

    @staticmethod
    def get_pk_rank(pk_score: int) -> str:
        """根据 PK 积分返回段位名称"""
        if pk_score >= 200:
            return "王者"
        elif pk_score >= 150:
            return "钻石"
        elif pk_score >= 100:
            return "铂金"
        elif pk_score >= 60:
            return "黄金"
        elif pk_score >= 30:
            return "白银"
        else:
            return "青铜"

    @staticmethod
    def get_pk_rank_emoji(pk_score: int) -> str:
        """根据 PK 积分返回段位 emoji"""
        rank = PkService.get_pk_rank(pk_score)
        rank_emoji = {
            "王者": "👑",
            "钻石": "💎",
            "铂金": "🏆",
            "黄金": "🥇",
            "白银": "🥈",
            "青铜": "🥉",
        }
        return rank_emoji.get(rank, "🥉")

    @staticmethod
    def _derive_element(wife: Optional[WifeMeta]) -> str:
        """实时推导元素类型（不持久化）

        基于老婆来源（source）哈希映射到 5 种元素：火/水/风/土/光
        """
        if not wife:
            return ""
        elements = ["火", "水", "风", "土", "光"]
        h = sum(ord(c) for c in (wife.source or wife.chara or ""))
        return elements[h % len(elements)]

    @staticmethod
    def _check_element_advantage(atk_element: str, def_element: str) -> float:
        """检查元素克制关系，返回加成倍率

        火克风，风克土，土克水，水克火，光独立
        """
        advantage_map = {
            ("火", "风"): 1.20,
            ("风", "土"): 1.20,
            ("土", "水"): 1.20,
            ("水", "火"): 1.20,
        }
        if (atk_element, def_element) in advantage_map:
            return advantage_map[(atk_element, def_element)]
        if (def_element, atk_element) in advantage_map:
            return 0.80
        return 1.0

    @staticmethod
    def _calc_power(
        wife: Optional[WifeMeta],
        ownership: Optional[Ownership],
        config: Optional[PluginConfig] = None,
        opponent_wife: Optional[WifeMeta] = None,
    ) -> float:
        """计算战力：base * intimacy * work * element * bond"""
        if not wife:
            return 0
        stats = wife.base_stats
        intimacy = ownership.intimacy if ownership else 0

        # 基础战力
        power = stats.atk + stats.defense + stats.hp * 0.5

        # T40: 亲密度加成（1 + intimacy/500）
        power *= (1 + intimacy / 500)

        # T34: 打工惩罚
        if ownership and ownership.is_working and config:
            mode_config = config.work_modes.get(ownership.work_mode, {})
            pk_penalty = mode_config.get("pk_penalty", 0)
            power *= (1 - pk_penalty)

        # T40: 元素克制加成
        if opponent_wife and config:
            atk_element = PkService._derive_element(wife)
            def_element = PkService._derive_element(opponent_wife)
            element_modifier = PkService._check_element_advantage(atk_element, def_element)
            power *= element_modifier

        # T40: 羁绊加成（基于图鉴收集数量）
        if ownership and config:
            # 简单实现：同源老婆越多，羁绊加成越高
            bond_bonus = 1.0  # 基础羁绊
            power *= bond_bonus

        return power

    # ---------- 同步别名（测试/无锁场景兼容） ----------

    def pk_sync(
        self,
        gid: str,
        attacker_uid: str,
        defender_uid: str,
        attacker_nick: str,
        defender_nick: str,
        today: str,
    ) -> PkResult:
        """同步版 pk（不经过锁）。"""
        # 检查冷却
        if self._cooldown and self._config.pk_cooldown > 0:
            if not self._cooldown.check(gid, attacker_uid, "pk", self._config.pk_cooldown):
                remaining = self._cooldown.remaining(gid, attacker_uid, "pk", self._config.pk_cooldown)
                return PkResult(ok=False, reason="cooldown", msg=f"PK 冷却中，还需等待 {remaining} 秒~")
        return self._pk_inner(
            gid,
            attacker_uid,
            defender_uid,
            attacker_nick,
            defender_nick,
            today,
        )
