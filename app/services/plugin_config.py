"""插件配置容器：集中管理所有配置项及其默认值。

设计要点：

* 所有配置项均有默认值，老配置文件升级时缺失字段自动回退（Q 决策）；
* 单元测试可直接构造 ``PluginConfig.default_for_test()`` 注入；
* 不依赖 astrbot 的 ``AstrBotConfig``，便于脱离框架单测；
* :meth:`from_dict` 接受任意 Mapping，兼容 AstrBotConfig（dict-like）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["PluginConfig"]


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    return default


@dataclass
class PluginConfig:
    """插件全部配置项（带默认值）"""

    # ---------- 基础 ----------
    admins: list = field(default_factory=list)
    need_prefix: bool = False
    image_base_url: str = "https://cdn.jsdmirror.com/gh/monbed/wife@main"
    image_list_url: str = "https://animewife.dpdns.org/list.txt"

    # ---------- 冷却（秒） ----------
    ntr_cooldown: int = 60
    draw_cooldown: int = 0
    swap_cooldown: int = 30
    pk_cooldown: int = 600  # 自冷却 10 分钟（默认）
    pk_max_per_day: int = 5

    # ---------- NTR ----------
    ntr_max: int = 3
    ntr_possibility: float = 0.20
    revenge_window_hours: int = 24
    revenge_success_multiplier: float = 2.0

    # ---------- 交换 ----------
    swap_max_per_day: int = 2

    # ---------- 亲密度 ----------
    intimacy_per_day: int = 10
    intimacy_max: int = 100
    intimacy_pet_coin_cost: int = 5
    intimacy_pet_gain: int = 3
    intimacy_gift_coin_cost: int = 30
    intimacy_gift_gain: int = 20

    # ---------- 榜单 ----------
    activity_window_days: int = 7
    leaderboard_top_n: int = 10

    # ---------- 稀有度 ----------
    rarity_weights: dict = field(
        default_factory=lambda: {"SSR": 5, "SR": 20, "R": 50, "N": 25}
    )
    pity_threshold: int = 10
    pity_min_rarity: str = "SR"

    # ---------- 经济 ----------
    initial_coins: int = 50
    daily_checkin_coins: int = 20
    daily_free_draws: int = 1           # 每日免费抽卡次数
    pk_winner_reward: int = 15
    quest_complete_coins: int = 10

    # ---------- 商城价格 ----------
    shop_prices: dict = field(
        default_factory=lambda: {
            "lock_item": 50,
            "protection_charm": 60,
            "insurance_card": 80,
            "draw_ticket_single": 30,    # 单抽券
            "draw_ticket_ten": 270,      # 十连券（9折）
        }
    )

    # ---------- Phase 4: 签到连签 ----------
    checkin_streak_3day_bonus: int = 30
    checkin_streak_7day_bonus: int = 100
    checkin_streak_7day_item: str = "draw_ticket_single"

    # ---------- Phase 4: 对话/约会 ----------
    chat_cooldown: int = 7200          # 2h = 7200s
    chat_intimacy_gain: int = 1
    chat_coin_reward: int = 5
    date_cooldown: int = 43200         # 12h = 43200s
    date_intimacy_gain: int = 8
    date_coin_cost: int = 10

    # ---------- Phase 4: NTR 降级补偿 ----------
    ntr_intimacy_retain_ratio: float = 0.50
    ntr_coin_compensation_per_intimacy: int = 2
    ntr_coin_compensation_max: int = 50
    ntr_streak_penalty: float = 0.10

    # ---------- Phase 4: 亲密度护盾 ----------
    intimacy_shield_threshold: int = 60
    intimacy_shield_reduction: float = 0.30

    # ---------- Phase 4: 新手保护 ----------
    newbie_ntr_protection_days: int = 1
    newbie_ntr_retain_ratio: float = 0.75

    # ---------- Phase 4: 复仇令牌 ----------
    revenge_token_bonus: float = 0.5
    revenge_success_intimacy_restore: float = 0.75
    revenge_fail_consolation_coins: int = 5

    # ---------- Phase 4: 作恶值 ----------
    evil_points_broadcast_threshold: int = 5
    evil_points_compensation_multiplier: float = 2.0

    # ---------- Phase 4: PK 增强 ----------
    pk_loser_reward: int = 5
    pk_loser_reward_close_threshold: float = 0.50
    pk_tie_reward: int = 8
    pk_random_variance: float = 0.10
    pk_score_per_win: int = 5
    pk_score_per_lose: int = 1
    pk_pair_cooldown_hours: int = 0  # 0 = 不限制同对手（默认仅靠自冷却）
    pk_score_decay_days: int = 30
    pk_score_decay_amount: int = 50
    pk_element_advantage: float = 1.20
    pk_element_disadvantage: float = 0.80

    # ---------- Phase 4: 重复抽卡补偿 ----------
    duplicate_coin_compensation: dict = field(
        default_factory=lambda: {"N": 5, "R": 10, "SR": 20, "SSR": 50}
    )

    # ---------- Phase 4: 打工系统 ----------
    work_enabled: bool = True
    work_max_concurrent: int = 3  # 每个用户同时最多几个老婆打工
    work_modes: dict = field(
        default_factory=lambda: {
            "normal": {
                "duration": 7200,
                "start_cost": 10,
                "reward_min": 20,
                "reward_max": 40,
                "ntr_multiplier": 1.5,
                "pk_penalty": 0.10,
                "intimacy_gain": 5,
            },
            "overtime": {
                "duration": 14400,
                "start_cost": 20,
                "reward_min": 30,
                "reward_max": 60,
                "ntr_multiplier": 2.0,
                "pk_penalty": 0.20,
                "intimacy_gain": 3,
            },
            "expedition": {
                "duration": 28800,
                "start_cost": 30,
                "reward_min": 50,
                "reward_max": 100,
                "ntr_multiplier": 2.5,
                "pk_penalty": 0.30,
                "intimacy_gain": 10,
            },
        }
    )
    work_streak_bonus: float = 0.05

    # ---------- Phase 4: 亲密度等级奖励 ----------
    intimacy_levelup_rewards: dict = field(
        default_factory=lambda: {
            "2": {"coins": 20},
            "3": {"coins": 50},
            "4": {"coins": 100, "item": "draw_ticket_single"},
            "5": {"coins": 200, "item": "draw_ticket_ten"},
        }
    )

    # ---------- Phase 4: 周惊喜宝箱 ----------
    weekly_surprise_box: dict = field(
        default_factory=lambda: {
            "min_checkin_days": 5,
            "coins": 100,
            "item": "draw_ticket_single",
        }
    )

    # ---------- Phase 4: 新手引导 ----------
    newbie_guide: dict = field(
        default_factory=lambda: {
            "day1_draw_once": {"coins": 50, "item": "draw_ticket_single"},
            "day2_pet_and_chat": {"coins": 30},
            "day3_pk_once": {"coins": 50, "item": "protection_charm"},
        }
    )

    # ---------- Phase 4 第二波（打工合约 v2 / 搭档 / 亲密度衰减） ----------
    work_contract_bonus_per_coin: float = 0.02   # 每币加成比例（0.02 = 2%）
    work_contract_min_amount: int = 1             # 最低投入
    work_contract_max_amount: int = 1000          # 最高投入
    work_partner_bonus: float = 0.20
    work_partner_daily_limit: int = 1
    intimacy_decay: int = 0

    # ---------- Phase 6 / 寿命系统 ----------
    lifespan_enabled: bool = True                       # 总开关（关闭后所有寿命相关逻辑短路）
    lifespan_max: int = 100                            # 寿命上限（新抽老婆默认满血）
    lifespan_loss_work: dict = field(                  # 打工结算时损失寿命
        default_factory=lambda: {
            "normal": 5,
            "overtime": 10,
            "expedition": 20,
        }
    )
    lifespan_loss_pk_tie: int = 8                      # PK 平局各扣
    pk_loser_defeat_penalty: int = 5                   # PK 败方战败老婆（is_alive=False）扣寿命
    hp_loss_per_point: float = 2.0                     # 败方存活老婆：每损失 1% 血量=折算寿命/上限×此值
    death_probability_base: float = 0.50               # 寿命=0 时的死亡概率
                                                       # 实际公式: p = base * (1 - lifespan/max)^2
    revive_base_cost: dict = field(                    # 复活/修复基础价（按稀有度）
        default_factory=lambda: {
            "N": 30,
            "R": 60,
            "SR": 120,
            "SSR": 250,
        }
    )

    # ---------- Phase 5 / v3 接力战（Phase C 接入）----------
    pk_v2_enabled: bool = True                  # 4v4 接力战总开关（false 回退 1v1）
    pk_v2_turn_delay_ms: int = 1000             # 每回合间主动消息延迟（毫秒）
    pk_v2_use_forward: bool = True              # 战报用合并转发（QQ 聊天记录卡片）；关掉回退一条长消息
    pk_v2_forward_sender_name: str = "哆啦b梦"  # 合并转发的"发言人"昵称（可 WebUI 改）

    # ---------- Phase E / v3 负债经济 ----------
    debt_floor: int = -500                      # 负债下限硬封顶
    debt_block_work: bool = True                # 负债时不能打工
    debt_block_shop: bool = True                # 负债时不能商城购买
    debt_block_single_draw: bool = True          # 负债时不能用币单抽
    debt_allow_ticket_draw: bool = True          # 负债时仍可用券抽卡

    # ---------- Phase F / v3 NTR 安慰币 ----------
    ntr_comfort_base_N: int = 10                # N 卡安慰币基础
    ntr_comfort_base_R: int = 25                # R 卡安慰币基础
    ntr_comfort_base_SR: int = 60               # SR 卡安慰币基础
    ntr_comfort_base_SSR: int = 120             # SSR 卡安慰币基础
    ntr_comfort_intimacy_mult: float = 0.005    # 每点好感度加 0.5%
    ntr_comfort_intimacy_mult_base: float = 1.0  # 基础倍率 1.0
    revenge_is_free: bool = True                 # 复仇免费

    # ---------- 派生 ----------
    @property
    def normalized_image_base_url(self) -> str:
        """图床基础 URL，强制以 / 结尾"""
        return self.image_base_url.rstrip("/") + "/"

    def is_admin(self, uid: str) -> bool:
        """判断 uid 是否在管理员列表中（兼容字符串/数字混存）"""
        target = str(uid)
        return any(str(a) == target for a in self.admins)

    @classmethod
    def from_dict(cls, data: "Mapping[str, Any] | None") -> "PluginConfig":
        """从任意 Mapping（AstrBotConfig 或 dict）构造，缺失字段使用默认值"""
        d: Mapping[str, Any] = data or {}

        admins_raw = d.get("admins") or []
        if not isinstance(admins_raw, (list, tuple)):
            admins_raw = []
        admins = [str(a) for a in admins_raw]

        rarity_weights = dict(d.get("rarity_weights") or {})
        if not rarity_weights:
            rarity_weights = {"SSR": 5, "SR": 20, "R": 50, "N": 25}

        shop_prices = dict(d.get("shop_prices") or {})
        if not shop_prices:
            shop_prices = {
                "lock_item": 50,
                "protection_charm": 60,
                "insurance_card": 90,
                "draw_ticket_single": 30,
                "draw_ticket_ten": 270,
            }

        # Phase 4 dict fields
        duplicate_coin_compensation = dict(d.get("duplicate_coin_compensation") or {})
        if not duplicate_coin_compensation:
            duplicate_coin_compensation = {"N": 5, "R": 10, "SR": 20, "SSR": 50}

        work_modes = dict(d.get("work_modes") or {})
        if not work_modes:
            work_modes = {
                "normal": {
                    "duration": 7200, "start_cost": 10,
                    "reward_min": 20, "reward_max": 40,
                    "ntr_multiplier": 1.5, "pk_penalty": 0.10,
                    "intimacy_gain": 5,
                },
                "overtime": {
                    "duration": 14400, "start_cost": 20,
                    "reward_min": 30, "reward_max": 60,
                    "ntr_multiplier": 2.0, "pk_penalty": 0.20,
                    "intimacy_gain": 3,
                },
                "expedition": {
                    "duration": 28800, "start_cost": 30,
                    "reward_min": 50, "reward_max": 100,
                    "ntr_multiplier": 2.5, "pk_penalty": 0.30,
                    "intimacy_gain": 10,
                },
            }

        intimacy_levelup_rewards = dict(d.get("intimacy_levelup_rewards") or {})
        if not intimacy_levelup_rewards:
            intimacy_levelup_rewards = {
                "2": {"coins": 20},
                "3": {"coins": 50},
                "4": {"coins": 100, "item": "draw_ticket_single"},
                "5": {"coins": 200, "item": "draw_ticket_ten"},
            }

        weekly_surprise_box = dict(d.get("weekly_surprise_box") or {})
        if not weekly_surprise_box:
            weekly_surprise_box = {
                "min_checkin_days": 5, "coins": 100,
                "item": "draw_ticket_single",
            }

        newbie_guide = dict(d.get("newbie_guide") or {})
        if not newbie_guide:
            newbie_guide = {
                "day1_draw_once": {"coins": 50, "item": "draw_ticket_single"},
                "day2_pet_and_chat": {"coins": 30},
                "day3_pk_once": {"coins": 50, "item": "protection_charm"},
            }

        # Phase 6 / 寿命系统
        lifespan_loss_work = dict(d.get("lifespan_loss_work") or {})
        if not lifespan_loss_work:
            lifespan_loss_work = {"normal": 5, "overtime": 10, "expedition": 20}

        revive_base_cost = dict(d.get("revive_base_cost") or {})
        if not revive_base_cost:
            revive_base_cost = {"N": 30, "R": 60, "SR": 120, "SSR": 250}

        return cls(
            admins=admins,
            need_prefix=_as_bool(d.get("need_prefix"), False),
            image_base_url=str(
                d.get("image_base_url")
                or "https://cdn.jsdmirror.com/gh/monbed/wife@main"
            ),
            image_list_url=str(
                d.get("image_list_url") or "https://animewife.dpdns.org/list.txt"
            ),
            ntr_cooldown=_as_int(d.get("ntr_cooldown"), 60),
            draw_cooldown=_as_int(d.get("draw_cooldown"), 0),
            swap_cooldown=_as_int(d.get("swap_cooldown"), 30),
            pk_cooldown=_as_int(d.get("pk_cooldown"), 600),
            pk_max_per_day=_as_int(d.get("pk_max_per_day"), 5),
            ntr_max=_as_int(d.get("ntr_max"), 3),
            ntr_possibility=_as_float(d.get("ntr_possibility"), 0.20),
            revenge_window_hours=_as_int(d.get("revenge_window_hours"), 24),
            revenge_success_multiplier=_as_float(
                d.get("revenge_success_multiplier"), 2.0
            ),
            swap_max_per_day=_as_int(d.get("swap_max_per_day"), 2),
            intimacy_per_day=_as_int(d.get("intimacy_per_day"), 10),
            intimacy_max=_as_int(d.get("intimacy_max"), 100),
            intimacy_pet_coin_cost=_as_int(d.get("intimacy_pet_coin_cost"), 5),
            intimacy_pet_gain=_as_int(d.get("intimacy_pet_gain"), 3),
            intimacy_gift_coin_cost=_as_int(d.get("intimacy_gift_coin_cost"), 30),
            intimacy_gift_gain=_as_int(d.get("intimacy_gift_gain"), 20),
            activity_window_days=_as_int(d.get("activity_window_days"), 7),
            leaderboard_top_n=_as_int(d.get("leaderboard_top_n"), 10),
            rarity_weights=rarity_weights,
            pity_threshold=_as_int(d.get("pity_threshold"), 10),
            pity_min_rarity=str(d.get("pity_min_rarity") or "SR"),
            initial_coins=_as_int(d.get("initial_coins"), 50),
            daily_checkin_coins=_as_int(d.get("daily_checkin_coins"), 20),
            daily_free_draws=_as_int(d.get("daily_free_draws"), 1),
            pk_winner_reward=_as_int(d.get("pk_winner_reward"), 15),
            quest_complete_coins=_as_int(d.get("quest_complete_coins"), 10),
            shop_prices=shop_prices,
            # Phase 4 fields
            checkin_streak_3day_bonus=_as_int(d.get("checkin_streak_3day_bonus"), 30),
            checkin_streak_7day_bonus=_as_int(d.get("checkin_streak_7day_bonus"), 100),
            checkin_streak_7day_item=str(d.get("checkin_streak_7day_item") or "draw_ticket_single"),
            chat_cooldown=_as_int(d.get("chat_cooldown"), 7200),
            chat_intimacy_gain=_as_int(d.get("chat_intimacy_gain"), 1),
            chat_coin_reward=_as_int(d.get("chat_coin_reward"), 5),
            date_cooldown=_as_int(d.get("date_cooldown"), 43200),
            date_intimacy_gain=_as_int(d.get("date_intimacy_gain"), 8),
            date_coin_cost=_as_int(d.get("date_coin_cost"), 10),
            ntr_intimacy_retain_ratio=_as_float(d.get("ntr_intimacy_retain_ratio"), 0.50),
            ntr_coin_compensation_per_intimacy=_as_int(d.get("ntr_coin_compensation_per_intimacy"), 2),
            ntr_coin_compensation_max=_as_int(d.get("ntr_coin_compensation_max"), 50),
            ntr_streak_penalty=_as_float(d.get("ntr_streak_penalty"), 0.10),
            intimacy_shield_threshold=_as_int(d.get("intimacy_shield_threshold"), 60),
            intimacy_shield_reduction=_as_float(d.get("intimacy_shield_reduction"), 0.30),
            newbie_ntr_protection_days=_as_int(d.get("newbie_ntr_protection_days"), 1),
            newbie_ntr_retain_ratio=_as_float(d.get("newbie_ntr_retain_ratio"), 0.75),
            revenge_token_bonus=_as_float(d.get("revenge_token_bonus"), 0.5),
            revenge_success_intimacy_restore=_as_float(d.get("revenge_success_intimacy_restore"), 0.75),
            revenge_fail_consolation_coins=_as_int(d.get("revenge_fail_consolation_coins"), 5),
            evil_points_broadcast_threshold=_as_int(d.get("evil_points_broadcast_threshold"), 5),
            evil_points_compensation_multiplier=_as_float(d.get("evil_points_compensation_multiplier"), 2.0),
            pk_loser_reward=_as_int(d.get("pk_loser_reward"), 5),
            pk_loser_reward_close_threshold=_as_float(d.get("pk_loser_reward_close_threshold"), 0.50),
            pk_tie_reward=_as_int(d.get("pk_tie_reward"), 8),
            pk_random_variance=_as_float(d.get("pk_random_variance"), 0.10),
            pk_score_per_win=_as_int(d.get("pk_score_per_win"), 5),
            pk_score_per_lose=_as_int(d.get("pk_score_per_lose"), 1),
            pk_pair_cooldown_hours=_as_int(d.get("pk_pair_cooldown_hours"), 0),
            pk_score_decay_days=_as_int(d.get("pk_score_decay_days"), 30),
            pk_score_decay_amount=_as_int(d.get("pk_score_decay_amount"), 50),
            pk_element_advantage=_as_float(d.get("pk_element_advantage"), 1.20),
            pk_element_disadvantage=_as_float(d.get("pk_element_disadvantage"), 0.80),
            duplicate_coin_compensation=duplicate_coin_compensation,
            work_enabled=_as_bool(d.get("work_enabled"), True),
            work_modes=work_modes,
            work_streak_bonus=_as_float(d.get("work_streak_bonus"), 0.05),
            intimacy_levelup_rewards=intimacy_levelup_rewards,
            weekly_surprise_box=weekly_surprise_box,
            newbie_guide=newbie_guide,
            work_contract_bonus_per_coin=_as_float(d.get("work_contract_bonus_per_coin"), 0.02),
            work_contract_min_amount=_as_int(d.get("work_contract_min_amount"), 1),
            work_contract_max_amount=_as_int(d.get("work_contract_max_amount"), 1000),
            work_partner_bonus=_as_float(d.get("work_partner_bonus"), 0.20),
            work_partner_daily_limit=_as_int(d.get("work_partner_daily_limit"), 1),
            intimacy_decay=_as_int(d.get("intimacy_decay"), 0),
            # Phase 6 / 寿命系统
            lifespan_enabled=_as_bool(d.get("lifespan_enabled"), True),
            lifespan_max=_as_int(d.get("lifespan_max"), 100),
            lifespan_loss_work=lifespan_loss_work,
            lifespan_loss_pk_tie=_as_int(d.get("lifespan_loss_pk_tie"), 8),
            pk_loser_defeat_penalty=_as_int(d.get("pk_loser_defeat_penalty"), 5),
            hp_loss_per_point=_as_float(d.get("hp_loss_per_point"), 2.0),
            death_probability_base=_as_float(d.get("death_probability_base"), 0.50),
            revive_base_cost=revive_base_cost,
            # Phase 5 / v3 接力战
            pk_v2_enabled=_as_bool(d.get("pk_v2_enabled"), True),
            pk_v2_turn_delay_ms=_as_int(d.get("pk_v2_turn_delay_ms"), 1000),
            pk_v2_use_forward=_as_bool(d.get("pk_v2_use_forward"), True),
            pk_v2_forward_sender_name=str(
                d.get("pk_v2_forward_sender_name") or "哆啦b梦"
            ),
            # Phase E / v3 负债经济
            debt_floor=_as_int(d.get("debt_floor"), -500),
            debt_block_work=_as_bool(d.get("debt_block_work"), True),
            debt_block_shop=_as_bool(d.get("debt_block_shop"), True),
            debt_block_single_draw=_as_bool(d.get("debt_block_single_draw"), True),
            debt_allow_ticket_draw=_as_bool(d.get("debt_allow_ticket_draw"), True),
            # Phase F / v3 NTR 安慰币
            ntr_comfort_base_N=_as_int(d.get("ntr_comfort_base_N"), 10),
            ntr_comfort_base_R=_as_int(d.get("ntr_comfort_base_R"), 25),
            ntr_comfort_base_SR=_as_int(d.get("ntr_comfort_base_SR"), 60),
            ntr_comfort_base_SSR=_as_int(d.get("ntr_comfort_base_SSR"), 120),
            ntr_comfort_intimacy_mult=_as_float(d.get("ntr_comfort_intimacy_mult"), 0.005),
            ntr_comfort_intimacy_mult_base=_as_float(d.get("ntr_comfort_intimacy_mult_base"), 1.0),
            revenge_is_free=_as_bool(d.get("revenge_is_free"), True),
        )

    @classmethod
    def default_for_test(cls) -> "PluginConfig":
        """单元测试用：全部默认值"""
        return cls()
