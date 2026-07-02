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
    "handle_admin_reset_group",
    "handle_admin_reset_draw",
    "handle_admin_test_draw",
    "handle_admin_test_intimacy",
    "handle_admin_test_coins",
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
• 抽老婆 - 抽取新老婆（每日1次免费，之后消耗单抽券）
• 十连 - 十连抽卡（消耗十连券，9折优惠）
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
• 老婆 商城 - 查看可购买道具（含单抽券/十连券）
• 老婆 购买 <道具> [数量] - 购买道具
• 老婆 背包 - 查看已持有道具

【锁定功能】🔒
• 老婆 锁定 <编号> - 限期锁定老婆7天（消耗锁定卡）
• 老婆 解锁 <编号> - 解锁老婆

【PK功能】⚔️
• 老婆 PK @某人 - 老婆PK对战

【图鉴/面板】📋
• 老婆 图鉴 - 查看收集进度
• 老婆 面板 - 查看个人面板

【管理员命令】
• 切换ntr开关状态 - 开启/关闭NTR功能
• 老婆 重置本群 - 清空本群所有老婆数据（慎用！）
• 老婆 重置抽卡 [@某人] - 重置目标的今日抽卡状态
• 老婆 测试抽卡 [次数] - 模拟抽卡测试概率分布（不写入数据）
• 老婆 测试亲密度 @某人 <数值> - 设置目标亲密度
• 老婆 测试币 @某人 <数值> - 设置目标老婆币余额

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

    from ..storage.stores import OwnershipStore, ProfileStore
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    target = profiles.get(tid)
    if not target:
        yield event.plain_result("目标用户没有老婆数据~")
        return

    # 清除今日抽卡日期
    target.last_draw_date = ""
    profile_store.save_all(profiles)

    # 清除主老婆记录（否则 draw_or_get_primary 仍会返回旧老婆）
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    OwnershipStore.clear_primary_for_user(ownerships, tid)
    ownership_store.save_all(ownerships)

    target_nick = target.nick or tid
    yield event.plain_result(f"已重置 {target_nick} 的今日抽卡状态，可以重新抽老婆了~")


async def handle_admin_test_draw(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 测试抽卡 <次数>`` — 管理员批量模拟抽卡（不写入数据，仅测试概率）"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    if not ctx.config.is_admin(uid):
        yield event.plain_result(f"{nick}，你没有权限执行此操作~")
        return

    msg = (event.message_str or "").strip()
    rest = msg
    for prefix in ("老婆测试抽卡", "老婆 测试抽卡"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    try:
        count = int(rest) if rest else 10
    except ValueError:
        count = 10
    count = max(1, min(count, 1000))

    from ..models.profile import UserProfile
    from ..services.rarity_service import RarityService

    rarity_svc = RarityService(ctx.paths, ctx.config)

    # 模拟抽卡统计
    stats = {"N": 0, "R": 0, "SR": 0, "SSR": 0}
    pity_triggers = 0
    max_pity = 0
    current_pity = 0

    for i in range(count):
        rarity, pity_hit = rarity_svc.roll_rarity(current_pity)
        stats[rarity] += 1
        if pity_hit:
            pity_triggers += 1
        if rarity in ("SR", "SSR"):
            current_pity = 0
        else:
            current_pity += 1
            max_pity = max(max_pity, current_pity)

    lines = [f"【模拟抽卡 x{count}】"]
    for r in ("SSR", "SR", "R", "N"):
        pct = stats[r] / count * 100
        lines.append(f"  {r}: {stats[r]} ({pct:.1f}%)")
    lines.append(f"保底触发: {pity_triggers} 次")
    lines.append(f"最大连续非SR: {max_pity}")

    yield event.plain_result("\n".join(lines))


async def handle_admin_test_intimacy(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 测试亲密度 @某人 <数值>`` — 管理员设置目标亲密度"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    tid = parse_at_target(event)

    if not ctx.config.is_admin(uid):
        yield event.plain_result(f"{nick}，你没有权限执行此操作~")
        return
    if not tid:
        yield event.plain_result("请@目标用户，如：老婆 测试亲密度 @某人 50")
        return

    msg = (event.message_str or "").strip()
    import re
    numbers = re.findall(r"\d+", msg)
    value = int(numbers[-1]) if numbers else 0

    from ..storage.stores import OwnershipStore
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    primary = ownership_store.get_primary(tid, ownerships)
    if not primary:
        yield event.plain_result("目标用户没有老婆~")
        return

    primary.intimacy = max(0, min(value, ctx.config.intimacy_max))
    ownership_store.save_all(ownerships)

    target_nick = tid
    yield event.plain_result(f"已将 {target_nick} 的亲密度设置为 {primary.intimacy}")


async def handle_admin_test_coins(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 测试币 @某人 <数值>`` — 管理员设置目标老婆币余额"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)
    tid = parse_at_target(event)

    if not ctx.config.is_admin(uid):
        yield event.plain_result(f"{nick}，你没有权限执行此操作~")
        return
    if not tid:
        yield event.plain_result("请@目标用户，如：老婆 测试币 @某人 999")
        return

    msg = (event.message_str or "").strip()
    import re
    numbers = re.findall(r"\d+", msg)
    value = int(numbers[-1]) if numbers else 0

    from ..storage.stores import ProfileStore
    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    target = profiles.get(tid)
    if not target:
        yield event.plain_result("目标用户没有老婆数据~")
        return

    target.coins = max(0, value)
    profile_store.save_all(profiles)

    target_nick = target.nick or tid
    yield event.plain_result(f"已将 {target_nick} 的老婆币设置为 {target.coins}")
