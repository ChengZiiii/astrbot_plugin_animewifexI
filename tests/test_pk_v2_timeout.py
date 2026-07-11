"""v3 接力战 · 战斗超时 / HP 比判定测试。

覆盖 v3_接力战_主线.md §S7.1：

* 一方全死 → 另一方胜
* 12 回合后按剩余 HP 比判胜
"""

from __future__ import annotations

import pytest

from app.models.pk_battle import BattleStatusLayer, FormationMember, PkBattle
from app.services.pk_v2_battle import check_timeout


def _make_member(
    wid: str = "m1",
    pos: int = 1,
    rarity: str = "SSR",
    element: str = "力量",
    atk: int = 100,
    defense: int = 50,
    hp: int = 200,
    current_hp: int = None,
    is_alive: bool = True,
) -> FormationMember:
    if current_hp is None:
        current_hp = hp
    return FormationMember(
        wid=wid, pos=pos, nickname=f"W{wid}", rarity=rarity, element=element,
        base_atk=atk, base_def=defense, base_hp=hp,
        intimacy=0, is_locked=False,
        current_hp=current_hp, is_alive=is_alive, is_active=False,
    )


def _make_battle(
    atk_members: list,
    df_members: list,
    turn_idx: int = 0,
    active_idx: tuple = (1, 1),
    atk_uid: str = "u1",
    def_uid: str = "u2",
) -> PkBattle:
    atk_status = [BattleStatusLayer() for _ in atk_members]
    df_status = [BattleStatusLayer() for _ in df_members]
    return PkBattle(
        gid="g1", battle_id="b1",
        atk_uid=atk_uid, atk_nick="alice",
        def_uid=def_uid, def_nick="bob",
        atk_formation=list(atk_members),
        def_formation=list(df_members),
        atk_status_layers=atk_status,
        def_status_layers=df_status,
        turn_idx=turn_idx,
        active_idx=active_idx,
        rng_seed=42,
        status="active",
    )


# ============== check_timeout（§S7.1） ==============


class TestCheckTimeout:
    """check_timeout(battle) → None / winner_uid"""

    def test_no_timeout_when_both_alive(self):
        """双方都还有存活 → None（继续）"""
        m1 = _make_member()
        m2 = _make_member()
        battle = _make_battle([m1], [m2], turn_idx=5)
        result = check_timeout(battle)
        assert result is None

    def test_no_timeout_when_below_max_turns(self):
        """12 回合前双方都还活着 → None"""
        m1 = _make_member()
        m2 = _make_member()
        battle = _make_battle([m1], [m2], turn_idx=11)
        assert check_timeout(battle) is None

    def test_atk_all_dead_returns_def_winner(self):
        """攻方全死 → 守方胜"""
        dead_a1 = _make_member(wid="a1", is_alive=False)
        alive_b1 = _make_member(wid="b1")
        battle = _make_battle([dead_a1], [alive_b1], turn_idx=5)
        result = check_timeout(battle)
        assert result == "u2"  # def_uid

    def test_def_all_dead_returns_atk_winner(self):
        """守方全死 → 攻方胜"""
        alive_a1 = _make_member(wid="a1")
        dead_b1 = _make_member(wid="b1", is_alive=False)
        battle = _make_battle([alive_a1], [dead_b1], turn_idx=5)
        result = check_timeout(battle)
        assert result == "u1"  # atk_uid

    def test_both_all_dead_def_wins_by_default(self):
        """双方同归于尽 → 默认守方胜（spec §S6.3）"""
        dead_a1 = _make_member(wid="a1", is_alive=False)
        dead_b1 = _make_member(wid="b1", is_alive=False)
        battle = _make_battle([dead_a1], [dead_b1], turn_idx=5)
        result = check_timeout(battle)
        assert result == "u2"  # def_uid

    def test_max_turns_atk_more_hp_returns_atk(self):
        """12 回合到 + 攻方剩余 HP 多 → 攻方胜"""
        # 攻方：1 个满血 (200 hp)
        # 守方：2 个各 50 hp（共 100 hp）
        alive_a1 = _make_member(wid="a1", hp=200, current_hp=200)
        alive_b1 = _make_member(wid="b1", hp=100, current_hp=50)
        alive_b2 = _make_member(wid="b2", pos=2, hp=100, current_hp=50)
        battle = _make_battle(
            [alive_a1], [alive_b1, alive_b2], turn_idx=12,
        )
        result = check_timeout(battle)
        assert result == "u1"

    def test_max_turns_def_more_hp_returns_def(self):
        """12 回合到 + 守方剩余 HP 多 → 守方胜"""
        alive_a1 = _make_member(wid="a1", hp=200, current_hp=50)
        alive_a2 = _make_member(wid="a2", pos=2, hp=200, current_hp=50)  # 100 total
        alive_b1 = _make_member(wid="b1", hp=200, current_hp=200)
        battle = _make_battle(
            [alive_a1, alive_a2], [alive_b1], turn_idx=12,
        )
        result = check_timeout(battle)
        assert result == "u2"

    def test_max_turns_hp_tie_def_wins(self):
        """12 回合到 + 剩余 HP 相等 → 守方胜（默认）"""
        alive_a1 = _make_member(wid="a1", hp=100, current_hp=50)
        alive_b1 = _make_member(wid="b1", hp=100, current_hp=50)
        battle = _make_battle([alive_a1], [alive_b1], turn_idx=12)
        result = check_timeout(battle)
        assert result == "u2"

    def test_max_turns_zero_hp_sides_tie(self):
        """12 回合到 + 双方 HP 都是 0 → 守方胜（持平）"""
        alive_a1 = _make_member(wid="a1", hp=100, current_hp=0)
        alive_b1 = _make_member(wid="b1", hp=100, current_hp=0)
        battle = _make_battle([alive_a1], [alive_b1], turn_idx=12)
        # 0 == 0 → def_wins_by_default
        result = check_timeout(battle)
        assert result == "u2"

    def test_only_dead_at_max_turns(self):
        """12 回合 + 双方都全死 → 守方胜"""
        dead_a1 = _make_member(wid="a1", is_alive=False)
        dead_b1 = _make_member(wid="b1", is_alive=False)
        battle = _make_battle([dead_a1], [dead_b1], turn_idx=12)
        result = check_timeout(battle)
        assert result == "u2"

    def test_partial_dead_at_max_turns_uses_hp_ratio(self):
        """12 回合 + 一方有部分存活 + 双方都有 HP → 按 HP 比"""
        # 攻方：2 个存活（hp 50 + 50 = 100）
        # 守方：1 个存活（hp 200）
        # atk_total_hp = 100, def_total_hp = 200 → def wins
        alive_a1 = _make_member(wid="a1", hp=100, current_hp=50)
        alive_a2 = _make_member(wid="a2", pos=2, hp=100, current_hp=50)
        alive_b1 = _make_member(wid="b1", hp=200, current_hp=200)
        battle = _make_battle(
            [alive_a1, alive_a2], [alive_b1], turn_idx=12,
        )
        result = check_timeout(battle)
        assert result == "u2"

    def test_multi_member_hp_sum(self):
        """多成员 HP 求和正确"""
        alive_a1 = _make_member(wid="a1", hp=100, current_hp=80)
        alive_a2 = _make_member(wid="a2", pos=2, hp=100, current_hp=70)
        # atk_total_hp = 150
        alive_b1 = _make_member(wid="b1", hp=100, current_hp=60)
        alive_b2 = _make_member(wid="b2", pos=2, hp=100, current_hp=50)
        # def_total_hp = 110
        battle = _make_battle(
            [alive_a1, alive_a2], [alive_b1, alive_b2], turn_idx=12,
        )
        result = check_timeout(battle)
        assert result == "u1"  # 150 > 110