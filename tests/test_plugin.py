"""插件入口冒烟测试：验证 app.plugin.WifePlugin 能在 stub 环境下加载。

不测试完整生命周期（需要 AstrBot 运行时），仅验证：

* 模块导入无误；
* ``WifePlugin.__init__`` 在 mock context + 默认配置下能完成装配；
* ``registry.parse`` 入口在 CommandContext 上能正常解析关键命令。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from app.commands.context import CommandContext
from app.commands.registration import build_registry
from app.plugin import WifePlugin
from app.services.plugin_config import PluginConfig


class _MockContext:
    """最小化的 Context mock，仅提供 get_config()"""

    def __init__(self, config: Dict[str, Any]):
        self._config = config

    def get_config(self):
        return self._config


def test_plugin_imports():
    """模块能被 import（间接由本测试模块 import 验证）"""
    assert WifePlugin is not None


def test_plugin_init_with_default_config(tmp_path, monkeypatch):
    """插件 init 在 mock 环境下完成装配"""
    # StarTools.get_data_dir 默认返回 mkdtemp，覆盖为 tmp_path 子目录
    from astrbot.api.star import StarTools

    original = StarTools.get_data_dir

    def _mocked_get_data_dir(name):
        import os
        path = os.path.join(str(tmp_path), name)
        os.makedirs(path, exist_ok=True)
        return path

    monkeypatch.setattr(StarTools, "get_data_dir", staticmethod(_mocked_get_data_dir))

    # AstrBotConfig 是 dict-like，用空 dict 触发全部默认值
    raw_config: Dict[str, Any] = {}
    context = _MockContext({"timezone": "Asia/Shanghai"})

    plugin = WifePlugin(context, raw_config)

    # 验证装配
    assert plugin.paths is not None
    assert plugin.plugin_config is not None
    assert plugin.locks is not None
    assert plugin.wife_service is not None
    assert plugin.ownership_service is not None
    assert plugin.registry is not None
    assert plugin.cmd_ctx is not None
    # 注册了 12+ 个旧扁平命令
    assert len(plugin.registry.legacy_commands) >= 12

    # 清理后台任务
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(plugin.terminate())
    finally:
        loop.close()


def test_plugin_init_archive_legacy_data(tmp_path, monkeypatch):
    """启动时若存在 v2.x 旧数据，自动归档"""
    import json
    import os

    from astrbot.api.star import StarTools

    def _mocked_get_data_dir(name):
        path = os.path.join(str(tmp_path), name)
        os.makedirs(path, exist_ok=True)
        return path

    monkeypatch.setattr(StarTools, "get_data_dir", staticmethod(_mocked_get_data_dir))

    # 先模拟旧版数据
    plugin_root = _mocked_get_data_dir("astrbot_plugin_animewifex")
    legacy_config_dir = os.path.join(plugin_root, "config")
    os.makedirs(legacy_config_dir, exist_ok=True)
    with open(os.path.join(legacy_config_dir, "records.json"), "w", encoding="utf-8") as f:
        json.dump({"ntr": {}}, f)

    raw_config: Dict[str, Any] = {}
    context = _MockContext({})
    plugin = WifePlugin(context, raw_config)

    # config/ 应已被归档移走
    assert not os.path.exists(os.path.join(legacy_config_dir, "records.json"))
    # archive_v1 下应有归档目录
    archives = os.listdir(plugin.paths.archive_dir)
    assert len(archives) >= 1

    # 清理
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(plugin.terminate())
    finally:
        loop.close()


def test_plugin_parse_commands_via_context(tmp_path, monkeypatch):
    """plugin.cmd_ctx + registry 能解析关键命令"""
    from astrbot.api.star import StarTools

    def _mocked_get_data_dir(name):
        import os
        path = os.path.join(str(tmp_path), name)
        os.makedirs(path, exist_ok=True)
        return path

    monkeypatch.setattr(StarTools, "get_data_dir", staticmethod(_mocked_get_data_dir))

    raw_config: Dict[str, Any] = {}
    context = _MockContext({})
    plugin = WifePlugin(context, raw_config)

    # 关键命令都能解析
    for cmd in ["抽老婆", "查老婆", "牛老婆", "换老婆", "交换老婆",
                "同意交换", "拒绝交换", "查看交换请求", "重置牛", "重置换",
                "老婆帮助", "切换ntr开关状态"]:
        result = plugin.registry.parse(cmd)
        assert result is not None, f"command not parsed: {cmd}"

    # 清理
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(plugin.terminate())
    finally:
        loop.close()
