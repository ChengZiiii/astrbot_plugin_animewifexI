"""v3 接力战 · 战斗引擎：速度判定 + 伤害公式（13 乘数）。

对应 spec 章节：

* ``v3_接力战_主线.md §S6.1`` —— 速度判定公式（双层被动 + 锁定扣速 + 狂暴扣速）。
* ``v3_接力战_主线.md §S6.2`` —— 伤害公式（13 个乘数，顺序应用）。
* ``v3_接力战_主线.md §S6.3`` —— 死亡换人（移到 B.4）。

设计要点：

* 所有随机调用都走注入的 ``rng``，测试可固定 seed 复现；
* ``PkV2Defaults`` 集中保存 spec §S10 的所有魔法数字（Phase C 迁入 PluginConfig）；
* 不依赖 astrbot —— 这是纯算法层。

NOTE: 这里**暂不**应用状态层（qi_po / weak_point / bloodlust / frenzy），
那些由 B.3 的 ``accumulate_status_layers`` 在战斗流程里更新状态后，
这里只读取 ``status: BattleStatusLayer`` 字段。早期 B.2 阶段 ``status``
可以是默认值（qi_po=0, bloodlust=0, frenzy=False）—— B.3 之后才接进伤害公式。
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, Optional

from ..models.pk_battle import BattleStatusLayer, FormationMember, PkBattle

__all__ = [
    "PkV2Defaults",
    "calc_speed",
    "pick_first_striker",
    "calc_raw_damage",
    "on_hit_apply_layers",
    "accumulate_status_layers",
    "swap_if_dead",
    "do_turn",
    "ELEMENT_ADVANTAGE_MAP",
]


# ============== 常量（spec §S10） ==============


class PkV2Defaults:
    """v3 接力战常量。Phase C 接入 PluginConfig 后可被覆盖。"""

    # 战斗节奏
    MAX_TURNS = 12

    # 命中 / 暴击 / 浮动
    HIT_RATE = 0.90
    CRIT_RATE_BASE = 0.10
    CRIT_MULT = 1.50
    JITTER = 0.20  # ±20%

    # 双层被动（来自 pk_v2_passives）
    POWER_ATK_MULT = 1.15        # 力量 atk ×1.15
    AGILITY_SPEED_MULT = 1.10    # 敏捷 speed ×1.10
    AGILITY_DODGE_RATE = 0.05    # 敏捷 dodge +5%（暂未接线，备用）
    INTELLECT_CRIT_RATE = 0.05   # 智力 crit +5%
    INTELLECT_TAKEN_CRIT_MULT = 0.85  # 智力受暴 -15%

    # 元素克制（深化）
    ELEMENT_ADVANTAGE = 1.30
    ELEMENT_DISADVANTAGE = 0.75

    # 状态层
    QI_PO_MAX = 5
    QI_PO_PER_LAYER = 0.03        # 每层 +3% atk
    WEAK_POINT_MAX = 3
    WEAK_POINT_PER_LAYER = 0.05   # 每层 +5% 受伤
    BLOODLUST_LV1_TURN = 5
    BLOODLUST_LV1_ATK = 0.10
    BLOODLUST_LV2_TURN = 8
    BLOODLUST_LV2_ATK = 0.15
    FRENZY_HP_THRESHOLD = 0.30
    FRENZY_ATK = 0.25
    FRENZY_SPEED_PENALTY = 0.75

    # 锁定 / 减伤
    LOCKED_POWER_PENALTY = 0.85    # 锁定老婆 PK 战力 ×0.85
    SR_DAMAGE_REDUCE = 0.90         # SR 被 SSR/SR 攻击时受击 -10%

    # 打工惩罚
    WORK_MULT_NORMAL = 0.85
    WORK_MULT_OVERTIME = 0.75
    WORK_MULT_EXPEDITION = 0.65

    # N 卡连击
    N_COMBO_CHANCE = 0.25


# 元素克制表（按 spec §S3.6：力量 → 敏捷 → 智力 → 力量）
ELEMENT_ADVANTAGE_MAP: Dict[tuple, float] = {
    ("力量", "敏捷"): PkV2Defaults.ELEMENT_ADVANTAGE,
    ("敏捷", "智力"): PkV2Defaults.ELEMENT_ADVANTAGE,
    ("智力", "力量"): PkV2Defaults.ELEMENT_ADVANTAGE,
    # 反向（被克制）
    ("敏捷", "力量"): PkV2Defaults.ELEMENT_DISADVANTAGE,
    ("智力", "敏捷"): PkV2Defaults.ELEMENT_DISADVANTAGE,
    ("力量", "智力"): PkV2Defaults.ELEMENT_DISADVANTAGE,
}


# ============== 速度判定（spec §S6.1） ==============


def calc_speed(
    member: FormationMember,
    status: BattleStatusLayer,
    rng: Optional[random.Random] = None,
) -> int:
    """本回合在场老婆的速度。

    叠加顺序（spec §S6.1）：
      1) 基础速度 = atk × 0.3 + hp × 0.2
      2) R 卡被动：speed ×1.10
      3) 敏捷元素被动：speed ×1.10
      4) 锁定老婆：speed ×0.85
      5) 狂暴状态：speed ×0.75

    ``rng`` 在此函数内未使用（速度公式本身无随机），保留参数为统一签名。
    """
    spd = int(member.base_atk * 0.3 + member.base_hp * 0.2)

    if member.rarity == "R":
        spd = int(spd * PkV2Defaults.AGILITY_SPEED_MULT)
    if member.element == "敏捷":
        spd = int(spd * PkV2Defaults.AGILITY_SPEED_MULT)
    if member.is_locked:
        spd = int(spd * PkV2Defaults.LOCKED_POWER_PENALTY)
    if status.frenzy:
        spd = int(spd * PkV2Defaults.FRENZY_SPEED_PENALTY)
    return spd


def pick_first_striker(
    atk_member: FormationMember,
    df_member: FormationMember,
    atk_status: BattleStatusLayer,
    df_status: BattleStatusLayer,
    rng: random.Random,
) -> str:
    """速度判定后决定先手方。

    * ``sa > sd`` → ``"atk"``（攻方先手）
    * ``sd > sa`` → ``"def"``（守方先手）
    * 平速度 → 50/50 随机（用 ``rng`` 保证公平 + 可复现）
    """
    sa = calc_speed(atk_member, atk_status, rng=rng)
    sd = calc_speed(df_member, df_status, rng=rng)
    if sa > sd:
        return "atk"
    if sd > sa:
        return "def"
    return "atk" if rng.random() < 0.5 else "def"


# ============== 伤害公式（spec §S6.2 · 13 乘数） ==============


def calc_raw_damage(
    attacker: FormationMember,
    defender: FormationMember,
    atk_status: BattleStatusLayer,
    df_status: BattleStatusLayer,
    turn_idx: int,
    rng: random.Random,
    cfg: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """严格按 spec §S6.2 顺序应用 13 个乘数，返回伤害结算 dict。

    返回值（dict）：

    * ``hit``: 是否命中（90%）
    * ``dmg``: 最终伤害（至少 1，未命中时 0）
    * ``crit``: 是否暴击
    * ``combo``: 是否触发连击（N 卡专属，**B.2 阶段先返回 False**，B.4 再接线）
    * ``jitter``: 实际应用的浮动系数（用于调试）
    * ``multipliers``: 各乘数明细（用于消息模板 / 调试）

    参数：

    * ``cfg`` —— 预留配置注入。``None`` 时用 ``PkV2Defaults``。Phase C 会传入
      ``PluginConfig`` 的 ``pk_v2_*`` 字段。
    """
    cfg = cfg if cfg is not None else _default_cfg()
    hit_rate = float(cfg.get("hit_rate", PkV2Defaults.HIT_RATE))
    crit_rate_base = float(cfg.get("crit_rate", PkV2Defaults.CRIT_RATE_BASE))
    crit_mult_base = float(cfg.get("crit_mult", PkV2Defaults.CRIT_MULT))
    jitter_amp = float(cfg.get("jitter", PkV2Defaults.JITTER))

    # === 1. 命中 90% ===
    if rng.random() > hit_rate:
        return {
            "hit": False,
            "dmg": 0,
            "crit": False,
            "combo": False,
            "jitter": 1.0,
            "multipliers": {},
        }

    # === 2. 暴击率（基础 + SSR 被动 + 智力被动）===
    crit_rate = crit_rate_base
    if attacker.rarity == "SSR":
        crit_rate += 0.10  # SSR 被动：暴击 +10%
    if attacker.element == "智力":
        crit_rate += PkV2Defaults.INTELLECT_CRIT_RATE  # 智力被动：暴击 +5%
    is_crit = rng.random() < crit_rate

    # === 3. 暴击倍率（智力受暴 -15%）===
    if is_crit:
        crit_mult = crit_mult_base
        if defender.element == "智力":
            crit_mult *= PkV2Defaults.INTELLECT_TAKEN_CRIT_MULT
    else:
        crit_mult = 1.0

    # === 4. 元素克制倍率（深化 1.30 / 0.75）===
    element_mult = ELEMENT_ADVANTAGE_MAP.get(
        (attacker.element, defender.element), 1.0
    )

    # === 5. 攻击方 atk 倍率（力量元素 + 狂暴）===
    atk_bonus_total = 0.0
    if attacker.element == "力量":
        atk_bonus_total += (PkV2Defaults.POWER_ATK_MULT - 1.0)
    if atk_status.frenzy:
        atk_bonus_total += PkV2Defaults.FRENZY_ATK

    # === 6. 状态层（气魄 + 血性）作用于攻击方 atk ===
    qi_po_bonus = min(atk_status.qi_po, PkV2Defaults.QI_PO_MAX) * PkV2Defaults.QI_PO_PER_LAYER
    if turn_idx >= PkV2Defaults.BLOODLUST_LV2_TURN:
        bloodlust_bonus = PkV2Defaults.BLOODLUST_LV2_ATK
    elif turn_idx >= PkV2Defaults.BLOODLUST_LV1_TURN:
        bloodlust_bonus = PkV2Defaults.BLOODLUST_LV1_ATK
    else:
        bloodlust_bonus = 0.0

    atk_layer_mult = 1.0 + qi_po_bonus + bloodlust_bonus

    # === 7. 防御方弱点层（受击 +5%/层）===
    weak_point_mult = 1.0 + min(df_status.weak_point, PkV2Defaults.WEAK_POINT_MAX) * PkV2Defaults.WEAK_POINT_PER_LAYER

    # === 8. 打工惩罚（沿用 Phase 4）===
    work_mult = 1.0  # v3 接力战中"打工中的老婆"按 B.3 状态层处理；这里默认无惩罚
    # 注：spec §S6.2 公式保留 work_mult 占位，本期暂取 1.0
    # （编队开始时老婆在打工会被剔除，Phase C 接入后由调用方传入 work_mode）

    # === 9. 亲密加成 ===
    intimacy_mult = 1 + attacker.intimacy / 500.0

    # === 10. 锁定惩罚 ===
    lock_atk_mult = PkV2Defaults.LOCKED_POWER_PENALTY if attacker.is_locked else 1.0

    # === 11. SR 减伤（被 SSR/SR 攻击时 -10%）===
    if (
        defender.rarity == "SR"
        and attacker.rarity in ("SSR", "SR")
    ):
        damage_taken_mult = PkV2Defaults.SR_DAMAGE_REDUCE
    else:
        damage_taken_mult = 1.0

    # === 12. 伤害合成 ===
    atk_base = attacker.base_atk * (1.0 + atk_bonus_total) + attacker.base_def * 0.3
    raw = (
        atk_base
        * atk_layer_mult
        * crit_mult
        * element_mult
        * work_mult
        * intimacy_mult
        * lock_atk_mult
        * damage_taken_mult
        * weak_point_mult
    )

    # === 13. 浮动 ±20% ===
    jitter = (1.0 - jitter_amp) + rng.random() * (2 * jitter_amp)
    dmg = max(1, int(raw * jitter))

    return {
        "hit": True,
        "dmg": dmg,
        "crit": is_crit,
        "combo": False,  # B.4 接线
        "jitter": jitter,
        "multipliers": {
            "atk_bonus_total": atk_bonus_total,
            "atk_layer_mult": atk_layer_mult,
            "qi_po_bonus": qi_po_bonus,
            "bloodlust_bonus": bloodlust_bonus,
            "crit_rate": crit_rate,
            "crit_mult": crit_mult,
            "element_mult": element_mult,
            "work_mult": work_mult,
            "intimacy_mult": intimacy_mult,
            "lock_atk_mult": lock_atk_mult,
            "damage_taken_mult": damage_taken_mult,
            "weak_point_mult": weak_point_mult,
        },
    }


def _default_cfg() -> Dict[str, Any]:
    """默认配置（Phase C 接入 PluginConfig 后此函数被替代）"""
    return {
        "hit_rate": PkV2Defaults.HIT_RATE,
        "crit_rate": PkV2Defaults.CRIT_RATE_BASE,
        "crit_mult": PkV2Defaults.CRIT_MULT,
        "jitter": PkV2Defaults.JITTER,
    }


# ============== 状态层累积（spec §S6.5） ==============


def on_hit_apply_layers(
    attacker_status: BattleStatusLayer,
    defender_status: BattleStatusLayer,
    is_attacker_hit: bool = True,
) -> None:
    """每次攻击结算后调用：攻方+1 气魄、守方+1 弱点（命中时）。

    参数：

    * ``attacker_status`` / ``defender_status`` —— 当前攻击方向的两方状态层
    * ``is_attacker_hit`` —— 攻击是否命中（未命中不累积）
    """
    if not is_attacker_hit:
        return
    if attacker_status.qi_po < PkV2Defaults.QI_PO_MAX:
        attacker_status.qi_po += 1
    if defender_status.weak_point < PkV2Defaults.WEAK_POINT_MAX:
        defender_status.weak_point += 1


def accumulate_status_layers(
    member: FormationMember,
    status: BattleStatusLayer,
    turn_idx: int,
) -> None:
    """每回合结束后调用，更新血性 / 狂暴。

    参数：

    * ``member`` —— 当前在场老婆（用于读 current_hp / base_hp 判定狂暴）
    * ``status`` —— 该老婆的状态层（in-place 修改）
    * ``turn_idx`` —— 0-based 回合编号（spec §S6.4 / §S6.5）

    注：气魄 / 弱点 不在这里处理（由 ``on_hit_apply_layers`` 实时维护）。
    """
    # 血性：5 / 8 回合激活
    if turn_idx >= PkV2Defaults.BLOODLUST_LV2_TURN:
        status.bloodlust = 2
    elif turn_idx >= PkV2Defaults.BLOODLUST_LV1_TURN:
        status.bloodlust = 1
    else:
        status.bloodlust = 0

    # 狂暴：当前 HP < 30% 时激活（atk +25% / speed -25%）
    if member.base_hp > 0:
        hp_ratio = member.current_hp / member.base_hp
        status.frenzy = hp_ratio < PkV2Defaults.FRENZY_HP_THRESHOLD
    else:
        # 防御性：base_hp=0 时不激活
        status.frenzy = False


# ============== 死亡换人（spec §S6.3） ==============


def swap_if_dead(battle: "PkBattle", side: str) -> bool:
    """如果 ``side`` 当前 active 成员已死，标记下一个存活的为 active。

    参数：

    * ``side`` —— ``"atk"`` 或 ``"def"``

    返回：是否实际换了人（False = 当前 active 还活着 / 无下一个）
    """
    if side == "atk":
        formation = battle.atk_formation
        idx_pos = 0
    elif side == "def":
        formation = battle.def_formation
        idx_pos = 1
    else:
        raise ValueError(f"side must be 'atk' or 'def', got {side!r}")

    if not formation:
        return False

    active_pos = battle.active_idx[idx_pos]  # 1-based
    active_idx_zero = active_pos - 1
    if active_idx_zero < 0 or active_idx_zero >= len(formation):
        return False

    current = formation[active_idx_zero]
    if current.is_alive:
        # 当前还活着 → 不换
        return False

    # 找下一个存活的（从 active_pos+1 开始，到队尾）
    next_idx = None
    for i in range(active_pos, len(formation)):
        if formation[i].is_alive:
            next_idx = i
            break

    if next_idx is None:
        # 没有下一个：调用方负责判胜负
        return False

    # 标记新的 active
    formation[next_idx].is_active = True
    formation[active_idx_zero].is_active = False
    new_active_idx = list(battle.active_idx)
    new_active_idx[idx_pos] = next_idx + 1  # 转回 1-based
    battle.active_idx = (new_active_idx[0], new_active_idx[1])
    return True


# ============== 单回合 do_turn（spec §S6.4） ==============


def do_turn(
    battle: "PkBattle",
    turn_idx: int,
    rng: random.Random,
) -> Dict[str, Any]:
    """单回合完整流程（spec §S6.4）。

    1. 速度判定
    2. 先手攻击（含 on_hit_apply_layers）
    3. 后手反击（如存活）
    4. 死亡换人（双方）
    5. 状态层累积（双方 active）
    6. 检查胜负（一方无存活则结束）

    返回 dict：

    * ``turn_finished`` —— bool，本回合正常推进完
    * ``battle_ended`` —— bool，是否本回合后战斗结束
    * ``winner_uid`` —— 战斗结束时，胜方 uid
    * ``end_reason`` —— ``"all_dead"`` / ``""``
    * ``atk_swapped_to`` / ``def_swapped_to`` —— 死亡换人后的 active pos（1-based）
    * ``first_striker`` —— ``"atk"`` / ``"def"``
    * ``attack_events`` —— list of {``side``, ``hit``, ``dmg``, ``crit``, ``combo``}
    """
    atk_pos = battle.active_idx[0]
    df_pos = battle.active_idx[1]
    if atk_pos < 1 or atk_pos > len(battle.atk_formation):
        return {"turn_finished": False, "battle_ended": True, "winner_uid": battle.def_uid, "end_reason": "all_dead"}
    if df_pos < 1 or df_pos > len(battle.def_formation):
        return {"turn_finished": False, "battle_ended": True, "winner_uid": battle.atk_uid, "end_reason": "all_dead"}

    atk_member = battle.atk_formation[atk_pos - 1]
    df_member = battle.def_formation[df_pos - 1]
    atk_status = battle.atk_status_layers[atk_pos - 1]
    df_status = battle.def_status_layers[df_pos - 1]

    attack_events: list = []

    # === 1. 速度判定 ===
    first = pick_first_striker(atk_member, df_member, atk_status, df_status, rng)

    # === 2. 先手攻击 ===
    if first == "atk":
        result = calc_raw_damage(atk_member, df_member, atk_status, df_status, turn_idx, rng)
        attack_events.append({"side": "atk", **result})
        _apply_attack_result(atk_member, df_member, atk_status, df_status, result)
        # === 3. 后手反击（如存活）===
        if df_member.is_alive:
            result2 = calc_raw_damage(df_member, atk_member, df_status, atk_status, turn_idx, rng)
            attack_events.append({"side": "def", **result2})
            _apply_attack_result(df_member, atk_member, df_status, atk_status, result2)
    else:
        # def 先手
        result = calc_raw_damage(df_member, atk_member, df_status, atk_status, turn_idx, rng)
        attack_events.append({"side": "def", **result})
        _apply_attack_result(df_member, atk_member, df_status, atk_status, result)
        if atk_member.is_alive:
            result2 = calc_raw_damage(atk_member, df_member, atk_status, df_status, turn_idx, rng)
            attack_events.append({"side": "atk", **result2})
            _apply_attack_result(atk_member, df_member, atk_status, df_status, result2)

    # === 4. 死亡换人 ===
    swap_if_dead(battle, "atk")
    swap_if_dead(battle, "def")

    # === 5. 状态层累积（双方当前 active） ===
    # 注意：换人后 active 可能已变；这里对换人后的 active 应用 turn-end 状态
    atk_pos_after = battle.active_idx[0]
    df_pos_after = battle.active_idx[1]
    if 1 <= atk_pos_after <= len(battle.atk_formation):
        accumulate_status_layers(
            battle.atk_formation[atk_pos_after - 1],
            battle.atk_status_layers[atk_pos_after - 1],
            turn_idx,
        )
    if 1 <= df_pos_after <= len(battle.def_formation):
        accumulate_status_layers(
            battle.def_formation[df_pos_after - 1],
            battle.def_status_layers[df_pos_after - 1],
            turn_idx,
        )

    # === 6. 检查胜负 ===
    atk_any_alive = any(m.is_alive for m in battle.atk_formation)
    df_any_alive = any(m.is_alive for m in battle.def_formation)

    battle_ended = False
    winner_uid = ""
    end_reason = ""
    if not atk_any_alive and not df_any_alive:
        # 双方同归于尽：判防守方胜（spec §S6.3 默认）
        battle_ended = True
        winner_uid = battle.def_uid
        end_reason = "all_dead"
    elif not atk_any_alive:
        battle_ended = True
        winner_uid = battle.def_uid
        end_reason = "all_dead"
    elif not df_any_alive:
        battle_ended = True
        winner_uid = battle.atk_uid
        end_reason = "all_dead"

    return {
        "turn_finished": True,
        "battle_ended": battle_ended,
        "winner_uid": winner_uid,
        "end_reason": end_reason,
        "first_striker": first,
        "atk_swapped_to": battle.active_idx[0],
        "def_swapped_to": battle.active_idx[1],
        "attack_events": attack_events,
    }


def _apply_attack_result(
    attacker: FormationMember,
    defender: FormationMember,
    attacker_status: BattleStatusLayer,
    defender_status: BattleStatusLayer,
    result: Dict[str, Any],
) -> None:
    """把单次攻击的结果应用到双方 HP + 状态层。

    * 命中 → 扣 HP；HP ≤ 0 → 标记 is_alive=False
    * 命中 → 累积 qi_po / weak_point
    * 击杀 → 累 attacker.kills
    * 双方各自累 damage_dealt / damage_taken
    """
    if not result.get("hit", False):
        return

    dmg = int(result.get("dmg", 0) or 0)
    defender.current_hp = max(0, defender.current_hp - dmg)
    if defender.current_hp <= 0:
        defender.is_alive = False
        attacker.kills += 1

    attacker.damage_dealt += dmg
    defender.damage_taken += dmg

    # 状态层累积（气魄 / 弱点）
    on_hit_apply_layers(attacker_status, defender_status, is_attacker_hit=True)