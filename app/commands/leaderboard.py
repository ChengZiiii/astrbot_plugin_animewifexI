"""排行榜命令处理器：支持全维度播报、详细排行、趣味点评。"""

from __future__ import annotations

import random
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from astrbot.api.event import AstrMessageEvent

from ..api.events import get_group_id
from ..models.enums import Action
from ..services.leaderboard_service import (
    DimensionResult,
    LeaderboardEntry,
    LeaderboardService,
)
from ..storage.stores import ProfileStore
from .context import CommandContext

__all__ = ["handle_leaderboard"]

# ── 排行类型 ──────────────────────────────────────────────
_RANK_TYPES = {
    "日": ("daily", "日榜"),
    "周": ("weekly", "周榜"),
    "总": ("alltime", "总榜"),
}

# ── 单维度查询的维度映射 ──────────────────────────────────
_DIMENSIONS = {
    "牛": (Action.NTR_SUCCESS, "牛老婆"),
    "被牛": (Action.NTR_LOST, "被牛"),
    "PK": ("pk_score", "PK段位"),
    "收集": ("collection", "收集数"),
    "亲密度": ("intimacy", "亲密度"),
    "作恶": ("evil_points", "作恶值"),
}

# ── 全维度播报的顺序 ──────────────────────────────────────
_ALL_DIMENSION_KEYS = ["收集", "牛", "被牛", "亲密度", "PK", "作恶"]

# ── 趣味点评模板 ──────────────────────────────────────────
# key = 维度标签 → [(rank_range, [templates])], rank 从 1 开始
# rank_range: (low, high) 表示 low <= rank <= high
_COMMENT_TEMPLATES: Dict[str, List[Tuple[Tuple[int, int], List[str]]]] = {
    "收集数": [
        ((1, 1), ["图鉴之王！{value}位老婆尽入囊中，真正的全图鉴收藏家"]),
        ((2, 3), ["收藏狂人！已经集齐{value}位，离全图鉴不远了"]),
        ((4, 6), ["稳步收集中，{value}位老婆在册"]),
        ((7, 999), ["图鉴新人刚上路，{value}位老婆，继续加油！"]),
    ],
    "牛老婆": [
        ((1, 1), ["牛界传奇！{value}次成功NTR，无人能挡"]),
        ((2, 3), ["NTR高手！{value}次成功出击，被牛的人瑟瑟发抖"]),
        ((4, 6), ["牛刀小试，{value}次得手，未来可期"]),
        ((7, 999), ["初出茅庐的牛人，{value}次成功，潜力股"]),
    ],
    "被牛": [
        ((1, 1), ["全群最惨！被牛{value}次，心疼你的老婆"]),
        ((2, 3), ["被牛重灾区！{value}次痛失所爱，快去锁定吧"]),
        ((4, 6), ["被牛{value}次，还好没到最惨"]),
        ((7, 999), ["安全意识不错，只被牛了{value}次"]),
    ],
    "亲密度": [
        ((1, 1), ["真爱无敌！主老婆亲密度{value}，全群最甜"]),
        ((2, 3), ["恩爱典范！亲密度{value}，令人羡慕"]),
        ((4, 6), ["感情升温中，亲密度{value}"]),
        ((7, 999), ["亲密度{value}，多去摸头送礼呀"]),
    ],
    "PK段位": [
        ((1, 1), ["PK之神！{value}分独占鳌头，拳打四方"]),
        ((2, 3), ["格斗达人！{value}分名列前茅"]),
        ((4, 6), ["PK好手，{value}分实力不俗"]),
        ((7, 999), ["PK新秀，{value}分还在成长中"]),
    ],
    "作恶值": [
        ((1, 1), ["全群最大恶人！作恶值{value}，人人喊打"]),
        ((2, 3), ["恶名昭彰！作恶值{value}，小心被复仇"]),
        ((4, 6), ["作恶值{value}，离大魔王还差一步"]),
        ((7, 999), ["作恶值{value}，小恶怡情"]),
    ],
}

# ── 通用点评（用于没有专属模板的维度） ──────────────────
_DEFAULT_COMMENT = [
    ((1, 1), ["{label}榜首！{value}{unit}，实力碾压"]),
    ((2, 3), ["{label}第{rank}名，{value}{unit}，紧追不舍"]),
    ((4, 999), ["{label}第{rank}名，{value}{unit}，再接再厉"]),
]


# ── 入口 ──────────────────────────────────────────────────


async def handle_leaderboard(
    event: AstrMessageEvent, ctx: CommandContext
) -> AsyncGenerator:
    """``老婆 排行 [日|周|总] [牛|被牛|PK|收集|亲密度|作恶]``

    无参数时默认周榜 + 全维度播报 + 趣味点评。
    指定维度时显示该维度 Top-N 详细排行 + 点评。
    """
    gid = get_group_id(event)
    if not gid:
        return

    msg = (event.message_str or "").strip()
    rest = msg
    for prefix in ("老婆排行", "老婆 排行"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    rest = rest.strip()

    # 解析参数
    rank_type_key: Optional[str] = None
    dimension_key: Optional[str] = None

    parts = rest.split()
    for part in parts:
        part = part.strip()
        if part in _RANK_TYPES:
            rank_type_key = part
        elif part in _DIMENSIONS:
            dimension_key = part

    if rank_type_key is None:
        rank_type_key = "周"

    leaderboard = LeaderboardService(ctx.paths, ctx.config, ctx.tz)
    top_n = ctx.config.leaderboard_top_n

    uid = _extract_uid(event)

    # ── 指定维度：详细排行 + 点评 ──
    if dimension_key:
        dim_action, dim_label = _DIMENSIONS[dimension_key]
        result = _get_single_dimension(leaderboard, gid, rank_type_key, dim_action, dim_label, top_n)
        if result is None or not result.has_data:
            yield event.plain_result(f"暂无{dim_label}排行数据，快去试试吧~")
            return

        text = _format_single_dimension(result, uid)
        yield event.plain_result(text)
        return

    # ── 全维度播报 ──
    rank_label = _RANK_TYPES[rank_type_key][1]
    all_dims = leaderboard.get_all_dimensions(gid, rank_type_key)

    any_data = any(d.has_data for d in all_dims)
    if not any_data:
        yield event.plain_result("暂无排行数据，快去试试吧~")
        return

    lines = [f"🏆 {rank_label}速览"]

    for i, dim in enumerate(all_dims):
        lines.append("")
        lines.append(_format_compact_dim(dim, uid, is_first=(i == 0)))

    lines.append("")
    lines.append("💡 详情 → 老婆 排行 收集/牛/被牛/亲密度/PK/作恶")

    yield event.plain_result("\n".join(lines))


# ── 数据获取 ──────────────────────────────────────────────


def _get_single_dimension(
    leaderboard: LeaderboardService,
    gid: str,
    rank_type_key: str,
    action: str,
    label: str,
    top_n: int,
) -> Optional[DimensionResult]:
    """获取单维度排行结果"""
    if action == "collection":
        entries = leaderboard.rank_collection(gid)
    elif action == "intimacy":
        entries = leaderboard.rank_primary_intimacy(gid)
    elif action == "pk_score":
        entries = leaderboard.rank_pk_score(gid)
    elif action == "evil_points":
        entries = leaderboard.rank_evil_points(gid)
    elif rank_type_key == "总":
        entries = leaderboard.rank_alltime(gid, action)
    else:
        days = 7 if rank_type_key == "周" else 1
        entries = leaderboard.rank_daily(gid, action, days)

    if not entries:
        return None

    # 填充排名和档案数据
    profile_store = ProfileStore(leaderboard._paths, gid)
    profiles = profile_store.load_all()
    entries = leaderboard._enrich_entries(entries, profiles)

    unit = _get_unit(action)
    return DimensionResult(label=label, entries=entries, has_data=True, unit=unit)


def _get_unit(action: str) -> str:
    """获取维度单位"""
    units = {
        "collection": "个",
        Action.NTR_SUCCESS: "次",
        Action.NTR_LOST: "次",
        Action.PK_WIN: "场",
        "intimacy": "点",
        "pk_score": "分",
        "evil_points": "点",
    }
    return units.get(action, "")


# ── 格式化：详细排行 ──────────────────────────────────────


def _format_single_dimension(result: DimensionResult, uid: Optional[str]) -> str:
    """格式化单维度详细排行（含点评）"""
    lines = [f"【{result.label}】Top {len(result.entries)}"]

    for entry in result.entries:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(entry.rank, f"{entry.rank}.")
        name = entry.nick or entry.uid
        title_tag = f" [{entry.active_title}]" if entry.active_title else ""

        # 主体信息
        lines.append(f"{medal} {name}{title_tag}")

        # 根据维度展示额外信息
        extra = _build_extra_line(entry, result.label)
        if extra:
            lines.append(f"   {extra}")

        # 趣味点评
        comment = _get_comment(result.label, entry.rank, entry.value, result.unit)
        if comment:
            lines.append(f"   {comment}")

    # 显示请求者自己的排名（如果不在 Top-N 中）
    if uid:
        my_line = _find_my_rank(result, uid)
        if my_line:
            lines.append(f"📍 你的排名：{my_line}")

    return "\n".join(lines)


def _build_extra_line(entry: LeaderboardEntry, dim_label: str) -> str:
    """根据维度构建额外信息行"""
    parts = []

    if dim_label == "收集数":
        if entry.total_draws > 0:
            parts.append(f"总抽卡{entry.total_draws}次")
        if entry.coins > 0:
            parts.append(f"💰{entry.coins}")

    elif dim_label == "牛老婆":
        if entry.total_draws > 0:
            parts.append(f"总抽卡{entry.total_draws}次")
        if entry.collection_count > 0:
            parts.append(f"图鉴{entry.collection_count}位")

    elif dim_label == "被牛":
        if entry.collection_count > 0:
            parts.append(f"图鉴{entry.collection_count}位")
        if entry.streak_days > 0:
            parts.append(f"签到{entry.streak_days}天")

    elif dim_label == "亲密度":
        if entry.collection_count > 0:
            parts.append(f"图鉴{entry.collection_count}位")
        if entry.coins > 0:
            parts.append(f"💰{entry.coins}")

    elif dim_label == "PK段位":
        if entry.total_draws > 0:
            parts.append(f"总抽卡{entry.total_draws}次")
        if entry.collection_count > 0:
            parts.append(f"图鉴{entry.collection_count}位")

    elif dim_label == "作恶值":
        if entry.collection_count > 0:
            parts.append(f"图鉴{entry.collection_count}位")
        if entry.streak_days > 0:
            parts.append(f"签到{entry.streak_days}天")

    return " | ".join(parts)


# ── 格式化：紧凑播报 ──────────────────────────────────────


def _format_compact_dim(dim: DimensionResult, uid: Optional[str], is_first: bool = False) -> str:
    """紧凑模式：一行展示 Top 3 + 点评"""
    if not dim.has_data or not dim.entries:
        return f"{dim.label}  暂无数据"

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    top3 = dim.entries[:3]
    items = "  ".join(
        f"{medals.get(e.rank, '')}{e.nick}({e.value})" for e in top3
    )

    # 检查请求者是否在 Top 3 中
    my_marker = ""
    if uid and any(e.uid == uid for e in top3):
        my_marker = " 👈"

    comment = _get_compact_comment(dim.label, dim.entries[0])

    if comment:
        return f"{dim.label}  {items}{my_marker}\n    {comment}"
    return f"{dim.label}  {items}{my_marker}"


def _get_compact_comment(dim_label: str, top: LeaderboardEntry) -> str:
    """紧凑模式下给第一名的简短点评"""
    comments = {
        "收集数": f"👑 {top.nick}以{top.value}位老婆领跑全场",
        "牛老婆": f"🐄 {top.nick}牛了{top.value}次，所向披靡",
        "被牛": f"😭 {top.nick}被牛{top.value}次，全场最惨",
        "亲密度": f"💕 {top.nick}亲密度{top.value}，真爱无敌",
        "PK段位": f"⚔️ {top.nick}以{top.value}分登顶PK王",
        "作恶值": f"😈 {top.nick}作恶{top.value}点，人人喊打",
    }
    return comments.get(dim_label, "")


# ── 趣味点评引擎 ──────────────────────────────────────────


def _get_comment(dim_label: str, rank: int, value: int, unit: str) -> str:
    """根据维度、排名和数值生成趣味点评"""
    templates = _COMMENT_TEMPLATES.get(dim_label, _DEFAULT_COMMENT)
    for (low, high), msgs in templates:
        if low <= rank <= high:
            tmpl = random.choice(msgs)
            return "💬 " + tmpl.format(rank=rank, value=value, unit=unit, label=dim_label)
    return ""


# ── 辅助函数 ──────────────────────────────────────────────


def _extract_uid(event: AstrMessageEvent) -> Optional[str]:
    """从事件中提取发送者 uid"""
    sender = getattr(event, "sender", None)
    if sender:
        uid = getattr(sender, "id", None) or getattr(sender, "uid", None)
        if uid:
            return str(uid)
    return None


def _find_my_rank(result: DimensionResult, uid: str) -> Optional[str]:
    """在 Top-N 之外查找请求者的排名"""
    # 先看是否已在 Top-N 中
    for entry in result.entries:
        if entry.uid == uid:
            return None  # 已在列表中显示

    # 需要重新加载全量数据来查找排名
    # 这里返回一个简单提示
    return "未上榜，继续努力！"
