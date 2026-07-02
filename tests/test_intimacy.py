"""亲密度系统单元测试。"""

from __future__ import annotations

import pytest

from app.models.ownership import Ownership
from app.services.ownership_service import OwnershipService
from app.services.plugin_config import PluginConfig
from app.storage.stores import OwnershipStore, ProfileStore
from app.utils.time import now_ts


@pytest.fixture
def config_with_intimacy():
    return PluginConfig(
        intimacy_per_day=10,
        intimacy_max=100,
        intimacy_pet_coin_cost=5,
        intimacy_pet_gain=3,
        intimacy_gift_coin_cost=30,
        intimacy_gift_gain=20,
        initial_coins=100,
    )


@pytest.fixture
def intimacy_service(tmp_paths, config_with_intimacy, locks, mock_wife_service):
    return OwnershipService(
        paths=tmp_paths,
        config=config_with_intimacy,
        locks=locks,
        wife_service=mock_wife_service,
    )


class TestPetWife:
    @pytest.mark.asyncio
    async def test_pet_success(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        result = await intimacy_service.pet_wife(gid, "u1", "Alice", today)
        assert result.ok
        assert result.intimacy == 3  # intimacy_pet_gain
        assert result.coin_balance == 95  # 100 - 5

    @pytest.mark.asyncio
    async def test_pet_no_wife_fails(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        result = await intimacy_service.pet_wife(gid, "u1", "Alice", today)
        assert result.ok is False
        assert result.reason == "no_wife"

    @pytest.mark.asyncio
    async def test_pet_not_enough_coins(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        # Drain coins
        ps = ProfileStore(tmp_paths, gid)
        profiles = ps.load_all()
        profiles["u1"].coins = 2
        ps.save_all(profiles)

        result = await intimacy_service.pet_wife(gid, "u1", "Alice", today)
        assert result.ok is False
        assert result.reason == "not_enough_coins"
        assert result.coin_balance == 2

    @pytest.mark.asyncio
    async def test_pet_intimacy_maxed(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        # Set intimacy to max
        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                o.intimacy = 100
                o.intimacy_updated_date = today
        store.save_all(ownerships)

        result = await intimacy_service.pet_wife(gid, "u1", "Alice", today)
        assert result.ok is False
        assert result.reason == "intimacy_maxed"

    @pytest.mark.asyncio
    async def test_pet_caps_at_max(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        # Set intimacy close to max
        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                o.intimacy = 99
                o.intimacy_updated_date = today
        store.save_all(ownerships)

        result = await intimacy_service.pet_wife(gid, "u1", "Alice", today)
        assert result.ok
        assert result.intimacy == 100  # capped at max


class TestGiftWife:
    @pytest.mark.asyncio
    async def test_gift_success(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        result = await intimacy_service.gift_wife(gid, "u1", "Alice", today)
        assert result.ok
        assert result.intimacy == 20  # intimacy_gift_gain
        assert result.coin_balance == 70  # 100 - 30

    @pytest.mark.asyncio
    async def test_gift_not_enough_coins(self, intimacy_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        ps = ProfileStore(tmp_paths, gid)
        profiles = ps.load_all()
        profiles["u1"].coins = 10
        ps.save_all(profiles)

        result = await intimacy_service.gift_wife(gid, "u1", "Alice", today)
        assert result.ok is False
        assert result.reason == "not_enough_coins"


class TestDailyIntimacyIncrement:
    @pytest.mark.asyncio
    async def test_daily_increment(self, intimacy_service, tmp_paths):
        gid = "g1"
        today = "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        updated = await intimacy_service.daily_intimacy_increment_for_group(gid, today)
        assert updated == 1

        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                assert o.intimacy == 10  # intimacy_per_day
                assert o.intimacy_updated_date == today
                break

    @pytest.mark.asyncio
    async def test_daily_increment_idempotent(self, intimacy_service, tmp_paths):
        """同一天不会重复加"""
        gid = "g1"
        today = "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        await intimacy_service.daily_intimacy_increment_for_group(gid, today)
        updated2 = await intimacy_service.daily_intimacy_increment_for_group(gid, today)
        assert updated2 == 0  # Already incremented today

        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                assert o.intimacy == 10  # Still 10, not 20
                break

    @pytest.mark.asyncio
    async def test_daily_increment_caps_at_max(self, intimacy_service, tmp_paths):
        gid = "g1"
        today = "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        # Set intimacy near max
        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                o.intimacy = 95
                o.intimacy_updated_date = ""  # Not today
        store.save_all(ownerships)

        await intimacy_service.daily_intimacy_increment_for_group(gid, today)

        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                assert o.intimacy == 100  # Capped at max
                break


class TestIntimacyLevel:
    def test_level_0(self):
        assert OwnershipService.intimacy_level(0) == 0
        assert OwnershipService.intimacy_level(-1) == 0

    def test_level_1(self):
        assert OwnershipService.intimacy_level(1) == 1
        assert OwnershipService.intimacy_level(10) == 1

    def test_level_2(self):
        assert OwnershipService.intimacy_level(11) == 2
        assert OwnershipService.intimacy_level(20) == 2

    def test_level_10(self):
        assert OwnershipService.intimacy_level(91) == 10
        assert OwnershipService.intimacy_level(100) == 10

    def test_level_caps_at_10(self):
        assert OwnershipService.intimacy_level(200) == 10

    def test_level_emoji(self):
        assert OwnershipService.intimacy_level_emoji(0) == ""
        assert "Lv.1" in OwnershipService.intimacy_level_emoji(1)
        assert "Lv.10" in OwnershipService.intimacy_level_emoji(100)
