"""QuestService 单元测试。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.enums import Action
from app.models.profile import UserProfile
from app.services.plugin_config import PluginConfig
from app.services.quest_service import QuestService
from app.storage.paths import Paths
from app.storage.stores import ActivityStore, ProfileStore


@pytest.fixture
def tmp_paths(tmp_path):
    return Paths(str(tmp_path))


@pytest.fixture
def config():
    return PluginConfig(initial_coins=0, quest_complete_coins=10)


@pytest.fixture
def quest(tmp_paths, config):
    return QuestService(tmp_paths, config)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _seed_profile(paths: Paths, gid: str, uid: str, nick: str = "Alice"):
    store = ProfileStore(paths, gid)
    profiles = store.load_all()
    profiles[uid] = UserProfile(uid=uid, nick=nick, coins=0)
    store.save_all(profiles)


def _log_activity(paths: Paths, gid: str, uid: str, action: str, count: int = 1):
    store = ActivityStore(paths, gid)
    logs = store.load_all()
    from app.models.activity import ActivityLog
    log = logs.get(uid) or ActivityLog()
    today = _today()
    for _ in range(count):
        log.increment(today, action, 1)
    logs[uid] = log
    store.save_all(logs)


class TestCheckAndComplete:
    """任务完成检查测试。"""

    def test_no_activity_returns_none(self, quest, tmp_paths):
        """没有任何活动时返回 None。"""
        _seed_profile(tmp_paths, "g1", "u1")
        assert quest.check_and_complete_sync("g1", "u1") is None

    def test_partial_activity_returns_none(self, quest, tmp_paths):
        """只完成部分任务返回 None。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        assert quest.check_and_complete_sync("g1", "u1") is None

    def test_all_quests_done(self, quest, tmp_paths):
        """全部任务完成，返回奖励金额。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)
        # 被牛 0 次：不记录 NTR_LOST

        reward = quest.check_and_complete_sync("g1", "u1")
        assert reward == 10

    def test_all_quests_done_with_ntr_lost_fails(self, quest, tmp_paths):
        """被牛 1 次则任务失败。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_LOST, 1)

        assert quest.check_and_complete_sync("g1", "u1") is None

    def test_double_claim_prevented(self, quest, tmp_paths):
        """同一天不能领两次。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)

        quest.check_and_complete_sync("g1", "u1")
        assert quest.check_and_complete_sync("g1", "u1") is None

    def test_reward_added_to_coins(self, quest, tmp_paths):
        """奖励正确加到余额。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)

        quest.check_and_complete_sync("g1", "u1")

        store = ProfileStore(tmp_paths, "g1")
        profiles = store.load_all()
        assert profiles["u1"].coins == 10

    def test_quest_creates_profile_if_needed(self, quest, tmp_paths):
        """不存在的用户自动创建 profile。"""
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)

        reward = quest.check_and_complete_sync("g1", "u1")
        assert reward == 10


class TestGetQuestStatus:
    """任务状态查询测试。"""

    def test_empty_status(self, quest, tmp_paths):
        """无活动时，被牛0次任务完成，其他未完成。"""
        _seed_profile(tmp_paths, "g1", "u1")
        status = quest.get_quest_status("g1", "u1")
        assert len(status) == 4
        # 被牛0次：无NTR_LOST记录，count=0，满足条件
        assert status["被牛 0 次"] is True
        # 其他任务未完成
        assert status["抽老婆 1 次"] is False
        assert status["参与 PK 1 次"] is False
        assert status["牛成功 1 次"] is False

    def test_partial_status(self, quest, tmp_paths):
        """部分完成。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        status = quest.get_quest_status("g1", "u1")
        assert status["抽老婆 1 次"] is True
        assert status["参与 PK 1 次"] is False

    def test_all_done_status(self, quest, tmp_paths):
        """全部完成。"""
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)
        status = quest.get_quest_status("g1", "u1")
        assert all(status.values())


class TestIsCompleted:
    """is_completed 测试。"""

    def test_not_completed_initially(self, quest, tmp_paths):
        _seed_profile(tmp_paths, "g1", "u1")
        assert quest.is_completed("g1", "u1") is False

    def test_completed_after_all_quests(self, quest, tmp_paths):
        _seed_profile(tmp_paths, "g1", "u1")
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.NTR_SUCCESS, 1)
        quest.check_and_complete_sync("g1", "u1")
        assert quest.is_completed("g1", "u1") is True
