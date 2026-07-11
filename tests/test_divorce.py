"""离婚系统单元测试。

Phase D / v3 离婚系统：
- 返还公式（4 稀有度 × 5 好感度边界 = 20 组合）
- 分家产概率公式（0/50/80/100 边界）
- 7 天冷却边界
- 分家产金额双向公式（Q4 双向百分比 ±200 封顶）
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.profile import UserProfile
from app.models.ownership import Ownership
from app.services.divorce_service import (
    calc_divorce_return,
    calc_divorce_property_split_amount,
    calc_divorce_property_split_prob,
    validate_divorce_possible,
    apply_divorce_split,
)


class TestDivorceReturn:
    """返还公式：稀有度基础 × (1 + 好感度/100)"""

    @pytest.mark.parametrize("rarity,intimacy,expected", [
        # N: base=10
        ("N", 0, 10),
        ("N", 20, 12),
        ("N", 50, 15),
        ("N", 80, 18),
        ("N", 100, 20),
        # R: base=25
        ("R", 0, 25),
        ("R", 20, 30),
        ("R", 50, 37),
        ("R", 80, 45),
        ("R", 100, 50),
        # SR: base=60
        ("SR", 0, 60),
        ("SR", 20, 72),
        ("SR", 50, 90),
        ("SR", 80, 108),
        ("SR", 100, 120),
        # SSR: base=120
        ("SSR", 0, 120),
        ("SSR", 20, 144),
        ("SSR", 50, 180),
        ("SSR", 80, 216),
        ("SSR", 100, 240),
    ])
    def test_return_values(self, rarity, intimacy, expected):
        assert calc_divorce_return(rarity, intimacy) == expected

    def test_unknown_rarity_raises_key_error(self):
        with pytest.raises(KeyError):
            calc_divorce_return("UR", 50)


class TestDivorcePropertySplitProb:
    """分家产概率公式：min(0.50, 0.10 + intimacy/200)"""

    @pytest.mark.parametrize("intimacy,expected", [
        (0, 0.10),
        (20, 0.20),
        (50, 0.35),
        (80, 0.50),
        (100, 0.50),
        (200, 0.50),  # 超过好感度上限也封顶
    ])
    def test_prob_values(self, intimacy, expected):
        assert calc_divorce_property_split_prob(intimacy) == expected

    def test_prob_monotonic(self):
        """概率应单调递增直到封顶"""
        prev = 0.0
        for i in range(0, 101, 10):
            p = calc_divorce_property_split_prob(i)
            assert p >= prev
            prev = p


class TestDivorceCooldown:
    """7 天冷却边界"""

    def _make_profile(self, last_divorce_date: str) -> UserProfile:
        return UserProfile(
            uid="u1", nick="test",
            last_divorce_date=last_divorce_date,
        )

    def _make_ownership(self) -> Ownership:
        return Ownership(wid="w_test", uid="u1", intimacy=50)

    def test_no_previous_divorce_allowed(self):
        """从未离过婚 → 允许"""
        profile = self._make_profile("")
        ok, msg = validate_divorce_possible(profile, self._make_ownership(), "2026-07-12")
        assert ok is True
        assert msg == ""

    def test_exactly_7_days_ago_allowed(self):
        """7 天前离过婚（7 天差）→ 允许"""
        # 7-05 to 7-12 = exactly 7 days
        profile = self._make_profile("2026-07-05")
        ok, msg = validate_divorce_possible(profile, self._make_ownership(), "2026-07-12")
        assert ok is True

    def test_6_days_ago_denied(self):
        """6 天前离过婚 → 拒绝"""
        profile = self._make_profile("2026-07-06")
        ok, msg = validate_divorce_possible(profile, self._make_ownership(), "2026-07-12")
        assert ok is False
        assert "天" in msg

    def test_same_day_denied(self):
        """今天刚离过 → 拒绝"""
        profile = self._make_profile("2026-07-12")
        ok, msg = validate_divorce_possible(profile, self._make_ownership(), "2026-07-12")
        assert ok is False
        assert "天" in msg

    def test_working_wife_denied(self):
        """打工中的老婆不能离婚"""
        profile = self._make_profile("")
        o = self._make_ownership()
        o.is_working = True
        ok, msg = validate_divorce_possible(profile, o, "2026-07-12")
        assert ok is False
        assert "打工" in msg

    def test_in_battle_wife_denied(self):
        """战斗中的老婆不能离婚"""
        profile = self._make_profile("")
        o = self._make_ownership()
        o.is_in_battle = True
        ok, msg = validate_divorce_possible(profile, o, "2026-07-12")
        assert ok is False
        assert "战斗" in msg


class TestDivorcePropertySplitAmount:
    """分家产金额（Q4 双向百分比 ±200 封顶）"""

    def test_positive_balance_normal(self):
        """正余额 +500 → 分走 +100 → 新余额 +400"""
        assert calc_divorce_property_split_amount(500) == 100

    def test_positive_balance_cap(self):
        """正余额 +2000 → 分走 +200（封顶）"""
        assert calc_divorce_property_split_amount(2000) == 200

    def test_zero_balance(self):
        """零余额 → 分走 0"""
        assert calc_divorce_property_split_amount(0) == 0

    def test_negative_balance_normal(self):
        """负余额 -500 → 减压 -100（分走负值 = 负债减轻）"""
        assert calc_divorce_property_split_amount(-500) == -100

    def test_negative_balance_cap(self):
        """负余额 -2000 → 减压 -200（封顶）"""
        assert calc_divorce_property_split_amount(-2000) == -200

    def test_small_positive_balance(self):
        """小余额 +100 → 分走 +20"""
        assert calc_divorce_property_split_amount(100) == 20

    def test_small_negative_balance(self):
        """小负债 -100 → 减压 -20"""
        assert calc_divorce_property_split_amount(-100) == -20


class TestApplyDivorceSplit:
    """apply_divorce_split 完整流程"""

    def test_positive_500(self):
        new_coins, split = apply_divorce_split(500)
        assert new_coins == 400
        assert split == 100

    def test_positive_2000_capped(self):
        new_coins, split = apply_divorce_split(2000)
        assert new_coins == 1800
        assert split == 200

    def test_zero(self):
        new_coins, split = apply_divorce_split(0)
        assert new_coins == 0
        assert split == 0

    def test_negative_500(self):
        new_coins, split = apply_divorce_split(-500)
        assert new_coins == -400
        assert split == -100

    def test_negative_2000_capped(self):
        new_coins, split = apply_divorce_split(-2000)
        assert new_coins == -1800
        assert split == -200
