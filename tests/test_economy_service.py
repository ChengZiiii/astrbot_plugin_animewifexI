"""EconomyService 单元测试。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

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
        economy.earn("g1", "u1", 100, nick="Alice")
        assert economy.balance("g1", "u1") == 100


class TestEarn:
    """收入测试。"""

    def test_earn_positive_amount(self, economy):
        """正常发放。"""
        balance = economy.earn("g1", "u1", 50, nick="Alice")
        assert balance == 50

    def test_earn_multiple_times(self, economy):
        """多次发放累加。"""
        economy.earn("g1", "u1", 30, nick="Alice")
        balance = economy.earn("g1", "u1", 20, nick="Alice")
        assert balance == 50

    def test_earn_zero_amount_is_noop(self, economy):
        """发放 0 不改变余额。"""
        economy.earn("g1", "u1", 50, nick="Alice")
        balance = economy.earn("g1", "u1", 0, nick="Alice")
        assert balance == 50

    def test_earn_negative_amount_is_noop(self, economy):
        """发放负数不改变余额。"""
        economy.earn("g1", "u1", 50, nick="Alice")
        balance = economy.earn("g1", "u1", -10, nick="Alice")
        assert balance == 50

    def test_earn_creates_profile_if_needed(self, economy):
        """不存在的用户自动创建 profile。"""
        economy.earn("g1", "u1", 10, nick="Alice")
        assert economy.balance("g1", "u1") == 10

    def test_earn_returns_new_balance(self, economy):
        """返回发放后的余额。"""
        assert economy.earn("g1", "u1", 30) == 30
        assert economy.earn("g1", "u1", 20) == 50


class TestSpend:
    """支出测试。"""

    def test_spend_success(self, economy):
        """余额充足时扣款成功。"""
        economy.earn("g1", "u1", 100, nick="Alice")
        assert economy.spend("g1", "u1", 30) is True
        assert economy.balance("g1", "u1") == 70

    def test_spend_insufficient_balance(self, economy):
        """余额不足返回 False，不扣款。"""
        economy.earn("g1", "u1", 20, nick="Alice")
        assert economy.spend("g1", "u1", 30) is False
        assert economy.balance("g1", "u1") == 20

    def test_spend_exact_balance(self, economy):
        """余额刚好够时扣款成功。"""
        economy.earn("g1", "u1", 30, nick="Alice")
        assert economy.spend("g1", "u1", 30) is True
        assert economy.balance("g1", "u1") == 0

    def test_spend_zero_amount_is_noop(self, economy):
        """扣款 0 返回 True，不改变余额。"""
        economy.earn("g1", "u1", 50, nick="Alice")
        assert economy.spend("g1", "u1", 0) is True
        assert economy.balance("g1", "u1") == 50

    def test_spend_negative_amount_is_noop(self, economy):
        """扣款负数返回 True，不改变余额。"""
        economy.earn("g1", "u1", 50, nick="Alice")
        assert economy.spend("g1", "u1", -10) is True
        assert economy.balance("g1", "u1") == 50

    def test_spend_nonexistent_user(self, economy):
        """不存在的用户扣款失败。"""
        assert economy.spend("g1", "u1", 10) is False


class TestDailyCheckin:
    """每日签到测试。"""

    def test_checkin_first_time(self, economy):
        """首次签到成功，返回奖励金额。"""
        reward = economy.daily_checkin("g1", "u1", nick="Alice")
        assert reward == 20  # daily_checkin_coins 默认值

    def test_checkin_twice_same_day(self, economy):
        """同一天签到两次，第二次返回 None。"""
        economy.daily_checkin("g1", "u1", nick="Alice")
        assert economy.daily_checkin("g1", "u1", nick="Alice") is None

    def test_checkin_adds_coins(self, economy):
        """签到后余额增加。"""
        economy.daily_checkin("g1", "u1", nick="Alice")
        assert economy.balance("g1", "u1") == 20

    def test_checkin_creates_profile(self, economy):
        """不存在的用户签到自动创建 profile。"""
        economy.daily_checkin("g1", "u1", nick="Alice")
        assert economy.balance("g1", "u1") == 20

    def test_has_checked_in_false_initially(self, economy):
        """未签到时返回 False。"""
        assert economy.has_checked_in("g1", "u1") is False

    def test_has_checked_in_true_after_checkin(self, economy):
        """签到后返回 True。"""
        economy.daily_checkin("g1", "u1", nick="Alice")
        assert economy.has_checked_in("g1", "u1") is True

    def test_has_checked_in_nonexistent_user(self, economy):
        """不存在的用户返回 False。"""
        assert economy.has_checked_in("g1", "u1") is False


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
