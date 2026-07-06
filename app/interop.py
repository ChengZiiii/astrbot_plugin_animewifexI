"""跨插件 facade：impact 日老婆 联动。所有写走 GroupLocks；只读不走锁。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .services.ownership_service import OwnershipService
from .storage.locks import GroupLocks
from .storage.stores import OwnershipStore, WivesMasterStore

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
        level_names = {1: "相识", 2: "熟悉", 3: "亲密", 4: "挚爱", 5: "灵魂伴侣"}
        return {
            "wid": picked.wid,
            "name": meta.chara if meta else "",
            "source": meta.source if meta else "",
            "img": meta.img if meta else "",
            "intimacy": intimacy,
            "level": level,
            "level_name": level_names.get(level, ""),
            "is_primary": bool(picked.is_primary),
        }
