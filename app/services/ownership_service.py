"""所有权服务：群内老婆所有权的增删改查 + 上限校验 + 抽老婆流程编排。

设计原则：

* 所有公开方法内部走群锁 (:class:`app.storage.locks.GroupLocks`)；
* 多个 Store 在一次锁内批量 load → 修改 → save，避免半状态；
* 抽老婆所需的图片获取委托给 :class:`app.services.wife_service.WifeService`；
* 方法返回小型 dataclass 结果（不返回原始 Store 对象），便于命令层格式化。

Phase 1 行为对齐 v2.x：

* 每用户 0 或 1 条 ``is_primary=True`` 的 ownership（"今日老婆"语义）；
* NTR 成功：目标主老婆转移给攻击者，攻击者旧主老婆删除（保留 v2.x 替换语义）；
* 数据结构本身支持多老婆（list 型 ownership.json），Phase 3 暴露 UI。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..models import ActivityLog, Ownership, UserProfile, WifeMeta
from ..models.enums import AcquireVia, Action, Rarity
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    NtrStatusStore,
    OwnershipStore,
    ProfileStore,
    SwapRequestStore,
    WivesMasterStore,
)
from ..utils.image import parse_wife_name
from ..utils.time import now_ts
from .plugin_config import PluginConfig
from .wife_service import WifeService

__all__ = [
    "OwnershipService",
    "DrawResult",
    "NtrResult",
    "ChangeResult",
    "SwapResult",
]


# ==================== wid 生成 ====================


def wid_for_img(img: str) -> str:
    """根据图片标识生成稳定 wid（``w_<sha1 前 8 位>``）

    同一 ``img`` 跨运行稳定；不同 ``img`` 几乎不会碰撞（sha1 8 位 ≈ 4.3 亿空间）。
    """
    h = hashlib.sha1(img.encode("utf-8")).hexdigest()[:8]
    return f"w_{h}"


# ==================== 结果 dataclass ====================


@dataclass
class DrawResult:
    """抽老婆结果"""

    ok: bool
    img: str = ""
    wid: str = ""
    is_new: bool = False            # 是否本次新抽（False 表示已有当日老婆）
    reason: str = ""                # 失败原因：'fetch_failed' 等
    profile: Optional[UserProfile] = None


@dataclass
class NtrResult:
    """牛老婆结果"""

    ok: bool
    img: str = ""
    wid: str = ""
    success: bool = False           # NTR 是否成功（False 可能是冷却/失败/限额）
    remaining_attempts: int = 0     # 今日剩余次数
    reason: str = ""                # 失败/拒绝原因
    profile: Optional[UserProfile] = None


@dataclass
class ChangeResult:
    """换老婆结果"""

    ok: bool
    img: str = ""
    wid: str = ""
    remaining_changes: int = 0
    reason: str = ""


@dataclass
class SwapResult:
    """交换老婆结果"""

    ok: bool
    reason: str = ""
    swap_consumed: bool = False     # 是否消耗了发起次数


# ==================== 服务 ====================


class OwnershipService:
    """所有权 + 抽老婆业务编排"""

    def __init__(
        self,
        paths: Paths,
        config: PluginConfig,
        locks: GroupLocks,
        wife_service: WifeService,
    ):
        self._paths = paths
        self._config = config
        self._locks = locks
        self._wife_service = wife_service
        # 全局老婆元数据与 NTR 开关不按群隔离
        self._wives_master = WivesMasterStore(paths)
        self._ntr_status = NtrStatusStore(paths)

    # ---------- 群级 Store 工厂 ----------

    def _ownership_store(self, gid: str) -> OwnershipStore:
        return OwnershipStore(self._paths, gid)

    def _profile_store(self, gid: str) -> ProfileStore:
        return ProfileStore(self._paths, gid)

    def _activity_store(self, gid: str) -> ActivityStore:
        return ActivityStore(self._paths, gid)

    def _swap_store(self, gid: str) -> SwapRequestStore:
        return SwapRequestStore(self._paths, gid)

    # ---------- 全局老婆元数据 ----------

    def _ensure_wife_meta(self, img: str) -> str:
        """首次见到 img 时写入全局 WifeMeta；返回 wid

        幂等：已存在时不覆盖（避免重置 first_seen）。
        """
        wid = wid_for_img(img)
        all_metas = self._wives_master.load_all()
        if wid in all_metas:
            return wid
        chara, source = parse_wife_name(img)
        meta = WifeMeta(
            wid=wid,
            img=img,
            source=source or "",
            chara=chara or "",
            # Phase 1 不实现稀有度抽卡，默认 N（Phase 3 由 rarity_service 重写）
            rarity=Rarity.N,
            first_seen=now_ts(),
        )
        all_metas[wid] = meta
        self._wives_master.save_all(all_metas)
        return wid

    def get_wife_meta(self, wid: str) -> Optional[WifeMeta]:
        """根据 wid 查询老婆元数据"""
        return self._wives_master.load_all().get(wid)

    def get_wife_meta_by_img(self, img: str) -> Optional[WifeMeta]:
        """根据 img 查询老婆元数据"""
        return self._wives_master.load_all().get(wid_for_img(img))

    # ---------- 查询 ----------

    def get_primary_wid(self, gid: str, uid: str) -> Optional[str]:
        """查询用户主老婆的 wid（无主老婆返回 None）

        只读操作不进入群锁（list 读取在 Python 单线程 GIL 下安全）；
        若调用方后续要做写操作，应直接走 :meth:`draw_or_get_primary` 等加锁方法。
        """
        ownerships = self._ownership_store(gid).load_all()
        primary = self._ownership_store(gid).get_primary(uid, ownerships)
        return primary.wid if primary else None

    def get_primary_img(self, gid: str, uid: str) -> Optional[str]:
        """查询用户主老婆的图片标识（无则 None）"""
        wid = self.get_primary_wid(gid, uid)
        if not wid:
            return None
        meta = self.get_wife_meta(wid)
        return meta.img if meta else None

    def get_profile(self, gid: str, uid: str, nick: str = "") -> UserProfile:
        """获取用户档案（不存在则按默认值创建并落盘）

        只读命令（查老婆、面板）使用此方法。同步执行：
        ``get_or_create`` 本身幂等且单条 dict 修改在 GIL 下原子，
        即使与同群并发写协程交错也不会损坏数据，最坏情况是重复创建一份
        默认 profile 被后写的覆盖。
        """
        profiles = self._profile_store(gid).load_all()
        profile = ProfileStore.get_or_create(
            profiles,
            uid,
            nick,
            capacity=self._config.default_capacity,
            coins=self._config.initial_coins,
        )
        self._profile_store(gid).save_all(profiles)
        return profile

    # ---------- 抽老婆 ----------

    async def draw_or_get_primary(
        self, gid: str, uid: str, nick: str, today: str
    ) -> DrawResult:
        """抽老婆：有当日主老婆则返回，否则新抽一张

        v2.x 行为：每用户每天只有一张主老婆，重复抽返回同一张。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            # 已有主老婆：直接返回（v2.x 抽老婆幂等语义）
            primary = ownership_store.get_primary(uid, ownerships)
            profile = ProfileStore.get_or_create(
                profiles,
                uid,
                nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )
            if primary:
                meta = self.get_wife_meta(primary.wid)
                img = meta.img if meta else ""
                profile_store.save_all(profiles)
                return DrawResult(
                    ok=True, img=img, wid=primary.wid, is_new=False, profile=profile
                )

            # 新抽一张（图片获取在锁外更佳，但 v2.x 也是锁内 fetch，保持一致）
            img = await self._wife_service.fetch_image()
            if not img:
                profile_store.save_all(profiles)
                return DrawResult(ok=False, reason="fetch_failed", profile=profile)

            wid = self._ensure_wife_meta(img)
            new_o = Ownership(
                wid=wid,
                uid=uid,
                acquired_at=now_ts(),
                acquired_via=AcquireVia.DRAW,
                is_primary=True,
            )
            ownership_store.add(ownerships, new_o)

            # 更新 profile
            if wid not in profile.collection:
                profile.collection.append(wid)
            profile.last_draw_date = today
            profile.total_draws += 1

            # 活动日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.DRAW, 1)

            # 落盘
            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)

            return DrawResult(
                ok=True, img=img, wid=wid, is_new=True, profile=profile
            )

    # ---------- 牛老婆 ----------

    async def try_ntr(
        self,
        gid: str,
        uid: str,
        tid: str,
        nick: str,
        today: str,
        daily_ntr_count: int,
        ntr_enabled: bool,
        roll_seed: Optional[float] = None,
    ) -> NtrResult:
        """牛老婆尝试

        ``daily_ntr_count`` 为调用方维护的"今日已牛次数"（与限额校验解耦，
        便于命令层接入 records.json 或未来 cooldown_service）。

        ``roll_seed`` 用于测试注入固定概率，正常调用传 ``None``。

        返回 :class:`NtrResult`，调用方根据 ``success``/``reason`` 决定提示。
        """
        if not ntr_enabled:
            return NtrResult(ok=False, reason="ntr_disabled")
        if not tid or tid == uid:
            return NtrResult(ok=False, reason="invalid_target")
        if daily_ntr_count >= self._config.ntr_max:
            return NtrResult(
                ok=True,
                success=False,
                reason="limit_reached",
                remaining_attempts=0,
            )

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()
            activity_logs = activity_store.load_all()

            target_primary = ownership_store.get_primary(tid, ownerships)
            attacker_profile = ProfileStore.get_or_create(
                profiles,
                uid,
                nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )
            target_profile = profiles.get(tid)  # 不存在不创建，避免污染数据

            if not target_primary:
                profile_store.save_all(profiles)
                return NtrResult(
                    ok=True,
                    success=False,
                    reason="target_no_wife",
                    remaining_attempts=self._config.ntr_max - daily_ntr_count,
                    profile=attacker_profile,
                )

            # 概率判定
            import random as _r
            roll = roll_seed if roll_seed is not None else _r.random()
            success = roll < self._config.ntr_possibility

            meta = self.get_wife_meta(target_primary.wid)
            img = meta.img if meta else ""
            wid = target_primary.wid

            if not success:
                # 失败：仅记活动日志 + profile.total_ntr_lost（攻击者发起但失败）
                ActivityStore.log(activity_logs, uid, today, Action.NTR_SUCCESS, 0)
                profile_store.save_all(profiles)
                activity_store.save_all(activity_logs)
                return NtrResult(
                    ok=True,
                    success=False,
                    img=img,
                    wid=wid,
                    reason="roll_failed",
                    remaining_attempts=self._config.ntr_max - daily_ntr_count - 1,
                    profile=attacker_profile,
                )

            # 成功：转移所有权（保留 v2.x 替换语义）
            # 1. 删除攻击者旧主老婆（若有）
            attacker_old_primary = ownership_store.get_primary(uid, ownerships)
            if attacker_old_primary is not None:
                ownership_store.remove_by_wid(ownerships, attacker_old_primary.wid)
            # 2. 转移目标主老婆给攻击者，并设为攻击者主老婆
            ownership_store.transfer(
                ownerships,
                wid=wid,
                new_uid=uid,
                acquired_at=now_ts(),
                acquired_via=AcquireVia.NTR,
            )
            ownership_store.set_primary(ownerships, uid, wid)
            # 3. 收集图鉴
            if wid not in attacker_profile.collection:
                attacker_profile.collection.append(wid)
            attacker_profile.total_ntr_success += 1
            if target_profile is not None:
                target_profile.total_ntr_lost += 1
                # 复仇窗口：记录被谁、什么时候牛的
                target_profile.last_ntr_by = {"uid": uid, "ts": now_ts()}

            # 活动日志双写
            ActivityStore.log(activity_logs, uid, today, Action.NTR_SUCCESS, 1)
            ActivityStore.log(activity_logs, tid, today, Action.NTR_LOST, 1)

            # 落盘
            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)

            return NtrResult(
                ok=True,
                success=True,
                img=img,
                wid=wid,
                remaining_attempts=self._config.ntr_max - daily_ntr_count - 1,
                profile=attacker_profile,
            )

    # ---------- 换老婆 ----------

    async def change_primary(
        self,
        gid: str,
        uid: str,
        nick: str,
        today: str,
        daily_change_count: int,
    ) -> ChangeResult:
        """换老婆：丢弃当前主老婆，抽一张新的

        v2.x 行为：当日已换 change_max_per_day 次拒绝；无老婆拒绝；
        抽取失败时老婆与次数都不动。
        """
        if daily_change_count >= self._config.change_max_per_day:
            return ChangeResult(
                ok=False,
                reason="limit_reached",
                remaining_changes=0,
            )

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()
            profile = ProfileStore.get_or_create(
                profiles,
                uid,
                nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )

            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None:
                profile_store.save_all(profiles)
                return ChangeResult(ok=False, reason="no_wife")

            # 先抽到新老婆再替换；抽取失败时老婆和次数都保持不动
            img = await self._wife_service.fetch_image()
            if not img:
                profile_store.save_all(profiles)
                return ChangeResult(ok=False, reason="fetch_failed")

            wid = self._ensure_wife_meta(img)

            # 删除旧主老婆 + 新建主老婆
            ownership_store.remove_by_wid(ownerships, primary.wid)
            ownership_store.add(
                ownerships,
                Ownership(
                    wid=wid,
                    uid=uid,
                    acquired_at=now_ts(),
                    acquired_via=AcquireVia.DRAW,
                    is_primary=True,
                ),
            )
            if wid not in profile.collection:
                profile.collection.append(wid)
            profile.last_draw_date = today
            profile.total_draws += 1

            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.DRAW, 1)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)

            return ChangeResult(
                ok=True,
                img=img,
                wid=wid,
                remaining_changes=self._config.change_max_per_day - daily_change_count - 1,
            )

    # ---------- 交换老婆 ----------

    async def swap_primaries(
        self,
        gid: str,
        uid_a: str,
        uid_b: str,
        today: str,
    ) -> Tuple[bool, str]:
        """交换两用户的主老婆（仅交换 wid，保留各自昵称）

        用于"同意交换"命令。返回 ``(ok, reason)``。
        调用方负责校验发起次数限额与目标是否一致。
        """
        if uid_a == uid_b:
            return False, "self_swap"

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            ownerships = ownership_store.load_all()

            a_primary = ownership_store.get_primary(uid_a, ownerships)
            b_primary = ownership_store.get_primary(uid_b, ownerships)
            if not a_primary or not b_primary:
                return False, "no_wife"

            # 交换 wid：删除旧记录 + 添加新记录（保留 acquired_at 不动会误导统计，
            # 因此各自重置 acquired_at + acquired_via=swap）
            import time as _t
            ts = now_ts()
            ownership_store.remove_by_wid(ownerships, a_primary.wid)
            ownership_store.remove_by_wid(ownerships, b_primary.wid)
            ownership_store.add(
                ownerships,
                Ownership(
                    wid=b_primary.wid,
                    uid=uid_a,
                    acquired_at=ts,
                    acquired_via=AcquireVia.SWAP,
                    is_primary=True,
                ),
            )
            ownership_store.add(
                ownerships,
                Ownership(
                    wid=a_primary.wid,
                    uid=uid_b,
                    acquired_at=ts,
                    acquired_via=AcquireVia.SWAP,
                    is_primary=True,
                ),
            )

            activity_store = self._activity_store(gid)
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid_a, today, Action.SWAP, 1)
            ActivityStore.log(activity_logs, uid_b, today, Action.SWAP, 1)

            ownership_store.save_all(ownerships)
            activity_store.save_all(activity_logs)
            return True, ""

    # ---------- 交换请求存储（旧 v2.x 行为） ----------

    def load_swap_requests(self, gid: str) -> Dict[str, dict]:
        """加载群内交换请求（命令层使用）"""
        return self._swap_store(gid).load_all()

    def save_swap_requests(self, gid: str, requests: Dict[str, dict]) -> None:
        """保存群内交换请求（命令层使用，需在群锁内调用）"""
        self._swap_store(gid).save_all(requests)

    # ---------- NTR 开关 ----------

    def load_ntr_statuses(self) -> Dict[str, bool]:
        """加载所有群的 NTR 开关状态"""
        return self._ntr_status.load_all()

    def save_ntr_statuses(self, statuses: Dict[str, bool]) -> None:
        self._ntr_status.save_all(statuses)

    # ---------- 上限校验 ----------

    def check_capacity(
        self, profile: UserProfile, expansion_count: int = 0
    ) -> Tuple[bool, str]:
        """校验用户能否再持有更多老婆

        ``expansion_count`` 为已使用的扩容道具数量（Phase 3 商城用）。
        返回 ``(ok, reason)``。
        """
        capacity = min(
            profile.capacity + expansion_count,
            self._config.max_capacity,
        )
        # 实际持有数需要查 ownerships；本方法只做容量上限检查，由调用方传入当前持有数
        # 这里仅返回上限值，调用方自行比较
        return True, str(capacity)
