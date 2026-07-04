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
    async def test_start_work_already_working(self, work_service, tmp_paths):
        """已在打工失败"""
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

        result = await work_service.start_work(gid, uid, nick, "normal", "2026-07-04")
        assert result.ok is False
        assert result.reason == "already_working"

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

        result = await work_service.resolve_stolen_work(gid, uid, today)
        assert result is not None
        assert result.ok
        assert result.reward >= 0
        assert result.reason == "stolen"

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
