"""PK 命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid, parse_at_target
from ..services.pk_service import PkService
from .context import CommandContext
from .view import find_uid_by_owner_nick

__all__ = ["handle_pk"]


async def handle_pk(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 PK @某人``"""
    gid = get_group_id(event)
    if not gid:
        return
    attacker_uid = get_sender_uid(event)
    attacker_nick = get_sender_nick(event)

    # 解析目标
    tid = parse_at_target(event)
    if not tid:
        # 尝试昵称匹配
        msg = (event.message_str or "").strip()
        rest = msg
        for prefix in ("老婆PK", "老婆 PK"):
            if rest.startswith(prefix):
                rest = rest[len(prefix):]
                break
        target_nick = rest.strip()
        if target_nick:
            tid = find_uid_by_owner_nick(ctx, gid, target_nick)

    if not tid:
        yield event.plain_result(f"{attacker_nick}，请@你想PK的对象哦~")
        return
    if tid == attacker_uid:
        yield event.plain_result(f"{attacker_nick}，不能和自己PK哦~")
        return

    # 获取对方昵称
    from ..storage.stores import ProfileStore
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    target_profile = profiles.get(tid)
    defender_nick = target_profile.nick if target_profile else "对方"

    pk_svc = PkService(ctx.paths, ctx.config, ctx.cooldown_service)
    result = pk_svc.pk(
        gid, attacker_uid, tid, attacker_nick, defender_nick, ctx.today()
    )

    if not result.ok:
        yield event.plain_result(f"{attacker_nick}，{result.msg}")
        return

    # 格式化战报
    lines = [
        f"【PK 战报】",
        f"⚔️ {result.attacker_name} vs {result.defender_name}",
        f"战力：{result.attacker_power:.0f} vs {result.defender_power:.0f}",
        f"",
        f"🏆 胜者：{result.winner_uid}（+{result.reward} 币）",
    ]
    yield event.plain_result("\n".join(lines))
