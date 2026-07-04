"""亲密度命令处理器（摸头 / 送礼）。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..services.ownership_service import OwnershipService
from .context import CommandContext

__all__ = ["handle_pet", "handle_gift", "handle_chat", "handle_date"]


async def handle_pet(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 摸头``：消耗币增加亲密度"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.pet_wife(gid, uid, nick, ctx.today())

    if not result.ok:
        if result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你今天还没有老婆，先去抽一个吧~")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"{nick}，你的老婆币不足（需要{ctx.config.intimacy_pet_coin_cost}币，"
                f"当前{result.coin_balance}币），去签到攒攒吧~"
            )
        elif result.reason == "intimacy_maxed":
            yield event.plain_result(
                f"{nick}，你和老婆的亲密度已经满啦（{result.intimacy}/{ctx.config.intimacy_max}）~"
            )
        else:
            yield event.plain_result(f"{nick}，摸头失败了~")
        return

    emoji = OwnershipService.intimacy_level_emoji(result.intimacy)
    yield event.plain_result(
        f"{nick}，摸头成功！亲密度 +{ctx.config.intimacy_pet_gain} "
        f"（{result.intimacy}/{ctx.config.intimacy_max}）{emoji}\n"
        f"消耗 {ctx.config.intimacy_pet_coin_cost} 币，余额 {result.coin_balance} 币"
    )


async def handle_gift(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 送礼``：高消耗高加成亲密度"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.gift_wife(gid, uid, nick, ctx.today())

    if not result.ok:
        if result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你今天还没有老婆，先去抽一个吧~")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"{nick}，你的老婆币不足（需要{ctx.config.intimacy_gift_coin_cost}币，"
                f"当前{result.coin_balance}币），去签到攒攒吧~"
            )
        elif result.reason == "intimacy_maxed":
            yield event.plain_result(
                f"{nick}，你和老婆的亲密度已经满啦（{result.intimacy}/{ctx.config.intimacy_max}）~"
            )
        else:
            yield event.plain_result(f"{nick}，送礼失败了~")
        return

    emoji = OwnershipService.intimacy_level_emoji(result.intimacy)
    yield event.plain_result(
        f"{nick}，送礼成功！亲密度 +{ctx.config.intimacy_gift_gain} "
        f"（{result.intimacy}/{ctx.config.intimacy_max}）{emoji}\n"
        f"消耗 {ctx.config.intimacy_gift_coin_cost} 币，余额 {result.coin_balance} 币"
    )


async def handle_chat(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 对话``：2h 冷却，+1 亲密度，+5 币"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.chat_wife(gid, uid, nick, ctx.today())

    if not result.ok:
        if result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你今天还没有老婆，先去抽一个吧~")
        elif result.reason == "cooldown":
            yield event.plain_result(f"{nick}，对话还在冷却中，过会儿再来聊天吧~")
        elif result.reason == "intimacy_maxed":
            yield event.plain_result(
                f"{nick}，你和老婆的亲密度已经满啦（{result.intimacy}/{ctx.config.intimacy_max}）~"
            )
        else:
            yield event.plain_result(f"{nick}，对话失败了~")
        return

    emoji = OwnershipService.intimacy_level_emoji(result.intimacy)
    yield event.plain_result(
        f"{nick}，和老婆聊天很开心！亲密度 +{ctx.config.chat_intimacy_gain} "
        f"（{result.intimacy}/{ctx.config.intimacy_max}）{emoji}\n"
        f"获得 {ctx.config.chat_coin_reward} 币，余额 {result.coin_balance} 币"
    )


async def handle_date(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 约会``：12h 冷却，花 10 币，+8 亲密度"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.date_wife(gid, uid, nick, ctx.today())

    if not result.ok:
        if result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你今天还没有老婆，先去抽一个吧~")
        elif result.reason == "cooldown":
            yield event.plain_result(f"{nick}，约会还在冷却中，过会儿再来吧~")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"{nick}，你的老婆币不足（需要{ctx.config.date_coin_cost}币，"
                f"当前{result.coin_balance}币），去签到攒攒吧~"
            )
        elif result.reason == "intimacy_maxed":
            yield event.plain_result(
                f"{nick}，你和老婆的亲密度已经满啦（{result.intimacy}/{ctx.config.intimacy_max}）~"
            )
        else:
            yield event.plain_result(f"{nick}，约会失败了~")
        return

    emoji = OwnershipService.intimacy_level_emoji(result.intimacy)
    yield event.plain_result(
        f"{nick}，约会很成功！亲密度 +{ctx.config.date_intimacy_gain} "
        f"（{result.intimacy}/{ctx.config.intimacy_max}）{emoji}\n"
        f"消耗 {ctx.config.date_coin_cost} 币，余额 {result.coin_balance} 币"
    )
