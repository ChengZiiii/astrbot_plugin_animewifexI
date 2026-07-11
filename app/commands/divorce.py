"""``老婆 离婚`` 命令处理器：预览、确认、冷却查询。

Phase D / v3 离婚系统：
- 老婆 离婚 <编号> — 预览离婚返还 + 分家产概率
- 老婆 离婚 <编号> 确认 — 执行离婚
- 老婆 离婚 冷却 — 查询冷却剩余天数
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import AsyncGenerator, Dict

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..services.divorce_service import (
    DIVORCE_COOLDOWN_DAYS,
    RETURN_BASE,
    apply_divorce_split,
    calc_divorce_property_split_amount,
    calc_divorce_property_split_prob,
    calc_divorce_return,
    validate_divorce_possible,
)
from ..storage.stores import OwnershipStore, ProfileStore, WivesMasterStore
from .context import CommandContext

__all__ = ["handle_divorce"]

# 预览缓存：{uid: {"wid": str, "created_at": float}}
_divorce_pending: Dict[str, Dict] = {}
_DIVORCE_PREVIEW_TTL = 600  # 10 分钟


def _strip_prefix(msg: str) -> str:
    """去掉 ``老婆 离婚`` 前缀，返回剩余参数文本"""
    for prefix in ("老婆离婚", "老婆 离婚"):
        if msg.startswith(prefix):
            return msg[len(prefix):].strip()
    return msg.strip()


def _parse_args(rest: str):
    """解析子命令参数。

    Returns:
        (sub, arg) 元组
        sub: "preview" | "confirm" | "cooldown" | ""
    """
    if not rest:
        return ("", "")

    parts = rest.split(maxsplit=1)
    first = parts[0]
    remainder = parts[1] if len(parts) > 1 else ""

    if first == "冷却":
        return ("cooldown", "")

    if first.isdigit():
        if remainder == "确认":
            return ("confirm", first)
        return ("preview", first)

    return ("", "")


async def handle_divorce(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 离婚`` 命令入口"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event) or "你"

    msg = (event.message_str or "").strip()
    rest = _strip_prefix(msg)
    sub, arg = _parse_args(rest)

    if sub == "cooldown":
        async for item in _handle_cooldown_query(event, ctx, gid, uid, nick):
            yield item
        return

    if sub == "preview":
        async for item in _handle_preview(event, ctx, gid, uid, nick, arg):
            yield item
        return

    if sub == "confirm":
        async for item in _handle_confirm(event, ctx, gid, uid, nick, arg):
            yield item
        return

    # 无参数 / 未知参数 → 用法提示
    yield event.plain_result(
        "💡 离婚系统用法：\n"
        "  `老婆 离婚 <编号>` — 预览离婚返还\n"
        "  `老婆 离婚 <编号> 确认` — 确认离婚\n"
        "  `老婆 离婚 冷却` — 查看冷却剩余天数"
    )


async def _handle_cooldown_query(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
) -> AsyncGenerator:
    """``老婆 离婚 冷却`` — 查询冷却"""
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile_store.save_all(profiles)

    if not profile.last_divorce_date:
        yield event.plain_result("你还没有离过婚，随时可以离婚哦~")
        return

    try:
        last = datetime.strptime(profile.last_divorce_date, "%Y-%m-%d").date()
        today = datetime.strptime(ctx.today(), "%Y-%m-%d").date()
        days_passed = (today - last).days
        if days_passed >= DIVORCE_COOLDOWN_DAYS:
            yield event.plain_result("你的离婚冷却已过，可以离婚了~")
        else:
            remaining = DIVORCE_COOLDOWN_DAYS - days_passed
            yield event.plain_result(
                f"你上次离婚是 {profile.last_divorce_date}，"
                f"还需等待 {remaining} 天才能再次离婚"
            )
    except ValueError:
        yield event.plain_result("日期数据异常，请联系管理员")


async def _handle_preview(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
    idx_str: str,
) -> AsyncGenerator:
    """``老婆 离婚 <编号>`` — 预览模式"""
    if not idx_str:
        yield event.plain_result("请指定老婆编号：`老婆 离婚 <编号>`")
        return

    try:
        idx = int(idx_str)
    except ValueError:
        yield event.plain_result("编号必须是数字")
        return

    # 查持有
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)

    if not my_wives:
        yield event.plain_result(f"{nick}，你还没有老婆~")
        return

    if idx < 1 or idx > len(my_wives):
        yield event.plain_result(
            f"编号 {idx} 超出范围（你持有 {len(my_wives)} 位老婆，编号 1-{len(my_wives)}）"
        )
        return

    target_ownership = my_wives[idx - 1]
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)

    # 前置校验
    ok, reason = validate_divorce_possible(profile, target_ownership, ctx.today())
    if not ok:
        yield event.plain_result(reason)
        return

    # 获取老婆元数据
    wives_meta = WivesMasterStore(ctx.paths).load_all()
    meta = wives_meta.get(target_ownership.wid)
    wife_name = (meta.chara or meta.img or "该老婆") if meta else "该老婆"
    rarity = meta.rarity if meta else "N"
    intimacy = target_ownership.intimacy
    is_dead = target_ownership.is_dead

    # 计算返还
    divorce_return = calc_divorce_return(rarity, intimacy) if not is_dead else 0

    # 计算分家产概率
    split_prob = calc_divorce_property_split_prob(intimacy) if not is_dead else 0.0
    split_prob_pct = int(split_prob * 100)

    # 计算分家产金额（基于当前余额）
    split_amount = calc_divorce_property_split_amount(profile.coins) if not is_dead else 0
    new_balance_if_split = profile.coins - split_amount if not is_dead else profile.coins

    # 保存预览状态
    _divorce_pending[uid] = {
        "wid": target_ownership.wid,
        "created_at": datetime.now().timestamp(),
    }

    # 生成预览贴
    base_val = RETURN_BASE.get(rarity, "?")
    mult = 1 + intimacy / 100.0
    if is_dead:
        lines = [
            "═══════════════════════════════════════",
            "⚠️ 离婚预告（离世）",
            "═══════════════════════════════════════",
            "",
            f"🪦 你考虑送走 [{wife_name}] {rarity} ☠️ 已离世",
            "",
            "💔 老婆已离世，离婚不返还任何老婆币",
            "💔 老婆已离世，不会触发分家产",
            "",
            "📌 离婚后：",
            f"   • [{wife_name}] 将从你的持有列表移除",
            "   • 图鉴保留（标记'已离世'）",
            f"   • {DIVORCE_COOLDOWN_DAYS} 天内不能再离婚",
            "",
            "⚠️ 确定要执行吗？发送 `老婆 离婚 <编号> 确认`",
            "  （预览有效期 10 分钟）",
            "═══════════════════════════════════════",
        ]
    else:
        lines = [
            "═══════════════════════════════════════",
            "⚠️ 离婚预告",
            "═══════════════════════════════════════",
            "",
            f"👋 你考虑放弃 [{wife_name}] {rarity} ❤️ {intimacy}",
            "",
            f"💰 离婚返还：{divorce_return} 币（基础 {base_val} × 好感度倍率 {mult:.1f}）",
            f"📊 分家产概率：{split_prob_pct}%（好感度 {intimacy}，命中 50% 上限）",
            f"💸 分家产金额（基于当前余额 {profile.coins}）：",
            f"   • 触发时：{split_amount:+d} 币 → 新余额 {new_balance_if_split}",
            f"   • 不触发：+{divorce_return} 币 → 新余额 {profile.coins + divorce_return}",
            "",
            "📌 离婚后：",
            f"   • [{wife_name}] 将离开你的持有列表",
            "   • 图鉴保留（标记'已离异'）",
            f"   • {DIVORCE_COOLDOWN_DAYS} 天内不能再离婚",
            "",
            "⚠️ 确定要执行吗？发送 `老婆 离婚 <编号> 确认`",
            "  （预览有效期 10 分钟）",
            "═══════════════════════════════════════",
        ]
    yield event.plain_result("\n".join(lines))


async def _handle_confirm(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
    idx_str: str,
) -> AsyncGenerator:
    """``老婆 离婚 <编号> 确认`` — 执行模式"""
    # 检查预览状态
    pending = _divorce_pending.get(uid)
    if not pending:
        yield event.plain_result("请先发送 `老婆 离婚 <编号>` 进行预览确认")
        return

    # 检查 TTL
    now = datetime.now().timestamp()
    if now - pending["created_at"] > _DIVORCE_PREVIEW_TTL:
        del _divorce_pending[uid]
        yield event.plain_result(
            "预览已过期（超过 10 分钟），请重新发送 `老婆 离婚 <编号>`"
        )
        return

    wid = pending["wid"]

    # 加载数据
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    target = ownership_store.find_by_wid(wid, ownerships)

    if target is None or target.uid != uid:
        del _divorce_pending[uid]
        yield event.plain_result("该老婆已经不属于你了，离婚取消")
        return

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)

    # 二次校验（避免冷却/状态在此期间改变）
    ok, reason = validate_divorce_possible(profile, target, ctx.today())
    if not ok:
        del _divorce_pending[uid]
        yield event.plain_result(reason)
        return

    # 获取老婆元数据
    wives_meta = WivesMasterStore(ctx.paths).load_all()
    meta = wives_meta.get(wid)
    wife_name = (meta.chara or meta.img or "该老婆") if meta else "该老婆"
    rarity = meta.rarity if meta else "N"
    intimacy = target.intimacy
    is_dead = target.is_dead

    # Phase 6: 死亡老婆离婚不返不扣
    if is_dead:
        divorce_return = 0
        split_happens = False
        split_amount = 0
    else:
        # 计算返还
        divorce_return = calc_divorce_return(rarity, intimacy)

        # 计算分家产
        split_prob = calc_divorce_property_split_prob(intimacy)
        split_happens = random.random() < split_prob

    old_coins = profile.coins

    if not is_dead and split_happens:
        split_amount = calc_divorce_property_split_amount(profile.coins)
        new_coins, _ = apply_divorce_split(profile.coins)
        profile.coins = new_coins

        if split_amount > 0:
            profile.total_divorce_property_lost += split_amount
        elif split_amount < 0:
            profile.total_divorce_debt_relieved += abs(split_amount)
    else:
        split_amount = 0

    # 应用返还（死亡老婆不返）
    if not is_dead:
        profile.coins += divorce_return
        profile.total_divorce_coins_earned += divorce_return

    # 更新统计
    profile.total_divorces += 1
    profile.last_divorce_date = ctx.today()

    # 删除所有权（移除持有）
    ownership_store.remove_by_wid(ownerships, wid)

    # 保存
    ownership_store.save_all(ownerships)
    profile_store.save_all(profiles)

    # 清理预览状态
    del _divorce_pending[uid]

    # 生成结算贴
    lines = [
        "═══════════════════════════════════════",
        "💔 离婚完成",
        "═══════════════════════════════════════",
        "",
    ]
    if is_dead:
        lines.append(f"🪦 [{wife_name}] {rarity} ☠️ 已离世 从你的持有列表移除")
        lines.append("   （图鉴保留，标记'已离世'）")
    else:
        lines.append(f"👋 [{wife_name}] {rarity} ❤️ {intimacy} 离开了你的持有列表")
        lines.append("   （图鉴保留，标记'已离异'）")
        lines.append("")
        lines.append(f"💰 返还币：+{divorce_return} 币")

        if split_happens:
            lines.append(f"💸 分家产：触发！")
            lines.append(
                f"   • 余额：{old_coins} → {profile.coins} ({split_amount:+d} 币)"
            )
        else:
            lines.append(f"💸 分家产：未触发")

    lines.extend(
        [
            "",
            "📋 累计统计：",
            f"   • 离婚次数：{profile.total_divorces} 次",
            f"   • 累计返还：{profile.total_divorce_coins_earned} 币",
            f"   • 累计损失/减压：{profile.total_divorce_property_lost}/{profile.total_divorce_debt_relieved} 币",
            "",
            f"⏰ 下次可离婚：{DIVORCE_COOLDOWN_DAYS} 天后",
        ]
    )

    # 展示当前持有
    remaining_wives = ownership_store.list_by_user(uid, ownerships)
    if remaining_wives:
        names = []
        for o in remaining_wives:
            m = wives_meta.get(o.wid)
            n = (m.chara or m.img or "?") if m else "?"
            names.append(f"[{n}]")
        lines.extend(
            [
                "",
                f"📢 @{nick} 你的当前持有：{' '.join(names)}",
            ]
        )

    lines.append("═══════════════════════════════════════")
    yield event.plain_result("\n".join(lines))
