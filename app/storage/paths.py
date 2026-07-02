"""路径常量：基于插件数据目录统一管理所有持久化文件路径。

新版本（v3.x）数据布局（参考 ``ROADMAP.md`` §2.1）::

    <plugin_data>/                 # StarTools.get_data_dir(...) 返回的根
    ├── img/wife/                  # 本地图库（保留，不动）
    └── data/                      # 新版本数据根
        ├── archive_v1/            # 旧版本（v2.x）归档
        ├── wives_master.json      # 全局老婆元数据
        └── groups/{gid}/
            ├── ownership.json
            ├── profiles.json
            ├── activity.json
            ├── swap_requests.json
            └── ntr_status.json

旧版本（v2.x）数据位于 ``<plugin_data>/config/`` 下，启动时若检测到则整体
归档到 ``archive_v1/<timestamp>/``，不做语义迁移。
"""

from __future__ import annotations

import os

__all__ = ["Paths"]


class Paths:
    """集中管理插件所有文件路径，避免散落在各处的字符串拼接

    所有方法都是纯函数（接收 ``root``），实例化后通过属性访问即可。
    """

    def __init__(self, root: str):
        """``root`` 为插件数据根目录（StarTools.get_data_dir 的返回值）"""
        self.root = root

        # 顶层目录
        self.img_dir = os.path.join(root, "img", "wife")
        self.data_dir = os.path.join(root, "data")
        self.archive_dir = os.path.join(self.data_dir, "archive_v1")
        self.groups_dir = os.path.join(self.data_dir, "groups")

        # 全局文件
        self.wives_master_file = os.path.join(self.data_dir, "wives_master.json")

        # 旧版本目录与文件（用于归档检测）
        self.legacy_config_dir = os.path.join(root, "config")
        self.legacy_records_file = os.path.join(self.legacy_config_dir, "records.json")
        self.legacy_swap_requests_file = os.path.join(
            self.legacy_config_dir, "swap_requests.json"
        )
        self.legacy_ntr_status_file = os.path.join(
            self.legacy_config_dir, "ntr_status.json"
        )
        self.legacy_wife_list_cache_file = os.path.join(
            self.legacy_config_dir, "wife_list_cache.txt"
        )
        self.legacy_group_config_file = lambda gid: os.path.join(
            self.legacy_config_dir, f"{gid}.json"
        )

        # 新版本共享缓存（与图库相关的远程列表缓存）
        self.wife_list_cache_file = os.path.join(self.data_dir, "wife_list_cache.txt")

    # ---------- 新数据：群组级 ----------

    def group_dir(self, gid: str) -> str:
        """获取群组数据目录，自动创建"""
        path = os.path.join(self.groups_dir, gid)
        os.makedirs(path, exist_ok=True)
        return path

    def group_ownership_file(self, gid: str) -> str:
        return os.path.join(self.group_dir(gid), "ownership.json")

    def group_profiles_file(self, gid: str) -> str:
        return os.path.join(self.group_dir(gid), "profiles.json")

    def group_activity_file(self, gid: str) -> str:
        return os.path.join(self.group_dir(gid), "activity.json")

    def group_swap_requests_file(self, gid: str) -> str:
        return os.path.join(self.group_dir(gid), "swap_requests.json")

    def group_ntr_status_file(self, gid: str) -> str:
        return os.path.join(self.group_dir(gid), "ntr_status.json")

    def group_daily_counts_file(self, gid: str) -> str:
        """每日次数计数文件（NTR/换/交换/重置/PK 等动作的当日触发次数）"""
        return os.path.join(self.group_dir(gid), "daily_counts.json")

    # ---------- 初始化 ----------

    def ensure_dirs(self) -> None:
        """创建所有运行时目录（幂等，启动时调用）"""
        for path in (
            self.img_dir,
            self.data_dir,
            self.archive_dir,
            self.groups_dir,
        ):
            os.makedirs(path, exist_ok=True)
