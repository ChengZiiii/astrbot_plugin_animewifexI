"""主老婆切换命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from .context import CommandContext
from .view import find_wid_by_index

__all__ = ["handle_switch_primary"]


async def handle_switch_primary(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 切换 <编号>``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    wid = find_wid_by_index(ctx, gid, uid, event.message_str)
    if not wid:
        yield event.plain_result("请输入正确的老婆编号，如：老婆 切换 2")
        return

    result = await ctx.ownership_service.switch_primary(gid, uid, wid)
    if not result.ok:
        if result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你还没有老婆，先去抽一个吧~")
        elif result.reason == "wife_not_found":
            yield event.plain_result(f"{nick}，你指定的老婆编号不存在哦~")
        else:
            yield event.plain_result(f"{nick}，切换主老婆失败了~")
        return

    if result.reason == "already_primary":
        yield event.plain_result(f"{nick}，这位已经是你的主老婆啦~")
        return

    yield event.plain_result(f"{nick}，已将 {result.wife_name} 设为主老婆~")
