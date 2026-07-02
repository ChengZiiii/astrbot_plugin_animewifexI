"""抽老婆核心服务：图片获取（本地→缓存→网络→过期缓存兜底）。

并发模型：图片列表缓存读写不进入群锁（与单群业务无关），但单次调用内
串行执行；如未来出现并发抢图床压力，可在 :class:`WifeService` 内增加
进程级 ``asyncio.Lock``。

.. note::

    抽老婆命令的"是否当日已抽过、写入 ownership"等业务逻辑由
    :mod:`app.services.ownership_service` 负责，本类只负责"取一张图片标识"。
"""

from __future__ import annotations

import os
import random
import time
from typing import List, Optional

import aiohttp

try:
    from astrbot.api import logger as _logger
    _error = _logger.error
except Exception:  # pragma: no cover
    import logging
    _error = logging.getLogger("astrbot_plugin_animewifex").error

from ..storage.paths import Paths
from .plugin_config import PluginConfig

__all__ = ["WifeService"]


class WifeService:
    """抽老婆核心：取一张图片标识"""

    def __init__(self, paths: Paths, config: PluginConfig):
        self._paths = paths
        self._config = config
        # 测试时可注入自定义随机源
        self._rng = random.Random()

    def set_rng(self, rng: random.Random) -> None:
        """注入随机源（测试用）"""
        self._rng = rng

    async def fetch_image(self) -> Optional[str]:
        """获取一张老婆图片标识

        依次尝试：本地图库 → 有效缓存 → 网络列表 → 过期缓存兜底
        全部失败返回 ``None``（调用方决定提示文案）。
        """
        img = self._pick_from_local_dir()
        if img:
            return img

        cached_lines, cache_expired = self._load_cache()
        if not cache_expired and cached_lines:
            return self._rng.choice(cached_lines)

        img = await self._fetch_remote_list_and_cache()
        if img:
            return img

        if cached_lines:
            return self._rng.choice(cached_lines)
        return None

    # ---------- 内部 ----------

    def _pick_from_local_dir(self) -> Optional[str]:
        """本地图库随机选一张（过滤子目录与非文件条目）"""
        try:
            with os.scandir(self._paths.img_dir) as entries:
                local_imgs = [e.name for e in entries if e.is_file()]
            if local_imgs:
                return self._rng.choice(local_imgs)
        except OSError:
            pass
        return None

    def _load_cache(self) -> "tuple[List[str], bool]":
        """读取本地缓存列表，返回 ``(行列表, 是否已过期)``"""
        cache_file = self._paths.wife_list_cache_file
        if not os.path.exists(cache_file):
            return [], True
        try:
            cache_expired = (
                time.time() - os.path.getmtime(cache_file)
            ) >= 3600
            with open(cache_file, "r", encoding="utf-8") as f:
                lines = [
                    s for s in (line.strip() for line in f.read().splitlines()) if s
                ]
            return lines, cache_expired
        except (OSError, UnicodeDecodeError):
            return [], True

    async def _fetch_remote_list_and_cache(self) -> Optional[str]:
        """请求远程图片列表，成功则写缓存并返回随机一项"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self._config.image_list_url) as resp:
                    if resp.status != 200:
                        return None
                    text = await resp.text()
                    lines = [
                        s for s in (line.strip() for line in text.splitlines()) if s
                    ]
                    if not lines:
                        return None
                    # 缓存写入失败不影响本次结果
                    try:
                        with open(
                            self._paths.wife_list_cache_file, "w", encoding="utf-8"
                        ) as f:
                            f.write("\n".join(lines))
                    except OSError:
                        pass
                    return self._rng.choice(lines)
        except Exception:
            return None
