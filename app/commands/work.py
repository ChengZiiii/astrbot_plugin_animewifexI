"""打工命令处理器。"""

from __future__ import annotations

import re
from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..storage.stores import WivesMasterStore
from ..services.work_service import WorkService, WorkSettleResult
from .context import CommandContext
from .view import find_wid_by_position

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
        wife_name = _wife_name(ctx, result.wid)
        mode_name = _mode_name(result.mode)
        return (
            f"🎉 {wife_name} 的{mode_name}打工结算完成！获得 {result.reward} 币，"
            f"亲密度 +{result.intimacy_gain}\n"
            f"余额：{result.coin_balance} 币"
        )
    return None


async def handle_work(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 打工 [编号] [加班|远征]``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    # 解析参数
    msg = (event.message_str or "").strip()
    rest = msg
    for prefix in ("老婆打工", "老婆 打工"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    mode = "normal"
    for alias, mode_key in MODE_ALIASES.items():
        if alias in rest:
            mode = mode_key
            break

    selected_wid = None
    number_match = re.search(r"\b(\d+)\b", rest)
    if number_match:
        index = int(number_match.group(1))
        selected_wid = find_wid_by_position(ctx, gid, uid, index)
        if selected_wid is None:
            yield event.plain_result(f"{nick}，你指定的老婆编号不存在哦~")
            return

    work_service = WorkService(ctx.paths, ctx.config, ctx.locks)

    # 先尝试结算到期的打工
    settle_result = await work_service.resolve_due_work(gid, uid, nick, ctx.today())
    if settle_result and settle_result.ok:
        wife_name = _wife_name(ctx, settle_result.wid)
        mode_name = _mode_name(settle_result.mode)
        yield event.plain_result(
            f"🎉 {wife_name} 的{mode_name}打工结算完成！获得 {settle_result.reward} 币\n"
            f"亲密度 +{settle_result.intimacy_gain}，连续打工 {settle_result.streak} 天\n"
            f"余额：{settle_result.coin_balance} 币"
        )

    # 启动新的打工
    result = await work_service.start_work(gid, uid, nick, mode, ctx.today(), selected_wid)

    if not result.ok:
        if result.reason == "disabled":
            yield event.plain_result("打工功能暂未开启~")
        elif result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你还没有老婆，先去抽一个吧~")
        elif result.reason == "wife_not_found":
            yield event.plain_result(f"{nick}，你指定的老婆编号不存在哦~")
        elif result.reason == "already_working":
            wife_name = _wife_name(ctx, result.wid)
            yield event.plain_result(f"{nick}，{wife_name} 正在打工中，不能重复开始哦~")
        elif result.reason == "invalid_mode":
            yield event.plain_result(f"打工模式不存在，可用：老婆 打工 [编号] / 老婆 打工 [编号] 加班 / 老婆 打工 [编号] 远征")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"{nick}，启动打工需要 {result.start_cost} 币，"
                f"你只有 {result.coin_balance} 币~"
            )
        else:
            yield event.plain_result(f"{nick}，打工失败了~")
        return

    # 打工成功
    mode_name = _mode_name(mode)
    wife_name = _wife_name(ctx, result.wid)
    yield event.plain_result(
        f"🔨 {nick} 派 {wife_name} 开始{mode_name}打工！\n"
        f"消耗 {result.start_cost} 币，余额 {result.coin_balance} 币\n"
        f"预计完成后结算奖励~"
    )


def _wife_name(ctx: CommandContext, wid: str) -> str:
    wives = WivesMasterStore(ctx.paths).load_all()
    wife = wives.get(wid)
    if wife is None:
        return "该老婆"
    return wife.chara or wife.img or "该老婆"


def _mode_name(mode: str) -> str:
    return {
        "normal": "普通",
        "overtime": "加班",
        "expedition": "远征",
    }.get(mode, mode)
