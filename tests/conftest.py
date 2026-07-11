"""pytest 公共夹具：临时 Paths、PluginConfig、GroupLocks、Mock WifeService 等。

设计：所有测试夹具使用 ``tmp_path`` 隔离文件系统，不污染 AstrBot 运行环境。
纯逻辑模块（utils/storage/models/services 大部分）不依赖 astrbot，可直接测试；
``app.api.*`` 的薄封装层依赖 astrbot，本地用 ``tests/_stub_astrbot.py`` 注入桩。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List, Optional

import pytest

# ---------- 注入 astrbot 桩（让 app.api.* 能 import） ----------

_STUB_MODULES = {
    "astrbot": "astrbot",
    "astrbot.api": "astrbot.api",
    "astrbot.api.message_components": "astrbot.api.message_components",
    "astrbot.api.event": "astrbot.api.event",
    "astrbot.api.event.filter": "astrbot.api.event.filter",
    "astrbot.api.star": "astrbot.api.star",
}


def _install_astrbot_stub() -> None:
    """注入最小可用的 astrbot 桩模块

    只覆盖 app.api.events / app.api.messaging / app.plugin 用到的属性，
    不实现完整框架（生产环境由真实 astrbot 提供）。
    """
    import types
    from typing import Any

    if "astrbot" in sys.modules:
        return  # 真 astrbot 已加载，跳过桩

    # astrbot.api.logger
    api_mod = types.ModuleType("astrbot.api")
    import logging
    api_logger = logging.getLogger("astrbot_test")
    api_mod.logger = api_logger
    api_mod.AstrBotConfig = dict  # type: ignore[attr-defined]

    # astrbot.api.message_components
    mc_mod = types.ModuleType("astrbot.api.message_components")

    class _At:
        def __init__(self, qq: str = "", name: str = ""):
            self.qq = qq
            self.name = name

    class _Plain:
        def __init__(self, text: str = ""):
            self.text = text

        def __repr__(self) -> str:
            return f"Plain({self.text!r})"

    class _Image:
        def __init__(self, url: str = "", file_path: str = ""):
            self.url = url
            self.file_path = file_path

        @classmethod
        def fromURL(cls, url: str) -> "_Image":
            return cls(url=url)

        @classmethod
        def fromFileSystem(cls, path: str) -> "_Image":
            return cls(file_path=path)

    class _Node:
        """合并转发节点桩（OneBot v11 / NapCat 节点结构）"""

        def __init__(self, uin: int = 0, name: str = "", content: list = None):
            self.uin = int(uin or 0)
            self.name = str(name or "")
            self.content = list(content) if content is not None else []

        def __repr__(self) -> str:
            return f"Node(uin={self.uin!r}, name={self.name!r}, content={self.content!r})"

    class _Nodes:
        """合并转发消息链组件"""

        def __init__(self, nodes: list = None):
            self.nodes = list(nodes) if nodes is not None else []

        def __repr__(self) -> str:
            return f"Nodes(nodes={self.nodes!r})"

    mc_mod.At = _At
    mc_mod.Plain = _Plain
    mc_mod.Image = _Image
    mc_mod.Node = _Node
    mc_mod.Nodes = _Nodes

    # astrbot.api.event
    ev_mod = types.ModuleType("astrbot.api.event")

    class _EventMessageType:
        GROUP_MESSAGE = "group_message"

    class _FilterNamespace:
        EventMessageType = _EventMessageType

        @staticmethod
        def event_message_type(msg_type):
            def deco(func):
                return func
            return deco

    ev_mod.filter = _FilterNamespace
    ev_mod.AstrMessageEvent = object  # type: ignore[attr-defined]

    # astrbot.api.star
    star_mod = types.ModuleType("astrbot.api.star")

    class _Star:
        """Star 基类桩：接受 context 参数（与真实 AstrBot Star 签名一致）"""

        def __init__(self, context: Any = None):
            self.context = context

        async def terminate(self):
            pass

    class _Context:
        """Context 桩：默认 get_config 返回空 dict"""

        def __init__(self, config: dict = None):
            self._config = config or {}

        def get_config(self) -> dict:
            return self._config

    class _StarTools:
        @staticmethod
        def get_data_dir(name: str) -> str:
            # 测试默认返回 tmp 目录下的子目录，由具体测试覆盖
            import tempfile
            import os
            return tempfile.mkdtemp(prefix=f"{name}_test_")

    star_mod.Star = _Star
    star_mod.Context = _Context
    star_mod.StarTools = _StarTools

    # astrbot 顶层
    top = types.ModuleType("astrbot")
    top.api = api_mod  # type: ignore[attr-defined]

    sys.modules["astrbot"] = top
    sys.modules["astrbot.api"] = api_mod
    sys.modules["astrbot.api.message_components"] = mc_mod
    sys.modules["astrbot.api.event"] = ev_mod
    sys.modules["astrbot.api.event.filter"] = ev_mod.filter
    sys.modules["astrbot.api.star"] = star_mod


_install_astrbot_stub()


# ---------- 公共夹具 ----------


@pytest.fixture
def tmp_paths(tmp_path: Path):
    """临时 Paths 实例，自动 ensure_dirs"""
    from app.storage.paths import Paths

    paths = Paths(str(tmp_path))
    paths.ensure_dirs()
    return paths


@pytest.fixture
def config():
    """默认 PluginConfig（全默认值，daily_free_draws=0 表示无限制）"""
    from app.services.plugin_config import PluginConfig

    return PluginConfig(daily_free_draws=0, newbie_ntr_protection_days=0)


@pytest.fixture
def locks():
    from app.storage.locks import GroupLocks

    return GroupLocks()


@pytest.fixture
def mock_wife_service():
    """内存版 WifeService，不触网，返回预设图片列表"""
    from app.services.wife_service import WifeService
    from app.storage.paths import Paths
    from app.services.plugin_config import PluginConfig

    class _MockWifeService:
        def __init__(self):
            self._images: List[str] = [
                "进击的巨人!三笠.jpg",
                "Re:从零开始的异世界生活!雷姆.jpg",
                "鬼灭之刃!灶门祢豆子.jpg",
                "某科学的超电磁炮!御坂美琴.jpg",
                "Fate/stay night!Saber.jpg",
            ]
            self._call_count = 0

        def set_images(self, images: List[str]) -> None:
            self._images = list(images)

        async def fetch_image(self) -> Optional[str]:
            import random
            self._call_count += 1
            if not self._images:
                return None
            return random.choice(self._images)

    return _MockWifeService()


@pytest.fixture
def ownership_service(tmp_paths, config, locks, mock_wife_service):
    """装配好的 OwnershipService 实例"""
    from app.services.ownership_service import OwnershipService

    return OwnershipService(
        paths=tmp_paths,
        config=config,
        locks=locks,
        wife_service=mock_wife_service,
    )


@pytest.fixture
def lifespan_service(tmp_paths, config, locks):
    """Phase 6: 寿命系统服务（测试用 fixture）"""
    from app.services.lifespan_service import LifespanService

    return LifespanService(
        paths=tmp_paths,
        config=config,
        locks=locks,
    )


@pytest.fixture
def event_loop_policy():
    """pytest-asyncio 兼容：使用默认事件循环策略"""
    return asyncio.DefaultEventLoopPolicy()
