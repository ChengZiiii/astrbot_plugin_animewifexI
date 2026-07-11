"""``老婆 休息`` / ``养老婆`` / ``老婆 复活`` 命令处理器。

设计要点
--------

* **三种 alias 共享同一逻辑**（底层都是修老婆的命）：
  - ``老婆 休息`` / ``休息`` — 修复（任意老婆）
  - ``养老婆`` / ``老婆 养老婆`` — 修复（alias）
  - ``老婆 复活`` / ``复活`` — 复活（语义上更强调"死了救回来"，但实现相同）
* **不指定编号**：列出所有老婆的修复价格预览，提示 ``老婆 休息 <编号>`` 确认。
  不直接扣币，避免误操作。
* **指定编号**：扣币 + 满血复活。
* **死亡老婆**：按 ``lifespan=0`` 算价格（即 2x 基础价）；复活后清 ``is_dead``。
* **活老婆修复**：按当前 ``lifespan`` 算价格，扣币后满血。
* **满血修复**：返回 "already_full"，不扣币。
* **币不够**：返回 "not_enough_coins"。
* **全部走群锁**（与其它命令一致）。
"""

from __future__ import annotations

import re
from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..services.lifespan_service import format_lifespan_bar
from ..storage.stores import OwnershipStore, WivesMasterStore
from .context import CommandContext
from .view import find_wid_by_position

__all__ = ["handle_rest"]


# 命令前缀列表（休息 / 养老婆 / 复活 共享同一 handler）
_REST_PREFIXES = (
    "老婆休息", "老婆 休息",
    "养老婆", "老婆 养老婆",
    "老婆复活", "老婆 复活",
    "休息",        # 兼容简短
    "复活",        # 兼容简短
)


def _strip_prefix(msg: str) -> str:
    """去掉 ``老婆 休息`` 等前缀，返回剩余参数文本。"""
    for prefix in _REST_PREFIXES:
        if msg.startswith(prefix):
            return msg[len(prefix):].strip()
    return msg.strip()


def _parse_args(rest: str) -> tuple[str, str]:
    """解析参数。

    Returns:
        (sub, arg)
        sub: "" | "preview" | "confirm"
        arg: 老婆编号（字符串）
    """
    if not rest:
        return ("preview", "")
    parts = rest.split(maxsplit=1)
    first = parts[0]
    if first.isdigit():
        return ("confirm", first)
    return ("preview", "")


async def handle_rest(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 休息 [编号]`` / ``养老婆 [编号]`` / ``老婆 复活 [编号]`` 命令入口。"""
    if not getattr(ctx.config, "lifespan_enabled", True):
        yield event.plain_result("💤 寿命系统未开启，无需修复/复活~")
        return

    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event) or "你"

    msg = (event.message_str or "").strip()
    rest = _strip_prefix(msg)
    sub, arg = _parse_args(rest)

    if sub == "preview":
        async for item in _handle_preview(event, ctx, gid, uid, nick):
            yield item
        return

    if sub == "confirm":
        async for item in _handle_confirm(event, ctx, gid, uid, nick, arg):
            yield item
        return

    # fallback
    async for item in _handle_preview(event, ctx, gid, uid, nick):
        yield item


async def _handle_preview(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
) -> AsyncGenerator:
    """``老婆 休息``（不指定编号）— 列出所有老婆的修复价格预览。"""
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)
    if not my_wives:
        yield event.plain_result(f"{nick}，你还没有老婆~")
        return

    wives_meta = WivesMasterStore(ctx.paths).load_all()
    lifespan_svc = ctx.lifespan_service

    lines = [f"🛏️ {nick} 的老婆修复价格表：", ""]

    needs_repair = []
    for i, o in enumerate(my_wives, 1):
        meta = wives_meta.get(o.wid)
        name = (meta.chara or meta.img or "?") if meta else "?"
        rarity = meta.rarity if meta else "N"

        bar = format_lifespan_bar(
            o.lifespan, ctx.config.lifespan_max, is_dead=o.is_dead,
        )
        quote = lifespan_svc.quote_revive_cost(gid, o.wid)
        cost = quote.get("cost", 0) if quote.get("ok") else 0

        if o.is_dead:
            tag = "☠️ 离世"
        elif o.lifespan >= ctx.config.lifespan_max:
            tag = "✅ 满血"
        else:
            tag = "⚠️ 受损"
            needs_repair.append(i)

        if o.is_dead or o.lifespan < ctx.config.lifespan_max:
            cost_str = f"{cost} 币"
        else:
            cost_str = "—"

        lines.append(f"  {i}. {name} {rarity} | {bar} | {tag} | 修复 {cost_str}")

    lines.append("")
    if not needs_repair and not any(o.is_dead for o in my_wives):
        lines.append("✅ 所有老婆都满血，无需修复~")
    else:
        lines.append("💡 发送 `老婆 休息 <编号>` 修复指定老婆")
        lines.append("   例：`老婆 休息 1`（修第 1 位）")
    lines.append("   ⚰️ 死亡老婆按 2x 基础价满血复活")

    yield event.plain_result("\n".join(lines))


async def _handle_confirm(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
    idx_str: str,
) -> AsyncGenerator:
    """``老婆 休息 <编号>`` — 扣币 + 满血修复/复活。"""
    if not idx_str:
        yield event.plain_result("请指定老婆编号：`老婆 休息 <编号>`")
        return

    try:
        idx = int(idx_str)
    except ValueError:
        yield event.plain_result("编号必须是数字")
        return

    wid = find_wid_by_position(ctx, gid, uid, idx)
    if wid is None:
        yield event.plain_result(f"{nick}，你指定的老婆编号不存在哦~")
        return

    # 走 lifespan_service（在群锁内）
    async with ctx.locks.acquire(gid):
        result = ctx.lifespan_service.apply_revive(
            gid, uid, nick, wid, target_wid=wid,
        )

    if not result.ok:
        if result.reason == "already_full":
            yield event.plain_result(f"💚 第 {idx} 位老婆已经满血，无需修复~")
        elif result.reason == "wife_not_found":
            yield event.plain_result(f"{nick}，找不到该老婆~")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"💸 修复需要 {result.cost} 币，你只有 {result.coin_balance} 币~"
            )
        else:
            yield event.plain_result(f"{nick}，修复失败了 ({result.reason})~")
        return

    wives_meta = WivesMasterStore(ctx.paths).load_all()
    meta = wives_meta.get(wid)
    wife_name = (meta.chara or meta.img or "该老婆") if meta else "该老婆"
    rarity = meta.rarity if meta else "N"

    if result.was_dead:
        title = "🕯️ 复活成功"
        kind = "复活"
    else:
        title = "💚 修复完成"
        kind = "修复"

    yield event.plain_result(
        f"═══════════════════════════════════════\n"
        f"{title}\n"
        f"═══════════════════════════════════════\n"
        f"\n"
        f"💖 {wife_name} {rarity} 已{kind}！\n"
        f"❤️ 寿命：{result.new_lifespan}/{ctx.config.lifespan_max} "
        f"{'█' * 10}\n"
        f"💰 花费：{result.cost} 币\n"
        f"💰 余额：{result.coin_balance} 币\n"
    )
