"""PK 命令处理器（含 1v1 / 4v4 双轨分发）。

对应 spec：

* §S4.2 — ``老婆 PK @某人`` 不带编号 → 4v4 接力战（new）
* §S4.5 — ``老婆 PK @某人 [n1] [n2]`` 带编号 → 1v1 单回合（legacy 兼容）
* §S10 — ``config.pk_v2_enabled`` 可关闭 4v4，回退 1v1

设计要点：

* **不破坏 1v1 路径**：Phase 4 的 ``PkService.pk`` + 战报生成逻辑全部保留原样
* **不持久化到 pk_service.py**：只在本文件分发
* **构造 PkBattle**：从双方持有老婆 + profile.formation 拼成两边 FormationMember，
  不足 4 位时按 holdings 前 N 个填充（spec §S4.5 容错）
* **主动消息 umo 捕获**：使用 ``event.unified_msg_origin`` —— spec §S7.6 强调
  必须在命令触发时捕获并传递
"""

from __future__ import annotations

import random
import re
from typing import AsyncGenerator, List, Optional, Sequence

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid, parse_at_target
from ..models.pk_battle import BattleStatusLayer, FormationMember, PkBattle
from ..services.pk_service import PkService
from ..services.pk_v2_passives import compute_combined_modifiers, derive_element
from ..services.pk_v2_service import PkV2Service
from ..storage.stores import OwnershipStore, ProfileStore, WivesMasterStore
from ..utils.time import now_ts
from .context import CommandContext
from .view import find_uid_by_owner_nick

__all__ = ["handle_pk", "_construct_battle"]

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
    """``老婆 PK @某人`` — 按有无数字参数走 1v1 或 4v4。

    * 不带编号 → 4v4（PkV2Service）
    * 带编号 → 1v1（PkService，Phase 4 兼容）
    """
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

    # 决定走哪条路径
    args_after_pk = _extract_args_after_pk(event.message_str or "")
    if _has_legacy_pk_indices(args_after_pk):
        # 带编号 → 1v1
        async for reply in _handle_pk_legacy_1v1(event, ctx, gid, attacker_uid, attacker_nick, tid):
            yield reply
        return

    # 不带编号 → 4v4（如果开启）；否则回退 1v1
    pk_v2_enabled = bool(getattr(ctx.config, "pk_v2_enabled", True))
    if not pk_v2_enabled:
        async for reply in _handle_pk_legacy_1v1(event, ctx, gid, attacker_uid, attacker_nick, tid):
            yield reply
        return

    # 4v4 路径
    async for reply in _handle_pk_v2_4v4(event, ctx, gid, attacker_uid, attacker_nick, tid):
        yield reply


# ============== 4v4 (PkV2) ==============


async def _handle_pk_v2_4v4(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    attacker_uid: str,
    attacker_nick: str,
    defender_uid: str,
) -> AsyncGenerator:
    """启动 4v4 接力战：
    1. 双方构造 PkBattle（编队 + 持有列表兜底）
    2. 调 PkV2Service.start_battle
    3. 返回同步 ack（启动贴单独推送）
    """
    # 拿对方昵称
    profiles = ProfileStore(ctx.paths, gid).load_all()
    defender_nick = profiles.get(defender_uid).nick if profiles.get(defender_uid) else "对方"

    # 构造 PkBattle + 前置校验
    try:
        battle, atk_used_default, def_used_default = _construct_battle(
            ctx, gid, attacker_uid, attacker_nick, defender_uid, defender_nick,
        )
    except _PkBuildError as e:
        yield event.plain_result(str(e))
        return

    # 启动贴里默认编队的额外公告
    intro_lines = []
    if atk_used_default:
        intro_lines.append(f"⚠️ @{attacker_nick} 还没设置编队，系统临时用默认前 {len(battle.atk_formation)} 位")
    if def_used_default:
        intro_lines.append(f"⚠️ @{defender_nick} 还没设置编队，系统临时用默认前 {len(battle.def_formation)} 位")

    # 调 PkV2Service.start_battle（构造 service + 发启动贴）
    umo = event.unified_msg_origin or ""

    # Phase C.3: 从 ctx.context（AstrBot Context）构造 send_message 闭包
    if ctx.context is not None:
        async def _pk_v2_send(umo_arg: str, text: str) -> None:
            from astrbot.api.event import MessageChain
            chain = MessageChain().message(text)
            await ctx.context.send_message(umo_arg, chain)
    else:
        _pk_v2_send = None

    service = PkV2Service(
        paths=ctx.paths,
        config=ctx.config,
        locks=ctx.locks,
        send_message=_pk_v2_send,
    )
    try:
        ack = await service.start_battle(battle, umo)
    except Exception as e:
        # 兜底：4v2 service 异常 → 回退 1v1
        yield event.plain_result(f"{attacker_nick}，4v4 启动失败 ({e!r})，已自动回退 1v1...")
        async for reply in _handle_pk_legacy_1v1(event, ctx, gid, attacker_uid, attacker_nick, defender_uid):
            yield reply
        return

    if intro_lines:
        yield event.plain_result("\n".join(intro_lines) + "\n" + ack)
    else:
        yield event.plain_result(ack)


# ============== 1v1 (Phase 4 兼容) ==============


async def _handle_pk_legacy_1v1(
    event: AstrMessageEvent,
    ctx: CommandContext,
    gid: str,
    attacker_uid: str,
    attacker_nick: str,
    defender_uid: str,
) -> AsyncGenerator:
    """原 Phase 4 1v1 单回合 PK —— 不改任何逻辑。"""
    # 获取对方昵称
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    target_profile = profiles.get(defender_uid)
    defender_nick = target_profile.nick if target_profile else "对方"

    pk_svc = PkService(ctx.paths, ctx.config, ctx.locks, ctx.cooldown_service)
    result = await pk_svc.pk(
        gid,
        attacker_uid,
        defender_uid,
        attacker_nick,
        defender_nick,
        ctx.today(),
    )

    if not result.ok:
        yield event.plain_result(f"{attacker_nick}，{result.msg}")
        return

    # T43: 格式化详细战报
    profiles = ProfileStore(ctx.paths, gid).load_all()
    attacker_profile = profiles.get(result.attacker_uid)
    defender_profile = profiles.get(result.defender_uid)
    attacker_score = attacker_profile.pk_score if attacker_profile else 0
    defender_score = defender_profile.pk_score if defender_profile else 0
    attacker_rank = PkService.get_pk_rank(attacker_score)
    defender_rank = PkService.get_pk_rank(defender_score)
    attacker_rank_emoji = PkService.get_pk_rank_emoji(attacker_score)
    defender_rank_emoji = PkService.get_pk_rank_emoji(defender_score)

    element_info = ""
    if result.element_advantage > 1.0:
        element_info = f"（{result.attacker_element}克{result.defender_element}，攻击方有利！）"
    elif result.element_advantage < 1.0:
        element_info = f"（{result.defender_element}克{result.attacker_element}，防御方有利！）"
    else:
        element_info = f"（{result.attacker_element} vs {result.defender_element}，无克制）"

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
        f"  {result.defender_name}：+{result.loser_score_gain if winner_uid_check(result, attacker_uid) else result.winner_score_gain} 分（{defender_rank_emoji}{defender_rank}）",
    ]
    yield event.plain_result("\n".join(lines))


def winner_uid_check(result, attacker_uid):
    return result.winner_uid == attacker_uid


# ============== helpers ==============


class _PkBuildError(Exception):
    """构造 PkBattle 时的用户可见错误"""


def _extract_args_after_pk(msg: str) -> str:
    """剥离 ``老婆 PK`` 前缀，返回剩余 args 文本。"""
    rest = (msg or "").strip()
    for prefix in ("老婆PK", "老婆 PK"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):].strip()
            break
    return rest


def _has_legacy_pk_indices(args: str) -> bool:
    """args 中是否含 1～2 个数字（推测为 1v1 编号）。

    关键：QQ @mention 会以 ``[At:QQ]`` 或 ``@QQ`` 形式出现在 message_str 中，
    其中的 QQ 号（9~10 位数字）绝不能误判为老婆编号。
    方案：只检查：a) 小数值（≤ 持有上限 30）且 b) 不在 @ 标记内。
    """
    if not args:
        return False
    # 排除 @mention（QQ 号）
    clean = re.sub(r"\[At:\d+\]", "", args)  # [At:QQ]
    clean = re.sub(r"@\d+", "", clean)  # @QQ
    clean = clean.strip()
    if not clean:
        return False
    nums = re.findall(r"\b(\d+)\b", clean)
    if not nums:
        return False
    # 1 个或 2 个数字，且都是小数值（≤ 30，合理的老婆编号范围）
    if len(nums) > 2:
        return False
    return all(int(n) <= 30 for n in nums)


def _resolve_target(
    event: AstrMessageEvent, ctx: CommandContext, gid: str
) -> Optional[str]:
    """解析 PK 目标。"""
    rest = _extract_args_after_pk(event.message_str or "")
    tid = parse_at_target(event)
    if not tid:
        parts = rest.split(maxsplit=1)
        target_nick = parts[0].strip() if parts else ""
        if target_nick:
            tid = find_uid_by_owner_nick(ctx, gid, target_nick)
    return tid


def _construct_battle(
    ctx: CommandContext,
    gid: str,
    atk_uid: str,
    atk_nick: str,
    def_uid: str,
    def_nick: str,
) -> tuple:
    """构造双方编队 + PkBattle。失败抛 ``_PkBuildError``（用户可见提示）。

    Returns
    -------
    (battle, atk_used_default, def_used_default)
        ``*_used_default`` = 该方用了 holdings[:N] 兜底（用于群播报"系统临时用默认编队"）
    """
    ownership_store = OwnershipStore(ctx.paths, gid)
    profile_store = ProfileStore(ctx.paths, gid)
    wives_store = WivesMasterStore(ctx.paths)

    ownerships = ownership_store.load_all()
    profiles = profile_store.load_all()
    wives = wives_store.load_all()

    atk_formation, atk_used_default = _build_formation(
        ctx, atk_uid, ownerships, profiles, wives,
    )
    def_formation, def_used_default = _build_formation(
        ctx, def_uid, ownerships, profiles, wives,
    )

    if not atk_formation:
        raise _PkBuildError(f"{atk_nick}，你没有老婆，先去抽一个吧~")
    if not def_formation:
        raise _PkBuildError(f"{def_nick}，对方还没有老婆~")

    battle_id = f"b-{int(now_ts() * 1000)}-{random.randrange(1000, 9999)}"
    atk_status_layers = [BattleStatusLayer() for _ in atk_formation]
    def_status_layers = [BattleStatusLayer() for _ in def_formation]

    battle = PkBattle(
        gid=gid,
        battle_id=battle_id,
        atk_uid=atk_uid, atk_nick=atk_nick,
        def_uid=def_uid, def_nick=def_nick,
        atk_formation=atk_formation,
        def_formation=def_formation,
        atk_status_layers=atk_status_layers,
        def_status_layers=def_status_layers,
        turn_idx=0,
        active_idx=(1, 1),
        rng_seed=now_ts(),
        status="active",
    )
    return battle, atk_used_default, def_used_default


def _build_formation(
    ctx: CommandContext,
    uid: str,
    ownerships: list,
    profiles: dict,
    wives: dict,
) -> tuple:
    """为单个用户构造 FormationMember 列表。

    * 有 profile.formation → 严格按用户指定顺序
    * 否则 → holdings 前 N 个（N = min(持有数, 4)）
    """
    ownership_store = OwnershipStore(ctx.paths, "")

    # 找用户的主档案
    profile = profiles.get(uid)
    formation_wids = list(profile.formation) if profile and profile.formation else []

    used_default = False
    if not formation_wids:
        used_default = True
        my_wives = [o for o in ownerships if o.uid == uid]
        take = min(len(my_wives), 4)
        formation_wids = [o.wid for o in my_wives[:take]]

    formation: List[FormationMember] = []
    for pos, wid in enumerate(formation_wids, start=1):
        ow = next((o for o in ownerships if o.wid == wid and o.uid == uid), None)
        if ow is None:
            continue
        wife_meta = wives.get(wid)
        if wife_meta is None:
            continue
        element = derive_element(wife_meta.base_stats)
        modifiers = compute_combined_modifiers(wife_meta.rarity, element)
        # 取第一个 modifier_id 作为 passive_id（如有）
        passive_id = ""
        if modifiers:
            passive_id = ", ".join(sorted(modifiers.keys()))

        formation.append(
            FormationMember(
                wid=wid,
                pos=pos,
                nickname=wife_meta.chara or wife_meta.img or "老婆",
                rarity=wife_meta.rarity,
                element=element,
                base_atk=wife_meta.base_stats.atk,
                base_def=wife_meta.base_stats.defense,
                base_hp=wife_meta.base_stats.hp,
                intimacy=ow.intimacy,
                is_locked=ow.is_locked,
                current_hp=wife_meta.base_stats.hp,
                is_alive=True,
                is_active=(pos == 1),
                kills=0, damage_dealt=0, damage_taken=0,
                passive_id=passive_id,
                work_mode=ow.work_mode if ow.is_working else "",
            )
        )

    return formation, used_default
