"""管理员 + 重置 + 帮助命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import At, Plain

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from ..services.ownership_service import DailyAction
from .context import CommandContext

__all__ = [
    "handle_reset_ntr",
    "handle_reset_change",
    "handle_switch_ntr",
    "handle_help",
    "build_help_text",
]


# ==================== 重置 ====================


async def _do_reset(
    event: AstrMessageEvent,
    ctx: CommandContext,
    action: str,
    label: str,
    short: str,
) -> AsyncGenerator:
    """通用重置命令：管理员直接成功；普通用户按概率（失败禁言）

    ``action``: DailyAction 常量（如 ``DailyAction.NTR_ATTEMPT``）
    ``label``:  消息中的完整名称（如 "牛老婆"）
    ``short``:  失败提示中的简称（如 "牛"）
    """
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    tid = parse_at_target(event) or uid
    is_admin = ctx.config.is_admin(uid)

    result = await ctx.ownership_service.reset_user_action(
        gid=gid,
        operator_uid=uid,
        operator_is_admin=is_admin,
        target_uid=tid,
        action=action,
        today=ctx.today(),
    )

    if not result["ok"]:
        if result["reason"] == "limit_reached":
            yield event.plain_result(
                f"{nick}，你今天已经用完{ctx.config.reset_max_uses_per_day}次重置机会啦，明天再来吧~"
            )
            return
        # 其他失败原因（roll_failed）走 do_mute 分支

    if result["ok"]:
        # 成功消息
        prefix = "管理员操作：已重置" if is_admin else "已重置"
        if is_admin:
            yield event.chain_result(
                [Plain(prefix), At(qq=tid), Plain(f"的{label}次数。")]
            )
        else:
            yield event.chain_result(
                [Plain(prefix), At(qq=tid), Plain(f"的{label}次数。")]
            )
        return

    # 失败 + 需禁言
    yield event.plain_result(
        f"{nick}，重置{short}失败，被禁言{ctx.config.reset_mute_duration}秒，下次记得再接再厉哦~"
    )
    if result["do_mute"]:
        try:
            await event.bot.set_group_ban(
                group_id=int(gid),
                user_id=int(uid),
                duration=result["mute_duration"],
            )
        except Exception:
            # 禁言失败（权限不足/平台不支持）静默忽略
            pass


async def handle_reset_ntr(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``重置牛 [@用户]``"""
    async for reply in _do_reset(
        event, ctx, DailyAction.NTR_ATTEMPT, "牛老婆", "牛"
    ):
        yield reply


async def handle_reset_change(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``重置换 [@用户]``"""
    async for reply in _do_reset(
        event, ctx, DailyAction.CHANGE_ATTEMPT, "换老婆", "换"
    ):
        yield reply


# ==================== NTR 开关 ====================


async def handle_switch_ntr(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``切换ntr开关状态``：管理员切换本群 NTR 开关"""
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    if not ctx.config.is_admin(uid):
        yield event.plain_result(f"{nick}，你没有权限操作哦~")
        return

    gid = get_group_id(event)
    if not gid:
        return

    current = ctx.ownership_service.get_ntr_enabled(gid)
    ctx.ownership_service.set_ntr_enabled(gid, not current)
    state = "开启" if not current else "关闭"
    yield event.plain_result(f"{nick}，NTR已{state}")


# ==================== 帮助 ====================


def build_help_text() -> str:
    """生成帮助文本（v3.x Phase 1）"""
    return """
【基础命令】
• 抽老婆 - 每天抽取一个二次元老婆
• 查老婆 [@用户] - 查看别人的老婆（支持昵称匹配）

【牛老婆功能】(概率较低😭)
• 牛老婆 [@用户] - 有概率抢走别人的老婆
• 重置牛 [@用户] - 重置牛的次数(失败会禁言)

【换老婆功能】
• 换老婆 - 丢弃当前老婆换新的
• 重置换 [@用户] - 重置换老婆的次数(失败会禁言)

【交换功能】
• 交换老婆 [@用户] - 向别人发起老婆交换请求
• 同意交换 [@发起者] - 同意交换请求
• 拒绝交换 [@发起者] - 拒绝交换请求
• 查看交换请求 - 查看当前的交换请求

【管理员命令】
• 切换ntr开关状态 - 开启/关闭NTR功能

💡 提示：部分命令有每日使用次数限制

🔮 更多玩法（亲密度/PK/商城/图鉴）将在 Phase 2/3 陆续开放~
""".strip()


async def handle_help(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``老婆帮助``"""
    yield event.plain_result(build_help_text())
