"""打工命令处理器。"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..services.work_service import WorkService, WorkSettleResult
from .context import CommandContext

__all__ = ["handle_work", "try_settle_work"]

# 模式别名映射
MODE_ALIASES = {
    "加班": "overtime",
    "远征": "expedition",
}


async def try_settle_work(
    event: AstrMessageEvent, ctx: CommandContext
) -> Optional[str]:
    """尝试结算到期的打工，返回结算消息或 None"""
    gid = get_group_id(event)
    if not gid:
        return None
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    work_service = WorkService(ctx.paths, ctx.config, ctx.locks)
    result = await work_service.resolve_due_work(gid, uid, nick, ctx.today())
    if result and result.ok:
        return (
            f"🎉 打工结算完成！获得 {result.reward} 币，"
            f"亲密度 +{result.intimacy_gain}\n"
            f"余额：{result.coin_balance} 币"
        )
    return None


async def handle_work(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 打工 [加班|远征]``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    # 解析模式
    msg = (event.message_str or "").strip()
    mode = "normal"
    for alias, mode_key in MODE_ALIASES.items():
        if alias in msg:
            mode = mode_key
            break

    work_service = WorkService(ctx.paths, ctx.config, ctx.locks)

    # 先尝试结算到期的打工
    settle_result = await work_service.resolve_due_work(gid, uid, nick, ctx.today())
    if settle_result and settle_result.ok:
        yield event.plain_result(
            f"🎉 打工结算完成！获得 {settle_result.reward} 币\n"
            f"亲密度 +{settle_result.intimacy_gain}，连续打工 {settle_result.streak} 天\n"
            f"余额：{settle_result.coin_balance} 币"
        )

    # 启动新的打工
    result = await work_service.start_work(gid, uid, nick, mode, ctx.today())

    if not result.ok:
        if result.reason == "disabled":
            yield event.plain_result("打工功能暂未开启~")
        elif result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你还没有老婆，先去抽一个吧~")
        elif result.reason == "already_working":
            yield event.plain_result(f"{nick}，你正在打工中，不能重复开始哦~")
        elif result.reason == "invalid_mode":
            yield event.plain_result(f"打工模式不存在，可用：老婆 打工 / 老婆 打工 加班 / 老婆 打工 远征")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"{nick}，启动打工需要 {result.start_cost} 币，"
                f"你只有 {result.coin_balance} 币~"
            )
        else:
            yield event.plain_result(f"{nick}，打工失败了~")
        return

    # 打工成功
    mode_names = {"normal": "普通", "overtime": "加班", "expedition": "远征"}
    mode_name = mode_names.get(mode, mode)
    yield event.plain_result(
        f"🔨 {nick} 开始{mode_name}打工！\n"
        f"消耗 {result.start_cost} 币，余额 {result.coin_balance} 币\n"
        f"预计完成后结算奖励~"
    )
