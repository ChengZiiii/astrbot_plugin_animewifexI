"""命令注册：组装所有命令处理器到 :class:`CommandRegistry`。

Phase 1 注册：

* 12 个旧扁平命令（v2.x 兼容）；
* ``老婆帮助`` 的两种触发形式（旧版无空格 + 新版带空格）；
* Phase 2/3 占位子命令（``老婆 列表`` 等）统一返回"未开放"提示。

Phase 2 注册：

* ``老婆 排行 [日|周|总] [牛|被牛|PK|收集]`` — 排行榜
* ``老婆 复仇 @x`` — 复仇
* ``老婆 摸头`` — 亲密度互动（摸头）
* ``老婆 送礼`` — 亲密度互动（送礼）

Phase 3 注册：

* ``老婆 签到`` — 每日签到
* ``老婆 任务`` — 每日任务
* ``老婆 商城`` — 商城列表
* ``老婆 购买 <道具>`` — 购买道具
* ``老婆 背包`` — 查看背包
* ``老婆 求婚 <编号>`` — 永久锁定老婆
* ``老婆 锁 <编号>`` — 限期锁定老婆
* ``老婆 解锁 <编号>`` — 解锁老婆
* ``老婆 PK @某人`` — 老婆 PK
* ``老婆 图鉴`` — 查看图鉴
* ``老婆 面板`` — 查看个人面板
"""

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
from .draw import handle_draw
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
from .intimacy import handle_gift, handle_pet
from .leaderboard import handle_leaderboard
from .marry import handle_lock, handle_propose, handle_unlock
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

__all__ = ["build_registry"]


def build_registry() -> CommandRegistry:
    """构造 Phase 3 完整命令注册表"""
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

    # ---------- Phase 2 分组命令 ----------
    registry.register_grouped("帮助", handle_help)
    registry.register_grouped("排行", handle_leaderboard)
    registry.register_grouped("复仇", handle_revenge)
    registry.register_grouped("摸头", handle_pet)
    registry.register_grouped("送礼", handle_gift)

    # ---------- Phase 3 分组命令 ----------
    registry.register_grouped("签到", handle_checkin)
    registry.register_grouped("任务", handle_quest)
    registry.register_grouped("商城", handle_shop)
    registry.register_grouped("购买", handle_buy)
    registry.register_grouped("背包", handle_backpack)

    # ---------- Phase 3: 求婚/锁定/PK/图鉴/面板 ----------
    registry.register_grouped("求婚", handle_propose)
    registry.register_grouped("锁", handle_lock)
    registry.register_grouped("解锁", handle_unlock)
    registry.register_grouped("PK", handle_pk)
    registry.register_grouped("图鉴", handle_collection)
    registry.register_grouped("面板", handle_panel)

    # ---------- 管理员命令 ----------
    registry.register_grouped("重置本群", handle_admin_reset_group)
    registry.register_grouped("重置抽卡", handle_admin_reset_draw)
    registry.register_grouped("测试抽卡", handle_admin_test_draw)
    registry.register_grouped("测试亲密度", handle_admin_test_intimacy)
    registry.register_grouped("测试币", handle_admin_test_coins)

    # ---------- Phase 2/3 剩余占位子命令 ----------
    for sub in NOT_IMPLEMENTED_SUBCOMMANDS:
        registry.register_grouped(sub, make_not_implemented_handler(sub))

    return registry
