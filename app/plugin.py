"""WifePluginCore：插件业务装配基类（无 AstrBot 装饰器，便于单测）。

实际入口 :class:`WifePlugin` 在 ``main.py`` 中继承本类并加上
``@filter.event_message_type`` 装饰器。装饰器必须在 ``main.py`` 里，
否则 AstrBot reload 时由于 ``app.plugin`` 已缓存于 ``sys.modules``，
装饰器不会重跑 → handler 不重新注册 → 插件失效。
"""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star, StarTools

from .commands.context import CommandContext
from .commands.registration import build_registry
from .services.cooldown_service import CooldownService
from .services.ownership_service import OwnershipService
from .services.plugin_config import PluginConfig
from .services.wife_service import WifeService
from .storage.locks import GroupLocks
from .storage.migrations import archive_legacy_data
from .storage.paths import Paths
from .utils.time import get_today, seconds_until_next_midnight

DEFAULT_TIMEZONE = "Asia/Shanghai"

__all__ = ["WifePluginCore", "DEFAULT_TIMEZONE"]


class WifePluginCore(Star):
    """v3.x 插件业务装配（不含 ``@filter`` 装饰方法，便于单测）"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self._raw_config = config
        self.plugin_config = PluginConfig.from_dict(config)

        # 时区：跟随 AstrBot 全局 timezone 配置
        self.tz = self._resolve_timezone(context)

        # 数据目录与归档
        plugin_data_root = StarTools.get_data_dir("astrbot_plugin_animewifexI")
        self.paths = Paths(plugin_data_root)
        self.paths.ensure_dirs()

        # 启动时归档 v2.x 旧数据（Q6 = 清空重来）
        try:
            archive_legacy_data(self.paths)
        except Exception:
            logger.exception("归档 v2.x 旧数据失败，继续以新结构启动")

        # 并发模型：群锁池
        self.locks = GroupLocks()

        # 业务服务
        self.wife_service = WifeService(self.paths, self.plugin_config)
        self.ownership_service = OwnershipService(
            self.paths, self.plugin_config, self.locks, self.wife_service,
            self.cooldown_service,
        )
        self.cooldown_service = CooldownService(self.locks)

        # 命令注册表
        self.registry = build_registry()

        # 命令上下文（所有 handler 共享）
        self.cmd_ctx = CommandContext(
            paths=self.paths,
            config=self.plugin_config,
            locks=self.locks,
            ownership_service=self.ownership_service,
            wife_service=self.wife_service,
            cooldown_service=self.cooldown_service,
            tz=self.tz,
        )

        # 启动零点清理任务
        coro = self._daily_cleanup_loop()
        try:
            self._daily_cleanup_task = asyncio.create_task(coro)
        except RuntimeError:
            # 无运行中的事件循环时关闭协程，避免 "coroutine never awaited" 告警
            coro.close()
            self._daily_cleanup_task = None

    # ---------- 时区 ----------

    @staticmethod
    def _resolve_timezone(context: Context) -> ZoneInfo:
        """读取 AstrBot 全局时区配置（WebUI 系统设置 ``timezone``）"""
        tz_name = None
        try:
            tz_name = context.get_config().get("timezone")
        except Exception:
            tz_name = None
        if not tz_name:
            return _safe_zoneinfo(DEFAULT_TIMEZONE)
        try:
            return ZoneInfo(str(tz_name))
        except (ZoneInfoNotFoundError, ValueError):
            logger.error(
                f"AstrBot 全局时区配置无效: {tz_name!r}，已回退 {DEFAULT_TIMEZONE}"
            )
            return _safe_zoneinfo(DEFAULT_TIMEZONE)

    # ---------- 零点清理循环 ----------

    async def _daily_cleanup_loop(self):
        """每天零点清理跨天失效的 daily_counts / swap_requests / activity_logs，并递增亲密度"""
        while True:
            try:
                # 多等一分钟，避免时钟误差导致在日期变更前执行
                await asyncio.sleep(seconds_until_next_midnight(self.tz) + 60)
                await self._cleanup_all_groups()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("定时清理过期数据失败")

    async def _cleanup_all_groups(self):
        """逐群清理跨天失效的次数记录、交换请求、活动日志，并执行亲密度每日递增"""
        today = get_today(self.tz)
        # 已知群基于锁池（消息触发过的群），未触发的群也无数据可清
        for gid in list(self.locks.known_groups()):
            try:
                await self.ownership_service.prune_daily_counts_for_group(gid, today)
            except Exception:
                logger.exception(f"清理群 {gid} 的 daily_counts 失败")
            try:
                await self.ownership_service.prune_swap_requests_for_group(gid, today)
            except Exception:
                logger.exception(f"清理群 {gid} 的 swap_requests 失败")
            try:
                await self.ownership_service.prune_activity_logs_for_group(gid, today)
            except Exception:
                logger.exception(f"清理群 {gid} 的 activity_logs 失败")
            try:
                await self.ownership_service.daily_intimacy_increment_for_group(gid, today)
            except Exception:
                logger.exception(f"群 {gid} 亲密度每日递增失败")

    # ---------- 生命周期 ----------

    async def terminate(self):
        """插件卸载时停止后台任务"""
        task = getattr(self, "_daily_cleanup_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _safe_zoneinfo(name: str) -> ZoneInfo:
    """容错构造 ZoneInfo，缺失 tzdata 时回退 UTC"""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.error(f"时区 {name!r} 不可用，回退 UTC")
        return ZoneInfo("UTC")
