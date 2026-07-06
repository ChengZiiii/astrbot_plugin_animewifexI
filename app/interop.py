"""跨插件 facade：impact 日老婆 联动。所有写走 GroupLocks；只读不走锁。"""

from __future__ import annotations

from typing import Any, Dict, Optional

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
    def __init__(self, ownership_service: OwnershipService, locks: GroupLocks, config, paths):
        self._os = ownership_service
        self._locks = locks
        self._config = config
        self._paths = paths

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
