"""PkService 单元测试。"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.enums import AcquireVia
from app.models.ownership import Ownership
from app.models.profile import UserProfile
from app.models.wife import BaseStats, WifeMeta
from app.services.pk_service import PkService
from app.services.plugin_config import PluginConfig
from app.storage.paths import Paths
from app.storage.stores import OwnershipStore, ProfileStore, WivesMasterStore


@pytest.fixture
def tmp_paths(tmp_path):
    return Paths(str(tmp_path))


@pytest.fixture
def config():
    return PluginConfig(
        initial_coins=0,
        pk_winner_reward=15,
        pk_cooldown=120,
        pk_max_per_day=5,
    )


@pytest.fixture
def pk_service(tmp_paths, config):
    svc = PkService(tmp_paths, config)
    svc.set_rng(random.Random(42))
    return svc


def _seed_wife(paths, wid, chara, rarity="N", atk=10, defense=10, hp=20):
    store = WivesMasterStore(paths)
    all_wives = store.load_all()
    all_wives[wid] = WifeMeta(
        wid=wid, img=f"{chara}.jpg", chara=chara, rarity=rarity,
        base_stats=BaseStats(atk=atk, defense=defense, hp=hp),
    )
    store.save_all(all_wives)


def _seed_ownership(paths, gid, uid, wid, is_primary=True):
    store = OwnershipStore(paths, gid)
    ownerships = store.load_all()
    ownerships.append(Ownership(
        wid=wid, uid=uid, acquired_at=0,
        acquired_via=AcquireVia.DRAW, is_primary=is_primary,
    ))
    store.save_all(ownerships)


def _seed_profile(paths, gid, uid, coins=0):
    store = ProfileStore(paths, gid)
    profiles = store.load_all()
    profiles[uid] = UserProfile(uid=uid, nick=f"User_{uid}", coins=coins)
    store.save_all(profiles)


class TestPk:
    def test_pk_attacker_wins(self, pk_service, tmp_paths):
        _seed_wife(tmp_paths, "w1", "强角色", "SSR", atk=50, defense=50, hp=100)
        _seed_wife(tmp_paths, "w2", "弱角色", "N", atk=5, defense=5, hp=10)
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_ownership(tmp_paths, "g1", "u2", "w2")
        _seed_profile(tmp_paths, "g1", "u1", coins=0)
        _seed_profile(tmp_paths, "g1", "u2", coins=0)

        result = pk_service.pk_sync("g1", "u1", "u2", "Alice", "Bob", "2026-07-03")
        assert result.ok is True
        # 强角色应该赢
        assert result.winner_uid == "u1"
        assert result.reward == 15

    def test_pk_no_wife(self, pk_service, tmp_paths):
        _seed_wife(tmp_paths, "w1", "角色A")
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_profile(tmp_paths, "g1", "u1")
        _seed_profile(tmp_paths, "g1", "u2")

        result = pk_service.pk_sync("g1", "u1", "u2", "Alice", "Bob", "2026-07-03")
        assert result.ok is False
        assert "对方还没有老婆" in result.msg

    def test_pk_self_no_wife(self, pk_service, tmp_paths):
        _seed_profile(tmp_paths, "g1", "u1")

        result = pk_service.pk_sync("g1", "u1", "u2", "Alice", "Bob", "2026-07-03")
        assert result.ok is False
        assert "你还没有老婆" in result.msg

    def test_pk_winner_receives_reward(self, pk_service, tmp_paths):
        _seed_wife(tmp_paths, "w1", "强", "SR", atk=30, defense=30, hp=60)
        _seed_wife(tmp_paths, "w2", "弱", "N", atk=5, defense=5, hp=10)
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_ownership(tmp_paths, "g1", "u2", "w2")
        _seed_profile(tmp_paths, "g1", "u1", coins=0)
        _seed_profile(tmp_paths, "g1", "u2", coins=0)

        pk_service.pk_sync("g1", "u1", "u2", "Alice", "Bob", "2026-07-03")

        store = ProfileStore(tmp_paths, "g1")
        profiles = store.load_all()
        assert profiles["u1"].coins == 15  # winner gets reward

    def test_pk_draws_added_to_collection(self, pk_service, tmp_paths):
        _seed_wife(tmp_paths, "w1", "强", "SR", atk=30, defense=30, hp=60)
        _seed_wife(tmp_paths, "w2", "弱", "N", atk=5, defense=5, hp=10)
        _seed_ownership(tmp_paths, "g1", "u1", "w1")
        _seed_ownership(tmp_paths, "g1", "u2", "w2")
        _seed_profile(tmp_paths, "g1", "u1", coins=0)
        _seed_profile(tmp_paths, "g1", "u2", coins=0)

        pk_service.pk_sync("g1", "u1", "u2", "Alice", "Bob", "2026-07-03")

        store = ProfileStore(tmp_paths, "g1")
        profiles = store.load_all()
        # Winner should have loser's wid in collection
        assert "w2" in profiles["u1"].collection


class TestCalcPower:
    def test_power_formula(self, pk_service):
        wife = WifeMeta(wid="w1", img="test.jpg", base_stats=BaseStats(atk=10, defense=20, hp=30))
        ownership = Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via="draw", intimacy=5)
        power = pk_service._calc_power(wife, ownership)
        # 10 + 20 + 30*0.5 + 5*2 = 55
        assert power == 55.0

    def test_power_no_wife(self, pk_service):
        assert pk_service._calc_power(None, None) == 0
