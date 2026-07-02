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
from ..api.messaging import build_text_image_chain
from ..utils.image import build_wife_intro_text
from .context import CommandContext

__all__ = ["handle_view", "find_uid_by_owner_nick"]


async def handle_view(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``查老婆 [@用户 | 昵称]``：查看自己或他人的主老婆"""
    gid = get_group_id(event)
    if not gid:
        return

    tid = _resolve_target(event, ctx)
    if tid is None:
        yield event.plain_result("没有发现老婆的踪迹，快去抽一个试试吧~")
        return

    img = ctx.ownership_service.get_primary_img(gid, tid)
    if not img:
        yield event.plain_result("没有发现老婆的踪迹，快去抽一个试试吧~")
        return

    target_profile = ctx.ownership_service.get_profile(gid, tid)
    owner = target_profile.nick or "未知用户"
    intro = build_wife_intro_text(img, prefix=f"{owner}的老婆是", suffix="，羡慕吗？")
    yield event.chain_result(
        build_text_image_chain(
            intro,
            img,
            ctx.paths.img_dir,
            ctx.config.normalized_image_base_url,
        )
    )


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
