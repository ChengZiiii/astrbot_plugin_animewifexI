"""PK 命令处理器。"""

from __future__ import annotations

import random
from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid, parse_at_target
from ..services.pk_service import PkService
from .context import CommandContext
from .view import find_uid_by_owner_nick

__all__ = ["handle_pk"]

_PK_WIN_FLAVOR = [
    "{winner}把{loser}按在地上摩擦！毫无悬念~",
    "{winner}一拳把{loser}打飞了！实力碾压~",
    "{winner}：就这？{loser}：呜呜呜……",
    "经过激烈对决，{winner}以绝对优势胜出！{loser}表示不服……",
    "{winner}使出了终极必杀技，{loser}当场去世（不是）",
    "观众：哇！{winner}太强了！{loser}：我不服，下次再来！",
]

_PK_DRAW_FLAVOR = [
    "双方打得难解难分，最后累得躺在地上……",
    "两个老婆互瞪了三分钟，谁也没动手。平局。",
    "裁判：我看了回放，真的分不出胜负……",
    "她们打了一架后发现是失散多年的姐妹，和好了。平局。",
]


async def handle_pk(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 PK @某人``：双方主老婆对战"""
    gid = get_group_id(event)
    if not gid:
        return
    attacker_uid = get_sender_uid(event)
    attacker_nick = get_sender_nick(event)

    tid = _resolve_target(event, ctx, gid)

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

    pk_svc = PkService(ctx.paths, ctx.config, ctx.locks, ctx.cooldown_service)
    result = await pk_svc.pk(
        gid,
        attacker_uid,
        tid,
        attacker_nick,
        defender_nick,
        ctx.today(),
    )

    if not result.ok:
        yield event.plain_result(f"{attacker_nick}，{result.msg}")
        return

    # T43: 格式化详细战报
    # 获取双方段位
    from ..storage.stores import ProfileStore
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    attacker_profile = profiles.get(result.attacker_uid)
    defender_profile = profiles.get(result.defender_uid)
    attacker_score = attacker_profile.pk_score if attacker_profile else 0
    defender_score = defender_profile.pk_score if defender_profile else 0
    attacker_rank = PkService.get_pk_rank(attacker_score)
    defender_rank = PkService.get_pk_rank(defender_score)
    attacker_rank_emoji = PkService.get_pk_rank_emoji(attacker_score)
    defender_rank_emoji = PkService.get_pk_rank_emoji(defender_score)

    # 元素克制显示
    element_info = ""
    if result.element_advantage > 1.0:
        element_info = f"（{result.attacker_element}克{result.defender_element}，攻击方有利！）"
    elif result.element_advantage < 1.0:
        element_info = f"（{result.defender_element}克{result.attacker_element}，防御方有利！）"
    else:
        element_info = f"（{result.attacker_element} vs {result.defender_element}，无克制）"

    # 胜负判定
    if result.is_tie:
        taunt = random.choice(_PK_DRAW_FLAVOR)
        result_text = f"🤝 平局！\n📢 {taunt}"
        winner_text = f"双方平局，各获得 {result.reward} 币"
    elif result.winner_uid == result.attacker_uid:
        taunt = random.choice(_PK_WIN_FLAVOR).format(winner=result.attacker_name, loser=result.defender_name)
        result_text = f"🎉 {result.attacker_name} 获胜！\n📢 {taunt}"
        winner_text = f"{result.attacker_name} 获得 {result.reward} 币"
    else:
        taunt = random.choice(_PK_WIN_FLAVOR).format(winner=result.defender_name, loser=result.attacker_name)
        result_text = f"🎉 {result.defender_name} 获胜！\n📢 {taunt}"
        winner_text = f"{result.defender_name} 获得 {result.reward} 币"

    lines = [
        f"【PK 战报】",
        f"⚔️ {result.attacker_name} vs {result.defender_name}",
        f"🔮 元素：{result.attacker_element} vs {result.defender_element} {element_info}",
        f"💪 战力：{result.attacker_power:.0f} vs {result.defender_power:.0f}",
        f"",
        f"{result_text}",
        f"🏆 {winner_text}",
        f"💰 败方获得：{result.loser_reward} 币",
        f"",
        f"📊 积分变化：",
        f"  {result.attacker_name}：+{result.winner_score_gain if result.winner_uid == result.attacker_uid else result.loser_score_gain} 分（{attacker_rank_emoji}{attacker_rank}）",
        f"  {result.defender_name}：+{result.loser_score_gain if result.winner_uid == result.attacker_uid else result.winner_score_gain} 分（{defender_rank_emoji}{defender_rank}）",
    ]
    yield event.plain_result("\n".join(lines))


def _resolve_target(
    event: AstrMessageEvent, ctx: CommandContext, gid: str
) -> str | None:
    """解析 PK 目标。

    语法：``老婆 PK @某人`` 或 ``老婆 PK 昵称``。
    """
    msg = (event.message_str or "").strip()
    rest = msg
    for prefix in ("老婆PK", "老婆 PK"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    tid = parse_at_target(event)
    if not tid:
        parts = rest.split(maxsplit=1)
        target_nick = parts[0].strip() if parts else ""
        if target_nick:
            tid = find_uid_by_owner_nick(ctx, gid, target_nick)
    return tid
