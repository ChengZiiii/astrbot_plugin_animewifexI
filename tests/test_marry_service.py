"""MarryService 单元测试。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.enums import AcquireVia
from app.models.ownership import Ownership
from app.models.profile import UserProfile
from app.services.marry_service import LOCK_DAYS, MarryService
from app.services.plugin_config import PluginConfig
from app.storage.paths import Paths
from app.storage.stores import OwnershipStore, ProfileStore


@pytest.fixture
def tmp_paths(tmp_path):
    return Paths(str(tmp_path))


@pytest.fixture
def config():
    return PluginConfig(
        initial_coins=200,
    )


@pytest.fixture
def marry(tmp_paths, config):
    return MarryService(tmp_paths, config)


def _seed_ownership(paths, gid, uid, wid, intimacy=0):
    store = OwnershipStore(paths, gid)
    ownerships = store.load_all()
    ownerships.append(Ownership(
        wid=wid, uid=uid, acquired_at=0,
        acquired_via=AcquireVia.DRAW, is_primary=True, intimacy=intimacy,
    ))
    store.save_all(ownerships)


def _seed_profile(paths, gid, uid, coins=200, lock_item=0):
    store = ProfileStore(paths, gid)
    profiles = store.load_all()
    p = UserProfile(uid=uid, nick="Alice", coins=coins)
    p.inventory["lock_item"] = lock_item
    profiles[uid] = p
    store.save_all(profiles)


class TestLock:
    def test_lock_success(self, marry, tmp_paths):
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_profile(tmp_paths, "g1", "u1", coins=200, lock_item=2)
        result = marry.lock_sync("g1", "u1", "w1", "Alice")
        assert result.ok is True
        assert "锁定成功" in result.msg

    def test_lock_no_item(self, marry, tmp_paths):
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_profile(tmp_paths, "g1", "u1", coins=200, lock_item=0)
        result = marry.lock_sync("g1", "u1", "w1")
        assert result.ok is False
        assert "没有锁定卡" in result.msg

    def test_lock_deducts_item(self, marry, tmp_paths):
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_profile(tmp_paths, "g1", "u1", coins=200, lock_item=2)
        marry.lock_sync("g1", "u1", "w1", "Alice")
        store = ProfileStore(tmp_paths, "g1")
        profiles = store.load_all()
        assert profiles["u1"].inventory["lock_item"] == 1


class TestUnlock:
    def test_unlock_success(self, marry, tmp_paths):
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_profile(tmp_paths, "g1", "u1", coins=200, lock_item=1)
        marry.lock_sync("g1", "u1", "w1")
        result = marry.unlock_sync("g1", "u1", "w1")
        assert result.ok is True
        assert "解锁成功" in result.msg

    def test_unlock_not_locked(self, marry, tmp_paths):
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        result = marry.unlock_sync("g1", "u1", "w1")
        assert result.ok is False
        assert "没有被锁定" in result.msg


class TestIsLocked:
    def test_not_locked(self, marry):
        o = Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via="draw")
        assert marry.is_locked(o) is False

    def test_permanent_lock(self, marry):
        o = Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via="draw", is_locked=True)
        assert marry.is_locked(o) is True

    def test_timed_lock_active(self, marry):
        o = Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via="draw", is_locked=True, lock_expires_at=int(time.time()) + 1000)
        assert marry.is_locked(o) is True

    def test_timed_lock_expired(self, marry):
        o = Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via="draw", is_locked=True, lock_expires_at=int(time.time()) - 100)
        assert marry.is_locked(o) is False
        # H4: is_locked 是纯检查，需要 clear_expired_lock 来清除过期状态
        cleared = marry.clear_expired_lock(o)
        assert cleared is True
        assert o.is_locked is False
