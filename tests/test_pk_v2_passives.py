"""v3 接力战 · 双层被动 (稀有度 × 元素) + 元素派生测试。

覆盖 v3_接力战_主线.md §S3.5（双层被动 4×3=12 组合）与 §S3.4（元素派生）。
"""

from __future__ import annotations

import pytest


# ============== 双层被动叠加 · 12 组合 ==============


class TestDualPassiveAllCombos:
    """4 稀有度 × 3 元素 = 12 组合，全部都要 verify。"""

    @pytest.mark.parametrize("rarity,element", [
        ("N", "力量"), ("N", "敏捷"), ("N", "智力"),
        ("R", "力量"), ("R", "敏捷"), ("R", "智力"),
        ("SR", "力量"), ("SR", "敏捷"), ("SR", "智力"),
        ("SSR", "力量"), ("SSR", "敏捷"), ("SSR", "智力"),
    ])
    def test_all_12_combos_return_dict(self, rarity, element):
        """每个组合都能调用 compute_combined_modifiers 并返回 dict。"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers(rarity, element)
        assert isinstance(mods, dict)
        assert len(mods) > 0

    # ---- SSR + 力量 = crit_plus + atk_pressure ----

    def test_ssr_power_crit_plus_atk_pressure(self):
        """SSR + 力量 → crit_rate=+0.10 (SSR 被动) + atk_mult=1.15（极端爆发）

        注：基础 0.10 暴击率由伤害公式负责（spec §S6.2），不在被动 dict 里。
        最终暴击率 = 0.10 base + 0.10 SSR = 20%。
        """
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("SSR", "力量")
        assert mods["crit_rate"] == pytest.approx(0.10)
        assert mods["atk_mult"] == pytest.approx(1.15)
        # 智力被动不在该组合里
        assert "taken_crit_mult" not in mods

    # ---- N + 敏捷 = combo + evasion_instinct ----

    def test_n_agility_combo_speed_dodge(self):
        """N + 敏捷 → combo_on_kill=0.25 + speed_mult=1.10 + dodge_rate=0.05"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("N", "敏捷")
        assert mods["combo_on_kill"] == pytest.approx(0.25)
        assert mods["speed_mult"] == pytest.approx(1.10)
        assert mods["dodge_rate"] == pytest.approx(0.05)

    # ---- SR + 智力 = damage_reduce + crit_intuition ----

    def test_sr_intellect_reduce_crit(self):
        """SR + 智力 → damage_taken_mult=0.90 + crit_rate=+0.05 (智力) + taken_crit_mult=0.85

        注：最终暴击率 = 0.10 base + 0.05 智力 = 15%。
        """
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("SR", "智力")
        assert mods["damage_taken_mult"] == pytest.approx(0.90)
        assert mods["crit_rate"] == pytest.approx(0.05)
        assert mods["taken_crit_mult"] == pytest.approx(0.85)

    # ---- R + 力量 = speed_plus + atk_pressure ----

    def test_r_power_speed_atk(self):
        """R + 力量 → speed_mult=1.10 + atk_mult=1.15（平衡强攻）"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("R", "力量")
        assert mods["speed_mult"] == pytest.approx(1.10)
        assert mods["atk_mult"] == pytest.approx(1.15)

    # ---- SSR + 敏捷 = crit_plus + evasion_instinct ----

    def test_ssr_agility_crit_speed_dodge(self):
        """SSR + 敏捷 → crit_rate=+0.10 (SSR) + speed_mult=1.10 + dodge_rate=0.05（速攻暴击）

        注：最终暴击率 = 0.10 base + 0.10 SSR = 20%。
        """
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("SSR", "敏捷")
        assert mods["crit_rate"] == pytest.approx(0.10)
        assert mods["speed_mult"] == pytest.approx(1.10)
        assert mods["dodge_rate"] == pytest.approx(0.05)

    # ---- N + 力量 = combo + atk_pressure ----

    def test_n_power_combo_atk(self):
        """N + 力量 → combo_on_kill=0.25 + atk_mult=1.15（残血反扑）"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("N", "力量")
        assert mods["combo_on_kill"] == pytest.approx(0.25)
        assert mods["atk_mult"] == pytest.approx(1.15)

    # ---- R + 智力 ----

    def test_r_intellect_speed_crit(self):
        """R + 智力 → speed_mult=1.10 + crit_rate=+0.05 (智力) + taken_crit_mult=0.85

        注：最终暴击率 = 0.10 base + 0.05 智力 = 15%。
        """
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("R", "智力")
        assert mods["speed_mult"] == pytest.approx(1.10)
        assert mods["crit_rate"] == pytest.approx(0.05)
        assert mods["taken_crit_mult"] == pytest.approx(0.85)

    # ---- SR + 力量 ----

    def test_sr_power_reduce_atk(self):
        """SR + 力量 → damage_taken_mult=0.90 + atk_mult=1.15"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("SR", "力量")
        assert mods["damage_taken_mult"] == pytest.approx(0.90)
        assert mods["atk_mult"] == pytest.approx(1.15)

    # ---- SR + 敏捷 ----

    def test_sr_agility_reduce_speed_dodge(self):
        """SR + 敏捷 → damage_taken_mult=0.90 + speed_mult=1.10 + dodge_rate=0.05"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("SR", "敏捷")
        assert mods["damage_taken_mult"] == pytest.approx(0.90)
        assert mods["speed_mult"] == pytest.approx(1.10)
        assert mods["dodge_rate"] == pytest.approx(0.05)

    # ---- N + 智力 ----

    def test_n_intellect_combo_crit(self):
        """N + 智力 → combo_on_kill=0.25 + crit_rate=+0.05 (智力) + taken_crit_mult=0.85

        注：最终暴击率 = 0.10 base + 0.05 智力 = 15%。
        """
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("N", "智力")
        assert mods["combo_on_kill"] == pytest.approx(0.25)
        assert mods["crit_rate"] == pytest.approx(0.05)
        assert mods["taken_crit_mult"] == pytest.approx(0.85)

    # ---- R + 敏捷 ----

    def test_r_agility_speed_dodge(self):
        """R + 敏捷 → speed_mult=1.10 + dodge_rate=0.05（敏捷层 +1.10 二次叠加 = 1.21）"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("R", "敏捷")
        # R 给 speed_mult=1.10, 敏捷也再给 1.10 → 乘法叠加 1.21
        assert mods["speed_mult"] == pytest.approx(1.21)
        assert mods["dodge_rate"] == pytest.approx(0.05)

    # ---- SSR + 智力 ----

    def test_ssr_intellect_crit_taken(self):
        """SSR + 智力 → crit_rate=+0.15 (SSR+智力) + taken_crit_mult=0.85

        注：最终暴击率 = 0.10 base + 0.10 SSR + 0.05 智力 = 25%。
        """
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("SSR", "智力")
        assert mods["crit_rate"] == pytest.approx(0.15)
        assert mods["taken_crit_mult"] == pytest.approx(0.85)


# ============== 单一被动表 ==============


class TestRarityPassives:
    def test_rarity_table_keys(self):
        from app.services.pk_v2_passives import RARITY_PASSIVES

        assert set(RARITY_PASSIVES.keys()) == {"N", "R", "SR", "SSR"}

    def test_rarity_passive_ids(self):
        from app.services.pk_v2_passives import RARITY_PASSIVES

        assert RARITY_PASSIVES["SSR"]["id"] == "crit_plus"
        assert RARITY_PASSIVES["SR"]["id"] == "damage_reduce"
        assert RARITY_PASSIVES["R"]["id"] == "speed_plus"
        assert RARITY_PASSIVES["N"]["id"] == "combo"


class TestElementPassives:
    def test_element_table_keys(self):
        from app.services.pk_v2_passives import ELEMENT_PASSIVES

        assert set(ELEMENT_PASSIVES.keys()) == {"力量", "敏捷", "智力"}

    def test_element_passive_ids(self):
        from app.services.pk_v2_passives import ELEMENT_PASSIVES

        assert ELEMENT_PASSIVES["力量"]["id"] == "atk_pressure"
        assert ELEMENT_PASSIVES["敏捷"]["id"] == "evasion_instinct"
        assert ELEMENT_PASSIVES["智力"]["id"] == "crit_intuition"


# ============== 设计契约：被动只返回 delta，不含 base ==============


class TestModifierDesignContract:
    """契约：compute_combined_modifiers 返回的是**被动增量**，不包含战斗公式里的基础值。

    战斗公式（§S6.2）：

    * crit_rate 基础 0.10 → SSR 被动 +0.10 → 智力被动 +0.05 → 最终
    * speed_mult 是乘法叠加（R 1.10 × 敏捷 1.10 = 1.21）

    这些规则由 damage formula 负责，本模块只暴露 modifier dict。
    """

    def test_crit_rate_does_not_include_base(self):
        """modifier.crit_rate 只反映被动增量，不含 base 0.10。"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        # SSR 提供 +0.10，智力提供 +0.05
        # 期望：mods["crit_rate"] = 0.15（仅被动增量）
        mods = compute_combined_modifiers("SSR", "智力")
        assert mods["crit_rate"] == pytest.approx(0.15)

    def test_speed_mult_is_multiplicative(self):
        """speed_mult 在双层叠加时乘法（R 1.10 × 敏捷 1.10 = 1.21）。"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("R", "敏捷")
        assert mods["speed_mult"] == pytest.approx(1.21)

    def test_crit_rate_additive_for_double_intellect_only(self):
        """单独智力被动：crit_rate = +0.05。"""
        from app.services.pk_v2_passives import compute_combined_modifiers

        mods = compute_combined_modifiers("N", "智力")
        assert mods["crit_rate"] == pytest.approx(0.05)


# ============== 元素派生（按 base_stats 最高项） ==============


class TestDeriveElement:
    """按 §S3.4：base_stats 最高项派生，并列按 atk > hp > def 优先级。"""

    def test_atk_highest_yields_power(self):
        """atk 最高 → 力量（克制敏捷）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 80, "def": 60, "hp": 50}) == "力量"

    def test_hp_highest_yields_agility(self):
        """hp 最高 → 敏捷（被力量克制）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 50, "def": 60, "hp": 100}) == "敏捷"

    def test_def_highest_yields_intellect(self):
        """def 最高 → 智力（克制力量）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 50, "def": 80, "hp": 60}) == "智力"

    def test_tie_atk_hp_atk_wins(self):
        """atk == hp → atk 优先（力量）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 80, "def": 60, "hp": 80}) == "力量"

    def test_tie_atk_def_atk_wins(self):
        """atk == def → atk 优先（力量）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 80, "def": 80, "hp": 50}) == "力量"

    def test_tie_hp_def_hp_wins(self):
        """hp == def → hp 优先（敏捷）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 30, "def": 80, "hp": 80}) == "敏捷"

    def test_three_way_tie_atk_wins(self):
        """三项全等 → atk 优先（力量）"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 50, "def": 50, "hp": 50}) == "力量"

    def test_zero_stats_defaults_to_power(self):
        """全 0 → atk 优先 → 力量"""
        from app.services.pk_v2_passives import derive_element

        assert derive_element({"atk": 0, "def": 0, "hp": 0}) == "力量"