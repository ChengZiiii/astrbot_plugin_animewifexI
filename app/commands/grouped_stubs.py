"""Phase 2/3 分组命令占位（亲密度/经济/PK/图鉴/面板/任务/商城/求婚）。

Phase 1 仅注册 ``老婆帮助`` 与未实现提示，避免命令解析失败。
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from .context import CommandContext

__all__ = [
    "handle_not_implemented",
    "make_not_implemented_handler",
    "NOT_IMPLEMENTED_SUBCOMMANDS",
]


NOT_IMPLEMENTED_SUBCOMMANDS = (
    "列表", "查", "切换", "摸头", "送礼", "复仇", "PK", "求婚",
    "锁", "解锁", "排行", "图鉴", "面板", "签到",
    "商城", "购买", "背包", "任务",
)


async def handle_not_implemented(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """通用"功能未开放"提示"""
    yield event.plain_result(
        "该功能将在 Phase 2/3 开放，敬请期待~ 当前可用命令见「老婆帮助」"
    )


def make_not_implemented_handler(subcommand: str):
    """为指定子命令生成一个未实现提示处理器（保留 subcommand 用于未来埋点）"""

    async def _handler(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
        yield event.plain_result(
            f"「老婆 {subcommand}」将在 Phase 2/3 开放，敬请期待~"
        )

    return _handler
