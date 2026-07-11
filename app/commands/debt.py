"""``老婆 查负债`` 命令处理器。

Task G.1 / v3_经济_负债_分币.md [S7.1]：
- 老婆 查负债 — 查看自己的负债状态
- 老婆 查负债 @xxx — 查看他人的负债状态
"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid, parse_at_target
from ..services.economy_service import EconomyService
from ..storage.stores import ProfileStore
from .context import CommandContext

__all__ = ["handle_debt_query"]


async def handle_debt_query(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 查负债`` — 查看（自己或他人的）负债状态"""
    gid = get_group_id(event)
    if not gid:
        return

    requester_uid = get_sender_uid(event)
    _ = get_sender_nick(event) or "你"

    # 解析 @目标
    target_uid = parse_at_target(event)
    if target_uid is None:
        # 查自己
        target_uid = requester_uid

    # 加载目标和查询者的 profile（仅用于获取昵称）
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()

    # 目标昵称
    target_profile = profiles.get(target_uid)
    if target_profile:
        target_nick = target_profile.nick or "该用户"
    else:
        target_nick = "该用户"

    # 余额
    economy = EconomyService(ctx.paths, ctx.config, ctx.locks)
    balance = economy.balance(gid, target_uid)

    debt_floor = ctx.config.debt_floor  # 默认 -500
    distance_to_floor = balance - debt_floor  # 距触底 = 余额 - 下限

    lines = [
        f"[{target_nick}] 当前余额 {balance} 币",
        f"  触底保护：{debt_floor} 币",
        f"  距触底：{distance_to_floor} 币",
        f"  💸 利息累积：0%（无利息）",
        f"  📌 任何产出先还债",
    ]

    yield event.plain_result("\n".join(lines))
