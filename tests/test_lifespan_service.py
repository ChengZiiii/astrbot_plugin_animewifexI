"""Tests for app.services.lifespan_service: 公式 + apply_damage + apply_revive + 死亡流程。"""

from __future__ import annotations

import pytest

from app.models.ownership import Ownership
from app.services.lifespan_service import (
    DEATH_CAUSE_IMPACT,
    DEATH_CAUSE_PK,
    DEATH_CAUSE_WORK,
    LifespanService,
    calc_death_probability,
    calc_revive_cost,
    calc_revive_urgency,
    format_lifespan_bar,
)
from app.storage.stores import OwnershipStore, ProfileStore


# ==================== 纯函数公式 ====================


def test_death_probability_zero_lifespan_is_one():
    """寿命=0 必死亡（基础公式 = 1.0）"""
    p = calc_death_probability(0, 100, 0.5)
    assert p == 1.0


def test_death_probability_max_lifespan_is_zero():
    """满血不会死"""
    p = calc_death_probability(100, 100, 0.5)
    assert p == 0.0


def test_death_probability_increases_as_lifespan_drops():
    """寿命越低死亡概率越高（单调）"""
    p100 = calc_death_probability(100, 100, 0.5)
    p80 = calc_death_probability(80, 100, 0.5)
    p50 = calc_death_probability(50, 100, 0.5)
    p20 = calc_death_probability(20, 100, 0.5)
    p10 = calc_death_probability(10, 100, 0.5)
    assert p100 == 0
    assert p80 < p50 < p20
    # 默认 base=0.5: lifespan=20 → 0.32; lifespan=50 → 0.125
    assert abs(p50 - 0.125) < 1e-9
    assert abs(p20 - 0.32) < 1e-9


def test_death_probability_clamps_to_unit():
    """p 不能 > 1（base > 1 也安全）"""
    p = calc_death_probability(50, 100, 5.0)
    assert 0.0 <= p <= 1.0


def test_revive_urgency_full_is_one():
    assert calc_revive_urgency(100, 100) == 1.0


def test_revive_urgency_zero_is_two():
    assert calc_revive_urgency(0, 100) == 2.0


def test_revive_urgency_monotonic():
    """紧急度随寿命降低而升高"""
    u100 = calc_revive_urgency(100, 100)
    u50 = calc_revive_urgency(50, 100)
    u10 = calc_revive_urgency(10, 100)
    assert u100 < u50 < u10
    assert u10 <= 2.0


def test_revive_cost_full_is_zero():
    """满血不花钱"""
    cost = calc_revive_cost("SSR", 100, 100, {"N": 30, "R": 60, "SR": 120, "SSR": 250})
    assert cost == 0


def test_revive_cost_zero_lifespan_double_base():
    """lifespan=0 复活 = 2x 基础价"""
    cost = calc_revive_cost("SSR", 0, 100, {"N": 30, "R": 60, "SR": 120, "SSR": 250})
    assert cost == 500  # 250 * 2.0


def test_revive_cost_half_lifespan_one_and_a_half():
    cost = calc_revive_cost("SR", 50, 100, {"N": 30, "R": 60, "SR": 120, "SSR": 250})
    assert cost == int(120 * 1.5)  # 180


def test_revive_cost_unknown_rarity_is_zero():
    cost = calc_revive_cost("???", 10, 100, {"N": 30, "R": 60, "SR": 120, "SSR": 250})
    assert cost == 0


def test_format_lifespan_bar_dead():
    bar = format_lifespan_bar(0, 100, is_dead=True)
    assert "☠️" in bar
    assert "0/100" in bar


def test_format_lifespan_bar_full():
    bar = format_lifespan_bar(100, 100)
    assert "100/100" in bar
    assert bar.count("█") == 10


def test_format_lifespan_bar_half():
    bar = format_lifespan_bar(50, 100, width=10)
    assert "50/100" in bar
    assert bar.count("█") == 5
    assert bar.count("░") == 5


# ==================== apply_damage ====================


async def test_apply_damage_basic(tmp_paths, config, locks, lifespan_service):
    """普通扣减不触发死亡（roll_seed=1.0 → 不会死）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_a", uid="u1", lifespan=100, is_dead=False)])

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_damage(
            "g1", "w_a", 10, cause=DEATH_CAUSE_WORK,
            today="2026-07-12", roll_seed=1.0,  # 强制不死亡
        )
    )

    assert res.ok
    assert res.death_occurred is False
    assert res.new_lifespan == 90

    reloaded = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded[0].lifespan == 90
    assert reloaded[0].is_dead is False


async def test_apply_damage_triggers_death_when_lifespan_zero(tmp_paths, config, locks, lifespan_service):
    """扣到 0 必死亡（不等概率）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_d", uid="u1", lifespan=5, is_dead=False)])

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_damage(
            "g1", "w_d", 10, cause=DEATH_CAUSE_WORK,
            today="2026-07-12", roll_seed=1.0,
        )
    )

    assert res.ok
    assert res.death_occurred is True
    assert res.new_lifespan == 0

    reloaded = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded[0].is_dead is True
    assert reloaded[0].lifespan == 0
    assert reloaded[0].death_date == "2026-07-12"
    assert reloaded[0].death_cause == DEATH_CAUSE_WORK


async def test_apply_damage_force_roll_death(tmp_paths, config, locks, lifespan_service):
    """roll_seed=0.0 + 中等寿命 → 强制死亡（任意 < base 都会死）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_m", uid="u1", lifespan=50, is_dead=False)])

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_damage(
            "g1", "w_m", 1, cause=DEATH_CAUSE_PK,
            today="2026-07-12", roll_seed=0.0,
        )
    )
    # 扣 1 后 lifespan=49；ratio=0.51；p = 0.5 × 0.51² = 0.13005
    # roll=0.0 < 0.13005 → 死亡
    assert res.ok
    assert res.death_occurred is True
    assert abs(res.rolled_probability - 0.13005) < 1e-9
    assert res.new_lifespan == 49

    reloaded = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded[0].is_dead is True
    assert reloaded[0].death_cause == DEATH_CAUSE_PK


async def test_apply_damage_skip_already_dead(tmp_paths, config, locks, lifespan_service):
    """已经死亡的老婆不再处理"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(
        wid="w_dead", uid="u1", lifespan=0, is_dead=True,
        death_date="2026-07-11", death_cause=DEATH_CAUSE_WORK,
    )])

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_damage(
            "g1", "w_dead", 5, cause=DEATH_CAUSE_WORK,
            today="2026-07-12", roll_seed=0.0,
        )
    )
    assert res.ok is False
    assert res.reason == "already_dead"
    # 状态没变
    reloaded = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded[0].is_dead is True
    assert reloaded[0].death_date == "2026-07-11"  # 没被覆盖


async def test_apply_damage_no_damage_when_delta_zero(tmp_paths, config, locks, lifespan_service):
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_a", uid="u1", lifespan=100, is_dead=False)])

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_damage(
            "g1", "w_a", 0, cause=DEATH_CAUSE_WORK,
        )
    )
    assert res.ok is False
    assert res.reason == "no_damage"


async def test_apply_damage_disabled_via_config(tmp_paths, locks):
    """lifespan_enabled=False 短路所有操作"""
    from app.services.plugin_config import PluginConfig
    cfg = PluginConfig(lifespan_enabled=False)
    svc = LifespanService(tmp_paths, cfg, locks)
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_a", uid="u1", lifespan=100, is_dead=False)])

    res = await _call_with_lock(
        svc, "g1",
        lambda: svc.apply_damage("g1", "w_a", 10),
    )
    assert res.ok is False
    assert res.reason == "disabled"


async def test_apply_damage_increments_total_death_counter(tmp_paths, config, locks, lifespan_service):
    """死亡时 profile.total_wife_deaths += 1"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_d", uid="u1", lifespan=5, is_dead=False)])

    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": _make_profile("u1", "Alice")})

    await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_damage(
            "g1", "w_d", 10, cause=DEATH_CAUSE_WORK, today="2026-07-12",
        )
    )
    p = ProfileStore(tmp_paths, "g1").load_all()["u1"]
    assert p.total_wife_deaths == 1


# ==================== apply_revive ====================


async def test_apply_revive_revives_dead_wife(tmp_paths, config, locks, lifespan_service):
    """复活已死亡老婆：清 is_dead，满血，扣币"""
    from app.models.wife import WifeMeta
    from app.storage.stores import WivesMasterStore

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(
        wid="w_d", uid="u1", lifespan=0, is_dead=True,
        death_date="2026-07-11", death_cause=DEATH_CAUSE_WORK,
    )])
    WivesMasterStore(tmp_paths).save_all({
        "w_d": WifeMeta(wid="w_d", img="x.jpg", chara="X", rarity="SSR"),
    })
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": _make_profile("u1", "Alice", coins=1000)})

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_revive("g1", "u1", "Alice", "w_d", target_wid="w_d"),
    )
    assert res.ok
    assert res.was_dead is True
    assert res.new_lifespan == 100  # 满血
    # SSR rarity base=250 * 2 = 500
    assert res.cost == 500
    assert res.coin_balance == 500

    reloaded_o = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded_o[0].is_dead is False
    assert reloaded_o[0].lifespan == 100
    assert reloaded_o[0].death_date == ""  # 清

    p = ProfileStore(tmp_paths, "g1").load_all()["u1"]
    assert p.coins == 500
    assert p.total_lifespan_restored == 1
    assert p.total_coins_spent_on_revive == 500


async def test_apply_revive_partial_restore(tmp_paths, config, locks, lifespan_service):
    """修复半血老婆：清到 max，按当前 lifespan 算价格"""
    from app.models.wife import WifeMeta
    from app.storage.stores import WivesMasterStore

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_p", uid="u1", lifespan=50, is_dead=False)])
    WivesMasterStore(tmp_paths).save_all({
        "w_p": WifeMeta(wid="w_p", img="x.jpg", chara="X", rarity="SR"),
    })
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": _make_profile("u1", "Alice", coins=1000)})

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_revive("g1", "u1", "Alice", "w_p", target_wid="w_p"),
    )
    assert res.ok
    assert res.was_dead is False
    assert res.new_lifespan == 100
    # SR rarity base=120 × (2 - 50/100) = 120 × 1.5 = 180
    assert res.cost == 180


async def test_apply_revive_already_full(tmp_paths, config, locks, lifespan_service):
    """满血老婆修复 → already_full 拒绝（不扣币）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_full", uid="u1", lifespan=100, is_dead=False)])
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": _make_profile("u1", "Alice", coins=1000)})

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_revive("g1", "u1", "Alice", "w_full", target_wid="w_full"),
    )
    assert res.ok is False
    assert res.reason == "already_full"
    p = ProfileStore(tmp_paths, "g1").load_all()["u1"]
    assert p.coins == 1000  # 没扣


async def test_apply_revive_not_enough_coins(tmp_paths, config, locks, lifespan_service):
    """币不够复活 → 拒绝"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_d", uid="u1", lifespan=0, is_dead=True)])
    profile_store = ProfileStore(tmp_paths, "g1")
    profile_store.save_all({"u1": _make_profile("u1", "Alice", coins=10)})

    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_revive("g1", "u1", "Alice", "w_d", target_wid="w_d"),
    )
    assert res.ok is False
    assert res.reason == "not_enough_coins"
    p = ProfileStore(tmp_paths, "g1").load_all()["u1"]
    assert p.coins == 10  # 没扣


async def test_apply_revive_wife_not_found(tmp_paths, config, locks, lifespan_service):
    res = await _call_with_lock(
        lifespan_service, "g1",
        lambda: lifespan_service.apply_revive("g1", "u1", "Alice", "w_xx", target_wid="w_xx"),
    )
    assert res.ok is False
    assert res.reason == "wife_not_found"


# ==================== query / quote ====================


async def test_query_lifespan_alive(tmp_paths, config, lifespan_service):
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_q", uid="u1", lifespan=80, is_dead=False)])
    res = lifespan_service.query_lifespan("g1", "w_q")
    assert res["ok"]
    assert res["current"] == 80
    assert res["max"] == 100
    assert res["is_dead"] is False


async def test_query_lifespan_dead(tmp_paths, config, lifespan_service):
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(
        wid="w_d", uid="u1", lifespan=0, is_dead=True,
        death_date="2026-07-12", death_cause=DEATH_CAUSE_WORK,
    )])
    res = lifespan_service.query_lifespan("g1", "w_d")
    assert res["ok"]
    assert res["is_dead"] is True
    assert res["death_cause"] == DEATH_CAUSE_WORK


async def test_quote_revive_cost(tmp_paths, config, lifespan_service):
    """quote_revive_cost 只读，不持锁"""
    from app.models.wife import WifeMeta
    from app.storage.stores import WivesMasterStore

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_q", uid="u1", lifespan=30, is_dead=False)])
    WivesMasterStore(tmp_paths).save_all({
        "w_q": WifeMeta(wid="w_q", img="x.jpg", chara="X", rarity="R"),
    })

    res = lifespan_service.quote_revive_cost("g1", "w_q")
    assert res["ok"]
    assert res["current"] == 30
    assert res["rarity"] == "R"
    # R base=60 × (2 - 0.3) = 60 × 1.7 = 102
    assert res["cost"] == 102


# ==================== 工具 ====================


def _make_profile(uid, nick, coins=100):
    from app.models.profile import UserProfile
    return UserProfile(uid=uid, nick=nick, coins=coins)


async def _call_with_lock(svc, gid, fn):
    """包装：在 lifespan_service 的群锁内调用 fn()"""
    async with svc._locks.acquire(gid):
        return fn()
