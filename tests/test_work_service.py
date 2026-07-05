"""WorkService 单元测试。"""

from __future__ import annotations

import pytest

from app.models.enums import Action
from app.services.plugin_config import PluginConfig
from app.services.work_service import WorkService
from app.storage.stores import ActivityStore, OwnershipStore, ProfileStore


@pytest.fixture
def work_config():
    return PluginConfig(
        daily_free_draws=0,
        newbie_ntr_protection_days=0,
        work_enabled=True,
    )


@pytest.fixture
def work_service(tmp_paths, work_config, locks):
    return WorkService(
        paths=tmp_paths,
        config=work_config,
        locks=locks,
    )


class TestStartWork:
    @pytest.mark.asyncio
    async def test_start_work_success(self, work_service, tmp_paths):
        """正常启动打工"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        # 先抽老婆
        from app.services.ownership_service import OwnershipService
        from app.services.wife_service import WifeService
        from tests.conftest import mock_wife_service as _mws
        # 直接写 ownership 数据
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
        ))
        ownership_store.save_all(ownerships)

        # 给用户足够币
        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        result = await work_service.start_work(gid, uid, nick, "normal", today)
        assert result.ok
        assert result.mode == "normal"
        assert result.start_cost == 10
        assert result.coin_balance == 90

        # 验证打工状态
        ownerships = ownership_store.load_all()
        for o in ownerships:
            if o.uid == uid and o.is_primary:
                assert o.is_working is True
                assert o.work_mode == "normal"
                assert o.work_ends_at > 0
                break

    @pytest.mark.asyncio
    async def test_start_work_no_wife_fails(self, work_service, tmp_paths):
        """无老婆打工失败"""
        result = await work_service.start_work("g1", "u1", "Alice", "normal", "2026-07-04")
        assert result.ok is False
        assert result.reason == "no_wife"

    @pytest.mark.asyncio
    async def test_start_work_invalid_mode(self, work_service, tmp_paths, locks):
        """无效模式失败"""
        gid, uid, nick = "g1", "u1", "Alice"
        # 写 ownership
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
        ))
        ownership_store.save_all(ownerships)

        result = await work_service.start_work(gid, uid, nick, "invalid", "2026-07-04")
        assert result.ok is False
        assert result.reason == "invalid_mode"

    @pytest.mark.asyncio
    async def test_start_work_not_enough_coins(self, work_service, tmp_paths):
        """余额不足失败"""
        gid, uid, nick = "g1", "u1", "Alice"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=5)
        profile_store.save_all(profiles)

        result = await work_service.start_work(gid, uid, nick, "normal", "2026-07-04")
        assert result.ok is False
        assert result.reason == "not_enough_coins"

    @pytest.mark.asyncio
    async def test_start_work_already_working(self, tmp_paths, locks):
        """达到并发打工上限时失败"""
        from app.services.work_service import WorkService
        config = PluginConfig(work_max_concurrent=1)
        svc = WorkService(tmp_paths, config, locks)

        gid, uid, nick = "g1", "u1", "Alice"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        result = await svc.start_work(gid, uid, nick, "normal", "2026-07-04")
        assert result.ok is False
        assert result.reason == "already_working"

    @pytest.mark.asyncio
    async def test_start_work_concurrent_under_limit(self, tmp_paths, locks):
        """未达并发上限时允许多个老婆同时打工"""
        from app.services.work_service import WorkService
        config = PluginConfig(work_max_concurrent=3)
        svc = WorkService(tmp_paths, config, locks)

        gid, uid, nick = "g1", "u1", "Alice"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        # 第一个老婆已在打工
        ownerships.append(Ownership(
            wid="w1", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
        ))
        # 第二个老婆空闲
        ownerships.append(Ownership(
            wid="w2", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW,
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        # 指定第二个老婆打工，应该成功
        result = await svc.start_work(gid, uid, nick, "normal", "2026-07-04", selected_wid="w2")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_start_work_disabled(self, tmp_paths, locks):
        """功能关闭失败"""
        config = PluginConfig(work_enabled=False)
        service = WorkService(paths=tmp_paths, config=config, locks=locks)
        result = await service.start_work("g1", "u1", "Alice", "normal", "2026-07-04")
        assert result.ok is False
        assert result.reason == "disabled"

    @pytest.mark.asyncio
    async def test_start_work_writes_activity_log(self, work_service, tmp_paths):
        """启动打工写 Action.WORK_START 日志"""
        gid, uid, nick = "g1", "u1", "Alice"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        today = "2026-07-04"
        await work_service.start_work(gid, uid, nick, "normal", today)

        activity_store = ActivityStore(tmp_paths, gid)
        logs = activity_store.load_all()
        assert logs[uid].days.get(today, {}).get(Action.WORK_START, 0) == 1

    @pytest.mark.asyncio
    async def test_reserve_work_contract_success(self, work_service, tmp_paths):
        gid, uid, nick = "g1", "u1", "Alice"
        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile

        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        result = await work_service.reserve_work_contract(gid, uid, nick, "normal")
        assert result.ok is True
        assert result.mode == "normal"

        profiles = profile_store.load_all()
        assert profiles[uid].work_contract_reserved == "normal"
        assert profiles[uid].coins == 50

    @pytest.mark.asyncio
    async def test_set_work_partner_success(self, work_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia

        ownerships.append(Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w2", uid="u2", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)

        result = await work_service.set_work_partner(gid, "u1", "u2", "Alice", "Bob", today)
        assert result.ok is True

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        assert profiles["u1"].work_partner_uid == "u2"
        assert profiles["u2"].work_partner_uid == "u1"
        assert profiles["u1"].work_partner_count == 1

    @pytest.mark.asyncio
    async def test_set_work_partner_daily_limit_default_one(self, work_service, tmp_paths):
        """默认 work_partner_daily_limit=1：当天再次绑定不同搭档会被拒。"""
        gid, today = "g1", "2026-07-04"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia

        ownerships.append(Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w2", uid="u2", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w3", uid="u3", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)

        first = await work_service.set_work_partner(gid, "u1", "u2", "Alice", "Bob", today)
        assert first.ok is True

        second = await work_service.set_work_partner(gid, "u1", "u3", "Alice", "Carol", today)
        assert second.ok is False
        assert second.reason == "daily_limit"

    @pytest.mark.asyncio
    async def test_set_work_partner_daily_limit_allows_multiple(self, tmp_paths, locks):
        """work_partner_daily_limit=2：允许当天绑定 2 次不同搭档。"""
        from app.services.plugin_config import PluginConfig
        config = PluginConfig(
            daily_free_draws=0,
            newbie_ntr_protection_days=0,
            work_enabled=True,
            work_partner_daily_limit=2,
        )
        service = WorkService(paths=tmp_paths, config=config, locks=locks)

        gid, today = "g1", "2026-07-04"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia

        ownerships.append(Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w2", uid="u2", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w3", uid="u3", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)

        first = await service.set_work_partner(gid, "u1", "u2", "Alice", "Bob", today)
        assert first.ok is True

        second = await service.set_work_partner(gid, "u1", "u3", "Alice", "Carol", today)
        assert second.ok is True

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        assert profiles["u1"].work_partner_count == 2
        assert profiles["u1"].work_partner_uid == "u3"
        # u2 的旧链接应被清空
        assert profiles["u2"].work_partner_uid == ""
        assert profiles["u3"].work_partner_uid == "u1"

        # 第 3 次应该被拒
        from app.models.ownership import Ownership as _O
        from app.models.enums import AcquireVia as _A
        ownerships = ownership_store.load_all()
        ownerships.append(_O(wid="w4", uid="u4", acquired_at=0, acquired_via=_A.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)
        third = await service.set_work_partner(gid, "u1", "u4", "Alice", "Dave", today)
        assert third.ok is False
        assert third.reason == "daily_limit"

    @pytest.mark.asyncio
    async def test_set_work_partner_resets_count_on_new_day(self, tmp_paths, locks):
        """跨天后 work_partner_count 自动重置。"""
        from app.services.plugin_config import PluginConfig
        config = PluginConfig(
            daily_free_draws=0,
            newbie_ntr_protection_days=0,
            work_enabled=True,
            work_partner_daily_limit=1,
        )
        service = WorkService(paths=tmp_paths, config=config, locks=locks)

        gid, today, tomorrow = "g1", "2026-07-04", "2026-07-05"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia

        ownerships.append(Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w2", uid="u2", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)

        first = await service.set_work_partner(gid, "u1", "u2", "Alice", "Bob", today)
        assert first.ok is True

        # 同一天再绑别人应失败
        from app.models.ownership import Ownership as _O
        from app.models.enums import AcquireVia as _A
        ownerships = ownership_store.load_all()
        ownerships.append(_O(wid="w3", uid="u3", acquired_at=0, acquired_via=_A.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)
        same_day = await service.set_work_partner(gid, "u1", "u3", "Alice", "Carol", today)
        assert same_day.ok is False
        assert same_day.reason == "daily_limit"

        # 跨天后可重新绑定
        next_day = await service.set_work_partner(gid, "u1", "u3", "Alice", "Carol", tomorrow)
        assert next_day.ok is True

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        assert profiles["u1"].work_partner_count == 1
        assert profiles["u1"].work_partner_count_date == tomorrow

    @pytest.mark.asyncio
    async def test_start_work_can_target_non_primary_wife(self, work_service, tmp_paths):
        """可指定非主老婆去打工"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        ownerships.append(Ownership(wid="w_primary", uid=uid, acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid="w_worker", uid=uid, acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=False))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        result = await work_service.start_work(gid, uid, nick, "normal", today, "w_worker")
        assert result.ok is True
        assert result.wid == "w_worker"

        ownerships = ownership_store.load_all()
        worker = next(o for o in ownerships if o.wid == "w_worker")
        primary = next(o for o in ownerships if o.wid == "w_primary")
        assert worker.is_working is True
        assert primary.is_working is False


class TestClearWorkState:
    def test_clear_work_state(self):
        """清空打工状态"""
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        o = Ownership(
            wid="w_test", uid="u1", acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=1000, work_ends_at=2000,
        )
        service = WorkService.__new__(WorkService)
        service.clear_work_state(o)
        assert o.is_working is False
        assert o.work_mode == ""
        assert o.work_started_at == 0
        assert o.work_ends_at == 0


class TestResolveDueWork:
    @pytest.mark.asyncio
    async def test_resolve_due_work_success(self, work_service, tmp_paths):
        """到期结算成功"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        # 设置打工中的 ownership
        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=ts - 15000, work_ends_at=ts - 1,  # 已到期
        ))
        ownership_store.save_all(ownerships)

        # 设置用户档案
        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=50)
        profile_store.save_all(profiles)

        result = await work_service.resolve_due_work(gid, uid, nick, today)
        assert result is not None
        assert result.ok
        assert result.reward > 0
        assert result.coin_balance > 50  # 奖励加到了余额

        # 验证打工状态已清空
        ownerships = ownership_store.load_all()
        for o in ownerships:
            if o.uid == uid:
                assert o.is_working is False
                assert o.work_mode == ""

    @pytest.mark.asyncio
    async def test_resolve_due_work_not_due(self, work_service, tmp_paths):
        """未到期不结算"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=ts, work_ends_at=ts + 14400,  # 未到期
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=50)
        profile_store.save_all(profiles)

        result = await work_service.resolve_due_work(gid, uid, nick, today)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_due_work_no_wife(self, work_service, tmp_paths):
        """无老婆不结算"""
        result = await work_service.resolve_due_work("g1", "u1", "Alice", "2026-07-04")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_due_work_writes_log(self, work_service, tmp_paths):
        """结算写 Action.WORK_COMPLETE 日志"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=ts - 15000, work_ends_at=ts - 1,
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=50)
        profile_store.save_all(profiles)

        await work_service.resolve_due_work(gid, uid, nick, today)

        activity_store = ActivityStore(tmp_paths, gid)
        logs = activity_store.load_all()
        assert logs[uid].days.get(today, {}).get(Action.WORK_COMPLETE, 0) == 1

    @pytest.mark.asyncio
    async def test_resolve_due_work_applies_contract_and_partner_bonus(self, work_service, tmp_paths):
        gid, today = "g1", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.models.profile import UserProfile
        from app.utils.time import now_ts
        from app.models.activity import ActivityLog

        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(wid="w1", uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True, is_working=True, work_mode="normal", work_started_at=ts - 15000, work_ends_at=ts - 1))
        ownerships.append(Ownership(wid="w2", uid="u2", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles["u1"] = UserProfile(uid="u1", nick="Alice", coins=50, work_contract_reserved="normal", work_partner_uid="u2", work_partner_date=today)
        profiles["u2"] = UserProfile(uid="u2", nick="Bob", coins=50, work_partner_uid="u1", work_partner_date=today)
        profile_store.save_all(profiles)

        activity_store = ActivityStore(tmp_paths, gid)
        logs = activity_store.load_all()
        log1 = logs.get("u1") or ActivityLog()
        log2 = logs.get("u2") or ActivityLog()
        log1.increment(today, Action.WORK_START, 1)
        log2.increment(today, Action.WORK_START, 1)
        logs["u1"] = log1
        logs["u2"] = log2
        activity_store.save_all(logs)

        result = await work_service.resolve_due_work(gid, "u1", "Alice", today)
        assert result is not None
        assert result.ok is True
        assert result.contract_used is True
        assert result.partner_bonus_used is True

        profiles = profile_store.load_all()
        assert profiles["u1"].work_contract_reserved == ""

    @pytest.mark.asyncio
    async def test_resolve_due_work_for_non_primary_worker(self, work_service, tmp_paths):
        """非主老婆打工到期也能结算"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(wid="w_primary", uid=uid, acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(
            wid="w_worker", uid=uid, acquired_at=0, acquired_via=AcquireVia.DRAW,
            is_primary=False, is_working=True, work_mode="normal",
            work_started_at=ts - 15000, work_ends_at=ts - 1,
        ))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=50)
        profile_store.save_all(profiles)

        result = await work_service.resolve_due_work(gid, uid, nick, today)
        assert result is not None
        assert result.ok is True
        assert result.wid == "w_worker"


class TestResolveStolenWork:
    @pytest.mark.asyncio
    async def test_resolve_stolen_work_success(self, work_service, tmp_paths):
        """被截胡结算成功"""
        gid, uid, today = "g1", "u1", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.utils.time import now_ts

        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(
            wid="w_test", uid=uid, acquired_at=0,
            acquired_via=AcquireVia.DRAW, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=ts - 7200, work_ends_at=ts + 7200,  # 半程
        ))
        ownership_store.save_all(ownerships)

        result = await work_service.resolve_stolen_work(gid, uid, today, attacker_uid="u2", attacker_nick="Bob")
        assert result is not None
        assert result.ok
        assert result.reward >= 0
        assert result.reason == "stolen"

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        assert profiles["u2"].coins == result.coin_balance
        assert profiles["u2"].coins == 50 + result.reward

        # 验证打工状态已清空
        ownerships = ownership_store.load_all()
        for o in ownerships:
            if o.uid == uid:
                assert o.is_working is False

    @pytest.mark.asyncio
    async def test_resolve_stolen_work_not_working(self, work_service, tmp_paths):
        """未打工不结算"""
        result = await work_service.resolve_stolen_work("g1", "u1", "2026-07-04")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_stolen_work_voids_contract_and_uses_insurance(self, work_service, tmp_paths):
        gid, uid, today = "g1", "u1", "2026-07-04"
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        ownership_store = OwnershipStore(tmp_paths, gid)
        ownerships = ownership_store.load_all()
        ts = now_ts()
        ownerships.append(Ownership(wid="w_test", uid=uid, acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True, is_working=True, work_mode="normal", work_started_at=ts - 7200, work_ends_at=ts + 7200))
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick="Alice", coins=50, work_contract_reserved="normal", inventory={
            "lock_item": 0,
            "protection_charm": 0,
            "draw_ticket_single": 0,
            "draw_ticket_ten": 0,
            "revenge_token": 0,
            "insurance_card": 1,
        })
        profile_store.save_all(profiles)

        result = await work_service.resolve_stolen_work(gid, uid, today, attacker_uid="u2", attacker_nick="Bob")
        assert result is not None
        assert result.contract_voided is True
        assert result.insurance_used is True

        profiles = profile_store.load_all()
        assert profiles[uid].work_contract_reserved == ""
        assert profiles[uid].inventory["insurance_card"] == 0
        assert profiles[uid].inventory["revenge_token"] == 1


class TestWorkUmo:
    def test_ownership_work_umo_roundtrip(self):
        """work_umo 在序列化/反序列化后保持一致"""
        from app.models.ownership import Ownership

        o = Ownership(
            wid="w1", uid="u1", acquired_via="draw",
            is_working=True, work_mode="normal",
            work_started_at=1000, work_ends_at=5000,
            work_umo="aiocqhttp:group:123456",
        )
        d = o.to_dict()
        assert d["work_umo"] == "aiocqhttp:group:123456"

        o2 = Ownership.from_dict(d)
        assert o2.work_umo == "aiocqhttp:group:123456"

    def test_ownership_work_umo_default_empty(self):
        """旧数据没有 work_umo 字段时默认为空字符串"""
        from app.models.ownership import Ownership

        o = Ownership.from_dict({"wid": "w1", "uid": "u1"})
        assert o.work_umo == ""

    @pytest.mark.asyncio
    async def test_start_work_stores_umo(self, work_service, tmp_paths):
        """start_work 正确存储 work_umo"""
        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        from app.models.ownership import Ownership
        ownerships.append(Ownership(wid="w1", uid=uid, is_primary=True))
        store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        from app.models.profile import UserProfile
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        result = await work_service.start_work(
            gid, uid, nick, "normal", today, umo="aiocqhttp:group:999"
        )
        assert result.ok is True

        ownerships = store.load_all()
        o = next(o for o in ownerships if o.uid == uid)
        assert o.work_umo == "aiocqhttp:group:999"


class TestSettleAllDue:
    @pytest.mark.asyncio
    async def test_settle_all_due_returns_umo(self, tmp_paths, work_config, locks):
        """settle_all_due 应在结果中返回 work_umo（而非被 clear_work_state 清空后返回空字符串）"""
        from app.models.ownership import Ownership
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"
        test_umo = "aiocqhttp:group:12345"

        # 创建打工中的 ownership，work_ends_at 已过
        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        ownerships.append(Ownership(
            wid="w1", uid=uid, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=now_ts() - 10000,
            work_ends_at=now_ts() - 1,  # 已到期
            work_umo=test_umo,
        ))
        store.save_all(ownerships)

        # 创建 profile
        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        svc = WorkService(tmp_paths, work_config, locks)
        results = await svc.settle_all_due()

        assert len(results) == 1
        umo, result = results[0]
        assert umo == test_umo, f"work_umo 应为 {test_umo!r}，实际为 {umo!r}"
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_settle_all_due_clears_work_state_after(self, tmp_paths, work_config, locks):
        """settle_all_due 结算后 ownership 的打工状态应被清空"""
        from app.models.ownership import Ownership
        from app.models.profile import UserProfile
        from app.utils.time import now_ts

        gid, uid, nick, today = "g1", "u1", "Alice", "2026-07-04"

        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        ownerships.append(Ownership(
            wid="w1", uid=uid, is_primary=True,
            is_working=True, work_mode="normal",
            work_started_at=now_ts() - 10000,
            work_ends_at=now_ts() - 1,
            work_umo="aiocqhttp:group:12345",
        ))
        store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, gid)
        profiles = profile_store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick=nick, coins=100)
        profile_store.save_all(profiles)

        svc = WorkService(tmp_paths, work_config, locks)
        await svc.settle_all_due()

        ownerships = store.load_all()
        o = next(o for o in ownerships if o.uid == uid)
        assert o.is_working is False
        assert o.work_umo == ""
