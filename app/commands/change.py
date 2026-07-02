"""换老婆命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..api.messaging import build_text_image_chain
from ..utils.image import build_wife_intro_text
from .context import CommandContext
from .ntr import cancel_related_swap_requests

__all__ = ["handle_change"]


async def handle_change(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``换老婆``：丢弃当前主老婆，抽一张新的"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.change_primary(gid, uid, nick, ctx.today())

    if not result.ok:
        if result.reason == "limit_reached":
            yield event.plain_result(
                f"{nick}，你今天已经换了{ctx.config.change_max_per_day}次老婆啦，明天再来吧~"
            )
        elif result.reason == "no_wife":
            yield event.plain_result(
                f"{nick}，你今天还没有老婆，先去抽一个再来换吧~"
            )
        elif result.reason == "fetch_failed":
            yield event.plain_result(
                "抱歉，新老婆获取失败了，本次更换未生效，请稍后再试~"
            )
        return

    cancel_msg = cancel_related_swap_requests(ctx, gid, [uid], ctx.today())
    if cancel_msg:
        yield event.plain_result(cancel_msg)

    yield event.chain_result(
        build_text_image_chain(
            build_wife_intro_text(
                result.img,
                prefix=f"{nick}，你今天的老婆是",
                suffix="，请好好珍惜哦~",
            ),
            result.img,
            ctx.paths.img_dir,
            ctx.config.normalized_image_base_url,
        )
    )
