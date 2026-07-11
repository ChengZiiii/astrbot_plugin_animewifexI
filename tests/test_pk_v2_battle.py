"""v3 接力战 · 战斗引擎测试（速度判定 + 伤害公式）。

覆盖 v3_接力战_主线.md §S6.1（速度判定）+ §S6.2（伤害公式 13 乘数）。
B.3（状态层累积）+ B.4（do_turn + 死亡换人）+ B.5（战斗超时）会在
后续 Task 加 case 进同一个文件。
"""

from __future__ import annotations

import random

import pytest

from app.models.pk_battle import BattleStatusLayer, FormationMember
from app.services.pk_v2_battle import (
    ELEMENT_ADVANTAGE_MAP,
    PkV2Defaults,
    calc_raw_damage,
    calc_speed,
    pick_first_striker,
)


# ============== 通用夹具 ==============


def _make_member(
    wid: str = "w_a",
    rarity: str = "SSR",
    element: str = "力量",
    atk: int = 100,
    defense: int = 50,
    hp: int = 200,
    intimacy: int = 0,
    is_locked: bool = False,
    current_hp: int = 200,
    work_mode: str = "",
) -> FormationMember:
    return FormationMember(
        wid=wid, pos=1, nickname=f"W{wid}", rarity=rarity, element=element,
        base_atk=atk, base_def=defense, base_hp=hp,
        intimacy=intimacy, is_locked=is_locked,
        current_hp=current_hp, is_alive=True, is_active=True,
        work_mode=work_mode,
    )


@pytest.fixture
def attacker():
    """标准攻击方：SSR 力量 atk=100 def=50 hp=200"""
    return _make_member("a1", rarity="SSR", element="力量", atk=100, defense=50, hp=200)


@pytest.fixture
def defender():
    """标准防御方：N 智力 atk=80 def=40 hp=200（智力不给 speed 加成）"""
    return _make_member("d1", rarity="N", element="智力", atk=80, defense=40, hp=200)


@pytest.fixture
def defender_agile():
    """克制关系用守方：N 敏捷 atk=80 def=40 hp=200（力量→敏捷=1.30）"""
    return _make_member("d2", rarity="N", element="敏捷", atk=80, defense=40, hp=200)


@pytest.fixture
def fresh_status():
    return BattleStatusLayer()


@pytest.fixture
def rng():
    return random.Random(42)


# ============== 速度判定（§S6.1） ==============


class TestCalcSpeed:
    """calc_speed：基础 + R/敏捷被动 + 锁定 + 狂暴"""

    def test_basic_speed_formula(self, attacker, fresh_status):
        """基础速度 = atk×0.3 + hp×0.2 = 100×0.3 + 200×0.2 = 30 + 40 = 70"""
        assert calc_speed(attacker, fresh_status) == 70

    def test_r_rarity_applies_speed_mult(self, attacker, fresh_status):
        """R 稀有度 speed ×1.10（attacker 改成 R）"""
        r_member = _make_member("r1", rarity="R", element="力量", atk=100, hp=200)
        # base 70, R ×1.10 → 77
        assert calc_speed(r_member, fresh_status) == 77

    def test_agility_element_applies_speed_mult(self, attacker, fresh_status):
        """敏捷元素 speed ×1.10"""
        agi_member = _make_member("g1", rarity="SSR", element="敏捷", atk=100, hp=200)
        # base 70, 敏捷 ×1.10 → 77
        assert calc_speed(agi_member, fresh_status) == 77

    def test_r_and_agility_stack_multiplicatively(self, attacker, fresh_status):
        """R + 敏捷同时：speed ×1.10 ×1.10 = 1.21"""
        m = _make_member("rg", rarity="R", element="敏捷", atk=100, hp=200)
        # base 70 * 1.21 = 84 (trunc to int)
        assert calc_speed(m, fresh_status) == 84

    def test_locked_applies_penalty(self, attacker, fresh_status):
        """锁定老婆 speed ×0.85"""
        locked = _make_member("lk", is_locked=True)
        # base 70 * 0.85 = 59
        assert calc_speed(locked, fresh_status) == 59

    def test_frenzy_applies_speed_penalty(self, attacker, fresh_status):
        """狂暴状态 speed ×0.75"""
        fresh_status.frenzy = True
        # base 70 * 0.75 = 52
        assert calc_speed(attacker, fresh_status) == 52

    def test_all_modifiers_stack(self, attacker):
        """R + 敏捷 + 锁定 + 狂暴 全部叠加"""
        m = _make_member("all", rarity="R", element="敏捷", is_locked=True)
        st = BattleStatusLayer(frenzy=True)
        # base 70 * 1.10 * 1.10 * 0.85 * 0.75 = 53.95 → 53
        assert calc_speed(m, st) == 53


class TestPickFirstStriker:
    def test_faster_atk_wins(self, attacker, defender, fresh_status, rng):
        """攻方 SSR atk=100 速度 70 vs 守方 N atk=80 速度 64 → atk 先手"""
        result = pick_first_striker(attacker, defender, fresh_status, fresh_status, rng)
        assert result == "atk"

    def test_faster_def_wins(self, attacker, defender, fresh_status, rng):
        """攻方减速 → def 先手"""
        slow = _make_member("s", rarity="N", element="智力", atk=10, hp=10)
        # base 10*0.3 + 10*0.2 = 5
        result = pick_first_striker(slow, defender, fresh_status, fresh_status, rng)
        assert result == "def"

    def test_tie_random_50_50(self, attacker, defender, fresh_status, rng):
        """平速度 → 50/50（注入 seed 后确定）"""
        # 两边同样的 member 让速度相等
        result = pick_first_striker(attacker, attacker, fresh_status, fresh_status, rng)
        assert result in ("atk", "def")

    def test_tie_rng_deterministic(self):
        """同样 seed 同样结果（可复现）"""
        m = _make_member()
        a = pick_first_striker(m, m, BattleStatusLayer(), BattleStatusLayer(), random.Random(42))
        b = pick_first_striker(m, m, BattleStatusLayer(), BattleStatusLayer(), random.Random(42))
        assert a == b

    def test_tie_rng_distribution_eventually_balanced(self):
        """1000 次平速度：atk/def 比例不会偏差太大（蒙特卡洛 sanity check）"""
        m = _make_member()
        rng = random.Random(123)
        atk_count = 0
        for _ in range(1000):
            if pick_first_striker(m, m, BattleStatusLayer(), BattleStatusLayer(), rng) == "atk":
                atk_count += 1
        # 期望 500，允许 ±10% 浮动
        assert 400 <= atk_count <= 600, f"atk_count={atk_count}, expected ~500"


# ============== 伤害公式（§S6.2 · 13 乘数） ==============


class TestCalcRawDamageBasic:
    def test_miss_returns_zero_damage(self, attacker, defender, fresh_status, rng):
        """10% 未命中 → dmg=0"""
        # 构造一个 rng 让 random() 返回 0.95（>0.90 必未中）
        rng = random.Random(0)  # seed=0 让 random() 序列稳定
        # random.Random(0) 的第一次 random() 是 0.8444 → 命中；改用 mock
        # 这里用概率法：多次调用直到拿到 miss
        for _ in range(2000):
            r = random.Random()
            # 强制命中失败：人为构造 mock 不优雅，直接构造一个总返回 0.95 的 Random 子类
            class _AlwaysMiss:
                def random(self) -> float:
                    return 0.95
            result = calc_raw_damage(attacker, defender, fresh_status, fresh_status, 0, _AlwaysMiss())
            if not result["hit"]:
                assert result["dmg"] == 0
                assert result["crit"] is False
                return
        pytest.fail("couldn't produce miss in 2000 tries (rng mock broken)")

    def test_hit_at_least_1_damage(self, attacker, defender, fresh_status, rng):
        """命中时 dmg >= 1（即使 raw 很小）"""
        class _AlwaysHit:
            def __init__(self, inner):
                self._inner = inner

            def random(self) -> float:
                v = self._inner.random()
                # 第一次必命中（hit_rate 0.90）
                if not hasattr(self, "_first"):
                    self._first = False
                    return 0.5  # < 0.90 命中
                return v
        r = _AlwaysHit(rng)
        # 用 atk=1 def=1 hp=1 的老婆让 raw 接近 0
        weak_att = _make_member(atk=1, defense=1, hp=1, current_hp=1)
        weak_df = _make_member(atk=1, defense=1, hp=1, current_hp=1)
        result = calc_raw_damage(weak_att, weak_df, fresh_status, fresh_status, 0, r)
        assert result["hit"] is True
        assert result["dmg"] >= 1


class TestCalcRawDamageMultipliers:
    """逐项乘数验证（按 spec §S6.2 顺序）"""

    def test_all_multipliers_default_at_zero_turn(self, attacker, defender_agile, fresh_status):
        """所有状态层=0, turn=0: 各乘数等于默认值（强制不暴击）

        使用 defender_agile (N 敏捷) 让 element_mult = 1.30（克制）。
        """
        # 强制命中 + 不暴击 + jitter=1.0
        class _FixedRNG:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5  # < 0.90 命中
                if self._n == 2:
                    return 0.95  # > 0.20 不暴击
                return 0.5  # jitter = 0.8 + 0.5*0.4 = 1.0
        result = calc_raw_damage(attacker, defender_agile, fresh_status, fresh_status, 0, _FixedRNG())
        m = result["multipliers"]
        # 1) atk_bonus_total: 力量 0.15 + 狂暴 0 = 0.15
        assert m["atk_bonus_total"] == pytest.approx(0.15)
        # 2) atk_layer_mult: qi_po=0 + bloodlust=0 (turn 0 < 5) = 1.0
        assert m["atk_layer_mult"] == pytest.approx(1.0)
        # 3) crit_rate: 0.10 base + SSR +0.10 = 0.20
        assert m["crit_rate"] == pytest.approx(0.20)
        # 4) crit_mult: 不暴击时 1.0
        assert m["crit_mult"] == pytest.approx(1.0)
        # 5) element_mult: SSR 力量 vs N 敏捷 = 1.30（克制）
        assert m["element_mult"] == pytest.approx(1.30)
        # 6) work_mult: 默认 1.0
        assert m["work_mult"] == pytest.approx(1.0)
        # 7) intimacy_mult: intimacy=0 = 1.0
        assert m["intimacy_mult"] == pytest.approx(1.0)
        # 8) lock_atk_mult: 未锁定 = 1.0
        assert m["lock_atk_mult"] == pytest.approx(1.0)
        # 9) damage_taken_mult: defender=N, attacker=SSR → 不触发 SR 减伤 = 1.0
        assert m["damage_taken_mult"] == pytest.approx(1.0)
        # 10) weak_point_mult: 0 层 = 1.0
        assert m["weak_point_mult"] == pytest.approx(1.0)

    def test_ssr_crit_rate_at_20_pct(self, attacker, defender, fresh_status, rng):
        """SSR 暴击率 = 0.10 base + 0.10 SSR = 0.20"""
        result = calc_raw_damage(attacker, defender, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["crit_rate"] == pytest.approx(0.20)

    def test_intellect_attacker_crit_rate_15(self, defender, fresh_status, rng):
        """智力攻击方：0.10 base + 0.05 智力 = 0.15（无 SSR）"""
        intel_atk = _make_member("i1", rarity="N", element="智力")
        result = calc_raw_damage(intel_atk, defender, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["crit_rate"] == pytest.approx(0.15)

    def test_intellect_defender_taken_crit_mult(self, attacker, fresh_status, rng):
        """智力受暴：crit_mult = 1.5 × 0.85 = 1.275（命中+暴击+智力守方）"""
        intel_def = _make_member("d_i", rarity="N", element="智力")
        # 强制命中 + 暴击
        class _HitCrit:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5  # < 0.90 → 命中
                if self._n == 2:
                    return 0.05  # < 0.20 → 暴击
                return 0.5  # 浮动
        result = calc_raw_damage(attacker, intel_def, fresh_status, fresh_status, 0, _HitCrit())
        assert result["hit"] is True
        assert result["crit"] is True
        assert result["multipliers"]["crit_mult"] == pytest.approx(1.275)

    def test_element_advantage_power_vs_agility(self, fresh_status, rng):
        """力量 → 敏捷 = 1.30（克制）"""
        atk = _make_member("p", rarity="N", element="力量")
        df = _make_member("a", rarity="N", element="敏捷")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(1.30)

    def test_element_advantage_agility_vs_intellect(self, fresh_status, rng):
        """敏捷 → 智力 = 1.30（克制）"""
        atk = _make_member("a", rarity="N", element="敏捷")
        df = _make_member("i", rarity="N", element="智力")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(1.30)

    def test_element_advantage_intellect_vs_power(self, fresh_status, rng):
        """智力 → 力量 = 1.30（克制）"""
        atk = _make_member("i", rarity="N", element="智力")
        df = _make_member("p", rarity="N", element="力量")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(1.30)

    def test_element_disadvantage_agility_vs_power(self, fresh_status, rng):
        """敏捷 → 力量 = 0.75（被克制）"""
        atk = _make_member("a", rarity="N", element="敏捷")
        df = _make_member("p", rarity="N", element="力量")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(0.75)

    def test_element_disadvantage_intellect_vs_agility(self, fresh_status, rng):
        """智力 → 敏捷 = 0.75（被克制）"""
        atk = _make_member("i", rarity="N", element="智力")
        df = _make_member("a", rarity="N", element="敏捷")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(0.75)

    def test_element_disadvantage_power_vs_intellect(self, fresh_status, rng):
        """力量 → 智力 = 0.75（被克制）"""
        atk = _make_member("p", rarity="N", element="力量")
        df = _make_member("i", rarity="N", element="智力")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(0.75)

    def test_element_neutral_same_element(self, fresh_status, rng):
        """同元素 = 1.0"""
        atk = _make_member("p1", rarity="N", element="力量")
        df = _make_member("p2", rarity="N", element="力量")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["element_mult"] == pytest.approx(1.0)

    def test_power_atk_mult_115(self, fresh_status, rng):
        """力量 atk 倍率：atk_bonus_total = 0.15"""
        atk = _make_member("p", rarity="N", element="力量")
        df = _make_member("a", rarity="N", element="智力")  # 智力吃暴击但本测不暴击
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["atk_bonus_total"] == pytest.approx(0.15)

    def test_locked_power_penalty(self, fresh_status, rng):
        """锁定老婆：lock_atk_mult = 0.85"""
        locked = _make_member("lk", is_locked=True)
        df = _make_member("d")
        result = calc_raw_damage(locked, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["lock_atk_mult"] == pytest.approx(0.85)

    def test_sr_defender_damage_reduce_against_ssr(self, fresh_status, rng):
        """SR 守方被 SSR 攻击：damage_taken_mult = 0.90"""
        atk = _make_member("s", rarity="SSR", element="力量")
        df = _make_member("d", rarity="SR", element="敏捷")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["damage_taken_mult"] == pytest.approx(0.90)

    def test_sr_defender_no_reduce_against_n(self, fresh_status, rng):
        """SR 守方被 N 攻击：不触发减伤 = 1.0"""
        atk = _make_member("n", rarity="N", element="力量")
        df = _make_member("d", rarity="SR", element="敏捷")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["damage_taken_mult"] == pytest.approx(1.0)

    def test_intimacy_mult(self, fresh_status, rng):
        """亲密度加成：1 + intimacy/500"""
        atk = _make_member("a", intimacy=100)
        df = _make_member("d")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["intimacy_mult"] == pytest.approx(1.20)

    def test_intimacy_max_120(self, fresh_status, rng):
        """亲密度 100 → 1.20"""
        atk = _make_member("a", intimacy=100)
        df = _make_member("d")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["intimacy_mult"] == pytest.approx(1.20)


class TestCalcRawDamageWorkMult:
    """work_mult 乘数（spec §S6.2 §8 / Phase 4 打工惩罚）

    work_mult 按 attacker.work_mode 查表：
    * ``normal``     → 0.85
    * ``overtime``   → 0.75
    * ``expedition`` → 0.65
    * 空 / 未知模式 → 1.0
    """

    def test_work_mult_normal_0_85(self, fresh_status, rng):
        """work_mode="normal" → work_mult = 0.85"""
        atk = _make_member("n1", work_mode="normal")
        df = _make_member("d1")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["work_mult"] == pytest.approx(0.85)

    def test_work_mult_overtime_0_75(self, fresh_status, rng):
        """work_mode="overtime" → work_mult = 0.75"""
        atk = _make_member("o1", work_mode="overtime")
        df = _make_member("d1")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["work_mult"] == pytest.approx(0.75)

    def test_work_mult_expedition_0_65(self, fresh_status, rng):
        """work_mode="expedition" → work_mult = 0.65"""
        atk = _make_member("e1", work_mode="expedition")
        df = _make_member("d1")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["work_mult"] == pytest.approx(0.65)

    def test_work_mult_empty_string_default_1_0(self, fresh_status, rng):
        """work_mode=""（默认）→ work_mult = 1.0（不在打工）"""
        atk = _make_member("z1", work_mode="")
        df = _make_member("d1")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["work_mult"] == pytest.approx(1.0)

    def test_work_mult_unknown_mode_default_1_0(self, fresh_status, rng):
        """work_mode=未知字符串 → work_mult = 1.0（兜底）"""
        atk = _make_member("u1", work_mode="bogus_mode")
        df = _make_member("d1")
        result = calc_raw_damage(atk, df, fresh_status, fresh_status, 0, rng)
        assert result["multipliers"]["work_mult"] == pytest.approx(1.0)

    def test_work_mult_propagates_to_raw_damage(self, fresh_status):
        """work_mult 实际参与伤害合成（normal 模式下 dmg 至少小于无惩罚基准）"""
        # 固定命中 + 不暴击 + jitter=1.0（jitter=0.5 → factor=1.0）
        class _Hit:
            def random(self) -> float:
                return 0.5

        atk_normal = _make_member("n2", work_mode="normal")
        atk_idle = _make_member("i2", work_mode="")
        df = _make_member("d2")

        r_normal = calc_raw_damage(atk_normal, df, fresh_status, fresh_status, 0, _Hit())
        r_idle = calc_raw_damage(atk_idle, df, fresh_status, fresh_status, 0, _Hit())
        # 0.85 倍率应该反映在 dmg 上（两次随机性相同 → dmg_normal = int(raw*0.85)）
        assert r_normal["dmg"] < r_idle["dmg"]
        # 同 raw 比例 0.85（±jitter 之前；此处 jitter=1.0 固定）
        # 严格的算式：dmg_normal / dmg_idle ≈ 0.85
        # 但 raw 包含 jitter=1.0, int() 截断可能让比例偏离一点
        ratio = r_normal["dmg"] / max(r_idle["dmg"], 1)
        assert 0.7 <= ratio <= 0.95, f"work_mult not propagated: ratio={ratio}"


class TestCalcRawDamageStatusLayers:
    """状态层对伤害的影响（接进 B.3 之前的契约：直接传 BattleStatusLayer）"""

    def test_qi_po_5_layers_15pct_atk(self, attacker, defender, rng):
        """qi_po=5 → atk_layer_mult = 1.15"""
        st = BattleStatusLayer(qi_po=5)
        result = calc_raw_damage(attacker, defender, st, fresh_status_default(), 0, rng)
        assert result["multipliers"]["atk_layer_mult"] == pytest.approx(1.15)

    def test_weak_point_3_layers_15pct_taken(self, attacker, defender, fresh_status, rng):
        """weak_point=3 → weak_point_mult = 1.15"""
        df_st = BattleStatusLayer(weak_point=3)
        result = calc_raw_damage(attacker, defender, fresh_status, df_st, 0, rng)
        assert result["multipliers"]["weak_point_mult"] == pytest.approx(1.15)

    def test_bloodlust_lv1_turn_5(self, attacker, defender, fresh_status, rng):
        """turn=5 → bloodlust_lv1 +10%"""
        result = calc_raw_damage(attacker, defender, fresh_status, fresh_status, 5, rng)
        assert result["multipliers"]["bloodlust_bonus"] == pytest.approx(0.10)

    def test_bloodlust_lv2_turn_8(self, attacker, defender, fresh_status, rng):
        """turn=8 → bloodlust_lv2 +15%"""
        result = calc_raw_damage(attacker, defender, fresh_status, fresh_status, 8, rng)
        assert result["multipliers"]["bloodlust_bonus"] == pytest.approx(0.15)

    def test_no_bloodlust_turn_0_to_4(self, attacker, defender, fresh_status, rng):
        """turn < 5 → bloodlust 0"""
        for t in range(5):
            result = calc_raw_damage(attacker, defender, fresh_status, fresh_status, t, rng)
            assert result["multipliers"]["bloodlust_bonus"] == pytest.approx(0.0)

    def test_frenzy_atk_bonus(self, attacker, defender, fresh_status, rng):
        """狂暴：atk_bonus_total 增加 0.25"""
        atk_st = BattleStatusLayer(frenzy=True)
        result = calc_raw_damage(attacker, defender, atk_st, fresh_status, 0, rng)
        # 力量 0.15 + 狂暴 0.25 = 0.40
        assert result["multipliers"]["atk_bonus_total"] == pytest.approx(0.40)


class TestCalcRawDamageJitter:
    """±20% 浮动（spec §S6.2 §13）"""

    def test_jitter_within_20pct(self, attacker, defender_agile, fresh_status):
        """多次调用 dmg 在 [0.8, 1.2] 区间内（raw 已包含 element_mult）"""
        # 固定命中 + 不暴击 + 变化 jitter
        class _HitNoCrit:
            def __init__(self, rng: random.Random):
                self._rng = rng
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5  # < 0.90 命中
                if self._n == 2:
                    return 0.95  # > 0.20 不暴击
                return self._rng.random()  # jitter 由真 rng 提供
        dmgs = []
        inner_rng = random.Random(42)
        for _ in range(200):
            r = calc_raw_damage(
                attacker, defender_agile, fresh_status, fresh_status, 0, _HitNoCrit(inner_rng)
            )
            assert r["hit"] is True
            assert r["crit"] is False
            dmgs.append(r["dmg"])

        # raw = atk_base * element_mult = (100*1.15 + 50*0.3) * 1.30 = 130 * 1.30 = 169
        raw_estimate = 169
        lo = int(raw_estimate * 0.79)  # 留 1% 余量
        hi = int(raw_estimate * 1.21) + 1
        assert min(dmgs) >= lo, f"min dmg {min(dmgs)} < {lo}"
        assert max(dmgs) <= hi, f"max dmg {max(dmgs)} > {hi}"

    def test_jitter_range_default(self, attacker, defender, fresh_status):
        """jitter 字段返回 [0.8, 1.2] 范围内的实数"""
        class _Hit:
            def random(self) -> float:
                return 0.5  # 命中
        jitters = []
        for _ in range(50):
            r = calc_raw_damage(attacker, defender, fresh_status, fresh_status, 0, _Hit())
            jitters.append(r["jitter"])
        assert all(0.8 <= j <= 1.2 for j in jitters)


# ============== 综合计算反推（端到端数值校验） ==============


class TestCalcRawDamageNumerical:
    """已知输入 → 已知 raw → 验证 dmg 浮动后落在正确区间"""

    def test_pure_formula_no_jitter_at_1(self, attacker, defender_agile, fresh_status):
        """jitter=1.0（人为固定）时 dmg == int(raw)"""
        class _FixedJitter:
            def random(self) -> float:
                return 0.5  # jitter = 0.8 + 0.5 * 0.4 = 1.0
        r = calc_raw_damage(attacker, defender_agile, fresh_status, fresh_status, 0, _FixedJitter())
        # raw = (100 * 1.15 + 50*0.3) * 1.0 * 1.0 * 1.30 * 1.0 * 1.0 * 1.0 * 1.0 * 1.0
        #     = 130 * 1.30 = 169
        # dmg = int(169 * 1.0) = 169
        assert r["dmg"] == 169
        assert r["jitter"] == pytest.approx(1.0)

    def test_full_13_multipliers_applied(self):
        """同时应用所有 13 个乘数，验证合成正确（jitter 固定=1.0）"""
        atk = _make_member("a", rarity="SSR", element="力量",
                            atk=100, defense=50, hp=200, intimacy=100, is_locked=True)
        df = _make_member("d", rarity="SR", element="敏捷", atk=80, defense=40, hp=200)
        atk_st = BattleStatusLayer(qi_po=5, frenzy=True)
        df_st = BattleStatusLayer(weak_point=3)
        turn = 8  # bloodlust lv2

        class _FixedJitter:
            def random(self) -> float:
                return 0.5  # jitter=1.0
        r = calc_raw_damage(atk, df, atk_st, df_st, turn, _FixedJitter())

        # 手算：
        # atk_bonus_total = (1.15-1.0) + 0.25 = 0.40
        # atk_base = 100 * (1+0.40) + 50*0.3 = 140 + 15 = 155
        # atk_layer_mult = 1.0 + 5*0.03 + 0.15 = 1.30
        # crit_mult = 1.0（不暴击）
        # element_mult = 1.30（力量 → 敏捷）
        # work_mult = 1.0
        # intimacy_mult = 1 + 100/500 = 1.20
        # lock_atk_mult = 0.85
        # damage_taken_mult = 0.90（SR 被 SSR）
        # weak_point_mult = 1.0 + 3*0.05 = 1.15
        # raw = 155 * 1.30 * 1.0 * 1.30 * 1.0 * 1.20 * 0.85 * 0.90 * 1.15
        #     = 155 * 1.30 = 201.5
        #     * 1.30 = 261.95
        #     * 1.20 = 314.34
        #     * 0.85 = 267.189
        #     * 0.90 = 240.4701
        #     * 1.15 = 276.54
        # jitter = 1.0 → dmg = int(276.54) = 276
        expected_raw = 155 * 1.30 * 1.0 * 1.30 * 1.0 * 1.20 * 0.85 * 0.90 * 1.15
        expected_dmg = int(expected_raw)
        assert r["dmg"] == expected_dmg, f"dmg={r['dmg']}, expected={expected_dmg}, raw={expected_raw}"


# ============== 辅助 ==============


def fresh_status_default() -> BattleStatusLayer:
    return BattleStatusLayer()