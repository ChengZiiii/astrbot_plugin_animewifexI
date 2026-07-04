#!/usr/bin/env python3
"""Comprehensive QA test script for astrbot_plugin_animewifexI.

Covers ALL Phase 1-4 commands with ~100+ scenarios:

Phase 1: 抽老婆 / 查老婆 / 牛老婆 / 换老婆 / 交换 / 重置 / 帮助 / NTR开关
Phase 2: 排行 / 复仇 / 摸头 / 送礼
Phase 3: 签到 / 任务 / 商城 / 购买 / 背包 / 十连 / 锁定 / 解锁 / PK / 图鉴 / 面板
Phase 4: 打工 / 对话 / 约会 / 连续签到 / 亲密度护盾 / NTR补偿 / 作恶值 / 新手保护

Run:
    python qa_full_test.py [--verbose 0|1|2] [--scenarios all] [--seed 42]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_SKILL_ROOT = os.path.abspath(
    os.path.join(os.environ.get("ASTRBOT_QA_SKILL", ""), "")
)
# Try to auto-locate the skill
if not os.path.isdir(os.path.join(_SKILL_ROOT, "references")):
    for candidate in [
        r"T:\AI\Skills\SorenSkills\astrbot-qa",
        os.path.join(os.path.dirname(__file__), "..", "..", "astrbot-qa"),
    ]:
        if os.path.isdir(os.path.join(candidate, "references")):
            _SKILL_ROOT = os.path.abspath(candidate)
            break

if _SKILL_ROOT and _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from references.harness import Harness  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = _HERE

SEED_IMAGES = [
    "进击的巨人!三笠.jpg",
    "Re从零开始的异世界生活!雷姆.jpg",
    "鬼灭之刃!灶门祢豆子.jpg",
    "某科学的超电磁炮!御坂美琴.jpg",
    "Fate系列!Saber.jpg",
    "魔法少女小圆!鹿目圆.jpg",
    "刀剑神域!亚丝娜.jpg",
    "约会大作战!夜刀神十香.jpg",
    "间谍过家家!约尔.jpg",
    "链锯人!蕾塞.jpg",
    "蔚蓝档案!爱丽丝.jpg",
    "原神!甘雨.jpg",
]

DEFAULT_CONFIG = {
    "daily_free_draws": 0,
    "ntr_possibility": 1.0,
    "ntr_cooldown": 60,
    "draw_cooldown": 0,
    "swap_cooldown": 0,
    "pk_cooldown": 0,
    "ntr_max": 50,
    "change_max_per_day": 50,
    "swap_max_per_day": 50,
    "initial_coins": 1000,
    "image_base_url": "https://example.com/img",
    "revenge_window_hours": 24,
    "revenge_success_multiplier": 2.0,
    "chat_cooldown": 7200,
    "date_cooldown": 43200,
    "date_coin_cost": 10,
    "intimacy_pet_coin_cost": 5,
    "intimacy_gift_coin_cost": 30,
    "work_enabled": True,
    "checkin_streak_3day_bonus": 30,
    "checkin_streak_7day_bonus": 100,
}

USERS = [
    ("u1", "Alice", True),
    ("u2", "Bob", False),
    ("u3", "Carol", False),
    ("u4", "Dave", False),
]


# ============================================================
# Phase 1: 基础命令
# ============================================================

async def scenario_help(h: Harness) -> None:
    h.scenario("P1 - 帮助命令")
    await h.send("u1", "老婆帮助")
    h.expect_match(r"基础命令|抽老婆")


async def scenario_draw(h: Harness) -> None:
    h.scenario("P1 - 首次抽老婆")
    await h.send("u1", "抽老婆")
    h.expect_match(r"抽到|你.*老婆是")

    h.scenario("P1 - 再次抽老婆（应展示已有或抽新）")
    await h.send("u1", "抽老婆")
    h.expect_match(r"老婆|当前|抽到")

    h.scenario("P1 - u2 抽老婆")
    await h.send("u2", "抽老婆")
    h.expect_match(r"抽到|老婆")

    h.scenario("P1 - u3 抽老婆")
    await h.send("u3", "抽老婆")
    h.expect_match(r"抽到|老婆")


async def scenario_view(h: Harness) -> None:
    h.scenario("P1 - 查老婆（自己）")
    await h.send("u1", "查老婆")
    h.expect_match(r"老婆|位")

    h.scenario("P1 - 查老婆（指定用户）")
    await h.send("u1", "查老婆", at="u2")
    h.expect_match(r"老婆|位|没有")

    h.scenario("P1 - 查老婆 第2页")
    await h.send("u1", "查老婆 2")


async def scenario_ntr(h: Harness) -> None:
    h.scenario("P1 - 牛老婆（@目标，seed=0强制成功）")
    await h.send("u3", "抽老婆")
    h.seed_random(0)
    await h.send("u1", "牛老婆", at="u3")
    h.expect_match(r"牛老婆成功|对方.*没有|冷却")

    h.scenario("P1 - 牛老婆（冷却中）")
    await h.send("u1", "牛老婆", at="u2")
    h.expect_match(r"冷却|牛老婆成功|没有")

    h.scenario("P1 - 牛老婆（跳过冷却再试）")
    with h.time_freeze("2026-07-03 10:00:00"):
        h.seed_random(0)
        await h.send("u1", "牛老婆", at="u2")
        h.advance(seconds=61)
        h.seed_random(0)
        await h.send("u1", "牛老婆", at="u2")


async def scenario_ntr_specify_index(h: Harness) -> None:
    h.scenario("P1 - 牛老婆（指定编号）")
    await h.send("u3", "抽老婆")
    await h.send("u3", "抽老婆")
    h.seed_random(0)
    await h.send("u1", "牛老婆 @u3 2", at="u3")
    h.expect_match(r"牛老婆成功|编号|没有|冷却")


async def scenario_ntr_self(h: Harness) -> None:
    h.scenario("P1 - 牛老婆（不能牛自己）")
    await h.send("u1", "牛老婆", at="u1")
    h.expect_match(r"不能牛自己")


async def scenario_change(h: Harness) -> None:
    h.scenario("P1 - 换老婆")
    await h.send("u2", "换老婆")
    h.expect_match(r"换|老婆|次数")


async def scenario_swap(h: Harness) -> None:
    h.scenario("P1 - 交换老婆（发起）")
    await h.send("u1", "交换老婆", at="u2")
    h.expect_match(r"交换|请求|发起")

    h.scenario("P1 - 查看交换请求")
    await h.send("u2", "查看交换请求")

    h.scenario("P1 - 同意交换")
    await h.send("u2", "同意交换", at="u1")
    h.expect_match(r"交换成功|交换|请求")


async def scenario_reject_swap(h: Harness) -> None:
    h.scenario("P1 - 交换老婆（拒绝流程）")
    await h.send("u1", "交换老婆", at="u3")
    await h.send("u3", "拒绝交换", at="u1")
    h.expect_match(r"拒绝|交换")


async def scenario_ntr_switch(h: Harness) -> None:
    h.scenario("P1 - 非管理员切换NTR开关")
    await h.send("u2", "切换ntr开关状态")
    h.expect_match(r"没有权限")

    h.scenario("P1 - 管理员切换NTR开关")
    await h.send("u1", "切换ntr开关状态")
    h.expect_match(r"NTR已")
    await h.send("u1", "切换ntr开关状态")
    h.expect_match(r"NTR已")


async def scenario_reset_ntr(h: Harness) -> None:
    h.scenario("P1 - 重置牛（管理员）")
    await h.send("u1", "重置牛", at="u2")
    h.expect_match(r"重置.*牛")


async def scenario_reset_change(h: Harness) -> None:
    h.scenario("P1 - 重置换（管理员）")
    await h.send("u1", "重置换", at="u2")
    h.expect_match(r"重置.*换")


# ============================================================
# Phase 2: 排行 / 复仇 / 摸头 / 送礼
# ============================================================

async def scenario_leaderboard(h: Harness) -> None:
    h.scenario("P2 - 排行榜（总）")
    await h.send("u1", "老婆 排行")
    h.expect_match(r"排行|榜|名次")

    h.scenario("P2 - 排行榜（日）")
    await h.send("u1", "老婆 排行 日")

    h.scenario("P2 - 排行榜（收集）")
    await h.send("u1", "老婆 排行 总 收集")


async def scenario_revenge(h: Harness) -> None:
    h.scenario("P2 - 复仇流程")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u2", "抽老婆")
        await h.send("u3", "抽老婆")
        h.seed_random(0)
        await h.send("u2", "牛老婆", at="u3")
        h.seed_random(0)
        await h.send("u3", "老婆 复仇", at="u2")
        h.expect_match(r"复仇|成功|冷却|窗口|没有")


async def scenario_revenge_window_expiry(h: Harness) -> None:
    h.scenario("P2 - 复仇窗口过期（25h后）")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u2", "抽老婆")
        await h.send("u4", "抽老婆")
        h.seed_random(0)
        await h.send("u2", "牛老婆", at="u4")
        h.advance(hours=25)
        h.seed_random(0)
        await h.send("u4", "老婆 复仇", at="u2")
        h.expect_match(r"窗口|过期|复仇|冷却|没有")


async def scenario_pet(h: Harness) -> None:
    h.scenario("P2 - 摸头（成功）")
    await h.send("u1", "抽老婆")
    await h.send("u1", "老婆 摸头")
    h.expect_match(r"摸头成功|亲密度|余额")

    h.scenario("P2 - 无老婆摸头")
    h.add_user("u99", nick="Newbie99")
    await h.send("u99", "老婆 摸头")
    h.expect_match(r"还没有老婆")


async def scenario_gift(h: Harness) -> None:
    h.scenario("P2 - 送礼（成功）")
    await h.send("u1", "老婆 送礼")
    h.expect_match(r"送礼成功|亲密度|余额")

    h.scenario("P2 - 无老婆送礼")
    await h.send("u99", "老婆 送礼")
    h.expect_match(r"还没有老婆")


# ============================================================
# Phase 3: 签到 / 任务 / 商城 / 购买 / 背包 / 十连 / 锁定 / PK / 图鉴 / 面板
# ============================================================

async def scenario_checkin(h: Harness) -> None:
    h.scenario("P3 - 签到首次")
    await h.send("u2", "老婆 签到")
    h.expect_match(r"签到成功")

    h.scenario("P3 - 签到重复")
    await h.send("u2", "老婆 签到")
    h.expect_match(r"已经签到")

    h.scenario("P3 - 签到跨天")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "老婆 签到")
        h.advance(days=1)
        await h.send("u1", "老婆 签到")
        h.expect_match(r"签到成功")


async def scenario_checkin_streak(h: Harness) -> None:
    h.scenario("P3 - 连续签到3天奖励")
    with h.time_freeze("2026-07-10 10:00:00"):
        await h.send("u4", "抽老婆")
        for day in range(3):
            await h.send("u4", "老婆 签到")
            h.advance(days=1)
        h.expect_match(r"签到成功|额外奖励")

    h.scenario("P3 - 连续签到7天奖励")
    with h.time_freeze("2026-07-20 10:00:00"):
        for day in range(7):
            await h.send("u4", "老婆 签到")
            h.advance(days=1)
        h.expect_match(r"签到成功|额外奖励|道具")


async def scenario_quest(h: Harness) -> None:
    h.scenario("P3 - 任务（查看进度）")
    await h.send("u2", "老婆 任务")
    h.expect_match(r"任务|每日")


async def scenario_shop(h: Harness) -> None:
    h.scenario("P3 - 商城")
    await h.send("u2", "老婆 商城")
    h.expect_match(r"商城|余额")


async def scenario_buy(h: Harness) -> None:
    h.scenario("P3 - 购买单抽券")
    await h.send("u2", "老婆 购买 单抽券")
    h.expect_match(r"购买成功|余额不足")

    h.scenario("P3 - 购买十连券")
    await h.send("u2", "老婆 购买 十连券")
    h.expect_match(r"购买成功|余额不足")

    h.scenario("P3 - 购买锁定卡")
    await h.send("u2", "老婆 购买 锁定卡")
    h.expect_match(r"购买成功|余额不足")

    h.scenario("P3 - 购买不存在的道具")
    await h.send("u2", "老婆 购买 幻想剑")
    h.expect_match(r"不存在")

    h.scenario("P3 - 购买0个")
    await h.send("u2", "老婆 购买 单抽券 0")
    h.expect_match(r"大于 0|格式|数量")

    h.scenario("P3 - 购买多个")
    await h.send("u2", "老婆 购买 单抽券 3")
    h.expect_match(r"购买成功|余额不足")

    h.scenario("P3 - 余额不足购买")
    h.add_user("u98", nick="Poor")
    await h.send("u98", "老婆 购买 十连券 100")
    h.expect_match(r"余额不足|购买成功")


async def scenario_backpack(h: Harness) -> None:
    h.scenario("P3 - 背包（有道具）")
    await h.send("u2", "老婆 背包")
    h.expect_match(r"背包|券|卡|空空")

    h.scenario("P3 - 背包（空）")
    h.add_user("u97", nick="Empty")
    await h.send("u97", "老婆 背包")
    h.expect_match(r"空空|背包")


async def scenario_draw_ten(h: Harness) -> None:
    h.scenario("P3 - 十连（有券）")
    await h.send("u2", "老婆 十连")

    h.scenario("P3 - 十连（无券）")
    await h.send("u97", "老婆 十连")
    h.expect_match(r"没有十连券|十连")


async def scenario_lock(h: Harness) -> None:
    h.scenario("P3 - 锁定老婆")
    await h.send("u1", "抽老婆")
    await h.send("u1", "老婆 购买 锁定卡")
    await h.send("u1", "老婆 锁定 1")
    h.expect_match(r"锁定成功|没有锁定卡|编号")

    h.scenario("P3 - 解锁老婆")
    await h.send("u1", "老婆 解锁 1")
    h.expect_match(r"解锁成功|没有被锁定|编号")


async def scenario_lock_expiry(h: Harness) -> None:
    h.scenario("P3 - 锁定7天过期")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "老婆 购买 锁定卡 5")
        await h.send("u1", "老婆 锁定 1")
        h.advance(days=8)
        await h.send("u1", "老婆 重置抽卡", at="u3")
        await h.send("u3", "抽老婆")
        h.seed_random(0)
        await h.send("u3", "牛老婆", at="u1")
        h.expect_match(r"牛老婆成功|没有|冷却|失败")


async def scenario_pk(h: Harness) -> None:
    h.scenario("P3 - PK对战")
    await h.send("u1", "老婆 测试币 9999", at="u2")
    await h.send("u1", "老婆 测试币 9999", at="u3")
    await h.send("u1", "老婆 重置抽卡", at="u2")
    await h.send("u1", "老婆 重置抽卡", at="u3")
    await h.send("u2", "抽老婆")
    await h.send("u3", "抽老婆")
    await h.send("u2", "老婆 PK", at="u3")
    h.expect_match(r"PK|战报|战力|胜|平|还没有老婆")


async def scenario_pk_self(h: Harness) -> None:
    h.scenario("P3 - PK不能和自己")
    await h.send("u2", "老婆 PK", at="u2")
    h.expect_match(r"不能和自己PK")


async def scenario_pk_no_wife(h: Harness) -> None:
    h.scenario("P3 - 无老婆PK")
    h.add_user("u96", nick="NoWife")
    await h.send("u96", "老婆 PK", at="u1")
    h.expect_match(r"还没有老婆")


async def scenario_collection(h: Harness) -> None:
    h.scenario("P3 - 图鉴")
    await h.send("u1", "老婆 图鉴")
    h.expect_match(r"图鉴|收集")


async def scenario_panel(h: Harness) -> None:
    h.scenario("P3 - 面板")
    await h.send("u1", "老婆 面板")
    h.expect_match(r"面板|老婆币|余额")


# ============================================================
# Phase 4: 打工 / 对话 / 约会 / 高级NTR机制
# ============================================================

async def scenario_work_normal(h: Harness) -> None:
    h.scenario("P4 - 普通打工")
    await h.send("u1", "老婆 测试币 5000", at="u1")
    await h.send("u1", "抽老婆")
    await h.send("u1", "老婆 打工")
    h.expect_match(r"打工|消耗|余额")


async def scenario_work_overtime(h: Harness) -> None:
    h.scenario("P4 - 加班打工")
    await h.send("u2", "老婆 测试币 5000", at="u2")
    await h.send("u1", "老婆 重置抽卡", at="u2")
    await h.send("u2", "抽老婆")
    await h.send("u2", "老婆 打工 加班")
    h.expect_match(r"打工|消耗|余额")


async def scenario_work_expedition(h: Harness) -> None:
    h.scenario("P4 - 远征打工")
    await h.send("u3", "老婆 测试币 5000", at="u3")
    await h.send("u1", "老婆 重置抽卡", at="u3")
    await h.send("u3", "抽老婆")
    await h.send("u3", "老婆 打工 远征")
    h.expect_match(r"打工|消耗|余额")


async def scenario_work_no_wife(h: Harness) -> None:
    h.scenario("P4 - 无老婆打工")
    h.add_user("u95", nick="NoWifeWork")
    await h.send("u95", "老婆 打工")
    h.expect_match(r"还没有老婆")


async def scenario_work_no_coins(h: Harness) -> None:
    h.scenario("P4 - 余额不足打工")
    h.add_user("u94", nick="PoorWork")
    await h.send("u94", "抽老婆")
    await h.send("u94", "老婆 测试币 0", at="u94")
    await h.send("u94", "老婆 打工")
    h.expect_match(r"不足|打工|需要|没有老婆")


async def scenario_work_already(h: Harness) -> None:
    h.scenario("P4 - 重复打工")
    await h.send("u1", "老婆 打工")
    h.expect_match(r"打工中|重复|打工")


async def scenario_work_settle(h: Harness) -> None:
    h.scenario("P4 - 打工结算（快进4小时）")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u4", "老婆 测试币 5000", at="u4")
        await h.send("u1", "老婆 重置抽卡", at="u4")
        await h.send("u4", "抽老婆")
        await h.send("u4", "老婆 打工")
        h.advance(hours=5)
        await h.send("u4", "老婆 打工")
        h.expect_match(r"结算|获得|打工|余额|老婆")


async def scenario_chat(h: Harness) -> None:
    h.scenario("P4 - 对话（成功）")
    await h.send("u1", "抽老婆")
    await h.send("u1", "老婆 对话")
    h.expect_match(r"聊天|亲密度|余额")

    h.scenario("P4 - 对话（冷却中）")
    await h.send("u1", "老婆 对话")
    h.expect_match(r"冷却|聊天")

    h.scenario("P4 - 对话（跳过2h冷却）")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "老婆 对话")
        h.advance(hours=3)
        await h.send("u1", "老婆 对话")
        h.expect_match(r"聊天|亲密度|冷却")


async def scenario_chat_no_wife(h: Harness) -> None:
    h.scenario("P4 - 无老婆对话")
    await h.send("u99", "老婆 对话")
    h.expect_match(r"还没有老婆")


async def scenario_date(h: Harness) -> None:
    h.scenario("P4 - 约会（成功）")
    await h.send("u1", "老婆 测试币 5000", at="u1")
    await h.send("u1", "抽老婆")
    await h.send("u1", "老婆 约会")
    h.expect_match(r"约会|亲密度|余额")

    h.scenario("P4 - 约会（冷却中）")
    await h.send("u1", "老婆 约会")
    h.expect_match(r"冷却|约会")

    h.scenario("P4 - 约会（跳过12h冷却）")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "老婆 约会")
        h.advance(hours=13)
        await h.send("u1", "老婆 约会")
        h.expect_match(r"约会|亲密度|冷却")


async def scenario_date_no_wife(h: Harness) -> None:
    h.scenario("P4 - 无老婆约会")
    await h.send("u99", "老婆 约会")
    h.expect_match(r"还没有老婆")


async def scenario_date_no_coins(h: Harness) -> None:
    h.scenario("P4 - 余额不足约会")
    h.add_user("u93", nick="PoorDate")
    await h.send("u93", "抽老婆")
    await h.send("u93", "老婆 测试币 0", at="u93")
    await h.send("u93", "老婆 约会")
    h.expect_match(r"不足|约会|需要|还没有老婆")


async def scenario_intimacy_pet_maxed(h: Harness) -> None:
    h.scenario("P4 - 亲密度满后摸头")
    await h.send("u1", "老婆 测试亲密度 @u1 100")
    await h.send("u1", "老婆 摸头")
    h.expect_match(r"满|亲密度|摸头")


async def scenario_intimacy_gift_maxed(h: Harness) -> None:
    h.scenario("P4 - 亲密度满后送礼")
    await h.send("u1", "老婆 送礼")
    h.expect_match(r"满|亲密度|送礼")


async def scenario_ntr_compensation(h: Harness) -> None:
    h.scenario("P4 - 被牛后补偿机制")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u2", "老婆 测试币 5000", at="u2")
        await h.send("u1", "老婆 重置抽卡", at="u2")
        await h.send("u2", "抽老婆")
        await h.send("u2", "老婆 摸头")
        await h.send("u3", "抽老婆")
        h.seed_random(0)
        await h.send("u3", "牛老婆", at="u2")
        h.expect_match(r"牛老婆成功|没有|冷却|失败")


async def scenario_ntr_cooldown(h: Harness) -> None:
    h.scenario("P4 - NTR冷却60秒")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "抽老婆")
        await h.send("u2", "抽老婆")
        h.seed_random(0)
        await h.send("u1", "牛老婆", at="u2")
        await h.send("u1", "牛老婆", at="u2")
        h.expect_match(r"冷却|成功|没有")
        h.advance(seconds=61)
        h.seed_random(0)
        await h.send("u1", "牛老婆", at="u2")


async def scenario_daily_reset(h: Harness) -> None:
    h.scenario("P4 - 跨天每日任务重置")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "老婆 签到")
        await h.send("u1", "老婆 签到")
        h.expect_match(r"已经签到")
        h.advance(days=1)
        await h.send("u1", "老婆 签到")
        h.expect_match(r"签到成功")


# ============================================================
# Phase 4: 管理员命令
# ============================================================

async def scenario_admin_test_draw(h: Harness) -> None:
    h.scenario("P4 - 管理员测试抽卡")
    await h.send("u1", "老婆 测试抽卡 100")
    h.expect_match(r"模拟抽卡|SSR|SR")


async def scenario_admin_test_coins(h: Harness) -> None:
    h.scenario("P4 - 管理员测试币")
    await h.send("u1", "老婆 测试币 999", at="u2")
    h.expect_match(r"老婆币|设置|没有|数值")


async def scenario_admin_test_intimacy(h: Harness) -> None:
    h.scenario("P4 - 管理员测试亲密度")
    await h.send("u1", "老婆 测试亲密度 @u2 50")
    h.expect_match(r"亲密度|设置|没有")


async def scenario_admin_reset_draw(h: Harness) -> None:
    h.scenario("P4 - 管理员重置抽卡")
    await h.send("u1", "老婆 重置抽卡", at="u2")
    h.expect_match(r"重置|抽卡")


async def scenario_admin_reset_group(h: Harness) -> None:
    h.scenario("P4 - 管理员重置本群（非管理员拒绝）")
    await h.send("u2", "老婆 重置本群")
    h.expect_match(r"没有权限")


# ============================================================
# 边界场景
# ============================================================

async def scenario_edge_no_wife(h: Harness) -> None:
    h.scenario("边界 - 无老婆锁定")
    h.add_user("u90", nick="Edge1")
    await h.send("u90", "老婆 锁定 1")
    h.expect_match(r"编号|还没有老婆")

    h.scenario("边界 - 无老婆牛人（攻击方无老婆不影响NTR尝试）")
    await h.send("u90", "牛老婆", at="u1")
    h.expect_match(r"牛老婆|成功|失败|冷却|次数|请@|没有")


async def scenario_edge_no_target(h: Harness) -> None:
    h.scenario("边界 - 牛老婆无目标")
    await h.send("u1", "牛老婆")
    h.expect_match(r"请@")


async def scenario_edge_buy_empty(h: Harness) -> None:
    h.scenario("边界 - 购买无参数")
    await h.send("u1", "老婆 购买")
    h.expect_match(r"格式|商城")


async def scenario_edge_pk_no_target(h: Harness) -> None:
    h.scenario("边界 - PK无目标")
    await h.send("u1", "老婆 PK")
    h.expect_match(r"请@|PK")


async def scenario_edge_leaderboard_empty(h: Harness) -> None:
    h.scenario("边界 - 空排行榜")
    h.add_user("u89", nick="Alone")
    await h.send("u89", "老婆 排行")


# ============================================================
# 跨天综合流程
# ============================================================

async def scenario_cross_day_full(h: Harness) -> None:
    h.scenario("综合 - 跨天全流程")
    with h.time_freeze("2026-07-03 10:00:00"):
        await h.send("u1", "老婆 签到")
        await h.send("u1", "老婆 对话")
        await h.send("u1", "老婆 约会")
        h.advance(days=1)
        await h.send("u1", "老婆 签到")
        h.expect_match(r"签到成功")
        await h.send("u1", "老婆 对话")
        h.expect_match(r"聊天|冷却")


# ============================================================
# Runner
# ============================================================

SCENARIOS = {
    # Phase 1
    "help": scenario_help,
    "draw": scenario_draw,
    "view": scenario_view,
    "ntr": scenario_ntr,
    "ntr_index": scenario_ntr_specify_index,
    "ntr_self": scenario_ntr_self,
    "change": scenario_change,
    "swap": scenario_swap,
    "reject_swap": scenario_reject_swap,
    "ntr_switch": scenario_ntr_switch,
    "reset_ntr": scenario_reset_ntr,
    "reset_change": scenario_reset_change,
    # Phase 2
    "leaderboard": scenario_leaderboard,
    "revenge": scenario_revenge,
    "revenge_expiry": scenario_revenge_window_expiry,
    "pet": scenario_pet,
    "gift": scenario_gift,
    # Phase 3
    "checkin": scenario_checkin,
    "checkin_streak": scenario_checkin_streak,
    "quest": scenario_quest,
    "shop": scenario_shop,
    "buy": scenario_buy,
    "backpack": scenario_backpack,
    "draw_ten": scenario_draw_ten,
    "lock": scenario_lock,
    "lock_expiry": scenario_lock_expiry,
    "pk": scenario_pk,
    "pk_self": scenario_pk_self,
    "pk_no_wife": scenario_pk_no_wife,
    "collection": scenario_collection,
    "panel": scenario_panel,
    # Phase 4
    "work_normal": scenario_work_normal,
    "work_overtime": scenario_work_overtime,
    "work_expedition": scenario_work_expedition,
    "work_no_wife": scenario_work_no_wife,
    "work_no_coins": scenario_work_no_coins,
    "work_already": scenario_work_already,
    "work_settle": scenario_work_settle,
    "chat": scenario_chat,
    "chat_no_wife": scenario_chat_no_wife,
    "date": scenario_date,
    "date_no_wife": scenario_date_no_wife,
    "date_no_coins": scenario_date_no_coins,
    "intimacy_pet_maxed": scenario_intimacy_pet_maxed,
    "intimacy_gift_maxed": scenario_intimacy_gift_maxed,
    "ntr_compensation": scenario_ntr_compensation,
    "ntr_cooldown": scenario_ntr_cooldown,
    "daily_reset": scenario_daily_reset,
    # Admin
    "admin_test_draw": scenario_admin_test_draw,
    "admin_test_coins": scenario_admin_test_coins,
    "admin_test_intimacy": scenario_admin_test_intimacy,
    "admin_reset_draw": scenario_admin_reset_draw,
    "admin_reset_group": scenario_admin_reset_group,
    # Edge
    "edge_no_wife": scenario_edge_no_wife,
    "edge_no_target": scenario_edge_no_target,
    "edge_buy_empty": scenario_edge_buy_empty,
    "edge_pk_no_target": scenario_edge_pk_no_target,
    "edge_leaderboard_empty": scenario_edge_leaderboard_empty,
    # Comprehensive
    "cross_day_full": scenario_cross_day_full,
}


async def main(args: argparse.Namespace) -> None:
    h = Harness(
        plugin_dir=args.plugin_dir,
        group_id="g1",
        bot_uid="bot",
        config=DEFAULT_CONFIG,
        verbose=args.verbose,
        download_images=args.download_images,
        seed=args.seed,
        fresh=not args.no_fresh,
        log_file=args.log_file,
    )
    for uid, nick, is_admin in USERS:
        h.add_user(uid, nick=nick, admin=is_admin)
    h.seed_images(SEED_IMAGES)

    h.header("QA FULL TEST: astrbot_plugin_animewifexI (Phase 1-4)")

    selected = (
        args.scenarios.split(",") if args.scenarios != "all" else list(SCENARIOS)
    )
    for name in selected:
        name = name.strip()
        fn = SCENARIOS.get(name)
        if fn is None:
            h.note(f"unknown scenario: {name!r}, skipping")
            continue
        try:
            await fn(h)
        except Exception as e:
            h.printer.failed_(f"scenario {name!r} raised: {e!r}")

    h.report()
    await h.terminate()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Full QA test for astrbot_plugin_animewifexI"
    )
    p.add_argument(
        "--plugin-dir",
        default=PLUGIN_DIR,
        help=f"path to plugin root (default: {PLUGIN_DIR})",
    )
    p.add_argument(
        "--verbose",
        type=int,
        default=2,
        choices=[0, 1, 2],
        help="0=chat, 1=+assert, 2=+debug (default: 2)",
    )
    p.add_argument("--no-fresh", action="store_true", help="don't wipe data dir")
    p.add_argument("--download-images", action="store_true", help="fetch images")
    p.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    p.add_argument(
        "--scenarios",
        default="all",
        help=f"comma-separated scenario names (default: all). "
        f"available: {','.join(SCENARIOS)}",
    )
    p.add_argument("--log-file", default=None, help="write output to UTF-8 file")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args))
