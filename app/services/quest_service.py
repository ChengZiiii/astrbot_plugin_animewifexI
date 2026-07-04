"""每日任务服务。

任务模板（T50 重构）：

新手任务（注册前 3 天）：
* day1_draw_once: 抽老婆 1 次
* day2_pet_and_chat: 撸老婆 + 对话
* day3_pk_once: PK 1 次

标准任务（新手期后）：
* 抽老婆 1 次
* 亲密互动 2 次
* PK 1 次
* 打工 1 次

完成自动发币，写入 ``profile.quest_completed_date`` 防重领。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from ..models.enums import Action
from ..models.profile import UserProfile
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import ActivityStore, ProfileStore
from ..utils.time import now_ts
from .economy_service import EconomyService
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.quest")

__all__ = ["QuestService"]

# 新手任务模板：(action_key, 需要的次数, 显示名)
NEWBIE_QUESTS = {
    1: [  # Day 1
        (Action.DRAW, 1, "抽老婆 1 次"),
    ],
    2: [  # Day 2
        (Action.INTIMACY, 1, "撸老婆 1 次"),
        (Action.CHAT, 1, "对话 1 次"),
    ],
    3: [  # Day 3
        (Action.PK_WIN, 1, "PK 1 次"),  # PK_WIN 或 PK_LOST 或 PK_TIE 都算
    ],
}

# 标准任务模板：(action_key, 需要的次数, 显示名)
STANDARD_QUESTS = [
    (Action.DRAW, 1, "抽老婆 1 次"),
    (Action.INTIMACY, 2, "亲密互动 2 次"),
    ("pk_any", 1, "PK 1 次"),  # 特殊：PK_WIN + PK_LOST + PK_TIE 求和
    (Action.WORK_START, 1, "打工 1 次"),
]


class QuestService:
    """每日任务服务。"""

    def __init__(self, paths: Paths, config: PluginConfig, locks: GroupLocks | None = None):
        self._paths = paths
        self._config = config
        self._locks = locks
        self._economy = EconomyService(paths, config, locks)

    def _get_newbie_day(self, profile: UserProfile) -> int:
        """获取新手天数（1-3），如果不是新手期返回 0。"""
        if profile.registered_at <= 0:
            return 0  # 旧玩家，无注册时间
        days_since_reg = (now_ts() - profile.registered_at) / 86400
        if days_since_reg < 1:
            return 1
        elif days_since_reg < 2:
            return 2
        elif days_since_reg < 3:
            return 3
        return 0  # 超过 3 天

    def _get_quests_for_profile(self, profile: UserProfile) -> List[Tuple[str, int, str]]:
        """根据用户 profile 返回对应的任务列表。"""
        newbie_day = self._get_newbie_day(profile)
        if newbie_day > 0 and newbie_day in NEWBIE_QUESTS:
            return NEWBIE_QUESTS[newbie_day]
        return STANDARD_QUESTS

    async def check_and_complete(
        self, gid: str, uid: str, nick: str = ""
    ) -> Optional[int]:
        """检查任务完成状态，完成则发币并返回奖励金额。

        已完成返回 None（防重领）。
        """
        if self._locks:
            async with self._locks.acquire(gid):
                return self._check_and_complete_inner(gid, uid, nick)
        return self._check_and_complete_inner(gid, uid, nick)

    def _check_and_complete_inner(self, gid: str, uid: str, nick: str) -> Optional[int]:
        today = self._today()

        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick,
            self._config.initial_coins
        )

        # 已完成则跳过
        if profile.quest_completed_date == today:
            logger.debug("quest: gid=%s uid=%s already completed", gid, uid)
            return None

        # 检查今日活动日志
        act_store = ActivityStore(self._paths, gid)
        logs = act_store.load_all()
        log = logs.get(uid)

        # 获取当前应该完成的任务
        quests = self._get_quests_for_profile(profile)

        if not self._all_quests_done(log, today, quests):
            logger.debug("quest: gid=%s uid=%s not all quests done", gid, uid)
            return None

        # 全部完成，发币
        reward = self._config.quest_complete_coins
        profile.coins += reward
        profile.quest_completed_date = today
        store.save_all(profiles)

        logger.debug("quest: gid=%s uid=%s reward=%d -> balance=%d",
                      gid, uid, reward, profile.coins)
        return reward

    def get_quest_status(self, gid: str, uid: str) -> Dict[str, bool]:
        """获取各任务完成状态（用于展示进度）。"""
        today = self._today()
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)

        if not profile:
            # 不存在的用户，返回默认状态
            return {q[2]: False for q in STANDARD_QUESTS}

        if profile.quest_completed_date == today:
            quests = self._get_quests_for_profile(profile)
            return {q[2]: True for q in quests}

        act_store = ActivityStore(self._paths, gid)
        logs = act_store.load_all()
        log = logs.get(uid)

        quests = self._get_quests_for_profile(profile)
        status: Dict[str, bool] = {}
        for action_key, required, label in quests:
            if action_key == "pk_any":
                # 特殊：PK_WIN + PK_LOST + PK_TIE 求和
                pk_count = (
                    self._get_action_count(log, today, Action.PK_WIN) +
                    self._get_action_count(log, today, Action.PK_LOST) +
                    self._get_action_count(log, today, Action.PK_TIE)
                )
                status[label] = pk_count >= required
            else:
                count = self._get_action_count(log, today, action_key)
                status[label] = count >= required

        return status

    def is_completed(self, gid: str, uid: str) -> bool:
        """查询今日任务是否已完成。"""
        today = self._today()
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)
        return profile is not None and profile.quest_completed_date == today

    def _all_quests_done(self, log: Optional[object], today: str, quests: List[Tuple[str, int, str]]) -> bool:
        """检查所有任务是否完成。"""
        for action_key, required, _ in quests:
            if action_key == "pk_any":
                # 特殊：PK_WIN + PK_LOST + PK_TIE 求和
                pk_count = (
                    self._get_action_count(log, today, Action.PK_WIN) +
                    self._get_action_count(log, today, Action.PK_LOST) +
                    self._get_action_count(log, today, Action.PK_TIE)
                )
                if pk_count < required:
                    return False
            else:
                count = self._get_action_count(log, today, action_key)
                if count < required:
                    return False
        return True

    @staticmethod
    def _get_action_count(log: Optional[object], today: str, action: str) -> int:
        """获取活动日志中某天某 action 的计数。"""
        if log is None:
            return 0
        # ActivityLog 结构：log.days[date][action] = count
        if hasattr(log, "days"):
            day_data = log.days.get(today)
            if isinstance(day_data, dict):
                return int(day_data.get(action, 0) or 0)
        return 0

    def _today(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")

    # ---------- 同步别名（测试/无锁场景兼容） ----------

    def check_and_complete_sync(
        self, gid: str, uid: str, nick: str = ""
    ) -> Optional[int]:
        """同步版 check_and_complete（不经过锁）。"""
        return self._check_and_complete_inner(gid, uid, nick)
