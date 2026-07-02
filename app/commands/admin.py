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
    """生成帮助文本（v3.x Phase 3）"""
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

【亲密度功能】✨
• 老婆 摸头 - 消耗币增加亲密度
• 老婆 送礼 - 高消耗高加成亲密度

【复仇功能】⚔️
• 老婆 复仇 [@用户] - 在被牛24小时内复仇，成功率翻倍

【排行榜功能】📊
• 老婆 排行 [日|周|总] [牛|被牛|PK|收集]

【经济功能】💰
• 老婆 签到 - 每日领取老婆币
• 老婆 任务 - 查看每日任务 / 领取奖励
• 老婆 商城 - 查看可购买道具
• 老婆 购买 <道具> [数量] - 购买道具
• 老婆 背包 - 查看已持有道具

【管理员命令】
• 切换ntr开关状态 - 开启/关闭NTR功能
• 老婆 重置本群 - 清空本群所有老婆数据（慎用！）
• 老婆 重置抽卡 [@某人] - 重置目标的今日抽卡状态

💡 提示：部分命令有每日使用次数限制和冷却时间

🔮 更多玩法（PK/求婚/图鉴）将在后续开放~
""".strip()


async def handle_help(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``老婆帮助``"""
    yield event.plain_result(build_help_text())


# ==================== 管理员重置 ====================


async def handle_admin_reset_group(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 重置本群`` — 管理员清空本群所有老婆数据"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    if not ctx.config.is_admin(uid):
        yield event.plain_result(f"{nick}，你没有权限执行此操作~")
        return

    # 清空本群所有数据文件
    import os
    group_dir = ctx.paths.group_dir(gid)
    if os.path.exists(group_dir):
        import shutil
        shutil.rmtree(group_dir)
        os.makedirs(group_dir, exist_ok=True)

    yield event.plain_result(f"{nick}，本群老婆数据已全部重置！所有人的老婆、币、背包、亲密度均已清空。")


async def handle_admin_reset_draw(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 重置抽卡 [@某人]`` — 管理员重置目标的今日抽卡状态"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    tid = parse_at_target(event) or uid

    if not ctx.config.is_admin(uid):
        yield event.plain_result(f"{nick}，你没有权限执行此操作~")
        return

    from ..storage.stores import ProfileStore
    store = ProfileStore(ctx.paths, gid)
    profiles = store.load_all()
    target = profiles.get(tid)
    if not target:
        yield event.plain_result("目标用户没有老婆数据~")
        return

    target.last_draw_date = ""
    store.save_all(profiles)

    target_nick = target.nick or tid
    yield event.plain_result(f"已重置 {target_nick} 的今日抽卡状态，可以重新抽老婆了~")
