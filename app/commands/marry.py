"""求婚/锁定命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..services.marry_service import MarryService
from .context import CommandContext
from .view import find_wid_by_index

__all__ = ["handle_propose", "handle_lock", "handle_unlock"]


async def handle_propose(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 求婚 <编号>``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    wid = find_wid_by_index(ctx, gid, uid, event.message_str)
    if not wid:
        yield event.plain_result("请输入正确的老婆编号，如：老婆 求婚 1")
        return

    marry = MarryService(ctx.paths, ctx.config)
    result = marry.propose(gid, uid, wid, nick)
    yield event.plain_result(result.msg)


async def handle_lock(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 锁 <编号>``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    wid = find_wid_by_index(ctx, gid, uid, event.message_str)
    if not wid:
        yield event.plain_result("请输入正确的老婆编号，如：老婆 锁 1")
        return

    marry = MarryService(ctx.paths, ctx.config)
    result = marry.lock(gid, uid, wid, nick)
    yield event.plain_result(result.msg)


async def handle_unlock(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 解锁 <编号>``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)

    wid = find_wid_by_index(ctx, gid, uid, event.message_str)
    if not wid:
        yield event.plain_result("请输入正确的老婆编号，如：老婆 解锁 1")
        return

    marry = MarryService(ctx.paths, ctx.config)
    result = marry.unlock(gid, uid, wid)
    yield event.plain_result(result.msg)
