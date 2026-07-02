"""各实体 Store 类：封装 JSON 持久化的读写。

设计原则：

* Store 只负责单文件的加载/落盘与 dict↔dataclass 转换；
* 不持有群锁（锁由 service 层在调用 Store 前获取）；
* 所有写方法立即落盘（保持与 v2.x 一致的"锁内即写"语义）；
* 文件损坏时记录日志并按空数据载入，不抛异常导致插件加载失败。

.. note::

    ``OwnershipStore`` 操作的是 list 型 JSON（每条 ownership 是独立记录，
    允许同一 uid 多条），不同于 v2.x 的 dict 型 ``{uid: wife}``。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

try:
    from astrbot.api import logger as _logger
    _error = _logger.error
except Exception:  # pragma: no cover
    import logging
    _error = logging.getLogger("astrbot_plugin_animewifex").error

from ..models import ActivityLog, Ownership, UserProfile, WifeMeta
from ..models.enums import Action
from . import json_store
from .paths import Paths

__all__ = [
    "WivesMasterStore",
    "OwnershipStore",
    "ProfileStore",
    "ActivityStore",
    "SwapRequestStore",
    "NtrStatusStore",
]


# ==================== 全局老婆元数据 ====================


class WivesMasterStore:
    """全局老婆元数据存储（无群锁，进程级单文件）"""

    def __init__(self, paths: Paths):
        self._path = paths.wives_master_file

    def load_all(self) -> Dict[str, WifeMeta]:
        """加载全部老婆元数据，按 wid 索引"""
        raw = json_store.load_json(self._path, default={})
        if not isinstance(raw, dict):
            _error(f"wives_master.json 顶层不是字典，已丢弃全部数据: {self._path}")
            return {}
        result: Dict[str, WifeMeta] = {}
        for wid, item in raw.items():
            if not isinstance(item, dict):
                continue
            meta = WifeMeta.from_dict(item)
            if meta.wid:
                result[meta.wid] = meta
        return result

    def save_all(self, metas: Dict[str, WifeMeta]) -> None:
        json_store.save_json(
            self._path, {wid: meta.to_dict() for wid, meta in metas.items()}
        )

    def upsert(self, meta: WifeMeta) -> Dict[str, WifeMeta]:
        """读取 → 写入/更新单条 → 落盘 → 返回新的全集

        用于"首次抽到新角色时写入元数据"。
        """
        all_metas = self.load_all()
        all_metas[meta.wid] = meta
        self.save_all(all_metas)
        return all_metas


# ==================== 所有权（list 型） ====================


class OwnershipStore:
    """群内所有权记录存储：list[Ownership]

    同一 wid 在同一群内全局唯一（Q2），但同一 uid 可持有多条。
    """

    def __init__(self, paths: Paths, gid: str):
        self._path = paths.group_ownership_file(gid)
        self._gid = gid

    def load_all(self) -> List[Ownership]:
        raw = json_store.load_list_json(self._path)
        return [Ownership.from_dict(item) for item in raw]

    def save_all(self, ownerships: Iterable[Ownership]) -> None:
        json_store.save_json(self._path, [o.to_dict() for o in ownerships])

    # ---------- 查询 ----------

    def find_by_wid(self, wid: str, ownerships: List[Ownership]) -> Optional[Ownership]:
        """根据 wid 查找（群内全局唯一）"""
        for o in ownerships:
            if o.wid == wid:
                return o
        return None

    def list_by_user(
        self, uid: str, ownerships: List[Ownership]
    ) -> List[Ownership]:
        """列出某用户持有的全部老婆"""
        return [o for o in ownerships if o.uid == uid]

    def get_primary(
        self, uid: str, ownerships: List[Ownership]
    ) -> Optional[Ownership]:
        """获取用户的主老婆（旧命令的"今日老婆"）"""
        for o in ownerships:
            if o.uid == uid and o.is_primary:
                return o
        return None

    # ---------- 修改（需在群锁内调用，调用方传入 ownerships 引用并接收新列表） ----------

    @staticmethod
    def add(
        ownerships: List[Ownership], new_o: Ownership
    ) -> List[Ownership]:
        """新增一条所有权记录

        若新老婆已被他人持有，调用方需先 :meth:`remove_by_wid`（NTR 场景）；
        若同一 uid 已有同 wid，按幂等语义忽略。
        """
        for existing in ownerships:
            if existing.wid == new_o.wid:
                return ownerships
        ownerships.append(new_o)
        return ownerships

    @staticmethod
    def remove_by_wid(ownerships: List[Ownership], wid: str) -> List[Ownership]:
        """按 wid 删除所有权记录"""
        return [o for o in ownerships if o.wid != wid]

    @staticmethod
    def set_primary(
        ownerships: List[Ownership], uid: str, wid: str
    ) -> List[Ownership]:
        """将指定老婆设为该用户的主老婆（其余同 uid 的去掉 primary）"""
        for o in ownerships:
            if o.uid == uid:
                o.is_primary = o.wid == wid
        return ownerships

    @staticmethod
    def clear_primary_for_user(ownerships: List[Ownership], uid: str) -> List[Ownership]:
        """清除某用户所有老婆的 primary 标记"""
        for o in ownerships:
            if o.uid == uid:
                o.is_primary = False
        return ownerships

    @staticmethod
    def transfer(
        ownerships: List[Ownership],
        wid: str,
        new_uid: str,
        acquired_at: int,
        acquired_via: str,
    ) -> List[Ownership]:
        """转移老婆所有权（NTR）：清空亲密度、更新归属

        转移后新主人若此前已有 primary，本次转移的老婆不会自动成为 primary，
        由调用方决定是否调用 :meth:`set_primary`。
        """
        target: Optional[Ownership] = None
        for o in ownerships:
            if o.wid == wid:
                target = o
                break
        if target is None:
            return ownerships
        target.uid = new_uid
        target.acquired_at = acquired_at
        target.acquired_via = acquired_via
        target.intimacy = 0
        target.intimacy_updated_date = ""
        return ownerships


# ==================== 用户档案 ====================


class ProfileStore:
    """群内用户档案存储：dict[uid, UserProfile]"""

    def __init__(self, paths: Paths, gid: str):
        self._path = paths.group_profiles_file(gid)
        self._gid = gid

    def load_all(self) -> Dict[str, UserProfile]:
        raw = json_store.load_json(self._path, default={})
        if not isinstance(raw, dict):
            _error(f"profiles.json 顶层不是字典，已丢弃全部数据: {self._path}")
            return {}
        result: Dict[str, UserProfile] = {}
        for uid, item in raw.items():
            if not isinstance(item, dict):
                continue
            profile = UserProfile.from_dict(item)
            result[str(uid)] = profile
        return result

    def save_all(self, profiles: Dict[str, UserProfile]) -> None:
        json_store.save_json(
            self._path, {uid: p.to_dict() for uid, p in profiles.items()}
        )

    @staticmethod
    def get_or_create(
        profiles: Dict[str, UserProfile],
        uid: str,
        nick: str,
        capacity: int = 3,
        coins: int = 50,
    ) -> UserProfile:
        """获取或创建用户档案（不落盘，调用方在临界区内决定何时 save）"""
        profile = profiles.get(uid)
        if profile is None:
            profile = UserProfile.new_with_defaults(
                uid=uid, nick=nick, capacity=capacity, coins=coins
            )
            profiles[uid] = profile
        elif nick and profile.nick != nick:
            # 同步最新昵称（每次发消息都更新，避免改名后显示旧昵称）
            profile.nick = nick
        return profile


# ==================== 活动日志 ====================


class ActivityStore:
    """群内活动日志存储：dict[uid, ActivityLog]"""

    def __init__(self, paths: Paths, gid: str):
        self._path = paths.group_activity_file(gid)
        self._gid = gid

    def load_all(self) -> Dict[str, ActivityLog]:
        raw = json_store.load_json(self._path, default={})
        if not isinstance(raw, dict):
            _error(f"activity.json 顶层不是字典，已丢弃全部数据: {self._path}")
            return {}
        result: Dict[str, ActivityLog] = {}
        for uid, days in raw.items():
            if not isinstance(days, dict):
                continue
            result[str(uid)] = ActivityLog.from_dict(days)
        return result

    def save_all(self, logs: Dict[str, ActivityLog]) -> None:
        json_store.save_json(
            self._path, {uid: log.to_dict() for uid, log in logs.items()}
        )

    @staticmethod
    def log(
        logs: Dict[str, ActivityLog],
        uid: str,
        date: str,
        action: str,
        delta: int = 1,
    ) -> None:
        """记录活动（自动创建用户条目与当天条目）"""
        log = logs.get(uid)
        if log is None:
            log = ActivityLog()
            logs[uid] = log
        log.increment(date, action, delta)

    @staticmethod
    def prune_user(log: ActivityLog, keep_dates: "set[str] | None", days: int) -> None:
        log.prune_before(keep_dates=keep_dates, days=days)


# ==================== 交换请求（保留 v2.x 语义） ====================


class SwapRequestStore:
    """群内交换老婆请求存储：dict[uid_initiator, {target, date}]"""

    def __init__(self, paths: Paths, gid: str):
        self._path = paths.group_swap_requests_file(gid)
        self._gid = gid

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        raw = json_store.load_json(self._path, default={})
        if not isinstance(raw, dict):
            return {}
        # 仅保留 dict 型条目
        return {str(uid): rec for uid, rec in raw.items() if isinstance(rec, dict)}

    def save_all(self, requests: Dict[str, Dict[str, Any]]) -> None:
        json_store.save_json(self._path, dict(requests))


# ==================== NTR 开关状态 ====================


class NtrStatusStore:
    """群内 NTR 开关状态：dict[gid, bool]（单文件存储所有群）"""

    def __init__(self, paths: Paths):
        self._path = paths.data_dir
        # 放在 data 根目录，与 v2.x ntr_status.json 同等地位
        self._path = os.path.join(paths.data_dir, "ntr_status.json")

    def load_all(self) -> Dict[str, bool]:
        raw = json_store.load_json(self._path, default={})
        if not isinstance(raw, dict):
            return {}
        return {str(gid): bool(v) for gid, v in raw.items()}

    def save_all(self, statuses: Dict[str, bool]) -> None:
        json_store.save_json(self._path, {gid: bool(v) for gid, v in statuses.items()})
