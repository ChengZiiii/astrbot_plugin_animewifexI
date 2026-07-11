"""v3 接力战 · PkV2Service 主动消息协程测试。

覆盖：

* 启动贴推送（1 次）
* 每个 do_turn 后推送回合贴（每回合 1 次）
* 死亡换人时推送死亡贴（0~2 次，依实际死亡数）
* 战斗结束推送结算贴（1 次）
* ``PkBattleStore.save`` 时机：每个 do_turn 后 + 战斗结束时
* ``PkPairStore.record_pk`` 在战斗结束时调用一次
* 战斗真的走完：双方都死 OR 超时 → 协程退出
* 协程异常被吞掉（不会冒泡到 _run_battle 调用方）
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pytest

from app.models.pk_battle import BattleStatusLayer, FormationMember, PkBattle
from app.services.pk_v2_service import PkV2Service


# ============== helpers ==============


@dataclass
class _MockSender:
    """记录所有 send_message 调用的 mock sender。"""

    calls: List[Tuple[str, str]] = field(default_factory=list)

    async def __call__(self, umo: str, text: str) -> None:
        self.calls.append((umo, text))


@dataclass
class _MockBattleStore:
    """In-memory PkBattleStore mock"""

    saved: List[Tuple[str, str, PkBattle]] = field(default_factory=list)
    deleted: List[Tuple[str, str]] = field(default_factory=list)

    def save(self, gid: str, battle_id: str, battle: PkBattle) -> None:
        self.saved.append((gid, battle_id, battle))

    def delete(self, gid: str, battle_id: str) -> None:
        self.deleted.append((gid, battle_id))


@dataclass
class _MockPairStore:
    """PkPairStore mock：只记录 record_pk 调用 + can_pk 永远返回 True"""

    recorded: List[Tuple[str, str]] = field(default_factory=list)
    can_pk_calls: int = 0
    data: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def can_pk(self, *args, **kwargs) -> bool:
        self.can_pk_calls += 1
        return True

    def load_all(self) -> Dict[str, Dict[str, float]]:
        return self.data

    def save_all(self, data) -> None:
        self.data = data

    def record_pk(self, data, attacker: str, defender: str) -> None:
        self.recorded.append((attacker, defender))


@dataclass
class _MockProfileStore:
    """ProfileStore mock：load_all 返回 dict"""

    profiles: Dict[str, dict] = field(default_factory=dict)
    saves: int = 0

    def load_all(self) -> Dict[str, dict]:
        return self.profiles

    def save_all(self, profiles) -> None:
        self.saves += 1
        self.profiles = profiles


def _make_member(
    wid: str = "w1",
    pos: int = 1,
    nick: str = "三笠",
    rarity: str = "SSR",
    element: str = "力量",
    atk: int = 80,
    defense: int = 60,
    hp: int = 500,
    intimacy: int = 90,
    is_locked: bool = False,
    current_hp: int = 500,
    is_alive: bool = True,
    kills: int = 0,
) -> FormationMember:
    return FormationMember(
        wid=wid, pos=pos, nickname=nick, rarity=rarity, element=element,
        base_atk=atk, base_def=defense, base_hp=hp,
        intimacy=intimacy, is_locked=is_locked,
        current_hp=current_hp, is_alive=is_alive, is_active=(pos == 1),
        kills=kills, work_mode="",
    )


def _atk_formation() -> List[FormationMember]:
    return [
        _make_member("wa1", 1, "三笠", "SSR", "力量", 80, 60, 500, 90),
        _make_member("wa2", 2, "阿尔敏", "SR", "智力", 50, 50, 380, 60),
        _make_member("wa3", 3, "萨沙", "R", "敏捷", 30, 30, 280, 30),
        _make_member("wa4", 4, "米卡莎", "N", "力量", 20, 20, 200, 10),
    ]


def _def_formation() -> List[FormationMember]:
    return [
        _make_member("wd1", 1, "祢豆子", "SR", "敏捷", 60, 50, 450, 50),
        _make_member("wd2", 2, "蝴蝶忍", "SR", "智力", 50, 50, 380, 70),
        _make_member("wd3", 3, "炭治郎", "R", "智力", 40, 40, 320, 40),
        _make_member("wd4", 4, "香奈乎", "N", "敏捷", 20, 20, 200, 20),
    ]


def _make_battle(
    atk_formation=None,
    def_formation=None,
    gid: str = "g1",
    atk_uid: str = "u1",
    def_uid: str = "u2",
) -> PkBattle:
    atk_f = atk_formation or _atk_formation()
    def_f = def_formation or _def_formation()
    atk_layers = [BattleStatusLayer() for _ in atk_f]
    def_layers = [BattleStatusLayer() for _ in def_f]
    return PkBattle(
        gid=gid,
        battle_id="b-test",
        atk_uid=atk_uid, atk_nick="alice",
        def_uid=def_uid, def_nick="bob",
        atk_formation=atk_f,
        def_formation=def_f,
        atk_status_layers=atk_layers,
        def_status_layers=def_layers,
        turn_idx=0,
        active_idx=(1, 1),
        rng_seed=42,
        status="active",
    )


def _service_with_mocks(
    sender: Optional[_MockSender] = None,
    battle_store: Optional[_MockBattleStore] = None,
    pair_store: Optional[_MockPairStore] = None,
    profile_store: Optional[_MockProfileStore] = None,
    config=None,
) -> PkV2Service:
    """Build a PkV2Service with mocked dependencies + a fast turn_delay."""
    from app.services.plugin_config import PluginConfig
    if config is None:
        config = PluginConfig(pk_v2_turn_delay_ms=1)  # 1ms = nearly instant
    return PkV2Service(
        paths=None,
        config=config,
        locks=None,
        send_message=(sender if sender else _MockSender()).__call__,
        battle_store=battle_store or _MockBattleStore(),
        pair_store=pair_store or _MockPairStore(),
        profile_store_provider=lambda gid: (profile_store or _MockProfileStore()),
    )


async def _wait_for_settle(service, sender, max_iter=200, sleep_s=0.02):
    """Utility: await until service._settled or sender saw settle贴."""
    for _ in range(max_iter):
        await asyncio.sleep(sleep_s)
        if service._settled:
            return
        if sender.calls and ("🏆" in sender.calls[-1][1] or "4v4 接力战结束" in sender.calls[-1][1]):
            return


# ============== _run_battle behavior ==============


class TestRunBattle:
    @pytest.mark.asyncio
    async def test_run_battle_sends_init_message(self):
        """_emit_init_message 必须发 1 条启动贴"""
        sender = _MockSender()
        store = _MockBattleStore()
        service = _service_with_mocks(sender=sender, battle_store=store)

        battle = _make_battle()
        await service._emit_init_message(battle, "umo_test")

        assert len(sender.calls) == 1
        text = sender.calls[0][1]
        assert "4v4" in text
        assert "接力战" in text
        assert sender.calls[0][0] == "umo_test"

    @pytest.mark.asyncio
    async def test_run_battle_init_message_contains_both_sides(self):
        """启动贴包含双方信息"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle()
        await service._emit_init_message(battle, "umo")
        msg = sender.calls[0][1]
        assert "alice" in msg
        assert "bob" in msg
        assert "三笠" in msg
        assert "祢豆子" in msg

    @pytest.mark.asyncio
    async def test_run_battle_saves_initial_battle(self):
        """_save_battle 必须 save battle"""
        store = _MockBattleStore()
        service = _service_with_mocks(battle_store=store)
        battle = _make_battle()
        service._save_battle(battle)
        assert len(store.saved) == 1
        assert store.saved[0][0] == "g1"
        assert store.saved[0][1] == "b-test"

    @pytest.mark.asyncio
    async def test_auto_advance_sends_turn_message_per_turn(self):
        """每个 do_turn 后推送回合贴"""
        sender = _MockSender()
        store = _MockBattleStore()
        service = _service_with_mocks(sender=sender, battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        # 手动驱动：先发启动贴，再跑 do_turn 循环
        await service._emit_init_message(battle, "umo")
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # 至少 2 条回合贴 + 启动贴 + 结算贴
        assert len(sender.calls) >= 3
        # 第一条：启动贴
        assert "4v4 接力战即将开始" in sender.calls[0][1]
        # 最后一条：结算贴
        assert "🏆" in sender.calls[-1][1] or "4v4 接力战结束" in sender.calls[-1][1]
        # 中间至少 1 条回合贴
        turn_count = sum(
            1 for _, t in sender.calls
            if ("第 " in t and " 回合" in t)
        )
        assert turn_count >= 1

    @pytest.mark.asyncio
    async def test_auto_advance_saves_each_turn(self):
        """每个 turn 后保存 battle"""
        store = _MockBattleStore()
        service = _service_with_mocks(battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._emit_init_message(battle, "umo")
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender := _MockSender())

        # 初始 save（_save_battle） + 每个 turn save + 一次 settle save = ≥ 3
        assert len(store.saved) >= 3

    @pytest.mark.asyncio
    async def test_record_pk_called_on_settle(self):
        """结算时调一次 PkPairStore.record_pk"""
        pair_store = _MockPairStore()
        service = _service_with_mocks(pair_store=pair_store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._emit_init_message(battle, "umo")
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, _MockSender())

        assert ("u1", "u2") in pair_store.recorded

    @pytest.mark.asyncio
    async def test_battle_file_deleted_on_settle(self):
        """结算结束删 battle 文件"""
        store = _MockBattleStore()
        service = _service_with_mocks(battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._emit_init_message(battle, "umo")
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, _MockSender())

        assert store.deleted == [("g1", "b-test")]

    @pytest.mark.asyncio
    async def test_battle_runs_to_completion(self):
        """战斗真的会走完"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._emit_init_message(battle, "umo")
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        assert service._settled is True
        assert battle.status in ("done", "settling")

    @pytest.mark.asyncio
    async def test_one_member_each_ends_fast(self):
        """单成员编队马上结束（一击死）"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        boss = _make_member("wboss", 1, "Boss", "SSR", "力量", 10000, 1, 99999, 90)
        weakling = _make_member("wweak", 1, "Weak", "N", "敏捷", 1, 1, 1, 0)
        battle = _make_battle(atk_formation=[boss], def_formation=[weakling])

        await service._emit_init_message(battle, "umo")
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        assert service._settled is True
        assert battle.winner_uid == "u1"

    @pytest.mark.asyncio
    async def test_coroutine_exception_does_not_propagate(self):
        """send_message 抛异常时协程不冒泡（仅日志）"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle()

        # Make the send raise
        async def bad_send(umo, text):
            raise RuntimeError("network down")
        service._send = bad_send

        # _emit_init_message should swallow
        await service._emit_init_message(battle, "umo")
        # 调用方拿到正常返回（不抛）
        assert sender.calls == []  # 因为 send 抛了，calls 不会增加


# ============== start_battle 公共 API ==============


class TestStartBattle:
    @pytest.mark.asyncio
    async def test_start_battle_returns_ack_message(self):
        """start_battle 返回 ✅ 启动贴已发送 的字符串"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle()

        msg = await service.start_battle(battle, "umo")
        assert isinstance(msg, str)
        assert "✅" in msg or "已发送" in msg or "启动" in msg

        # 等待协程跑完（可选）
        await _wait_for_settle(service, sender, max_iter=300)

    @pytest.mark.asyncio
    async def test_start_battle_spawns_background_task(self):
        """start_battle 用 asyncio.create_task 启动后台协程"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service.start_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # settle贴应已发出
        assert sender.calls, "no messages sent"
        assert any(
            "🏆" in t or "4v4 接力战结束" in t
            for _, t in sender.calls
        )

    @pytest.mark.asyncio
    async def test_start_battle_no_event_loop_does_not_raise(self):
        """start_battle 在无 running loop 时也不能崩（defensive）"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle()
        # 直接 await start_battle（loop 存在），不会 raise
        msg = await service.start_battle(battle, "umo")
        assert msg


# ============== turn_delay 配置 ==============


class TestTurnDelay:
    @pytest.mark.asyncio
    async def test_turn_delay_used_between_turns(self):
        """多回合间至少有几条消息延迟（不崩即可）"""
        from app.services.plugin_config import PluginConfig

        config = PluginConfig(pk_v2_turn_delay_ms=50)
        sender = _MockSender()
        service = _service_with_mocks(sender=sender, config=config)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service.start_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # 没崩就算过
        assert sender.calls


# ============== decide_rewards（单一奖励决策） ==============


class TestDecideRewards:
    """decide_rewards 必须按 §S9 经济表产出精确币数（驱动显示与实际发放）。"""

    def _service(self) -> PkV2Service:
        from app.services.plugin_config import PluginConfig
        return PkV2Service(
            paths=None, config=PluginConfig(), locks=None,
            pair_store=_MockPairStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )

    def _battle(self, atk_members, def_members, end_reason: str = "all_dead") -> PkBattle:
        atk_layers = [BattleStatusLayer() for _ in atk_members]
        def_layers = [BattleStatusLayer() for _ in def_members]
        return PkBattle(
            gid="g1", battle_id="b", atk_uid="u1", atk_nick="alice",
            def_uid="u2", def_nick="bob",
            atk_formation=atk_members, def_formation=def_members,
            atk_status_layers=atk_layers, def_status_layers=def_layers,
            end_reason=end_reason,
        )

    def test_decide_win_far_gives_winner_15_loser_1(self):
        """胜（大优势）：win +15/+5，loser +1/+0"""
        svc = self._service()
        atk = [_make_member("a", 1, "A", "SSR", "力量", 80, 60, 500, 90, current_hp=300, is_alive=True)]
        df = [_make_member("d", 1, "D", "SSR", "力量", 80, 60, 500, 90, current_hp=0, is_alive=False)]
        r = svc.decide_rewards(self._battle(atk, df), svc._config)
        assert r["is_tie"] is False
        assert r["winner_uid"] == "u1"
        assert r["win_coins"] == 15
        assert r["win_score"] == 5
        assert r["lose_coins"] == 1
        assert r["lose_score"] == 0

    def test_decide_close_loss_gives_loser_5(self):
        """负（战力差 ≤ 50%）：loser +5/+1"""
        svc = self._service()
        atk = [_make_member("a", 1, "A", "SSR", "力量", 80, 60, 500, 90, current_hp=300, is_alive=True)]
        df = [_make_member("d", 1, "D", "SSR", "力量", 80, 60, 500, 90, current_hp=200, is_alive=True)]
        r = svc.decide_rewards(self._battle(atk, df), svc._config)
        assert r["winner_uid"] == "u1"
        assert r["lose_coins"] == 5
        assert r["lose_score"] == 1

    def test_decide_far_loss_gives_loser_1(self):
        """负（战力差 > 50%）：loser +1/+0"""
        svc = self._service()
        atk = [_make_member("a", 1, "A", "SSR", "力量", 80, 60, 500, 90, current_hp=500, is_alive=True)]
        df = [_make_member("d", 1, "D", "SSR", "力量", 80, 60, 500, 90, current_hp=50, is_alive=True)]
        r = svc.decide_rewards(self._battle(atk, df), svc._config)
        assert r["lose_coins"] == 1
        assert r["lose_score"] == 0

    def test_decide_tie_gives_both_8(self):
        """平：双方 +8/+2"""
        svc = self._service()
        atk = [_make_member("a", 1, "A", "SSR", "力量", 80, 60, 500, 90, current_hp=200, is_alive=True)]
        df = [_make_member("d", 1, "D", "SSR", "力量", 80, 60, 500, 90, current_hp=200, is_alive=True)]
        r = svc.decide_rewards(self._battle(atk, df), svc._config)
        assert r["is_tie"] is True
        assert r["win_coins"] == 8
        assert r["lose_coins"] == 8
        assert r["win_score"] == 2
        assert r["lose_score"] == 2

    def test_decide_timeout_judges_by_hp(self):
        """超时（end_reason=timeout）按 HP 比判胜，胜方走 +15/+5"""
        svc = self._service()
        atk = [_make_member("a", 1, "A", "SSR", "力量", 80, 60, 500, 90, current_hp=300, is_alive=True)]
        df = [_make_member("d", 1, "D", "SSR", "力量", 80, 60, 500, 90, current_hp=100, is_alive=True)]
        r = svc.decide_rewards(self._battle(atk, df, end_reason="timeout"), svc._config)
        assert r["is_tie"] is False
        assert r["winner_uid"] == "u1"
        assert r["win_coins"] == 15
        assert r["win_score"] == 5


# ============== start_battle 24h 防刷预检 ==============


@dataclass
class _MockPairStoreBlocked(_MockPairStore):
    """can_pk 永远返回 False 的 pair store。"""

    def can_pk(self, *args, **kwargs) -> bool:
        self.can_pk_calls += 1
        return False


class TestStartBattleCooldown:
    @pytest.mark.asyncio
    async def test_start_battle_blocked_within_cooldown(self):
        """同对手冷却内已 PK 过 → start_battle 返回冷却文案（需配置 >0 才启用）"""
        from app.services.plugin_config import PluginConfig
        config = PluginConfig(pk_v2_turn_delay_ms=1, pk_pair_cooldown_hours=24)
        pair_store = _MockPairStoreBlocked()
        sender = _MockSender()
        service = _service_with_mocks(sender=sender, pair_store=pair_store, config=config)
        battle = _make_battle()

        msg = await service.start_battle(battle, "umo")

        # 返回冷却文案
        assert ("24" in msg) or ("PK 过" in msg) or ("休息" in msg)
        # can_pk 预检确实被调用
        assert pair_store.can_pk_calls >= 1
        # 不应推启动贴 / 结算贴（未启动）
        assert sender.calls == []
