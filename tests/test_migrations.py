"""旧数据归档测试（Q6 = 清空重来）。"""

from __future__ import annotations

import json
import os

import pytest

from app.storage.migrations import (
    archive_legacy_data,
    has_legacy_data,
    list_legacy_files,
)
from app.storage.paths import Paths


class TestHasLegacyData:
    def test_no_config_dir_returns_false(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        assert has_legacy_data(paths) is False

    def test_empty_config_dir_returns_false(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        # 创建一个非业务文件（如 wife_list_cache.txt）
        with open(paths.legacy_wife_list_cache_file, "w", encoding="utf-8") as f:
            f.write("a.jpg\nb.jpg")
        assert has_legacy_data(paths) is False

    def test_records_json_triggers_true(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        with open(paths.legacy_records_file, "w", encoding="utf-8") as f:
            json.dump({}, f)
        assert has_legacy_data(paths) is True

    def test_group_config_triggers_true(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        # 模拟旧版群配置文件
        with open(paths.legacy_group_config_file("g123"), "w", encoding="utf-8") as f:
            json.dump({"u1": ["img.jpg", "2026-07-01", "张三"]}, f)
        assert has_legacy_data(paths) is True


class TestListLegacyFiles:
    def test_lists_json_files_only(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        for name in ("records.json", "swap_requests.json", "g1.json"):
            with open(os.path.join(paths.legacy_config_dir, name), "w") as f:
                f.write("{}")
        # 非业务文件不归档（如随便放的 txt）
        with open(os.path.join(paths.legacy_config_dir, "random.txt"), "w") as f:
            f.write("noise")

        files = list_legacy_files(paths)
        names = [os.path.basename(f) for f in files]
        assert "records.json" in names
        assert "swap_requests.json" in names
        assert "g1.json" in names
        assert "random.txt" not in names

    def test_includes_wife_list_cache(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        with open(paths.legacy_wife_list_cache_file, "w", encoding="utf-8") as f:
            f.write("a.jpg")
        files = list_legacy_files(paths)
        names = [os.path.basename(f) for f in files]
        assert "wife_list_cache.txt" in names

    def test_no_config_dir_returns_empty(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        assert list_legacy_files(paths) == []


class TestArchiveLegacyData:
    def test_no_legacy_returns_none(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        assert archive_legacy_data(paths) is None

    def test_archives_to_timestamped_subdir(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        with open(paths.legacy_records_file, "w", encoding="utf-8") as f:
            json.dump({"ntr": {}, "change": {}}, f)
        with open(paths.legacy_group_config_file("g1"), "w", encoding="utf-8") as f:
            json.dump({"u1": ["a.jpg", "2026-07-01", "x"]}, f)

        archive_path = archive_legacy_data(paths)
        assert archive_path is not None
        assert os.path.isdir(archive_path)
        # 归档目录位于 archive_v1 下
        assert archive_path.startswith(paths.archive_dir)
        # 原文件已移走
        assert not os.path.exists(paths.legacy_records_file)
        assert not os.path.exists(paths.legacy_group_config_file("g1"))
        # 归档目录中存在移过来的文件
        archived_names = os.listdir(archive_path)
        assert "records.json" in archived_names
        assert "g1.json" in archived_names
        assert "MIGRATED.md" in archived_names

    def test_migrated_md_records_files(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        with open(paths.legacy_records_file, "w", encoding="utf-8") as f:
            json.dump({}, f)

        archive_path = archive_legacy_data(paths)
        md_path = os.path.join(archive_path, "MIGRATED.md")
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "records.json" in content
        assert "v2.x" in content

    def test_idempotent_second_call_returns_none(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        with open(paths.legacy_records_file, "w", encoding="utf-8") as f:
            json.dump({}, f)

        first = archive_legacy_data(paths)
        second = archive_legacy_data(paths)
        assert first is not None
        assert second is None  # 已无遗留数据

    def test_empty_config_dir_removed_after_archive(self, tmp_path):
        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        os.makedirs(paths.legacy_config_dir, exist_ok=True)
        with open(paths.legacy_records_file, "w", encoding="utf-8") as f:
            json.dump({}, f)

        archive_legacy_data(paths)
        # 归档完后 config/ 已空，被自动清理
        assert not os.path.exists(paths.legacy_config_dir)
