"""AstrBot 插件入口：仅插件注册 + config 注入 + 委托给 :class:`app.plugin.WifePlugin`。

AstrBot 通过 ``main.py`` 加载插件，``Star`` 子类即插件实例。
所有业务逻辑在 :mod:`app.plugin` 中实现，本文件保持精简。
"""

from __future__ import annotations

from app.plugin import WifePlugin

__all__ = ["WifePlugin"]
