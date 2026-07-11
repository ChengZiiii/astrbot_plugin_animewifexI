"""v3 接力战 · 双层被动 (稀有度 × 元素) + 元素派生。

对应 spec 章节：

* ``v3_接力战_主线.md §S3.5`` —— 4 稀有度 × 3 元素 = 12 种角色差异。
* ``v3_接力战_主线.md §S3.4`` —— 元素派生按 ``base_stats`` 最高项。

设计要点：

* ``RARITY_PASSIVES`` / ``ELEMENT_PASSIVES`` 为**单一来源**，spec 改值时只改这里。
* ``compute_combined_modifiers`` 按乘法叠加（speed_mult / crit_rate 类用乘法）。
* 数值未持久化到 ``WifeMeta.element``，仅战斗时按 ``base_stats`` 实时派生。
"""

from __future__ import annotations

from typing import Dict, Mapping

__all__ = [
    "RARITY_PASSIVES",
    "ELEMENT_PASSIVES",
    "compute_combined_modifiers",
    "derive_element",
]


# ============== 稀有度被动（沿用 v2 §S2） ==============


RARITY_PASSIVES: Dict[str, Dict[str, object]] = {
    "SSR": {
        "id": "crit_plus",
        "effect": "暴击率 +10%",
        "modifier": {"crit_rate": +0.10},
    },
    "SR": {
        "id": "damage_reduce",
        "effect": "受到的伤害 -10%（仅对 SSR/SR 攻击有效）",
        "modifier": {"damage_taken_mult": 0.90},
    },
    "R": {
        "id": "speed_plus",
        "effect": "速度 +10%",
        "modifier": {"speed_mult": 1.10},
    },
    "N": {
        "id": "combo",
        "effect": "击杀后 25% 概率追加 1 次普通攻击（连击）",
        "modifier": {"combo_on_kill": 0.25},
    },
}


# ============== 元素被动（v3 新增） ==============


ELEMENT_PASSIVES: Dict[str, Dict[str, object]] = {
    "力量": {
        "id": "atk_pressure",
        "effect": "攻击力 ×1.15（持久战中累积气魄时更猛）",
        "modifier": {"atk_mult": 1.15},
    },
    "敏捷": {
        "id": "evasion_instinct",
        "effect": "速度 ×1.10 + 闪避率基础 +5%（敏捷优先出手 + 灵活闪避）",
        "modifier": {"speed_mult": 1.10, "dodge_rate": +0.05},
    },
    "智力": {
        "id": "crit_intuition",
        "effect": "暴击率 +5% + 受到暴击伤害 -15%（精准与抗暴）",
        "modifier": {"crit_rate": +0.05, "taken_crit_mult": 0.85},
    },
}


# ============== 双层叠加 ==============


# 同 key 在双层叠加时的合并策略
# speed_mult → 乘法叠加：1.10 * 1.10 = 1.21
# crit_rate → 加法叠加：基础 0.10 + SSR +0.10 + 智力 +0.05
_ADDITIVE_KEYS = {"crit_rate", "dodge_rate"}
_MULTIPLICATIVE_KEYS = {"speed_mult", "atk_mult", "damage_taken_mult", "taken_crit_mult", "combo_on_kill"}


def compute_combined_modifiers(rarity: str, element: str) -> Dict[str, float]:
    """合并两层被动，返回 dict[str, float]。

    * ``crit_rate`` / ``dodge_rate`` —— 加法叠加（两个被动都给同一加法量）
    * ``speed_mult`` / 其他 mult —— 乘法叠加
    * 同层只有一个被动提供某 key → 直接采用
    """
    result: Dict[str, float] = {}

    rarity_passive = RARITY_PASSIVES.get(rarity)
    if rarity_passive:
        for k, v in dict(rarity_passive["modifier"]).items():  # type: ignore[arg-type]
            _apply_modifier(result, k, float(v))

    element_passive = ELEMENT_PASSIVES.get(element)
    if element_passive:
        for k, v in dict(element_passive["modifier"]).items():  # type: ignore[arg-type]
            _apply_modifier(result, k, float(v))

    return result


def _apply_modifier(mods: Dict[str, float], key: str, value: float) -> None:
    """把单条 modifier 应用到 mods dict 里，按 key 类型做加法/乘法合并。"""
    if key in mods:
        existing = mods[key]
        if key in _ADDITIVE_KEYS:
            mods[key] = existing + value
        elif key in _MULTIPLICATIVE_KEYS:
            mods[key] = existing * value
        else:
            # 未知 key：后写覆盖（保守策略）
            mods[key] = value
    else:
        mods[key] = value


# ============== 元素派生 ==============


def derive_element(base_stats: Mapping[str, object]) -> str:
    """按 base_stats 最高项派生元素。

    锁定规则（spec §S3.4）：

    * atk 最高 → 力量
    * hp 最高 → 敏捷
    * def 最高 → 智力
    * 并列按 atk > hp > def 优先级（atk 不等则力量，hp 不等则敏捷）

    输入兼容 ``BaseStats`` 对象（通过 ``.atk`` / ``.defense`` / ``.hp``）或
    ``Mapping``（如 ``{"atk": 80, "def": 60, "hp": 50}``）。
    """
    a, d, h = _extract_stats(base_stats)

    if a >= d and a >= h:
        return "力量"
    if h >= d:
        return "敏捷"
    return "智力"


def _extract_stats(base_stats: Mapping[str, object]) -> tuple:
    """从 BaseStats dataclass 或 dict 中提取 (atk, def, hp) 三个 int。

    兼容两种输入：

    * dataclass 对象：``.atk`` / ``.defense`` / ``.hp``
    * dict：``["atk"]`` / ``["def"]`` / ``["hp"]``
    """
    # dataclass 风格
    if hasattr(base_stats, "atk") and hasattr(base_stats, "defense") and hasattr(base_stats, "hp"):
        return (
            int(getattr(base_stats, "atk", 0) or 0),
            int(getattr(base_stats, "defense", 0) or 0),
            int(getattr(base_stats, "hp", 0) or 0),
        )
    # dict 风格
    return (
        int(base_stats.get("atk", 0) or 0),  # type: ignore[union-attr]
        int(base_stats.get("def", 0) or 0),  # type: ignore[union-attr]
        int(base_stats.get("hp", 0) or 0),  # type: ignore[union-attr]
    )