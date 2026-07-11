"""跨插件 facade：impact 日老婆 联动。所有写走 GroupLocks；只读不走锁。"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from .services.lifespan_service import DEATH_CAUSE_IMPACT
from .services.marry_service import MarryService
from .services.ownership_service import OwnershipService
from .storage.locks import GroupLocks
from .storage.stores import OwnershipStore, ProfileStore, WivesMasterStore
from .utils.time import now_ts

_facade: Optional["WifeInterop"] = None


def set_facade(facade: Optional["WifeInterop"]) -> None:
    global _facade
    _facade = facade


def get_wife_interop() -> "WifeInterop":
    if _facade is None:
        raise RuntimeError("animewifexI WifeInterop facade not initialized")
    return _facade


class WifeInterop:
    def __init__(self, ownership_service: OwnershipService, locks: GroupLocks, config, paths,
                 lifespan_service=None):
        self._os = ownership_service
        self._locks = locks
        self._config = config
        self._paths = paths
        # Phase 6: 寿命系统（可选；不注入时 lifespan 相关方法全部短路）
        self._lifespan = lifespan_service

    async def peek_wife(
        self, gid: str, owner_uid: str, index: Optional[int] = None,
    ) -> Dict[str, Any]:
        os_store = OwnershipStore(self._paths, gid)
        ownerships = os_store.load_all()
        mine = os_store.list_by_user(owner_uid, ownerships)
        if not mine:
            return {}
        if index is None:
            picked = os_store.get_primary(owner_uid, ownerships)
            if picked is None:
                picked = mine[0]  # no primary → fallback to earliest
        else:
            idx = index - 1
            if not (0 <= idx < len(mine)):
                return {}
            picked = mine[idx]
        meta = WivesMasterStore(self._paths).load_all().get(picked.wid)
        intimacy = picked.intimacy or 0
        level = OwnershipService.get_intimacy_level_no(intimacy)
        return {
            "wid": picked.wid,
            "name": meta.chara if meta else "",
            "source": meta.source if meta else "",
            "img": meta.img if meta else "",
            "intimacy": intimacy,
            "level": level,
            "level_name": OwnershipService.get_intimacy_level_name(intimacy),
            "is_primary": bool(picked.is_primary),
        }

    async def compute_ntr_resistance(
        self, gid: str, wid: str,
    ) -> Dict[str, Any]:
        """计算「日别人老婆」时老婆端的抗性乘积（animewifexI 单一真相源）。

        返回 {resistance, locked, shielded, working, newbie_protected,
        has_charm, target_owner_uid, intimacy, level}。
        老婆不存在时返回空 dict。
        """
        os_store = OwnershipStore(self._paths, gid)
        ownerships = os_store.load_all()
        wife = os_store.find_by_wid(wid, ownerships)
        if wife is None:
            return {}

        intimacy = wife.intimacy or 0
        level = OwnershipService.get_intimacy_level_no(intimacy)

        # 1. 锁定（前置拒绝，不参与乘积）
        locked = MarryService.is_locked(wife)

        # 2. 亲密度护盾
        shielded = OwnershipService.has_intimacy_shield(intimacy)
        resistance = 1.0
        if shielded:
            resistance *= self._config.intimacy_shield_reduction

        # 3. 新手保护
        newbie_protected = False
        profiles = ProfileStore(self._paths, gid).load_all()
        target_profile = profiles.get(wife.uid)
        if self._config.newbie_ntr_protection_days > 0 and target_profile and target_profile.registered_at > 0:
            days_since_reg = (now_ts() - target_profile.registered_at) / 86400
            if days_since_reg < self._config.newbie_ntr_protection_days:
                newbie_protected = True
                resistance *= 0.0
            elif days_since_reg < 7:
                newbie_protected = True
                resistance *= self._config.newbie_ntr_retain_ratio

        # 4. 打工状态
        working = wife.is_working
        if working:
            mode_config = self._config.work_modes.get(wife.work_mode, {})
            resistance *= mode_config.get("ntr_multiplier", 1.5)

        # 5. 保护符
        has_charm = bool(
            target_profile and target_profile.inventory.get("protection_charm", 0) > 0
        )
        if has_charm:
            resistance *= 0.3

        return {
            "resistance": resistance,
            "locked": locked,
            "shielded": shielded,
            "working": working,
            "newbie_protected": newbie_protected,
            "has_charm": has_charm,
            "target_owner_uid": wife.uid,
            "intimacy": intimacy,
            "level": level,
        }

    async def record_sex_act(
        self, gid: str, wid: str, actor_uid: str, is_ntr: bool, intimacy_delta: int,
    ) -> Dict[str, Any]:
        """走 GroupLocks 安全改亲密度（**不转移所有权**，区别于 try_ntr）。

        复刻完整 pet_wife 序列：load → guard → mutate → levelup check → save。
        """
        today = date.today().isoformat()

        async with self._locks.acquire(gid):
            os_store = OwnershipStore(self._paths, gid)
            profile_store = ProfileStore(self._paths, gid)

            ownerships = os_store.load_all()
            profiles = profile_store.load_all()

            target = os_store.find_by_wid(wid, ownerships)
            if target is None:
                return {"ok": False}

            if MarryService.is_locked(target):
                return {"ok": False}

            profile = ProfileStore.get_or_create(profiles, target.uid, "")

            old_intimacy = target.intimacy
            new_intimacy = min(self._config.intimacy_max, old_intimacy + intimacy_delta)
            target.intimacy = new_intimacy
            target.intimacy_updated_date = today

            self._os._check_intimacy_levelup(old_intimacy, new_intimacy, profile)

            os_store.save_all(ownerships)
            profile_store.save_all(profiles)

            return {
                "ok": True,
                "new_intimacy": new_intimacy,
                "level": OwnershipService.get_intimacy_level_no(new_intimacy),
                "level_name": OwnershipService.get_intimacy_level_name(new_intimacy),
            }

    async def apply_lifespan_damage_from_impact(
        self,
        gid: "str | int",
        wid: str,
        actor_uid: str,
        delta: int,
    ) -> Dict[str, Any]:
        """Phase 6 / 跨插件：impact 插件调用此方法扣减目标老婆寿命。

        设计：
        - 必须在 impact 那边算好 delta 后传进来（不要让 animewifexI 知道"丁丁尺寸"
          这种业务概念）。建议 impact 端规则：sender_dj < 30 → delta=0；否则
          delta = clamp(int((sender_dj - 30) * 0.5), 0, 20)。
        - **自己 ri 自己的老婆 → impact 端不应调用本方法**（这里也再校验一次：
          actor_uid == 老婆持有者时直接返回 ok=False）。
        - **寿命系统未启用 / lifespan_service 未注入 → 返回 ok=False**。

        Args:
            gid: 群 ID（int/str 都接受；内部转 str）
            wid: 目标老婆 wid
            actor_uid: 发起人 uid（用于"不能 ri 自己的老婆"二次校验）
            delta: 寿命减少量（正数；<=0 时直接返回 ok=True 表示"无变化"）

        Returns::
            {
                "ok": bool,
                "wid": str,
                "wife_owner_uid": str,    # 老婆当前持有者（便于 impact 写提示）
                "new_lifespan": int,      # 扣后寿命
                "death_occurred": bool,   # 这次扣减是否导致死亡
                "skipped": str,           # 跳过原因（self_ri / no_owner / disabled / not_alive / no_damage）
            }
        """
        # 类型规整：impact 那边 gid 是 int
        gid_str = str(gid)

        if not self._lifespan:
            return {"ok": False, "skipped": "no_lifespan_service", "wid": wid}

        if not getattr(self._config, "lifespan_enabled", True):
            return {"ok": False, "skipped": "disabled", "wid": wid}

        if delta <= 0:
            return {
                "ok": True,
                "wid": wid,
                "new_lifespan": -1,
                "death_occurred": False,
                "skipped": "no_damage",
            }

        # 一次性读 ownership（先快查，不持锁）
        os_store = OwnershipStore(self._paths, gid_str)
        ownerships = os_store.load_all()
        target = next((o for o in ownerships if o.wid == wid), None)
        if target is None:
            return {"ok": False, "skipped": "wife_not_found", "wid": wid}
        if target.uid == actor_uid:
            return {
                "ok": False,
                "skipped": "self_ri",
                "wid": wid,
                "wife_owner_uid": target.uid,
            }
        if target.is_dead:
            return {
                "ok": False,
                "skipped": "not_alive",
                "wid": wid,
                "wife_owner_uid": target.uid,
            }

        # 持群锁后正式扣减（避免与 work/pk/ntr 并发）
        async with self._locks.acquire(gid_str):
            damage = self._lifespan.apply_damage(
                gid_str, wid, delta, cause=DEATH_CAUSE_IMPACT,
            )
        return {
            "ok": damage.ok,
            "wid": wid,
            "wife_owner_uid": target.uid,
            "new_lifespan": damage.new_lifespan,
            "death_occurred": damage.death_occurred,
            "skipped": "" if damage.ok else damage.reason,
        }
