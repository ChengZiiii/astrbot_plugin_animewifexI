"""所有权服务：群内老婆所有权的增删改查 + 上限校验 + 抽老婆流程编排。

设计原则：

* 所有公开方法内部走群锁 (:class:`app.storage.locks.GroupLocks`)；
* 多个 Store 在一次锁内批量 load → 修改 → save，避免半状态；
* 每日次数计数 (NTR/换/交换) 在锁内 check+increment，避免并发绕过限额；
* 抽老婆所需的图片获取委托给 :class:`app.services.wife_service.WifeService`；
* 方法返回小型 dataclass 结果，便于命令层格式化。

Phase 1 行为对齐 v2.x：

* 每用户 0 或 1 条 ``is_primary=True`` 的 ownership（"今日老婆"语义）；
* NTR 成功：目标主老婆转移给攻击者，攻击者旧主老婆删除（保留 v2.x 替换语义）；
* 数据结构本身支持多老婆（list 型 ownership.json），Phase 3 暴露 UI。
"""

from __future__ import annotations

import hashlib
import random as _random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..models import Ownership, UserProfile, WifeMeta
from ..models.enums import AcquireVia, Action, Rarity
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    DailyCountStore,
    NtrStatusStore,
    OwnershipStore,
    ProfileStore,
    SwapRequestStore,
    WivesMasterStore,
)
from ..utils.image import parse_wife_name
from ..utils.time import now_ts
from .cooldown_service import CooldownService
from .plugin_config import PluginConfig
from .rarity_service import RarityService
from .wife_service import WifeService

__all__ = [
    "OwnershipService",
    "DrawResult",
    "NtrResult",
    "ChangeResult",
    "SwapResult",
    "IntimacyResult",
    "wid_for_img",
    "DailyAction",
    "CooldownAction",
]


# ==================== wid 生成 ====================


def wid_for_img(img: str) -> str:
    """根据图片标识生成稳定 wid（``w_<sha1 前 8 位>``）

    同一 ``img`` 跨运行稳定；不同 ``img`` 几乎不会碰撞（sha1 8 位 ≈ 4.3 亿空间）。
    """
    h = hashlib.sha1(img.encode("utf-8")).hexdigest()[:8]
    return f"w_{h}"


# ==================== 动作 key（每日次数计数用） ====================


class DailyAction:
    """每日次数计数的动作 key

    与 :class:`app.models.enums.Action`（活动日志，含 SUCCESS/LOST 等统计字段）区别：
    这里只关心"触发型"动作，每次执行都计 1，不论后续成功失败（除非明确不消耗）。
    """

    NTR_ATTEMPT = "ntr_attempt"        # 牛老婆尝试（成功失败都计，与 v2.x 一致）
    CHANGE_ATTEMPT = "change_attempt"  # 换老婆（仅成功才计）
    SWAP_ATTEMPT = "swap_attempt"      # 发起交换请求
    RESET_USE = "reset_use"            # 重置功能使用
    PK_ATTEMPT = "pk_attempt"          # PK（Phase 3）


# ==================== 冷却动作 key ====================


class CooldownAction:
    """CooldownService 使用的动作 key（对应 PluginConfig 中的 *_cooldown 字段）"""

    DRAW = "draw"
    NTR = "ntr"
    CHANGE = "change"
    SWAP = "swap"
    PK = "pk"


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
    # Phase 3: 稀有度
    rarity: str = "N"
    rarity_emoji: str = "·"
    is_duplicate: bool = False
    duplicate_coins: int = 0
    pity_triggered: bool = False


@dataclass
class NtrResult:
    """牛老婆结果"""

    ok: bool                              # 流程是否正常完成（False 表示被前置拒绝）
    img: str = ""
    wid: str = ""
    success: bool = False                 # NTR 是否成功（False 可能是冷却/失败/限额）
    consumed_attempt: bool = False        # 是否消耗了一次当日 NTR 次数
    remaining_attempts: int = 0           # 今日剩余次数
    reason: str = ""                      # 失败/拒绝原因
    profile: Optional[UserProfile] = None


@dataclass
class ChangeResult:
    """换老婆结果"""

    ok: bool
    img: str = ""
    wid: str = ""
    consumed_attempt: bool = False
    remaining_changes: int = 0
    reason: str = ""


@dataclass
class SwapResult:
    """交换请求结果"""

    ok: bool
    reason: str = ""
    consumed_attempt: bool = False         # 是否消耗了一次当日交换次数
    refunded_old: bool = False             # 是否返还了旧请求次数


@dataclass
class IntimacyResult:
    """亲密度操作结果"""

    ok: bool
    intimacy: int = 0          # 操作后的亲密度
    reason: str = ""           # 失败原因
    coin_balance: int = 0      # 操作后的币余额


# ==================== 服务 ====================


class OwnershipService:
    """所有权 + 抽老婆 + 每日次数计数 业务编排"""

    def __init__(
        self,
        paths: Paths,
        config: PluginConfig,
        locks: GroupLocks,
        wife_service: WifeService,
        cooldown_service: "CooldownService | None" = None,
    ):
        self._paths = paths
        self._config = config
        self._locks = locks
        self._wife_service = wife_service
        self._cooldown = cooldown_service
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

    def _daily_count_store(self, gid: str) -> DailyCountStore:
        return DailyCountStore(self._paths, gid)

    # ---------- 全局老婆元数据 ----------

    def _ensure_wife_meta(self, img: str) -> str:
        """首次见到 img 时写入全局 WifeMeta；返回 wid（幂等）"""
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

    # ---------- 查询（只读，不进入群锁） ----------

    def get_primary_wid(self, gid: str, uid: str) -> Optional[str]:
        """查询用户主老婆的 wid（无主老婆返回 None）"""
        ownerships = self._ownership_store(gid).load_all()
        primary = self._ownership_store(gid).get_primary(uid, ownerships)
        return primary.wid if primary else None

    def get_primary_img(self, gid: str, uid: str) -> Optional[str]:
        """查询用户主老婆的图片标识（无则 None）"""
        wid = self.get_primary_wid(gid, uid)
        if not wid:
            return None
        meta = self.get_wife_meta(wid)
        return meta.img if meta else ""

    def get_profile(self, gid: str, uid: str, nick: str = "") -> UserProfile:
        """获取用户档案（不存在则按默认值创建并落盘）

        同步执行：``get_or_create`` 本身幂等且单条 dict 修改在 GIL 下原子。
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

    def get_ntr_enabled(self, gid: str) -> bool:
        """获取群 NTR 开关状态（默认开启）"""
        return bool(self._ntr_status.load_all().get(gid, True))

    def set_ntr_enabled(self, gid: str, enabled: bool) -> None:
        """设置群 NTR 开关状态"""
        statuses = self._ntr_status.load_all()
        statuses[gid] = bool(enabled)
        self._ntr_status.save_all(statuses)

    def get_daily_count(self, gid: str, uid: str, action: str, today: str) -> int:
        """查询某用户某动作当日已触发次数"""
        data = self._daily_count_store(gid).load_all()
        return DailyCountStore.get_count(data, uid, action, today)

    def reset_daily_count(self, gid: str, uid: str, action: str) -> None:
        """清除某用户某动作的当日次数计数（管理员重置他人）"""
        store = self._daily_count_store(gid)
        data = store.load_all()
        DailyCountStore.reset_user_action(data, uid, action)
        store.save_all(data)

    # ---------- 抽老婆 ----------

    async def draw_or_get_primary(
        self, gid: str, uid: str, nick: str, today: str, skip_check: bool = False
    ) -> DrawResult:
        """抽老婆：检查免费/券，抽新老婆

        Phase 3: 支持多次抽卡，每日免费次数 + 抽卡券
        skip_check: 跳过免费/券检查（用于十连抽卡，券已在外部消耗）
        """
        # H2: skip_check 时也跳过冷却
        if not skip_check and self._cooldown and self._config.draw_cooldown > 0:
            if not self._cooldown.check(
                gid, uid, CooldownAction.DRAW, self._config.draw_cooldown
            ):
                return DrawResult(ok=False, reason="cooldown")

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

            # 重置今日计数（跨天）
            if profile.today_draw_date != today:
                profile.today_draws = 0
                profile.today_free_draws = 0
                profile.today_draw_date = today

            if not skip_check:
                # 检查是否还能抽卡
                # daily_free_draws=0 表示无限制
                free_draws_unlimited = self._config.daily_free_draws == 0
                can_free_draw = free_draws_unlimited or profile.today_free_draws < self._config.daily_free_draws
                has_single_ticket = profile.inventory.get("draw_ticket_single", 0) > 0

                if not can_free_draw and not has_single_ticket:
                    # 没有免费次数也没有券，返回已有主老婆（如果有）
                    primary = ownership_store.get_primary(uid, ownerships)
                    if primary:
                        meta = self.get_wife_meta(primary.wid)
                        img = meta.img if meta else ""
                        profile_store.save_all(profiles)
                        return DrawResult(
                            ok=True, img=img, wid=primary.wid, is_new=False, profile=profile,
                            reason="no_draws"
                        )
                    profile_store.save_all(profiles)
                    return DrawResult(ok=False, reason="no_draws", profile=profile)

                # 决定使用哪种抽卡方式
                use_free = can_free_draw
                use_single_ticket = not use_free and has_single_ticket

                if use_free and not free_draws_unlimited:
                    profile.today_free_draws += 1
                elif use_single_ticket:
                    profile.inventory["draw_ticket_single"] -= 1

            profile.today_draws += 1

            img = await self._wife_service.fetch_image()
            if not img:
                # 回退：恢复券
                if not skip_check:
                    if use_free and not free_draws_unlimited:
                        profile.today_free_draws -= 1
                    elif use_single_ticket:
                        profile.inventory["draw_ticket_single"] += 1
                profile.today_draws -= 1
                profile_store.save_all(profiles)
                return DrawResult(ok=False, reason="fetch_failed", profile=profile)

            # Phase 3: 使用 RarityService 抽稀有度 + 处理保底/重复
            rarity_svc = RarityService(self._paths, self._config)
            draw_result = rarity_svc.draw(img, profile, profile.collection)

            wid = draw_result.wife.wid
            # 检查该用户是否已有老婆
            user_has_wife = any(o.uid == uid for o in ownerships)
            new_o = Ownership(
                wid=wid,
                uid=uid,
                acquired_at=now_ts(),
                acquired_via=AcquireVia.DRAW,
                is_primary=not user_has_wife,  # 该用户第一个老婆自动成为主老婆
            )
            ownership_store.add(ownerships, new_o)

            if draw_result.is_new and wid not in profile.collection:
                profile.collection.append(wid)
            profile.last_draw_date = today
            profile.total_draws += 1

            # 重复角色补偿
            if draw_result.duplicate_coins > 0:
                profile.coins += draw_result.duplicate_coins

            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.DRAW, 1)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)

            # P2.1: 新抽成功后更新冷却
            if self._cooldown and self._config.draw_cooldown > 0:
                self._cooldown.update(gid, uid, CooldownAction.DRAW)

            return DrawResult(
                ok=True,
                img=img,
                wid=wid,
                is_new=draw_result.is_new,
                profile=profile,
                rarity=draw_result.rarity,
                rarity_emoji=draw_result.rarity_emoji,
                is_duplicate=not draw_result.is_new,
                duplicate_coins=draw_result.duplicate_coins,
                pity_triggered=draw_result.pity_triggered,
            )

    # ---------- 十连抽卡 ----------

    async def draw_ten(
        self, gid: str, uid: str, nick: str, today: str
    ) -> list[DrawResult]:
        """十连抽卡：检查+消耗十连券，在单次锁内完成 10 次抽卡

        返回 DrawResult 列表（可能 < 10 张，抽取失败时中断）。
        券在锁内检查+消耗，避免并发 double-spend。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            profiles = profile_store.load_all()
            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )

            # 检查十连券
            if profile.inventory.get("draw_ticket_ten", 0) <= 0:
                return []

            # 消耗十连券
            profile.inventory["draw_ticket_ten"] -= 1
            profile_store.save_all(profiles)

            # 重置今日计数（跨天）
            if profile.today_draw_date != today:
                profile.today_draws = 0
                profile.today_free_draws = 0
                profile.today_draw_date = today

            results: list[DrawResult] = []
            ownerships = ownership_store.load_all()

            for i in range(10):
                img = await self._wife_service.fetch_image()
                if not img:
                    break

                # Phase 3: 使用 RarityService 抽稀有度
                rarity_svc = RarityService(self._paths, self._config)
                draw_result = rarity_svc.draw(img, profile, profile.collection)

                wid = draw_result.wife.wid
                user_has_wife = any(o.uid == uid for o in ownerships)
                new_o = Ownership(
                    wid=wid,
                    uid=uid,
                    acquired_at=now_ts(),
                    acquired_via=AcquireVia.DRAW,
                    is_primary=not user_has_wife,
                )
                ownership_store.add(ownerships, new_o)

                if draw_result.is_new and wid not in profile.collection:
                    profile.collection.append(wid)
                profile.last_draw_date = today
                profile.total_draws += 1
                profile.today_draws += 1

                if draw_result.duplicate_coins > 0:
                    profile.coins += draw_result.duplicate_coins

                results.append(DrawResult(
                    ok=True,
                    img=img,
                    wid=wid,
                    is_new=draw_result.is_new,
                    profile=profile,
                    rarity=draw_result.rarity,
                    rarity_emoji=draw_result.rarity_emoji,
                    is_duplicate=not draw_result.is_new,
                    duplicate_coins=draw_result.duplicate_coins,
                    pity_triggered=draw_result.pity_triggered,
                ))

            if results:
                activity_logs = activity_store.load_all()
                ActivityStore.log(activity_logs, uid, today, Action.DRAW, len(results))
                activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return results

    # ---------- 牛老婆 ----------

    async def try_ntr(
        self,
        gid: str,
        uid: str,
        tid: str,
        nick: str,
        today: str,
        is_revenge: bool = False,
        roll_seed: "Optional[float]" = None,
        target_wid: "Optional[str]" = None,
    ) -> NtrResult:
        """牛老婆尝试

        内部完成：NTR 开关校验、目标合法性校验、当日次数限额校验、
        概率判定、所有权转移、活动日志写入。

        ``is_revenge``: True 时走复仇路径（检查复仇窗口、应用成功率加成）。
        ``roll_seed`` 用于测试注入固定概率，正常调用传 ``None``。
        ``target_wid``: 指定要牛的老婆 wid。None 时随机选一个。
        """
        if not tid or tid == uid:
            return NtrResult(ok=False, reason="invalid_target")
        if not self.get_ntr_enabled(gid):
            return NtrResult(ok=False, reason="ntr_disabled")

        # P2.1: NTR 冷却检查
        if self._cooldown and self._config.ntr_cooldown > 0:
            if not self._cooldown.check(
                gid, uid, CooldownAction.NTR, self._config.ntr_cooldown
            ):
                return NtrResult(ok=False, reason="cooldown")

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)
            daily_store = self._daily_count_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()
            activity_logs = activity_store.load_all()
            daily_counts = daily_store.load_all()

            used = DailyCountStore.get_count(
                daily_counts, uid, DailyAction.NTR_ATTEMPT, today
            )
            if used >= self._config.ntr_max:
                return NtrResult(
                    ok=True,
                    success=False,
                    consumed_attempt=False,
                    reason="limit_reached",
                    remaining_attempts=0,
                )

            # H1: 指定 wid 或随机选一个
            attacker_profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )

            # 先消耗当日次数（无论后续成功/失败，与 v2.x 一致）
            new_count = DailyCountStore.increment(
                daily_counts, uid, DailyAction.NTR_ATTEMPT, today
            )
            remaining = max(0, self._config.ntr_max - new_count)

            if target_wid:
                target_wife = ownership_store.find_by_wid(target_wid, ownerships)
                if not target_wife or target_wife.uid != tid:
                    profile_store.save_all(profiles)
                    daily_store.save_all(daily_counts)
                    return NtrResult(
                        ok=True,
                        success=False,
                        consumed_attempt=True,
                        reason="target_no_wife",
                        remaining_attempts=remaining,
                        profile=attacker_profile,
                    )
            else:
                # 随机选目标的一个老婆
                target_wives = ownership_store.list_by_user(tid, ownerships)
                if not target_wives:
                    profile_store.save_all(profiles)
                    daily_store.save_all(daily_counts)
                    return NtrResult(
                        ok=True,
                        success=False,
                        consumed_attempt=True,
                        reason="target_no_wife",
                        remaining_attempts=remaining,
                        profile=attacker_profile,
                    )
                target_wife = _random.choice(target_wives)
                target_wid = target_wife.wid

            target_profile = profiles.get(tid)

            # P2.1: NTR 尝试消耗后更新冷却（无论后续成功/失败）
            if self._cooldown and self._config.ntr_cooldown > 0:
                self._cooldown.update(gid, uid, CooldownAction.NTR)

            # H1: 检查目标老婆是否被锁定
            from .marry_service import MarryService
            if MarryService.is_locked(target_wife):
                profile_store.save_all(profiles)
                daily_store.save_all(daily_counts)
                return NtrResult(
                    ok=True,
                    success=False,
                    consumed_attempt=True,
                    reason="target_locked",
                    remaining_attempts=remaining,
                    profile=attacker_profile,
                )

            # P2.4: 复仇检查
            revenge_valid = False
            if is_revenge and attacker_profile.last_ntr_by:
                rev_uid = attacker_profile.last_ntr_by.get("uid", "")
                rev_ts = float(attacker_profile.last_ntr_by.get("ts", 0))
                if rev_uid == tid and (now_ts() - rev_ts) < self._config.revenge_window_hours * 3600:
                    revenge_valid = True

            # 概率判定（复仇时应用成功率加成）
            ntr_prob = self._config.ntr_possibility
            if revenge_valid:
                ntr_prob = min(1.0, ntr_prob * self._config.revenge_success_multiplier)

            roll = roll_seed if roll_seed is not None else _random.random()
            success = roll < ntr_prob

            meta = self.get_wife_meta(target_wid)
            img = meta.img if meta else ""
            wid = target_wid

            if not success:
                profile_store.save_all(profiles)
                daily_store.save_all(daily_counts)
                return NtrResult(
                    ok=True,
                    success=False,
                    consumed_attempt=True,
                    img=img,
                    wid=wid,
                    reason="roll_failed",
                    remaining_attempts=remaining,
                    profile=attacker_profile,
                )

            # 成功：转移所有权（保留 v2.x 替换语义）
            attacker_old_primary = ownership_store.get_primary(uid, ownerships)
            if attacker_old_primary is not None:
                ownership_store.remove_by_wid(ownerships, attacker_old_primary.wid)
            ownership_store.transfer(
                ownerships,
                wid=wid,
                new_uid=uid,
                acquired_at=now_ts(),
                acquired_via=AcquireVia.NTR,
            )
            ownership_store.set_primary(ownerships, uid, wid)
            if wid not in attacker_profile.collection:
                attacker_profile.collection.append(wid)
            attacker_profile.total_ntr_success += 1
            if target_profile is not None:
                target_profile.total_ntr_lost += 1
                target_profile.last_ntr_by = {"uid": uid, "ts": now_ts()}

            # P2.3: NTR 成功时被牛方亲密度归零（转移后的 ownership 从 0 开始）
            transferred = ownership_store.find_by_wid(wid, ownerships)
            if transferred:
                transferred.intimacy = 0
                transferred.intimacy_updated_date = ""
                ownership_store.save_all(ownerships)

            # P2.4: 复仇成功后清空 last_ntr_by（防链式复仇）
            if revenge_valid:
                attacker_profile.last_ntr_by = {}

            ActivityStore.log(activity_logs, uid, today, Action.NTR_SUCCESS, 1)
            ActivityStore.log(activity_logs, tid, today, Action.NTR_LOST, 1)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)
            daily_store.save_all(daily_counts)

            return NtrResult(
                ok=True,
                success=True,
                consumed_attempt=True,
                img=img,
                wid=wid,
                remaining_attempts=remaining,
                profile=attacker_profile,
            )

    # ---------- 换老婆 ----------

    async def change_primary(
        self, gid: str, uid: str, nick: str, today: str
    ) -> ChangeResult:
        """换老婆：丢弃当前主老婆，抽一张新的

        v2.x 行为：当日已换 ``change_max_per_day`` 次拒绝；无老婆拒绝；
        抽取失败时老婆与次数都不动（故 count 在抽成功后才 increment）。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)
            daily_store = self._daily_count_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()
            daily_counts = daily_store.load_all()
            profile = ProfileStore.get_or_create(
                profiles,
                uid,
                nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )

            used = DailyCountStore.get_count(
                daily_counts, uid, DailyAction.CHANGE_ATTEMPT, today
            )
            if used >= self._config.change_max_per_day:
                profile_store.save_all(profiles)
                return ChangeResult(
                    ok=False, reason="limit_reached", remaining_changes=0
                )

            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None:
                profile_store.save_all(profiles)
                return ChangeResult(ok=False, reason="no_wife")

            img = await self._wife_service.fetch_image()
            if not img:
                profile_store.save_all(profiles)
                return ChangeResult(ok=False, reason="fetch_failed")

            wid = self._ensure_wife_meta(img)

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

            new_count = DailyCountStore.increment(
                daily_counts, uid, DailyAction.CHANGE_ATTEMPT, today
            )

            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.DRAW, 1)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)
            activity_store.save_all(activity_logs)
            daily_store.save_all(daily_counts)

            return ChangeResult(
                ok=True,
                img=img,
                wid=wid,
                consumed_attempt=True,
                remaining_changes=max(0, self._config.change_max_per_day - new_count),
            )

    # ---------- 交换老婆 ----------

    async def create_swap_request(
        self, gid: str, uid: str, tid: str, today: str
    ) -> SwapResult:
        """发起交换请求

        v2.x 行为：

        * 当日次数已达上限拒绝（除非有旧请求可返还次数）；
        * 已有待处理请求时重复发起视为更换目标：自动取消旧请求并返还次数；
        * 任一方当日无老婆拒绝。
        """
        if not tid or tid == uid:
            return SwapResult(ok=False, reason="invalid_target")

        # P2.1: 交换冷却检查
        if self._cooldown and self._config.swap_cooldown > 0:
            if not self._cooldown.check(
                gid, uid, CooldownAction.SWAP, self._config.swap_cooldown
            ):
                return SwapResult(ok=False, reason="cooldown")

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            daily_store = self._daily_count_store(gid)
            swap_store = self._swap_store(gid)

            ownerships = ownership_store.load_all()
            daily_counts = daily_store.load_all()
            swap_requests = swap_store.load_all()

            old_req = swap_requests.get(uid)
            used = DailyCountStore.get_count(
                daily_counts, uid, DailyAction.SWAP_ATTEMPT, today
            )
            refundable = (
                1
                if old_req
                and old_req.get("date") == today
                and used > 0
                else 0
            )

            if used - refundable >= self._config.swap_max_per_day:
                return SwapResult(ok=False, reason="limit_reached")

            if not ownership_store.get_primary(uid, ownerships):
                return SwapResult(ok=False, reason="self_no_wife")
            if not ownership_store.get_primary(tid, ownerships):
                return SwapResult(ok=False, reason="target_no_wife")

            refunded_old = False
            if old_req is not None:
                if refundable:
                    cur = daily_counts.get(uid, {}).get(DailyAction.SWAP_ATTEMPT, {})
                    if cur.get("date") == today:
                        cur["count"] = max(0, int(cur.get("count", 0)) - 1)
                refunded_old = bool(refundable)

            DailyCountStore.increment(
                daily_counts, uid, DailyAction.SWAP_ATTEMPT, today
            )
            swap_requests[uid] = {"target": tid, "date": today}

            swap_store.save_all(swap_requests)
            daily_store.save_all(daily_counts)

            # P2.1: 交换请求创建后更新冷却
            if self._cooldown and self._config.swap_cooldown > 0:
                self._cooldown.update(gid, uid, CooldownAction.SWAP)

            return SwapResult(
                ok=True,
                consumed_attempt=True,
                refunded_old=refunded_old,
            )

    async def accept_swap(
        self, gid: str, initiator_uid: str, accepter_uid: str, today: str
    ) -> SwapResult:
        """同意交换请求"""
        if initiator_uid == accepter_uid:
            return SwapResult(ok=False, reason="self_swap")

        async with self._locks.acquire(gid):
            swap_store = self._swap_store(gid)
            swap_requests = swap_store.load_all()
            rec = swap_requests.get(initiator_uid)

            if rec and rec.get("date") != today:
                del swap_requests[initiator_uid]
                swap_store.save_all(swap_requests)
                return SwapResult(ok=False, reason="expired")
            if not rec or rec.get("target") != accepter_uid:
                return SwapResult(ok=False, reason="mismatch")

            ownership_store = self._ownership_store(gid)
            ownerships = ownership_store.load_all()
            a_primary = ownership_store.get_primary(initiator_uid, ownerships)
            b_primary = ownership_store.get_primary(accepter_uid, ownerships)
            if not a_primary or not b_primary:
                del swap_requests[initiator_uid]
                swap_store.save_all(swap_requests)
                return SwapResult(ok=False, reason="wife_changed")

            ts = now_ts()
            ownership_store.remove_by_wid(ownerships, a_primary.wid)
            ownership_store.remove_by_wid(ownerships, b_primary.wid)
            ownership_store.add(
                ownerships,
                Ownership(
                    wid=b_primary.wid,
                    uid=initiator_uid,
                    acquired_at=ts,
                    acquired_via=AcquireVia.SWAP,
                    is_primary=True,
                ),
            )
            ownership_store.add(
                ownerships,
                Ownership(
                    wid=a_primary.wid,
                    uid=accepter_uid,
                    acquired_at=ts,
                    acquired_via=AcquireVia.SWAP,
                    is_primary=True,
                ),
            )

            activity_store = self._activity_store(gid)
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, initiator_uid, today, Action.SWAP, 1)
            ActivityStore.log(activity_logs, accepter_uid, today, Action.SWAP, 1)

            del swap_requests[initiator_uid]

            ownership_store.save_all(ownerships)
            activity_store.save_all(activity_logs)
            swap_store.save_all(swap_requests)
            return SwapResult(ok=True)

    async def reject_swap(
        self, gid: str, initiator_uid: str, accepter_uid: str, today: str
    ) -> SwapResult:
        """拒绝交换请求（删除请求，不返还次数）"""
        async with self._locks.acquire(gid):
            swap_store = self._swap_store(gid)
            swap_requests = swap_store.load_all()
            rec = swap_requests.get(initiator_uid)

            if rec and rec.get("date") != today:
                del swap_requests[initiator_uid]
                swap_store.save_all(swap_requests)
                return SwapResult(ok=False, reason="expired")
            if not rec or rec.get("target") != accepter_uid:
                return SwapResult(ok=False, reason="mismatch")

            del swap_requests[initiator_uid]
            swap_store.save_all(swap_requests)
            return SwapResult(ok=True)

    def list_swap_requests(self, gid: str, today: str) -> Dict[str, str]:
        """查看今日有效的交换请求：返回 ``{initiator_uid: target_uid}``"""
        raw = self._swap_store(gid).load_all()
        return {
            uid: rec.get("target", "")
            for uid, rec in raw.items()
            if rec.get("date") == today
        }

    def cancel_swap_for_users(
        self, gid: str, user_ids: List[str], today: str
    ) -> int:
        """老婆变动时取消相关的今日交换请求，返回取消条数

        接受调用方持锁（如在 ``try_ntr`` 内部调用）；若调用方未持锁，
        本方法会进入群锁保护。
        """
        # 由于是 sync 方法，无法 await 群锁；本方法设计为供已持锁的 sync 上下文调用，
        # 或在命令层调用 `` OwnershipService.try_ntr`` / ``change_primary`` 后用
        # 返回值标记是否有相关请求需要清理。
        #
        # Phase 1 的 v2.x 行为："NTR/换/抽" 成功后命令层不需要主动取消请求，
        # 因为 v2.x 的 cancel_swap_on_wife_change 是在锁内调用，
        # 这里提供 sync 版本即可。
        swap_store = self._swap_store(gid)
        daily_store = self._daily_count_store(gid)
        swap_requests = swap_store.load_all()
        daily_counts = daily_store.load_all()

        to_cancel = [
            req_uid
            for req_uid, req in swap_requests.items()
            if req.get("date") == today
            and (req_uid in user_ids or req.get("target") in user_ids)
        ]
        if not to_cancel:
            return 0

        for req_uid in to_cancel:
            rec = swap_requests.get(req_uid, {})
            if rec.get("date") != today:
                continue
            cur = daily_counts.get(req_uid, {}).get(DailyAction.SWAP_ATTEMPT, {})
            if cur.get("date") == today and int(cur.get("count", 0)) > 0:
                cur["count"] = max(0, int(cur.get("count", 0)) - 1)
            del swap_requests[req_uid]

        swap_store.save_all(swap_requests)
        daily_store.save_all(daily_counts)
        return len(to_cancel)

    # ---------- 重置（管理员 / 概率型） ----------

    async def reset_user_action(
        self,
        gid: str,
        operator_uid: str,
        operator_is_admin: bool,
        target_uid: str,
        action: str,
        today: str,
        roll_seed: "Optional[float]" = None,
    ) -> Dict[str, Any]:
        """通用重置逻辑（v2.x ``_do_reset`` 的服务层版本）

        管理员直接成功；普通用户消耗 ``reset_max_uses_per_day`` 一次，
        按 ``reset_success_rate`` 概率成功，失败时返回 ``do_mute=True`` 让命令层禁言。
        """
        if operator_is_admin:
            async with self._locks.acquire(gid):
                daily_store = self._daily_count_store(gid)
                daily_counts = daily_store.load_all()
                DailyCountStore.reset_user_action(daily_counts, target_uid, action)
                daily_store.save_all(daily_counts)
            return {
                "ok": True,
                "consumed_reset": False,
                "do_mute": False,
                "mute_duration": 0,
                "reason": "admin",
            }

        async with self._locks.acquire(gid):
            daily_store = self._daily_count_store(gid)
            daily_counts = daily_store.load_all()

            reset_used = DailyCountStore.get_count(
                daily_counts, operator_uid, DailyAction.RESET_USE, today
            )
            if reset_used >= self._config.reset_max_uses_per_day:
                return {
                    "ok": False,
                    "consumed_reset": False,
                    "do_mute": False,
                    "mute_duration": 0,
                    "reason": "limit_reached",
                }

            DailyCountStore.increment(
                daily_counts, operator_uid, DailyAction.RESET_USE, today
            )

            roll = roll_seed if roll_seed is not None else _random.random()
            if roll < self._config.reset_success_rate:
                DailyCountStore.reset_user_action(daily_counts, target_uid, action)
                daily_store.save_all(daily_counts)
                return {
                    "ok": True,
                    "consumed_reset": True,
                    "do_mute": False,
                    "mute_duration": 0,
                    "reason": "success",
                }

            daily_store.save_all(daily_counts)
            return {
                "ok": False,
                "consumed_reset": True,
                "do_mute": True,
                "mute_duration": self._config.reset_mute_duration,
                "reason": "roll_failed",
            }

    # ---------- 亲密度 ----------

    async def pet_wife(
        self, gid: str, uid: str, nick: str, today: str
    ) -> IntimacyResult:
        """摸头：消耗币增加亲密度

        要求：有主老婆、币余额 >= intimacy_pet_coin_cost、亲密度未满。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None:
                return IntimacyResult(ok=False, reason="no_wife")

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )

            if profile.coins < self._config.intimacy_pet_coin_cost:
                return IntimacyResult(
                    ok=False, reason="not_enough_coins",
                    intimacy=primary.intimacy, coin_balance=profile.coins,
                )

            if primary.intimacy >= self._config.intimacy_max:
                return IntimacyResult(
                    ok=False, reason="intimacy_maxed",
                    intimacy=primary.intimacy, coin_balance=profile.coins,
                )

            profile.coins -= self._config.intimacy_pet_coin_cost
            primary.intimacy = min(
                self._config.intimacy_max,
                primary.intimacy + self._config.intimacy_pet_gain,
            )
            primary.intimacy_updated_date = today

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return IntimacyResult(
                ok=True, intimacy=primary.intimacy, coin_balance=profile.coins,
            )

    async def gift_wife(
        self, gid: str, uid: str, nick: str, today: str
    ) -> IntimacyResult:
        """送礼：高消耗高加成亲密度

        要求：有主老婆、币余额 >= intimacy_gift_coin_cost、亲密度未满。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            primary = ownership_store.get_primary(uid, ownerships)
            if primary is None:
                return IntimacyResult(ok=False, reason="no_wife")

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                capacity=self._config.default_capacity,
                coins=self._config.initial_coins,
            )

            if profile.coins < self._config.intimacy_gift_coin_cost:
                return IntimacyResult(
                    ok=False, reason="not_enough_coins",
                    intimacy=primary.intimacy, coin_balance=profile.coins,
                )

            if primary.intimacy >= self._config.intimacy_max:
                return IntimacyResult(
                    ok=False, reason="intimacy_maxed",
                    intimacy=primary.intimacy, coin_balance=profile.coins,
                )

            profile.coins -= self._config.intimacy_gift_coin_cost
            primary.intimacy = min(
                self._config.intimacy_max,
                primary.intimacy + self._config.intimacy_gift_gain,
            )
            primary.intimacy_updated_date = today

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return IntimacyResult(
                ok=True, intimacy=primary.intimacy, coin_balance=profile.coins,
            )

    async def daily_intimacy_increment_for_group(self, gid: str, today: str) -> int:
        """零点循环：所有持有老婆 +intimacy_per_day（幂等，每日只加一次）

        返回更新的 ownership 数量。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            ownerships = ownership_store.load_all()

            updated = 0
            for o in ownerships:
                if o.intimacy_updated_date == today:
                    continue
                if o.intimacy >= self._config.intimacy_max:
                    continue
                o.intimacy = min(
                    self._config.intimacy_max,
                    o.intimacy + self._config.intimacy_per_day,
                )
                o.intimacy_updated_date = today
                updated += 1

            if updated:
                ownership_store.save_all(ownerships)
            return updated

    @staticmethod
    def intimacy_level(intimacy: int) -> int:
        """亲密度 → 等级（1~10），线性分段"""
        if intimacy <= 0:
            return 0
        # 每 10 点一级，上限 10 级
        return min(10, (intimacy - 1) // 10 + 1)

    @staticmethod
    def intimacy_level_emoji(intimacy: int) -> str:
        """亲密度等级 emoji 展示（如 ❤️ Lv.3）"""
        lv = OwnershipService.intimacy_level(intimacy)
        if lv <= 0:
            return ""
        return f"❤️ Lv.{lv}"

    # ---------- 零点清理（由 plugin 定时循环调用） ----------

    async def prune_daily_counts_for_group(self, gid: str, today: str) -> bool:
        """删除某群所有非今日的次数记录，返回是否有变动"""
        async with self._locks.acquire(gid):
            store = self._daily_count_store(gid)
            data = store.load_all()
            changed = DailyCountStore.prune_for_group(data, today)
            if changed:
                store.save_all(data)
            return changed

    async def prune_swap_requests_for_group(self, gid: str, today: str) -> bool:
        """删除某群所有非今日的交换请求，返回是否有变动"""
        async with self._locks.acquire(gid):
            store = self._swap_store(gid)
            data = store.load_all()
            before = len(data)
            cleaned = {
                uid: rec for uid, rec in data.items() if rec.get("date") == today
            }
            if len(cleaned) != before:
                store.save_all(cleaned)
                return True
            return False

    async def prune_activity_logs_for_group(self, gid: str, today: str) -> bool:
        """删除某群所有早于 activity_window_days 的活动日志日期 key"""
        async with self._locks.acquire(gid):
            activity_store = self._activity_store(gid)
            logs = activity_store.load_all()
            changed = False
            for uid, log in logs.items():
                before = len(log.days)
                log.prune_before(days=self._config.activity_window_days)
                if len(log.days) != before:
                    changed = True
            if changed:
                activity_store.save_all(logs)
            return changed

    def known_groups(self) -> List[str]:
        """返回已知群列表（基于锁池，用于零点遍历）"""
        return self._locks.known_groups()
