"""复仇命令处理器。"""

from __future__ import annotations

import random
from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from ..api.messaging import build_text_image_chain
from ..storage.stores import WivesMasterStore
from ..utils.image import build_wife_intro_text
from .context import CommandContext
from .ntr import cancel_related_swap_requests
from .view import find_uid_by_owner_nick

__all__ = ["handle_revenge"]

_REVENGE_SUCCESS_FLAVOR = [
    "你以为跑得掉吗？！{name}回来了！",
    "{name}：我回来了！还是你最好~",
    "正义虽迟但到！{name}被抢回来了！",
    "{name}：终于回来了……那个人好可怕……",
    "你冲过去一把把{name}拽了回来！前任目瞪口呆……",
    "{name}：呜呜呜你终于来救我了！",
]


async def handle_revenge(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 复仇 [@用户]``：对最近牛走你老婆的人发起复仇"""
    gid = get_group_id(event)
    if not gid:
        return

    # T33: 打工懒结算
    from .work import try_settle_work
    settle_msg = await try_settle_work(event, ctx)
    if settle_msg:
        yield event.plain_result(settle_msg)

    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    tid = _resolve_target(event, ctx)

    if not tid or tid == uid:
        msg = (
            "请@你想复仇的对象哦~"
            if not tid
            else "不能对自己复仇啦~"
        )
        yield event.plain_result(f"{nick}，{msg}")
        return

    # 检查复仇条件（在 try_ntr 之前做前置校验）
    profile = ctx.ownership_service.get_profile(gid, uid)
    if not profile.last_ntr_by:
        yield event.plain_result(f"{nick}，你最近没有被牛过，不需要复仇哦~")
        return

    from ..utils.time import now_ts

    last_ntr = profile.last_ntr_by
    rev_uid = last_ntr.get("uid", "")
    rev_ts = float(last_ntr.get("ts", 0))
    window_secs = ctx.config.revenge_window_hours * 3600

    if rev_uid != tid:
        yield event.plain_result(
            f"{nick}，你要复仇的对象不对哦~ 最近是 <{rev_uid}> 牛走了你的老婆~"
        )
        return

    if (now_ts() - rev_ts) >= window_secs:
        yield event.plain_result(
            f"{nick}，复仇窗口已过期（{ctx.config.revenge_window_hours}小时内有效），下次要更快行动哦~"
        )
        return

    # 走 NTR 流程，标记 is_revenge=True
    result = await ctx.ownership_service.try_ntr(
        gid, uid, tid, nick, ctx.today(), is_revenge=True
    )

    if not result.ok:
        if result.reason == "ntr_disabled":
            yield event.plain_result("牛老婆功能还没开启哦，请联系管理员开启~")
        elif result.reason == "cooldown":
            remaining = ctx.cooldown_service.remaining(
                gid, uid, "ntr", ctx.config.ntr_cooldown
            )
            yield event.plain_result(
                f"{nick}，复仇冷却中，还需等待{remaining}秒~"
            )
        else:
            yield event.plain_result(f"{nick}，复仇失败了~")
        return

    if result.reason == "limit_reached":
        yield event.plain_result(
            f"{nick}，你今天已经牛了{ctx.config.ntr_max}次啦（含复仇），明天再来吧~"
        )
        return

    if result.reason == "target_no_wife":
        yield event.plain_result("对方今天已经没有老婆可复仇了哦~")
        return

    if not result.success:
        yield event.plain_result(
            f"{nick}，复仇失败了！概率不够运气来凑，你今天还可以再试{result.remaining_attempts}次~"
        )
        return

    # 复仇成功
    cancel_msg = cancel_related_swap_requests(ctx, gid, [uid, tid], ctx.today())
    wives_meta = WivesMasterStore(ctx.paths).load_all()
    w = wives_meta.get(result.wid)
    wife_name = (w.chara or w.img or "该老婆") if w else "该老婆"
    taunt = random.choice(_REVENGE_SUCCESS_FLAVOR).format(name=wife_name)
    yield event.plain_result(
        f"{nick}，复仇成功！你的老婆回来了，正义虽迟但到~\n\n📢 {taunt}"
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


def _resolve_target(event: AstrMessageEvent, ctx: CommandContext):
    """解析复仇目标：@优先 → 文本昵称匹配"""
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
