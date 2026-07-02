"""经济相关命令：签到、商城、购买、任务。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick
from ..services.economy_service import EconomyService
from ..services.quest_service import QuestService
from ..services.shop_service import ITEM_NAMES, ShopService
from .context import CommandContext

__all__ = [
    "handle_checkin",
    "handle_quest",
    "handle_shop",
    "handle_buy",
    "handle_backpack",
]


async def handle_checkin(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 签到``"""
    gid = get_group_id(event)
    if not gid:
        return

    uid = str(event.get_sender_id())
    nick = get_sender_nick(event)

    economy = EconomyService(ctx.paths, ctx.config)
    reward = economy.daily_checkin(gid, uid, nick)

    if reward is None:
        yield event.plain_result("今天已经签到过了，明天再来吧~")
        return

    balance = economy.balance(gid, uid)
    yield event.plain_result(
        f"签到成功！获得 {reward} 老婆币\n"
        f"当前余额：{balance} 币"
    )


async def handle_quest(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 任务`` — 查看任务进度 / 领取任务奖励"""
    gid = get_group_id(event)
    if not gid:
        return

    uid = str(event.get_sender_id())
    nick = get_sender_nick(event)

    quest = QuestService(ctx.paths, ctx.config)

    # 先尝试领取
    reward = quest.check_and_complete(gid, uid, nick)
    if reward is not None:
        economy = EconomyService(ctx.paths, ctx.config)
        balance = economy.balance(gid, uid)
        yield event.plain_result(
            f"所有任务已完成！获得 {reward} 老婆币\n"
            f"当前余额：{balance} 币"
        )
        return

    # 展示任务进度
    status = quest.get_quest_status(gid, uid)
    lines = ["【每日任务】"]
    for label, done in status.items():
        icon = "✅" if done else "❌"
        lines.append(f"{icon} {label}")

    if quest.is_completed(gid, uid):
        lines.append("\n今日任务已完成，奖励已领取~")
    else:
        lines.append("\n完成所有任务可领取奖励！")

    yield event.plain_result("\n".join(lines))


async def handle_shop(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 商城``"""
    gid = get_group_id(event)
    if not gid:
        return

    shop = ShopService(ctx.paths, ctx.config)
    items = shop.list_items()

    uid = str(event.get_sender_id())
    economy = EconomyService(ctx.paths, ctx.config)
    balance = economy.balance(gid, uid)

    lines = [f"【商城】余额：{balance} 币\n"]
    for key, name, price in items:
        lines.append(f"• {name} — {price} 币  （老婆 购买 {name}）")

    lines.append("\n使用道具：老婆 使用 <道具名>")
    yield event.plain_result("\n".join(lines))


async def handle_buy(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 购买 <道具> [数量]``"""
    gid = get_group_id(event)
    if not gid:
        return

    uid = str(event.get_sender_id())
    nick = get_sender_nick(event)

    msg = (event.message_str or "").strip()
    # 去掉 "老婆 购买" 前缀
    rest = msg
    for prefix in ("老婆购买", "老婆 购买"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    if not rest:
        yield event.plain_result("格式：老婆 购买 <道具名> [数量]\n可用：老婆 商城 查看道具列表")
        return

    parts = rest.split()
    item_name = parts[0]
    quantity = 1
    if len(parts) > 1:
        try:
            quantity = int(parts[1])
        except ValueError:
            yield event.plain_result("数量必须是数字")
            return

    # 按中文名查找 key
    item_key = None
    for key, name in ITEM_NAMES.items():
        if name == item_name or key == item_name:
            item_key = key
            break

    if not item_key:
        yield event.plain_result(f"道具「{item_name}」不存在，可用：老婆 商城")
        return

    shop = ShopService(ctx.paths, ctx.config)
    ok, msg_text = shop.buy(gid, uid, item_key, quantity, nick)

    if ok:
        economy = EconomyService(ctx.paths, ctx.config)
        balance = economy.balance(gid, uid)
        yield event.plain_result(f"{msg_text}\n余额：{balance} 币")
    else:
        yield event.plain_result(msg_text)


async def handle_backpack(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 背包``"""
    gid = get_group_id(event)
    if not gid:
        return

    uid = str(event.get_sender_id())
    shop = ShopService(ctx.paths, ctx.config)
    inv = shop.get_inventory(gid, uid)

    if not inv:
        yield event.plain_result("背包空空如也，去商城逛逛吧~")
        return

    lines = ["【背包】"]
    for key, count in inv.items():
        name = ITEM_NAMES.get(key, key)
        lines.append(f"• {name} x{count}")

    yield event.plain_result("\n".join(lines))
