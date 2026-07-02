"""dataclass 模型层单元测试。"""

from __future__ import annotations

import pytest

from app.models import ActivityLog, Ownership, UserProfile, WifeMeta
from app.models.enums import AcquireVia, Action, Rarity
from app.models.wife import BaseStats
from app.services.ownership_service import wid_for_img


class TestEnums:
    def test_acquire_via_values(self):
        assert AcquireVia.DRAW == "draw"
        assert AcquireVia.NTR == "ntr"
        assert AcquireVia.SWAP == "swap"
        assert set(AcquireVia.ALL) == {"draw", "ntr", "swap", "gift", "summon"}

    def test_rarity_values(self):
        assert Rarity.SSR == "SSR"
        assert set(Rarity.ALL) == {"N", "R", "SR", "SSR"}

    def test_action_values(self):
        assert Action.NTR_SUCCESS == "ntr_success"
        assert Action.DRAW == "draw"
        assert Action.COINS_EARNED == "coins_earned"


class TestWifeMeta:
    def test_roundtrip(self):
        meta = WifeMeta(
            wid="w_abc12345",
            img="进击的巨人!三笠.jpg",
            source="进击的巨人",
            chara="三笠",
            rarity=Rarity.SSR,
            base_stats=BaseStats(atk=80, defense=60, hp=100),
            birthday="12-25",
            first_seen=1720000000,
        )
        d = meta.to_dict()
        assert d["wid"] == "w_abc12345"
        assert d["base_stats"] == {"atk": 80, "def": 60, "hp": 100}
        loaded = WifeMeta.from_dict(d)
        assert loaded.wid == meta.wid
        assert loaded.source == meta.source
        assert loaded.base_stats.power() == 240

    def test_from_dict_with_missing_fields(self):
        loaded = WifeMeta.from_dict({"wid": "w_x", "img": "a.jpg"})
        assert loaded.rarity == Rarity.N
        assert loaded.base_stats.atk == 0
        assert loaded.first_seen == 0

    def test_from_dict_sanitize_bad_stats(self):
        loaded = WifeMeta.from_dict({
            "wid": "w_x",
            "img": "a.jpg",
            "base_stats": "not a dict",
        })
        assert loaded.base_stats.atk == 0

    def test_wid_for_img_stable(self):
        img = "进击的巨人!三笠.jpg"
        assert wid_for_img(img) == wid_for_img(img)
        assert wid_for_img(img).startswith("w_")
        assert len(wid_for_img(img)) == len("w_") + 8

    def test_wid_for_img_distinct(self):
        assert wid_for_img("a.jpg") != wid_for_img("b.jpg")


class TestOwnership:
    def test_roundtrip(self):
        o = Ownership(
            wid="w_abc",
            uid="u123",
            acquired_at=1720000000,
            acquired_via=AcquireVia.NTR,
            intimacy=42,
            intimacy_updated_date="2026-07-03",
            is_locked=True,
            lock_expires_at=None,
            is_primary=True,
        )
        d = o.to_dict()
        loaded = Ownership.from_dict(d)
        assert loaded.wid == o.wid
        assert loaded.intimacy == 42
        assert loaded.is_locked is True
        assert loaded.lock_expires_at is None
        assert loaded.is_primary is True

    def test_lock_expires_at_with_value(self):
        o = Ownership.from_dict({
            "wid": "w_x", "uid": "u", "lock_expires_at": 1720000000,
        })
        assert o.lock_expires_at == 1720000000

    def test_defaults(self):
        o = Ownership.from_dict({"wid": "w_x", "uid": "u"})
        assert o.acquired_via == AcquireVia.DRAW
        assert o.is_locked is False
        assert o.is_primary is False


class TestUserProfile:
    def test_roundtrip_preserves_all_fields(self):
        p = UserProfile(
            uid="u1",
            nick="张三",
            coins=100,
            capacity=5,
            streak_days=7,
            total_draws=30,
            collection=["w_a", "w_b"],
            inventory={"reroll_ticket": 2, "lock_item": 1},
            last_ntr_by={"uid": "u2", "ts": 1719900000},
            pity_counter=3,
        )
        d = p.to_dict()
        loaded = UserProfile.from_dict(d)
        assert loaded.uid == "u1"
        assert loaded.coins == 100
        assert loaded.collection == ["w_a", "w_b"]
        assert loaded.inventory["reroll_ticket"] == 2
        assert loaded.last_ntr_by == {"uid": "u2", "ts": 1719900000}
        assert loaded.pity_counter == 3

    def test_inventory_defaults_merged(self):
        """从旧档案加载时，新增的道具 key 自动补默认值 0"""
        p = UserProfile.from_dict({
            "uid": "u1",
            "inventory": {"reroll_ticket": 2},  # 仅有部分 key
        })
        assert p.inventory["reroll_ticket"] == 2
        assert p.inventory["lock_item"] == 0

    def test_new_with_defaults(self):
        p = UserProfile.new_with_defaults("u1", nick="x", coins=100)
        assert p.coins == 100
        assert p.inventory["revive_potion"] == 0

    def test_last_ntr_by_empty_when_missing(self):
        p = UserProfile.from_dict({"uid": "u1"})
        assert p.last_ntr_by == {}

    def test_collection_non_list_falls_back_to_empty(self):
        p = UserProfile.from_dict({"uid": "u1", "collection": "not a list"})
        assert p.collection == []


class TestActivityLog:
    def test_increment_creates_day(self):
        log = ActivityLog()
        log.increment("2026-07-03", Action.DRAW, 1)
        day = log.get_day("2026-07-03")
        assert day[Action.DRAW] == 1

    def test_increment_accumulates(self):
        log = ActivityLog()
        log.increment("2026-07-03", Action.DRAW, 1)
        log.increment("2026-07-03", Action.DRAW, 1)
        log.increment("2026-07-03", Action.DRAW, 1)
        assert log.get_day("2026-07-03")[Action.DRAW] == 3

    def test_increment_unknown_action_ignored(self):
        log = ActivityLog()
        log.increment("2026-07-03", "not_an_action", 1)
        assert "not_an_action" not in (log.get_day("2026-07-03"))

    def test_increment_negative_delta_ignored(self):
        log = ActivityLog()
        log.increment("2026-07-03", Action.DRAW, -1)
        assert log.get_day("2026-07-03")[Action.DRAW] == 0

    def test_get_day_missing_returns_empty_template(self):
        log = ActivityLog()
        day = log.get_day("2025-01-01")
        assert day[Action.NTR_SUCCESS] == 0
        assert day[Action.DRAW] == 0

    def test_from_dict_drops_invalid_actions(self):
        log = ActivityLog.from_dict({
            "2026-07-03": {"draw": 5, "bogus": 1, "ntr_success": 2},
        })
        day = log.get_day("2026-07-03")
        assert day[Action.DRAW] == 5
        assert day[Action.NTR_SUCCESS] == 2
        assert "bogus" not in day

    def test_from_dict_drops_non_int_values(self):
        log = ActivityLog.from_dict({
            "2026-07-03": {"draw": "not_number"},
        })
        # 非数字值被忽略，保留默认 0
        assert log.get_day("2026-07-03")[Action.DRAW] == 0

    def test_prune_before_keeps_recent_n_days(self):
        log = ActivityLog()
        for d in ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]:
            log.increment(d, Action.DRAW, 1)
        # 保留最近 2 天（从最新算起）
        removed = log.prune_before(keep_dates=set(), days=2)
        assert removed == 2
        assert "2026-07-04" in log.days
        assert "2026-07-03" in log.days
        assert "2026-07-02" not in log.days
        assert "2026-07-01" not in log.days

    def test_prune_before_keep_dates_priority(self):
        log = ActivityLog()
        for d in ["2026-07-01", "2026-07-02", "2026-07-03"]:
            log.increment(d, Action.DRAW, 1)
        # 即使超出 days 窗口，keep_dates 也保留
        log.prune_before(keep_dates={"2026-07-01"}, days=1)
        assert "2026-07-01" in log.days
        assert "2026-07-03" in log.days
        assert "2026-07-02" not in log.days
