"""查老婆命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from ..api.messaging import build_multi_image_chain, build_text_image_chain
from ..storage.stores import OwnershipStore, WivesMasterStore
from ..utils.image import build_wife_intro_text
from .context import CommandContext

__all__ = ["handle_view", "find_uid_by_owner_nick"]


async def handle_view(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``查老婆 [@用户 | 昵称]``：查看自己或他人的所有老婆"""
    gid = get_group_id(event)
    if not gid:
        return

    sender_uid = get_sender_uid(event)
    at_target = parse_at_target(event)
    target_uid = _resolve_target(event, ctx)
    if target_uid is None:
        yield event.plain_result("没有找到该昵称的群友老婆哦~")
        return

    target_profile = ctx.ownership_service.get_profile(gid, target_uid)
    owner = target_profile.nick or "未知用户"

    # 获取该用户所有老婆
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(target_uid, ownerships)

    if not my_wives:
        if target_uid == sender_uid or at_target is None:
            yield event.plain_result("没有发现老婆的踪迹，快去抽一个试试吧~")
        else:
            yield event.plain_result(f"{owner}今天还没有老婆哦~")
        return

    # 加载老婆元数据
    wives_meta = WivesMasterStore(ctx.paths).load_all()

    # 格式化所有老婆
    lines = [f"【{owner} 的老婆】共 {len(my_wives)} 位\n"]
    imgs = []
    seen_imgs = set()

    from ..services.ownership_service import OwnershipService
    for i, o in enumerate(my_wives, 1):
        wife = wives_meta.get(o.wid)
        if not wife:
            continue
        emoji = {"SSR": "✨", "SR": "🌟", "R": "⭐", "N": "·"}.get(wife.rarity, "·")
        name = wife.chara or wife.img
        lock_icon = " 🔒" if o.is_locked else ""
        primary_icon = " 👑" if o.is_primary else ""
        intimacy_str = OwnershipService.intimacy_level_emoji(o.intimacy)
        lines.append(f"{i}. {emoji} {name} (❤️{o.intimacy}{intimacy_str}){lock_icon}{primary_icon}")

        # 收集图片（去重）
        if wife.img and wife.img not in seen_imgs:
            imgs.append(wife.img)
            seen_imgs.add(wife.img)

    text = "\n".join(lines)

    if imgs:
        yield event.chain_result(
            build_multi_image_chain(
                text,
                imgs,
                ctx.paths.img_dir,
                ctx.config.normalized_image_base_url,
            )
        )
    else:
        yield event.plain_result(text)


def _resolve_target(event: AstrMessageEvent, ctx: CommandContext) -> Optional[str]:
    """解析目标用户 ID：@优先 → 文本昵称匹配 → 默认自己"""
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

    return get_sender_uid(event)


def find_uid_by_owner_nick(
    ctx: CommandContext, gid: str, nick: str
) -> Optional[str]:
    """根据用户档案的 nick 字段反查 uid（要求该 uid 当前持有主老婆）

    v2.x 的 ``wife.owner`` 字段在 v3.x 由 ``UserProfile.nick`` 等价承担。
    """
    from ..storage.stores import ProfileStore

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    for uid, profile in profiles.items():
        if profile.nick == nick:
            if ctx.ownership_service.get_primary_wid(gid, uid):
                return uid
    return None


def find_wid_by_index(
    ctx: CommandContext, gid: str, uid: str, msg: Optional[str]
) -> Optional[str]:
    """从消息中解析老婆编号（1-based），返回对应 wid。

    格式：``老婆 求婚 1`` 或 ``老婆 锁 2``
    """
    if not msg:
        return None
    # 取最后一个数字
    import re
    numbers = re.findall(r"\d+", msg)
    if not numbers:
        return None
    idx = int(numbers[-1]) - 1  # 转为 0-based

    from ..storage.stores import OwnershipStore
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)
    if 0 <= idx < len(my_wives):
        return my_wives[idx].wid
    return None
