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
            inventory={"lock_item": 2, "protection_charm": 1},
            last_ntr_by={"uid": "u2", "ts": 1719900000},
            pity_counter=3,
        )
        d = p.to_dict()
        loaded = UserProfile.from_dict(d)
        assert loaded.uid == "u1"
        assert loaded.coins == 100
        assert loaded.collection == ["w_a", "w_b"]
        assert loaded.inventory["lock_item"] == 2
        assert loaded.last_ntr_by == {"uid": "u2", "ts": 1719900000}
        assert loaded.pity_counter == 3

    def test_inventory_defaults_merged(self):
        """从旧档案加载时，新增的道具 key 自动补默认值 0"""
        p = UserProfile.from_dict({
            "uid": "u1",
            "inventory": {"lock_item": 2},  # 仅有部分 key
        })
        assert p.inventory["lock_item"] == 2
        assert p.inventory["protection_charm"] == 0

    def test_new_with_defaults(self):
        p = UserProfile.new_with_defaults("u1", nick="x", coins=100)
        assert p.coins == 100
        assert p.inventory["protection_charm"] == 0

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


class TestOwnershipContract:
    def test_contract_fields_defaults(self):
        o = Ownership(wid="w_test", uid="u1")
        assert o.work_contract_amount == 0
        assert o.work_contract_uid == ""
        assert o.work_contract_mode == ""

    def test_contract_fields_roundtrip(self):
        o = Ownership(
            wid="w_test", uid="u1",
            work_contract_amount=200, work_contract_uid="u1", work_contract_mode="overtime",
        )
        d = o.to_dict()
        o2 = Ownership.from_dict(d)
        assert o2.work_contract_amount == 200
        assert o2.work_contract_uid == "u1"
        assert o2.work_contract_mode == "overtime"

    def test_contract_fields_old_data_ignored(self):
        """旧数据没有 contract 字段时，默认值为 0"""
        d = {"wid": "w_test", "uid": "u1", "is_working": True}
        o = Ownership.from_dict(d)
        assert o.work_contract_amount == 0


class TestProfileNoContract:
    def test_no_contract_field_in_dict(self):
        p = UserProfile(uid="u1", nick="test")
        d = p.to_dict()
        assert "work_contract_reserved" not in d

    def test_from_dict_ignores_old_contract(self):
        d = {"uid": "u1", "work_contract_reserved": "overtime"}
        p = UserProfile.from_dict(d)
        assert p.uid == "u1"


class TestProfileFormation:
    """v3 接力战：UserProfile.formation 字段（编队持久化）"""

    def test_defaults_to_empty_list(self):
        p = UserProfile(uid="u1", nick="test")
        assert p.formation == []

    def test_round_trip(self):
        p = UserProfile(uid="u1", nick="test", formation=["w_a", "w_b", "w_c", "w_d"])
        data = p.to_dict()
        assert data["formation"] == ["w_a", "w_b", "w_c", "w_d"]
        p2 = UserProfile.from_dict(data)
        assert p2.formation == ["w_a", "w_b", "w_c", "w_d"]

    def test_round_trip_partial_formation(self):
        p = UserProfile(uid="u1", nick="test", formation=["w_a"])
        data = p.to_dict()
        p2 = UserProfile.from_dict(data)
        assert p2.formation == ["w_a"]

    def test_legacy_profile_missing_formation_field_defaults_to_empty(self):
        """旧档案（Phase 4 时代）没有 formation 字段时，回退为空列表"""
        d = {"uid": "u1", "nick": "old_player", "coins": 100}
        p = UserProfile.from_dict(d)
        assert p.formation == []

    def test_legacy_profile_formation_is_non_list_falls_back(self):
        """老数据格式异常（非 list）时，兜底为空列表"""
        d = {"uid": "u1", "formation": "broken"}
        p = UserProfile.from_dict(d)
        assert p.formation == []


# ==================== v3 接力战 数据模型 ====================


class TestFormationMember:
    def test_round_trip(self):
        from app.models.pk_battle import FormationMember

        m = FormationMember(
            wid="w_a1", pos=1, nickname="三笠", rarity="SSR",
            element="力量", base_atk=80, base_def=60, base_hp=500,
            intimacy=90, is_locked=False,
            current_hp=500, is_alive=True, is_active=True,
            kills=2, damage_dealt=300, damage_taken=120,
            passive_id="crit_plus",
        )
        data = m.to_dict()
        m2 = FormationMember.from_dict(data)
        assert m2.wid == "w_a1"
        assert m2.pos == 1
        assert m2.nickname == "三笠"
        assert m2.rarity == "SSR"
        assert m2.element == "力量"
        assert m2.base_atk == 80
        assert m2.base_def == 60
        assert m2.base_hp == 500
        assert m2.intimacy == 90
        assert m2.is_locked is False
        assert m2.current_hp == 500
        assert m2.is_alive is True
        assert m2.is_active is True
        assert m2.kills == 2
        assert m2.damage_dealt == 300
        assert m2.damage_taken == 120
        assert m2.passive_id == "crit_plus"

    def test_defaults_for_optional_fields(self):
        from app.models.pk_battle import FormationMember

        m = FormationMember(
            wid="w_x", pos=2, nickname="X", rarity="N",
            element="智力", base_atk=10, base_def=10, base_hp=100,
            intimacy=0, is_locked=False,
            current_hp=100, is_alive=True, is_active=True,
        )
        assert m.kills == 0
        assert m.damage_dealt == 0
        assert m.damage_taken == 0
        assert m.passive_id == ""


class TestBattleStatusLayer:
    def test_round_trip(self):
        from app.models.pk_battle import BattleStatusLayer

        s = BattleStatusLayer()
        s.qi_po = 3
        s.weak_point = 2
        s.bloodlust = 1
        s.frenzy = False
        data = s.to_dict()
        s2 = BattleStatusLayer.from_dict(data)
        assert s2.qi_po == 3
        assert s2.weak_point == 2
        assert s2.bloodlust == 1
        assert s2.frenzy is False

    def test_defaults(self):
        from app.models.pk_battle import BattleStatusLayer

        s = BattleStatusLayer()
        assert s.qi_po == 0
        assert s.weak_point == 0
        assert s.bloodlust == 0
        assert s.frenzy is False

    def test_frenzy_round_trip(self):
        from app.models.pk_battle import BattleStatusLayer

        s = BattleStatusLayer(frenzy=True, qi_po=5)
        data = s.to_dict()
        s2 = BattleStatusLayer.from_dict(data)
        assert s2.frenzy is True
        assert s2.qi_po == 5


class TestPkBattle:
    def test_round_trip_minimal(self):
        from app.models.pk_battle import PkBattle

        battle = PkBattle(
            gid="g1", battle_id="b1",
            atk_uid="u1", atk_nick="alice",
            def_uid="u2", def_nick="bob",
        )
        data = battle.to_dict()
        b2 = PkBattle.from_dict(data)
        assert b2.gid == "g1"
        assert b2.battle_id == "b1"
        assert b2.atk_uid == "u1"
        assert b2.atk_nick == "alice"
        assert b2.def_uid == "u2"
        assert b2.def_nick == "bob"
        assert b2.atk_formation == []
        assert b2.def_formation == []
        assert b2.atk_status_layers == []
        assert b2.def_status_layers == []
        assert b2.turn_idx == 0
        assert b2.active_idx == (1, 1)
        assert b2.rng_seed == 0
        assert b2.rng_state is None
        assert b2.status == "active"
        assert b2.winner_uid == ""
        assert b2.end_reason == ""
        assert b2.log == []
        assert b2.created_at == 0
        assert b2.updated_at == 0
        assert b2.finished_at == 0

    def test_round_trip_with_formations(self):
        from app.models.pk_battle import (
            BattleStatusLayer,
            FormationMember,
            PkBattle,
        )

        members = [
            FormationMember(
                wid="w_1", pos=1, nickname="三笠", rarity="SSR",
                element="力量", base_atk=80, base_def=60, base_hp=500,
                intimacy=90, is_locked=False,
                current_hp=500, is_alive=True, is_active=True,
            ),
            FormationMember(
                wid="w_2", pos=2, nickname="蝴蝶忍", rarity="SR",
                element="敏捷", base_atk=70, base_def=50, base_hp=450,
                intimacy=70, is_locked=False,
                current_hp=450, is_alive=True, is_active=False,
            ),
        ]
        layers = [BattleStatusLayer(), BattleStatusLayer()]
        layers[0].qi_po = 2

        battle = PkBattle(
            gid="g1", battle_id="b_test",
            atk_uid="u1", atk_nick="alice",
            def_uid="u2", def_nick="bob",
            atk_formation=list(members),
            def_formation=list(members),
            atk_status_layers=list(layers),
            def_status_layers=list(layers),
            turn_idx=5, active_idx=(2, 1),
            rng_seed=42,
            status="settling", winner_uid="u1", end_reason="all_dead",
            log=["第1回合...", "第2回合..."],
            created_at=1700000000, updated_at=1700000100, finished_at=1700000200,
        )
        data = battle.to_dict()
        b2 = PkBattle.from_dict(data)

        assert b2.atk_formation[0].wid == "w_1"
        assert b2.atk_formation[1].wid == "w_2"
        assert b2.def_formation[0].rarity == "SSR"
        assert b2.atk_status_layers[0].qi_po == 2
        assert b2.atk_status_layers[1].qi_po == 0
        assert b2.turn_idx == 5
        assert b2.active_idx == (2, 1)
        assert b2.rng_seed == 42
        assert b2.status == "settling"
        assert b2.winner_uid == "u1"
        assert b2.end_reason == "all_dead"
        assert b2.log == ["第1回合...", "第2回合..."]
        assert b2.created_at == 1700000000
        assert b2.updated_at == 1700000100
        assert b2.finished_at == 1700000200
