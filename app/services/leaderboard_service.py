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
from ..storage.stores import ActivityStore, OwnershipStore, ProfileStore, WivesMasterStore
from .plugin_config import PluginConfig

__all__ = ["LeaderboardService", "LeaderboardEntry", "DimensionResult"]


@dataclass
class LeaderboardEntry:
    """排行榜单条"""

    uid: str
    nick: str
    value: int
    rank: int = 0
    total_draws: int = 0
    streak_days: int = 0
    collection_count: int = 0
    titles: List[str] = None  # type: ignore[assignment]
    active_title: str = ""
    pk_score: int = 0
    coins: int = 0

    def __post_init__(self):
        if self.titles is None:
            self.titles = []

    def __repr__(self) -> str:
        return f"LeaderboardEntry(uid={self.uid!r}, nick={self.nick!r}, value={self.value})"


@dataclass
class DimensionResult:
    """单个维度排行结果"""

    label: str
    entries: List[LeaderboardEntry]
    has_data: bool = True
    unit: str = ""  # 数值后的单位标签


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

    # T51: 新增排行榜方法

    def rank_pk_score(self, gid: str) -> List[LeaderboardEntry]:
        """PK 积分榜：按当前赛季 PK 积分排序"""
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            if profile.pk_score > 0:
                scores[uid] = profile.pk_score

        return self._build_entries(scores, profiles)

    def rank_primary_intimacy(self, gid: str) -> List[LeaderboardEntry]:
        """亲密度榜：按主老婆亲密度排序"""
        from ..storage.stores import OwnershipStore

        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        ownership_store = OwnershipStore(self._paths, gid)
        ownerships = ownership_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            primary = ownership_store.get_primary(uid, ownerships)
            if primary and primary.intimacy > 0:
                scores[uid] = primary.intimacy

        return self._build_entries(scores, profiles)

    def rank_evil_points(self, gid: str) -> List[LeaderboardEntry]:
        """恶人值榜：按当前月作恶值排序"""
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            if profile.evil_points > 0:
                scores[uid] = profile.evil_points

        return self._build_entries(scores, profiles)

    def rank_work_week_income(self, gid: str) -> List[LeaderboardEntry]:
        """打工收入榜（周）：按本周打工收入排序"""
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            if profile.work_week_income > 0:
                scores[uid] = profile.work_week_income

        return self._build_entries(scores, profiles)

    def rank_work_streak(self, gid: str) -> List[LeaderboardEntry]:
        """打工连续天数榜：按连续打工天数排序"""
        profile_store = ProfileStore(self._paths, gid)
        profiles = profile_store.load_all()

        scores: Dict[str, int] = {}
        for uid, profile in profiles.items():
            if profile.work_streak > 0:
                scores[uid] = profile.work_streak

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

    def _enrich_entries(
        self, entries: List[LeaderboardEntry], profiles: Dict
    ) -> List[LeaderboardEntry]:
        """为排行榜条目填充用户档案数据（用于详细展示）"""
        for i, e in enumerate(entries):
            e.rank = i + 1
            profile = profiles.get(e.uid)
            if profile:
                e.total_draws = profile.total_draws
                e.streak_days = profile.streak_days
                e.collection_count = len(profile.collection) if profile.collection else 0
                e.titles = list(profile.titles) if profile.titles else []
                e.active_title = profile.active_title
                e.pk_score = profile.pk_score
                e.coins = profile.coins
        return entries

    def get_all_dimensions(self, gid: str, rank_type: str = "周") -> List[DimensionResult]:
        """一次性获取所有维度的排行结果（含富信息），用于默认播报。

        rank_type: "日" | "周" | "总"
        """
        dimensions = [
            ("收集数", "collection", "个", None),
            ("牛老婆", Action.NTR_SUCCESS, "次", None),
            ("被牛", Action.NTR_LOST, "次", None),
            ("亲密度", "intimacy", "点", None),
            ("PK段位", "pk_score", "分", None),
            ("作恶值", "evil_points", "点", None),
        ]

        results: List[DimensionResult] = []
        for label, action, unit, _ in dimensions:
            if action == "collection":
                entries = self.rank_collection(gid)
            elif action == "intimacy":
                entries = self.rank_primary_intimacy(gid)
            elif action == "pk_score":
                entries = self.rank_pk_score(gid)
            elif action == "evil_points":
                entries = self.rank_evil_points(gid)
            elif rank_type == "总":
                entries = self.rank_alltime(gid, action)
            else:
                days = 7 if rank_type == "周" else 1
                entries = self.rank_daily(gid, action, days)

            if entries:
                profile_store = ProfileStore(self._paths, gid)
                profiles = profile_store.load_all()
                entries = self._enrich_entries(entries, profiles)

            results.append(DimensionResult(
                label=label,
                entries=entries,
                has_data=len(entries) > 0,
                unit=unit,
            ))

        return results
