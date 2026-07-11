"""v3 接力战 · 战斗消息模板渲染。

对应 spec `v3_接力战_主线.md` §S8.1～§S8.4：启动贴 / 回合贴 / 死亡贴 / 结算贴。

设计原则：

* **纯函数**：不读文件、不调网络、不依赖 astrbot；输入全部参数化，便于单元测试。
* **签名严格按 spec**：每个函数的参数列表与编排器要求一致。
* **对 None / 缺失字段做防御**：比如结算贴的 formations_hero 中可能有人未出战
  （``exited_in_battle=False``），按模板跳过。
* **emoji 选择靠 spec 字面**：🐱/🐰/💀/🔥/📌/📋/⚔️ 等。

NOTE：模板输出**不依赖** :class:`BattleStatusLayer` 的具体字段名，只看它
自己的 ``qi_po`` / ``weak_point`` / ``bloodlust`` / ``frenzy``。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from ..models.pk_battle import BattleStatusLayer, FormationMember

__all__ = [
    "render_init_message",
    "render_turn_message",
    "render_death_message",
    "render_settle_message",
]


# ============== helpers ==============


_SIDE_EMOJI = {"atk": "🐱", "def": "🐰"}
_RARITY_ORDER = {"SSR": 4, "SR": 3, "R": 2, "N": 1}


def _format_power(formation: Sequence[FormationMember]) -> int:
    """简易战力 = ATK + DEF + HP × 0.5（与 PkService._calc_power 保持一致口径）。

    注：完整 PkService 战力还要乘 intimacy / work / element，本消息只展示
    **估算** 的"⚡ 战力"——不是战斗公式用的精确值，避免误用经济口径。
    """
    total = 0.0
    for m in formation:
        total += m.base_atk + m.base_def + m.base_hp * 0.5
    return int(total)


def _format_member_line(
    m: FormationMember,
    *,
    owner_emoji: str = "  ",
    default_tag: bool = False,
) -> str:
    """编队里单个老婆的单行描述（spec §S8.1）。"""
    pos = f"[{m.pos}]"
    nick = m.nickname or "?"
    rarity = m.rarity or "?"
    element = m.element or "?"
    intimacy = m.intimacy if m.intimacy else 0
    hp = f"Hp {m.current_hp}/{m.base_hp}" if m.base_hp else f"Hp {m.current_hp}"
    default_suffix = "  [未设置编队，使用默认]" if default_tag else ""
    lock_suffix = " 🔒" if m.is_locked else ""
    return (
        f"  {pos} {owner_emoji} {nick} [{rarity} ❤️ {element}] "
        f"❤️{intimacy}  ❤️{hp}{lock_suffix}{default_suffix}"
    )


def _format_alive_count(
    formation: Sequence[FormationMember],
) -> str:
    """存活列表：❤️=满血 / 🩸=已受伤 / 💀=已阵亡"""
    parts: List[str] = []
    for m in formation:
        if not m.is_alive:
            parts.append(f"{m.nickname}💀")
        elif m.current_hp < m.base_hp:
            parts.append(f"{m.nickname}🩸")
        else:
            parts.append(f"{m.nickname}❤️")
    return " ".join(parts) if parts else "(无)"


def _format_status_block(
    member: FormationMember,
    status: BattleStatusLayer,
    label: str,
) -> str:
    """状态层一行（spec §S8.2 "🔥 状态层"）。"""
    qi_po_pct = min(status.qi_po, 5) * 3
    qi_str = f"气魄 [{status.qi_po}/5 +{qi_po_pct}%]"
    wp_str = (
        f"弱点 [{status.weak_point}/3 +{status.weak_point * 5}%]"
        if status.weak_point > 0
        else "弱点 [0/3 +0%]"
    )
    if status.bloodlust >= 2:
        bloodlust_str = "血性Lv2 [+15%]"
    elif status.bloodlust >= 1:
        bloodlust_str = "血性Lv1 [+10%]"
    else:
        bloodlust_str = "血性 -"
    if member.base_hp > 0:
        hp_pct = int(member.current_hp * 100 / member.base_hp)
    else:
        hp_pct = 0
    frenzy_str = (
        f"狂暴 ✅ (HP {hp_pct}%)" if status.frenzy else f"狂暴 ❌ (HP {hp_pct}%)"
    )
    return (
        f"  {label}·{member.nickname}：{qi_str} {wp_str} "
        f"{bloodlust_str} {frenzy_str}"
    )


# ============== §S8.1 启动贴 ==============


def render_init_message(
    atk_formation: Sequence[FormationMember],
    def_formation: Sequence[FormationMember],
    atk_uid: str,
    atk_nick: str,
    def_uid: str,
    def_nick: str,
    atk_used_default: bool = False,
    def_used_default: bool = False,
) -> str:
    """启动贴：双方编队 + 战力 + 规则提示。"""
    sep = "═" * 30

    atk_lines: List[str] = []
    for m in atk_formation:
        atk_lines.append(_format_member_line(m, default_tag=atk_used_default))
    atk_lines.append(f"  ⚡ 战力：{_format_power(atk_formation)}")

    def_lines: List[str] = []
    for m in def_formation:
        def_lines.append(_format_member_line(m, default_tag=def_used_default))
    def_lines.append(f"  ⚡ 战力：{_format_power(def_formation)}")

    parts: List[str] = [
        sep,
        "⚔️ 4v4 接力战即将开始！",
        sep,
        "",
        f"🔴 攻方 @{atk_nick}",
        *atk_lines,
        "",
        f"🔵 守方 @{def_nick}",
        *def_lines,
        "",
        "📌 规则：速度先手，每回合结束自动换人",
        sep,
        "⚠️ 提示：使用 `老婆 编队 1 2 3 4` 来自定义你的出战顺序",
        sep,
    ]
    return "\n".join(parts)


# ============== §S8.2 回合贴 ==============


def render_turn_message(
    turn_idx: int,
    atk_member: FormationMember,
    df_member: FormationMember,
    atk_status: BattleStatusLayer,
    df_status: BattleStatusLayer,
    attack_results: Sequence[dict],
) -> str:
    """回合贴：先手 / 反击 / 状态层 / 存活。"""
    sep = "═" * 18
    lines: List[str] = [f"{sep} 第 {turn_idx} 回合 {sep}"]

    # 第一攻击 + 反击分别对应两条子块
    atk_event = next(
        (e for e in attack_results if e.get("side") == "atk"),
        {"side": "atk", "hit": False, "dmg": 0, "crit": False, "combo": False},
    )
    df_event = next(
        (e for e in attack_results if e.get("side") == "def"),
        {"side": "def", "hit": False, "dmg": 0, "crit": False, "combo": False},
    )
    # 先手方 = 出 attack_results 第一条
    first_event = attack_results[0] if attack_results else atk_event
    first_side = first_event.get("side", "atk")
    second_side = "def" if first_side == "atk" else "atk"

    lines.extend(_render_side_block(first_side, atk_member, df_member, atk_status, df_status, first_event, role_label="先手"))
    lines.append("")
    second_event = next(
        (e for e in attack_results if e.get("side") == second_side),
        None,
    )
    if second_event:
        lines.extend(_render_side_block(second_side, atk_member, df_member, atk_status, df_status, second_event, role_label="反击"))
        lines.append("")

    # 状态层
    lines.append("🔥 状态层：")
    lines.append(_format_status_block(atk_member, atk_status, "攻"))
    lines.append(_format_status_block(df_member, df_status, "守"))
    lines.append("")

    # 存活列表（仅显示当前在场）
    lines.append(
        f"📋 攻方存活: {_format_alive_count([atk_member])} "
        f"| 守方存活: {_format_alive_count([df_member])}"
    )

    lines.append("═" * 60)
    return "\n".join(lines)


def _render_side_block(
    side: str,
    atk_member: FormationMember,
    df_member: FormationMember,
    atk_status: BattleStatusLayer,
    df_status: BattleStatusLayer,
    event: dict,
    role_label: str = "先手",
) -> List[str]:
    """回合贴里单侧（先手 or 反击）的小块描述。

    ``role_label`` 由调用方传入 ``"先手"`` 或 ``"反击"`` ——
    .. 之前写死 ``side=="def"`` → 反击，但 def 也可以先手（speed 更高时）。
    """
    if side == "atk":
        attacker = atk_member
        defender = df_member
        attacker_status = atk_status
    else:
        attacker = df_member
        defender = atk_member
        attacker_status = df_status
    role = role_label

    emoji = "🐱" if side == "atk" else "🐰"
    # 计算速度（含双层被动 + 狂暴扣速）
    from .pk_v2_battle import calc_speed
    speed = calc_speed(attacker, attacker_status, rng=None)
    element_relationship = _element_relationship_text(attacker.element, defender.element)
    lines: List[str] = [
        f"{emoji} [{side}·{attacker.nickname} {attacker.rarity} ❤️ {attacker.element}·气魄{attacker_status.qi_po}] 速度 {speed} {role}！",
        f"  ├─ 🔮 {element_relationship}",
        f"  ├─ ⚔️ 普通攻击 [{('def' if side == 'atk' else 'atk')}·{defender.nickname} {defender.rarity}]",
    ]
    if not event.get("hit"):
        lines.append("  ├─ ❌ MISS（未命中）")
    else:
        crit_str = " 暴击" if event.get("crit") else ""
        dmg = event.get("dmg", 0)
        lines.append(f"  ├─ 💥 命中！{crit_str}造成 {dmg} 点伤害")
        lines.append(
            f"  └─ ⬆️ 气魄 +1 [{min(attacker_status.qi_po, 5)}/5]"
        )
    return lines


def _element_relationship_text(
    atk_element: str,
    df_element: str,
) -> str:
    """渲染元素克制标签。"""
    if atk_element == df_element:
        return f"同元素 [{atk_element}] ×1.00"
    advantage = {
        ("力量", "敏捷"): "元素克制！[力量 → 敏捷] ×1.30",
        ("敏捷", "智力"): "元素克制！[敏捷 → 智力] ×1.30",
        ("智力", "力量"): "元素克制！[智力 → 力量] ×1.30",
        ("敏捷", "力量"): "元素被克！[敏捷 ← 力量] ×0.75",
        ("智力", "敏捷"): "元素被克！[智力 ← 敏捷] ×0.75",
        ("力量", "智力"): "元素被克！[力量 ← 智力] ×0.75",
    }
    return advantage.get((atk_element, df_element), f"无克制 [{atk_element} vs {df_element}] ×1.00")


# ============== §S8.3 死亡贴 ==============


def render_death_message(
    victim_member: FormationMember,
    next_member: Optional[FormationMember] = None,
    side_char: str = "?",
) -> str:
    """死亡贴：单行倒下 + （可选）接战。

    ``side_char`` 是 ``"攻"`` 或 ``"守"``，默认 ``"?"`` 用于未接线场景。
    """
    lines: List[str] = [
        f"💀 [{_format_member_tag(victim_member, side_char)}] 倒下了！",
    ]
    if next_member is not None:
        lines.append(f"   [{_format_member_tag(next_member, side_char)}] 上场接战！")
    return "\n".join(lines)


def _format_member_tag(m: FormationMember, side_char: str = "?") -> str:
    """简短的 [守·祢豆子 SR ❤️70] 标签。

    Phase 6 寿命标注：
    * 死亡 → ` ☠️` 尾巴
    * 满血 → ` ❤️{lifespan}/{max}` 尾巴
    * 旧数据（lifespan=-1）→ 不加尾巴（向后兼容）
    """
    intimacy = m.intimacy if m.intimacy else 0
    suffix = ""
    if m.is_dead:
        suffix = " ☠️"
    elif m.lifespan >= 0:
        suffix = f" ❤️{m.lifespan}/{m.lifespan_max}"
    return f"{side_char}·{m.nickname} {m.rarity} ❤️{intimacy}{suffix}"


# ============== §S8.4 结算贴 ==============


def render_settle_message(
    winner_uid: str,
    winner_nick: str,
    loser_uid: str,
    loser_nick: str,
    atk_kills: int,
    def_kills: int,
    atk_dmg_total: int,
    def_dmg_total: int,
    reward_winner: int,
    reward_loser: int,
    winner_score_gain: int,
    loser_score_gain: int,
    winner_rank: str,
    loser_rank: str,
    formations_hero: Sequence[Tuple[str, int, bool]],
    target_needs_formation: bool = False,
    is_tie: bool = False,
    atk_total: int = 4,
    def_total: int = 4,
    atk_total_hp: int = 1830,
    def_total_hp: int = 1830,
    atk_nick: str = "",
    def_nick: str = "",
) -> str:
    """结算贴：胜负 + 奖励 + 积分 + 段位 + 英雄一览 + 编队提示。

    Parameters
    ----------
    formations_hero
        形如 ``[(nick, kills, is_winner_team), ...]`` 的列表——每位出场老婆一条。
        ``is_winner_team=False`` 时该成员用"奋勇作战"等中性标签。
    target_needs_formation
        败方是否需要提示设置编队（spec §S8.4 末行）。
    is_tie
        是否平局（双方 +8 币 / +2 分，无胜负）。
    atk_total / def_total
        双方队伍总人数（击破敌将分母，动态）。
    atk_total_hp / def_total_hp
        双方队伍总 HP（己方损耗分母，动态）。
    atk_nick / def_nick
        攻方 / 守方的玩家昵称。平局分支用于渲染"攻方 @xxx / 守方 @xxx"。

    Notes
    -----
    非平局分支用 ``@winner_nick`` / ``@loser_nick`` 标签——不再用 "攻方/守方"
    标签，避免把 QQ uid 误判成 ``"atk"`` 字符串的老 bug。
    """
    sep = "═" * 30

    # 平局分支：用 atk_nick / def_nick 渲染攻方/守方（这两参数在平局中才有意义）
    if is_tie:
        # 平局显示仍然按"攻方/守方"，因为平局没有"胜方"
        atk_label_nick = atk_nick or winner_nick
        def_label_nick = def_nick or loser_nick
        lines: List[str] = [
            sep,
            "🤝 4v4 接力战平局！",
            sep,
            "",
            f"🔴 攻方 @{atk_label_nick}",
            f"  击破敌将：{atk_kills}/{atk_total}",
            f"  己方损耗：{atk_dmg_total}/{atk_total_hp} HP",
            f"  奖励：+{reward_winner} 币 | +{winner_score_gain} PK 积分（{winner_rank}）",
            "",
            f"🔵 守方 @{def_label_nick}",
            f"  击破敌将：{def_kills}/{def_total}",
            f"  己方损耗：{def_dmg_total}/{def_total_hp} HP",
            f"  奖励：+{reward_loser} 币 | +{loser_score_gain} PK 积分（{loser_rank}）",
            "",
        ]
        if formations_hero:
            # 平局也用攻方昵称作为"编队一览"的标题前缀（保持与启动贴的"攻方"指代一致）
            lines.append(f"📢 @{atk_label_nick} 你的编队一览：")
            for nick, kills, in_winner in formations_hero:
                tag = _kill_tag(kills)
                suffix = f"（击杀 {kills}）" if kills > 0 else ""
                lines.append(f"  [✓] {nick} {tag}{suffix}".rstrip())
            lines.append("")
        lines.append(sep)
        return "\n".join(lines)

    # 非平局：用 @winner_nick / @loser_nick 直接打标签（不再用攻守方误判）
    lines = [
        sep,
        "🏆 4v4 接力战结束！",
        sep,
        "",
        f"🏆 胜方 @{winner_nick}",
        f"  击破敌将：{atk_kills}/{atk_total}",
        f"  己方损耗：{atk_dmg_total}/{atk_total_hp} HP",
        f"  奖励：+{reward_winner} 币 | +{winner_score_gain} PK 积分（{winner_rank}）",
        "",
        f"💀 败方 @{loser_nick}",
        f"  击破敌将：{def_kills}/{def_total}",
        f"  己方损耗：{def_dmg_total}/{def_total_hp} HP",
        f"  奖励：+{reward_loser} 币 | +{loser_score_gain} PK 积分（{loser_rank}）",
        "",
    ]

    # 英雄一览：用 winner_nick（玩家昵称），不是 formations_hero[0][0]（老婆名！）
    if formations_hero:
        lines.append(f"📢 @{winner_nick} 你的编队一览：")
        for nick, kills, in_winner in formations_hero:
            tag = _kill_tag(kills)
            suffix = f"（击杀 {kills}）" if kills > 0 else ""
            lines.append(f"  [✓] {nick} {tag}{suffix}".rstrip())
        lines.append("")

    if target_needs_formation:
        lines.append(f"📢 @{loser_nick} 待设置编队：发 `老婆 编队 1 2 3 4`")
        lines.append(sep)
    else:
        lines.append(sep)

    return "\n".join(lines)


def _kill_tag(kills: int) -> str:
    """按击杀数给出英雄标签。"""
    if kills >= 3:
        return "⭐MVP！"
    elif kills >= 2:
        return "⭐立大功！"
    elif kills >= 1:
        return "⭐奋勇作战！"
    return ""
