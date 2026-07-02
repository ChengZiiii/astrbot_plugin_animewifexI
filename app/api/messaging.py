"""消息链构建：封装 astrbot 消息组件的拼装。

集中管理 ``Plain`` + ``Image`` + ``At`` 的组合，命令层只声明意图，
不关心底层消息组件如何拼装。
"""

from __future__ import annotations

from typing import List, Optional

from astrbot.api.message_components import At, Image, Plain

from ..utils.image import build_image_url, is_path_within_dir

__all__ = [
    "build_text_chain",
    "build_text_image_chain",
    "build_multi_image_chain",
    "build_at_text_chain",
    "build_image_component",
]


def build_image_component(img_dir: str, base_url: str, img: str) -> Optional[Image]:
    """根据图片标识构建图片消息组件（本地优先，回退到 URL），失败返回 None

    本地读取前校验路径未逃逸出图库目录，避免被劫持的图片列表读取任意文件。
    """
    try:
        if not is_path_within_dir(img, img_dir):
            return Image.fromURL(build_image_url(base_url, img))
        import os
        abs_base = os.path.abspath(img_dir)
        abs_path = os.path.abspath(os.path.join(abs_base, img))
        if os.path.exists(abs_path):
            return Image.fromFileSystem(abs_path)
        return Image.fromURL(build_image_url(base_url, img))
    except Exception:
        return None


def build_text_chain(text: str) -> List:
    """纯文本消息链"""
    return [Plain(text)]


def build_text_image_chain(
    text: str, img: str, img_dir: str, base_url: str
) -> List:
    """「文字 + 图片」消息链，图片组件构建失败时仅保留文字"""
    chain = [Plain(text)]
    img_comp = build_image_component(img_dir, base_url, img)
    if img_comp is not None:
        chain.append(img_comp)
    return chain


def build_multi_image_chain(
    text: str, imgs: List[str], img_dir: str, base_url: str
) -> List:
    """「文字 + 多张图片」消息链（十连抽卡用）"""
    chain = [Plain(text)]
    for img in imgs:
        img_comp = build_image_component(img_dir, base_url, img)
        if img_comp is not None:
            chain.append(img_comp)
    return chain


def build_at_text_chain(at_qq: str, text_before: str = "", text_after: str = "") -> List:
    """``[Plain?] + At + [Plain?]`` 消息链"""
    chain = []
    if text_before:
        chain.append(Plain(text_before))
    chain.append(At(qq=at_qq))
    if text_after:
        chain.append(Plain(text_after))
    return chain
