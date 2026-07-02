"""用户档案 dataclass：群内某用户的游戏状态。

对应 ``data/groups/{gid}/profiles.json`` 中以 uid 为 key 的一条记录。

字段语义见 ROADMAP.md §2.2 ``profiles.json`` 示例。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

__all__ = ["UserProfile"]


def _default_inventory() -> Dict[str, int]:
    return {
        "reroll_ticket": 0,
        "capacity_expansion": 0,
        "lock_item": 0,
        "revive_potion": 0,
        "protection_charm": 0,
    }


def _default_last_ntr_by() -> Dict[str, Any]:
    # 字段缺失/None 时返回空 dict，避免从旧数据加载时 KeyError
    return {}


@dataclass
class UserProfile:
    """用户在某群的综合档案"""

    uid: str
    nick: str = ""
    coins: int = 0
    capacity: int = 3
    streak_days: int = 0
    last_draw_date: str = ""          # YYYY-MM-DD
    last_checkin_date: str = ""       # 每日签到日期
    quest_completed_date: str = ""    # 当日任务完成标记
    total_draws: int = 0
    total_ntr_success: int = 0
    total_ntr_lost: int = 0
    total_pk_win: int = 0
    total_pk_lost: int = 0
    collection: List[str] = field(default_factory=list)              # 历史 wid 列表（图鉴）
    inventory: Dict[str, int] = field(default_factory=_default_inventory)
    last_ntr_by: Dict[str, Any] = field(default_factory=_default_last_ntr_by)
    pity_counter: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "nick": self.nick,
            "coins": self.coins,
            "capacity": self.capacity,
            "streak_days": self.streak_days,
            "last_draw_date": self.last_draw_date,
            "last_checkin_date": self.last_checkin_date,
            "quest_completed_date": self.quest_completed_date,
            "total_draws": self.total_draws,
            "total_ntr_success": self.total_ntr_success,
            "total_ntr_lost": self.total_ntr_lost,
            "total_pk_win": self.total_pk_win,
            "total_pk_lost": self.total_pk_lost,
            "collection": list(self.collection),
            "inventory": dict(self.inventory),
            "last_ntr_by": dict(self.last_ntr_by) if self.last_ntr_by else {},
            "pity_counter": self.pity_counter,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UserProfile":
        inventory_raw = data.get("inventory") or {}
        if not isinstance(inventory_raw, Mapping):
            inventory_raw = {}
        # 合并默认 key，避免新增道具时老档案缺失
        inventory = _default_inventory()
        inventory.update({k: int(v or 0) for k, v in inventory_raw.items()})

        last_ntr_raw = data.get("last_ntr_by") or {}
        if not isinstance(last_ntr_raw, Mapping):
            last_ntr_raw = {}

        collection_raw = data.get("collection") or []
        if not isinstance(collection_raw, list):
            collection_raw = []

        return cls(
            uid=str(data.get("uid", "")),
            nick=str(data.get("nick", "") or ""),
            coins=int(data.get("coins", 0) or 0),
            capacity=int(data.get("capacity", 3) or 3),
            streak_days=int(data.get("streak_days", 0) or 0),
            last_draw_date=str(data.get("last_draw_date", "") or ""),
            last_checkin_date=str(data.get("last_checkin_date", "") or ""),
            quest_completed_date=str(data.get("quest_completed_date", "") or ""),
            total_draws=int(data.get("total_draws", 0) or 0),
            total_ntr_success=int(data.get("total_ntr_success", 0) or 0),
            total_ntr_lost=int(data.get("total_ntr_lost", 0) or 0),
            total_pk_win=int(data.get("total_pk_win", 0) or 0),
            total_pk_lost=int(data.get("total_pk_lost", 0) or 0),
            collection=[str(x) for x in collection_raw],
            inventory=inventory,
            last_ntr_by=dict(last_ntr_raw),
            pity_counter=int(data.get("pity_counter", 0) or 0),
        )

    @classmethod
    def new_with_defaults(
        cls,
        uid: str,
        nick: str = "",
        capacity: int = 3,
        coins: int = 50,
    ) -> "UserProfile":
        """按配置默认值创建新档案"""
        return cls(uid=uid, nick=nick, capacity=capacity, coins=coins)
