"""牛老婆命令处理器。"""

from __future__ import annotations

import random
import re
from typing import AsyncGenerator, List, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from ..api.messaging import build_text_image_chain
from ..storage.stores import OwnershipStore, WivesMasterStore
from ..utils.image import build_wife_intro_text
from .context import CommandContext
from .view import find_uid_by_owner_nick

__all__ = ["handle_ntr", "cancel_related_swap_requests"]

_NTR_SUCCESS_FLAVOR = [
    "趁{name}不注意，你悄悄把她带走了……",
    "{name}还没反应过来，就已经换了主人~",
    "你对{name}使出了「拐跑大法」，大成功！",
    "{name}：等等……我怎么在这里？！你：别问，跟我走就对了。",
    "趁着月黑风高，你把{name}偷走了……",
    "{name}迷迷糊糊地跟你走了，前任完全没发现……",
    "你用美食诱惑了{name}，她心甘情愿地跟你走了~",
    "前任：我老婆呢？！你：什么老婆？没见过。",
]

_NTR_FAIL_FLAVOR = [
    "你偷偷摸摸地靠近，但被发现了！{name}：你想干嘛？！",
    "你刚伸出手，就被{name}的主人抓了个正着……",
    "{name}瞪了你一眼：你谁啊？不认识，走开。",
    "你的牛老婆行动失败了，还被嘲讽了一番……",
    "差一点就成功了！{name}的守护者突然出现！",
    "你：嗨~ {name}：滚。好吧，失败了。",
]


async def handle_ntr(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``牛老婆 [@用户 | 昵称] [编号]``：尝试抢夺他人的老婆

    不指定编号：随机牛一个
    指定编号：牛对方的第 N 个老婆
    """
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

    tid, target_wid = _resolve_target_and_wid(event, ctx, gid)

    if not tid or tid == uid:
        msg = (
            "请@你想牛的对象，或输入完整的昵称哦~"
            if not tid
            else "不能牛自己呀，换个人试试吧~"
        )
        yield event.plain_result(f"{nick}，{msg}")
        return

    result = await ctx.ownership_service.try_ntr(
        gid, uid, tid, nick, ctx.today(), target_wid=target_wid
    )

    # 前置拒绝（无效目标/被禁用/冷却）
    if not result.ok:
        if result.reason == "ntr_disabled":
            yield event.plain_result("牛老婆功能还没开启哦，请联系管理员开启~")
        elif result.reason == "cooldown":
            remaining = ctx.cooldown_service.remaining(
                gid, uid, "ntr", ctx.config.ntr_cooldown
            )
            yield event.plain_result(
                f"{nick}，牛老婆冷却中，还需等待{remaining}秒~"
            )
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

    if result.reason == "target_locked":
        yield event.plain_result("对方的老婆正在锁定中，这次牛不走哦~")
        return

    # 概率失败
    if not result.success:
        wives_meta = WivesMasterStore(ctx.paths).load_all()
        w = wives_meta.get(result.wid)
        target_name = (w.chara or w.img or "该老婆") if w else "该老婆"
        taunt = random.choice(_NTR_FAIL_FLAVOR).format(name=target_name)
        yield event.plain_result(
            f"{nick}，很遗憾，牛失败了！你今天还可以再试{result.remaining_attempts}次~\n\n📢 {taunt}"
        )
        return

    # 成功
    cancel_msg = cancel_related_swap_requests(ctx, gid, [uid, tid], ctx.today())
    wives_meta = WivesMasterStore(ctx.paths).load_all()
    w = wives_meta.get(result.wid)
    wife_name = (w.chara or w.img or "该老婆") if w else "该老婆"
    taunt = random.choice(_NTR_SUCCESS_FLAVOR).format(name=wife_name)
    yield event.plain_result(
        f"{nick}，牛老婆成功！老婆已归你所有，恭喜恭喜~\n\n📢 {taunt}"
    )
    if result.stolen_work_reward > 0:
        extra_lines = [f"💼 顺手截胡了对方打工收益：+{result.stolen_work_reward} 币"]
        if result.contract_voided:
            extra_lines.append("📜 对方的打工合约已作废")
        if result.partner_broken:
            extra_lines.append("🤝 对方的打工搭档关系已解除")
        if result.insurance_used:
            extra_lines.append(f"🛡️ 对方触发保险卡，额外获得 {result.insurance_bonus_coins} 币与 1 个复仇令牌")
        yield event.plain_result("\n".join(extra_lines))
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


def _resolve_target_and_wid(
    event: AstrMessageEvent, ctx: CommandContext, gid: str
) -> tuple[Optional[str], Optional[str]]:
    """解析目标用户 + 可选的老婆编号。

    格式：``牛老婆 @某人 2`` 或 ``牛老婆 昵称 3``
    返回 (target_uid, target_wid)。target_wid 为 None 时随机牛。
    """
    at_target = parse_at_target(event)
    msg = (event.message_str or "").strip()

    # 提取末尾数字（老婆编号）
    target_wid = None
    page_match = re.search(r"\s(\d+)\s*$", msg)
    if page_match:
        # 有数字，先尝试解析为目标用户的第 N 个老婆
        idx = int(page_match.group(1)) - 1  # 0-based

        # 先确定目标用户
        tid = at_target
        if not tid:
            parts = msg.split(maxsplit=1)
            if len(parts) > 1:
                rest = re.sub(r"\s+\d+\s*$", "", parts[1]).strip()
                if rest:
                    tid = find_uid_by_owner_nick(ctx, gid, rest)

        if tid and idx >= 0:
            ownership_store = OwnershipStore(ctx.paths, gid)
            ownerships = ownership_store.load_all()
            my_wives = ownership_store.list_by_user(tid, ownerships)
            if 0 <= idx < len(my_wives):
                target_wid = my_wives[idx].wid
        return tid, target_wid

    # 无数字：@ 或昵称匹配
    if at_target:
        return at_target, None

    parts = msg.split(maxsplit=1)
    if len(parts) > 1:
        target_nick = parts[1].strip()
        if target_nick:
            tid = find_uid_by_owner_nick(ctx, gid, target_nick)
            if tid:
                return tid, None

    return None, None


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
