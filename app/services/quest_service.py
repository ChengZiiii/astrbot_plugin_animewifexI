"""每日任务服务。

任务模板（ROADMAP.md §5.1）：

* 抽老婆 1 次
* 参与 PK 1 次
* 被牛 0 次（即当日未被牛）
* 牛成功 1 次

完成自动发币，写入 ``profile.quest_completed_date`` 防重领。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ..models.enums import Action
from ..models.profile import UserProfile
from ..storage.paths import Paths
from ..storage.stores import ActivityStore, ProfileStore
from .economy_service import EconomyService
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.quest")

__all__ = ["QuestService"]

# 任务定义：(action_key, 需要的次数, 显示名)
QUEST_TEMPLATES = [
    (Action.DRAW, 1, "抽老婆 1 次"),
    (Action.PK_WIN, 1, "参与 PK 1 次"),
    (Action.NTR_LOST, 0, "被牛 0 次"),  # 特殊：0 表示当日不能有此行为
    (Action.NTR_SUCCESS, 1, "牛成功 1 次"),
]


class QuestService:
    """每日任务服务。"""

    def __init__(self, paths: Paths, config: PluginConfig):
        self._paths = paths
        self._config = config
        self._economy = EconomyService(paths, config)

    def check_and_complete(
        self, gid: str, uid: str, nick: str = ""
    ) -> Optional[int]:
        """检查任务完成状态，完成则发币并返回奖励金额。

        已完成返回 None（防重领）。
        """
        today = self._today()

        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick,
            self._config.default_capacity, self._config.initial_coins
        )

        # 已完成则跳过
        if profile.quest_completed_date == today:
            logger.debug("quest: gid=%s uid=%s already completed", gid, uid)
            return None

        # 检查今日活动日志
        act_store = ActivityStore(self._paths, gid)
        logs = act_store.load_all()
        log = logs.get(uid)

        if not self._all_quests_done(log, today):
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

        if profile and profile.quest_completed_date == today:
            return {q[2]: True for q in QUEST_TEMPLATES}

        act_store = ActivityStore(self._paths, gid)
        logs = act_store.load_all()
        log = logs.get(uid)

        status: Dict[str, bool] = {}
        for action_key, required, label in QUEST_TEMPLATES:
            if action_key == Action.NTR_LOST:
                # 被牛 0 次：当日被牛次数 == 0
                ntr_lost = self._get_action_count(log, today, action_key)
                status[label] = ntr_lost == 0
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

    def _all_quests_done(self, log: Optional[object], today: str) -> bool:
        """检查所有任务是否完成。"""
        for action_key, required, _ in QUEST_TEMPLATES:
            count = self._get_action_count(log, today, action_key)
            if action_key == Action.NTR_LOST:
                # 被牛 0 次
                if count != 0:
                    return False
            else:
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
