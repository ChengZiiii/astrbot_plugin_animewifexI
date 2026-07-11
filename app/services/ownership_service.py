"""所有权服务：群内老婆所有权的增删改查 + 上限校验 + 抽老婆流程编排。

设计原则：

* 所有公开方法内部走群锁 (:class:`app.storage.locks.GroupLocks`)；
* 多个 Store 在一次锁内批量 load → 修改 → save，避免半状态；
* 每日次数计数 (NTR/交换) 在锁内 check+increment，避免并发绕过限额；
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
    "SwapResult",
    "SwitchPrimaryResult",
    "IntimacyResult",
    "wid_for_img",
    "DailyAction",
    "CooldownAction",
]

# 每用户老婆上限（硬上限）
MAX_WIVES_PER_USER = 999


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
    SWAP_ATTEMPT = "swap_attempt"      # 发起交换请求
    PK_ATTEMPT = "pk_attempt"          # PK（Phase 3）


# ==================== 冷却动作 key ====================


class CooldownAction:
    """CooldownService 使用的动作 key（对应 PluginConfig 中的 *_cooldown 字段）"""

    DRAW = "draw"
    NTR = "ntr"
    SWAP = "swap"
    PK = "pk"
    CHAT = "chat"
    DATE = "date"


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
    final_probability: float = 0.0        # T20: 最终 NTR 概率
    stolen_work_reward: int = 0
    stolen_work_wid: str = ""
    insurance_used: bool = False
    insurance_bonus_coins: int = 0
    contract_inherited: bool = False      # 被牛时合约加成生效
    contract_amount: int = 0              # 合约金额
    partner_broken: bool = False


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
    wid: str = ""


@dataclass
class SwitchPrimaryResult:
    """切换主老婆结果。"""

    ok: bool
    reason: str = ""
    wid: str = ""
    wife_name: str = ""


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

    def _resolve_owned_target(
        self,
        gid: str,
        uid: str,
        ownerships: list[Ownership],
        selected_wid: str | None,
    ) -> Optional[Ownership]:
        """解析用户指定老婆；未指定时回退主老婆。"""
        ownership_store = self._ownership_store(gid)
        if selected_wid:
            target = ownership_store.find_by_wid(selected_wid, ownerships)
            if target is None or target.uid != uid:
                return None
            return target
        return ownership_store.get_primary(uid, ownerships)

    async def switch_primary(self, gid: str, uid: str, wid: str) -> SwitchPrimaryResult:
        """将指定 wid 设为当前用户主老婆。"""
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            ownerships = ownership_store.load_all()

            current = ownership_store.get_primary(uid, ownerships)
            if current is None:
                return SwitchPrimaryResult(ok=False, reason="no_wife")

            target = ownership_store.find_by_wid(wid, ownerships)
            if target is None or target.uid != uid:
                return SwitchPrimaryResult(ok=False, reason="wife_not_found")

            wife_meta = self.get_wife_meta(wid)
            wife_name = (
                wife_meta.chara or wife_meta.img if wife_meta is not None else wid
            )

            if target.is_primary:
                return SwitchPrimaryResult(
                    ok=True,
                    reason="already_primary",
                    wid=wid,
                    wife_name=wife_name,
                )

            ownership_store.set_primary(ownerships, uid, wid)
            ownership_store.save_all(ownerships)
            return SwitchPrimaryResult(ok=True, wid=wid, wife_name=wife_name)

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

            # 老婆上限检查
            my_wives_count = sum(1 for o in ownerships if o.uid == uid)
            if my_wives_count >= MAX_WIVES_PER_USER:
                profile_store.save_all(profiles)
                return DrawResult(ok=False, reason="limit_reached")

            profile = ProfileStore.get_or_create(
                profiles,
                uid,
                nick,
    
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
            ownerships = ownership_store.load_all()

            # 老婆上限检查
            my_wives_count = sum(1 for o in ownerships if o.uid == uid)
            if my_wives_count >= MAX_WIVES_PER_USER:
                return []

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
    
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

            for i in range(10):
                # 每次抽卡前检查上限
                my_wives_count = sum(1 for o in ownerships if o.uid == uid)
                if my_wives_count >= MAX_WIVES_PER_USER:
                    break

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

            # 老婆上限检查（攻击者已满则拒绝 NTR）
            my_wives_count = sum(1 for o in ownerships if o.uid == uid)
            if my_wives_count >= MAX_WIVES_PER_USER:
                return NtrResult(ok=False, reason="limit_reached")

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
    
                coins=self._config.initial_coins,
            )

            # 复仇必须固定追回 last_ntr_by.wid 记录的那位老婆；
            # 否则会退化成随机 NTR，可能牛回攻击者的其他老婆。
            if is_revenge and not target_wid and attacker_profile.last_ntr_by:
                rev_uid = attacker_profile.last_ntr_by.get("uid", "")
                rev_ts = float(attacker_profile.last_ntr_by.get("ts", 0))
                rev_wid = str(attacker_profile.last_ntr_by.get("wid", "") or "")
                if (
                    rev_wid
                    and rev_uid == tid
                    and (now_ts() - rev_ts) < self._config.revenge_window_hours * 3600
                ):
                    target_wid = rev_wid

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
                # Phase 6: 已死亡的老婆不能被牛
                if target_wife.is_dead:
                    profile_store.save_all(profiles)
                    daily_store.save_all(daily_counts)
                    return NtrResult(
                        ok=True,
                        success=False,
                        consumed_attempt=True,
                        reason="target_dead",
                        remaining_attempts=remaining,
                        profile=attacker_profile,
                        wid=target_wid,
                    )
            else:
                # 随机选目标的一个老婆（跳过被锁的、跳过已死亡的）
                from .marry_service import MarryService
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
                # Phase 6: 排除死亡老婆（尸体不让牛走）
                alive_unlocked_wives = [
                    w for w in target_wives
                    if not MarryService.is_locked(w) and not w.is_dead
                ]
                if not alive_unlocked_wives:
                    # 全部被锁或全部死亡；用第一个存在的老婆信息（仅供提示）
                    target_wife = target_wives[0]
                    target_wid = target_wife.wid
                    profile_store.save_all(profiles)
                    daily_store.save_all(daily_counts)
                    # 死亡优先提示
                    if all(w.is_dead for w in target_wives):
                        return NtrResult(
                            ok=True,
                            success=False,
                            consumed_attempt=True,
                            reason="target_all_dead",
                            remaining_attempts=remaining,
                            profile=attacker_profile,
                            wid=target_wid,
                        )
                    return NtrResult(
                        ok=True,
                        success=False,
                        consumed_attempt=True,
                        reason="target_locked",
                        remaining_attempts=remaining,
                        profile=attacker_profile,
                        wid=target_wid,
                    )
                target_wife = _random.choice(alive_unlocked_wives)
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

            # T20: NTR 概率流水线骨架
            # 独立计算每个概率因子，然后组合

            # 1. 基础概率
            prob_base = self._config.ntr_possibility

            # 2. 亲密度护盾（Lv.4+ 降低概率）
            target_intimacy = target_wife.intimacy if target_wife else 0
            prob_shield = 1.0
            if self.has_intimacy_shield(target_intimacy):
                prob_shield = self._config.intimacy_shield_reduction

            # 3. 魅力加成（基于攻击方主老婆亲密度）
            prob_charm = 1.0
            attacker_primary = ownership_store.get_primary(uid, ownerships)
            attacker_intimacy = attacker_primary.intimacy if attacker_primary else 0
            if attacker_intimacy >= 60:
                prob_charm = 1.20
            elif attacker_intimacy >= 40:
                prob_charm = 1.10
            elif attacker_intimacy >= 20:
                prob_charm = 1.05

            # 4. 锁定检查（已前置拒绝，占位）
            prob_lock = 1.0

            # 5. T23: 复仇加成 + 令牌消耗
            revenge_valid = False
            prob_revenge = 1.0
            has_revenge_token = False
            if is_revenge and attacker_profile.last_ntr_by:
                rev_uid = attacker_profile.last_ntr_by.get("uid", "")
                rev_ts = float(attacker_profile.last_ntr_by.get("ts", 0))
                if rev_uid == tid and (now_ts() - rev_ts) < self._config.revenge_window_hours * 3600:
                    revenge_valid = True
                    prob_revenge = self._config.revenge_success_multiplier
                    # T23: 有令牌时额外加成
                    has_revenge_token = attacker_profile.inventory.get("revenge_token", 0) > 0
                    if has_revenge_token:
                        prob_revenge *= (1 + self._config.revenge_token_bonus)

            # 6. 连续同目标成功衰减（防止对同一人连续霸凌）
            prob_streak = 1.0
            if attacker_profile.last_ntr_target_uid == tid and attacker_profile.same_target_ntr_streak > 0:
                prob_streak = 0.7 ** attacker_profile.same_target_ntr_streak

            # 7. 新手保护
            prob_newbie = 1.0
            if self._config.newbie_ntr_protection_days > 0 and target_profile and target_profile.registered_at > 0:
                days_since_reg = (now_ts() - target_profile.registered_at) / 86400
                if days_since_reg < self._config.newbie_ntr_protection_days:
                    prob_newbie = 0.0  # Day1 免疫
                elif days_since_reg < 7:
                    prob_newbie = self._config.newbie_ntr_retain_ratio

            # 8. T34: 打工状态（目标在打工中时，NTR 概率提升）
            prob_work = 1.0
            is_target_working = False
            if target_wife and target_wife.is_working:
                is_target_working = True
                mode_config = self._config.work_modes.get(target_wife.work_mode, {})
                prob_work = mode_config.get("ntr_multiplier", 1.5)

            # 9. T22: 保护符（目标背包有 protection_charm 时，概率 ×0.3）
            prob_protection = 1.0
            has_protection_charm = False
            if target_profile and target_profile.inventory.get("protection_charm", 0) > 0:
                has_protection_charm = True
                prob_protection = 0.3

            # 组合最终概率
            ntr_prob = min(1.0, prob_base * prob_shield * prob_charm * prob_lock *
                          prob_revenge * prob_streak * prob_newbie * prob_work * prob_protection)

            roll = roll_seed if roll_seed is not None else _random.random()
            success = roll < ntr_prob

            meta = self.get_wife_meta(target_wid)
            img = meta.img if meta else ""
            wid = target_wid

            if not success:
                if attacker_profile.last_ntr_target_uid == tid:
                    attacker_profile.same_target_ntr_streak = 0
                # T23: 复仇失败 - 消耗令牌、给安慰币、清空 last_ntr_by
                if revenge_valid:
                    if has_revenge_token:
                        attacker_profile.inventory["revenge_token"] = max(
                            0, attacker_profile.inventory.get("revenge_token", 0) - 1
                        )
                    consolation = self._config.revenge_fail_consolation_coins
                    if consolation > 0:
                        attacker_profile.coins += consolation
                    attacker_profile.last_ntr_by = {}

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
                    final_probability=ntr_prob,
                )

            # T21: 成功 - 转移所有权（攻击者保留旧老婆，只切主老婆）
            stolen_work_reward = 0
            insurance_used = False
            insurance_bonus_coins = 0
            contract_inherited = False
            contract_amount = 0
            partner_broken = False
            stolen_work_wid = ""
            if is_target_working and target_wife:
                from .work_service import WorkService

                work_service = WorkService(self._paths, self._config, self._locks)
                stolen_result = work_service._resolve_stolen_work_inner(
                    gid,
                    tid,
                    today,
                    ownerships,
                    profiles,
                    activity_logs,
                    selected_wid=target_wid,
                    attacker_uid=uid,
                    attacker_nick=nick,
                )
                if stolen_result is not None:
                    stolen_work_reward = stolen_result.reward
                    stolen_work_wid = stolen_result.wid
                    insurance_used = stolen_result.insurance_used
                    insurance_bonus_coins = stolen_result.insurance_bonus_coins
                    contract_inherited = stolen_result.contract_inherited
                    contract_amount = stolen_result.contract_amount
                    partner_broken = stolen_result.partner_broken

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
            if attacker_profile.last_ntr_target_uid == tid:
                attacker_profile.same_target_ntr_streak += 1
            else:
                attacker_profile.last_ntr_target_uid = tid
                attacker_profile.same_target_ntr_streak = 1

            # T24: 作恶值 +1（按自然月懒重置）
            current_month = today[:7]  # YYYY-MM
            if attacker_profile.evil_points_month != current_month:
                attacker_profile.evil_points = 0
                attacker_profile.evil_points_month = current_month
            attacker_profile.evil_points += 1

            # T21: 被牛方处理 - 保留部分亲密度 + 补偿币
            transferred = ownership_store.find_by_wid(wid, ownerships)
            if transferred and target_profile is not None:
                target_profile.total_ntr_lost += 1

                # 计算保留比例（新手保留 75%，普通保留 50%）
                old_intimacy = transferred.intimacy
                is_newbie = (
                    target_profile.registered_at > 0
                    and self._config.newbie_ntr_protection_days > 0
                    and (now_ts() - target_profile.registered_at) / 86400 < 7
                )
                retain_ratio = 0.75 if is_newbie else 0.50
                lost_intimacy = int(old_intimacy * (1 - retain_ratio))

                # T22: 扩展 last_ntr_by 保存 lost_intimacy
                target_profile.last_ntr_by = {
                    "uid": uid,
                    "ts": now_ts(),
                    "wid": wid,
                    "lost_intimacy": lost_intimacy,
                }

                # 保留亲密度
                transferred.intimacy = old_intimacy - lost_intimacy
                transferred.intimacy_updated_date = ""

                # Phase F: NTR 安慰币（替代原 Phase 4 intimacy × 2 补偿）
                # 攻击者零代价（Q-D），被牛方按稀有度+好感度收安慰币（Q-E）
                # 注意：必须使用 target_intimacy（pre-transfer 值），而非
                # transferred.intimacy（transfer() 已将其清零）
                # 复仇路径跳过安慰币（spec §S5.5）
                if not is_revenge:
                    from .ntr_comfort import apply_ntr_comfort_inner
                    target_rarity = meta.rarity if meta else "N"
                    apply_ntr_comfort_inner(
                        target_profile, target_rarity, target_intimacy
                    )

                # T22: 保护符消耗（NTR 结算后消耗 1 个）
                if has_protection_charm:
                    target_profile.inventory["protection_charm"] = max(
                        0, target_profile.inventory.get("protection_charm", 0) - 1
                    )

                # T22: 首次被牛安抚（revenge_token +1，first_ntr_lost_done = True）
                if not target_profile.first_ntr_lost_done:
                    target_profile.first_ntr_lost_done = True
                    target_profile.inventory["revenge_token"] = (
                        target_profile.inventory.get("revenge_token", 0) + 1
                    )

            # T23: 复仇成功后 - 消耗令牌、恢复亲密度、清空 last_ntr_by
            if revenge_valid:
                # 消耗复仇令牌
                if has_revenge_token:
                    attacker_profile.inventory["revenge_token"] = max(
                        0, attacker_profile.inventory.get("revenge_token", 0) - 1
                    )
                # 恢复亲密度（按被牛时损失的比例恢复）
                if transferred:
                    restore_amount = int(lost_intimacy * self._config.revenge_success_intimacy_restore)
                    transferred.intimacy = min(
                        self._config.intimacy_max,
                        transferred.intimacy + restore_amount,
                    )
                # 清空 last_ntr_by（防链式复仇）
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
                final_probability=ntr_prob,
                stolen_work_reward=stolen_work_reward,
                stolen_work_wid=stolen_work_wid,
                insurance_used=insurance_used,
                insurance_bonus_coins=insurance_bonus_coins,
                contract_inherited=contract_inherited,
                contract_amount=contract_amount,
                partner_broken=partner_broken,
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
        # 或在命令层调用 ``OwnershipService.try_ntr`` 后用
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

    # ---------- 亲密度 ----------

    async def pet_wife(
        self, gid: str, uid: str, nick: str, today: str, selected_wid: str | None = None
    ) -> IntimacyResult:
        """摸头：消耗币增加亲密度

        要求：有主老婆、币余额 >= intimacy_pet_coin_cost、亲密度未满。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            target = self._resolve_owned_target(gid, uid, ownerships, selected_wid)
            if target is None:
                reason = "wife_not_found" if selected_wid else "no_wife"
                return IntimacyResult(ok=False, reason=reason)

            # 锁定中的老婆不能摸头
            from .marry_service import MarryService
            if MarryService.is_locked(target):
                return IntimacyResult(ok=False, reason="locked", intimacy=target.intimacy, wid=target.wid)

            # Phase 6: 死亡老婆不能摸头
            if target.is_dead:
                return IntimacyResult(
                    ok=False, reason="wife_dead",
                    intimacy=target.intimacy, wid=target.wid,
                )

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,

                coins=self._config.initial_coins,
            )

            if profile.coins < self._config.intimacy_pet_coin_cost:
                return IntimacyResult(
                    ok=False, reason="not_enough_coins",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            if target.intimacy >= self._config.intimacy_max:
                return IntimacyResult(
                    ok=False, reason="intimacy_maxed",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            old_intimacy = target.intimacy
            profile.coins -= self._config.intimacy_pet_coin_cost
            target.intimacy = min(
                self._config.intimacy_max,
                target.intimacy + self._config.intimacy_pet_gain,
            )
            target.intimacy_updated_date = today

            # T12: 检测跨级升级并发放奖励
            levelup_info = self._check_intimacy_levelup(
                old_intimacy, target.intimacy, profile
            )

            # T12: 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.INTIMACY, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return IntimacyResult(
                ok=True, intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
            )

    async def gift_wife(
        self, gid: str, uid: str, nick: str, today: str, selected_wid: str | None = None
    ) -> IntimacyResult:
        """送礼：高消耗高加成亲密度

        要求：有主老婆、币余额 >= intimacy_gift_coin_cost、亲密度未满。
        """
        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            target = self._resolve_owned_target(gid, uid, ownerships, selected_wid)
            if target is None:
                reason = "wife_not_found" if selected_wid else "no_wife"
                return IntimacyResult(ok=False, reason=reason)

            # 锁定中的老婆不能送礼
            from .marry_service import MarryService
            if MarryService.is_locked(target):
                return IntimacyResult(ok=False, reason="locked", intimacy=target.intimacy, wid=target.wid)

            # Phase 6: 死亡老婆不能送礼
            if target.is_dead:
                return IntimacyResult(
                    ok=False, reason="wife_dead",
                    intimacy=target.intimacy, wid=target.wid,
                )

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,

                coins=self._config.initial_coins,
            )

            if profile.coins < self._config.intimacy_gift_coin_cost:
                return IntimacyResult(
                    ok=False, reason="not_enough_coins",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            if target.intimacy >= self._config.intimacy_max:
                return IntimacyResult(
                    ok=False, reason="intimacy_maxed",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            old_intimacy = target.intimacy
            profile.coins -= self._config.intimacy_gift_coin_cost
            target.intimacy = min(
                self._config.intimacy_max,
                target.intimacy + self._config.intimacy_gift_gain,
            )
            target.intimacy_updated_date = today

            # T12: 检测跨级升级并发放奖励
            levelup_info = self._check_intimacy_levelup(
                old_intimacy, target.intimacy, profile
            )

            # T12: 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.INTIMACY, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return IntimacyResult(
                ok=True, intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
            )

    async def chat_wife(
        self, gid: str, uid: str, nick: str, today: str, selected_wid: str | None = None
    ) -> IntimacyResult:
        """对话：2h 冷却，+1 亲密度，+5 币

        要求：有主老婆、冷却已过。
        """
        # T13: 冷却检查
        if self._cooldown and self._config.chat_cooldown > 0:
            if not self._cooldown.check(
                gid, uid, CooldownAction.CHAT, self._config.chat_cooldown
            ):
                return IntimacyResult(ok=False, reason="cooldown")

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            target = self._resolve_owned_target(gid, uid, ownerships, selected_wid)
            if target is None:
                reason = "wife_not_found" if selected_wid else "no_wife"
                return IntimacyResult(ok=False, reason=reason)

            # 锁定中的老婆不能对话
            from .marry_service import MarryService
            if MarryService.is_locked(target):
                return IntimacyResult(ok=False, reason="locked", intimacy=target.intimacy, wid=target.wid)

            # Phase 6: 死亡老婆不能对话
            if target.is_dead:
                return IntimacyResult(
                    ok=False, reason="wife_dead",
                    intimacy=target.intimacy, wid=target.wid,
                )

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                coins=self._config.initial_coins,
            )

            if target.intimacy >= self._config.intimacy_max:
                return IntimacyResult(
                    ok=False, reason="intimacy_maxed",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            old_intimacy = target.intimacy
            target.intimacy = min(
                self._config.intimacy_max,
                target.intimacy + self._config.chat_intimacy_gain,
            )
            target.intimacy_updated_date = today
            profile.coins += self._config.chat_coin_reward

            # 检测跨级升级
            self._check_intimacy_levelup(old_intimacy, target.intimacy, profile)

            # 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.INTIMACY, 1)
            ActivityStore.log(activity_logs, uid, today, Action.CHAT, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            # 更新冷却
            if self._cooldown and self._config.chat_cooldown > 0:
                self._cooldown.update(gid, uid, CooldownAction.CHAT)

            return IntimacyResult(
                ok=True, intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
            )

    async def date_wife(
        self, gid: str, uid: str, nick: str, today: str, selected_wid: str | None = None
    ) -> IntimacyResult:
        """约会：12h 冷却，花 10 币，+8 亲密度

        要求：有主老婆、冷却已过、余额足够。
        """
        # T13: 冷却检查
        if self._cooldown and self._config.date_cooldown > 0:
            if not self._cooldown.check(
                gid, uid, CooldownAction.DATE, self._config.date_cooldown
            ):
                return IntimacyResult(ok=False, reason="cooldown")

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            profile_store = self._profile_store(gid)
            activity_store = self._activity_store(gid)

            ownerships = ownership_store.load_all()
            profiles = profile_store.load_all()

            target = self._resolve_owned_target(gid, uid, ownerships, selected_wid)
            if target is None:
                reason = "wife_not_found" if selected_wid else "no_wife"
                return IntimacyResult(ok=False, reason=reason)

            # 锁定中的老婆不能约会
            from .marry_service import MarryService
            if MarryService.is_locked(target):
                return IntimacyResult(ok=False, reason="locked", intimacy=target.intimacy, wid=target.wid)

            # Phase 6: 死亡老婆不能约会
            if target.is_dead:
                return IntimacyResult(
                    ok=False, reason="wife_dead",
                    intimacy=target.intimacy, wid=target.wid,
                )

            profile = ProfileStore.get_or_create(
                profiles, uid, nick,
                coins=self._config.initial_coins,
            )

            if profile.coins < self._config.date_coin_cost:
                return IntimacyResult(
                    ok=False, reason="not_enough_coins",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            if target.intimacy >= self._config.intimacy_max:
                return IntimacyResult(
                    ok=False, reason="intimacy_maxed",
                    intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
                )

            old_intimacy = target.intimacy
            profile.coins -= self._config.date_coin_cost
            target.intimacy = min(
                self._config.intimacy_max,
                target.intimacy + self._config.date_intimacy_gain,
            )
            target.intimacy_updated_date = today

            # 检测跨级升级
            self._check_intimacy_levelup(old_intimacy, target.intimacy, profile)

            # 写行为日志
            activity_logs = activity_store.load_all()
            ActivityStore.log(activity_logs, uid, today, Action.INTIMACY, 1)
            ActivityStore.log(activity_logs, uid, today, Action.DATE, 1)
            activity_store.save_all(activity_logs)

            ownership_store.save_all(ownerships)
            profile_store.save_all(profiles)

            # 更新冷却
            if self._cooldown and self._config.date_cooldown > 0:
                self._cooldown.update(gid, uid, CooldownAction.DATE)

            return IntimacyResult(
                ok=True, intimacy=target.intimacy, coin_balance=profile.coins, wid=target.wid,
            )

    async def daily_intimacy_increment_for_group(self, gid: str, today: str) -> int:
        """零点循环：所有持有老婆 +intimacy_per_day（幂等，每日只加一次）

        返回更新的 ownership 数量。锁定中的老婆不增长。
        """
        from .marry_service import MarryService

        async with self._locks.acquire(gid):
            ownership_store = self._ownership_store(gid)
            ownerships = ownership_store.load_all()

            updated = 0
            for o in ownerships:
                if o.intimacy_updated_date == today:
                    continue
                # 锁定中的老婆不增长亲密度
                if MarryService.is_locked(o):
                    o.intimacy_updated_date = today
                    continue
                if self._config.intimacy_decay > 0 and o.intimacy >= 60:
                    new_intimacy = max(50, o.intimacy - self._config.intimacy_decay)
                    if new_intimacy != o.intimacy:
                        o.intimacy = new_intimacy
                        updated += 1
                    o.intimacy_updated_date = today
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
        """亲密度 → 等级（1~5），5 档分段（保留旧接口兼容）"""
        return OwnershipService.get_intimacy_level_no(intimacy)

    @staticmethod
    def intimacy_level_emoji(intimacy: int) -> str:
        """亲密度等级 emoji 展示（如 ❤️ Lv.3）"""
        lv = OwnershipService.get_intimacy_level_no(intimacy)
        if lv <= 0:
            return ""
        return f"❤️ Lv.{lv}"

    @staticmethod
    def get_intimacy_level_no(intimacy: int) -> int:
        """亲密度 → 等级编号（1~5）

        等级规则：
        - 0-19  → 1
        - 20-39 → 2
        - 40-59 → 3
        - 60-79 → 4
        - 80-100 → 5
        """
        if intimacy < 0:
            intimacy = 0
        if intimacy >= 100:
            return 5
        return intimacy // 20 + 1

    @staticmethod
    def get_intimacy_level_name(intimacy: int) -> str:
        """亲密度 → 等级名称"""
        lv = OwnershipService.get_intimacy_level_no(intimacy)
        names = {1: "相识", 2: "熟悉", 3: "亲密", 4: "挚爱", 5: "灵魂伴侣"}
        return names.get(lv, "相识")

    @staticmethod
    def get_intimacy_bonus_ratio(intimacy: int) -> float:
        """亲密度 → 战斗力加成倍率（用于 PK 公式）

        返回 1.0 ~ 1.2 的加成系数
        """
        lv = OwnershipService.get_intimacy_level_no(intimacy)
        # 每级 +5% 加成，最高 +20%
        return 1.0 + (lv - 1) * 0.05

    @staticmethod
    def has_intimacy_shield(intimacy: int) -> bool:
        """亲密度是否有护盾（NTR 概率减免）

        Lv.4 及以上（亲密度 ≥ 60）自动获得护盾
        """
        return OwnershipService.get_intimacy_level_no(intimacy) >= 4

    def _check_intimacy_levelup(
        self,
        old_intimacy: int,
        new_intimacy: int,
        profile: "UserProfile",
    ) -> Optional[Dict[str, Any]]:
        """检测亲密度是否跨级，如果是则发放升级奖励

        返回奖励信息 dict 或 None（无升级）
        """
        old_level = self.get_intimacy_level_no(old_intimacy)
        new_level = self.get_intimacy_level_no(new_intimacy)
        if new_level <= old_level:
            return None

        # 跨级了，发放奖励（只发本次跨越的最高级）
        rewards = self._config.intimacy_levelup_rewards.get(str(new_level), {})
        coins = rewards.get("coins", 0)
        item = rewards.get("item", "")

        if coins > 0:
            profile.coins += coins
        if item:
            profile.inventory[item] = profile.inventory.get(item, 0) + 1

        return {
            "old_level": old_level,
            "new_level": new_level,
            "coins": coins,
            "item": item,
        }

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
