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
        "lock_item": 0,
        "revive_potion": 0,
        "protection_charm": 0,
        "draw_ticket_single": 0,    # 单抽券
        "draw_ticket_ten": 0,       # 十连券
        "revenge_token": 0,         # Phase 4: 复仇令牌
        "insurance_card": 0,        # Phase 4 第二波: 保险卡
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
    today_draws: int = 0              # 今日已抽卡次数
    today_free_draws: int = 0         # 今日已用免费次数
    today_draw_date: str = ""         # 今日抽卡日期（用于跨天重置）
    total_ntr_success: int = 0
    total_ntr_lost: int = 0
    total_pk_win: int = 0
    total_pk_lost: int = 0
    collection: List[str] = field(default_factory=list)              # 历史 wid 列表（图鉴）
    inventory: Dict[str, int] = field(default_factory=_default_inventory)
    last_ntr_by: Dict[str, Any] = field(default_factory=_default_last_ntr_by)
    pity_counter: int = 0
    # Phase 4 新增字段
    registered_at: int = 0                # 注册时间戳（Unix seconds），0=老玩家
    pk_score: int = 0                     # 当前赛季 PK 积分
    pk_score_season: str = ""             # 当前赛季 key（YYYY-MM）
    pk_last_active_date: str = ""         # 最近 PK 日期（YYYY-MM-DD）
    evil_points: int = 0                  # 作恶值
    evil_points_month: str = ""           # 作恶值所属月份（YYYY-MM）
    titles: List[str] = field(default_factory=list)       # 已获得称号列表
    active_title: str = ""                # 当前佩戴称号
    work_streak: int = 0                  # 连续打工天数
    work_last_settle_date: str = ""       # 最近打工结算日期（YYYY-MM-DD）
    work_week_key: str = ""               # 本周打工 key（YYYY-WW）
    work_week_income: int = 0             # 本周打工收入
    work_contract_reserved: str = ""      # 打工合约预留模式
    work_partner_uid: str = ""            # 打工搭档 uid
    work_partner_date: str = ""           # 打工搭档日期（YYYY-MM-DD）
    work_partner_count: int = 0           # 当日已绑定打工搭档次数
    work_partner_count_date: str = ""     # 打工搭档计数日期（YYYY-MM-DD）
    weekly_box_claimed_week: str = ""     # 已领取周宝箱的周 key（YYYY-WW）
    first_ntr_lost_done: bool = False     # 是否已首次被牛
    newbie_guide_claimed: List[str] = field(default_factory=list)  # 已领取的新手引导任务
    last_ntr_target_uid: str = ""         # 最近一次成功 NTR 的目标 uid
    same_target_ntr_streak: int = 0       # 对同一目标连续成功次数

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
            "today_draws": self.today_draws,
            "today_free_draws": self.today_free_draws,
            "today_draw_date": self.today_draw_date,
            "total_ntr_success": self.total_ntr_success,
            "total_ntr_lost": self.total_ntr_lost,
            "total_pk_win": self.total_pk_win,
            "total_pk_lost": self.total_pk_lost,
            "collection": list(self.collection),
            "inventory": dict(self.inventory),
            "last_ntr_by": dict(self.last_ntr_by) if self.last_ntr_by else {},
            "pity_counter": self.pity_counter,
            # Phase 4
            "registered_at": self.registered_at,
            "pk_score": self.pk_score,
            "pk_score_season": self.pk_score_season,
            "pk_last_active_date": self.pk_last_active_date,
            "evil_points": self.evil_points,
            "evil_points_month": self.evil_points_month,
            "titles": list(self.titles),
            "active_title": self.active_title,
            "work_streak": self.work_streak,
            "work_last_settle_date": self.work_last_settle_date,
            "work_week_key": self.work_week_key,
            "work_week_income": self.work_week_income,
            "work_contract_reserved": self.work_contract_reserved,
            "work_partner_uid": self.work_partner_uid,
            "work_partner_date": self.work_partner_date,
            "work_partner_count": self.work_partner_count,
            "work_partner_count_date": self.work_partner_count_date,
            "weekly_box_claimed_week": self.weekly_box_claimed_week,
            "first_ntr_lost_done": self.first_ntr_lost_done,
            "newbie_guide_claimed": list(self.newbie_guide_claimed),
            "last_ntr_target_uid": self.last_ntr_target_uid,
            "same_target_ntr_streak": self.same_target_ntr_streak,
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

        titles_raw = data.get("titles") or []
        if not isinstance(titles_raw, list):
            titles_raw = []

        newbie_guide_raw = data.get("newbie_guide_claimed") or []
        if not isinstance(newbie_guide_raw, list):
            newbie_guide_raw = []

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
            today_draws=int(data.get("today_draws", 0) or 0),
            today_free_draws=int(data.get("today_free_draws", 0) or 0),
            today_draw_date=str(data.get("today_draw_date", "") or ""),
            total_ntr_success=int(data.get("total_ntr_success", 0) or 0),
            total_ntr_lost=int(data.get("total_ntr_lost", 0) or 0),
            total_pk_win=int(data.get("total_pk_win", 0) or 0),
            total_pk_lost=int(data.get("total_pk_lost", 0) or 0),
            collection=[str(x) for x in collection_raw],
            inventory=inventory,
            last_ntr_by=dict(last_ntr_raw),
            pity_counter=int(data.get("pity_counter", 0) or 0),
            # Phase 4
            registered_at=int(data.get("registered_at", 0) or 0),
            pk_score=int(data.get("pk_score", 0) or 0),
            pk_score_season=str(data.get("pk_score_season", "") or ""),
            pk_last_active_date=str(data.get("pk_last_active_date", "") or ""),
            evil_points=int(data.get("evil_points", 0) or 0),
            evil_points_month=str(data.get("evil_points_month", "") or ""),
            titles=[str(x) for x in titles_raw],
            active_title=str(data.get("active_title", "") or ""),
            work_streak=int(data.get("work_streak", 0) or 0),
            work_last_settle_date=str(data.get("work_last_settle_date", "") or ""),
            work_week_key=str(data.get("work_week_key", "") or ""),
            work_week_income=int(data.get("work_week_income", 0) or 0),
            work_contract_reserved=str(data.get("work_contract_reserved", "") or ""),
            work_partner_uid=str(data.get("work_partner_uid", "") or ""),
            work_partner_date=str(data.get("work_partner_date", "") or ""),
            work_partner_count=int(data.get("work_partner_count", 0) or 0),
            work_partner_count_date=str(data.get("work_partner_count_date", "") or ""),
            weekly_box_claimed_week=str(data.get("weekly_box_claimed_week", "") or ""),
            first_ntr_lost_done=bool(data.get("first_ntr_lost_done", False)),
            newbie_guide_claimed=[str(x) for x in newbie_guide_raw],
            last_ntr_target_uid=str(data.get("last_ntr_target_uid", "") or ""),
            same_target_ntr_streak=int(data.get("same_target_ntr_streak", 0) or 0),
        )

    @classmethod
    def new_with_defaults(
        cls,
        uid: str,
        nick: str = "",
        coins: int = 50,
    ) -> "UserProfile":
        """按配置默认值创建新档案"""
        return cls(uid=uid, nick=nick, coins=coins)
