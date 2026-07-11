"""NTR 安慰币服务：攻击者零代价（Q-D），被牛方按稀有度+好感度收安慰（Q-E）。

对应 v3_经济_负债_分币.md [S5.2]。

核心设计：
- 安慰币 = 离婚返还基础 × (1 + 好感度/200)
- 跟离婚返还算式对齐，形成镜像
- 无手续费 → 无系统池 → 无双向结算
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .economy_service import apply_income

if TYPE_CHECKING:
    from ..models.profile import UserProfile

# 安慰币基础值（= 离婚返还基础 · Q-E）
COMFORT_BASE = {
    "N": 10,
    "R": 25,
    "SR": 60,
    "SSR": 120,
}

__all__ = [
    "COMFORT_BASE",
    "calc_ntr_comfort",
    "record_ntr_lost",
    "apply_ntr_comfort_inner",
]


def calc_ntr_comfort(target_rarity: str, target_intimacy: int) -> int:
    """NTR 安慰币 = 离婚返还基础 × (1 + 好感度 / 200)

    Args:
        target_rarity: 被牛老婆稀有度（N/R/SR/SSR）
        target_intimacy: 被牛时的亲密度

    Returns:
        安慰币数量（向下取整）

    Examples:
        >>> calc_ntr_comfort("N", 0)
        10
        >>> calc_ntr_comfort("SSR", 100)
        180
        >>> calc_ntr_comfort("R", 50)
        31
    """
    base = COMFORT_BASE.get(target_rarity, 10)
    mult = 1 + target_intimacy / 200.0
    return int(base * mult)


def record_ntr_lost(profile: "UserProfile", comfort: int) -> None:
    """更新被牛方统计字段。

    注意：``total_ntr_lost`` 已在 ``ownership_service.try_ntr()`` 中自增，
    本函数只更新 ``total_ntr_comfort_received``。
    """
    profile.total_ntr_comfort_received = (
        getattr(profile, "total_ntr_comfort_received", 0) + comfort
    )


def apply_ntr_comfort_inner(
    target_profile: "UserProfile",
    target_rarity: str,
    target_intimacy: int,
) -> int:
    """在锁内给被牛方发安慰币（不落盘，调用方负责 save profiles）。

    必须在 ``try_ntr`` 的锁上下文内调用，避免死锁。
    通过 ``apply_income`` 处理债务自动还债。

    Args:
        target_profile: 被牛方的 UserProfile（锁内引用，直接修改）
        target_rarity: 被牛老婆稀有度
        target_intimacy: 被牛时的亲密度

    Returns:
        安慰币数量（非新余额）
    """
    comfort = calc_ntr_comfort(target_rarity, target_intimacy)
    target_profile.coins = apply_income(target_profile.coins, comfort)
    record_ntr_lost(target_profile, comfort)
    return comfort
