"""图片处理工具：纯函数，不依赖 astrbot 框架，便于本地单测。

图床约定：图片文件名形如 ``进击的巨人!三笠.jpg``，``!`` 前为作品来源，
后为角色名；不含 ``!`` 时视为仅有角色名。

需要构建 astrbot 消息组件的部分见 :mod:`app.api.messaging`。
"""

from __future__ import annotations

import os
from typing import Optional

__all__ = [
    "parse_wife_name",
    "build_image_url",
    "build_wife_intro_text",
    "is_path_within_dir",
]


def parse_wife_name(img: str) -> "tuple[str, Optional[str]]":
    """从图片标识解析出 ``(角色名, 作品来源)``，无来源时来源为 ``None``

    图片标识可能携带路径前缀（远程列表或本地缓存），仅取文件名部分。
    """
    name = os.path.splitext(img)[0].split("/")[-1]
    if "!" in name:
        source, chara = name.split("!", 1)
        return chara, source
    return name, None


def build_image_url(base_url: str, img: str) -> str:
    """根据图床基础 URL 与图片标识拼接完整 URL"""
    return base_url.rstrip("/") + "/" + img.lstrip("/")


def build_wife_intro_text(img: str, prefix: str, suffix: str) -> str:
    """构建「老婆介绍」文案：``{prefix}来自《{source}》的{chara}{suffix}``

    无作品来源时省略作品部分。``prefix``/``suffix`` 用于自定义主语与收尾。
    """
    chara, source = parse_wife_name(img)
    if source:
        return f"{prefix}来自《{source}》的{chara}{suffix}"
    return f"{prefix}{chara}{suffix}"


def is_path_within_dir(path: str, base: str) -> bool:
    """校验 ``path``（相对于 ``base``）是否严格位于 ``base`` 目录之内（防逃逸）

    使用绝对路径的公共前缀判断，``path`` 不存在也返回 ``True``（仅做词法校验）。
    """
    abs_base = os.path.abspath(base)
    abs_path = os.path.abspath(os.path.join(abs_base, path))
    return os.path.commonpath([abs_base, abs_path]) == abs_base
