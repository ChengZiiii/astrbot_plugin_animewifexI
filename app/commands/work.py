"""打工命令处理器。"""

from __future__ import annotations

import random
import re
from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid, parse_at_target
from ..storage.stores import ProfileStore, WivesMasterStore
from ..services.work_service import WorkContractResult, WorkPartnerResult, WorkService, WorkSettleResult
from .context import CommandContext
from .view import find_wid_by_position

__all__ = ["handle_work", "try_settle_work"]

# 模式别名映射
MODE_ALIASES = {
    "加班": "overtime",
    "远征": "expedition",
}

# 打工结算风味台词（{name} 会被替换为老婆名，{reward} 为奖励币数）
_WORK_SETTLE_FLAVOR = [
    "{name}回来了！赚了{reward}币，累得趴在桌子上了……",
    "{name}：打工好累啊……但是赚到钱了！{reward}币！",
    "{name}拖着疲惫的身体回来了，但看到{reward}币的工资条就笑了~",
    "{name}：老板说我很能干！还多给了小费~ {reward}币到手！",
    "{name}回来了，衣服上沾满了灰尘，但钱包鼓鼓的~ {reward}币！",
    "{name}：我回来了~ {reward}币！虽然累但是值得的！",
]

_WORK_TAUNTS = {
    "normal": [
        "{name}一个人出去打工了，好像很忙的样子……有没有人想去「关心」一下？",
        "{name}正在工厂里埋头苦干，完全没注意到身后的目光……",
        "{name}出去赚钱了！不过听说最近外面不太平，小心被坏人盯上哦~",
        "{name}背着小包出门打工了，看起来孤零零的……谁去陪陪她？",
        "打工中的{name}毫无防备，这可是千载难逢的好机会……",
    ],
    "overtime": [
        "{name}加班到深夜，周围一个人都没有……好危险的感觉！",
        "{name}说加班能赚更多钱，但深夜独处也太不安全了吧……",
        "加班中的{name}累得快要睡着了，这时候如果有人靠近……",
        "{name}选择了加班！虽然赚得多，但被盯上的概率也更大了……",
    ],
    "expedition": [
        "{name}踏上了远征之路！要离开好久……这段时间会发生什么呢？",
        "{name}远征去了，短期内回不来。她的位置空出来了，有人想趁虚而入吗？",
        "远征中的{name}身处远方，完全顾不上这边……这可是最容易得手的时候！",
        "{name}去远征了！收益最高但风险也最大——被牛概率高达2.5倍！",
    ],
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
        taunt = random.choice(_WORK_SETTLE_FLAVOR).format(name=wife_name, reward=result.reward)
        return (
            f"🎉 {wife_name} 的{mode_name}打工结算完成！获得 {result.reward} 币，"
            f"亲密度 +{result.intimacy_gain}\n"
            f"余额：{result.coin_balance} 币"
            f"\n\n💬 {taunt}"
        )
    return None


async def handle_work(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 打工 [编号] [加班|远征]`` / ``老婆 打工 合约`` / ``老婆 打工 搭档``"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    work_service = WorkService(ctx.paths, ctx.config, ctx.locks)

    # 解析参数
    msg = (event.message_str or "").strip()
    rest = msg
    for prefix in ("老婆打工", "老婆 打工"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    if rest.startswith("合约"):
        async for item in _handle_work_contract(event, ctx, work_service, gid, uid, nick, rest):
            yield item
        return

    if rest.startswith("搭档"):
        async for item in _handle_work_partner(event, ctx, work_service, gid, uid, nick):
            yield item
        return

    if rest.startswith("中断"):
        async for item in _handle_work_cancel(event, ctx, work_service, gid, uid, nick, rest):
            yield item
        return

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

    # 先尝试结算到期的打工
    settle_result = await work_service.resolve_due_work(gid, uid, nick, ctx.today())
    if settle_result and settle_result.ok:
        wife_name = _wife_name(ctx, settle_result.wid)
        mode_name = _mode_name(settle_result.mode)
        bonus_lines = []
        if settle_result.contract_used:
            bonus_lines.append("📜 打工合约生效，本次收益提升！")
        if settle_result.partner_bonus_used:
            bonus_lines.append("🤝 打工搭档加成生效，本次收益提升！")
        taunt = random.choice(_WORK_SETTLE_FLAVOR).format(name=wife_name, reward=settle_result.reward)
        yield event.plain_result(
            f"🎉 {wife_name} 的{mode_name}打工结算完成！获得 {settle_result.reward} 币\n"
            f"亲密度 +{settle_result.intimacy_gain}，连续打工 {settle_result.streak} 天\n"
            f"余额：{settle_result.coin_balance} 币"
            + ("\n" + "\n".join(bonus_lines) if bonus_lines else "")
            + f"\n\n💬 {taunt}"
        )

    # 启动新的打工
    result = await work_service.start_work(gid, uid, nick, mode, ctx.today(), selected_wid, umo=event.unified_msg_origin)

    if not result.ok:
        if result.reason == "disabled":
            yield event.plain_result("打工功能暂未开启~")
        elif result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你还没有老婆，先去抽一个吧~")
        elif result.reason == "wife_not_found":
            yield event.plain_result(f"{nick}，你指定的老婆编号不存在哦~")
        elif result.reason == "already_working":
            max_c = ctx.config.work_max_concurrent
            yield event.plain_result(f"{nick}，已经有 {max_c} 位老婆在打工中，达到上限了~")
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
    taunt = random.choice(_WORK_TAUNTS.get(mode, _WORK_TAUNTS["normal"]))
    yield event.plain_result(
        f"🔨 {nick} 派 {wife_name} 开始{mode_name}打工！\n"
        f"消耗 {result.start_cost} 币，余额 {result.coin_balance} 币\n"
        f"预计完成后结算奖励~\n\n"
        f"📢 {taunt.format(name=wife_name)}"
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


async def _handle_work_contract(
    event: AstrMessageEvent,
    ctx: CommandContext,
    work_service: WorkService,
    gid: str,
    uid: str,
    nick: str,
    rest: str,
) -> AsyncGenerator:
    """预约下一次指定模式的打工合约。"""
    mode = "normal"
    for alias, mode_key in MODE_ALIASES.items():
        if alias in rest:
            mode = mode_key
            break

    result = await work_service.reserve_work_contract(gid, uid, nick, mode)
    if not result.ok:
        if result.reason == "invalid_mode":
            yield event.plain_result("可预约的合约模式：老婆 打工 合约 / 老婆 打工 合约 加班 / 老婆 打工 合约 远征")
        elif result.reason == "already_reserved":
            yield event.plain_result(f"{nick}，你已经预约过一次{_mode_name(result.mode)}打工合约了，先完成再说吧~")
        elif result.reason == "not_enough_coins":
            yield event.plain_result(
                f"{nick}，预约打工合约需要 {ctx.config.work_contract_cost} 币，当前只有 {result.coin_balance} 币~"
            )
        else:
            yield event.plain_result(f"{nick}，预约打工合约失败了~")
        return

    yield event.plain_result(
        f"📜 {nick} 已预约下一次{_mode_name(result.mode)}打工合约！\n"
        f"下次同模式打工完成时收益 x{ctx.config.work_contract_reward_multiplier:.1f}\n"
        f"余额：{result.coin_balance} 币"
    )


async def _handle_work_partner(
    event: AstrMessageEvent,
    ctx: CommandContext,
    work_service: WorkService,
    gid: str,
    uid: str,
    nick: str,
) -> AsyncGenerator:
    """绑定今日打工搭档。"""
    partner_uid = parse_at_target(event)
    if not partner_uid:
        yield event.plain_result(f"{nick}，请 @ 你想绑定的打工搭档哦~")
        return

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    partner_profile = profiles.get(partner_uid)
    partner_nick = partner_profile.nick if partner_profile else partner_uid

    result = await work_service.set_work_partner(
        gid, uid, partner_uid, nick, partner_nick, ctx.today()
    )
    if not result.ok:
        if result.reason == "invalid_target":
            yield event.plain_result(f"{nick}，不能把自己设成打工搭档哦~")
        elif result.reason == "no_wife":
            yield event.plain_result(f"{nick}，你还没有老婆，先去抽一个吧~")
        elif result.reason == "target_no_wife":
            yield event.plain_result(f"{nick}，对方还没有老婆，没法一起打工哦~")
        elif result.reason == "already_partner":
            yield event.plain_result(f"{nick}，你们今天已经是打工搭档啦~")
        elif result.reason == "daily_limit":
            yield event.plain_result(
                f"{nick}，今天绑定打工搭档的次数（{ctx.config.work_partner_daily_limit} 次/天）已经用完啦~"
            )
        elif result.reason == "target_has_partner":
            yield event.plain_result(f"{nick}，对方今天已经和别人绑定打工搭档了~")
        else:
            yield event.plain_result(f"{nick}，绑定打工搭档失败了~")
        return

    yield event.plain_result(
        f"🤝 {nick} 与 {partner_nick} 已绑定今日打工搭档！\n"
        f"双方今天都成功打工时，结算收益额外 +{int(ctx.config.work_partner_bonus * 100)}%"
    )


async def _handle_work_cancel(
    event: AstrMessageEvent,
    ctx: CommandContext,
    work_service: WorkService,
    gid: str,
    uid: str,
    nick: str,
    rest: str,
) -> AsyncGenerator:
    """中断打工（全额没收）"""
    selected_wid = None
    number_match = re.search(r"\b(\d+)\b", rest)
    if number_match:
        index = int(number_match.group(1))
        selected_wid = find_wid_by_position(ctx, gid, uid, index)
        if selected_wid is None:
            yield event.plain_result(f"{nick}，你指定的老婆编号不存在哦~")
            return

    result = await work_service.cancel_work(gid, uid, selected_wid)
    if not result.ok:
        if result.reason == "not_working":
            yield event.plain_result(f"{nick}，没有老婆在打工中哦~")
        else:
            yield event.plain_result(f"{nick}，中断打工失败了~")
        return

    wife_name = _wife_name(ctx, result.wid)
    mode_name = _mode_name(result.mode)
    yield event.plain_result(
        f"🚫 {nick} 中断了 {wife_name} 的{mode_name}打工！\n"
        f"打工奖励已没收，启动费不退还~"
    )
