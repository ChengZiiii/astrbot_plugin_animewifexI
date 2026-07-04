"""查老婆命令处理器。"""

from __future__ import annotations

import re
from typing import AsyncGenerator, Optional

from astrbot.api.event import AstrMessageEvent

from ..api.events import (
    get_group_id,
    get_sender_nick,
    get_sender_uid,
    parse_at_target,
)
from ..api.messaging import build_multi_image_chain
from ..storage.stores import OwnershipStore, WivesMasterStore
from .context import CommandContext

__all__ = ["handle_view", "find_uid_by_owner_nick"]

# 每页显示数量
PAGE_SIZE = 10


async def handle_view(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``查老婆 [@用户 | 昵称] [页码]``：查看自己或他人的老婆（分页）"""
    gid = get_group_id(event)
    if not gid:
        return

    # T33: 打工懒结算
    from .work import try_settle_work
    settle_msg = await try_settle_work(event, ctx)
    if settle_msg:
        yield event.plain_result(settle_msg)

    sender_uid = get_sender_uid(event)
    at_target = parse_at_target(event)
    target_uid, page = _resolve_target_and_page(event, ctx)
    if target_uid is None:
        yield event.plain_result("没有找到该昵称的群友老婆哦~")
        return

    target_profile = ctx.ownership_service.get_profile(gid, target_uid)
    owner = target_profile.nick or "未知用户"

    # 获取该用户所有老婆
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(target_uid, ownerships)

    if not my_wives:
        if target_uid == sender_uid or at_target is None:
            yield event.plain_result("没有发现老婆的踪迹，快去抽一个试试吧~")
        else:
            yield event.plain_result(f"{owner}今天还没有老婆哦~")
        return

    # 分页
    total = len(my_wives)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_wives = my_wives[start:end]

    # 加载老婆元数据
    wives_meta = WivesMasterStore(ctx.paths).load_all()

    # 格式化当前页老婆
    lines = [f"【{owner} 的老婆】共 {total} 位（第 {page}/{total_pages} 页）\n"]
    imgs = []

    # T24: 作恶值展示
    from ..utils.time import now_ts
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    if target_profile.evil_points_month != current_month:
        target_profile.evil_points = 0
    if target_profile.evil_points >= 5:
        lines.append("⚠️ 极度危险用户！被牛时补偿翻倍！\n")
    elif target_profile.evil_points >= 3:
        lines.append("⚠️ 危险用户！请注意防范！\n")
    seen_imgs = set()

    from ..services.ownership_service import OwnershipService
    for i, o in enumerate(page_wives, start + 1):
        wife = wives_meta.get(o.wid)
        if not wife:
            continue
        emoji = {"SSR": "✨", "SR": "🌟", "R": "⭐", "N": "·"}.get(wife.rarity, "·")
        name = wife.chara or wife.img
        lock_icon = " 🔒" if o.is_locked else ""
        primary_icon = " 👑" if o.is_primary else ""
        intimacy_str = OwnershipService.intimacy_level_emoji(o.intimacy)
        lines.append(f"{i}. {emoji} {name} (❤️{o.intimacy}{intimacy_str}){lock_icon}{primary_icon}")

        # 收集当前页图片（去重）
        if wife.img and wife.img not in seen_imgs:
            imgs.append(wife.img)
            seen_imgs.add(wife.img)

    # 翻页提示
    if total_pages > 1:
        hints = []
        if page > 1:
            hints.append(f"上一页：查老婆 {page - 1}")
        if page < total_pages:
            hints.append(f"下一页：查老婆 {page + 1}")
        lines.append(f"\n💡 {' | '.join(hints)}")

    text = "\n".join(lines)

    if imgs:
        yield event.chain_result(
            build_multi_image_chain(
                text,
                imgs,
                ctx.paths.img_dir,
                ctx.config.normalized_image_base_url,
            )
        )
    else:
        yield event.plain_result(text)


def _resolve_target_and_page(
    event: AstrMessageEvent, ctx: CommandContext
) -> tuple[Optional[str], int]:
    """解析目标用户和页码：@/昵称 + 页码数字"""
    at_target = parse_at_target(event)
    msg = (event.message_str or "").strip()

    # 提取页码（消息末尾的数字）
    page = 1
    page_match = re.search(r"\s(\d+)\s*$", msg)
    if page_match:
        try:
            page = int(page_match.group(1))
        except ValueError:
            pass

    # @目标
    if at_target:
        return at_target, page

    # 昵称匹配
    parts = msg.split(maxsplit=1)
    if len(parts) > 1:
        rest = parts[1].strip()
        # 去掉末尾页码
        rest_no_page = re.sub(r"\s+\d+\s*$", "", rest).strip()
        gid = get_group_id(event)
        if gid and rest_no_page:
            tid = find_uid_by_owner_nick(ctx, gid, rest_no_page)
            if tid:
                return tid, page

    return get_sender_uid(event), page


def find_uid_by_owner_nick(
    ctx: CommandContext, gid: str, nick: str
) -> Optional[str]:
    """根据用户档案的 nick 字段反查 uid（要求该 uid 当前持有主老婆）

    v2.x 的 ``wife.owner`` 字段在 v3.x 由 ``UserProfile.nick`` 等价承担。
    """
    from ..storage.stores import ProfileStore

    profile_store = ProfileStore(ctx.paths, gid)
    profiles = profile_store.load_all()
    for uid, profile in profiles.items():
        if profile.nick == nick:
            if ctx.ownership_service.get_primary_wid(gid, uid):
                return uid
    return None


def find_wid_by_index(
    ctx: CommandContext, gid: str, uid: str, msg: Optional[str]
) -> Optional[str]:
    """从消息中解析老婆编号（1-based），返回对应 wid。

    格式：``老婆 求婚 1`` 或 ``老婆 锁 2``
    """
    if not msg:
        return None
    # 取最后一个数字
    import re
    numbers = re.findall(r"\d+", msg)
    if not numbers:
        return None
    idx = int(numbers[-1]) - 1  # 转为 0-based

    from ..storage.stores import OwnershipStore
    ownership_store = OwnershipStore(ctx.paths, gid)
    ownerships = ownership_store.load_all()
    my_wives = ownership_store.list_by_user(uid, ownerships)
    if 0 <= idx < len(my_wives):
        return my_wives[idx].wid
    return None
