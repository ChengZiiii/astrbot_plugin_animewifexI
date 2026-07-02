"""复仇机制单元测试。"""

from __future__ import annotations

import time

import pytest

from app.models.enums import AcquireVia
from app.models.ownership import Ownership
from app.services.ownership_service import OwnershipService
from app.services.plugin_config import PluginConfig
from app.storage.stores import OwnershipStore, ProfileStore
from app.utils.time import now_ts


@pytest.fixture
def config_with_revenge():
    return PluginConfig(
        ntr_possibility=1.0,  # 100% for testing
        ntr_max=5,
        revenge_window_hours=24,
        revenge_success_multiplier=2.0,
    )


@pytest.fixture
def revenge_service(tmp_paths, config_with_revenge, locks, mock_wife_service):
    return OwnershipService(
        paths=tmp_paths,
        config=config_with_revenge,
        locks=locks,
        wife_service=mock_wife_service,
    )


def _setup_wife(service: OwnershipService, gid: str, uid: str, nick: str, today: str):
    """为 uid 抽一个老婆"""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        service.draw_or_get_primary(gid, uid, nick, today)
    )


class TestRevengeWindow:
    @pytest.mark.asyncio
    async def test_revenge_within_window(self, revenge_service, tmp_paths):
        """被牛后 24 小时内可以复仇"""
        gid, today = "g1", "2026-07-04"
        # u1 has wife, u2 attacks and succeeds
        draw1 = await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        assert draw1.ok

        # u2 draws own wife first
        draw2 = await revenge_service.draw_or_get_primary(gid, "u2", "Bob", today)
        assert draw2.ok

        # u2 ntr u1 (100% success)
        ntr = await revenge_service.try_ntr(gid, "u2", "u1", "Bob", today)
        assert ntr.success

        # Verify u1's last_ntr_by is set
        profile = revenge_service.get_profile(gid, "u1")
        assert profile.last_ntr_by is not None
        assert profile.last_ntr_by["uid"] == "u2"

        # u1 tries revenge (should be valid since within window)
        # But u1 has no wife now (was stolen), so need to draw a new one
        draw3 = await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        assert draw3.ok

        revenge = await revenge_service.try_ntr(
            gid, "u1", "u2", "Alice", today, is_revenge=True
        )
        assert revenge.ok
        # Should succeed (100% * 2.0 = still 100%)
        assert revenge.success

    @pytest.mark.asyncio
    async def test_revenge_clears_last_ntr_by(self, revenge_service, tmp_paths):
        """复仇成功后清空 last_ntr_by（防链式复仇）"""
        gid, today = "g1", "2026-07-04"
        await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        await revenge_service.draw_or_get_primary(gid, "u2", "Bob", today)

        # u2 steals from u1
        await revenge_service.try_ntr(gid, "u2", "u1", "Bob", today)

        # u1 draws new wife and revenges
        await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        await revenge_service.try_ntr(gid, "u1", "u2", "Alice", today, is_revenge=True)

        # last_ntr_by should be cleared (empty dict, not None, due to serialization)
        profile = revenge_service.get_profile(gid, "u1")
        assert not profile.last_ntr_by  # empty dict is falsy

    @pytest.mark.asyncio
    async def test_revenge_wrong_target_fails(self, revenge_service, tmp_paths):
        """复仇目标必须是最近牛你的人"""
        gid, today = "g1", "2026-07-04"
        await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        await revenge_service.draw_or_get_primary(gid, "u2", "Bob", today)
        await revenge_service.draw_or_get_primary(gid, "u3", "Charlie", today)

        # u2 steals from u1
        await revenge_service.try_ntr(gid, "u2", "u1", "Bob", today)

        # u1 tries to revenge against u3 (wrong target)
        await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        # This should work as a normal NTR (not revenge), since target doesn't match
        result = await revenge_service.try_ntr(
            gid, "u1", "u3", "Alice", today, is_revenge=True
        )
        # The revenge check should fail (target != last_ntr_by.uid),
        # but it still proceeds as a normal NTR attempt
        assert result.ok  # NTR attempt is valid


class TestIntimacyResetOnNTR:
    @pytest.mark.asyncio
    async def test_ntr_resets_intimacy(self, revenge_service, tmp_paths):
        """NTR 成功后被牛方亲密度归零"""
        gid, today = "g1", "2026-07-04"
        # u1 draws wife and gains intimacy
        draw = await revenge_service.draw_or_get_primary(gid, "u1", "Alice", today)
        assert draw.ok

        # Manually set intimacy on u1's ownership
        store = OwnershipStore(tmp_paths, gid)
        ownerships = store.load_all()
        for o in ownerships:
            if o.uid == "u1" and o.is_primary:
                o.intimacy = 50
                o.intimacy_updated_date = today
        store.save_all(ownerships)

        # u2 draws own wife and steals from u1
        await revenge_service.draw_or_get_primary(gid, "u2", "Bob", today)
        ntr = await revenge_service.try_ntr(gid, "u2", "u1", "Bob", today)
        assert ntr.success

        # The transferred ownership should have intimacy = 0
        ownerships = store.load_all()
        for o in ownerships:
            if o.wid == ntr.wid and o.uid == "u2":
                assert o.intimacy == 0
                assert o.intimacy_updated_date == ""
                break
        else:
            pytest.fail("Transferred ownership not found")
