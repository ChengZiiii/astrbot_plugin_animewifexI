"""当前仍保留的分组命令占位处理器。"""

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
    "列表", "查",
)


async def handle_not_implemented(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """通用"功能未开放"提示"""
    yield event.plain_result(
        "该功能当前还未开放，请先使用「老婆帮助」查看现有命令。"
    )


def make_not_implemented_handler(subcommand: str):
    """为指定子命令生成一个未实现提示处理器（保留 subcommand 用于未来埋点）"""

    async def _handler(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
        yield event.plain_result(
            f"「老婆 {subcommand}」当前还未开放，请先使用「老婆帮助」查看现有命令。"
        )

    return _handler
