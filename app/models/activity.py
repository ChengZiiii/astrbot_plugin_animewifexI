"""活动日志 dataclass：滚动 N 天的活动统计（榜单数据源）。

对应 ``data/groups/{gid}/activity.json`` 中
``{uid: {date: {action: count}}}`` 三层嵌套结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

from .enums import Action

__all__ = ["ActivityLog", "empty_day"]


def empty_day() -> Dict[str, int]:
    """返回一份全 0 的当日活动记录（包含所有 Action key）"""
    return {a: 0 for a in Action.ALL}


@dataclass
class ActivityLog:
    """单用户在单群的活动日志聚合（按日期索引）"""

    # 结构：{date_str: {action_key: value}}
    days: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Dict[str, int]]:
        return {date: dict(actions) for date, actions in self.days.items()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActivityLog":
        if not isinstance(data, Mapping):
            return cls()
        cleaned: Dict[str, Dict[str, int]] = {}
        for date, actions in data.items():
            if not isinstance(actions, Mapping):
                continue
            day = empty_day()
            for k, v in actions.items():
                if k in day and isinstance(v, (int, float)):
                    day[k] = int(v)
            cleaned[str(date)] = day
        return cls(days=cleaned)

    def increment(self, date: str, action: str, delta: int = 1) -> None:
        """在指定日期增加某动作的计数（自动创建当天条目）"""
        if action not in Action.ALL:
            return
        day = self.days.setdefault(date, empty_day())
        day[action] = day.get(action, 0) + max(0, delta)

    def get_day(self, date: str) -> Dict[str, int]:
        """获取某天的活动记录（不存在返回空模板）"""
        return self.days.get(date) or empty_day()

    def prune_before(self, keep_dates: "set[str] | None" = None, days: int = 7) -> int:
        """删除早于保留窗口的日期 key

        * ``keep_dates``：明确需要保留的日期集合（高优先级）
        * ``days``：保留最近 N 天（基于 ``keep_dates`` 之外的日期中最近的若干个）

        返回被删除的日期数量。
        """
        if not self.days:
            return 0
        keep = set(keep_dates or ())
        all_dates = sorted(self.days.keys(), reverse=True)
        kept_count = 0
        for date in all_dates:
            if date in keep:
                continue
            if kept_count < days:
                kept_count += 1
                continue
            del self.days[date]
        return len(all_dates) - len(self.days)
