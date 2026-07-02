"""时间处理工具：时区感知的日期/秒数计算。

AstrBot 全局时区配置（WebUI 系统设置 ``timezone``）由调用方解析后传入，
本模块只负责基于给定时区做无副作用的纯函数计算。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = ["get_today", "seconds_until_next_midnight", "now_ts"]


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
