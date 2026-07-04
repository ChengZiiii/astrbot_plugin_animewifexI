"""时间处理工具：时区感知的日期/秒数计算。

AstrBot 全局时区配置（WebUI 系统设置 ``timezone``）由调用方解析后传入，
本模块只负责基于给定时区做无副作用的纯函数计算。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = [
    "get_today",
    "seconds_until_next_midnight",
    "now_ts",
    "get_week_key",
    "get_month_key",
    "is_next_day",
    "hours_between",
]


def get_today(tz: ZoneInfo) -> str:
    """获取指定时区的当前日期字符串（ISO 格式 ``YYYY-MM-DD``）"""
    return datetime.now(tz).date().isoformat()


def seconds_until_next_midnight(tz: ZoneInfo) -> float:
    """距指定时区下一个零点的秒数"""
    now = datetime.now(tz)
    next_midnight = datetime.combine(
        (now + timedelta(days=1)).date(), datetime.min.time(), tzinfo=tz
    )
    return (next_midnight - now).total_seconds()


def now_ts() -> int:
    """当前 Unix 时间戳（秒，整数）"""
    return int(datetime.now().timestamp())


def get_week_key(tz: ZoneInfo) -> str:
    """获取 ISO 周 key，格式 ``YYYY-WW``（如 ``2026-W01``）"""
    now = datetime.now(tz)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def get_month_key(tz: ZoneInfo) -> str:
    """获取自然月 key，格式 ``YYYY-MM``"""
    return datetime.now(tz).strftime("%Y-%m")


def is_next_day(prev_date: str, today: str) -> bool:
    """判断 ``today`` 是否是 ``prev_date`` 的下一天。

    两者均为 ISO 格式 ``YYYY-MM-DD`` 字符串。
    如果 ``prev_date`` 为空或无效，返回 ``False``。
    """
    try:
        prev = datetime.fromisoformat(prev_date).date()
        cur = datetime.fromisoformat(today).date()
        return (cur - prev).days == 1
    except (ValueError, TypeError):
        return False


def hours_between(ts1: int, ts2: int) -> float:
    """计算两个 Unix 时间戳之间的小时差（绝对值）"""
    return abs(ts2 - ts1) / 3600.0
