"""所有权 dataclass：群内某老婆与某用户的归属关系。

对应 ``data/groups/{gid}/ownership.json`` 的单条记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .enums import AcquireVia

__all__ = ["Ownership"]


@dataclass
class Ownership:
    """群内老婆所有权记录

    一个老婆在群内全局唯一（Q2），故同一 ``wid`` 在 ``ownership.json`` 中只会出现一次。
    一个用户可以同时持有多条（受 :attr:`UserProfile.capacity` 限制）。
    """

    wid: str
    uid: str
    acquired_at: int = 0
    acquired_via: str = AcquireVia.DRAW
    intimacy: int = 0
    intimacy_updated_date: str = ""    # YYYY-MM-DD，零点 +亲密度时用于幂等
    is_locked: bool = False
    lock_expires_at: Optional[int] = None  # 求婚锁定为 None（永久），限期锁定为时间戳
    is_primary: bool = False           # 是否为用户主老婆（旧命令的"今日老婆"）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wid": self.wid,
            "uid": self.uid,
            "acquired_at": self.acquired_at,
            "acquired_via": self.acquired_via,
            "intimacy": self.intimacy,
            "intimacy_updated_date": self.intimacy_updated_date,
            "is_locked": self.is_locked,
            "lock_expires_at": self.lock_expires_at,
            "is_primary": self.is_primary,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Ownership":
        return cls(
            wid=str(data.get("wid", "")),
            uid=str(data.get("uid", "")),
            acquired_at=int(data.get("acquired_at", 0) or 0),
            acquired_via=str(data.get("acquired_via", AcquireVia.DRAW) or AcquireVia.DRAW),
            intimacy=int(data.get("intimacy", 0) or 0),
            intimacy_updated_date=str(data.get("intimacy_updated_date", "") or ""),
            is_locked=bool(data.get("is_locked", False)),
            lock_expires_at=(
                int(data["lock_expires_at"])
                if data.get("lock_expires_at") is not None
                else None
            ),
            is_primary=bool(data.get("is_primary", False)),
        )
