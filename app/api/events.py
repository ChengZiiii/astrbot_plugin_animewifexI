"""AstrMessageEvent 工具：目标解析、发送者信息提取等。

封装对 astrbot 内部结构的访问，便于：

* 命令层不直接操作 ``event.message_obj``；
* 单元测试可 mock 这一层而不必构造完整的 AstrMessageEvent。
"""

from __future__ import annotations

from typing import Optional

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import At

__all__ = [
    "get_group_id",
    "get_sender_uid",
    "get_sender_nick",
    "get_self_id",
    "parse_at_target",
    "parse_target_by_text",
]


def get_group_id(event: AstrMessageEvent) -> Optional[str]:
    """获取群 ID（非群聊事件返回 None）"""
    if not event.message_obj or not hasattr(event.message_obj, "group_id"):
        return None
    gid = event.message_obj.group_id
    return str(gid) if gid is not None else None


def get_sender_uid(event: AstrMessageEvent) -> str:
    """获取发送者用户 ID"""
    return str(event.get_sender_id())


def get_sender_nick(event: AstrMessageEvent) -> str:
    """获取发送者昵称（可能为空）"""
    return event.get_sender_name() or ""


def get_self_id(event: AstrMessageEvent) -> str:
    """获取机器人自身的用户 ID"""
    return str(event.get_self_id())


def parse_at_target(event: AstrMessageEvent) -> Optional[str]:
    """解析消息中的 @目标用户

    跳过所有指向机器人自身的 At，返回第一个有效的目标用户 ID；
    未找到时返回 ``None``。
    """
    if not event.message_obj or not hasattr(event.message_obj, "message"):
        return None
    self_id = get_self_id(event)
    for comp in event.message_obj.message:
        if isinstance(comp, At) and str(comp.qq) != self_id:
            return str(comp.qq)
    return None


def parse_target_by_text(
    event: AstrMessageEvent, command_prefix: str, match_owner: "callable"
) -> Optional[str]:
    """从纯文本昵称解析目标用户 ID

    用于"牛老婆 <昵称>"/"查老婆 <昵称>"这类不带 @的命令。
    ``match_owner`` 接收昵称字符串，返回对应的 uid（由命令层注入查询回调）。
    """
    msg = event.message_str.strip()
    if not msg.startswith(command_prefix):
        return None
    parts = msg[len(command_prefix):].strip().split(maxsplit=0)
    if not parts or not parts[0]:
        return None
    return match_owner(parts[0])
