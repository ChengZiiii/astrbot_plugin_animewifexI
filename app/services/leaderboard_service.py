"""排行榜服务：聚合活动日志 → 排序 → 输出 Top-N。

数据源：``ActivityStore`` 中 ``{uid: ActivityLog}`` 的滚动日志。
支持日榜（``days=1``）、周榜（``days=7``）、总榜（从 ``ProfileStore.total_*`` 读取）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from ..models.enums import Action
from ..storage.paths import Paths
from ..storage.stores import ActivityStore, ProfileStore
from .plugin_config import PluginConfig

__all__ = ["LeaderboardService", "LeaderboardEntry"]


@dataclass
class LeaderboardEntry:
    """排行榜单条"""

    uid: str
    nick: str
    value: int

    def __repr__(self) -> str:
        return f"LeaderboardEntry(uid={self.uid!r}, nick={self.nick!r}, value={self.value})"


# Action → 可排行的维度
_RANKABLE_ACTIONS = {
    "牛": Action.NTR_SUCCESS,
    "被牛": Action.NTR_LOST,
    "PK": Action.PK_WIN,
    "收集": "collection",
    "ntr": Action.NTR_SUCCESS,
    "ntr_lost": Action.NTR_LOST,
    "pk": Action.PK_WIN,
    "collection": "collection",
}

# 总榜使用的 profile 字段
_PROFILE_TOTAL_FIELDS = {
    Action.NTR_SUCCESS: "total_ntr_success",
    Action.NTR_LOST: "total_ntr_lost",
    Action.PK_WIN: "total_pk_win",
    Action.PK_LOST: "total_pk_lost",
}


class LeaderboardService:
    """排行榜聚合"""

    def __init__(self, paths: Paths, config: PluginConfig, tz: ZoneInfo):
        self._paths = paths
        self._config = config
        self._tz = tz

    def _date_range(self, days: int) -> List[str]:
        """返回最近 N 天的日期字符串列表（含今天）"""
        now = datetime.now(self._tz)
        return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    def resolve_action(self, action_key: str) -> Optional[str]:
        """将中文/英文 action key 解析为 Action 常量或 'collection'"""
        return _RANKABLE_ACTIONS.get(action_key)

    def rank_daily(
        self, gid: str, action: str, days: int = 1
    ) -> List[LeaderboardEntry]:
        """日榜/周榜：聚合最近 N 天的 activity 日志

        ``action`` 应为 Action 常量（如 ``Action.NTR_SUCCESS``）。
        """
        date_range = self._date_range(days)
        activity_store = ActivityStore(self._paths, gid)
        profile_store = ProfileStore(self._paths, gid)

        all_logs = activity_store.load_all()
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, log in all_logs.items():
            total = 0
            for date in date_range:
                day_data = log.get_day(date)
                total += day_data.get(action, 0)
            if total > 0:
                scores[uid] = total

        return self._build_entries(scores, profiles)

    def rank_alltime(self, gid: str, action: str) -> List[LeaderboardEntry]:
        """总榜：从 profile 的 total_* 字段读取

        ``action`` 应为 Action 常量（如 ``Action.NTR_SUCCESS``）。
        """
        field = _PROFILE_TOTAL_FIELDS.get(action)
        if not field:
            return []

        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            val = getattr(profile, field, 0)
            if val > 0:
                scores[uid] = val

        return self._build_entries(scores, profiles)

    def rank_collection(self, gid: str) -> List[LeaderboardEntry]:
        """收集榜：按 profile.collection 长度排序"""
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            count = len(profile.collection) if profile.collection else 0
            if count > 0:
                scores[uid] = count

        return self._build_entries(scores, profiles)

    def _build_entries(
        self, scores: Dict[str, int], profiles: Dict
    ) -> List[LeaderboardEntry]:
        """将 uid→score 映射排序并截取 Top-N"""
        entries = []
        for uid, score in scores.items():
            profile = profiles.get(uid)
            nick = profile.nick if profile else uid
            entries.append(LeaderboardEntry(uid=uid, nick=nick, value=score))

        entries.sort(key=lambda e: e.value, reverse=True)
        return entries[: self._config.leaderboard_top_n]
