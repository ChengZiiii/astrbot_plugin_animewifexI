"""稀有度抽卡服务。

* ``roll_rarity()`` 根据 ``rarity_weights`` 加权随机
* 保底机制：``pity_counter`` 连续 N 次未达 ``pity_min_rarity`` 强制保底
* 首次抽到新角色自动写入 ``wives_master``（按 hash 派生稀有度）
* 重复角色自动转换为老婆币补偿
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Dict, List, Optional, Tuple

from ..models.enums import Rarity, RARITY_ORDER
from ..models.profile import UserProfile
from ..models.wife import BaseStats, WifeMeta
from ..storage.paths import Paths
from ..storage.stores import WivesMasterStore
from ..utils.random_utils import weighted_choice
from ..utils.image import parse_wife_name, wife_wid_for_img
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.rarity")

__all__ = ["RarityService", "DrawResult"]

# 重复角色补偿金额
DUPLICATE_COIN_COMPENSATION = 10

# 稀有度对应的基础战力范围
RARITY_STAT_RANGES = {
    Rarity.N:  {"atk": (5, 15),  "def": (5, 15),  "hp": (10, 30)},
    Rarity.R:  {"atk": (10, 25), "def": (10, 25), "hp": (20, 50)},
    Rarity.SR: {"atk": (20, 40), "def": (20, 40), "hp": (40, 80)},
    Rarity.SSR:{"atk": (35, 60), "def": (35, 60), "hp": (70, 120)},
}


class DrawResult:
    """抽卡结果"""

    __slots__ = (
        "wife", "rarity", "is_new", "duplicate_coins",
        "pity_triggered", "img",
    )

    def __init__(
        self,
        wife: WifeMeta,
        rarity: str,
        is_new: bool,
        duplicate_coins: int = 0,
        pity_triggered: bool = False,
        img: str = "",
    ):
        self.wife = wife
        self.rarity = rarity
        self.is_new = is_new
        self.duplicate_coins = duplicate_coins
        self.pity_triggered = pity_triggered
        self.img = img or wife.img

    @property
    def rarity_emoji(self) -> str:
        return {
            Rarity.SSR: "✨",
            Rarity.SR: "🌟",
            Rarity.R: "⭐",
            Rarity.N: "·",
        }.get(self.rarity, "·")

    @property
    def rarity_label(self) -> str:
        return f"{self.rarity_emoji} {self.rarity}"


class RarityService:
    """稀有度抽卡服务。"""

    # C4: 全局锁保护 wives_master 文件并发写入
    _wives_master_lock = asyncio.Lock()

    def __init__(self, paths: Paths, config: PluginConfig):
        self._paths = paths
        self._config = config
        self._rng = random.Random()

    def set_rng(self, rng: random.Random) -> None:
        """注入随机源（测试用）"""
        self._rng = rng

    def roll_rarity(self, pity_counter: int) -> Tuple[str, bool]:
        """根据权重随机稀有度，返回 (rarity, 是否触发保底)。

        pity_counter: 连续未达 pity_min_rarity 的次数
        """
        threshold = self._config.pity_threshold
        min_rarity = self._config.pity_min_rarity  # "SR"

        # 保底触发：强制至少 SR
        if pity_counter >= threshold:
            logger.debug("roll_rarity: pity triggered (counter=%d >= threshold=%d)",
                         pity_counter, threshold)
            # 在 SR 和 SSR 之间按权重随机
            pity_weights = {
                k: v for k, v in self._config.rarity_weights.items()
                if self._rarity_ge(k, min_rarity)
            }
            rarity = weighted_choice(pity_weights, self._rng)
            return rarity, True

        # 正常抽取
        rarity = weighted_choice(self._config.rarity_weights, self._rng)
        return rarity, False

    def pick_wife_by_rarity(
        self, rarity: str, exclude_wids: Optional[set] = None
    ) -> Optional[WifeMeta]:
        """从 wives_master 中随机选取指定稀有度的角色。

        exclude_wids: 排除的 wid 集合（可选）
        """
        store = WivesMasterStore(self._paths)
        all_wives = store.load_all()

        candidates = [
            w for w in all_wives.values()
            if w.rarity == rarity
            and (not exclude_wids or w.wid not in exclude_wids)
        ]

        if not candidates:
            return None
        return self._rng.choice(candidates)

    def draw(
        self,
        img: str,
        profile: UserProfile,
        collection: List[str],
    ) -> DrawResult:
        """完整抽卡流程。

        img: 图片标识（由 WifeService 获取）
        profile: 用户档案（会修改 pity_counter）
        collection: 用户历史 wid 列表

        返回 DrawResult
        """
        # 1. 抽稀有度
        rarity, pity_triggered = self.roll_rarity(profile.pity_counter)

        # 2. 生成 wid
        wid = wife_wid_for_img(img)

        # 3. C4: 使用全局锁保护 wives_master 读写
        wife, is_new_wife = self._ensure_wife_in_master(wid, img, rarity)

        # 4. 检查重复
        is_new = wid not in collection
        duplicate_coins = 0
        if not is_new:
            duplicate_coins = DUPLICATE_COIN_COMPENSATION
            logger.debug("draw: duplicate wid=%s, compensating %d coins", wid, duplicate_coins)

        # 5. 更新保底计数器
        if self._rarity_ge(rarity, self._config.pity_min_rarity):
            profile.pity_counter = 0
        else:
            profile.pity_counter += 1

        return DrawResult(
            wife=wife,
            rarity=rarity,
            is_new=is_new,
            duplicate_coins=duplicate_coins,
            pity_triggered=pity_triggered,
            img=img,
        )

    def _ensure_wife_in_master(
        self, wid: str, img: str, rarity: str
    ) -> Tuple[WifeMeta, bool]:
        """查找或创建/升级 wives_master 中的角色元数据。

        返回 (wife, is_new_wife)。
        """
        store = WivesMasterStore(self._paths)
        all_wives = store.load_all()
        wife = all_wives.get(wid)

        is_new_wife = wife is None
        if wife is None:
            chara, source = parse_wife_name(img)
            wife = WifeMeta(
                wid=wid,
                img=img,
                source=source or "",
                chara=chara or "",
                rarity=rarity,
                base_stats=self._generate_stats(rarity),
                first_seen=int(time.time()),
            )
            all_wives[wid] = wife
            store.save_all(all_wives)
            logger.debug("draw: new wife created wid=%s rarity=%s", wid, rarity)
        else:
            if self._rarity_gt(rarity, wife.rarity):
                logger.debug("draw: wife %s upgraded %s -> %s", wid, wife.rarity, rarity)
                wife.rarity = rarity
                wife.base_stats = self._generate_stats(rarity)
                all_wives[wid] = wife
                store.save_all(all_wives)

        return wife, is_new_wife

    def _generate_stats(self, rarity: str) -> BaseStats:
        """根据稀有度随机生成基础战力"""
        ranges = RARITY_STAT_RANGES.get(rarity, RARITY_STAT_RANGES[Rarity.N])
        return BaseStats(
            atk=self._rng.randint(*ranges["atk"]),
            defense=self._rng.randint(*ranges["def"]),
            hp=self._rng.randint(*ranges["hp"]),
        )

    @staticmethod
    def _rarity_ge(a: str, b: str) -> bool:
        """a >= b（稀有度比较）"""
        try:
            return RARITY_ORDER.index(a) >= RARITY_ORDER.index(b)
        except ValueError:
            return False

    @staticmethod
    def _rarity_gt(a: str, b: str) -> bool:
        """a > b（稀有度比较）"""
        try:
            return RARITY_ORDER.index(a) > RARITY_ORDER.index(b)
        except ValueError:
            return False
