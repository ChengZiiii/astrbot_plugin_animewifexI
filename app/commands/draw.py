"""抽老婆命令处理器：单抽 + 十连。"""

from __future__ import annotations

from typing import AsyncGenerator, List

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id, get_sender_nick, get_sender_uid
from ..api.messaging import build_multi_image_chain, build_text_image_chain
from ..services.ownership_service import DrawResult
from ..utils.image import build_wife_intro_text
from .context import CommandContext

__all__ = ["handle_draw", "handle_draw_ten"]


def _format_draw_result(nick: str, result: DrawResult, index: int = 0) -> str:
    """格式化单次抽卡结果"""
    prefix = f"[{index}] " if index > 0 else ""
    intro = build_wife_intro_text(
        result.img,
        prefix=f"{prefix}{nick}，你抽到了",
        suffix="",
    )
    rarity_line = f" | {result.rarity_emoji} {result.rarity}"
    if result.pity_triggered:
        rarity_line += "（保底！）"
    if result.is_duplicate:
        rarity_line += f"（重复，+{result.duplicate_coins}币）"
    return intro + rarity_line


async def handle_draw(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``抽老婆``：单抽"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    result = await ctx.ownership_service.draw_or_get_primary(
        gid, uid, nick, ctx.today()
    )
    if not result.ok:
        if result.reason == "cooldown":
            remaining = ctx.cooldown_service.remaining(
                gid, uid, "draw", ctx.config.draw_cooldown
            )
            yield event.plain_result(
                f"{nick}，抽老婆冷却中，还需等待{remaining}秒~"
            )
        elif result.reason == "no_draws":
            yield event.plain_result(
                f"{nick}，今日免费次数已用完，请购买「单抽券」或「十连券」继续抽卡~\n"
                f"当前余额：{result.profile.coins} 币"
            )
        elif result.reason == "fetch_failed":
            yield event.plain_result("抱歉，老婆获取失败了，请稍后再试~")
        else:
            yield event.plain_result("抽卡失败，请稍后再试~")
        return

    if not result.is_new and result.reason == "no_draws":
        # 没有抽卡次数，展示已有老婆
        intro = build_wife_intro_text(
            result.img,
            prefix=f"{nick}，你当前的老婆是",
            suffix="",
        )
        yield event.plain_result(f"{intro}\n（今日免费次数已用完，购买抽卡券可继续抽卡）")
        return

    if not result.img:
        yield event.plain_result("抱歉，老婆获取失败了~")
        return

    text = _format_draw_result(nick, result)
    yield event.chain_result(
        build_text_image_chain(
            text,
            result.img,
            ctx.paths.img_dir,
            ctx.config.normalized_image_base_url,
        )
    )


async def handle_draw_ten(event: AstrMessageEvent, ctx: CommandContext) -> AsyncGenerator:
    """``十连``：十连抽卡（消耗十连券）"""
    gid = get_group_id(event)
    if not gid:
        return
    uid = get_sender_uid(event)
    nick = get_sender_nick(event)

    # 委托给 ownership_service.draw_ten（券检查+消耗在锁内完成）
    results = await ctx.ownership_service.draw_ten(gid, uid, nick, ctx.today())

    if not results:
        yield event.plain_result(
            f"{nick}，你没有十连券，去商城购买吧~\n"
            f"十连券价格：{ctx.config.shop_prices.get('draw_ticket_ten', 270)} 币（9折优惠）"
        )
        return

    # 格式化结果（文字部分）
    lines = [f"【{nick} 的十连抽卡】\n"]
    for i, r in enumerate(results, 1):
        lines.append(_format_draw_result(nick, r, i))

    # 统计
    rarities = {}
    for r in results:
        rarities[r.rarity] = rarities.get(r.rarity, 0) + 1
    summary = []
    for r in ("SSR", "SR", "R", "N"):
        if r in rarities:
            summary.append(f"{r}x{rarities[r]}")
    lines.append(f"\n统计：{' '.join(summary)}")

    # 收集所有图片（去重避免重复发送）
    imgs = []
    seen = set()
    for r in results:
        if r.img and r.img not in seen:
            imgs.append(r.img)
            seen.add(r.img)

    yield event.chain_result(
        build_multi_image_chain(
            "\n".join(lines),
            imgs,
            ctx.paths.img_dir,
            ctx.config.normalized_image_base_url,
        )
    )
