"""v3 接力战 · 战斗消息模板渲染测试。

对应 spec `v3_接力战_主线.md` §S8：启动贴 / 回合贴 / 死亡贴 / 结算贴。

要点：
* 模板是**纯函数**：不读文件、不调网络、不依赖外部随机。
* 每个模板断言关键字符串（"第 N 回合"、"气魄"、"击败"、"暴击"、"速度"、"积分"、"编队"），
  说明它确实渲染了对应语义而不是空骨架。
* 同时检查基本边角：空编队 / 单成员编队 / 部分死亡。
"""

from __future__ import annotations

import pytest

from app.models.pk_battle import BattleStatusLayer, FormationMember
from app.services.pk_v2_messages import (
    render_death_message,
    render_init_message,
    render_settle_message,
    render_turn_message,
)


# ============== helpers ==============


def _make_member(
    wid: str = "w1",
    pos: int = 1,
    nickname: str = "三笠",
    rarity: str = "SSR",
    element: str = "力量",
    base_atk: int = 80,
    base_def: int = 60,
    base_hp: int = 500,
    intimacy: int = 90,
    is_locked: bool = False,
    current_hp: int = 500,
    is_alive: bool = True,
    kills: int = 0,
    damage_dealt: int = 0,
    damage_taken: int = 0,
    passive_id: str = "",
) -> FormationMember:
    return FormationMember(
        wid=wid, pos=pos, nickname=nickname, rarity=rarity, element=element,
        base_atk=base_atk, base_def=base_def, base_hp=base_hp,
        intimacy=intimacy, is_locked=is_locked,
        current_hp=current_hp, is_alive=is_alive, is_active=(pos == 1),
        kills=kills, damage_dealt=damage_dealt, damage_taken=damage_taken,
        passive_id=passive_id,
    )


def _four_atk_members() -> list:
    """一组标准的 4 人攻方编队"""
    return [
        _make_member("wa1", 1, "三笠", "SSR", "力量", 80, 60, 500, 90),
        _make_member("wa2", 2, "阿尔敏", "SR", "智力", 50, 50, 380, 60),
        _make_member("wa3", 3, "萨沙", "R", "敏捷", 30, 30, 280, 30),
        _make_member("wa4", 4, "米卡莎", "N", "力量", 20, 20, 200, 10),
    ]


def _four_def_members() -> list:
    return [
        _make_member("wd1", 1, "祢豆子", "SR", "敏捷", 60, 50, 450, 50),
        _make_member("wd2", 2, "蝴蝶忍", "SR", "智力", 50, 50, 380, 70),
        _make_member("wd3", 3, "炭治郎", "R", "智力", 40, 40, 320, 40),
        _make_member("wd4", 4, "香奈乎", "N", "敏捷", 20, 20, 200, 20),
    ]


# ============== render_init_message (S8.1) ==============


class TestRenderInitMessage:
    def test_contains_4v4_header(self):
        """启动贴必须有 4v4 头部"""
        msg = render_init_message(
            atk_formation=_four_atk_members(),
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
        )
        assert "4v4" in msg
        assert "接力战" in msg

    def test_shows_attacker_and_defender(self):
        """显示双方昵称 + 攻/守标签"""
        msg = render_init_message(
            atk_formation=_four_atk_members(),
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
        )
        assert "soren" in msg
        assert "xxx" in msg
        # 攻/守标签
        assert "攻方" in msg
        assert "守方" in msg

    def test_shows_each_member_info(self):
        """4 位编队每位都要列出（昵称 + 稀有度 + 元素 + HP）"""
        atk = _four_atk_members()
        msg = render_init_message(
            atk_formation=atk,
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
        )
        for m in atk:
            assert m.nickname in msg, f"missing nickname {m.nickname!r}"
            assert m.rarity in msg, f"missing rarity {m.rarity!r}"
            assert m.element in msg, f"missing element {m.element!r}"
            assert str(m.base_hp) in msg

    def test_shows_formation_hint(self):
        """未自定义时显示编队提示"""
        msg = render_init_message(
            atk_formation=_four_atk_members(),
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
            atk_used_default=True, def_used_default=False,
        )
        # 默认编队应提示
        assert "默认编队" in msg or "默认" in msg

    def test_no_default_hint_when_customized(self):
        """双方都自定义时不应有默认提示"""
        msg = render_init_message(
            atk_formation=_four_atk_members(),
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
            atk_used_default=False, def_used_default=False,
        )
        # 自定义时不应显示"使用默认编队"
        assert "使用默认" not in msg

    def test_partial_formation_accepted(self):
        """单成员（1vN）编队也能渲染"""
        atk = [_make_member("wa1", 1, "三笠", "SSR", "力量", 80, 60, 500, 90)]
        msg = render_init_message(
            atk_formation=atk,
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
        )
        assert "三笠" in msg

    def test_shows_power_totals(self):
        """显示双方战力"""
        msg = render_init_message(
            atk_formation=_four_atk_members(),
            def_formation=_four_def_members(),
            atk_uid="u1", atk_nick="soren",
            def_uid="u2", def_nick="xxx",
        )
        # 战力有"⚡"图标或中文"战力"
        assert "战力" in msg


# ============== render_turn_message (S8.2) ==============


class TestRenderTurnMessage:
    def test_contains_turn_number(self):
        """回合贴必须有"第 N 回合"标记"""
        msg = render_turn_message(
            turn_idx=6,
            atk_member=_make_member("wa1", 1, "三笠", "SSR", "力量"),
            df_member=_make_member("wd1", 1, "祢豆子", "SR", "敏捷"),
            atk_status=BattleStatusLayer(qi_po=4),
            df_status=BattleStatusLayer(weak_point=2),
            attack_results=[
                {"side": "atk", "hit": True, "dmg": 247, "crit": True, "combo": False},
            ],
        )
        assert "第 6 回合" in msg

    def test_contains_status_layer_keywords(self):
        """回合贴显示状态层（气魄/弱点/血性/狂暴）"""
        msg = render_turn_message(
            turn_idx=6,
            atk_member=_make_member("wa1", 1, "三笠", "SSR", "力量"),
            df_member=_make_member("wd1", 1, "祢豆子", "SR", "敏捷"),
            atk_status=BattleStatusLayer(qi_po=5, bloodlust=2),
            df_status=BattleStatusLayer(weak_point=3, bloodlust=1),
            attack_results=[
                {"side": "atk", "hit": True, "dmg": 100, "crit": False, "combo": False},
            ],
        )
        assert "气魄" in msg
        assert "弱点" in msg

    def test_shows_crit_on_critical_hit(self):
        """暴击攻击显示"暴击"标记"""
        msg = render_turn_message(
            turn_idx=6,
            atk_member=_make_member("wa1", 1, "三笠", "SSR", "力量"),
            df_member=_make_member("wd1", 1, "祢豆子", "SR", "敏捷"),
            atk_status=BattleStatusLayer(),
            df_status=BattleStatusLayer(),
            attack_results=[
                {"side": "atk", "hit": True, "dmg": 247, "crit": True, "combo": False},
            ],
        )
        assert "暴击" in msg

    def test_shows_speed_label(self):
        """先手方有"先手"/"反击"标记 + 速度数字"""
        msg = render_turn_message(
            turn_idx=6,
            atk_member=_make_member("wa1", 1, "三笠", "SSR", "力量"),
            df_member=_make_member("wd1", 1, "祢豆子", "SR", "敏捷"),
            atk_status=BattleStatusLayer(),
            df_status=BattleStatusLayer(),
            attack_results=[
                {"side": "atk", "hit": True, "dmg": 100, "crit": False, "combo": False},
            ],
        )
        assert "速度" in msg
        # 至少有一方"先手"或"反击"
        assert ("先手" in msg) or ("反击" in msg)

    def test_shows_miss_when_no_hit(self):
        """未命中时显示 hit=False（攻击结果的某种 miss 标记）"""
        msg = render_turn_message(
            turn_idx=6,
            atk_member=_make_member("wa1", 1, "三笠", "SSR", "力量"),
            df_member=_make_member("wd1", 1, "祢豆子", "SR", "敏捷"),
            atk_status=BattleStatusLayer(),
            df_status=BattleStatusLayer(),
            attack_results=[
                {"side": "atk", "hit": False, "dmg": 0, "crit": False, "combo": False},
            ],
        )
        # 显示"未命中"或"miss"或类似标记
        assert ("未命中" in msg) or ("MISS" in msg) or ("miss" in msg.lower())

    def test_shows_element_advantage(self):
        """克制倍率标签显示"""
        msg = render_turn_message(
            turn_idx=6,
            atk_member=_make_member("wa1", 1, "三笠", "SSR", "力量"),
            df_member=_make_member("wd1", 1, "祢豆子", "SR", "敏捷"),
            atk_status=BattleStatusLayer(),
            df_status=BattleStatusLayer(),
            attack_results=[
                {"side": "atk", "hit": True, "dmg": 247, "crit": False, "combo": False},
            ],
        )
        # 元素克制有标识
        assert ("元素克制" in msg) or ("克制" in msg) or ("元素" in msg)


# ============== render_death_message (S8.3) ==============


class TestRenderDeathMessage:
    def test_contains_death_keyword(self):
        """死亡贴必须有"倒" / "击败" / "退场" / "死"等标识"""
        victim = _make_member("wd1", 1, "祢豆子", "SR", "敏捷")
        msg = render_death_message(victim)
        assert ("倒" in msg) or ("击败" in msg) or ("退场" in msg) or ("死" in msg)
        assert "祢豆子" in msg

    def test_with_next_member_shows_swap(self):
        """有下一位时显示上场接战"""
        victim = _make_member("wd1", 1, "祢豆子", "SR", "敏捷")
        next_m = _make_member("wd2", 2, "蝴蝶忍", "SR", "智力")
        msg = render_death_message(victim, next_member=next_m)
        assert "蝴蝶忍" in msg
        # "上场"或"接战"
        assert ("上场" in msg) or ("接战" in msg)

    def test_no_next_member_no_swap(self):
        """没有下一位时不显示上场接战"""
        victim = _make_member("wd1", 1, "祢豆子", "SR", "敏捷")
        msg = render_death_message(victim, next_member=None)
        # 不应出现"上场"或"接战"
        assert "上场" not in msg
        assert "接战" not in msg


# ============== render_settle_message (S8.4) ==============


class TestRenderSettleMessage:
    def _settle_args(self, **overrides):
        """标准结算贴参数集"""
        args = dict(
            winner_uid="u1", winner_nick="soren",
            loser_uid="u2", loser_nick="xxx",
            atk_kills=4, def_kills=2,
            atk_dmg_total=1234, def_dmg_total=1830,
            reward_winner=15, reward_loser=5,
            winner_score_gain=5, loser_score_gain=1,
            winner_rank="黄金 II", loser_rank="白银 III",
            formations_hero=[
                ("三笠", 3, True),
                ("阿尔敏", 1, True),
                ("萨沙", 0, True),
                ("米卡莎", 0, True),
            ],
            target_needs_formation=False,
        )
        args.update(overrides)
        return args

    def test_contains_winner_and_loser(self):
        """结算贴显示胜方和败方"""
        msg = render_settle_message(**self._settle_args())
        assert "soren" in msg
        assert "xxx" in msg
        assert ("胜利" in msg) or ("胜" in msg)
        assert ("失败" in msg) or ("败" in msg)

    def test_contains_rewards_and_score(self):
        """结算贴显示币 + 积分"""
        msg = render_settle_message(**self._settle_args())
        assert "+15" in msg or "15" in msg
        assert "+5" in msg or "5" in msg
        assert "积分" in msg
        assert "币" in msg

    def test_contains_hero_roster(self):
        """结算贴显示英雄一览"""
        msg = render_settle_message(**self._settle_args())
        assert "三笠" in msg
        assert "阿尔敏" in msg

    def test_contains_rank_label(self):
        """结算贴显示段位"""
        msg = render_settle_message(**self._settle_args())
        assert "黄金" in msg
        assert "白银" in msg

    def test_formation_hint_when_defender_needs_formation(self):
        """败方未设置编队时给出提示"""
        msg = render_settle_message(**self._settle_args(
            target_needs_formation=True,
        ))
        assert "编队" in msg
        # 提示使用 `老婆 编队 ...`
        assert "老婆 编队" in msg or "编队 1 2 3 4" in msg

    def test_no_formation_hint_when_set(self):
        """败方已设置时不显示编队提示"""
        msg = render_settle_message(**self._settle_args(
            target_needs_formation=False,
        ))
        assert "发 `老婆 编队" not in msg

    def test_contains_kill_count(self):
        """结算贴显示击破数"""
        msg = render_settle_message(**self._settle_args(
            atk_kills=4, def_kills=2,
        ))
        # 4/4 和 2/4 表示击破
        assert "4/4" in msg
        assert "2/4" in msg

    def test_contains_damage_hp_loss(self):
        """结算贴显示己方损耗（HP）"""
        msg = render_settle_message(**self._settle_args(
            atk_dmg_total=1234, def_dmg_total=1830,
        ))
        # 损耗含 HP / xxxxx 数字
        assert "1234" in msg
        assert "1830" in msg


class TestRenderSettleMessageDynamic:
    """Minor #5 / #6：结算贴分母动态化 + 平局渲染。"""

    def _args(self, **overrides):
        base = dict(
            winner_uid="u1", winner_nick="soren",
            loser_uid="u2", loser_nick="xxx",
            atk_kills=2, def_kills=3,
            atk_dmg_total=500, def_dmg_total=700,
            reward_winner=15, reward_loser=5,
            winner_score_gain=5, loser_score_gain=1,
            winner_rank="黄金 II", loser_rank="白银 III",
            formations_hero=[("三笠", 1, True)],
            target_needs_formation=False,
            atk_total=4, def_total=4,
            atk_total_hp=1830, def_total_hp=1830,
        )
        base.update(overrides)
        return base

    def test_uses_dynamic_team_size(self):
        """击破敌将分母动态：传入 3 / 5 时显示 /3 与 /5，且不出现硬编码 /4"""
        msg = render_settle_message(**self._args(atk_total=3, def_total=5))
        assert "/3" in msg
        assert "/5" in msg
        assert "/4" not in msg

    def test_uses_dynamic_total_hp(self):
        """己方损耗分母动态：传入 900 / 1200 时显示，且不出现硬编码 1830"""
        msg = render_settle_message(**self._args(atk_total_hp=900, def_total_hp=1200))
        assert "900" in msg
        assert "1200" in msg
        assert "1830" not in msg

    def test_tie_renders_draw(self):
        """平局：显示平局 + 双方 +8"""
        msg = render_settle_message(**self._args(
            is_tie=True,
            reward_winner=8, reward_loser=8,
            winner_score_gain=2, loser_score_gain=2,
        ))
        assert "平局" in msg
        assert "+8" in msg

    # ============== 回归测试：3 个 bug 的修复 ==============

    def test_bug1_no_atk_def_mislabel_regression(self):
        """Bug #1 回归：结算贴不再用 "攻方 @xxx / 守方 @xxx" 的互换标签，
        也不再有把 winner_uid 误判为 "atk" 字符串的逻辑 bug。

        测试要点：
        - winner_uid="u1"（不是字符串 "atk"）
        - 渲染结果：胜方行用 winner_nick "alice"，败方行用 loser_nick "bob"
        - alice（胜方）绝不出现在"败方"行；bob（败方）绝不出现在"胜方"行
        - 没有"攻方/守方"标签（只在平局分支才有，平局分支已经单独测了）
        """
        msg = render_settle_message(
            winner_uid="u1", winner_nick="alice",
            loser_uid="u2", loser_nick="bob",
            atk_kills=0, def_kills=3,
            atk_dmg_total=500, def_dmg_total=800,
            reward_winner=15, reward_loser=1,
            winner_score_gain=5, loser_score_gain=0,
            winner_rank="白银 I", loser_rank="青铜 I",
            formations_hero=[("优妮", 0, True), ("无声铃鹿", 3, False)],
            target_needs_formation=False,
            atk_nick="alice", def_nick="bob",
        )
        # 没有 "攻方" / "守方" 标签（非平局分支）
        assert "攻方" not in msg
        assert "守方" not in msg
        # 用胜/败方标签
        assert "胜方 @alice" in msg
        assert "败方 @bob" in msg
        # 关键回归断言：胜方 "alice" 不出现在败方行；败方 "bob" 不出现在胜方行
        for line in msg.splitlines():
            if line.startswith("💀 败方"):
                assert "alice" not in line, (
                    f"bug #1 未修复：alice（胜方）居然出现在败方行：{line!r}"
                )
            if line.startswith("🏆 胜方"):
                assert "bob" not in line, (
                    f"bug #1 未修复：bob（败方）居然出现在胜方行：{line!r}"
                )
        # alice 的胜方行 + 英雄一览行 = 2 处出现（合法的）；bob 败方行 + 编队提示 = 可能 1~2 处
        alice_count = sum(1 for ln in msg.splitlines() if "@alice" in ln)
        bob_count = sum(1 for ln in msg.splitlines() if "@bob" in ln)
        assert alice_count >= 1, "alice 至少应在胜方行出现"
        assert bob_count >= 1, "bob 至少应在败方行出现"

    def test_bug2_hero_roster_uses_winner_nick_not_wife_name_regression(self):
        """Bug #2 回归：英雄一览的 "@xxx 你的编队一览" 必须用 **玩家昵称**
        （winner_nick），而不是 formations_hero 第一项的老婆名。

        历史上 formations_hero[0][0] 是老婆昵称（"优妮"），导致出现
        "@优妮 你的编队一览" 这种荒诞结果。
        """
        msg = render_settle_message(
            winner_uid="u1", winner_nick="玩家A",
            loser_uid="u2", loser_nick="玩家B",
            atk_kills=2, def_kills=1,
            atk_dmg_total=300, def_dmg_total=400,
            reward_winner=15, reward_loser=1,
            winner_score_gain=5, loser_score_gain=0,
            winner_rank="白银 I", loser_rank="青铜 I",
            formations_hero=[
                ("优妮", 2, True),    # 第一项是老婆名"优妮"
                ("中川夏纪", 0, True),
            ],
            target_needs_formation=False,
            atk_nick="玩家A", def_nick="玩家B",
        )
        # 必须用 winner_nick，而不是老婆名
        assert "📢 @玩家A 你的编队一览" in msg
        assert "📢 @优妮 你的编队一览" not in msg, (
            "bug #2 未修复：英雄一览居然用了 formations_hero[0][0]（老婆名）而不是 winner_nick"
        )

    def test_tie_uses_atk_def_nicks_for_labels_regression(self):
        """平局分支：攻方/守方标签分别用 atk_nick / def_nick 平局分支仍然按攻守方打标签，靠这两个参数渲染。"""
        msg = render_settle_message(
            winner_uid="u1", winner_nick="soren",
            loser_uid="u2", loser_nick="xxx",
            atk_kills=1, def_kills=1,
            atk_dmg_total=300, def_dmg_total=300,
            reward_winner=8, reward_loser=8,
            winner_score_gain=2, loser_score_gain=2,
            winner_rank="白银 I", loser_rank="白银 I",
            formations_hero=[("优妮", 1, True), ("无形铃鹿", 1, False)],
            target_needs_formation=False,
            is_tie=True,
            atk_nick="攻方Alice", def_nick="守方Bob",
        )
        assert "攻方 @攻方Alice" in msg
        assert "守方 @守方Bob" in msg
        # 平局分支英雄一览也用 atk_label_nick（默认 atk_nick）
        assert "📢 @攻方Alice 你的编队一览" in msg
