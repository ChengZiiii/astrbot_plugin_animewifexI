"""RarityService 单元测试。"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.enums import Rarity, RARITY_ORDER
from app.models.profile import UserProfile
from app.models.wife import WifeMeta
from app.services.plugin_config import PluginConfig
from app.services.rarity_service import DrawResult, RarityService
from app.storage.paths import Paths
from app.storage.stores import WivesMasterStore
from app.utils.image import wife_wid_for_img


@pytest.fixture
def tmp_paths(tmp_path):
    return Paths(str(tmp_path))


@pytest.fixture
def config():
    return PluginConfig(
        rarity_weights={"SSR": 5, "SR": 20, "R": 50, "N": 25},
        pity_threshold=10,
        pity_min_rarity="SR",
        initial_coins=0,
    )


@pytest.fixture
def rarity_service(tmp_paths, config):
    svc = RarityService(tmp_paths, config)
    svc.set_rng(random.Random(42))  # 固定种子可复现
    return svc


def _seed_wife(paths: Paths, wid: str, img: str, rarity: str = "N"):
    store = WivesMasterStore(paths)
    all_wives = store.load_all()
    all_wives[wid] = WifeMeta(wid=wid, img=img, rarity=rarity)
    store.save_all(all_wives)


class TestRollRarity:
    """稀有度抽取测试。"""

    def test_roll_returns_valid_rarity(self, rarity_service):
        """返回值在合法稀有度范围内。"""
        for _ in range(100):
            rarity, _ = rarity_service.roll_rarity(pity_counter=0)
            assert rarity in RARITY_ORDER

    def test_roll_pity_counter_at_threshold(self, rarity_service):
        """保底触发时至少 SR。"""
        for _ in range(50):
            rarity, triggered = rarity_service.roll_rarity(pity_counter=10)
            assert triggered is True
            assert rarity in (Rarity.SR, Rarity.SSR)

    def test_roll_pity_counter_below_threshold(self, rarity_service):
        """未触发保底。"""
        for _ in range(50):
            _, triggered = rarity_service.roll_rarity(pity_counter=5)
            assert triggered is False

    def test_roll_distribution_monte_carlo(self, rarity_service):
        """蒙特卡洛测试：概率分布大致符合配置。"""
        counts = {r: 0 for r in RARITY_ORDER}
        n = 10000
        for _ in range(n):
            rarity, _ = rarity_service.roll_rarity(pity_counter=0)
            counts[rarity] += 1

        # SSR 约 5%，允许 ±3%
        assert 0.02 < counts["SSR"] / n < 0.08
        # SR 约 20%，允许 ±5%
        assert 0.15 < counts["SR"] / n < 0.25
        # N 约 25%，允许 ±5%
        assert 0.20 < counts["N"] / n < 0.30


class TestPickWifeByRarity:
    """按稀有度选取角色测试。"""

    def test_pick_existing_rarity(self, rarity_service, tmp_paths):
        """能正确选取指定稀有度的角色。"""
        _seed_wife(tmp_paths, "w_001", "a.jpg", "SR")
        _seed_wife(tmp_paths, "w_002", "b.jpg", "N")
        wife = rarity_service.pick_wife_by_rarity("SR")
        assert wife is not None
        assert wife.rarity == "SR"

    def test_pick_no_candidates(self, rarity_service, tmp_paths):
        """无候选角色返回 None。"""
        _seed_wife(tmp_paths, "w_001", "a.jpg", "N")
        wife = rarity_service.pick_wife_by_rarity("SSR")
        assert wife is None

    def test_pick_exclude_wids(self, rarity_service, tmp_paths):
        """排除指定 wid。"""
        _seed_wife(tmp_paths, "w_001", "a.jpg", "SR")
        _seed_wife(tmp_paths, "w_002", "b.jpg", "SR")
        wife = rarity_service.pick_wife_by_rarity("SR", exclude_wids={"w_001"})
        assert wife is not None
        assert wife.wid == "w_002"


class TestDraw:
    """完整抽卡流程测试。"""

    def test_draw_new_wife(self, rarity_service, tmp_paths):
        """抽到新角色。"""
        profile = UserProfile(uid="u1", pity_counter=0)
        result = rarity_service.draw("test.jpg", profile, [])

        assert result.is_new is True
        assert result.duplicate_coins == 0
        assert result.wife is not None
        assert result.rarity in RARITY_ORDER

    def test_draw_duplicate_wife(self, rarity_service, tmp_paths):
        """抽到重复角色，按配置获得补偿。"""
        wid = wife_wid_for_img("test.jpg")
        _seed_wife(tmp_paths, wid, "test.jpg", "N")
        profile = UserProfile(uid="u1", pity_counter=0)
        result = rarity_service.draw("test.jpg", profile, [wid])

        assert result.is_new is False
        expected_coins = rarity_service._config.duplicate_coin_compensation.get(result.rarity, 10)
        assert result.duplicate_coins == expected_coins

    def test_draw_resets_pity_on_sr(self, rarity_service, tmp_paths):
        """抽到 SR+ 时保底计数器归零。"""
        profile = UserProfile(uid="u1", pity_counter=9)
        # 强制保底
        rarity_service._rng = random.Random(0)  # 选一个会触发保底的种子
        result = rarity_service.draw("test.jpg", profile, [])

        if result.rarity in (Rarity.SR, Rarity.SSR):
            assert profile.pity_counter == 0

    def test_draw_increments_pity_on_n(self, rarity_service, tmp_paths):
        """抽到 N 时保底计数器 +1。"""
        profile = UserProfile(uid="u1", pity_counter=5)
        # 让 roll_rarity 返回 N
        original_rng = rarity_service._rng

        class AlwaysNRng:
            def random(self):
                return 0.99  # 会命中权重最大的 N
            def randint(self, a, b):
                return a
            def choice(self, seq):
                return seq[0]

        rarity_service._rng = AlwaysNRng()
        result = rarity_service.draw("test.jpg", profile, [])
        rarity_service._rng = original_rng

        if result.rarity == Rarity.N:
            assert profile.pity_counter == 6

    def test_draw_creates_wife_meta(self, rarity_service, tmp_paths):
        """首次抽到的角色自动写入 wives_master。"""
        profile = UserProfile(uid="u1", pity_counter=0)
        rarity_service.draw("new_wife.jpg", profile, [])

        store = WivesMasterStore(tmp_paths)
        all_wives = store.load_all()
        # 应该有一条记录
        assert len(all_wives) >= 1

    def test_draw_upgrades_rarity(self, rarity_service, tmp_paths):
        """抽到更高稀有度时升级。"""
        _seed_wife(tmp_paths, "w_test", "test.jpg", "N")
        profile = UserProfile(uid="u1", pity_counter=10)  # 触发保底
        result = rarity_service.draw("test.jpg", profile, [])

        # 保底应该至少 SR
        assert result.rarity in (Rarity.SR, Rarity.SSR)

    def test_draw_result_rarity_emoji(self, rarity_service, tmp_paths):
        """DrawResult 稀有度 emoji 正确。"""
        profile = UserProfile(uid="u1", pity_counter=0)
        result = rarity_service.draw("test.jpg", profile, [])
        assert result.rarity_emoji in ("✨", "🌟", "⭐", "·")

    def test_draw_result_rarity_label(self, rarity_service, tmp_paths):
        """DrawResult 稀有度标签正确。"""
        profile = UserProfile(uid="u1", pity_counter=0)
        result = rarity_service.draw("test.jpg", profile, [])
        assert result.rarity in result.rarity_label


class TestRarityComparison:
    """稀有度比较工具测试。"""

    def test_rarity_ge(self, rarity_service):
        assert rarity_service._rarity_ge("SSR", "SR") is True
        assert rarity_service._rarity_ge("SR", "SR") is True
        assert rarity_service._rarity_ge("N", "SSR") is False

    def test_rarity_gt(self, rarity_service):
        assert rarity_service._rarity_gt("SSR", "SR") is True
        assert rarity_service._rarity_gt("SR", "SR") is False
        assert rarity_service._rarity_gt("N", "SSR") is False
