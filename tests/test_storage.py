"""json_store / paths / locks 基础持久化层单元测试。"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from app.storage import json_store
from app.storage.locks import GroupLocks
from app.storage.paths import Paths


# ==================== json_store ====================


class TestJsonStore:
    def test_load_missing_file_returns_default(self, tmp_path):
        path = str(tmp_path / "missing.json")
        assert json_store.load_json(path) == {}
        assert json_store.load_json(path, default=[]) == []

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "data.json")
        data = {"a": 1, "b": [1, 2, 3], "c": "中文"}
        json_store.save_json(path, data)
        assert json_store.load_json(path) == data

    def test_save_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "deep" / "nested" / "data.json")
        json_store.save_json(path, {"x": 1})
        assert os.path.exists(path)
        assert json_store.load_json(path) == {"x": 1}

    def test_load_corrupted_file_returns_empty(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        assert json_store.load_json(path) == {}

    def test_load_non_dict_top_level(self, tmp_path):
        path = str(tmp_path / "list.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        # load_json 返回原值（不做顶层类型校验）
        assert json_store.load_json(path) == [1, 2, 3]

    def test_load_list_json_filters_non_dict(self, tmp_path):
        path = str(tmp_path / "list.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"a": 1}, "not_dict", {"b": 2}, 42], f)
        result = json_store.load_list_json(path)
        assert result == [{"a": 1}, {"b": 2}]

    def test_atomic_save_no_tmp_leftover(self, tmp_path):
        path = str(tmp_path / "data.json")
        json_store.save_json(path, {"x": 1})
        assert not os.path.exists(f"{path}.tmp")

    def test_save_utf8_preserved(self, tmp_path):
        path = str(tmp_path / "cn.json")
        data = {"name": "三笠", "source": "进击的巨人"}
        json_store.save_json(path, data)
        # 直接以 utf-8 读回，确认未转义为 \uXXXX
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        assert "三笠" in raw
        assert json_store.load_json(path) == data


class TestSanitizeGroupRecords:
    def test_none_returns_empty(self):
        assert json_store.sanitize_group_records(None, "test") == {}

    def test_non_dict_returns_empty(self):
        assert json_store.sanitize_group_records([1, 2, 3], "test") == {}

    def test_drops_non_dict_inner_records(self):
        data = {
            "g1": {"u1": {"date": "2026-01-01"}, "u2": "broken"},
            "g2": "not_dict",
        }
        cleaned = json_store.sanitize_group_records(data, "test")
        assert "u1" in cleaned["g1"]
        assert "u2" not in cleaned["g1"]
        assert "g2" not in cleaned

    def test_item_validator(self):
        data = {"g1": {"u1": {"date": "x"}, "u2": {"date": "y"}}}

        def has_x(rec):
            return rec.get("date") == "x"

        cleaned = json_store.sanitize_group_records(data, "test", item_validator=has_x)
        assert "u1" in cleaned["g1"]
        assert "u2" not in cleaned["g1"]


# ==================== Paths ====================


class TestPaths:
    def test_ensure_dirs_creates_all(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        assert os.path.isdir(paths.img_dir)
        assert os.path.isdir(paths.data_dir)
        assert os.path.isdir(paths.archive_dir)
        assert os.path.isdir(paths.groups_dir)

    def test_group_dir_auto_created(self, tmp_path):
        paths = Paths(str(tmp_path))
        gdir = paths.group_dir("g123")
        assert os.path.isdir(gdir)

    def test_group_files_under_group_dir(self, tmp_path):
        paths = Paths(str(tmp_path))
        ownership = paths.group_ownership_file("g1")
        profiles = paths.group_profiles_file("g1")
        assert os.path.dirname(ownership) == paths.group_dir("g1")
        assert os.path.dirname(profiles) == paths.group_dir("g1")

    def test_legacy_paths(self, tmp_path):
        paths = Paths(str(tmp_path))
        assert paths.legacy_config_dir.endswith("config")
        assert paths.legacy_records_file.endswith("records.json")


# ==================== GroupLocks ====================


class TestGroupLocks:
    def test_acquire_returns_same_lock_for_same_gid(self):
        locks = GroupLocks()
        l1 = locks.acquire("g1")
        l2 = locks.acquire("g1")
        assert l1 is l2

    def test_acquire_returns_different_locks_for_different_gid(self):
        locks = GroupLocks()
        l1 = locks.acquire("g1")
        l2 = locks.acquire("g2")
        assert l1 is not l2

    def test_known_groups(self):
        locks = GroupLocks()
        locks.acquire("g1")
        locks.acquire("g2")
        assert set(locks.known_groups()) == {"g1", "g2"}

    @pytest.mark.asyncio
    async def test_lock_serializes_concurrent_access(self):
        """并发协程在锁内串行执行（顺序可由全局变量验证）"""
        locks = GroupLocks()
        log = []

        async def worker(name: str, delay: float):
            async with locks.acquire("g1"):
                log.append(f"{name}-enter")
                await asyncio.sleep(delay)
                log.append(f"{name}-exit")

        await asyncio.gather(worker("a", 0.01), worker("b", 0.01))
        # 两次 enter-exit 不交错
        assert log in (
            ["a-enter", "a-exit", "b-enter", "b-exit"],
            ["b-enter", "b-exit", "a-enter", "a-exit"],
        )


# ==================== PkBattleStore（v3 接力战持久化） ====================


class TestPkBattlePaths:
    def test_pk_battles_dir_under_group_dir(self, tmp_paths):
        from app.storage.paths import Paths

        d = tmp_paths.pk_battles_dir_for("g1")
        assert os.path.isdir(d)
        assert os.path.dirname(d) == tmp_paths.group_dir("g1")


class TestPkBattleStore:
    def _make_member(self, wid="w_1", pos=1, **overrides):
        from app.models.pk_battle import FormationMember

        defaults = dict(
            wid=wid, pos=pos, nickname="三笠", rarity="SSR",
            element="力量", base_atk=80, base_def=60, base_hp=500,
            intimacy=90, is_locked=False,
            current_hp=500, is_alive=True, is_active=True,
        )
        defaults.update(overrides)
        return FormationMember(**defaults)

    def _make_battle(self, gid="g1", battle_id="b1", **overrides):
        from app.models.pk_battle import PkBattle

        defaults = dict(
            gid=gid, battle_id=battle_id,
            atk_uid="u1", atk_nick="alice",
            def_uid="u2", def_nick="bob",
        )
        defaults.update(overrides)
        return PkBattle(**defaults)

    def test_save_and_load_round_trip(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        m = self._make_member(wid="w_1", pos=1)
        battle = self._make_battle(
            gid="g1", battle_id="b1",
            atk_formation=[m], def_formation=[m],
        )

        store.save("g1", "b1", battle)
        loaded = store.load("g1", "b1")
        assert loaded is not None
        assert loaded.battle_id == "b1"
        assert loaded.atk_uid == "u1"
        assert loaded.def_uid == "u2"
        assert len(loaded.atk_formation) == 1
        assert loaded.atk_formation[0].wid == "w_1"
        assert loaded.atk_formation[0].rarity == "SSR"

    def test_load_missing_returns_none(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        assert store.load("g1", "no_such_battle") is None

    def test_save_persists_under_pk_battles_subdir(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        battle = self._make_battle(gid="g1", battle_id="b_xyz")
        store.save("g1", "b_xyz", battle)

        expected = os.path.join(tmp_paths.pk_battles_dir_for("g1"), "b_xyz.json")
        assert os.path.exists(expected)

    def test_list_active_returns_all_saved_battles(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        store.save("g1", "b1", self._make_battle(battle_id="b1"))
        store.save("g1", "b2", self._make_battle(battle_id="b2"))
        store.save("g1", "b3", self._make_battle(battle_id="b3"))

        all_battles = store.list_active("g1")
        ids = sorted(b.battle_id for b in all_battles)
        assert ids == ["b1", "b2", "b3"]

    def test_list_active_empty_when_dir_missing(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g_no_battles")
        assert store.list_active("g_no_battles") == []

    def test_delete_removes_battle_file(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        store.save("g1", "b1", self._make_battle(battle_id="b1"))
        assert store.load("g1", "b1") is not None

        store.delete("g1", "b1")
        assert store.load("g1", "b1") is None

    def test_delete_nonexistent_battle_is_noop(self, tmp_paths):
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        # 不应抛异常
        store.delete("g1", "never_existed")

    def test_list_active_skips_corrupt_files(self, tmp_paths):
        """JSON 损坏的文件被静默跳过，不影响其他战斗加载"""
        from app.storage.stores import PkBattleStore

        store = PkBattleStore(tmp_paths, "g1")
        store.save("g1", "b1", self._make_battle(battle_id="b1"))

        # 写入一个损坏的 JSON 到 pk_battles 目录
        bad_path = os.path.join(tmp_paths.pk_battles_dir_for("g1"), "bad.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")

        battles = store.list_active("g1")
        ids = [b.battle_id for b in battles]
        assert "b1" in ids
