"""管理员 + 帮助命令处理器。"""

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
from .context import CommandContext

__all__ = [
    "handle_switch_ntr",
    "handle_help",
    "build_help_text",
    "handle_admin_reset_group",
    "handle_admin_reset_draw",
    "handle_admin_test_draw",
    "handle_admin_test_intimacy",
    "handle_admin_test_coins",
]


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
    """生成当前实现功能对应的帮助文本。"""
    return """
【基础命令】
• 老婆帮助 / 老婆 帮助 - 查看完整帮助
• 抽老婆 - 抽取新老婆（每日1次免费，之后消耗单抽券）
• 老婆 十连 - 十连抽卡（消耗十连券，9折优惠）
• 查老婆 [@用户] [页码] - 查看老婆列表（支持翻页，每页10个）
• 老婆 列表 [页码] / 老婆 查 [@用户] [页码] - `查老婆` 的分组入口
• 老婆规则：列表里带 `👑` 的就是主老婆；很多默认操作会优先使用主老婆
• 新手建议：先 `抽老婆` -> `查老婆` -> 有多位老婆后用 `老婆 切换 <编号>` 设定主老婆

【互动养成】
• 老婆 摸头 [编号] - 消耗老婆币增加亲密度；不写编号默认主老婆
• 老婆 送礼 [编号] - 高消耗高加成亲密度；不写编号默认主老婆
• 老婆 对话 [编号] - 冷却后可增加亲密度并获得老婆币；不写编号默认主老婆
• 老婆 约会 [编号] - 冷却后可消耗老婆币换取更多亲密度；不写编号默认主老婆
• 老婆 打工 [编号] [加班|远征] - 派老婆打工赚钱；可同时派多位（上限3位）
• 老婆 打工 中断 [编号] - 中断老婆的打工（奖励没收，启动费不退）
• 老婆 打工 合约 [加班|远征] - 预约下一次同模式打工收益提升
• 老婆 打工 搭档 @用户 - 绑定今日打工搭档，双方都打工时额外加成

【经济 / 道具】
• 老婆 签到 - 每日领取老婆币（含连续签到奖励）
• 老婆 任务 - 查看每日任务进度（完成后自动领取奖励）
• 新手引导任务完成后，会自动切换到标准每日任务
• 老婆 商城 - 查看可购买道具（含单抽券/十连券/锁定卡等）
• 老婆 购买 <道具> [数量] - 购买道具
• 老婆 背包 - 查看已持有道具

【对抗 / 社交】
• 牛老婆 [@用户] [编号] - 有概率抢走别人的老婆（不指定编号随机牛）
• 老婆 复仇 [@用户] - 在被牛24小时内复仇，成功率翻倍
• 交换老婆 [@用户] - 向别人发起老婆交换请求
• 同意交换 [@发起者] - 同意交换请求
• 拒绝交换 [@发起者] - 拒绝交换请求
• 查看交换请求 - 查看当前的交换请求
• 老婆 PK @某人 - 双方主老婆对战

【信息 / 管理】
• 老婆 排行 [日|周|总] [牛|被牛|PK|收集]
• 老婆 锁定 <编号> - 限期锁定老婆7天（消耗锁定卡）
• 老婆 解锁 <编号> - 解锁老婆
• 老婆 切换 <编号> - 将指定编号的老婆设为主老婆
• 老婆 图鉴 - 查看收集进度
• 老婆 面板 - 查看个人面板
• 连续签到和每周宝箱会在 `签到` / `任务` / `面板` 中懒触发领取

【管理员命令】
• 切换ntr开关状态 - 开启/关闭NTR功能
• 老婆 重置本群 - 清空本群所有老婆数据（慎用！）
• 老婆 重置抽卡 [@某人] - 重置目标的今日抽卡状态并清理抽卡冷却
• 老婆 测试抽卡 [次数] - 模拟抽卡测试概率分布（不写入数据）
• 老婆 测试亲密度 @某人 <数值> - 设置目标亲密度
• 老婆 测试币 @某人 <数值> - 设置目标老婆币余额

━━━ 游戏规则 ━━━

【老婆属性】每个老婆抽到时会随机生成 ⚔️攻击 🛡️防御 ❤️血量 三项属性，决定 PK 战力。
  战力 = 攻击 + 防御 + 血量×0.5，再受亲密度/元素/打工状态加成。属性可在「查老婆」和「面板」中查看。

【打工风险】老婆出去打工时，被牛（NTR）的概率大幅提升！
  • 普通打工（4h）：被牛概率 ×1.5
  • 加班打工（2h）：被牛概率 ×2.0
  • 远征打工（8h）：被牛概率 ×2.5
  打工中的老婆 PK 战力也会扣减（普通-10%，加班-20%，远征-30%）。
  可以同时派多位老婆打工（默认上限3位），也可以用「老婆 打工 中断」召回（但奖励没收）。

【保护机制】
  • 锁定卡：锁定老婆7天，锁定期间无法被牛，但不能打工、不能提升亲密度（消耗锁定卡）
  • 保护符：背包中有保护符时，被牛概率 ×0.3（一次性消耗）
  • 新手保护：新抽到的老婆在保护期内被牛概率大幅降低

【PK 机制】双方主老婆对战，战力受属性/亲密度/元素克制/打工状态影响。
  胜者获得老婆币奖励和排名积分，败者扣分。每天有 PK 次数上限和同对手冷却。

【NTR 机制】牛老婆时，系统综合计算成功率：基础概率 × 锁定/保护/打工/新手等系数。
  成功则老婆转移，失败也可能消耗尝试次数。被牛后24小时内可复仇（成功率翻倍）。

💡 提示：老婆编号以「查老婆」/「老婆 面板」中的序号为准。
💡 提示：`👑` = 主老婆；可用 `老婆 切换 <编号>` 手动切换默认互动/出战对象。
💡 提示：不写编号时，摸头 / 送礼 / 对话 / 约会 / PK / 打工 默认都使用主老婆。
💡 提示：打工中的老婆更危险！群友们可能趁虚而入……
💡 提示：部分命令有每日使用次数限制、冷却时间与周奖励懒触发。
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

    # Also clear in-memory and global per-group state that lives outside group_dir.
    ctx.cooldown_service._table.pop(gid, None)
    ctx.ownership_service.set_ntr_enabled(gid, True)

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

    # 清除今日抽卡日期（Phase 1 字段）
    target.last_draw_date = ""
    # H3: 清除 Phase 3 抽卡计数字段
    target.today_draw_date = ""
    target.today_draws = 0
    target.today_free_draws = 0
    profile_store.save_all(profiles)

    # 清除主老婆记录（否则 draw_or_get_primary 仍会返回旧老婆）
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    OwnershipStore.clear_primary_for_user(ownerships, tid)
    ownership_store.save_all(ownerships)

    ctx.cooldown_service.reset(gid, tid, "draw")

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
