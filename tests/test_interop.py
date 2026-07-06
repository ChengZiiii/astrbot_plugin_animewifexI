"""Tests for app.interop: WifeInterop facade (peek_wife, compute_ntr_resistance, record_sex_act)."""

from __future__ import annotations

import asyncio

import pytest

from app.interop import WifeInterop, get_wife_interop, set_facade
from app.models.ownership import Ownership
from app.models.wife import WifeMeta
from app.storage.locks import GroupLocks
from app.storage.stores import OwnershipStore, ProfileStore, WivesMasterStore


async def test_peek_wife_primary(tmp_paths, config):
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([
        Ownership(wid="w_abc12345", uid="u1", intimacy=60, is_primary=True),
    ])
    WivesMasterStore(tmp_paths).save_all({
        "w_abc12345": WifeMeta(
            wid="w_abc12345", img="x!y.jpg", source="x", chara="y", rarity="R",
        ),
    })
    interop = WifeInterop(
        ownership_service=None, locks=GroupLocks(), config=config, paths=tmp_paths,
    )
    res = await interop.peek_wife("g1", "u1")
    assert res["wid"] == "w_abc12345"
    assert res["is_primary"] is True
    assert res["level"] == 4  # intimacy 60 -> Lv4


async def test_peek_wife_no_primary_falls_back_to_first(tmp_paths, config):
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([
        Ownership(wid="w_first", uid="u1", intimacy=10, is_primary=False),
        Ownership(wid="w_second", uid="u1", intimacy=20, is_primary=False),
    ])
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.peek_wife("g1", "u1")  # index=None, no primary
    assert res["wid"] == "w_first"  # falls back to first
    assert res["is_primary"] is False


async def test_peek_wife_index_selects_nth(tmp_paths, config):
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([
        Ownership(wid="w_a", uid="u1", is_primary=True),
        Ownership(wid="w_b", uid="u1", is_primary=False),
    ])
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    assert (await interop.peek_wife("g1", "u1", index=2))["wid"] == "w_b"
    assert (await interop.peek_wife("g1", "u1", index=99)) == {}  # out of bounds


async def test_peek_wife_no_wives_returns_empty(tmp_paths, config):
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    assert (await interop.peek_wife("g1", "nobody")) == {}


def test_get_wife_interop_raises_when_not_set():
    set_facade(None)  # reset
    with pytest.raises(RuntimeError):
        get_wife_interop()


def test_set_facade_and_get(tmp_paths, config):
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    set_facade(interop)
    assert get_wife_interop() is interop
    set_facade(None)  # cleanup


# ==================== compute_ntr_resistance ====================


@pytest.mark.asyncio
async def test_resistance_locked_wife(tmp_paths, config):
    """锁定的老婆 → locked=True，resistance=1.0（锁定已前置拒绝，乘积不叠加）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    locked = Ownership(wid="w_l", uid="u1", intimacy=10, is_locked=True, lock_expires_at=9999999999)
    os_store.save_all([locked])
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "w_l")
    assert res["locked"] is True
    assert res["resistance"] == 1.0
    assert res["target_owner_uid"] == "u1"


@pytest.mark.asyncio
async def test_resistance_shield_lowers(tmp_paths, config):
    """亲密度 ≥ 60 → shielded=True，resistance 乘以 intimacy_shield_reduction"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_s", uid="u1", intimacy=70)])  # Lv4 → shield
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "w_s")
    assert res["shielded"] is True
    assert res["intimacy"] == 70
    assert res["level"] == 4  # intimacy 70 → Lv4 (60-79 range)
    # config default: intimacy_shield_reduction = 0.30
    assert abs(res["resistance"] - 0.30) < 1e-9


@pytest.mark.asyncio
async def test_resistance_no_shield(tmp_paths, config):
    """亲密度 < 60 → shielded=False，resistance=1.0"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_ns", uid="u1", intimacy=40)])  # Lv3, no shield
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "w_ns")
    assert res["shielded"] is False
    assert res["resistance"] == 1.0


@pytest.mark.asyncio
async def test_resistance_working_wife(tmp_paths, config):
    """打工中的老婆 → working=True，resistance 乘以 work_modes[mode].ntr_multiplier"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_w", uid="u1", intimacy=10, is_working=True, work_mode="normal")])
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "w_w")
    assert res["working"] is True
    # config default: work_modes.normal.ntr_multiplier = 1.5
    assert abs(res["resistance"] - 1.5) < 1e-9


@pytest.mark.asyncio
async def test_resistance_protection_charm(tmp_paths, config):
    """目标 owner 背包有 protection_charm → has_charm=True，resistance ×0.3"""
    from app.models.profile import UserProfile

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_c", uid="u1", intimacy=10)])
    # 写入 owner profile，带 protection_charm
    profiles = {"u1": UserProfile(uid="u1", inventory={"protection_charm": 1})}
    ProfileStore(tmp_paths, "g1").save_all(profiles)
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "w_c")
    assert res["has_charm"] is True
    assert abs(res["resistance"] - 0.30) < 1e-9


@pytest.mark.asyncio
async def test_resistance_combined_factors(tmp_paths, config):
    """多个因子叠加：shield + work + charm"""
    from app.models.profile import UserProfile

    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_combo", uid="u1", intimacy=80, is_working=True, work_mode="overtime")])
    profiles = {"u1": UserProfile(uid="u1", inventory={"protection_charm": 2})}
    ProfileStore(tmp_paths, "g1").save_all(profiles)
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "w_combo")
    assert res["shielded"] is True
    assert res["working"] is True
    assert res["has_charm"] is True
    # shield(0.3) * work_overtime(2.0) * charm(0.3) = 0.18
    assert abs(res["resistance"] - 0.18) < 1e-9


@pytest.mark.asyncio
async def test_resistance_wife_not_found(tmp_paths, config):
    """老婆不存在 → 返回空 dict"""
    interop = WifeInterop(None, GroupLocks(), config, tmp_paths)
    res = await interop.compute_ntr_resistance("g1", "nonexistent")
    assert res == {}


# ==================== record_sex_act ====================


async def test_record_sex_act_increments_intimacy(tmp_paths, config, ownership_service):
    """亲密度增加 delta，持久化到磁盘"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_r", uid="u1", intimacy=10)])
    interop = WifeInterop(ownership_service, GroupLocks(), config, tmp_paths)

    res = await interop.record_sex_act("g1", "w_r", "u_actor", False, 5)

    assert res["ok"] is True
    assert res["new_intimacy"] == 15
    assert res["level"] == 1
    assert res["level_name"] == "相识"

    reloaded = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded[0].intimacy == 15


async def test_record_sex_act_does_not_transfer_ownership(tmp_paths, config, ownership_service):
    """NTR 场景下 uid 不变（不转移所有权）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_ntr", uid="u_victim", intimacy=10)])
    interop = WifeInterop(ownership_service, GroupLocks(), config, tmp_paths)

    await interop.record_sex_act("g1", "w_ntr", "u_attacker", True, 5)

    reloaded = OwnershipStore(tmp_paths, "g1").load_all()
    assert reloaded[0].uid == "u_victim"


async def test_record_sex_act_concurrent_no_lost_update(tmp_paths, config, ownership_service):
    """10 个并发 +1 → 亲密度 = 10（GroupLocks 序列化保证无丢失更新）"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([Ownership(wid="w_c", uid="u1", intimacy=0)])
    locks = GroupLocks()
    interop = WifeInterop(ownership_service, locks, config, tmp_paths)

    results = await asyncio.gather(*(
        interop.record_sex_act("g1", "w_c", f"u_{i}", False, 1)
        for i in range(10)
    ))

    final = OwnershipStore(tmp_paths, "g1").load_all()
    assert final[0].intimacy == 10


async def test_record_sex_act_locked_wife_fails(tmp_paths, config, ownership_service):
    """锁定中的老婆 → ok=False"""
    os_store = OwnershipStore(tmp_paths, "g1")
    os_store.save_all([
        Ownership(wid="w_lk", uid="u1", intimacy=10, is_locked=True, lock_expires_at=9999999999),
    ])
    interop = WifeInterop(ownership_service, GroupLocks(), config, tmp_paths)

    res = await interop.record_sex_act("g1", "w_lk", "u_actor", False, 5)

    assert res["ok"] is False


async def test_record_sex_act_wife_not_found(tmp_paths, config, ownership_service):
    """不存在的 wid → ok=False"""
    interop = WifeInterop(ownership_service, GroupLocks(), config, tmp_paths)

    res = await interop.record_sex_act("g1", "nonexistent", "u_actor", False, 5)

    assert res["ok"] is False
