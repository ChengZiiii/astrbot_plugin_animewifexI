"""ShopService 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.profile import UserProfile
from app.services.plugin_config import PluginConfig
from app.services.shop_service import ITEM_NAMES, ShopService
from app.storage.paths import Paths
from app.storage.stores import ProfileStore


@pytest.fixture
def tmp_paths(tmp_path):
    return Paths(str(tmp_path))


@pytest.fixture
def config():
    return PluginConfig(
        initial_coins=200,
        shop_prices={
            "lock_item": 50,
            "protection_charm": 60,
            "insurance_card": 90,
        },
    )


@pytest.fixture
def shop(tmp_paths, config):
    return ShopService(tmp_paths, config)


def _seed_profile(paths: Paths, gid: str, uid: str, coins: int = 200):
    store = ProfileStore(paths, gid)
    profiles = store.load_all()
    profiles[uid] = UserProfile(uid=uid, nick="Alice", coins=coins)
    store.save_all(profiles)


class TestListItems:
    """商品列表测试。"""

    def test_list_items_count(self, shop):
        """道具数量正确。"""
        items = shop.list_items()
        assert len(items) == len(ITEM_NAMES)

    def test_list_items_format(self, shop):
        """道具格式正确。"""
        items = shop.list_items()
        for key, name, price in items:
            assert key in ITEM_NAMES
            assert name == ITEM_NAMES[key]
            assert isinstance(price, int) and price >= 0

    def test_get_item_price(self, shop):
        """获取道具价格。"""
        assert shop.get_item_price("lock_item") == 50
        assert shop.get_item_price("nonexistent") is None


class TestBuy:
    """购买测试。"""

    def test_buy_success(self, shop, tmp_paths):
        """购买成功。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        ok, msg = shop.buy_sync("g1", "u1", "lock_item", quantity=1)
        assert ok is True
        assert "购买成功" in msg

    def test_buy_deducts_coins(self, shop, tmp_paths):
        """购买扣款正确。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        shop.buy_sync("g1", "u1", "lock_item", quantity=1)  # 50 币
        store = ProfileStore(tmp_paths, "g1")
        profiles = store.load_all()
        assert profiles["u1"].coins == 150

    def test_buy_adds_to_inventory(self, shop, tmp_paths):
        """购买后背包增加。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        shop.buy_sync("g1", "u1", "lock_item", quantity=2)
        inv = shop.get_inventory("g1", "u1")
        assert inv.get("lock_item") == 2

    def test_buy_insufficient_balance(self, shop, tmp_paths):
        """余额不足。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=10)
        ok, msg = shop.buy_sync("g1", "u1", "lock_item", quantity=1)
        assert ok is False
        assert "余额不足" in msg

    def test_buy_nonexistent_item(self, shop, tmp_paths):
        """不存在的道具。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        ok, msg = shop.buy_sync("g1", "u1", "nonexistent_item", quantity=1)
        assert ok is False
        assert "不存在" in msg

    def test_buy_zero_quantity(self, shop, tmp_paths):
        """数量为 0 失败。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        ok, msg = shop.buy_sync("g1", "u1", "lock_item", quantity=0)
        assert ok is False

    def test_buy_negative_quantity(self, shop, tmp_paths):
        """数量为负失败。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        ok, msg = shop.buy_sync("g1", "u1", "lock_item", quantity=-1)
        assert ok is False

    def test_buy_protection_charm_limit(self, shop, tmp_paths):
        """保护符持有上限。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=500)
        # 第一个成功
        ok1, _ = shop.buy_sync("g1", "u1", "protection_charm", quantity=1)
        assert ok1 is True
        # 第二个失败（上限 1）
        ok2, msg = shop.buy_sync("g1", "u1", "protection_charm", quantity=1)
        assert ok2 is False
        assert "上限" in msg

    def test_buy_insurance_card_limit(self, shop, tmp_paths):
        _seed_profile(tmp_paths, "g1", "u1", coins=500)
        ok1, _ = shop.buy_sync("g1", "u1", "insurance_card", quantity=1)
        assert ok1 is True
        ok2, msg = shop.buy_sync("g1", "u1", "insurance_card", quantity=1)
        assert ok2 is False
        assert "上限" in msg

    def test_buy_creates_profile_if_needed(self, shop, tmp_paths):
        """不存在的用户自动创建。"""
        ok, _ = shop.buy_sync("g1", "u1", "lock_item", quantity=1, nick="Alice")
        assert ok is True


class TestUseItem:
    """使用道具测试。"""

    def test_use_success(self, shop, tmp_paths):
        """使用成功。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        shop.buy_sync("g1", "u1", "lock_item", quantity=2)
        ok, msg = shop.use_item_sync("g1", "u1", "lock_item")
        assert ok is True
        assert "剩余 1" in msg

    def test_use_empty_inventory(self, shop, tmp_paths):
        """背包为空时使用失败。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        ok, msg = shop.use_item_sync("g1", "u1", "lock_item")
        assert ok is False
        assert "没有" in msg

    def test_use_nonexistent_item(self, shop, tmp_paths):
        """不存在的道具。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        ok, msg = shop.use_item_sync("g1", "u1", "nonexistent")
        assert ok is False

    def test_use_deducts_inventory(self, shop, tmp_paths):
        """使用后背包减少。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=200)
        shop.buy_sync("g1", "u1", "lock_item", quantity=2)
        shop.use_item_sync("g1", "u1", "lock_item")
        inv = shop.get_inventory("g1", "u1")
        assert inv.get("lock_item") == 1


class TestGetInventory:
    """背包查询测试。"""

    def test_empty_inventory(self, shop, tmp_paths):
        """空背包返回空字典。"""
        _seed_profile(tmp_paths, "g1", "u1")
        inv = shop.get_inventory("g1", "u1")
        assert inv == {}

    def test_inventory_after_buy(self, shop, tmp_paths):
        """购买后背包正确。"""
        _seed_profile(tmp_paths, "g1", "u1", coins=500)
        shop.buy_sync("g1", "u1", "lock_item", quantity=2)
        shop.buy_sync("g1", "u1", "lock_item", quantity=1)
        inv = shop.get_inventory("g1", "u1")
        assert inv["lock_item"] == 3

    def test_inventory_nonexistent_user(self, shop, tmp_paths):
        """不存在的用户返回空。"""
        inv = shop.get_inventory("g1", "u1")
        assert inv == {}
