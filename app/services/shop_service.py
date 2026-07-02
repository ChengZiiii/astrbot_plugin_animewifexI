"""商城服务：道具购买。

道具清单（ROADMAP.md §5.1）：

* ``reroll_ticket``     - 抵扣换老婆消耗
* ``capacity_expansion`` - 扩容 +1
* ``lock_item``         - 限期锁定
* ``revive_potion``     - 被牛后复活
* ``protection_charm``  - 24h 免疫一次 NTR
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from ..models.profile import UserProfile
from ..storage.paths import Paths
from ..storage.stores import ProfileStore
from .economy_service import EconomyService
from .plugin_config import PluginConfig

logger = logging.getLogger("astrbot_plugin_animewifex.shop")

__all__ = ["ShopService"]

# 道具 key 与中文名映射
ITEM_NAMES: Dict[str, str] = {
    "reroll_ticket": "换老婆券",
    "capacity_expansion": "扩容卡",
    "lock_item": "锁定卡",
    "revive_potion": "复活药水",
    "protection_charm": "保护符",
}

# 使用上限（0 表示无上限）
ITEM_USE_LIMITS: Dict[str, int] = {
    "reroll_ticket": 0,
    "capacity_expansion": 0,
    "lock_item": 0,
    "revive_potion": 0,
    "protection_charm": 1,  # 同时只能持有 1 个
}


class ShopService:
    """商城服务。"""

    def __init__(self, paths: Paths, config: PluginConfig):
        self._paths = paths
        self._config = config
        self._economy = EconomyService(paths, config)

    def list_items(self) -> List[Tuple[str, str, int]]:
        """返回道具列表 [(key, name, price), ...]。"""
        result = []
        for key, name in ITEM_NAMES.items():
            price = self._config.shop_prices.get(key, 0)
            result.append((key, name, price))
        return result

    def get_item_price(self, item_key: str) -> Optional[int]:
        """获取道具价格，不存在返回 None。"""
        if item_key not in ITEM_NAMES:
            return None
        return self._config.shop_prices.get(item_key, 0)

    def buy(
        self,
        gid: str,
        uid: str,
        item_key: str,
        quantity: int = 1,
        nick: str = "",
    ) -> Tuple[bool, str]:
        """购买道具。返回 (成功, 消息)。"""
        if item_key not in ITEM_NAMES:
            return False, f"道具 {item_key} 不存在"

        if quantity <= 0:
            return False, "数量必须大于 0"

        price = self._config.shop_prices.get(item_key, 0)
        total_cost = price * quantity

        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick,
            self._config.default_capacity, self._config.initial_coins
        )

        # 检查余额
        if profile.coins < total_cost:
            logger.debug("buy: gid=%s uid=%s item=%s qty=%d -> insufficient (need %d, have %d)",
                         gid, uid, item_key, quantity, total_cost, profile.coins)
            return False, f"余额不足，需要 {total_cost} 币，当前 {profile.coins} 币"

        # 检查持有上限
        limit = ITEM_USE_LIMITS.get(item_key, 0)
        if limit > 0:
            current = profile.inventory.get(item_key, 0)
            if current + quantity > limit:
                logger.debug("buy: gid=%s uid=%s item=%s qty=%d -> limit exceeded (have %d, limit %d)",
                             gid, uid, item_key, quantity, current, limit)
                return False, f"{ITEM_NAMES[item_key]} 持有上限为 {limit}，当前已有 {current} 个"

        # 扣款 + 发货
        profile.coins -= total_cost
        profile.inventory[item_key] = profile.inventory.get(item_key, 0) + quantity
        store.save_all(profiles)

        logger.debug("buy: gid=%s uid=%s item=%s qty=%d cost=%d -> balance=%d, inventory=%d",
                     gid, uid, item_key, quantity, total_cost, profile.coins, profile.inventory[item_key])
        return True, f"购买成功！获得 {ITEM_NAMES[item_key]} x{quantity}，花费 {total_cost} 币"

    def use_item(
        self,
        gid: str,
        uid: str,
        item_key: str,
        nick: str = "",
    ) -> Tuple[bool, str]:
        """使用/消耗道具。返回 (成功, 消息)。"""
        if item_key not in ITEM_NAMES:
            return False, f"道具 {item_key} 不存在"

        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = ProfileStore.get_or_create(
            profiles, uid, nick,
            self._config.default_capacity, self._config.initial_coins
        )

        current = profile.inventory.get(item_key, 0)
        if current <= 0:
            return False, f"你没有 {ITEM_NAMES[item_key]}"

        profile.inventory[item_key] = current - 1
        store.save_all(profiles)

        logger.debug("use_item: gid=%s uid=%s item=%s -> remaining=%d",
                     gid, uid, item_key, profile.inventory[item_key])
        return True, f"使用 {ITEM_NAMES[item_key]} 成功，剩余 {profile.inventory[item_key]} 个"

    def get_inventory(self, gid: str, uid: str) -> Dict[str, int]:
        """获取用户背包（仅返回数量 > 0 的道具）。"""
        store = ProfileStore(self._paths, gid)
        profiles = store.load_all()
        profile = profiles.get(uid)
        if not profile:
            return {}
        return {k: v for k, v in profile.inventory.items() if v > 0}
