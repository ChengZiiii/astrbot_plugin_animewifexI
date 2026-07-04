"""经济相关命令：签到、商城、购买、任务。"""

from __future__ import annotations

import random
from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick
from ..services.economy_service import EconomyService
from ..services.quest_service import QuestService
from ..services.shop_service import ITEM_NAMES, ShopService
from ..storage.stores import OwnershipStore, WivesMasterStore
from .context import CommandContext

_SIGN_IN_FLAVOR = {
    "low": [      # 亲密度 0-49
        "{name}：哦，你来了。（冷漠脸）",
        "{name}：签到？嗯。（头也不抬）",
        "{name}：……你好。（小声）",
        "{name}收下了你的签到币，但没有说话。",
    ],
    "mid": [      # 亲密度 50-149
        "{name}：你来啦~今天也要加油哦！",
        "{name}：签到成功！给你的奖励~",
        "{name}：嘿嘿，你每天都来呢。",
        "{name}：今天天气不错，适合签到~",
    ],
    "high": [     # 亲密度 150-299
        "{name}：你终于来了！我等你好久了~❤️",
        "{name}飞扑过来：你今天也来看我了吗！",
        "{name}：每次看到你来我就开心~",
        "{name}：签到成功！顺便……想你了。",
    ],
    "max": [      # 亲密度 300+
        "{name}：你是我的全世界~签到什么的不重要，你在就好❤️",
        "{name}紧紧抱住你：不要离开我好不好……",
        "{name}：签到？不如我们去约会吧~❤️",
        "{name}：今天也是爱你的一天！签到币什么的都给你~",
    ],
}

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

    economy = EconomyService(ctx.paths, ctx.config, ctx.locks)
    result = await economy.daily_checkin(gid, uid, nick)

    if result is None:
        yield event.plain_result("今天已经签到过了，明天再来吧~")
        return

    reward, bonus_coins, bonus_item = result
    balance = economy.balance(gid, uid)

    lines = [f"签到成功！获得 {reward} 老婆币"]
    if bonus_coins > 0:
        lines[0] += f"（含额外奖励 {bonus_coins} 币）"
    if bonus_item:
        item_name = ITEM_NAMES.get(bonus_item, bonus_item)
        lines.append(f"🎁 额外获得：{item_name}")

    weekly_box = economy.claim_weekly_surprise_box_sync(gid, uid, nick)
    if weekly_box is not None:
        box_coins, box_item = weekly_box
        lines.append(f"📦 本周惊喜宝箱：+{box_coins} 币")
        if box_item:
            item_name = ITEM_NAMES.get(box_item, box_item)
            lines.append(f"📦 宝箱额外获得：{item_name}")
    lines.append(f"当前余额：{balance} 币")

    # 按亲密度等级添加签到台词
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    primary = ownership_store.get_primary(uid, ownerships)
    if primary:
        wives_meta = WivesMasterStore(ctx.paths).load_all()
        w = wives_meta.get(primary.wid)
        wife_name = (w.chara or w.img or "该老婆") if w else "该老婆"
        intimacy = primary.intimacy
        if intimacy < 50:
            tier = "low"
        elif intimacy < 150:
            tier = "mid"
        elif intimacy < 300:
            tier = "high"
        else:
            tier = "max"
        taunt = random.choice(_SIGN_IN_FLAVOR[tier]).format(name=wife_name)
        lines.append(f"\n💬 {taunt}")

    yield event.plain_result("\n".join(lines))


async def handle_quest(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 任务`` — 查看任务进度 / 领取任务奖励"""
    gid = get_group_id(event)
    if not gid:
        return

    uid = str(event.get_sender_id())
    nick = get_sender_nick(event)

    quest = QuestService(ctx.paths, ctx.config, ctx.locks)
    economy = EconomyService(ctx.paths, ctx.config)
    weekly_box = economy.claim_weekly_surprise_box_sync(gid, uid, nick)

    # 先尝试领取
    reward = await quest.check_and_complete(gid, uid, nick)
    if reward is not None:
        balance = economy.balance(gid, uid)
        lines = [f"任务完成！获得 {reward.coins} 老婆币"]
        if reward.item:
            item_name = ITEM_NAMES.get(reward.item, reward.item)
            lines.append(f"🎁 额外获得：{item_name}")
        if weekly_box is not None:
            box_coins, box_item = weekly_box
            lines.append(f"📦 本周惊喜宝箱：+{box_coins} 币")
            if box_item:
                item_name = ITEM_NAMES.get(box_item, box_item)
                lines.append(f"📦 宝箱额外获得：{item_name}")
        lines.append(f"当前余额：{balance} 币")
        yield event.plain_result("\n".join(lines))
        return

    if weekly_box is not None:
        box_coins, box_item = weekly_box
        lines = [f"📦 本周惊喜宝箱已领取：+{box_coins} 币"]
        if box_item:
            item_name = ITEM_NAMES.get(box_item, box_item)
            lines.append(f"📦 宝箱额外获得：{item_name}")
        yield event.plain_result("\n".join(lines))

    # 展示任务进度
    status = quest.get_quest_status(gid, uid)
    lines = [quest.get_track_title(gid, uid)]
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

    shop = ShopService(ctx.paths, ctx.config, ctx.locks)
    items = shop.list_items()

    uid = str(event.get_sender_id())
    economy = EconomyService(ctx.paths, ctx.config, ctx.locks)
    balance = economy.balance(gid, uid)

    lines = [f"【商城】余额：{balance} 币\n"]
    for key, name, price in items:
        lines.append(f"• {name} — {price} 币  （老婆 购买 {name}）")

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

    shop = ShopService(ctx.paths, ctx.config, ctx.locks)
    ok, msg_text = await shop.buy(gid, uid, item_key, quantity, nick)

    if ok:
        economy = EconomyService(ctx.paths, ctx.config, ctx.locks)
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
    shop = ShopService(ctx.paths, ctx.config, ctx.locks)
    inv = shop.get_inventory(gid, uid)

    if not inv:
        yield event.plain_result("背包空空如也，去商城逛逛吧~")
        return

    lines = ["【背包】"]
    for key, count in inv.items():
        name = ITEM_NAMES.get(key, key)
        lines.append(f"• {name} x{count}")

    yield event.plain_result("\n".join(lines))
