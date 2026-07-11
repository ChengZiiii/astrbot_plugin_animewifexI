"""``老婆 编队`` 命令：4v4 接力战的出战顺序管理。

语法：

* ``老婆 编队`` —— 查看当前编队，未设置时给出用法提示。
* ``老婆 编队 <n1> [n2] [n3] [n4]`` —— 按用户指定顺序设置编队（1-4 位）。
* ``老婆 编队 默认`` —— 按持有列表前 N 个填充 formation（N = min(持有数, 4)）；
  持有为空时返回错误提示，不写入编队。
* ``老婆 编队 清除`` / ``清空`` —— 清空编队（PK 时退化为"默认前 N 个"）。

校验：

* 编号必须是自己持有的老婆（用持有列表 1-based 编号索引）；
* 长度 1-4 有效，> 4 拒绝；
* 同一次设置中不允许重复编号；
* 锁定老婆可进编队但有 PK 战力惩罚（PK 服务层处理）；
* 设置后立即持久化到 ``profiles.json``。
"""

from __future__ import annotations

from typing import AsyncGenerator, List, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..storage.stores import OwnershipStore, ProfileStore
from .context import CommandContext

__all__ = ["handle_formation"]

_MAX_FORMATION_SIZE = 4


async def handle_formation(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 编队`` 命令入口（async generator）"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event) or "你"

    msg = (event.message_str or "").strip()
    rest = _strip_prefix(msg)

    # 无参数 → 查看当前编队
    if not rest:
        async for item in _show_formation(event, ctx, gid, uid, nick):
            yield item
        return

    rest_norm = rest.strip()
    # 默认 / 清除 / 清空
    if rest_norm == "默认":
        async for item in _default_formation(event, ctx, gid, uid, nick):
            yield item
        return
    if rest_norm in ("清除", "清空"):
        async for item in _clear_formation(event, ctx, gid, uid, nick):
            yield item
        return

    # 解析编号
    numbers = _parse_indices(rest_norm)
    if numbers is None:
        yield event.plain_result(
            "格式：老婆 编队 <编号1> [编号2] [编号3] [编号4]（1-4 个不重复编号）\n"
            "或：老婆 编队 默认（按持有列表前 N 个自动填充）\n"
            "或：老婆 编队 清除（清空编队）"
        )
        return

    async for item in _set_formation(event, ctx, gid, uid, nick, numbers):
        yield item


# ---------- helpers ----------


def _strip_prefix(msg: str) -> str:
    """去掉 ``老婆 编队`` 前缀，返回剩余参数文本"""
    for prefix in ("老婆编队", "老婆 编队"):
        if msg.startswith(prefix):
            return msg[len(prefix):].strip()
    return msg.strip()


def _parse_indices(text: str) -> Optional[List[int]]:
    """从 ``"2 4 1 3"`` 这类字符串解析为 ``[2, 4, 1, 3]``，无法解析返回 ``None``"""
    parts = [p for p in text.replace(",", " ").split() if p]
    if not parts:
        return None
    indices: List[int] = []
    for p in parts:
        if not p.isdigit():
            return None
        indices.append(int(p))
    return indices


async def _show_formation(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
) -> AsyncGenerator:
    """``老婆 编队`` 无参数 → 查看当前编队"""
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile_store.save_all(profiles)

    my_wives = ownership_store.list_by_user(uid, ownerships)
    if not my_wives:
        yield event.plain_result(
            f"{nick}，你还没有老婆，先去抽一个吧~"
        )
        return

    formation = list(profile.formation)
    if not formation:
        yield event.plain_result(
            f"{nick}，你还没有设置编队。\n"
            f"使用 `老婆 编队 <编号1> [编号2] [编号3] [编号4]` 一次性设置 1-4 位出战老婆\n"
            f"或 `老婆 编队 默认` 按持有列表前 N 个自动填充（持有 ≥ 4 时填 4 位）"
        )
        return

    # 把 wid 翻译回 1-based 编号展示
    wid_to_index = {o.wid: i + 1 for i, o in enumerate(my_wives)}
    nums = [wid_to_index.get(wid, -1) for wid in formation]
    nums_str = " ".join(str(n) for n in nums) if nums else "(空)"

    yield event.plain_result(
        f"{nick} 的当前编队：{nums_str}\n"
        f"（共 {len(formation)} 位，不足 4 位 PK 时按 Nv4 进行）\n"
        f"💡 修改：`老婆 编队 <新编号...>` 或 `老婆 编队 默认` 重置为持有顺序"
    )


async def _clear_formation(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
) -> AsyncGenerator:
    """``老婆 编队 清除/清空`` → 把 formation 清空（profile.formation = []）"""
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile.formation = []
    profile_store.save_all(profiles)

    yield event.plain_result(
        f"✅ 已清空编队（下次 PK 将用默认编队）"
    )


async def _default_formation(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
) -> AsyncGenerator:
    """``老婆 编队 默认`` → 按持有列表前 N 个填充 formation（N = min(持有数, 4)）。

    spec §S4.1：当持有老婆 ≥ 4 时填前 4 个，< 4 时填持有数，= 0 时返回错误。
    """
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)
    if not my_wives:
        yield event.plain_result(
            f"你还没有老婆，先去抽一个吧~"
        )
        return

    take = min(len(my_wives), _MAX_FORMATION_SIZE)
    wids: List[str] = [o.wid for o in my_wives[:take]]

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile.formation = list(wids)
    profile_store.save_all(profiles)

    nums_str = " ".join(str(i + 1) for i in range(take))
    yield event.plain_result(
        f"✅ 已按持有列表设置默认编队（前 {take} 个）：{nums_str}"
    )


async def _set_formation(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    uid: str,
    nick: str,
    indices: List[int],
) -> AsyncGenerator:
    """``老婆 编队 <n1> ...`` → 校验后写入编队"""
    # 长度校验
    if len(indices) > _MAX_FORMATION_SIZE:
        yield event.plain_result(
            f"编队最多 {_MAX_FORMATION_SIZE} 位哦~你提供了 {len(indices)} 个编号"
        )
        return

    # 重复校验
    if len(set(indices)) != len(indices):
        yield event.plain_result(
            "编队编号不能重复，请重新指定~"
        )
        return

    # 持有校验
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)
    if not my_wives:
        yield event.plain_result(
            f"{nick}，你还没有老婆，先去抽一个吧~"
        )
        return

    max_idx = len(my_wives)
    for n in indices:
        if n < 1 or n > max_idx:
            yield event.plain_result(
                f"编号 {n} 超出范围（你持有 {max_idx} 位老婆，编号 1-{max_idx}）"
            )
            return

    # 写入编队（按用户指定顺序）
    wids: List[str] = [my_wives[n - 1].wid for n in indices]

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile.formation = list(wids)
    profile_store.save_all(profiles)

    nums_str = " ".join(str(n) for n in indices)
    suffix = ""
    if len(indices) < _MAX_FORMATION_SIZE:
        suffix = (
            f"\n⚠️ 当前编队 {len(indices)} 位，PK 时将按 Nv{_MAX_FORMATION_SIZE} 进行，"
            f"可继续 `老婆 编队 <更多编号>` 补齐 4 位"
        )
    yield event.plain_result(
        f"{nick}，编队已设置：{nums_str}{suffix}"
    )