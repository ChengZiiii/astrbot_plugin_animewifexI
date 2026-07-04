"""图鉴/面板命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..models.enums import Rarity, RARITY_ORDER
from ..services.economy_service import EconomyService
from ..storage.stores import OwnershipStore, ProfileStore, WivesMasterStore
from .context import CommandContext

__all__ = ["handle_collection", "handle_panel"]


async def handle_collection(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 图鉴``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    economy = EconomyService(ctx.paths, ctx.config, ctx.locks)
    weekly_box = economy.claim_weekly_surprise_box_sync(gid, uid, nick)
    if weekly_box is not None:
        box_coins, box_item = weekly_box
        lines = [f"📦 本周惊喜宝箱已领取：+{box_coins} 币"]
        if box_item:
            item_name = {"draw_ticket_single": "单抽券", "draw_ticket_ten": "十连券"}.get(box_item, box_item)
            lines.append(f"📦 宝箱额外获得：{item_name}")
        yield event.plain_result("\n".join(lines))

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = profiles.get(uid)
    if not profile or not profile.collection:
        yield event.plain_result(f"{nick}，你还没有收集到任何老婆，快去抽一个吧~")
        return

    # 加载所有老婆元数据
    wives = WivesMasterStore(ctx.paths).load_all()

    # 按稀有度统计
    rarity_counts = {r: 0 for r in RARITY_ORDER}
    total = len(profile.collection)
    for wid in profile.collection:
        wife = wives.get(wid)
        if wife:
            rarity_counts[wife.rarity] = rarity_counts.get(wife.rarity, 0) + 1

    # 全服总图鉴数
    total_wives = len(wives)

    lines = [
        f"【{nick} 的图鉴】收集 {total}/{total_wives}",
        "",
    ]
    for r in reversed(RARITY_ORDER):
        emoji = {"SSR": "✨", "SR": "🌟", "R": "⭐", "N": "·"}.get(r, "·")
        count = rarity_counts.get(r, 0)
        lines.append(f"  {emoji} {r}: {count}")

    yield event.plain_result("\n".join(lines))


async def handle_panel(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 面板``"""
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

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = profiles.get(uid)
    if not profile:
        yield event.plain_result(f"{nick}，你还没有老婆数据，先去抽一个吧~")
        return

    # 持有老婆列表
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)

    wives = WivesMasterStore(ctx.paths).load_all()

    lines = [f"【{nick} 的面板】", ""]

    # 基础信息
    lines.append(f"💰 老婆币：{profile.coins}")
    lines.append(f"📅 连续天数：{profile.streak_days}")
    lines.append("👑 主老婆：列表中带 👑 的那位，可用 `老婆 切换 <编号>` 修改")

    # T24: 作恶值展示
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    if profile.evil_points_month != current_month:
        profile.evil_points = 0
    if profile.evil_points > 0:
        lines.append(f"😈 作恶值：{profile.evil_points}")
    lines.append("")

    # 统计
    lines.append("【累计统计】")
    lines.append(f"  抽卡：{profile.total_draws} 次")
    lines.append(f"  牛人：{profile.total_ntr_success} 次")
    lines.append(f"  被牛：{profile.total_ntr_lost} 次")
    lines.append(f"  PK胜：{profile.total_pk_win} / 负：{profile.total_pk_lost}")
    lines.append("")

    # 持有老婆
    from ..services.ownership_service import MAX_WIVES_PER_USER
    if my_wives:
        primary_wife = next((o for o in my_wives if o.is_primary), None)
        if primary_wife:
            primary_meta = wives.get(primary_wife.wid)
            primary_name = primary_meta.chara or primary_meta.img if primary_meta else primary_wife.wid
            lines.append(f"🎯 当前默认老婆：{primary_name}")
            lines.append("")
        lines.append(f"【持有老婆】{len(my_wives)}/{MAX_WIVES_PER_USER}")
        for i, o in enumerate(my_wives, 1):
            wife = wives.get(o.wid)
            if wife:
                emoji = {"SSR": "✨", "SR": "🌟", "R": "⭐", "N": "·"}.get(wife.rarity, "·")
                name = wife.chara or wife.img
                lock = " 🔒" if o.is_locked else ""
                work = ""
                if o.is_working:
                    work = {
                        "normal": " 💼打工中",
                        "overtime": " 💼加班中",
                        "expedition": " 💼远征中",
                    }.get(o.work_mode, " 💼打工中")
                primary = " 👑" if o.is_primary else ""
                lines.append(f"  {i}. {emoji} {name} (❤️{o.intimacy}){lock}{work}{primary}")
    else:
        lines.append("【持有老婆】无")

    yield event.plain_result("\n".join(lines))
