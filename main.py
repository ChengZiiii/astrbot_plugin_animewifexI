"""AstrBot 插件入口。

AstrBot 通过 ``main.py`` 加载插件，会用 ``cls.__module__`` 在 ``star_map`` 中
匹配插件元数据。本文件的模块路径是 ``data.plugins.astrbot_plugin_animewifexI.main``，
但 ``WifePlugin`` 类定义在 ``app/plugin.py``（作为顶层 ``app.plugin`` 模块加载），
``cls.__module__`` 是 ``"app.plugin"`` —— 两者不匹配会导致 AstrBot 跳过实例化
与 handler 绑定。

所以导入后必须把 ``star_map`` / ``star_handlers_registry`` 中所有 ``"app.plugin"``
键改写为当前模块路径，让 AstrBot 能正确识别。
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

# 把 star_map / star_handlers_registry 中的 "app.plugin" 改写为当前模块路径，
# 让 AstrBot 能识别 WifePlugin
_THIS_MODULE = __name__
try:
    from astrbot.core.star import star_map
    from astrbot.core.star.register.star_handler import (
        star_handlers_registry as _handlers_reg,
    )

    WifePlugin.__module__ = _THIS_MODULE

    _md = star_map.pop("app.plugin", None)
    if _md is not None:
        _md.module_path = _THIS_MODULE
        star_map[_THIS_MODULE] = _md

    for _h in list(_handlers_reg._handlers):
        if _h.handler_module_path == "app.plugin":
            _old_full = _h.handler_full_name
            _h.handler_module_path = _THIS_MODULE
            _h.handler_full_name = f"{_THIS_MODULE}_{_h.handler_name}"
            _handlers_reg.star_handlers_map.pop(_old_full, None)
            _handlers_reg.star_handlers_map[_h.handler_full_name] = _h
except ImportError:
    # 测试环境无 astrbot，跳过改写
    pass

__all__ = ["WifePlugin"]
