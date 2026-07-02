"""随机工具：可注入种子的加权随机，便于测试。"""

from __future__ import annotations

import random
from typing import Mapping, TypeVar

__all__ = ["weighted_choice", "roll_chance"]

T = TypeVar("T")


def weighted_choice(weights: "Mapping[T, float]", rng: "random.Random | None" = None) -> T:
    """按权重字典做加权随机选择

    ``weights`` 形如 ``{"SSR": 5, "SR": 20, ...}``，权重之和无需归一化。
    空字典时抛 ``ValueError``；负权重按 0 处理。
    """
    items = [(k, max(0.0, float(w))) for k, w in weights.items()]
    total = sum(w for _, w in items)
    if total <= 0:
        raise ValueError("weighted_choice 权重总和必须为正")
    r = (rng or random).random() * total
    acc = 0.0
    for key, w in items:
        acc += w
        if r < acc:
            return key
    return items[-1][0]


def roll_chance(probability: float, rng: "random.Random | None" = None) -> bool:
    """以给定概率返回 ``True``；``probability`` 自动 clamp 到 ``[0, 1]``"""
    p = max(0.0, min(1.0, float(probability)))
    return (rng or random).random() < p
