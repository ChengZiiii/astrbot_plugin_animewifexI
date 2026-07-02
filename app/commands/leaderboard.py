"""排行榜命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id
from ..models.enums import Action
from ..services.leaderboard_service import LeaderboardService
from .context import CommandContext

__all__ = ["handle_leaderboard"]

# 排行类型 → (rank 方法名, action 参数, 标签)
_RANK_TYPES = {
    "日": ("daily", None, "日榜"),
    "周": ("weekly", None, "周榜"),
    "总": ("alltime", None, "总榜"),
}

# 维度 → (action, 标签, 是否需要 rank_type)
_DIMENSIONS = {
    "牛": (Action.NTR_SUCCESS, "牛老婆次数", True),
    "被牛": (Action.NTR_LOST, "被牛次数", True),
    "PK": (Action.PK_WIN, "PK胜场", True),
    "收集": ("collection", "收集数", False),
}


async def handle_leaderboard(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 排行 [日|周|总] [牛|被牛|PK|收集]``"""
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

    # 解析参数：默认 日 牛
    rank_type_key = "日"
    dimension_key = "牛"

    parts = rest.split()
    for part in parts:
        part = part.strip()
        if part in _RANK_TYPES:
            rank_type_key = part
        elif part in _DIMENSIONS:
            dimension_key = part

    dimension_action, dimension_label, needs_rank_type = _DIMENSIONS[dimension_key]

    leaderboard = LeaderboardService(ctx.paths, ctx.config, ctx.tz)

    # 收集榜不区分日/周/总
    if dimension_action == "collection":
        entries = leaderboard.rank_collection(gid)
        title = f"【收集排行】Top {ctx.config.leaderboard_top_n}"
    else:
        if rank_type_key == "总":
            entries = leaderboard.rank_alltime(gid, dimension_action)
        else:
            days = 7 if rank_type_key == "周" else 1
            entries = leaderboard.rank_daily(gid, dimension_action, days)
        title = f"【{dimension_label}{_RANK_TYPES[rank_type_key][2]}】Top {ctx.config.leaderboard_top_n}"

    if not entries:
        yield event.plain_result(f"暂无{dimension_label}排行数据，快去试试吧~")
        return

    lines = [title]
    for i, entry in enumerate(entries, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(f"{medal} {entry.nick}：{entry.value}")

    yield event.plain_result("\n".join(lines))
