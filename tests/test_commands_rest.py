"""Tests for app.commands.rest: 老婆 休息 / 养老婆 / 复活 命令处理器。"""

from __future__ import annotations

from typing import List

import pytest

from app.commands.context import CommandContext
from app.commands.rest import handle_rest
from app.models.ownership import Ownership
from app.models.profile import UserProfile
from app.models.wife import WifeMeta
from app.services.lifespan_service import LifespanService
from app.services.plugin_config import PluginConfig
from app.services.work_service import WorkService
from app.storage.locks import GroupLocks
from app.storage.paths import Paths
from app.storage.stores import (
    OwnershipStore,
    ProfileStore,
    WivesMasterStore,
)


# ==================== 工具 ====================


class _MockEvent:
    """最小可用的 AstrMessageEvent 替身。"""

    def __init__(self, message_str: str, group_id: str = "g1", sender_uid: str = "u1",
                 sender_nick: str = "Alice"):
        self.message_str = message_str
        self.message_obj = type("MO", (), {"group_id": group_id})()
        self._uid = sender_uid
        self._nick = sender_nick

    def get_sender_id(self):
        return self._uid

    def get_sender_nick(self):
        return self._nick

    def get_sender_name(self):
        return self._nick

    def plain_result(self, text: str):
        return ("plain", text)

    def chain_result(self, chain):
        return ("chain", chain)


def _build_ctx(
    paths: Paths,
    cfg: PluginConfig,
    lifespan_service: LifespanService,
) -> CommandContext:
    """构建测试用 CommandContext（不需要 ownership_service/wife_service，因为 rest 只用 lifespan）"""
    locks = GroupLocks()
    return CommandContext(
        paths=paths,
        config=cfg,
        locks=locks,
        ownership_service=None,
        wife_service=None,
        cooldown_service=None,
        tz=_no_tz(),
        context=None,
        lifespan_service=lifespan_service,
    )


def _no_tz():
    """用 UTC 时区作为 fallback"""
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo("UTC")
    except Exception:
        from datetime import timezone, timedelta
        return timezone(timedelta(hours=8))


async def _collect(handler) -> List:
    """执行 async generator，收集所有 yield 的结果"""
    out: List = []
    async for item in handler:
        out.append(item)
    return out


# ==================== 测试 ====================


async def test_rest_preview_no_wives(tmp_paths, config, lifespan_service):
    """没老婆时预览"""
    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("老婆 休息")
    res = await _collect(handle_rest(event, ctx))
    assert any("还没有老婆" in r[1] for r in res if r[0] == "plain")


async def test_rest_preview_lists_all_wives_with_cost(tmp_paths, config, lifespan_service):
    """预览列出所有老婆的修复价格"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([
        Ownership(wid="w_full", uid="u1", lifespan=100, is_dead=False),
        Ownership(wid="w_low", uid="u1", lifespan=40, is_dead=False),
        Ownership(wid="w_dead", uid="u1", lifespan=0, is_dead=True),
    ])
    WivesMasterStore(tmp_paths).save_all({
        "w_full": WifeMeta(wid="w_full", img="x.jpg", chara="满", rarity="N"),
        "w_low": WifeMeta(wid="w_low", img="x.jpg", chara="低", rarity="SR"),
        "w_dead": WifeMeta(wid="w_dead", img="x.jpg", chara="亡", rarity="SSR"),
    })
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": UserProfile(uid="u1", nick="Alice", coins=1000)})

    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("老婆 休息")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "修复价格表" in text
    assert "满血" in text
    assert "已离世" in text
    # SSR 死亡复活价 = 250 * 2 = 500
    assert "500 币" in text
    # SR 40/100 修复 = 120 * (2 - 0.4) = 192
    assert "192 币" in text


async def test_rest_confirm_revive_dead_wife(tmp_paths, config, lifespan_service):
    """指定编号复活死亡老婆"""
    from app.models.wife import WifeMeta
    from app.storage.stores import WivesMasterStore

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([
        Ownership(wid="w_d", uid="u1", lifespan=0, is_dead=True),
    ])
    WivesMasterStore(tmp_paths).save_all({
        "w_d": WifeMeta(wid="w_d", img="x.jpg", chara="亡", rarity="R"),
    })
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": UserProfile(uid="u1", nick="Alice", coins=500)})

    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("老婆 休息 1")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "复活成功" in text
    assert "100/100" in text
    # R base=60 * 2 = 120
    assert "120 币" in text

    p = ProfileStore(tmp_paths, "g1").load_all()["u1"]
    assert p.coins == 500 - 120
    o = OwnershipStore(tmp_paths, "g1").load_all()[0]
    assert o.is_dead is False
    assert o.lifespan == 100


async def test_rest_confirm_already_full(tmp_paths, config, lifespan_service):
    """满血修复 → already_full 提示"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_f", uid="u1", lifespan=100, is_dead=False)])
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": UserProfile(uid="u1", nick="Alice", coins=1000)})

    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("老婆 休息 1")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "满血" in text

    p = ProfileStore(tmp_paths, "g1").load_all()["u1"]
    assert p.coins == 1000  # 没扣


async def test_rest_confirm_insufficient_coins(tmp_paths, config, lifespan_service):
    """币不够复活"""
    from app.models.wife import WifeMeta
    from app.storage.stores import WivesMasterStore

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_d", uid="u1", lifespan=0, is_dead=True)])
    WivesMasterStore(tmp_paths).save_all({
        "w_d": WifeMeta(wid="w_d", img="x.jpg", chara="亡", rarity="SSR"),
    })
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": UserProfile(uid="u1", nick="Alice", coins=10)})

    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("老婆 复活 1")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "500 币" in text  # SSR 全价
    assert "只有 10 币" in text


async def test_rest_alias_yangkaolaopo(tmp_paths, config, lifespan_service):
    """养老婆 alias"""
    from app.models.wife import WifeMeta
    from app.storage.stores import WivesMasterStore

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_d", uid="u1", lifespan=0, is_dead=True)])
    WivesMasterStore(tmp_paths).save_all({
        "w_d": WifeMeta(wid="w_d", img="x.jpg", chara="亡", rarity="N"),
    })
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": UserProfile(uid="u1", nick="Alice", coins=100)})

    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("养老婆 1")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "复活成功" in text
    # N base=30 * 2 = 60
    assert "60 币" in text


async def test_rest_disabled_short_circuits(tmp_paths, locks):
    """lifespan_enabled=False 短路"""
    from app.services.plugin_config import PluginConfig
    cfg = PluginConfig(lifespan_enabled=False)
    lifespan = LifespanService(tmp_paths, cfg, locks)
    ctx = _build_ctx(tmp_paths, cfg, lifespan)
    event = _MockEvent("老婆 休息")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "未开启" in text


async def test_rest_invalid_index(tmp_paths, config, lifespan_service):
    """无效编号 → 报错"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_1", uid="u1", lifespan=100)])
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": UserProfile(uid="u1", nick="Alice", coins=1000)})

    ctx = _build_ctx(tmp_paths, config, lifespan_service)
    event = _MockEvent("老婆 休息 99")
    res = await _collect(handle_rest(event, ctx))
    text = "\n".join(r[1] for r in res if r[0] == "plain")
    assert "不存在" in text
