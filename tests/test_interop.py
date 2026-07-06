"""Tests for app.interop: WifeInterop facade with peek_wife."""

from __future__ import annotations

import pytest

from app.interop import WifeInterop, get_wife_interop, set_facade
from app.models.ownership import Ownership
from app.models.wife import WifeMeta
from app.storage.locks import GroupLocks
from app.storage.stores import OwnershipStore, WivesMasterStore


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
