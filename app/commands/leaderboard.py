"""排行榜命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator, List, Optional, Tuple

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id
from ..models.enums import Action
from ..services.leaderboard_service import LeaderboardEntry, LeaderboardService
from .context import CommandContext

__all__ = ["handle_leaderboard"]

# 排行类型 → (rank 方法名, 标签)
_RANK_TYPES = {
    "日": ("daily", "日榜"),
    "周": ("weekly", "周榜"),
    "总": ("alltime", "总榜"),
}

# 维度 → (action, 标签)
_DIMENSIONS = {
    "牛": (Action.NTR_SUCCESS, "牛老婆"),
    "被牛": (Action.NTR_LOST, "被牛"),
    "PK": (Action.PK_WIN, "PK胜场"),
    "收集": ("collection", "收集数"),
}

# 默认显示的维度（全量播报时）
_ALL_DIMENSIONS = [
    ("牛", Action.NTR_SUCCESS, "牛老婆"),
    ("被牛", Action.NTR_LOST, "被牛"),
    ("收集", "collection", "收集数"),
]


async def handle_leaderboard(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 排行 [日|周|总] [牛|被牛|PK|收集]``

    无参数时默认周榜 + 全维度播报。
    """
    gid = get_group_id(event)
    if not gid:
        return

    msg = (event.message_str or "").strip()
    # 去掉 "老婆 排行" 前缀
    rest = msg
    for prefix in ("老婆排行", "老婆 排行"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    # 解析参数
    rank_type_key: Optional[str] = None
    dimension_key: Optional[str] = None

    parts = rest.split()
    for part in parts:
        part = part.strip()
        if part in _RANK_TYPES:
            rank_type_key = part
        elif part in _DIMENSIONS:
            dimension_key = part

    # 默认周榜
    if rank_type_key is None:
        rank_type_key = "周"

    leaderboard = LeaderboardService(ctx.paths, ctx.config, ctx.tz)
    top_n = ctx.config.leaderboard_top_n

    # 指定了维度：只显示该维度
    if dimension_key:
        dim_action, dim_label = _DIMENSIONS[dimension_key]
        section = _format_section(leaderboard, gid, rank_type_key, dim_action, dim_label, top_n)
        if section:
            yield event.plain_result(section)
        else:
            yield event.plain_result(f"暂无{dim_label}排行数据，快去试试吧~")
        return

    # 未指定维度：全维度播报
    rank_label = _RANK_TYPES[rank_type_key][1]
    sections: List[str] = [f"📊 【{rank_label}】\n"]

    for key, action, label in _ALL_DIMENSIONS:
        section = _format_section(leaderboard, gid, rank_type_key, action, label, top_n, compact=True)
        if section:
            sections.append(section)

    if len(sections) == 1:
        yield event.plain_result("暂无排行数据，快去试试吧~")
        return

    yield event.plain_result("\n".join(sections))


def _format_section(
    leaderboard: LeaderboardService,
    gid: str,
    rank_type_key: str,
    action: str,
    label: str,
    top_n: int,
    compact: bool = False,
) -> Optional[str]:
    """格式化单个维度的排行段落，无数据返回 None。"""
    if action == "collection":
        entries = leaderboard.rank_collection(gid)
    elif rank_type_key == "总":
        entries = leaderboard.rank_alltime(gid, action)
    else:
        days = 7 if rank_type_key == "周" else 1
        entries = leaderboard.rank_daily(gid, action, days)

    if not entries:
        return None

    if compact:
        # 紧凑模式：只显示前 3 名
        top3 = entries[:3]
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        items = "  ".join(
            f"{medals[i+1]}{e.nick}({e.value})" for i, e in enumerate(top3)
        )
        return f"• {label}：{items}"
    else:
        lines = [f"【{label}】Top {top_n}"]
        for i, entry in enumerate(entries, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            lines.append(f"{medal} {entry.nick}：{entry.value}")
        return "\n".join(lines)
