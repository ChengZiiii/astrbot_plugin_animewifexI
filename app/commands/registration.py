"""命令注册：组装当前所有可用命令到 :class:`CommandRegistry`。"""

from __future__ import annotations

from .admin import (
    handle_admin_reset_draw,
    handle_admin_reset_group,
    handle_admin_test_coins,
    handle_admin_test_draw,
    handle_admin_test_intimacy,
    handle_help,
    handle_reset_change,
    handle_reset_ntr,
    handle_switch_ntr,
)
from .change import handle_change
from .context import CommandContext
from .draw import handle_draw, handle_draw_ten
from .economy import (
    handle_backpack,
    handle_buy,
    handle_checkin,
    handle_quest,
    handle_shop,
)
from .grouped_stubs import (
    NOT_IMPLEMENTED_SUBCOMMANDS,
    make_not_implemented_handler,
)
from .intimacy import handle_chat, handle_date, handle_gift, handle_pet
from .leaderboard import handle_leaderboard
from .marry import handle_lock, handle_unlock
from .ntr import handle_ntr
from .panel import handle_collection, handle_panel
from .pk import handle_pk
from .registry import CommandRegistry
from .revenge import handle_revenge
from .swap import (
    handle_swap_accept,
    handle_swap_reject,
    handle_swap_request,
    handle_swap_view,
)
from .view import handle_view
from .work import handle_work

__all__ = ["build_registry"]


def build_registry() -> CommandRegistry:
    """构造当前完整命令注册表。"""
    registry = CommandRegistry()

    # ---------- 旧扁平命令 ----------
    registry.register_legacy("老婆帮助", handle_help)
    registry.register_legacy("抽老婆", handle_draw)
    registry.register_legacy("查老婆", handle_view)
    registry.register_legacy("牛老婆", handle_ntr)
    registry.register_legacy("重置牛", handle_reset_ntr)
    registry.register_legacy("换老婆", handle_change)
    registry.register_legacy("重置换", handle_reset_change)
    registry.register_legacy("交换老婆", handle_swap_request)
    registry.register_legacy("同意交换", handle_swap_accept)
    registry.register_legacy("拒绝交换", handle_swap_reject)
    registry.register_legacy("查看交换请求", handle_swap_view)

    # NTR 开关：兼容大小写两种写法
    registry.register_legacy("切换ntr开关状态", handle_switch_ntr)
    registry.register_legacy("切换NTR开关状态", handle_switch_ntr)

    # ---------- 分组命令：互动 / 排行 ----------
    registry.register_grouped("帮助", handle_help)
    registry.register_grouped("排行", handle_leaderboard)
    registry.register_grouped("复仇", handle_revenge)
    registry.register_grouped("摸头", handle_pet)
    registry.register_grouped("送礼", handle_gift)
    registry.register_grouped("对话", handle_chat)
    registry.register_grouped("约会", handle_date)

    # ---------- 分组命令：经济 / 道具 / 抽卡 ----------
    registry.register_grouped("签到", handle_checkin)
    registry.register_grouped("任务", handle_quest)
    registry.register_grouped("商城", handle_shop)
    registry.register_grouped("购买", handle_buy)
    registry.register_grouped("背包", handle_backpack)
    registry.register_grouped("十连", handle_draw_ten)

    # ---------- 分组命令：锁定 / PK / 图鉴 / 面板 ----------
    registry.register_grouped("锁定", handle_lock)
    registry.register_grouped("解锁", handle_unlock)
    registry.register_grouped("pk", handle_pk)
    registry.register_grouped("PK", handle_pk)
    registry.register_grouped("图鉴", handle_collection)
    registry.register_grouped("面板", handle_panel)

    # ---------- 分组命令：打工 ----------
    registry.register_grouped("打工", handle_work)

    # ---------- 管理员命令 ----------
    registry.register_grouped("重置本群", handle_admin_reset_group)
    registry.register_grouped("重置抽卡", handle_admin_reset_draw)
    registry.register_grouped("测试抽卡", handle_admin_test_draw)
    registry.register_grouped("测试亲密度", handle_admin_test_intimacy)
    registry.register_grouped("测试币", handle_admin_test_coins)

    # ---------- 当前仍未开放的占位子命令 ----------
    for sub in NOT_IMPLEMENTED_SUBCOMMANDS:
        registry.register_grouped(sub, make_not_implemented_handler(sub))

    return registry
