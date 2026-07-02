"""AstrBot 插件入口：仅插件注册 + config 注入 + 委托给 :class:`app.plugin.WifePlugin`。

AstrBot 通过 ``main.py`` 加载插件，``Star`` 子类即插件实例。
所有业务逻辑在 :mod:`app.plugin` 中实现，本文件保持精简。
"""

from __future__ import annotations

import os
import sys

# AstrBot 加载插件时不会把插件目录加入 sys.path，导致 ``from app.xxx`` 失败。
# 这里在导入 app 之前先把插件目录注入 sys.path（若尚未存在）。
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from app.plugin import WifePlugin

__all__ = ["WifePlugin"]
