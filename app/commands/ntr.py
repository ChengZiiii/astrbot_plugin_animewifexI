"""牛老婆命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator, List, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from ..api.messaging import build_text_image_chain
from ..utils.image import build_wife_intro_text
from .context import CommandContext
from .view import find_uid_by_owner_nick

__all__ = ["handle_ntr", "cancel_related_swap_requests"]


async def handle_ntr(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``牛老婆 [@用户 | 昵称]``：尝试抢夺他人的主老婆"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    tid = _resolve_target(event, ctx)

    if not tid or tid == uid:
        msg = (
            "请@你想牛的对象，或输入完整的昵称哦~"
            if not tid
            else "不能牛自己呀，换个人试试吧~"
        )
        yield event.plain_result(f"{nick}，{msg}")
        return

    result = await ctx.ownership_service.try_ntr(
        gid, uid, tid, nick, ctx.today()
    )

    # 前置拒绝（无效目标/被禁用）
    if not result.ok:
        if result.reason == "ntr_disabled":
            yield event.plain_result("牛老婆功能还没开启哦，请联系管理员开启~")
        else:
            yield event.plain_result(f"{nick}，请@有效的牛老婆对象哦~")
        return

    # 限额用尽
    if result.reason == "limit_reached":
        yield event.plain_result(
            f"{nick}，你今天已经牛了{ctx.config.ntr_max}次啦，明天再来吧~"
        )
        return

    # 目标无老婆
    if result.reason == "target_no_wife":
        yield event.plain_result("对方今天还没有老婆可牛哦~")
        return

    # 概率失败
    if not result.success:
        yield event.plain_result(
            f"{nick}，很遗憾，牛失败了！你今天还可以再试{result.remaining_attempts}次~"
        )
        return

    # 成功
    cancel_msg = cancel_related_swap_requests(ctx, gid, [uid, tid], ctx.today())
    yield event.plain_result(
        f"{nick}，牛老婆成功！老婆已归你所有，恭喜恭喜~"
    )
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


def _resolve_target(event: AstrMessageEvent, ctx: CommandContext) -> Optional[str]:
    """与查老婆相同：@优先 → 文本昵称匹配"""
    at_target = parse_at_target(event)
    if at_target:
        return at_target

    msg = (event.message_str or "").strip()
    parts = msg.split(maxsplit=1)
    if len(parts) > 1:
        target_nick = parts[1].strip()
        gid = get_group_id(event)
        if gid and target_nick:
            tid = find_uid_by_owner_nick(ctx, gid, target_nick)
            if tid:
                return tid
    return None


def cancel_related_swap_requests(
    ctx: CommandContext, gid: str, user_ids: List[str], today: str
) -> Optional[str]:
    """老婆变动后取消相关的交换请求（与 v2.x 一致）

    返回提示文本；无变动返回 ``None``。

    .. note::

        严格并发安全：``ownership_service.try_ntr``/``change_primary`` 已在群锁内
        完成所有权转移，此调用紧随其后但未持群锁。理论上与并发 ``accept_swap``
        存在竞态窗口，但实际场景下用户不会在自己 NTR 成功的同一瞬间接受交换。
        Phase 1 接受此窗口；Phase 3 重构时可将此逻辑下沉到 try_ntr 内部。
    """
    canceled = ctx.ownership_service.cancel_swap_for_users(gid, user_ids, today)
    if canceled:
        return f"已自动取消 {canceled} 条相关的交换请求并返还次数~"
    return None
