"""命令注册：组装所有命令处理器到 :class:`CommandRegistry`。

Phase 1 注册：

* 12 个旧扁平命令（v2.x 兼容）；
* ``老婆帮助`` 的两种触发形式（旧版无空格 + 新版带空格）；
* Phase 2/3 占位子命令（``老婆 列表`` 等）统一返回"未开放"提示。
"""

from __future__ import annotations

from .admin import handle_help, handle_reset_change, handle_reset_ntr, handle_switch_ntr
from .change import handle_change
from .context import CommandContext
from .draw import handle_draw
from .grouped_stubs import (
    NOT_IMPLEMENTED_SUBCOMMANDS,
    make_not_implemented_handler,
)
from .ntr import handle_ntr
from .registry import CommandRegistry
from .swap import (
    handle_swap_accept,
    handle_swap_reject,
    handle_swap_request,
    handle_swap_view,
)
from .view import handle_view

__all__ = ["build_registry", "apply_legacy_aliases"]


def build_registry() -> CommandRegistry:
    """构造 Phase 1 完整命令注册表"""
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

    # ---------- Phase 2/3 分组命令占位 ----------
    # 也支持 ``老婆 帮助`` 作为新版入口
    registry.register_grouped("帮助", handle_help)
    for sub in NOT_IMPLEMENTED_SUBCOMMANDS:
        registry.register_grouped(sub, make_not_implemented_handler(sub))

    return registry
