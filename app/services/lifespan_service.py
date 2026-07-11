"""寿命系统核心服务。

设计要点
--------

* **死亡概率**：每次有寿命消耗的事件后做一次检查。

  公式（用户原话"寿命值越低，猝死概率成指数级增长"）：

  .. code-block:: python

      ratio = 1.0 - lifespan / lifespan_max
      p_death = death_probability_base * (ratio ** 2)

  lifespan=0 时直接 ``is_dead=True``（不靠概率；零寿命必死亡）。
  lifespan=max 时 p=0（满血不会死）。

  默认 base=0.50：lifespan=20 → p≈0.32；lifespan=50 → p≈0.125；lifespan=80 → p≈0.02。

* **修复价格**：基础价 × 紧急度倍率。

  .. code-block:: python

      urgency = 2.0 - lifespan / lifespan_max      # 1.0~2.0
      price = revive_base_cost[rarity] * urgency

  lifespan=max 时返回 0（满血无需修复）；lifespan=0（死了）→ 2x 基础价。

* **死亡状态机**：死亡后老婆**仍在** ownership.json 里（不删除），
  业务侧用 ``is_dead`` 字段拦截所有"使用"型操作（打工/战斗/亲密度互动/被牛），
  但允许"离开"型操作（离婚）+ "恢复"型操作（老婆 休息 复活）。

* **跨插件入口**：见 :meth:`WifeInterop.apply_lifespan_damage_from_impact`。
  impact 插件调用方按"丁丁尺寸"算好绝对 delta 传进来，我们只扣。

* **并发安全**：所有写操作都走群锁 (:class:`GroupLocks`)；上层
  service（work/pk/ownership）在锁内调用本服务即可。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..models.enums import Action
from ..models.ownership import Ownership
from ..models.profile import UserProfile
from ..storage.locks import GroupLocks
from ..storage.paths import Paths
from ..storage.stores import (
    ActivityStore,
    OwnershipStore,
    ProfileStore,
    WivesMasterStore,
)
from .plugin_config import PluginConfig

__all__ = [
    "LifespanService",
    "ReviveResult",
    "DamageResult",
    "calc_death_probability",
    "calc_revive_cost",
    "calc_revive_urgency",
    "format_lifespan_bar",
    "DEATH_CAUSE_WORK",
    "DEATH_CAUSE_PK",
    "DEATH_CAUSE_IMPACT",
    "DEATH_CAUSE_MANUAL",
]

# 死亡原因枚举常量（写入 ownership.death_cause）
DEATH_CAUSE_WORK = "work_exhaustion"
DEATH_CAUSE_PK = "pk_exhaustion"
DEATH_CAUSE_IMPACT = "impact"
DEATH_CAUSE_MANUAL = "manual"

logger = logging.getLogger("astrbot_plugin_animewifex.lifespan")


# ==================== 纯函数公式 ====================


def calc_death_probability(
    lifespan: int,
    lifespan_max: int,
    base: float,
) -> float:
    """计算当前寿命下的猝死概率。

    公式：``p = base * (1 - lifespan/max)^2``

    Args:
        lifespan: 当前寿命
        lifespan_max: 上限
        base: 基础值（配置项 death_probability_base）

    Returns:
        0.0~1.0 之间的概率值。lifespan>=max 时返回 0。
    """
    if lifespan_max <= 0:
        return 0.0
    if lifespan >= lifespan_max:
        return 0.0
    if lifespan <= 0:
        return 1.0  # 零寿命 = 必死亡（调用方应直接标 is_dead，不再走概率）
    ratio = 1.0 - (lifespan / lifespan_max)
    p = base * (ratio * ratio)
    if p < 0.0:
        return 0.0
    if p > 1.0:
        return 1.0
    return p


def calc_revive_urgency(
    current_lifespan: int,
    lifespan_max: int,
) -> float:
    """修复价格紧急度倍率 = ``2.0 - current/max``，范围 [1.0, 2.0]。

    lifespan=max → 1.0（满血无压力，理论上不会被调用因为不需要修复）
    lifespan=0   → 2.0（最紧急）
    """
    if lifespan_max <= 0:
        return 1.0
    if current_lifespan >= lifespan_max:
        return 1.0
    if current_lifespan <= 0:
        return 2.0
    ratio = current_lifespan / lifespan_max
    urgency = 2.0 - ratio
    if urgency < 1.0:
        return 1.0
    if urgency > 2.0:
        return 2.0
    return urgency


def calc_revive_cost(
    rarity: str,
    current_lifespan: int,
    lifespan_max: int,
    base_cost_map: Dict[str, int],
) -> int:
    """计算修复/复活价格。

    满血返回 0（无需修复）；否则 = base × (2 - current/max)。

    Args:
        rarity: 稀有度 N/R/SR/SSR
        current_lifespan: 当前寿命
        lifespan_max: 上限
        base_cost_map: 稀有度→基础价 映射（来自 config.revive_base_cost）

    Returns:
        修复价格（int），最低 0。
    """
    if current_lifespan >= lifespan_max:
        return 0
    base = int(base_cost_map.get(rarity, 0))
    if base <= 0:
        return 0
    urgency = calc_revive_urgency(current_lifespan, lifespan_max)
    return int(base * urgency)


def format_lifespan_bar(
    current: int,
    max_value: int,
    width: int = 10,
    is_dead: bool = False,
) -> str:
    """生成寿命条的可读文本。

    例：``❤️ 60/100 ██████░░░░`` 或 ``☠️ 已离世 0/100 ░░░░░░░░░░``
    """
    if is_dead:
        return f"☠️ 已离世 {current}/{max_value} " + ("░" * width)
    if max_value <= 0:
        return f"❤️ {current}/?"
    filled = max(0, min(width, int(round(current / max_value * width))))
    bar = "█" * filled + "░" * (width - filled)
    return f"❤️ {current}/{max_value} {bar}"


# ==================== 结果 dataclass ====================


@dataclass
class DamageResult:
    """单次寿命扣减 + 死亡检查结果"""

    ok: bool = False
    new_lifespan: int = 0
    was_alive: bool = True         # 调用前是否活着
    death_occurred: bool = False   # 这次扣减是否导致死亡
    death_cause: str = ""          # 死亡原因
    damage_applied: int = 0        # 实际扣了多少（可能小于请求的 delta）
    rolled_probability: float = 0.0  # 实际 roll 的死亡概率（0 表示未触发）
    reason: str = ""               # 失败原因：wife_not_found / already_dead / disabled / ...
    wid: str = ""


@dataclass
class ReviveResult:
    """单次复活/修复结果"""

    ok: bool = False
    reason: str = ""               # 失败原因：wife_not_found / already_full / not_enough_coins / ...
    wid: str = ""
    new_lifespan: int = 0          # 修复后的寿命（应等于 lifespan_max）
    cost: int = 0                  # 实际花费
    coin_balance: int = 0          # 修复后余额
    was_dead: bool = False         # 调用前是否已死（区分复活 vs 修复）


# ==================== 服务 ====================


class LifespanService:
    """寿命系统服务。

    设计为**无内部锁**（lock 由调用方负责），与 ownership_service 风格一致：
    所有方法假设调用方已持 ``GroupLocks`` 临界区。

    提供三个公开方法：
    - :meth:`apply_damage` — 扣寿命 + 死亡检查（供 work/pk/impact 调用）
    - :meth:`apply_revive` — 老婆币修复/复活（供 commands/rest.py 调用）
    - :meth:`query_lifespan` — 只读查询当前寿命/死亡状态
    """

    def __init__(
        self,
        paths: Paths,
        config: PluginConfig,
        locks: GroupLocks,
    ):
        self._paths = paths
        self._config = config
        self._locks = locks

    # ---------- Store 工厂（与 ownership_service 风格一致） ----------

    def _ownership_store(self, gid: str) -> OwnershipStore:
        return OwnershipStore(self._paths, gid)

    def _profile_store(self, gid: str) -> ProfileStore:
        return ProfileStore(self._paths, gid)

    def _activity_store(self, gid: str) -> ActivityStore:
        return ActivityStore(self._paths, gid)

    def _wives_master(self) -> WivesMasterStore:
        return WivesMasterStore(self._paths)

    @staticmethod
    def _today_str() -> str:
        """本地日期字符串 YYYY-MM-DD。

        lifespan_service 不持有 tz，因此用本地时区近似。
        调用方传入 ``today`` 时优先用入参（来自 service 锁外的真实日期上下文）。
        """
        return datetime.now().strftime("%Y-%m-%d")

    # ---------- 只读 ----------

    def query_lifespan(
        self,
        gid: str,
        wid: str,
    ) -> Dict[str, Any]:
        """查询某老婆的当前寿命状态。

        返回::
            {
                "ok": bool,
                "wid": str,
                "current": int,
                "max": int,
                "is_dead": bool,
                "death_date": str,
                "death_cause": str,
            }
        """
        ownerships = self._ownership_store(gid).load_all()
        target = next((o for o in ownerships if o.wid == wid), None)
        if target is None:
            return {"ok": False}
        return {
            "ok": True,
            "wid": wid,
            "current": target.lifespan,
            "max": self._config.lifespan_max,
            "is_dead": target.is_dead,
            "death_date": target.death_date,
            "death_cause": target.death_cause,
        }

    def is_wife_dead(self, gid: str, wid: str) -> bool:
        """快速判断某老婆是否死亡（供其他服务用）。"""
        ownerships = self._ownership_store(gid).load_all()
        target = next((o for o in ownerships if o.wid == wid), None)
        if target is None:
            return False
        return target.is_dead

    # ---------- 扣寿命 + 死亡检查 ----------

    def apply_damage(
        self,
        gid: str,
        wid: str,
        delta: int,
        cause: str = DEATH_CAUSE_MANUAL,
        today: str = "",
        roll_seed: "Optional[float]" = None,
    ) -> DamageResult:
        """扣减寿命 + 死亡检查（load → mutate → save 全包）。

        调用方无需持锁；本方法本身会 load/save。
        适合**没有**内存中 ownerships 列表的调用方（如 impact interop）。

        如果调用方**已经**持有 ``ownerships`` 内存列表（如 work_service / pk_service），
        用 :meth:`apply_damage_inplace` 避免 load/save 覆盖内存修改。
        """
        if not self._config.lifespan_enabled:
            return DamageResult(
                ok=False,
                reason="disabled",
                wid=wid,
            )

        if delta <= 0:
            return DamageResult(
                ok=False,
                reason="no_damage",
                wid=wid,
            )

        ownership_store = self._ownership_store(gid)
        ownerships = ownership_store.load_all()
        target = next((o for o in ownerships if o.wid == wid), None)
        if target is None:
            return DamageResult(ok=False, reason="wife_not_found", wid=wid)

        result = self.apply_damage_inplace(target, delta, cause, today, roll_seed)
        if not result.ok:
            return result

        # 落盘
        ownership_store.save_all(ownerships)

        # 死亡事件统计
        if result.death_occurred:
            self._record_death_event(gid, target, today)

        return result

    def apply_damage_inplace(
        self,
        target: "Ownership",
        delta: int,
        cause: str = DEATH_CAUSE_MANUAL,
        today: str = "",
        roll_seed: "Optional[float]" = None,
    ) -> DamageResult:
        """扣减寿命 + 死亡检查（in-place 修改 target，不 load/save）。

        **调用方必须**：
        1. 已持群锁
        2. 自己负责 save ownerships（避免 load/save 覆盖 in-memory 修改）

        Args:
            target: Ownership 对象（来自调用方持有的 ownerships 列表）
            delta: 寿命减少量（正数）
            cause: 死亡原因
            today: YYYY-MM-DD
            roll_seed: 测试用固定概率

        Returns:
            :class:`DamageResult`
        """
        if not self._config.lifespan_enabled:
            return DamageResult(ok=False, reason="disabled", wid=target.wid)

        if delta <= 0:
            return DamageResult(ok=False, reason="no_damage", wid=target.wid)

        if target.is_dead:
            return DamageResult(
                ok=False, reason="already_dead", wid=target.wid, was_alive=False,
            )

        # 1. 扣寿命
        old_lifespan = target.lifespan
        actual_delta = min(delta, old_lifespan)
        new_lifespan = max(0, old_lifespan - actual_delta)
        target.lifespan = new_lifespan
        target.lifespan_updated_date = today or self._today_str()

        # 2. 死亡判定
        death_occurred = False
        rolled_p = 0.0
        if new_lifespan <= 0:
            death_occurred = True
            rolled_p = 1.0
        else:
            rolled_p = calc_death_probability(
                new_lifespan,
                self._config.lifespan_max,
                self._config.death_probability_base,
            )
            if rolled_p > 0:
                roll = roll_seed if roll_seed is not None else random.random()
                if roll < rolled_p:
                    death_occurred = True

        # 3. 死亡则标 is_dead
        if death_occurred:
            target.is_dead = True
            target.lifespan = 0
            target.death_date = today or self._today_str()
            target.death_cause = cause

        return DamageResult(
            ok=True,
            new_lifespan=new_lifespan,
            was_alive=True,
            death_occurred=death_occurred,
            death_cause=cause if death_occurred else "",
            damage_applied=actual_delta,
            rolled_probability=rolled_p,
            wid=target.wid,
        )

    def _record_death_event(
        self,
        gid: str,
        target: "Ownership",
        today: str,
    ) -> None:
        """死亡事件统计（profile 计数 + activity 日志）"""
        try:
            profile_store = self._profile_store(gid)
            profiles = profile_store.load_all()
            profile = profiles.get(target.uid)
            if profile is not None:
                profile.total_wife_deaths += 1
                profile_store.save_all(profiles)

            activity_store = self._activity_store(gid)
            activity_logs = activity_store.load_all()
            ActivityStore.log(
                activity_logs, target.uid, today or self._today_str(),
                Action.WIFE_DEATH, 1,
            )
            activity_store.save_all(activity_logs)
        except Exception:
            # 统计失败不阻塞主流程
            logger.exception("lifespan _record_death_event: 统计失败")

    def apply_damage_many(
        self,
        gid: str,
        wids: List[str],
        delta: int,
        cause: str = DEATH_CAUSE_MANUAL,
        today: str = "",
        roll_seed: "Optional[float]" = None,
    ) -> List[DamageResult]:
        """批量扣减寿命（PK 战斗后可能多老婆同时扣）。

        共享一次 load/save，每个 wid 独立 roll。
        """
        results: List[DamageResult] = []
        for w in wids:
            results.append(self.apply_damage(
                gid, w, delta, cause, today, roll_seed,
            ))
        return results

    # ---------- 修复 / 复活 ----------

    def apply_revive(
        self,
        gid: str,
        uid: str,
        nick: str,
        wid: str,
        target_wid: Optional[str] = None,
    ) -> ReviveResult:
        """花钱修复/复活指定老婆（满血）。

        必须在调用方已持 ``GroupLocks(gid)`` 锁的临界区内调用。

        Args:
            gid: 群 ID
            uid: 操作者 uid
            nick: 操作者昵称
            wid: 操作者要修的 wid（通过编号解析后传入）
            target_wid: 可选，要修的目标 wid（与 wid 二选一；为 None 时用 wid）

        Returns:
            :class:`ReviveResult` — 包含 cost / new_lifespan / coin_balance 等。
        """
        if not self._config.lifespan_enabled:
            return ReviveResult(ok=False, reason="disabled", wid=wid)

        actual_wid = target_wid or wid

        ownership_store = self._ownership_store(gid)
        profile_store = self._profile_store(gid)
        activity_store = self._activity_store(gid)
        wives_master = self._wives_master()

        ownerships = ownership_store.load_all()
        profiles = profile_store.load_all()

        target = next((o for o in ownerships if o.wid == actual_wid), None)
        if target is None or target.uid != uid:
            return ReviveResult(ok=False, reason="wife_not_found", wid=actual_wid)

        if target.lifespan >= self._config.lifespan_max and not target.is_dead:
            return ReviveResult(
                ok=False,
                reason="already_full",
                wid=actual_wid,
                new_lifespan=target.lifespan,
            )

        # 计算价格
        meta = wives_master.load_all().get(actual_wid)
        rarity = meta.rarity if meta else "N"
        cost = calc_revive_cost(
            rarity,
            target.lifespan,
            self._config.lifespan_max,
            self._config.revive_base_cost,
        )
        if cost <= 0:
            cost = 0  # 满血已拦截，理论上不会到这里

        # 扣币
        profile = ProfileStore.get_or_create(
            profiles, uid, nick, self._config.initial_coins,
        )
        if profile.coins < cost:
            return ReviveResult(
                ok=False,
                reason="not_enough_coins",
                wid=actual_wid,
                new_lifespan=target.lifespan,
                cost=cost,
                coin_balance=profile.coins,
                was_dead=target.is_dead,
            )

        was_dead = target.is_dead
        profile.coins -= cost
        profile.total_lifespan_restored += 1
        profile.total_coins_spent_on_revive += cost

        # 满血复活
        target.lifespan = self._config.lifespan_max
        target.lifespan_updated_date = self._today_str()
        if target.is_dead:
            target.is_dead = False
            target.death_date = ""
            target.death_cause = ""

        # 落盘
        ownership_store.save_all(ownerships)
        profile_store.save_all(profiles)

        # 行为日志
        try:
            activity_logs = activity_store.load_all()
            ActivityStore.log(
                activity_logs, uid, self._today_str(),
                Action.LIFESPAN_RESTORE, 1,
            )
            activity_store.save_all(activity_logs)
        except Exception:
            logger.exception("lifespan apply_revive: 行为日志写入失败")

        return ReviveResult(
            ok=True,
            wid=actual_wid,
            new_lifespan=target.lifespan,
            cost=cost,
            coin_balance=profile.coins,
            was_dead=was_dead,
        )

    # ---------- 价格查询（命令层展示用，不走锁） ----------

    def quote_revive_cost(
        self,
        gid: str,
        wid: str,
    ) -> Dict[str, Any]:
        """只读查询修复价格（不写盘，不持锁）。

        用于 ``老婆 休息 [编号]`` 列价格预览。
        """
        if not self._config.lifespan_enabled:
            return {"ok": False, "reason": "disabled"}
        ownerships = self._ownership_store(gid).load_all()
        target = next((o for o in ownerships if o.wid == wid), None)
        if target is None:
            return {"ok": False, "reason": "wife_not_found"}
        meta = self._wives_master().load_all().get(wid)
        rarity = meta.rarity if meta else "N"
        cost = calc_revive_cost(
            rarity,
            target.lifespan,
            self._config.lifespan_max,
            self._config.revive_base_cost,
        )
        return {
            "ok": True,
            "wid": wid,
            "current": target.lifespan,
            "max": self._config.lifespan_max,
            "is_dead": target.is_dead,
            "rarity": rarity,
            "cost": cost,
            "urgency": calc_revive_urgency(target.lifespan, self._config.lifespan_max),
        }
