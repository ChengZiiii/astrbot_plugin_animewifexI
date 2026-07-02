"""格式化工具：纯函数文本格式化辅助。"""

from __future__ import annotations

from typing import Iterable, Mapping

__all__ = ["format_intimacy_level", "format_rarity_badge", "truncate_text"]


_INTIMACY_LEVELS = [
    (90, "❤️❤️❤️❤️❤️"),
    (75, "❤️❤️❤️❤️"),
    (60, "❤️❤️❤️"),
    (40, "❤️❤️"),
    (20, "❤️"),
    (0, "💔"),
]


def format_intimacy_level(intimacy: int) -> str:
    """亲密度数值映射为心心等级文本（Lv.1~5）"""
    for threshold, hearts in _INTIMACY_LEVELS:
        if intimacy >= threshold:
            return hearts
    return "💔"


_RARITY_BADGES = {
    "SSR": "✨ SSR",
    "SR": "🌟 SR",
    "R": "⭐ R",
    "N": "· N",
}


def format_rarity_badge(rarity: str) -> str:
    """稀有度代码映射为展示徽章文本，未知值原样返回"""
    return _RARITY_BADGES.get(str(rarity).upper(), str(rarity))


def truncate_text(text: str, max_len: int = 200) -> str:
    """超长文本截断并补省略号；不超过长度时原样返回"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
