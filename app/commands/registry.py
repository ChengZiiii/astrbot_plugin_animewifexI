"""双轨命令注册表 + 统一 dispatch 入口。

设计：

* ``LEGACY_COMMANDS`` ：旧扁平命令（``抽老婆``/``查老婆``/...）；
* ``GROUPED_COMMANDS`` ：分组命令（``老婆 帮助``/``老婆 排行``/...）；
* 命令名按长度降序匹配，避免短命令截胡长命令（与 v2.x 一致）；
* 保留少量未开放分组子命令，占位时统一返回明确提示。
"""

from __future__ import annotations

from typing import AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from astrbot.api.event import AstrMessageEvent

from .context import CommandContext

__all__ = [
    "CommandHandler",
    "CommandRegistry",
    "DispatchResult",
]

CommandHandler = Callable[[AstrMessageEvent, CommandContext], AsyncGenerator]


class DispatchResult:
    """dispatch 返回值：用于测试断言"""

    def __init__(self, name: str, handler: CommandHandler):
        self.name = name
        self.handler = handler

    def __repr__(self) -> str:
        return f"DispatchResult({self.name!r})"


class CommandRegistry:
    """双轨命令注册表"""

    def __init__(self):
        self._legacy: Dict[str, CommandHandler] = {}
        self._grouped: Dict[str, CommandHandler] = {}
        # 缓存排序后的命令名，避免每次 dispatch 重排
        self._legacy_sorted: List[str] = []
        self._grouped_sorted: List[str] = []
        self._dirty = False

    # ---------- 注册 ----------

    def register_legacy(self, name: str, handler: CommandHandler) -> None:
        """注册一个旧扁平命令（``name`` 不能含空格）"""
        if not name:
            raise ValueError("命令名不能为空")
        self._legacy[name] = handler
        self._dirty = True

    def register_grouped(self, subcommand: str, handler: CommandHandler) -> None:
        """注册一个分组子命令（如 ``列表`` → ``老婆 列表``）"""
        if not subcommand:
            raise ValueError("子命令名不能为空")
        self._grouped[subcommand] = handler
        self._dirty = True

    # ---------- 查询 ----------

    @property
    def legacy_commands(self) -> Dict[str, CommandHandler]:
        return dict(self._legacy)

    @property
    def grouped_commands(self) -> Dict[str, CommandHandler]:
        return dict(self._grouped)

    def all_command_names(self) -> List[str]:
        """所有已注册命令名（含 ``老婆 xxx`` 形式），用于帮助列表"""
        names = list(self._legacy.keys())
        for sub in self._grouped.keys():
            names.append(f"老婆 {sub}")
        return sorted(names, key=len, reverse=True)

    # ---------- 解析 ----------

    def _rebuild_cache(self) -> None:
        """重建排序缓存（按长度降序）"""
        self._legacy_sorted = sorted(self._legacy.keys(), key=len, reverse=True)
        self._grouped_sorted = sorted(self._grouped.keys(), key=len, reverse=True)
        self._dirty = False

    def parse(self, text: str) -> "Optional[DispatchResult]":
        """纯解析：根据文本返回匹配的 DispatchResult（不执行）

        优先匹配旧扁平命令；若文本以 ``老婆`` 开头再尝试分组命令。
        返回 ``None`` 表示无匹配。
        """
        if self._dirty:
            self._rebuild_cache()

        stripped = text.strip()
        if not stripped:
            return None

        # 1. 旧扁平命令（按长度降序匹配）
        for name in self._legacy_sorted:
            if stripped.startswith(name):
                return DispatchResult(name, self._legacy[name])

        # 2. 分组命令：``老婆 <subcommand> [args]``
        #    注意要排除"老婆帮助"这种已注册的旧扁平命令（已在上一步匹配）
        if stripped.startswith("老婆"):
            rest = stripped[len("老婆"):].lstrip()
            # rest 可能为空（"老婆" 单独）或包含子命令
            for sub in self._grouped_sorted:
                # 子命令应作为 rest 的前缀（按词）
                if rest == sub or rest.startswith(sub + " ") or rest.startswith(sub):
                    return DispatchResult(f"老婆 {sub}", self._grouped[sub])

        return None

    async def dispatch(
        self, event: AstrMessageEvent, ctx: CommandContext
    ) -> "Optional[DispatchResult]":
        """解析 + 执行命令，返回 DispatchResult（已执行）；无匹配返回 None

        ``event.message_str`` 作为命令文本来源。调用方负责 ``async for``
        命令处理器的输出来发送消息。
        """
        text = event.message_str or ""
        result = self.parse(text)
        if result is None:
            return None
        return result
