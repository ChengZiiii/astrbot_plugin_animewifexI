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
    pk_cooldown: int = 120
    pk_max_per_day: int = 5

    # ---------- NTR ----------
    ntr_max: int = 3
    ntr_possibility: float = 0.20
    revenge_window_hours: int = 24
    revenge_success_multiplier: float = 2.0

    # ---------- 换/交换/重置 ----------
    change_max_per_day: int = 3
    swap_max_per_day: int = 2
    reset_max_uses_per_day: int = 3
    reset_success_rate: float = 0.30
    reset_mute_duration: int = 300

    # ---------- 亲密度 ----------
    intimacy_per_day: int = 10
    intimacy_max: int = 100
    intimacy_marry_threshold: int = 60
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
    reroll_cost: int = 30
    pk_winner_reward: int = 15
    quest_complete_coins: int = 10

    # ---------- 商城价格 ----------
    shop_prices: dict = field(
        default_factory=lambda: {
            "reroll_ticket": 30,
            "lock_item": 50,
            "revive_potion": 80,
            "protection_charm": 60,
            "draw_ticket_single": 30,    # 单抽券
            "draw_ticket_ten": 270,      # 十连券（9折）
        }
    )

    # ---------- 求婚 ----------
    marry_coin_cost: int = 100

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
                "reroll_ticket": 30,
                "lock_item": 50,
                "revive_potion": 80,
                "protection_charm": 60,
                "draw_ticket_single": 30,
                "draw_ticket_ten": 270,
            }

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
            pk_cooldown=_as_int(d.get("pk_cooldown"), 120),
            pk_max_per_day=_as_int(d.get("pk_max_per_day"), 5),
            ntr_max=_as_int(d.get("ntr_max"), 3),
            ntr_possibility=_as_float(d.get("ntr_possibility"), 0.20),
            revenge_window_hours=_as_int(d.get("revenge_window_hours"), 24),
            revenge_success_multiplier=_as_float(
                d.get("revenge_success_multiplier"), 2.0
            ),
            change_max_per_day=_as_int(d.get("change_max_per_day"), 3),
            swap_max_per_day=_as_int(d.get("swap_max_per_day"), 2),
            reset_max_uses_per_day=_as_int(d.get("reset_max_uses_per_day"), 3),
            reset_success_rate=_as_float(d.get("reset_success_rate"), 0.30),
            reset_mute_duration=_as_int(d.get("reset_mute_duration"), 300),
            intimacy_per_day=_as_int(d.get("intimacy_per_day"), 10),
            intimacy_max=_as_int(d.get("intimacy_max"), 100),
            intimacy_marry_threshold=_as_int(d.get("intimacy_marry_threshold"), 60),
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
            reroll_cost=_as_int(d.get("reroll_cost"), 30),
            pk_winner_reward=_as_int(d.get("pk_winner_reward"), 15),
            quest_complete_coins=_as_int(d.get("quest_complete_coins"), 10),
            shop_prices=shop_prices,
            marry_coin_cost=_as_int(d.get("marry_coin_cost"), 100),
        )

    @classmethod
    def default_for_test(cls) -> "PluginConfig":
        """单元测试用：全部默认值"""
        return cls()
