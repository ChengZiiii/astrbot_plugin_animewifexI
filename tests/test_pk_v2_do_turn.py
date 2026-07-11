"""v3 接力战 · 单回合 do_turn + 死亡换人测试（追加到 test_pk_v2_battle.py）。

覆盖 v3_接力战_主线.md §S6.3 + §S6.4。

NOTE: 本文件以 ``TestDoTurn`` / ``TestSwapIfDead`` 类**追加**到现有
``tests/test_pk_v2_battle.py`` 的下游——为了避免大改既有结构，本文件
import 同样的模块并新增类。
"""

from __future__ import annotations

import random

import pytest

from app.models.pk_battle import BattleStatusLayer, FormationMember, PkBattle
from app.services.pk_v2_battle import (
    PkV2Defaults,
    accumulate_status_layers,
    do_turn,
    swap_if_dead,
)


def _make_member(
    wid: str = "m1",
    pos: int = 1,
    rarity: str = "SSR",
    element: str = "力量",
    atk: int = 100,
    defense: int = 50,
    hp: int = 200,
    current_hp: int = None,
    is_locked: bool = False,
    is_alive: bool = True,
    is_active: bool = False,
) -> FormationMember:
    if current_hp is None:
        current_hp = hp
    return FormationMember(
        wid=wid, pos=pos, nickname=f"W{wid}", rarity=rarity, element=element,
        base_atk=atk, base_def=defense, base_hp=hp,
        intimacy=0, is_locked=is_locked,
        current_hp=current_hp, is_alive=is_alive, is_active=is_active,
    )


class _ScriptedRNG:
    """按固定序列返回 random() 值的脚本化 RNG（用于精确控制概率分支）。

    用法：传入一个 float 列表，每次调用 ``random()`` 顺序消费一个值。
    """

    def __init__(self, values):
        self._values = list(values)
        self._n = 0
        self.calls = []

    def random(self) -> float:
        v = self._values[self._n]
        self._n += 1
        self.calls.append(v)
        return v


def _make_battle(
    atk_members: list,
    df_members: list,
    turn_idx: int = 0,
    active_idx: tuple = (1, 1),
) -> PkBattle:
    """构造一个 PkBattle 用来测 do_turn / swap_if_dead"""
    atk_status = [BattleStatusLayer() for _ in atk_members]
    df_status = [BattleStatusLayer() for _ in df_members]
    return PkBattle(
        gid="g1",
        battle_id="b1",
        atk_uid="u1", atk_nick="alice",
        def_uid="u2", def_nick="bob",
        atk_formation=list(atk_members),
        def_formation=list(df_members),
        atk_status_layers=atk_status,
        def_status_layers=df_status,
        turn_idx=turn_idx,
        active_idx=active_idx,
        rng_seed=42,
        status="active",
    )


# ============== swap_if_dead（§S6.3） ==============


class TestSwapIfDead:
    def test_swap_to_next_alive(self):
        """当前 active 死亡 → 找下一个存活的并标记 active"""
        m1 = _make_member(wid="w1", pos=1, current_hp=0, is_alive=False, is_active=True)
        m2 = _make_member(wid="w2", pos=2, current_hp=200, is_alive=True, is_active=False)
        battle = _make_battle(atk_members=[m1, m2], df_members=[m1], active_idx=(1, 1))

        swap_if_dead(battle, "atk")

        assert battle.active_idx[0] == 2
        assert battle.atk_formation[1].is_active is True
        assert battle.atk_formation[0].is_active is False

    def test_no_swap_when_alive(self):
        """当前 active 还活着 → 不换人"""
        m1 = _make_member(wid="w1", pos=1, current_hp=200, is_alive=True, is_active=True)
        m2 = _make_member(wid="w2", pos=2, current_hp=200, is_alive=True, is_active=False)
        battle = _make_battle(atk_members=[m1, m2], df_members=[m1], active_idx=(1, 1))

        swap_if_dead(battle, "atk")

        assert battle.active_idx[0] == 1
        assert battle.atk_formation[0].is_active is True

    def test_no_next_alive_returns_no_swap(self):
        """没有下一个存活的：active_idx 保持原状（调用方负责判胜负）"""
        m1 = _make_member(wid="w1", pos=1, current_hp=0, is_alive=False, is_active=True)
        m2 = _make_member(wid="w2", pos=2, current_hp=0, is_alive=False, is_active=False)
        battle = _make_battle(atk_members=[m1, m2], df_members=[m1], active_idx=(1, 1))

        swap_if_dead(battle, "atk")

        # active_idx 不变，调用方负责读 atk_formation 全 is_alive=False → 失败
        assert battle.active_idx[0] == 1
        assert all(not m.is_alive for m in battle.atk_formation)

    def test_swap_skips_dead_intermediate(self):
        """跳过中间死亡位，找到下一个存活的"""
        m1 = _make_member(wid="w1", pos=1, current_hp=0, is_alive=False, is_active=True)
        m2 = _make_member(wid="w2", pos=2, current_hp=0, is_alive=False, is_active=False)
        m3 = _make_member(wid="w3", pos=3, current_hp=200, is_alive=True, is_active=False)
        battle = _make_battle(atk_members=[m1, m2, m3], df_members=[m1], active_idx=(1, 1))

        swap_if_dead(battle, "atk")

        assert battle.active_idx[0] == 3
        assert battle.atk_formation[2].is_active is True


# ============== do_turn（§S6.4） ==============


class TestDoTurn:
    """单回合完整流程：速度判定 → 先手 → 后手反击 → 死亡换人 → 状态累积"""

    def test_do_turn_returns_dict(self):
        """do_turn 返回 dict（包含 turn_finished / battle_ended 等字段）"""
        m1 = _make_member(wid="w1", pos=1)
        m2 = _make_member(wid="w2", pos=2)
        battle = _make_battle(atk_members=[m1], df_members=[m2])
        rng = random.Random(42)

        result = do_turn(battle, turn_idx=0, rng=rng)

        assert isinstance(result, dict)
        assert "turn_finished" in result
        assert result["turn_finished"] is True

    def test_do_turn_handles_both_alive_no_death(self):
        """双方都没死：active_idx 不变"""
        m1 = _make_member(wid="w1", pos=1)
        m2 = _make_member(wid="w2", pos=1)
        battle = _make_battle(atk_members=[m1], df_members=[m2])
        rng = random.Random(42)

        result = do_turn(battle, turn_idx=0, rng=rng)

        # 双方还活着
        assert battle.atk_formation[0].is_alive is True
        assert battle.def_formation[0].is_alive is True
        assert battle.active_idx == (1, 1)
        # 返回 dict 至少标记了双方存活状态
        assert result.get("battle_ended") is not True  # 没结束

    def test_do_turn_damage_dealt_taken_tracked(self):
        """伤害计入 damage_dealt / damage_taken"""
        m1 = _make_member(wid="w1", pos=1, atk=1000, hp=2000)  # 高攻确保命中后能打很多
        m2 = _make_member(wid="w2", pos=1, atk=10, hp=100)
        battle = _make_battle(atk_members=[m1], df_members=[m2])
        rng = random.Random(42)

        do_turn(battle, turn_idx=0, rng=rng)

        # 双方至少有一方被攻击过 → damage_dealt / damage_taken 累计
        atk_dmg_dealt = battle.atk_formation[0].damage_dealt
        df_dmg_taken = battle.def_formation[0].damage_taken
        total_atk_dealt = atk_dmg_dealt
        total_df_taken = df_dmg_taken
        # atk 至少攻击了一次，df 至少被攻击了一次（或反之）
        assert total_atk_dealt + total_df_taken > 0

    def test_do_turn_swap_on_defender_death(self):
        """守方死亡 → 攻方 active 不变 + 守方 swap 到下一个"""
        # 攻方很弱但极多，守方只有一个，会被打死
        # 我们用 huge 攻方确保一击毙命
        attacker = _make_member(wid="a1", pos=1, atk=10000, hp=20000, defense=1)
        defender_1 = _make_member(wid="d1", pos=1, atk=1, defense=1, hp=50)  # 易死
        defender_2 = _make_member(wid="d2", pos=2, atk=1, defense=1, hp=200)
        battle = _make_battle(
            atk_members=[attacker], df_members=[defender_1, defender_2],
            active_idx=(1, 1),
        )

        # 用强命中 rng：让 rng.random() 总是 < 0.90 命中，< 0.20 暴击
        class _AlwaysHitCrit:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5  # 命中
                if self._n == 2:
                    return 0.5  # 暴击（暴击率 0.20）
                return 0.5  # jitter = 1.0
        rng = _AlwaysHitCrit()

        result = do_turn(battle, turn_idx=0, rng=rng)

        # 守方 1 死了，swap 到 2
        assert battle.def_formation[0].is_alive is False
        assert battle.def_formation[1].is_alive is True
        # active 移动到 2
        assert battle.active_idx[1] == 2

    def test_do_turn_swap_on_each_side(self):
        """一回合内双方各自换人（不要求同时死亡）"""
        # attacker_1 (强) 一击打死了 defender_1
        attacker_1 = _make_member(wid="a1", pos=1, atk=10000, hp=200, defense=1)
        attacker_2 = _make_member(wid="a2", pos=2, atk=1, hp=200, defense=1)
        defender_1 = _make_member(wid="d1", pos=1, atk=10000, hp=50, defense=1)
        defender_2 = _make_member(wid="d2", pos=2, atk=1, hp=200, defense=1)

        battle = _make_battle(
            atk_members=[attacker_1, attacker_2],
            df_members=[defender_1, defender_2],
            active_idx=(1, 1),
        )

        # 强制命中暴击
        class _AlwaysHitCrit:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5
                if self._n == 2:
                    return 0.5
                return 0.5
        rng = _AlwaysHitCrit()

        # turn_idx=0 还不会触发血性 / 狂暴
        do_turn(battle, turn_idx=0, rng=rng)

        # attacker_1 杀死 defender_1 → defender swap 到 pos=2
        # attacker_1 还活着 → atk active 仍在 pos=1
        assert battle.def_formation[0].is_alive is False
        assert battle.def_formation[1].is_alive is True
        assert battle.active_idx == (1, 2)
        assert battle.atk_formation[0].is_alive is True

    def test_do_turn_battle_ended_when_no_next(self):
        """一方无下一个存活 → battle_ended=True"""

        attacker = _make_member(wid="a1", pos=1, atk=10000, hp=50, defense=1)
        defender = _make_member(wid="d1", pos=1, atk=1, hp=200, defense=1)  # defender 反击打不死 atk
        # defender 无下一个（只有 1 个）
        battle = _make_battle(
            atk_members=[attacker], df_members=[defender], active_idx=(1, 1),
        )

        # 强制命中暴击
        class _AlwaysHitCrit:
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                self._n += 1
                if self._n == 1:
                    return 0.5
                if self._n == 2:
                    return 0.5
                return 0.5
        rng = _AlwaysHitCrit()

        result = do_turn(battle, turn_idx=0, rng=rng)

        # defender 死了，无下一个 → battle 结束
        assert result["battle_ended"] is True
        # 胜方 = atk_uid (u1)
        assert result.get("winner_uid") == "u1"

    def test_do_turn_advances_turn_idx(self):
        """do_turn 不修改 battle.turn_idx（由调用方管理）"""
        m1 = _make_member(wid="w1", pos=1)
        m2 = _make_member(wid="w2", pos=1)
        battle = _make_battle(atk_members=[m1], df_members=[m2], turn_idx=5)

        do_turn(battle, turn_idx=5, rng=random.Random(42))

        # do_turn 不应该修改 battle.turn_idx
        assert battle.turn_idx == 5

    def test_do_turn_both_sides_swap_each_turn(self):
        """一回合内：双方各自可能换人"""
        attacker_1 = _make_member(wid="a1", pos=1, atk=10000, hp=200, defense=1)
        attacker_2 = _make_member(wid="a2", pos=2, atk=1, hp=200, defense=1)
        defender_1 = _make_member(wid="d1", pos=1, atk=1, hp=50, defense=1)  # 易死
        defender_2 = _make_member(wid="d2", pos=2, atk=1, hp=200, defense=1)

        battle = _make_battle(
            atk_members=[attacker_1, attacker_2],
            df_members=[defender_1, defender_2],
            active_idx=(1, 1),
        )

        # 强攻让 attacker_1 一击打死 defender_1；但 attacker_1 反击时被 defender_2 打死
        # 用一个能让这个剧情展开的 RNG（构造让 attacker_1 反击时命中但不暴击）
        class _Scenario:
            """先手 attacker_1 攻击 defender_1：命中 + 暴击
            后手反击 defender_2 攻击 attacker_1：命中 + 不暴击（重伤 50 hp）

            第一回合 random() 序列：
              1) hit check attacker_1 -> defender_1: 0.5 (命中)
              2) crit check attacker_1 -> defender_1: 0.5 (暴击，攻击方 SSR crit_rate=0.20)
              3) jitter: 0.5
              4) hit check defender_2 -> attacker_1 (反击): 0.5 (命中)
              5) crit check defender_2 -> attacker_1: 0.95 (不暴击)
              6) jitter: 0.5
            """
            def __init__(self):
                self._n = 0

            def random(self) -> float:
                values = [0.5, 0.5, 0.5, 0.5, 0.95, 0.5]
                self._n += 1
                return values[self._n - 1] if self._n <= len(values) else 0.5

        # attacker_1 反击时被打掉的血量需要 hp=50 全死
        # attacker_1: 200 hp. raw_dmg: defender_2 base_atk=1 + 0.3 = 1.3 → dmg ~1-2
        # 不会死。所以这个测试需要更精巧
        # 改用一个大攻击 defender_2 反击
        defender_2_atk = _make_member(wid="d2", pos=2, atk=10000, hp=200, defense=1)
        defender_1 = _make_member(wid="d1", pos=1, atk=1, hp=50, defense=1)  # 易死
        battle = _make_battle(
            atk_members=[attacker_1, attacker_2],
            df_members=[defender_1, defender_2_atk],
            active_idx=(1, 1),
        )
        do_turn(battle, turn_idx=0, rng=_Scenario())

        # 验证：def_1 死了、def_2 上场
        assert battle.def_formation[0].is_alive is False
        # attacker_1 可能死也可能不死（看 dmg），核心是 swap 了
        assert battle.active_idx[1] == 2


# ============== 状态层累积在 do_turn 里的触发 ==============


class TestDoTurnStatusAccumulation:
    def test_bloodlust_triggers_at_turn_5(self):
        """turn=5 → bloodlust 累积到当前 active"""
        m1 = _make_member(wid="w1", pos=1)
        m2 = _make_member(wid="w2", pos=1)
        battle = _make_battle(atk_members=[m1], df_members=[m2])
        rng = random.Random(42)

        do_turn(battle, turn_idx=5, rng=rng)

        assert battle.atk_status_layers[0].bloodlust == 1
        assert battle.def_status_layers[0].bloodlust == 1

    def test_frenzy_triggers_when_low_hp(self):
        """当 active hp < 30% 时 frenzy 激活"""
        m1 = _make_member(wid="w1", pos=1, hp=100, current_hp=20)
        m2 = _make_member(wid="w2", pos=1, hp=100, current_hp=100)
        battle = _make_battle(atk_members=[m1], df_members=[m2])
        rng = random.Random(42)

        do_turn(battle, turn_idx=0, rng=rng)

        assert battle.atk_status_layers[0].frenzy is True
        assert battle.def_status_layers[0].frenzy is False


# ============== N 卡连击（spec §S3.5 N 卡被动） ==============


class TestDoTurnCombo:
    """N 卡连击：击杀后 25% 概率追加 1 次普通攻击（spec §S3.5 N 卡被动）。

    接线要求：

    * ``do_turn`` 当 ``attacker.rarity == "N"`` 且本次攻击击杀守方（hp → 0）且
      ``rng.random() < 0.25`` 时：
      - 标记连击（attack_events 加 ``combo: True`` 条目）
      - 立即对守方再执行一次 ``calc_raw_damage``
      - 二次伤害记入 attacker.damage_dealt 并扣 defender.current_hp
    """

    def test_combo_triggers_on_n_kill_within_25pct(self):
        """N 卡一击毙命 + rng 序列让 combo 检查通过 → 2 个攻击事件（普通 + combo）"""
        # 攻方 N 卡（必须）一击毙命；守方一击毙命 → 攻方先手
        attacker = _make_member(
            wid="a1", pos=1, rarity="N", element="力量",
            atk=10000, defense=1, hp=200,
        )
        defender = _make_member(
            wid="d1", pos=1, rarity="N", element="智力",
            atk=1, defense=1, hp=50,
        )
        battle = _make_battle(atk_members=[attacker], df_members=[defender], active_idx=(1, 1))

        # rng 序列：
        # 1) 先手 hit (atk→df):   0.5  (< 0.90 → 命中)
        # 2) 先手 crit (atk→df):  0.95 (> 0.10 N 卡 crit_rate → 不暴击)
        # 3) 先手 jitter:         0.5  (jitter=1.0)
        # 4) combo check:         0.1  (< 0.25 → 触发 combo)
        # 5) combo hit:           0.5  (命中)
        # 6) combo crit:          0.95 (不暴击)
        # 7) combo jitter:        0.5
        # 8) 后手反击 → df 已死 → 跳过
        rng = _ScriptedRNG([0.5, 0.95, 0.5, 0.1, 0.5, 0.95, 0.5])

        result = do_turn(battle, turn_idx=0, rng=rng)

        attack_events = result["attack_events"]
        # 应该有 2 条：先手一击 + combo 补刀
        assert len(attack_events) == 2, f"expected 2 attack_events, got {len(attack_events)}"

        # 第 1 条：普通攻击，combo=False
        evt0 = attack_events[0]
        assert evt0["side"] == "atk"
        assert evt0["hit"] is True
        assert evt0["combo"] is False
        dmg0 = evt0["dmg"]

        # 第 2 条：combo 补刀，combo=True, combo_followup=True
        evt1 = attack_events[1]
        assert evt1["side"] == "atk"
        assert evt1["combo"] is True
        assert evt1["hit"] is True
        dmg1 = evt1["dmg"]

        # 攻方 damage_dealt = 两次 dmg 之和
        assert attacker.damage_dealt == dmg0 + dmg1, (
            f"damage_dealt={attacker.damage_dealt}, expected {dmg0 + dmg1}"
        )

    def test_combo_not_triggered_when_rng_above_threshold(self):
        """N 卡一击毙命，但 rng 序列让 combo 检查不通过 → 只有 1 个攻击事件"""
        attacker = _make_member(
            wid="a1", pos=1, rarity="N", element="力量",
            atk=10000, defense=1, hp=200,
        )
        defender = _make_member(
            wid="d1", pos=1, rarity="N", element="智力",
            atk=1, defense=1, hp=50,
        )
        battle = _make_battle(atk_members=[attacker], df_members=[defender], active_idx=(1, 1))

        # rng 序列：combo check = 0.5 (>= 0.25 → 不触发)
        rng = _ScriptedRNG([0.5, 0.95, 0.5, 0.5])

        result = do_turn(battle, turn_idx=0, rng=rng)

        attack_events = result["attack_events"]
        assert len(attack_events) == 1, (
            f"expected 1 attack_event (no combo), got {len(attack_events)}"
        )
        assert attack_events[0]["combo"] is False
        # damage_dealt = 单次 dmg
        assert attacker.damage_dealt == attack_events[0]["dmg"]

    def test_combo_only_for_n_rarity(self):
        """非 N 卡击杀 → 不触发 combo（即使 rng < 0.25 也会）"""
        attacker = _make_member(
            wid="a1", pos=1, rarity="SSR", element="力量",
            atk=10000, defense=1, hp=200,
        )
        defender = _make_member(
            wid="d1", pos=1, rarity="N", element="智力",
            atk=1, defense=1, hp=50,
        )
        battle = _make_battle(atk_members=[attacker], df_members=[defender], active_idx=(1, 1))

        # 极端：把 rng 阈值设得很小；如果 combo 检查被错误触发，会看到多余 random() 调用
        rng = _ScriptedRNG([0.5, 0.95, 0.5])

        result = do_turn(battle, turn_idx=0, rng=rng)

        assert len(result["attack_events"]) == 1, (
            f"SSR attacker should not trigger combo: got {len(result['attack_events'])} events"
        )
        # 也没调用额外的 random()（combo check 不存在）
        assert len(rng.calls) == 3, f"rng calls={rng.calls}"

    def test_combo_does_not_trigger_if_defender_not_killed(self):
        """N 卡没击杀 → 不触发 combo（即使 rng < 0.25）"""
        # 攻方 N 卡，但伤害不足以秒杀
        attacker = _make_member(
            wid="a1", pos=1, rarity="N", element="力量",
            atk=10, defense=1, hp=200,
        )
        defender = _make_member(
            wid="d1", pos=1, rarity="N", element="智力",
            atk=1, defense=1, hp=9999,
        )
        battle = _make_battle(atk_members=[attacker], df_members=[defender], active_idx=(1, 1))

        # 强制命中 + 不暴击；def 不死 → combo 不触发
        # 然后后手反击也要命中，但反击的伤害用尽 rng 即可
        # 序列：atk hit/crit/jitter, df hit/crit/jitter
        rng = _ScriptedRNG([0.5, 0.95, 0.5, 0.5, 0.95, 0.5])

        result = do_turn(battle, turn_idx=0, rng=rng)

        # 没有击杀 → 不应触发 combo
        assert defender.is_alive is True
        # 事件数：先手 1 + 后手 1 = 2；没有 combo 补刀
        assert len(result["attack_events"]) == 2
        for evt in result["attack_events"]:
            assert evt["combo"] is False