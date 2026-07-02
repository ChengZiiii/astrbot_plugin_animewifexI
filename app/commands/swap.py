"""交换老婆命令处理器（发起/同意/拒绝/查看）。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import At, Plain

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from .context import CommandContext

__all__ = [
    "handle_swap_request",
    "handle_swap_accept",
    "handle_swap_reject",
    "handle_swap_view",
]


async def handle_swap_request(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``交换老婆 [@用户]``：发起交换请求"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    tid = parse_at_target(event)

    if not tid or tid == uid:
        yield event.plain_result(f"{nick}，请在命令后@你想交换的对象哦~")
        return

    result = await ctx.ownership_service.create_swap_request(
        gid, uid, tid, ctx.today()
    )

    if not result.ok:
        if result.reason == "limit_reached":
            yield event.plain_result(
                f"{nick}，你今天已经发起了{ctx.config.swap_max_per_day}次交换请求啦，明天再来吧~"
            )
        elif result.reason == "self_no_wife":
            yield event.plain_result(f"{nick}，今天还没有老婆，无法进行交换哦~")
        elif result.reason == "target_no_wife":
            yield event.plain_result("对方今天还没有老婆，无法进行交换哦~")
        else:
            yield event.plain_result(f"{nick}，发起交换失败，请稍后再试~")
        return

    if result.refunded_old:
        yield event.plain_result(
            "已自动取消你之前发起的交换请求并返还次数~"
        )

    yield event.chain_result(
        [
            Plain(f"{nick} 想和 "),
            At(qq=tid),
            Plain(
                ' 交换老婆啦！请对方用"同意交换 @发起者"或"拒绝交换 @发起者"来回应~'
            ),
        ]
    )


async def handle_swap_accept(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``同意交换 [@发起者]``"""
    gid = get_group_id(event)
    if not gid:
        return
    accepter_uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    initiator_uid = parse_at_target(event)

    if not initiator_uid:
        yield event.plain_result(
            f'{nick}，请在命令后@发起者，或用"查看交换请求"命令查看当前请求哦~'
        )
        return

    result = await ctx.ownership_service.accept_swap(
        gid, initiator_uid, accepter_uid, ctx.today()
    )

    if not result.ok:
        if result.reason == "expired":
            yield event.plain_result("该交换请求已过期，请重新发起交换吧~")
        elif result.reason == "mismatch":
            yield event.plain_result(
                f'{nick}，请在命令后@发起者，或用"查看交换请求"命令查看当前请求哦~'
            )
        elif result.reason == "wife_changed":
            yield event.plain_result(
                "交换失败，有一方的老婆已经发生变化，请重新发起交换吧~"
            )
        else:
            yield event.plain_result(f"{nick}，同意交换失败，请稍后再试~")
        return

    yield event.plain_result("交换成功！你们的老婆已经互换啦，祝幸福~")


async def handle_swap_reject(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``拒绝交换 [@发起者]``"""
    gid = get_group_id(event)
    if not gid:
        return
    accepter_uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    initiator_uid = parse_at_target(event)

    if not initiator_uid:
        yield event.plain_result(
            f'{nick}，请在命令后@发起者，或用"查看交换请求"命令查看当前请求哦~'
        )
        return

    result = await ctx.ownership_service.reject_swap(
        gid, initiator_uid, accepter_uid, ctx.today()
    )

    if not result.ok:
        if result.reason == "expired":
            yield event.plain_result("该交换请求已过期，无需拒绝啦~")
        elif result.reason == "mismatch":
            yield event.plain_result(
                f'{nick}，请在命令后@发起者，或用"查看交换请求"命令查看当前请求哦~'
            )
        else:
            yield event.plain_result(f"{nick}，拒绝交换失败，请稍后再试~")
        return

    yield event.chain_result(
        [At(qq=initiator_uid), Plain("，对方婉拒了你的交换请求，下次加油吧~")]
    )


async def handle_swap_view(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``查看交换请求``"""
    gid = get_group_id(event)
    if not gid:
        return
    me = get_sender_uid(event)

    requests = ctx.ownership_service.list_swap_requests(gid, ctx.today())

    sent_targets = [requests[me]] if me in requests else []
    received_from = [uid for uid, target in requests.items() if target == me]

    if not sent_targets and not received_from:
        yield event.plain_result("你当前没有任何交换请求哦~")
        return

    parts = []
    for tid in sent_targets:
        target_profile = ctx.ownership_service.get_profile(gid, tid)
        name = target_profile.nick or "未知用户"
        parts.append(f"→ 你发起给 {name} 的交换请求")

    for uid in received_from:
        initiator_profile = ctx.ownership_service.get_profile(gid, uid)
        name = initiator_profile.nick or "未知用户"
        parts.append(f"→ {name} 发起给你的交换请求")

    text = (
        "当前交换请求如下：\n"
        + "\n".join(parts)
        + '\n请在"同意交换"或"拒绝交换"命令后@发起者进行操作~'
    )
    yield event.plain_result(text)
