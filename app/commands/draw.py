"""抽老婆命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..api.messaging import build_text_image_chain
from ..utils.image import build_wife_intro_text
from .context import CommandContext

__all__ = ["handle_draw"]


async def handle_draw(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``抽老婆``：每日抽取/查看主老婆"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.draw_or_get_primary(
        gid, uid, nick, ctx.today()
    )
    if not result.ok or not result.img:
        if result.reason == "cooldown":
            remaining = ctx.cooldown_service.remaining(
                gid, uid, "draw", ctx.config.draw_cooldown
            )
            yield event.plain_result(
                f"{nick}，抽老婆冷却中，还需等待{remaining}秒~"
            )
        else:
            yield event.plain_result("抱歉，今天的老婆获取失败了，请稍后再试~")
        return

    if not result.is_new:
        # 今天已经抽过了，提示并展示当前老婆
        yield event.plain_result(f"{nick}，你今天已经抽过老婆了哦~")
        return

    intro = build_wife_intro_text(
        result.img,
        prefix=f"{nick}，你今天的老婆是",
        suffix="，请好好珍惜哦~",
    )
    yield event.chain_result(
        build_text_image_chain(
            intro,
            result.img,
            ctx.paths.img_dir,
            ctx.config.normalized_image_base_url,
        )
    )
