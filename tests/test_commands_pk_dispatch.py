"""``老婆 PK`` 命令分发测试。

覆盖 v3_接力战_主线.md §S4.2 [PK 命令接入语法] + §S4.5 [兼容与回退]：

* 不带编号 → 4v4（new）：``PkV2Service.start_battle`` 被调用
* 带编号 → 1v1（legacy）：``PkService.pk`` 被调用
* PkV2Service 不可用 / 出错 → 回退 1v1 + 错误回复
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List
from unittest.mock import AsyncMock

import pytest

from app.commands.context import CommandContext
from app.services.plugin_config import PluginConfig


# ---------- helpers ----------
# 复用 test_commands_formation.py 的 mock event 模式


def _get_stub_at_class():
    """获取 stub 注入的 ``At`` 类（make isinstance check 通过）。"""
    import sys
    mod = sys.modules.get("astrbot.api.message_components")
    return mod.At


class _MockMessageObj:
    def __init__(self, gid: str, at_target: str = ""):
        self.group_id = gid
        At = _get_stub_at_class()
        self.message = [At(qq=at_target)] if at_target else []


class _MockEvent:
    """最小化 AstrMessageEvent 桩，足以驱动 PK 命令。"""

    def __init__(self, gid: str, uid: str, nick: str, message: str, at_target: str = "",
                 unified_msg_origin: str = "aiocqhttp:group_message:g1"):
        self.message_str = message
        self.message_obj = _MockMessageObj(gid, at_target=at_target)
        self._uid = uid
        self._nick = nick
        self._at = at_target
        self.unified_msg_origin = unified_msg_origin
        self.replies: List[str] = []

    def get_sender_id(self):
        return self._uid

    def get_sender_name(self):
        return self._nick

    def get_self_id(self):
        # 让 parse_at_target 跳过自己
        return "self-bot"

    def plain_result(self, text: str):
        self.replies.append(text)
        return text

    def chain_result(self, chain):
        self.replies.append(str(chain))
        return chain


def _make_ctx(tmp_paths, config, locks, ownership_service, wife_service):
    from zoneinfo import ZoneInfo
    return CommandContext(
        paths=tmp_paths,
        config=config,
        locks=locks,
        ownership_service=ownership_service,
        wife_service=wife_service,
        cooldown_service=None,
        tz=ZoneInfo("Asia/Shanghai"),
    )


# ============== 4v4 dispatch（不带编号） ==============


class TestPkDispatch4v4:
    @pytest.mark.asyncio
    async def test_no_args_at_target_dispatches_to_pk_v2(
        self, monkeypatch, tmp_paths, config, locks, ownership_service, mock_wife_service
    ):
        """``老婆 PK @某人``（无数字参数）→ PkV2Service.start_battle 被调"""
        from app.commands import pk as pk_cmd

        ctx = _make_ctx(tmp_paths, config, locks, ownership_service, mock_wife_service)
        event = _MockEvent("g1", "u1", "alice", "老婆 PK @bob", at_target="u2")

        called_kwargs = {}

        async def fake_start_battle(battle, umo):
            called_kwargs["battle_id"] = battle.battle_id
            called_kwargs["umo"] = umo
            called_kwargs["gid"] = battle.gid
            return "✅ 4v4 接力战启动！请查看后续战报..."

        # 把 PkV2Service 整个类换掉
        class FakePkV2:
            def __init__(self, *a, **kw):
                pass
            async def start_battle(self, battle, umo):
                return await fake_start_battle(battle, umo)

        monkeypatch.setattr(pk_cmd, "PkV2Service", FakePkV2)

        # 简化：构造一个能跑完的 fake PkBattle 装配
        # 这里直接确认 fake_start_battle 被调
        # handle_pk 需要构造 PkBattle 来 start_battle → 我们需要完整的 _construct_battle 路径
        # 暂时只测 dispatch 行为：构造一个 fake "service.start_battle 被调用过"

        # 我们需要构造有效编队才能跑通 4v4 路径；用 monkeypatch 替换内部构造函数
        def fake_construct(*a, **kw):
            from app.models.pk_battle import PkBattle
            return (
                PkBattle(gid="g1", battle_id="b-test",
                         atk_uid="u1", atk_nick="alice",
                         def_uid="u2", def_nick="bob",
                         atk_formation=[], def_formation=[],
                         atk_status_layers=[], def_status_layers=[]),
                False, False,
            )

        monkeypatch.setattr(pk_cmd, "_construct_battle", fake_construct)

        async for _ in pk_cmd.handle_pk(event, ctx):
            pass

        assert called_kwargs["gid"] == "g1"
        assert called_kwargs["umo"] == "aiocqhttp:group_message:g1"
        assert any("✅" in r for r in event.replies)


# ============== 1v1 dispatch（带编号） ==============


class TestPkDispatch1v1:
    @pytest.mark.asyncio
    async def test_with_number_args_dispatches_to_legacy_1v1(
        self, monkeypatch, tmp_paths, config, locks, ownership_service, mock_wife_service
    ):
        """``老婆 PK @某人 1 2``（带数字）→ 旧 PkService.pk 被调"""
        from app.commands import pk as pk_cmd
        from app.services.pk_service import PkResult

        ctx = _make_ctx(tmp_paths, config, locks, ownership_service, mock_wife_service)
        event = _MockEvent("g1", "u1", "alice", "老婆 PK @bob 1 2", at_target="u2")

        called = {"yes": False}

        async def fake_pk(self, gid, atk_uid, def_uid, atk_nick, def_nick, today):
            called["yes"] = True
            return PkResult(
                ok=True,
                attacker_name="三笠", defender_name="雷姆",
                attacker_uid="u1", defender_uid="u2",
                winner_uid="u1", winner_nick="alice",
                winner_score_gain=5, loser_score_gain=1,
                reward=15, loser_reward=5,
                attacker_element="力量", defender_element="敏捷",
                element_advantage=1.0,
                attacker_power=100, defender_power=80,
                is_tie=False,
            )

        monkeypatch.setattr(pk_cmd.PkService, "pk", fake_pk)
        # 4v4 不应被触发
        class ShouldNotBeCalled:
            async def start_battle(self, battle, umo):
                raise AssertionError("PkV2Service should not be called for 1v1")

        monkeypatch.setattr(pk_cmd, "PkV2Service", ShouldNotBeCalled)

        # 给一些老婆 + profile 让 1v1 路径走通
        from app.models.ownership import Ownership
        from app.models.wife import BaseStats, WifeMeta
        from app.models.profile import UserProfile
        from app.storage.stores import (
            OwnershipStore, ProfileStore, WivesMasterStore,
        )
        # 主老婆 for u1
        store = OwnershipStore(tmp_paths, "g1")
        ownerships = store.load_all()
        ownerships.append(Ownership(wid="w_a", uid="u1", is_primary=True))
        ownerships.append(Ownership(wid="w_b", uid="u2", is_primary=True))
        store.save_all(ownerships)
        # WifeMeta
        wives = WivesMasterStore(tmp_paths).load_all()
        wives["w_a"] = WifeMeta(wid="w_a", img="a.jpg", chara="三笠",
                                rarity="SSR", base_stats=BaseStats(atk=80, defense=60, hp=500))
        wives["w_b"] = WifeMeta(wid="w_b", img="b.jpg", chara="雷姆",
                                rarity="N", base_stats=BaseStats(atk=50, defense=50, hp=300))
        WivesMasterStore(tmp_paths).save_all(wives)
        # Profile for u1/u2
        profiles_store = ProfileStore(tmp_paths, "g1")
        profiles = profiles_store.load_all()
        profiles["u1"] = UserProfile(uid="u1", nick="alice", coins=0)
        profiles["u2"] = UserProfile(uid="u2", nick="bob", coins=0)
        profiles_store.save_all(profiles)

        async for _ in pk_cmd.handle_pk(event, ctx):
            pass

        assert called["yes"] is True
        # 1v1 路径返回的不是 4v4 ack
        assert not any("4v4 接力战启动" in r for r in event.replies)


# ============== 回退到 1v1 ==============


class TestPkDispatchFallback:
    @pytest.mark.asyncio
    async def test_pk_v2_disabled_falls_back_to_1v1(
        self, monkeypatch, tmp_paths, config, locks, ownership_service, mock_wife_service
    ):
        """``config.pk_v2_enabled = False`` → 回退 1v1"""
        from app.commands import pk as pk_cmd
        from app.services.pk_service import PkResult

        cfg = PluginConfig(pk_v2_enabled=False)
        ctx = _make_ctx(tmp_paths, config, locks, ownership_service, mock_wife_service)
        # 用我们的 cfg 覆盖 ctx.config
        object.__setattr__(ctx, "config", cfg)

        event = _MockEvent("g1", "u1", "alice", "老婆 PK @bob", at_target="u2")

        async def fake_pk(self, *a, **kw):
            return PkResult(
                ok=True,
                attacker_name="X", defender_name="Y",
                attacker_uid="u1", defender_uid="u2",
                winner_uid="u1", winner_nick="alice",
                winner_score_gain=5, loser_score_gain=1,
                reward=15, loser_reward=5,
                attacker_element="力量", defender_element="力量",
                element_advantage=1.0,
                attacker_power=100, defender_power=80,
                is_tie=False,
            )

        monkeypatch.setattr(pk_cmd.PkService, "pk", fake_pk)

        class ShouldNotBeCalled:
            def __init__(self, *a, **kw):
                raise AssertionError("PkV2Service should not be initialized when disabled")

        monkeypatch.setattr(pk_cmd, "PkV2Service", ShouldNotBeCalled)

        # Seed minimal data for 1v1
        from app.models.ownership import Ownership
        from app.models.wife import BaseStats, WifeMeta
        from app.models.profile import UserProfile
        from app.storage.stores import (
            OwnershipStore, ProfileStore, WivesMasterStore,
        )
        store = OwnershipStore(tmp_paths, "g1")
        ownerships = store.load_all()
        ownerships.append(Ownership(wid="w_a", uid="u1", is_primary=True))
        ownerships.append(Ownership(wid="w_b", uid="u2", is_primary=True))
        store.save_all(ownerships)
        wives = WivesMasterStore(tmp_paths).load_all()
        wives["w_a"] = WifeMeta(wid="w_a", img="a.jpg", chara="三笠",
                                rarity="SSR", base_stats=BaseStats(atk=80, defense=60, hp=500))
        wives["w_b"] = WifeMeta(wid="w_b", img="b.jpg", chara="雷姆",
                                rarity="N", base_stats=BaseStats(atk=50, defense=50, hp=300))
        WivesMasterStore(tmp_paths).save_all(wives)
        profiles_store = ProfileStore(tmp_paths, "g1")
        profiles = profiles_store.load_all()
        profiles["u1"] = UserProfile(uid="u1", nick="alice", coins=0)
        profiles["u2"] = UserProfile(uid="u2", nick="bob", coins=0)
        profiles_store.save_all(profiles)

        async for _ in pk_cmd.handle_pk(event, ctx):
            pass

        # 1v1 path returns detailed战报
        assert any("战报" in r or "获胜" in r or "失败" in r or "PK" in r for r in event.replies)
