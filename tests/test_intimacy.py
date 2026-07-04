"""亲密度系统单元测试。"""

from __future__ import annotations

import pytest

from app.models.enums import Action
from app.models.ownership import Ownership
from app.services.ownership_service import OwnershipService
from app.services.plugin_config import PluginConfig
from app.storage.stores import ActivityStore, OwnershipStore, ProfileStore
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
        # 0→20: Lv.1→Lv.2, 奖励 20 币
        assert result.coin_balance == 90  # 100 - 30 + 20 (Lv.2 reward)

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
        assert OwnershipService.intimacy_level(0) == 1
        assert OwnershipService.intimacy_level(-1) == 1

    def test_level_1(self):
        assert OwnershipService.intimacy_level(1) == 1
        assert OwnershipService.intimacy_level(10) == 1
        assert OwnershipService.intimacy_level(19) == 1

    def test_level_2(self):
        assert OwnershipService.intimacy_level(20) == 2
        assert OwnershipService.intimacy_level(39) == 2

    def test_level_3(self):
        assert OwnershipService.intimacy_level(40) == 3
        assert OwnershipService.intimacy_level(59) == 3

    def test_level_4(self):
        assert OwnershipService.intimacy_level(60) == 4
        assert OwnershipService.intimacy_level(79) == 4

    def test_level_5(self):
        assert OwnershipService.intimacy_level(80) == 5
        assert OwnershipService.intimacy_level(100) == 5

    def test_level_caps_at_5(self):
        assert OwnershipService.intimacy_level(200) == 5

    def test_level_emoji(self):
        assert "Lv.1" in OwnershipService.intimacy_level_emoji(0)
        assert "Lv.1" in OwnershipService.intimacy_level_emoji(1)
        assert "Lv.5" in OwnershipService.intimacy_level_emoji(100)

    def test_get_intimacy_level_no(self):
        assert OwnershipService.get_intimacy_level_no(0) == 1
        assert OwnershipService.get_intimacy_level_no(19) == 1
        assert OwnershipService.get_intimacy_level_no(20) == 2
        assert OwnershipService.get_intimacy_level_no(40) == 3
        assert OwnershipService.get_intimacy_level_no(60) == 4
        assert OwnershipService.get_intimacy_level_no(80) == 5
        assert OwnershipService.get_intimacy_level_no(100) == 5

    def test_get_intimacy_level_name(self):
        assert OwnershipService.get_intimacy_level_name(0) == "相识"
        assert OwnershipService.get_intimacy_level_name(20) == "熟悉"
        assert OwnershipService.get_intimacy_level_name(40) == "亲密"
        assert OwnershipService.get_intimacy_level_name(60) == "挚爱"
        assert OwnershipService.get_intimacy_level_name(80) == "灵魂伴侣"

    def test_get_intimacy_bonus_ratio(self):
        assert OwnershipService.get_intimacy_bonus_ratio(0) == 1.0
        assert OwnershipService.get_intimacy_bonus_ratio(20) == 1.05
        assert OwnershipService.get_intimacy_bonus_ratio(40) == 1.10
        assert OwnershipService.get_intimacy_bonus_ratio(60) == 1.15
        assert OwnershipService.get_intimacy_bonus_ratio(80) == 1.20

    def test_has_intimacy_shield(self):
        assert OwnershipService.has_intimacy_shield(0) is False
        assert OwnershipService.has_intimacy_shield(20) is False
        assert OwnershipService.has_intimacy_shield(40) is False
        assert OwnershipService.has_intimacy_shield(60) is True
        assert OwnershipService.has_intimacy_shield(80) is True


class TestIntimacyLevelupReward:
    """T12: 亲密度升级奖励和行为日志"""

    @pytest.mark.asyncio
    async def test_pet_writes_activity_log(self, intimacy_service, tmp_paths):
        """摸头写 Action.INTIMACY 日志"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        await intimacy_service.pet_wife(gid, "u1", "Alice", today)

        store = ActivityStore(tmp_paths, gid)
        logs = store.load_all()
        assert "u1" in logs
        assert logs["u1"].days.get(today, {}).get(Action.INTIMACY, 0) == 1

    @pytest.mark.asyncio
    async def test_gift_writes_activity_log(self, intimacy_service, tmp_paths):
        """送礼写 Action.INTIMACY 日志"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        await intimacy_service.gift_wife(gid, "u1", "Alice", today)

        store = ActivityStore(tmp_paths, gid)
        logs = store.load_all()
        assert "u1" in logs
        assert logs["u1"].days.get(today, {}).get(Action.INTIMACY, 0) == 1

    @pytest.mark.asyncio
    async def test_levelup_from_1_to_2(self, tmp_paths, locks, mock_wife_service):
        """从 Lv.1 升级到 Lv.2 获得 20 币奖励"""
        config = PluginConfig(
            intimacy_per_day=10,
            intimacy_max=100,
            intimacy_pet_coin_cost=5,
            intimacy_pet_gain=25,  # 每次 +25
            initial_coins=100,
        )
        service = OwnershipService(
            paths=tmp_paths, config=config, locks=locks,
            wife_service=mock_wife_service,
        )
        gid, today = "g1", "2026-07-04"
        await service.draw_or_get_primary(gid, "u1", "Alice", today)

        # 第一次摸头：0 → 25 (Lv.1→Lv.2, 奖励 20 币)
        result1 = await service.pet_wife(gid, "u1", "Alice", today)
        assert result1.ok
        assert result1.coin_balance == 115  # 100 - 5 + 20 (Lv.2 reward)

        # 第二次摸头：25 → 50 (Lv.2→Lv.3, 奖励 50 币)
        result2 = await service.pet_wife(gid, "u1", "Alice", today)
        assert result2.ok
        # 115 - 5 (pet cost) + 50 (Lv.3 reward) = 160
        assert result2.coin_balance == 160


class TestChatDateWife:
    """T13: 对话/约会 service 方法"""

    @pytest.mark.asyncio
    async def test_chat_success(self, intimacy_service, tmp_paths):
        """对话成功：+1 亲密度，+5 币"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        result = await intimacy_service.chat_wife(gid, "u1", "Alice", today)
        assert result.ok
        assert result.intimacy == 1  # chat_intimacy_gain
        assert result.coin_balance == 105  # 100 + 5

    @pytest.mark.asyncio
    async def test_chat_no_wife_fails(self, intimacy_service):
        """无老婆对话失败"""
        result = await intimacy_service.chat_wife("g1", "u1", "Alice", "2026-07-04")
        assert result.ok is False
        assert result.reason == "no_wife"

    @pytest.mark.asyncio
    async def test_chat_intimacy_maxed(self, intimacy_service, tmp_paths):
        """亲密度满时对话失败"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                o.intimacy = 100
        store.save_all(ownerships)

        result = await intimacy_service.chat_wife(gid, "u1", "Alice", today)
        assert result.ok is False
        assert result.reason == "intimacy_maxed"

    @pytest.mark.asyncio
    async def test_chat_writes_activity_log(self, intimacy_service, tmp_paths):
        """对话写 Action.CHAT 和 Action.INTIMACY 日志"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        await intimacy_service.chat_wife(gid, "u1", "Alice", today)

        store = ActivityStore(tmp_paths, gid)
        logs = store.load_all()
        assert logs["u1"].days.get(today, {}).get(Action.CHAT, 0) == 1
        assert logs["u1"].days.get(today, {}).get(Action.INTIMACY, 0) == 1

    @pytest.mark.asyncio
    async def test_date_success(self, intimacy_service, tmp_paths):
        """约会成功：花 10 币，+8 亲密度"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        result = await intimacy_service.date_wife(gid, "u1", "Alice", today)
        assert result.ok
        assert result.intimacy == 8  # date_intimacy_gain
        assert result.coin_balance == 90  # 100 - 10

    @pytest.mark.asyncio
    async def test_date_not_enough_coins(self, intimacy_service, tmp_paths):
        """余额不足约会失败"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        ps = ProfileStore(tmp_paths, gid)
        profiles = ps.load_all()
        profiles["u1"].coins = 5
        ps.save_all(profiles)

        result = await intimacy_service.date_wife(gid, "u1", "Alice", today)
        assert result.ok is False
        assert result.reason == "not_enough_coins"

    @pytest.mark.asyncio
    async def test_date_no_wife_fails(self, intimacy_service):
        """无老婆约会失败"""
        result = await intimacy_service.date_wife("g1", "u1", "Alice", "2026-07-04")
        assert result.ok is False
        assert result.reason == "no_wife"

    @pytest.mark.asyncio
    async def test_date_writes_activity_log(self, intimacy_service, tmp_paths):
        """约会写 Action.DATE 和 Action.INTIMACY 日志"""
        gid, today = "g1", "2026-07-04"
        await intimacy_service.draw_or_get_primary(gid, "u1", "Alice", today)

        await intimacy_service.date_wife(gid, "u1", "Alice", today)

        store = ActivityStore(tmp_paths, gid)
        logs = store.load_all()
        assert logs["u1"].days.get(today, {}).get(Action.DATE, 0) == 1
        assert logs["u1"].days.get(today, {}).get(Action.INTIMACY, 0) == 1
