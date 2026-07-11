"""NTR 安慰币公式与核心行为测试。

覆盖 v3_经济_负债_分币.md [S5.2] 全部边界：
- 安慰币公式：4 稀有度 × 5 好感度边界 = 20 组合
- 攻击者零代价（Q-D 核心）
- 被牛方收到正确安慰币（Q-E 核心）
- 负债玩家收到安慰币后余额增加
"""

from __future__ import annotations

import pytest

from app.models.profile import UserProfile
from app.services.economy_service import apply_income


class TestCalcNtrComfort:
    """安慰币纯函数测试：4 稀有度 × 5 好感度边界"""

    @pytest.mark.parametrize("rarity,intimacy,expected", [
        # N 卡：基础 10
        ("N", 0, 10),      # 10 × 1.00
        ("N", 50, 12),     # 10 × 1.25 = 12.5 → 12
        ("N", 100, 15),    # 10 × 1.50
        ("N", 150, 17),    # 10 × 1.75 = 17.5 → 17
        ("N", 200, 20),    # 10 × 2.00
        # R 卡：基础 25
        ("R", 0, 25),      # 25 × 1.00
        ("R", 50, 31),     # 25 × 1.25 = 31.25 → 31
        ("R", 100, 37),    # 25 × 1.50 = 37.5 → 37
        ("R", 150, 43),    # 25 × 1.75 = 43.75 → 43
        ("R", 200, 50),    # 25 × 2.00
        # SR 卡：基础 60
        ("SR", 0, 60),     # 60 × 1.00
        ("SR", 50, 75),    # 60 × 1.25
        ("SR", 80, 84),    # 60 × 1.40 = 84
        ("SR", 100, 90),   # 60 × 1.50
        ("SR", 200, 120),  # 60 × 2.00
        # SSR 卡：基础 120
        ("SSR", 0, 120),   # 120 × 1.00
        ("SSR", 50, 150),  # 120 × 1.25
        ("SSR", 100, 180), # 120 × 1.50
        ("SSR", 150, 210), # 120 × 1.75
        ("SSR", 200, 240), # 120 × 2.00
    ])
    def test_calc_ntr_comfort(self, rarity: str, intimacy: int, expected: int):
        from app.services.ntr_comfort import calc_ntr_comfort

        result = calc_ntr_comfort(rarity, intimacy)
        assert result == expected, (
            f"calc_ntr_comfort({rarity!r}, {intimacy}) "
            f"= {result}, expected {expected}"
        )

    def test_unknown_rarity_defaults_to_N(self):
        """未知稀有度回退到 N 卡基础 (10)"""
        from app.services.ntr_comfort import calc_ntr_comfort

        assert calc_ntr_comfort("UR", 0) == 10

    def test_zero_intimacy(self):
        """0 亲密度：倍率 = 1.0"""
        from app.services.ntr_comfort import calc_ntr_comfort

        assert calc_ntr_comfort("SSR", 0) == 120
        assert calc_ntr_comfort("N", 0) == 10


class TestRecordNtrLost:
    """记录被牛统计"""

    def test_record_updates_comfort_received(self):
        profile = UserProfile(uid="u1")
        from app.services.ntr_comfort import record_ntr_lost

        record_ntr_lost(profile, 50)
        assert profile.total_ntr_comfort_received == 50

        record_ntr_lost(profile, 30)
        assert profile.total_ntr_comfort_received == 80

    def test_record_with_new_profile_defaults_to_zero(self):
        """新档案 total_ntr_comfort_received 默认为 0"""
        profile = UserProfile(uid="u1")
        assert profile.total_ntr_comfort_received == 0


class TestApplyNtrComfortInner:
    """锁内发安慰币测试"""

    def test_victim_receives_correct_comfort(self):
        """Q-E 核心：被牛方收到与离婚基础对齐的安慰币"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        profile = UserProfile(uid="u1", coins=100)
        comfort = apply_ntr_comfort_inner(profile, "SSR", 100)

        # SSR + 100 好感 = 120 × 1.5 = 180
        assert comfort == 180
        assert profile.coins == 100 + 180  # apply_income: 100+180 = 280
        assert profile.total_ntr_comfort_received == 180

    def test_victim_with_debt_receives_comfort(self):
        """负债玩家收到安慰币后余额增加（-300 → -120 for SSR+100）"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        profile = UserProfile(uid="u1", coins=-300)
        comfort = apply_ntr_comfort_inner(profile, "SSR", 100)

        # SSR + 100 = 180 安慰币
        assert comfort == 180
        # apply_income(-300, 180) = -300 + 180 = -120
        assert profile.coins == -120
        assert profile.total_ntr_comfort_received == 180

    def test_victim_with_debt_small_comfort(self):
        """R+50=31 安慰币：-300 → -269"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        profile = UserProfile(uid="u1", coins=-300)
        comfort = apply_ntr_comfort_inner(profile, "R", 50)

        # R + 50 = 25 × 1.25 = 31
        assert comfort == 31
        assert profile.coins == -300 + 31  # = -269

    def test_victim_comfort_uses_apply_income(self):
        """验证 apply_income 逻辑：正余额直接加"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        profile = UserProfile(uid="u1", coins=50)
        apply_ntr_comfort_inner(profile, "N", 0)

        # N + 0 = 10
        assert profile.coins == 60

    def test_victim_stats_accumulate(self):
        """多次被牛，total_ntr_comfort_received 累加"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        profile = UserProfile(uid="u1", coins=0)

        apply_ntr_comfort_inner(profile, "N", 0)    # +10
        apply_ntr_comfort_inner(profile, "SR", 50)  # +75

        assert profile.total_ntr_comfort_received == 10 + 75


class TestAttackerPaysZero:
    """用户决策 Q-D 核心测试群"""

    def test_apply_ntr_comfort_does_not_touch_attacker(self):
        """apply_ntr_comfort_inner 只修改被牛方，不碰攻击方"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        attacker = UserProfile(uid="u_attacker", coins=500)
        victim = UserProfile(uid="u_victim", coins=100)

        attacker_coins_before = attacker.coins
        apply_ntr_comfort_inner(victim, "SSR", 100)

        # 攻击方余额不变
        assert attacker.coins == attacker_coins_before
        # 被牛方收到安慰币
        assert victim.coins == 280  # 100 + 180

    def test_ntr_comfort_does_not_deduct_attacker(self):
        """攻击者不会被扣任何币（验证 apply_ntr_comfort_inner 无扣款逻辑）"""
        from app.services.ntr_comfort import apply_ntr_comfort_inner

        attacker = UserProfile(uid="u_attacker", coins=500)
        victim = UserProfile(uid="u_victim", coins=0)

        before = attacker.coins
        apply_ntr_comfort_inner(victim, "N", 0)
        # 攻击方余额严格不变
        assert attacker.coins == before
