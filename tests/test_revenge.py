"""复仇机制单元测试。"""

from __future__ import annotations

import time

import pytest

from app.models.enums import AcquireVia
from app.models.ownership import Ownership
from app.models.profile import UserProfile
from app.models.wife import WifeMeta
from app.services.ownership_service import OwnershipService
from app.services.plugin_config import PluginConfig
from app.storage.stores import OwnershipStore, ProfileStore, WivesMasterStore
from app.utils.time import now_ts


@pytest.fixture
def config_with_revenge():
    return PluginConfig(
        ntr_possibility=1.0,  # 100% for testing
        ntr_max=5,
        revenge_window_hours=24,
        revenge_success_multiplier=2.0,
        daily_free_draws=0,  # unlimited for testing
        newbie_ntr_protection_days=0,  # T20: disable newbie protection for testing
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


    @pytest.mark.asyncio
    async def test_revenge_targets_recorded_stolen_wife_not_random_one(self, revenge_service, tmp_paths, monkeypatch):
        """复仇必须牛回 last_ntr_by.wid 记录的原老婆，而不是随机牛攻击者其他老婆。"""
        gid, today = "g1", "2026-07-04"
        ts = int(now_ts())
        stolen_wid = "w_stolen"
        other_wid_1 = "w_other_1"
        other_wid_2 = "w_other_2"

        WivesMasterStore(tmp_paths).save_all({
            stolen_wid: WifeMeta(wid=stolen_wid, img="B被牛走.jpg", chara="B被牛走"),
            other_wid_1: WifeMeta(wid=other_wid_1, img="A其他1.jpg", chara="A其他1"),
            other_wid_2: WifeMeta(wid=other_wid_2, img="A其他2.jpg", chara="A其他2"),
        })
        OwnershipStore(tmp_paths, gid).save_all([
            Ownership(wid=stolen_wid, uid="u2", acquired_at=ts, acquired_via=AcquireVia.NTR, is_primary=True),
            Ownership(wid=other_wid_1, uid="u2", acquired_at=ts, acquired_via=AcquireVia.DRAW, is_primary=False),
            Ownership(wid=other_wid_2, uid="u2", acquired_at=ts, acquired_via=AcquireVia.DRAW, is_primary=False),
        ])
        ProfileStore(tmp_paths, gid).save_all({
            "u1": UserProfile(
                uid="u1",
                nick="Alice",
                coins=1000,
                last_ntr_by={"uid": "u2", "ts": now_ts(), "wid": stolen_wid, "lost_intimacy": 0},
            ),
            "u2": UserProfile(uid="u2", nick="Bob", coins=1000),
        })

        # 如果复仇仍走随机目标，random.choice 会选中 A 的其他老婆；正确实现应完全绕过随机选择。
        monkeypatch.setattr("app.services.ownership_service._random.choice", lambda seq: seq[1])
        monkeypatch.setattr("app.services.ownership_service._random.random", lambda: 0.0)

        revenge = await revenge_service.try_ntr(gid, "u1", "u2", "Alice", today, is_revenge=True)

        assert revenge.success
        assert revenge.wid == stolen_wid
        ownerships = OwnershipStore(tmp_paths, gid).load_all()
        assert any(o.uid == "u1" and o.wid == stolen_wid for o in ownerships)
        assert any(o.uid == "u2" and o.wid == other_wid_1 for o in ownerships)
        assert any(o.uid == "u2" and o.wid == other_wid_2 for o in ownerships)


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
