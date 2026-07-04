"""EconomyService 单元测试。"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# 确保能导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.economy_service import EconomyService
from app.services.plugin_config import PluginConfig
from app.storage.paths import Paths


@pytest.fixture
def tmp_paths(tmp_path):
    """提供临时目录的 Paths 实例。"""
    return Paths(str(tmp_path))


@pytest.fixture
def config():
    return PluginConfig(initial_coins=0)


@pytest.fixture
def economy(tmp_paths, config):
    return EconomyService(tmp_paths, config)


class TestBalance:
    """余额查询测试。"""

    def test_balance_nonexistent_user_returns_zero(self, economy, tmp_paths):
        """不存在的用户余额为 0。"""
        assert economy.balance("g1", "u1") == 0

    def test_balance_after_earn(self, economy):
        """earn 后余额正确。"""
        economy.earn_sync("g1", "u1", 100, nick="Alice")
        assert economy.balance("g1", "u1") == 100


class TestEarn:
    """收入测试。"""

    def test_earn_positive_amount(self, economy):
        """正常发放。"""
        balance = economy.earn_sync("g1", "u1", 50, nick="Alice")
        assert balance == 50

    def test_earn_multiple_times(self, economy):
        """多次发放累加。"""
        economy.earn_sync("g1", "u1", 30, nick="Alice")
        balance = economy.earn_sync("g1", "u1", 20, nick="Alice")
        assert balance == 50

    def test_earn_zero_amount_is_noop(self, economy):
        """发放 0 不改变余额。"""
        economy.earn_sync("g1", "u1", 50, nick="Alice")
        balance = economy.earn_sync("g1", "u1", 0, nick="Alice")
        assert balance == 50

    def test_earn_negative_amount_is_noop(self, economy):
        """发放负数不改变余额。"""
        economy.earn_sync("g1", "u1", 50, nick="Alice")
        balance = economy.earn_sync("g1", "u1", -10, nick="Alice")
        assert balance == 50

    def test_earn_creates_profile_if_needed(self, economy):
        """不存在的用户自动创建 profile。"""
        economy.earn_sync("g1", "u1", 10, nick="Alice")
        assert economy.balance("g1", "u1") == 10

    def test_earn_returns_new_balance(self, economy):
        """返回发放后的余额。"""
        assert economy.earn_sync("g1", "u1", 30) == 30
        assert economy.earn_sync("g1", "u1", 20) == 50


class TestSpend:
    """支出测试。"""

    def test_spend_success(self, economy):
        """余额充足时扣款成功。"""
        economy.earn_sync("g1", "u1", 100, nick="Alice")
        assert economy.spend_sync("g1", "u1", 30) is True
        assert economy.balance("g1", "u1") == 70

    def test_spend_insufficient_balance(self, economy):
        """余额不足返回 False，不扣款。"""
        economy.earn_sync("g1", "u1", 20, nick="Alice")
        assert economy.spend_sync("g1", "u1", 30) is False
        assert economy.balance("g1", "u1") == 20

    def test_spend_exact_balance(self, economy):
        """余额刚好够时扣款成功。"""
        economy.earn_sync("g1", "u1", 30, nick="Alice")
        assert economy.spend_sync("g1", "u1", 30) is True
        assert economy.balance("g1", "u1") == 0

    def test_spend_zero_amount_is_noop(self, economy):
        """扣款 0 返回 True，不改变余额。"""
        economy.earn_sync("g1", "u1", 50, nick="Alice")
        assert economy.spend_sync("g1", "u1", 0) is True
        assert economy.balance("g1", "u1") == 50

    def test_spend_negative_amount_is_noop(self, economy):
        """扣款负数返回 True，不改变余额。"""
        economy.earn_sync("g1", "u1", 50, nick="Alice")
        assert economy.spend_sync("g1", "u1", -10) is True
        assert economy.balance("g1", "u1") == 50

    def test_spend_nonexistent_user(self, economy):
        """不存在的用户扣款失败。"""
        assert economy.spend_sync("g1", "u1", 10) is False


class TestDailyCheckin:
    """每日签到测试。"""

    def test_checkin_first_time(self, economy):
        """首次签到成功，返回 (reward, bonus, item)。"""
        result = economy.daily_checkin_sync("g1", "u1", nick="Alice")
        assert result is not None
        reward, bonus_coins, bonus_item = result
        assert reward == 20  # daily_checkin_coins 默认值
        assert bonus_coins == 0  # 首日无额外奖励
        assert bonus_item is None

    def test_checkin_twice_same_day(self, economy):
        """同一天签到两次，第二次返回 None。"""
        economy.daily_checkin_sync("g1", "u1", nick="Alice")
        assert economy.daily_checkin_sync("g1", "u1", nick="Alice") is None

    def test_checkin_adds_coins(self, economy):
        """签到后余额增加。"""
        economy.daily_checkin_sync("g1", "u1", nick="Alice")
        assert economy.balance("g1", "u1") == 20

    def test_checkin_creates_profile(self, economy):
        """不存在的用户签到自动创建 profile。"""
        economy.daily_checkin_sync("g1", "u1", nick="Alice")
        assert economy.balance("g1", "u1") == 20

    def test_checkin_streak_days(self, economy):
        """签到后 streak_days 正确更新。"""
        from app.storage.stores import ProfileStore
        economy.daily_checkin_sync("g1", "u1", nick="Alice")
        store = ProfileStore(economy._paths, "g1")
        profiles = store.load_all()
        profile = profiles["u1"]
        assert profile.streak_days == 1

    def test_has_checked_in_false_initially(self, economy):
        """未签到时返回 False。"""
        assert economy.has_checked_in("g1", "u1") is False

    def test_has_checked_in_true_after_checkin(self, economy):
        """签到后返回 True。"""
        economy.daily_checkin_sync("g1", "u1", nick="Alice")
        assert economy.has_checked_in("g1", "u1") is True

    def test_has_checked_in_nonexistent_user(self, economy):
        """不存在的用户返回 False。"""
        assert economy.has_checked_in("g1", "u1") is False

    def test_checkin_writes_activity_log(self, economy):
        """签到写入活动日志 Action.CHECKIN。"""
        from app.models.enums import Action
        from app.storage.stores import ActivityStore
        economy.daily_checkin_sync("g1", "u1", nick="Alice")
        activity_store = ActivityStore(economy._paths, "g1")
        logs = activity_store.load_all()
        log = logs.get("u1")
        assert log is not None
        today = economy._today()
        day_data = log.get_day(today)
        assert day_data.get(Action.CHECKIN, 0) >= 1

    def test_claim_weekly_surprise_box(self, economy):
        from app.models.activity import ActivityLog
        from app.models.enums import Action
        from app.storage.stores import ActivityStore

        activity_store = ActivityStore(economy._paths, "g1")
        logs = activity_store.load_all()
        log = ActivityLog()
        for day in ("2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11"):
            log.increment(day, Action.CHECKIN, 1)
        logs["u1"] = log
        activity_store.save_all(logs)

        with patch("app.services.economy_service.get_week_key", return_value="2026-W28"):
            result = economy.claim_weekly_surprise_box_sync("g1", "u1", nick="Alice")
        assert result == (100, "draw_ticket_single")

    def test_weekly_surprise_box_not_repeated(self, economy):
        from app.models.activity import ActivityLog
        from app.models.enums import Action
        from app.storage.stores import ActivityStore, ProfileStore

        activity_store = ActivityStore(economy._paths, "g1")
        logs = activity_store.load_all()
        log = ActivityLog()
        for day in ("2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11"):
            log.increment(day, Action.CHECKIN, 1)
        logs["u1"] = log
        activity_store.save_all(logs)

        with patch("app.services.economy_service.get_week_key", return_value="2026-W28"):
            assert economy.claim_weekly_surprise_box_sync("g1", "u1", nick="Alice") is not None
            assert economy.claim_weekly_surprise_box_sync("g1", "u1", nick="Alice") is None


class TestProfileManipulation:
    """直接操作 profile 的方法测试。"""

    def test_add_coins_to_profile(self, economy, tmp_paths):
        """直接给 profile 加币。"""
        from app.models.profile import UserProfile
        from app.storage.stores import ProfileStore

        profile = UserProfile(uid="u1", nick="Alice", coins=50)
        result = economy.add_coins_to_profile(profile, 30)
        assert result.coins == 80

    def test_deduct_coins_from_profile_success(self, economy):
        """直接从 profile 扣币成功。"""
        from app.models.profile import UserProfile

        profile = UserProfile(uid="u1", nick="Alice", coins=50)
        assert economy.deduct_coins_from_profile(profile, 30) is True
        assert profile.coins == 20

    def test_deduct_coins_from_profile_insufficient(self, economy):
        """直接从 profile 扣币余额不足。"""
        from app.models.profile import UserProfile

        profile = UserProfile(uid="u1", nick="Alice", coins=20)
        assert economy.deduct_coins_from_profile(profile, 30) is False
        assert profile.coins == 20  # 不变
