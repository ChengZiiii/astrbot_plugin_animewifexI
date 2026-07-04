"""QuestService 单元测试。

T50 重构：新手任务 + 标准任务双模式。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

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


def _seed_profile(paths: Paths, gid: str, uid: str, nick: str = "Alice", registered_at: float = 0):
    store = ProfileStore(paths, gid)
    profiles = store.load_all()
    profiles[uid] = UserProfile(uid=uid, nick=nick, coins=0, registered_at=registered_at)
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


class TestNewbieQuests:
    """新手任务测试（T50）。"""

    def test_day1_draw_once(self, quest, tmp_paths):
        """Day 1 新手任务：抽老婆 1 次。"""
        # 注册时间设置为现在（新手 Day 1）
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward == 10

    def test_day1_incomplete_returns_none(self, quest, tmp_paths):
        """Day 1 新手任务未完成返回 None。"""
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward is None

    def test_day2_pet_and_chat(self, quest, tmp_paths):
        """Day 2 新手任务：撸老婆 + 对话。"""
        # 注册时间设置为 1 天前（新手 Day 2）
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.INTIMACY, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.CHAT, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 86400 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward == 10

    def test_day3_pk_once(self, quest, tmp_paths):
        """Day 3 新手任务：PK 1 次。"""
        # 注册时间设置为 2 天前（新手 Day 3）
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 2 * 86400 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward == 10


class TestStandardQuests:
    """标准任务测试（T50）。"""

    def test_standard_quests_all_complete(self, quest, tmp_paths):
        """标准任务：全部完成。"""
        # 注册时间设置为 4 天前（标准任务）
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.INTIMACY, 2)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.WORK_START, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward == 10

    def test_standard_quests_partial(self, quest, tmp_paths):
        """标准任务：部分完成返回 None。"""
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.INTIMACY, 2)
        # 缺少 PK 和 打工

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward is None

    def test_standard_quests_pk_any(self, quest, tmp_paths):
        """标准任务：PK_WIN + PK_LOST + PK_TIE 都算。"""
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.INTIMACY, 2)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_LOST, 1)  # 用 PK_LOST
        _log_activity(tmp_paths, "g1", "u1", Action.WORK_START, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400 + 3600):
            reward = quest.check_and_complete_sync("g1", "u1")
            assert reward == 10


class TestGetQuestStatus:
    """任务状态查询测试（T50）。"""

    def test_empty_status_standard(self, quest, tmp_paths):
        """无活动时，标准任务状态。"""
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400):
            status = quest.get_quest_status("g1", "u1")
            assert len(status) == 4
            assert all(v is False for v in status.values())

    def test_partial_status_standard(self, quest, tmp_paths):
        """部分完成标准任务。"""
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400):
            status = quest.get_quest_status("g1", "u1")
            assert status["抽老婆 1 次"] is True
            assert status["亲密互动 2 次"] is False

    def test_all_done_status_standard(self, quest, tmp_paths):
        """全部完成标准任务。"""
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.INTIMACY, 2)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.WORK_START, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400):
            status = quest.get_quest_status("g1", "u1")
            assert all(status.values())


class TestIsCompleted:
    """is_completed 测试。"""

    def test_not_completed_initially(self, quest, tmp_paths):
        _seed_profile(tmp_paths, "g1", "u1")
        assert quest.is_completed("g1", "u1") is False

    def test_completed_after_all_quests(self, quest, tmp_paths):
        _seed_profile(tmp_paths, "g1", "u1", registered_at=1000000000)
        _log_activity(tmp_paths, "g1", "u1", Action.DRAW, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.INTIMACY, 2)
        _log_activity(tmp_paths, "g1", "u1", Action.PK_WIN, 1)
        _log_activity(tmp_paths, "g1", "u1", Action.WORK_START, 1)

        with patch("app.services.quest_service.now_ts", return_value=1000000000 + 4 * 86400 + 3600):
            quest.check_and_complete_sync("g1", "u1")
            assert quest.is_completed("g1", "u1") is True
