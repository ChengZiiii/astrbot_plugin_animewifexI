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
class _MockNodeSender:
    """记录所有 send_node（合并转发）调用的 mock。"""

    calls: List[Tuple[str, int, str, List[str]]] = field(default_factory=list)

    async def __call__(self, umo: str, sender_id: int, sender_name: str, texts: List[str]) -> None:
        self.calls.append((umo, sender_id, sender_name, list(texts)))


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
    profile_store: Optional[_MockProfileStore] = None,
    config=None,
    node_sender: Optional[_MockNodeSender] = None,
    forward_sender_id: int = 0,
    forward_sender_name: str = "哆啦b梦",
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
        send_node=(node_sender if node_sender else None),
        forward_sender_id=forward_sender_id,
        forward_sender_name=forward_sender_name,
        battle_store=battle_store or _MockBattleStore(),
        profile_store_provider=lambda gid: (profile_store or _MockProfileStore()),
    )


async def _wait_for_settle(service, sender, max_iter=200, sleep_s=0.02):
    """Utility: await until service._settled."""
    for _ in range(max_iter):
        await asyncio.sleep(sleep_s)
        if service._settled:
            return


# ============== _run_battle behavior ==============


class TestRunBattle:
    @pytest.mark.asyncio
    async def test_start_battle_sends_combined_messages(self):
        """start_battle → 战斗结束后会合并发送全部消息（含启动+回合+结算）"""
        sender = _MockSender()
        store = _MockBattleStore()
        service = _service_with_mocks(sender=sender, battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        msg = await service.start_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        assert isinstance(msg, str)
        assert "启动" in msg or "战报" in msg
        # 合并后只有 1 条发送调用
        assert len(sender.calls) >= 1
        combined = sender.calls[0][1] if sender.calls else ""
        assert "4v4" in combined or "接力战" in combined

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
    async def test_auto_advance_sends_one_combined_message(self):
        """合并后只有 1 条发送调用（含所有回合+启动+结算）"""
        sender = _MockSender()
        store = _MockBattleStore()
        service = _service_with_mocks(sender=sender, battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # 合并发送 = 1 条消息
        assert len(sender.calls) == 1
        combined = sender.calls[0][1]
        assert "4v4" in combined or "接力战" in combined
        assert "🏆" in combined

    @pytest.mark.asyncio
    async def test_auto_advance_saves_each_turn(self):
        """每个 turn 后保存 battle"""
        store = _MockBattleStore()
        service = _service_with_mocks(battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, _MockSender())

        # 初始 save + 每个 turn save + settle save = ≥ 3
        assert len(store.saved) >= 3

    @pytest.mark.asyncio
    async def test_battle_file_deleted_on_settle(self):
        """结算结束删 battle 文件"""
        store = _MockBattleStore()
        service = _service_with_mocks(battle_store=store)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, _MockSender())

        assert store.deleted == [("g1", "b-test")]

    @pytest.mark.asyncio
    async def test_battle_runs_to_completion(self):
        """战斗真的会走完"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

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

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        assert service._settled is True
        assert battle.winner_uid == "u1"

    @pytest.mark.asyncio
    async def test_coroutine_exception_does_not_propagate(self):
        """send_message 抛异常时协程不冒泡（仅日志）"""
        service = _service_with_mocks()
        battle = _make_battle()
        async def bad_send(umo, text):
            raise RuntimeError("network down")
        service._send = bad_send

        # 不抛异常即通过
        await service._auto_advance_battle(battle, "umo")


# ============== send_node 合并转发 ==============


class TestFlushBufferForward:
    """_flush_buffer 走合并转发（send_node）路径的测试。"""

    @pytest.mark.asyncio
    async def test_flush_buffer_uses_send_node_when_provided(self):
        """给了 send_node + 合法 forward_sender_id → 走合并转发，不走 send_message"""
        sender = _MockSender()
        node_sender = _MockNodeSender()
        service = _service_with_mocks(
            sender=sender,
            node_sender=node_sender,
            forward_sender_id=10086,
            forward_sender_name="哆啦b梦",
        )
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # send_message 不应被调用
        assert sender.calls == [], "send_message 不应被触发（已走 send_node）"
        # send_node 应被调用 1 次
        assert len(node_sender.calls) == 1
        umo, sender_id, sender_name, texts = node_sender.calls[0]
        assert umo == "umo"
        assert sender_id == 10086
        assert sender_name == "哆啦b梦"
        # texts 里应包含多回合独立条目（启动贴 + 回合贴 + 结算贴至少各一条）
        assert len(texts) >= 2
        assert any("4v4" in t or "接力战即将开始" in t for t in texts)
        assert any("🏆" in t or "4v4 接力战结束" in t for t in texts)
        # 关键：回合贴是独立的 Node，不应被 join 成长文本
        for t in texts:
            assert "────────────" not in t, "合并转发的每个 Node 应保持独立，不应被 join"

    @pytest.mark.asyncio
    async def test_flush_buffer_falls_back_when_forward_sender_id_zero(self):
        """forward_sender_id=0 时回退到 send_message（兼容老测试）"""
        sender = _MockSender()
        node_sender = _MockNodeSender()
        service = _service_with_mocks(
            sender=sender,
            node_sender=node_sender,
            forward_sender_id=0,  # 没拿到 bot id
        )
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # send_node 不会被调（因为 forward_sender_id == 0）
        assert node_sender.calls == []
        # 回退到 send_message
        assert len(sender.calls) >= 1
        combined = sender.calls[0][1]
        assert "────────────" in combined  # 老逻辑的 join 分隔

    @pytest.mark.asyncio
    async def test_flush_buffer_falls_back_when_no_send_node(self):
        """没给 send_node → 回退到 send_message（向后兼容）"""
        sender = _MockSender()
        service = _service_with_mocks(sender=sender, node_sender=None)
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # 老逻辑：合并成一条长消息
        assert len(sender.calls) == 1
        combined = sender.calls[0][1]
        assert "4v4" in combined or "接力战" in combined
        assert "────────────" in combined

    @pytest.mark.asyncio
    async def test_flush_buffer_node_sender_exception_falls_back(self):
        """send_node 抛异常时回退到 send_message（不让战斗崩）"""
        sender = _MockSender()

        async def bad_node(umo, sender_id, sender_name, texts):
            raise RuntimeError("forward API down")

        from app.services.plugin_config import PluginConfig
        service = PkV2Service(
            paths=None,
            config=PluginConfig(pk_v2_turn_delay_ms=1),
            locks=None,
            send_message=sender.__call__,
            send_node=bad_node,
            forward_sender_id=10086,
            forward_sender_name="哆啦b梦",
            battle_store=_MockBattleStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )
        battle = _make_battle(atk_formation=_def_formation(), def_formation=_def_formation())

        # 不抛异常即通过
        await service._auto_advance_battle(battle, "umo")
        await _wait_for_settle(service, sender)

        # 回退：send_message 应被调用
        assert len(sender.calls) >= 1


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


# ============== start_battle 防刷预检已移除 ==============
# 同对手限制已完全移除（仅靠自冷却 pk_cooldown）
# _MockPairStoreBlocked 类/测试一并删除


# ============== _apply_lifespan_damage v2 算法 ==============


class TestApplyLifespanDamageV2:
    """PK lifespan V2: 胜方不扣 / 败方按 hp 损失折算"""

    def test_winner_not_deducted(self, tmp_paths, config, locks, lifespan_service):
        """胜方参战老婆不扣寿命"""
        from app.storage.stores import OwnershipStore
        from app.models.ownership import Ownership

        atk_wid, def_wid = "w_atk", "w_def"
        store = OwnershipStore(tmp_paths, "g1")
        store.save_all([
            Ownership(uid="u1", wid=atk_wid, lifespan=100, is_dead=False),
            Ownership(uid="u2", wid=def_wid, lifespan=100, is_dead=False),
        ])

        atk_m = _make_member(atk_wid, 1, "AtkHero", "SSR", "力量", hp=200, current_hp=160)
        atk_m.damage_taken = 40  # 受伤但活着
        def_m = _make_member(def_wid, 1, "DefHero", "N", "敏捷", hp=100, current_hp=0, is_alive=False)

        battle = PkBattle(
            gid="g1", battle_id="b-test", atk_uid="u1", atk_nick="alice",
            def_uid="u2", def_nick="bob",
            atk_formation=[atk_m], def_formation=[def_m],
            atk_status_layers=[BattleStatusLayer()], def_status_layers=[BattleStatusLayer()],
            winner_uid="u1", end_reason="all_dead",
        )
        svc = PkV2Service(
            paths=tmp_paths, config=config, locks=locks,
            lifespan_service=lifespan_service,
            battle_store=_MockBattleStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )
        svc._apply_lifespan_damage(battle)

        reloaded = OwnershipStore(tmp_paths, "g1").load_all()
        atk_ow = next(o for o in reloaded if o.wid == atk_wid)
        def_ow = next(o for o in reloaded if o.wid == def_wid)
        assert atk_ow.lifespan == 100, f"胜方不扣寿命，但实际={atk_ow.lifespan}"
        assert def_ow.lifespan == 95, f"败方战败扣5，但实际={def_ow.lifespan}"

    def test_loser_defeated_fixed_penalty(self, tmp_paths, config, locks, lifespan_service):
        """败方战败（is_alive=False）扣 pk_loser_defeat_penalty=5"""
        from app.storage.stores import OwnershipStore
        from app.models.ownership import Ownership

        atk_wid, def_wid = "w_atk2", "w_def2"
        store = OwnershipStore(tmp_paths, "g2")
        store.save_all([
            Ownership(uid="u1", wid=atk_wid, lifespan=100, is_dead=False),
            Ownership(uid="u2", wid=def_wid, lifespan=100, is_dead=False),
        ])

        atk_m = _make_member(atk_wid, 1, "A", "SSR", "力量", hp=500, current_hp=500)
        def_m = _make_member(def_wid, 1, "D", "N", "敏捷", hp=100, current_hp=0, is_alive=False)

        battle = PkBattle(
            gid="g2", battle_id="b2", atk_uid="u1", atk_nick="a",
            def_uid="u2", def_nick="b",
            atk_formation=[atk_m], def_formation=[def_m],
            atk_status_layers=[BattleStatusLayer()], def_status_layers=[BattleStatusLayer()],
            winner_uid="u1", end_reason="all_dead",
        )
        svc = PkV2Service(
            paths=tmp_paths, config=config, locks=locks,
            lifespan_service=lifespan_service,
            battle_store=_MockBattleStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )
        svc._apply_lifespan_damage(battle)

        reloaded = OwnershipStore(tmp_paths, "g2").load_all()
        def_ow = next(o for o in reloaded if o.wid == def_wid)
        assert def_ow.lifespan == 95, f"败方战败扣5，实际={def_ow.lifespan}"

    def test_loser_survived_hp_ratio(self, tmp_paths, config, locks, lifespan_service):
        """败方存活：按 hp 损失比例折算"""
        from app.storage.stores import OwnershipStore
        from app.models.ownership import Ownership

        def_wid = "w_def3"
        store = OwnershipStore(tmp_paths, "g3")
        store.save_all([
            Ownership(uid="u1", wid="w_atk3", lifespan=100, is_dead=False),
            Ownership(uid="u2", wid=def_wid, lifespan=100, is_dead=False),
        ])

        atk_m = _make_member("w_atk3", 1, "A", "SSR", "力量", hp=500, current_hp=500)
        # 损失 30/100 = 30% hp → raw = 0.3 * 2/100 * 100 = 0.6 → int=0 → max(1,0)=1
        def_m = _make_member(def_wid, 1, "D", "N", "敏捷", hp=100, current_hp=70)
        def_m.damage_taken = 30

        battle = PkBattle(
            gid="g3", battle_id="b3", atk_uid="u1", atk_nick="a",
            def_uid="u2", def_nick="b",
            atk_formation=[atk_m], def_formation=[def_m],
            atk_status_layers=[BattleStatusLayer()], def_status_layers=[BattleStatusLayer()],
            winner_uid="u1", end_reason="all_dead",
        )
        svc = PkV2Service(
            paths=tmp_paths, config=config, locks=locks,
            lifespan_service=lifespan_service,
            battle_store=_MockBattleStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )
        svc._apply_lifespan_damage(battle)

        reloaded = OwnershipStore(tmp_paths, "g3").load_all()
        def_ow = next(o for o in reloaded if o.wid == def_wid)
        # raw = 30/100 * 2/100 * 100 = 0.6 → int 0 → max(1,0)=1
        assert def_ow.lifespan == 99, f"损失30%hp: 期望扣1, 实际={def_ow.lifespan}"

    def test_loser_survived_heavy_damage_capped(self, tmp_paths, config, locks, lifespan_service):
        """败方存活但重伤：扣减被上限 clamp 到 defeat_penalty*2=10"""
        from app.storage.stores import OwnershipStore
        from app.models.ownership import Ownership

        def_wid = "w_def4"
        store = OwnershipStore(tmp_paths, "g4")
        store.save_all([
            Ownership(uid="u1", wid="w_atk4", lifespan=100, is_dead=False),
            Ownership(uid="u2", wid=def_wid, lifespan=100, is_dead=False),
        ])

        atk_m = _make_member("w_atk4", 1, "A", "SSR", "力量", hp=500, current_hp=500)
        # 损失 90/100 = 90% hp → raw = 0.9 * 2/100 * 100 = 1.8 → int=1
        # 但上限是 defeat_penalty*2 = 10, 所以 min=1, max=10 最终=1
        # 实际上 max(1, min(1, 10)) = 1
        def_m = _make_member(def_wid, 1, "D", "N", "敏捷", hp=100, current_hp=10)
        def_m.damage_taken = 90

        battle = PkBattle(
            gid="g4", battle_id="b4", atk_uid="u1", atk_nick="a",
            def_uid="u2", def_nick="b",
            atk_formation=[atk_m], def_formation=[def_m],
            atk_status_layers=[BattleStatusLayer()], def_status_layers=[BattleStatusLayer()],
            winner_uid="u1", end_reason="all_dead",
        )
        svc = PkV2Service(
            paths=tmp_paths, config=config, locks=locks,
            lifespan_service=lifespan_service,
            battle_store=_MockBattleStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )
        svc._apply_lifespan_damage(battle)

        reloaded = OwnershipStore(tmp_paths, "g4").load_all()
        def_ow = next(o for o in reloaded if o.wid == def_wid)
        # raw = 90/100 * 2/100 * 100 = 1.8 → int=1 → max(1, min(1,10))=1
        assert def_ow.lifespan <= 99, f"重伤但存活: 扣1, 实际={def_ow.lifespan}"

    def test_tie_each_side_deducted_fixed(self, tmp_paths, config, locks, lifespan_service):
        """平局：双方各扣 lifespan_loss_pk_tie=8"""
        from app.storage.stores import OwnershipStore
        from app.models.ownership import Ownership

        atk_wid, def_wid = "w_atk5", "w_def5"
        store = OwnershipStore(tmp_paths, "g5")
        store.save_all([
            Ownership(uid="u1", wid=atk_wid, lifespan=100, is_dead=False),
            Ownership(uid="u2", wid=def_wid, lifespan=100, is_dead=False),
        ])

        atk_m = _make_member(atk_wid, 1, "A", "SSR", "力量", hp=200, current_hp=100)
        atk_m.damage_taken = 100
        def_m = _make_member(def_wid, 1, "D", "N", "敏捷", hp=200, current_hp=100)
        def_m.damage_taken = 100

        battle = PkBattle(
            gid="g5", battle_id="b5", atk_uid="u1", atk_nick="a",
            def_uid="u2", def_nick="b",
            atk_formation=[atk_m], def_formation=[def_m],
            atk_status_layers=[BattleStatusLayer()], def_status_layers=[BattleStatusLayer()],
            winner_uid="", end_reason="tie",
        )
        svc = PkV2Service(
            paths=tmp_paths, config=config, locks=locks,
            lifespan_service=lifespan_service,
            battle_store=_MockBattleStore(),
            profile_store_provider=lambda gid: _MockProfileStore(),
        )
        svc._apply_lifespan_damage(battle)

        reloaded = OwnershipStore(tmp_paths, "g5").load_all()
        atk_ow = next(o for o in reloaded if o.wid == atk_wid)
        def_ow = next(o for o in reloaded if o.wid == def_wid)
        assert atk_ow.lifespan == 92, f"平局各扣8, 实际={atk_ow.lifespan}"
        assert def_ow.lifespan == 92, f"平局各扣8, 实际={def_ow.lifespan}"
