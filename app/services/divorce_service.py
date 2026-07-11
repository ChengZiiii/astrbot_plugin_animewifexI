"""离婚系统核心服务。

Phase D / v3 离婚系统：
- 返还公式：稀有度基础 × (1 + 好感度/100)
- 分家产概率：min(0.50, 0.10 + intimacy/200)
- 分家产金额：双向 20% 比例，绝对值封顶 ±200
- 冷却校验：全用户级 7 天
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple

from ..models.ownership import Ownership
from ..models.profile import UserProfile

__all__ = [
    "calc_divorce_return",
    "calc_divorce_property_split_prob",
    "calc_divorce_property_split_amount",
    "apply_divorce_split",
    "validate_divorce_possible",
    "DIVORCE_COOLDOWN_DAYS",
    "RETURN_BASE",
]

DIVORCE_COOLDOWN_DAYS = 7

RETURN_BASE = {
    "N": 10,
    "R": 25,
    "SR": 60,
    "SSR": 120,
}


def calc_divorce_return(rarity: str, intimacy: int) -> int:
    """计算离婚返还币。

    Args:
        rarity: 稀有度（N/R/SR/SSR）
        intimacy: 当前亲密度

    Returns:
        返还的老婆币数量（int）

    Raises:
        KeyError: 未知稀有度
    """
    base = RETURN_BASE[rarity]
    mult = 1 + intimacy / 100.0
    return int(base * mult)


def calc_divorce_property_split_prob(intimacy: int) -> float:
    """计算分家产概率。

    Args:
        intimacy: 当前亲密度

    Returns:
        概率值（0.0 ~ 0.50）
    """
    p = 0.10 + intimacy / 200.0
    return min(0.50, p)


def calc_divorce_property_split_amount(current_coins: int) -> int:
    """计算分家产金额（Q4 双向百分比 ±200 封顶）。

    Args:
        current_coins: 当前余额

    Returns:
        被分走的金币数；正数 = 玩家损失，负数 = 玩家负债减压
    """
    split = int(current_coins * 0.20)
    if split > 200:
        return 200
    if split < -200:
        return -200
    return split


def apply_divorce_split(current_coins: int) -> Tuple[int, int]:
    """应用分家产，返回 (new_coins, split_amount)。"""
    split_amount = calc_divorce_property_split_amount(current_coins)
    return (current_coins - split_amount, split_amount)


def validate_divorce_possible(
    profile: UserProfile,
    ownership: Ownership,
    today: str,
) -> Tuple[bool, str]:
    """校验离婚的前置条件。

    Returns:
        (ok, msg) — ok=True 表示允许，msg 为空；ok=False 时 msg 为拒绝原因。
    """
    # 1. 检查冷却
    last_divorce_date = profile.last_divorce_date
    if last_divorce_date:
        try:
            last = datetime.strptime(last_divorce_date, "%Y-%m-%d").date()
            today_date = datetime.strptime(today, "%Y-%m-%d").date()
            if (today_date - last).days < DIVORCE_COOLDOWN_DAYS:
                remaining = DIVORCE_COOLDOWN_DAYS - (today_date - last).days
                return False, f"你刚离过婚，{remaining} 天后再来吧"
        except ValueError:
            pass  # 日期格式异常，视为允许

    # 2. 检查战斗中
    if ownership.is_in_battle:
        return False, "她正在战斗中，结束后再说"

    # 3. 检查打工中
    if ownership.is_working:
        return False, "她正在打工中，等结算后再说"

    return True, ""
