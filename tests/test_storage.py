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
