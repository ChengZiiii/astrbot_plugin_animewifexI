"""LeaderboardService 单元测试。"""

from __future__ import annotations

import pytest

from app.models.enums import Action
from app.services.leaderboard_service import LeaderboardEntry, LeaderboardService
from app.services.plugin_config import PluginConfig
from app.storage.paths import Paths
from app.storage.stores import ActivityStore, ProfileStore
from app.utils.time import get_today

from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def leaderboard_service(tmp_paths, config):
    return LeaderboardService(paths=tmp_paths, config=config, tz=TZ)


def _seed_profile(profile_store: ProfileStore, uid: str, nick: str, **kwargs):
    profiles = profile_store.load_all()
    from app.models.profile import UserProfile

    p = UserProfile.new_with_defaults(uid, nick)
    for k, v in kwargs.items():
        setattr(p, k, v)
    profiles[uid] = p
    profile_store.save_all(profiles)


def _seed_activity(activity_store: ActivityStore, uid: str, date: str, action: str, count: int):
    logs = activity_store.load_all()
    log = logs.get(uid) or __import__("app.models.activity", fromlist=["ActivityLog"]).ActivityLog()
    log.increment(date, action, count)
    logs[uid] = log
    activity_store.save_all(logs)


class TestLeaderboardEmpty:
    def test_empty_daily_returns_empty(self, leaderboard_service, tmp_paths):
        entries = leaderboard_service.rank_daily("g1", Action.NTR_SUCCESS, days=1)
        assert entries == []

    def test_empty_alltime_returns_empty(self, leaderboard_service, tmp_paths):
        entries = leaderboard_service.rank_alltime("g1", Action.NTR_SUCCESS)
        assert entries == []

    def test_empty_collection_returns_empty(self, leaderboard_service, tmp_paths):
        entries = leaderboard_service.rank_collection("g1")
        assert entries == []


class TestLeaderboardDaily:
    def test_single_user_today(self, leaderboard_service, tmp_paths):
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice")
        a_store = ActivityStore(tmp_paths, "g1")
        today = get_today(TZ)
        _seed_activity(a_store, "u1", today, Action.NTR_SUCCESS, 5)

        entries = leaderboard_service.rank_daily("g1", Action.NTR_SUCCESS, days=1)
        assert len(entries) == 1
        assert entries[0].uid == "u1"
        assert entries[0].nick == "Alice"
        assert entries[0].value == 5

    def test_multiple_users_sorted(self, leaderboard_service, tmp_paths):
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice")
        _seed_profile(ps, "u2", "Bob")
        _seed_profile(ps, "u3", "Charlie")
        a_store = ActivityStore(tmp_paths, "g1")
        today = get_today(TZ)
        _seed_activity(a_store, "u1", today, Action.NTR_SUCCESS, 3)
        _seed_activity(a_store, "u2", today, Action.NTR_SUCCESS, 10)
        _seed_activity(a_store, "u3", today, Action.NTR_SUCCESS, 7)

        entries = leaderboard_service.rank_daily("g1", Action.NTR_SUCCESS, days=1)
        assert len(entries) == 3
        assert entries[0].nick == "Bob"
        assert entries[0].value == 10
        assert entries[1].nick == "Charlie"
        assert entries[1].value == 7
        assert entries[2].nick == "Alice"
        assert entries[2].value == 3

    def test_weekly_aggregates_7_days(self, leaderboard_service, tmp_paths):
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice")
        a_store = ActivityStore(tmp_paths, "g1")
        from datetime import datetime, timedelta

        now = datetime.now(TZ)
        for i in range(7):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            _seed_activity(a_store, "u1", date, Action.NTR_SUCCESS, 1)

        entries = leaderboard_service.rank_daily("g1", Action.NTR_SUCCESS, days=7)
        assert len(entries) == 1
        assert entries[0].value == 7

    def test_top_n_truncation(self, leaderboard_service, tmp_paths):
        ps = ProfileStore(tmp_paths, "g1")
        a_store = ActivityStore(tmp_paths, "g1")
        today = get_today(TZ)
        for i in range(15):
            uid = f"u{i}"
            _seed_profile(ps, uid, f"User{i}")
            _seed_activity(a_store, uid, today, Action.NTR_SUCCESS, i)

        entries = leaderboard_service.rank_daily("g1", Action.NTR_SUCCESS, days=1)
        # Default top_n is 10
        assert len(entries) == 10
        assert entries[0].value == 14  # highest


class TestLeaderboardAlltime:
    def test_alltime_from_profile(self, leaderboard_service, tmp_paths):
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", total_ntr_success=50)
        _seed_profile(ps, "u2", "Bob", total_ntr_success=30)

        entries = leaderboard_service.rank_alltime("g1", Action.NTR_SUCCESS)
        assert len(entries) == 2
        assert entries[0].nick == "Alice"
        assert entries[0].value == 50


class TestLeaderboardCollection:
    def test_collection_ranking(self, leaderboard_service, tmp_paths):
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", collection=["w1", "w2", "w3"])
        _seed_profile(ps, "u2", "Bob", collection=["w1"])

        entries = leaderboard_service.rank_collection("g1")
        assert len(entries) == 2
        assert entries[0].nick == "Alice"
        assert entries[0].value == 3


class TestLeaderboardResolveAction:
    def test_chinese_ntr(self, leaderboard_service):
        assert leaderboard_service.resolve_action("牛") == Action.NTR_SUCCESS

    def test_chinese_ntr_lost(self, leaderboard_service):
        assert leaderboard_service.resolve_action("被牛") == Action.NTR_LOST

    def test_collection(self, leaderboard_service):
        assert leaderboard_service.resolve_action("收集") == "collection"

    def test_unknown_returns_none(self, leaderboard_service):
        assert leaderboard_service.resolve_action("不存在") is None


# T51: 新增排行榜测试

class TestLeaderboardPkScore:
    """PK 积分榜测试"""

    def test_pk_score_ranking(self, leaderboard_service, tmp_paths):
        """PK 积分榜排序"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", pk_score=100)
        _seed_profile(ps, "u2", "Bob", pk_score=200)
        _seed_profile(ps, "u3", "Charlie", pk_score=50)

        entries = leaderboard_service.rank_pk_score("g1")
        assert len(entries) == 3
        assert entries[0].nick == "Bob"
        assert entries[0].value == 200
        assert entries[1].nick == "Alice"
        assert entries[1].value == 100
        assert entries[2].nick == "Charlie"
        assert entries[2].value == 50

    def test_pk_score_excludes_zero(self, leaderboard_service, tmp_paths):
        """积分为 0 的用户不参与排名"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", pk_score=100)
        _seed_profile(ps, "u2", "Bob", pk_score=0)

        entries = leaderboard_service.rank_pk_score("g1")
        assert len(entries) == 1
        assert entries[0].nick == "Alice"


class TestLeaderboardPrimaryIntimacy:
    """亲密度榜测试"""

    def test_primary_intimacy_ranking(self, leaderboard_service, tmp_paths):
        """亲密度榜排序"""
        from app.models.ownership import Ownership
        from app.storage.stores import OwnershipStore

        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice")
        _seed_profile(ps, "u2", "Bob")

        # 创建主老婆记录
        os = OwnershipStore(tmp_paths, "g1")
        ownerships = os.load_all()
        ownerships.append(Ownership(uid="u1", wid="w1", is_primary=True, intimacy=50))
        ownerships.append(Ownership(uid="u2", wid="w2", is_primary=True, intimacy=80))
        os.save_all(ownerships)

        entries = leaderboard_service.rank_primary_intimacy("g1")
        assert len(entries) == 2
        assert entries[0].nick == "Bob"
        assert entries[0].value == 80
        assert entries[1].nick == "Alice"
        assert entries[1].value == 50

    def test_no_primary_excluded(self, leaderboard_service, tmp_paths):
        """没有主老婆的用户不参与排名"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice")

        entries = leaderboard_service.rank_primary_intimacy("g1")
        assert len(entries) == 0


class TestLeaderboardEvilPoints:
    """恶人值榜测试"""

    def test_evil_points_ranking(self, leaderboard_service, tmp_paths):
        """恶人值榜排序"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", evil_points=5)
        _seed_profile(ps, "u2", "Bob", evil_points=10)
        _seed_profile(ps, "u3", "Charlie", evil_points=3)

        entries = leaderboard_service.rank_evil_points("g1")
        assert len(entries) == 3
        assert entries[0].nick == "Bob"
        assert entries[0].value == 10
        assert entries[1].nick == "Alice"
        assert entries[1].value == 5
        assert entries[2].nick == "Charlie"
        assert entries[2].value == 3

    def test_evil_points_excludes_zero(self, leaderboard_service, tmp_paths):
        """作恶值为 0 的用户不参与排名"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", evil_points=5)
        _seed_profile(ps, "u2", "Bob", evil_points=0)

        entries = leaderboard_service.rank_evil_points("g1")
        assert len(entries) == 1
        assert entries[0].nick == "Alice"


class TestLeaderboardWorkWeekIncome:
    """打工收入榜（周）测试"""

    def test_work_week_income_ranking(self, leaderboard_service, tmp_paths):
        """打工收入榜排序"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", work_week_income=100)
        _seed_profile(ps, "u2", "Bob", work_week_income=200)

        entries = leaderboard_service.rank_work_week_income("g1")
        assert len(entries) == 2
        assert entries[0].nick == "Bob"
        assert entries[0].value == 200
        assert entries[1].nick == "Alice"
        assert entries[1].value == 100

    def test_work_week_income_excludes_zero(self, leaderboard_service, tmp_paths):
        """收入为 0 的用户不参与排名"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", work_week_income=100)
        _seed_profile(ps, "u2", "Bob", work_week_income=0)

        entries = leaderboard_service.rank_work_week_income("g1")
        assert len(entries) == 1
        assert entries[0].nick == "Alice"


class TestLeaderboardWorkStreak:
    """打工连续天数榜测试"""

    def test_work_streak_ranking(self, leaderboard_service, tmp_paths):
        """连续打工天数榜排序"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", work_streak=5)
        _seed_profile(ps, "u2", "Bob", work_streak=10)

        entries = leaderboard_service.rank_work_streak("g1")
        assert len(entries) == 2
        assert entries[0].nick == "Bob"
        assert entries[0].value == 10
        assert entries[1].nick == "Alice"
        assert entries[1].value == 5

    def test_work_streak_excludes_zero(self, leaderboard_service, tmp_paths):
        """连续天数为 0 的用户不参与排名"""
        ps = ProfileStore(tmp_paths, "g1")
        _seed_profile(ps, "u1", "Alice", work_streak=5)
        _seed_profile(ps, "u2", "Bob", work_streak=0)

        entries = leaderboard_service.rank_work_streak("g1")
        assert len(entries) == 1
        assert entries[0].nick == "Alice"
