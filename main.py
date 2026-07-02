"""AstrBot 插件入口。

**关键设计**：``WifePlugin`` 必须在 ``main.py`` 里定义，``@filter.event_message_type``
装饰的 ``on_all_messages`` 方法也必须在本文件中。

原因：AstrBot reload 时会重新执行 ``main.py``，但 ``app.plugin`` 已被 Python
缓存在 ``sys.modules`` 不会重新执行 → 如果装饰器写在 ``app/plugin.py`` 里，
reload 时装饰器不重跑 → handler 不重新注册 → 插件失效。

业务装配逻辑放在 :mod:`app.plugin` 的 :class:`WifePluginCore` 里（便于单测），
本文件只负责 AstrBot 相关的装饰器与消息分发。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import EventMessageType

from .app.plugin import WifePluginCore

# AstrBot 常见 wake prefix：/ ! \ . 与全角版本
_WAKE_PREFIXES = ("/", "!", "\\", ".", "／", "！", "、", "。")


def _strip_wake_prefix(text: str) -> str:
    """去掉开头的 wake prefix（/ ! \\ . 等）和首尾空白，便于命令匹配"""
    while text[:1] in _WAKE_PREFIXES:
        text = text[1:].lstrip()
    return text.strip()


class WifePlugin(WifePluginCore):
    """AstrBot 入口类：继承业务基类 + 注册消息监听"""

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_all_messages(self, event: AstrMessageEvent):
        """群聊消息分发（仅群聊监听）"""
        if not event.message_obj or not hasattr(event.message_obj, "group_id"):
            return

        if self.plugin_config.need_prefix and not event.is_at_or_wake_command:
            return

        text = (event.message_str or "").strip()
        if not text:
            return

        # 兼容 AstrBot wake prefix（/ ! \ . 等）与首尾空白
        text = _strip_wake_prefix(text)
        if not text:
            return

        result = self.registry.parse(text)
        if result is None:
            return

        # 命中即拦截，阻止后续 LLM 流程
        event.stop_event()
        # 执行 handler 并转发所有 yield 的消息
        try:
            async for reply in result.handler(event, self.cmd_ctx):
                yield reply
        except Exception:
            logger.exception(f"执行命令 {result.name!r} 时出错")


__all__ = ["WifePlugin"]
