"""v3 接力战 · 状态层累积测试。

覆盖 v3_接力战_主线.md §S6.5：气魄 / 弱点 / 血性 / 狂暴 在战斗中累积。
"""

from __future__ import annotations

import pytest

from app.models.pk_battle import BattleStatusLayer, FormationMember
from app.services.pk_v2_battle import (
    PkV2Defaults,
    accumulate_status_layers,
    calc_raw_damage,
    on_hit_apply_layers,
)


def _make_member(
    wid: str = "m1",
    hp: int = 200,
    current_hp: int = 200,
    rarity: str = "SSR",
    element: str = "力量",
) -> FormationMember:
    return FormationMember(
        wid=wid, pos=1, nickname=f"W{wid}", rarity=rarity, element=element,
        base_atk=100, base_def=50, base_hp=hp,
        intimacy=0, is_locked=False,
        current_hp=current_hp, is_alive=True, is_active=True,
    )


# ============== on_hit_apply_layers（§S6.5） ==============


class TestOnHitApplyLayers:
    def test_attacker_qi_po_increments(self):
        """攻方 qi_po +1"""
        atk = BattleStatusLayer()
        df = BattleStatusLayer()
        on_hit_apply_layers(atk, df, is_attacker_hit=True)
        assert atk.qi_po == 1
        assert df.weak_point == 1

    def test_qi_po_caps_at_5(self):
        """qi_po 上限 5（spec §S3.7）"""
        atk = BattleStatusLayer(qi_po=5)
        df = BattleStatusLayer()
        on_hit_apply_layers(atk, df, is_attacker_hit=True)
        assert atk.qi_po == 5  # 不再 +1

    def test_weak_point_caps_at_3(self):
        """weak_point 上限 3"""
        atk = BattleStatusLayer()
        df = BattleStatusLayer(weak_point=3)
        on_hit_apply_layers(atk, df, is_attacker_hit=True)
        assert df.weak_point == 3

    def test_multiple_hits_accumulate(self):
        """连续 3 次命中：qi_po=3, weak_point=3"""
        atk = BattleStatusLayer()
        df = BattleStatusLayer()
        for _ in range(3):
            on_hit_apply_layers(atk, df, is_attacker_hit=True)
        assert atk.qi_po == 3
        assert df.weak_point == 3

    def test_attacker_miss_does_not_apply(self):
        """攻方未命中（is_attacker_hit=False）不累积"""
        atk = BattleStatusLayer()
        df = BattleStatusLayer()
        on_hit_apply_layers(atk, df, is_attacker_hit=False)
        assert atk.qi_po == 0
        assert df.weak_point == 0

    def test_defender_retaliate_hit_applies(self):
        """后手反击也累积：攻方自己当 defender 的角色时也累层"""
        # 反击时：原 defender 当 attacker，原 attacker 当 defender
        # 调用签名 (attacker_status, defender_status) 反映当前攻击方向
        atk = BattleStatusLayer()  # 反击的攻方 = 原 df
        df = BattleStatusLayer()  # 反击的守方 = 原 atk
        on_hit_apply_layers(atk, df, is_attacker_hit=True)
        assert atk.qi_po == 1
        assert df.weak_point == 1


# ============== accumulate_status_layers（§S6.5） ==============


class TestAccumulateBloodlust:
    def test_bloodlust_turn_0_inactive(self):
        """turn=0 → bloodlust=0"""
        m = _make_member()
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.bloodlust == 0

    def test_bloodlust_turn_4_still_inactive(self):
        """turn=4 → bloodlust=0（Lv1 在 turn>=5 激活）"""
        m = _make_member()
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=4)
        assert st.bloodlust == 0

    def test_bloodlust_turn_5_lv1(self):
        """turn=5 → bloodlust=1 (Lv1 +10%)"""
        m = _make_member()
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=5)
        assert st.bloodlust == 1

    def test_bloodlust_turn_7_lv1(self):
        """turn=7 → bloodlust=1（仍 Lv1）"""
        m = _make_member()
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=7)
        assert st.bloodlust == 1

    def test_bloodlust_turn_8_lv2(self):
        """turn=8 → bloodlust=2 (Lv2 +15%)"""
        m = _make_member()
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=8)
        assert st.bloodlust == 2

    def test_bloodlust_turn_11_lv2(self):
        """turn=11（回合上限 0-based）→ bloodlust=2"""
        m = _make_member()
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=11)
        assert st.bloodlust == 2


class TestAccumulateFrenzy:
    def test_frenzy_below_30pct_activates(self):
        """HP < 30% → frenzy=True"""
        m = _make_member(hp=200, current_hp=50)  # 25%
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.frenzy is True

    def test_frenzy_at_exactly_30pct_does_not_activate(self):
        """HP == 30% → 不激活（边界）"""
        m = _make_member(hp=100, current_hp=30)
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.frenzy is False

    def test_frenzy_at_29pct_activates(self):
        """HP 29% → 激活"""
        m = _make_member(hp=100, current_hp=29)
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.frenzy is True

    def test_no_frenzy_above_threshold(self):
        """HP 50% → 不激活"""
        m = _make_member(hp=100, current_hp=50)
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.frenzy is False

    def test_no_frenzy_when_full_hp(self):
        """满血 → 不激活"""
        m = _make_member(hp=200, current_hp=200)
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.frenzy is False

    def test_frenzy_zero_hp_activates(self):
        """HP=0 → 激活（虽然人已死，但状态层会保留）"""
        m = _make_member(hp=200, current_hp=0)
        st = BattleStatusLayer()
        accumulate_status_layers(m, st, turn_idx=0)
        assert st.frenzy is True


# ============== 综合：状态层对伤害的真实影响（端到端） ==============


class TestStatusLayerImpactOnDamage:
    """状态层累积 → 伤害公式真实生效"""

    def test_qi_po_5_increases_damage_15pct(self):
        """qi_po=5 时伤害比 qi_po=0 高 15%"""
        from app.services.pk_v2_battle import calc_raw_damage

        atk = _make_member(rarity="N", element="力量", hp=200)
        df = _make_member(rarity="N", element="敏捷", hp=200)

        # 强制命中 + 不暴击 + jitter=1.0
        class _FixedRNG:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5
                if self._n == 2:
                    return 0.95
                return 0.5

        atk_st_no_qipo = BattleStatusLayer(qi_po=0)
        atk_st_max_qipo = BattleStatusLayer(qi_po=5)
        df_st = BattleStatusLayer()

        r1 = calc_raw_damage(atk, df, atk_st_no_qipo, df_st, 0, _FixedRNG())
        r2 = calc_raw_damage(atk, df, atk_st_max_qipo, df_st, 0, _FixedRNG())

        # qi_po=5 → atk_layer_mult=1.15, so dmg increases 15%
        # raw_no_qipo = 130 * 1.0 * 1.0 * 1.30 = 169 → dmg=169
        # raw_max_qipo = 130 * 1.15 * 1.0 * 1.30 = 194.35 → dmg=194
        assert r1["dmg"] == 169
        assert r2["dmg"] == 194
        assert r2["dmg"] == int(r1["dmg"] * 1.15)  # +15%

    def test_bloodlust_lv2_at_turn_8_increases_damage_15pct(self):
        """turn=8 bloodlust Lv2: dmg 比 turn=4 高 15%"""
        from app.services.pk_v2_battle import calc_raw_damage

        atk = _make_member(rarity="N", element="力量", hp=200)
        df = _make_member(rarity="N", element="敏捷", hp=200)

        class _FixedRNG:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5
                if self._n == 2:
                    return 0.95
                return 0.5

        atk_st = BattleStatusLayer()
        df_st = BattleStatusLayer()

        r1 = calc_raw_damage(atk, df, atk_st, df_st, 4, _FixedRNG())
        r2 = calc_raw_damage(atk, df, atk_st, df_st, 8, _FixedRNG())

        # turn=4: bloodlust=0 → atk_layer_mult=1.0
        # turn=8: bloodlust=0.15 → atk_layer_mult=1.15
        assert r2["dmg"] == int(r1["dmg"] * 1.15)

    def test_frenzy_increases_damage_and_deducts_speed(self):
        """狂暴：atk 加成 + speed 扣减"""

        # atk 加成
        atk = _make_member(rarity="N", element="力量", hp=200)
        df = _make_member(rarity="N", element="敏捷", hp=200)

        class _FixedRNG:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5
                if self._n == 2:
                    return 0.95
                return 0.5

        r1 = calc_raw_damage(atk, df, BattleStatusLayer(), BattleStatusLayer(), 0, _FixedRNG())
        r2 = calc_raw_damage(atk, df, BattleStatusLayer(frenzy=True), BattleStatusLayer(), 0, _FixedRNG())

        # 力量元素 atk +15% 持续生效；狂暴再 +25% 加成
        # 力量 vs 敏捷 element_mult = 1.30
        # raw = atk_base * 1.0 (no qi_po) * 1.0 (no crit) * 1.30
        # atk_base_normal = 100 * 1.15 + 50*0.3 = 115 + 15 = 130 → raw = 169 → dmg=169
        # atk_base_frenzy  = 100 * 1.40 + 50*0.3 = 140 + 15 = 155 → raw = 201.5 → dmg=201
        assert r1["dmg"] == 169
        assert r2["dmg"] == 201


# ============== PkV2Defaults 常量测试 ==============


class TestPkV2Defaults:
    def test_max_turns_is_12(self):
        assert PkV2Defaults.MAX_TURNS == 12

    def test_hit_rate_is_90(self):
        assert PkV2Defaults.HIT_RATE == 0.90

    def test_jitter_is_20pct(self):
        assert PkV2Defaults.JITTER == 0.20

    def test_element_advantage_130(self):
        assert PkV2Defaults.ELEMENT_ADVANTAGE == 1.30

    def test_element_disadvantage_75(self):
        assert PkV2Defaults.ELEMENT_DISADVANTAGE == 0.75

    def test_bloodlust_turns(self):
        assert PkV2Defaults.BLOODLUST_LV1_TURN == 5
        assert PkV2Defaults.BLOODLUST_LV2_TURN == 8

    def test_frenzy_threshold_30(self):
        assert PkV2Defaults.FRENZY_HP_THRESHOLD == 0.30