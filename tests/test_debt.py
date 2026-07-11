"""负债经济系统单元测试。

Covers: v3_经济_负债_分币.md [S4.3][S4.4][S4.5]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.plugin_config import PluginConfig


# =============================================================================
# Part 1: Pure function tests (try_deduct / apply_income)
# =============================================================================


class TestTryDeduct:
    """try_deduct 触底保护测试。"""

    def test_normal_deduct_positive(self):
        from app.services.economy_service import try_deduct

        success, new = try_deduct(100, 50)
        assert success is True
        assert new == 50

    def test_deduct_negative_stays_above_floor(self):
        """-400 扣 50 → -450 (>= -500)，允许。"""
        from app.services.economy_service import try_deduct

        success, new = try_deduct(-400, 50)
        assert success is True
        assert new == -450

    def test_deduct_below_floor_rejected(self):
        """-480 扣 50 → -530 (< -500)，拒绝。"""
        from app.services.economy_service import try_deduct

        success, new = try_deduct(-480, 50)
        assert success is False
        assert new == -480

    def test_deduct_at_floor_rejected(self):
        """-500 扣 1 → -501 (< -500)，拒绝。"""
        from app.services.economy_service import try_deduct

        success, new = try_deduct(-500, 1)
        assert success is False
        assert new == -500


class TestApplyIncome:
    """apply_income 优先抵债测试。"""

    def test_income_with_negative_balance_partial(self):
        from app.services.economy_service import apply_income

        assert apply_income(-100, 50) == -50

    def test_income_with_negative_balance_full(self):
        from app.services.economy_service import apply_income

        assert apply_income(-100, 150) == 50

    def test_income_with_zero_balance(self):
        from app.services.economy_service import apply_income

        assert apply_income(0, 30) == 30

    def test_income_with_positive_balance(self):
        from app.services.economy_service import apply_income

        assert apply_income(100, 30) == 130


# =============================================================================
# Part 2: EconomyService integration
# =============================================================================


class TestEconomyServiceDebt:
    """EconomyService 内部集成 try_deduct/apply_income 后的行为。"""

    @pytest.fixture
    def tmp_paths(self, tmp_path):
        from app.storage.paths import Paths

        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        return paths

    @pytest.fixture
    def config(self):
        return PluginConfig(initial_coins=0)

    @pytest.fixture
    def economy(self, tmp_paths, config):
        from app.services.economy_service import EconomyService

        return EconomyService(tmp_paths, config)

    def test_spend_allows_negative_balance(self, economy):
        """spend 允许扣到负余额（不超过 DEBT_FLOOR）。"""
        economy.earn_sync("g1", "u1", 20, nick="Alice")
        # 余额 20，扣 30 → -10，返回 True
        assert economy.spend_sync("g1", "u1", 30) is True
        assert economy.balance("g1", "u1") == -10

    def test_spend_respects_debt_floor(self, economy):
        """spend 不能低于 DEBT_FLOOR。"""
        economy.earn_sync("g1", "u1", 20, nick="Alice")
        # 扣 500 → -480（成功）
        assert economy.spend_sync("g1", "u1", 500) is True
        assert economy.balance("g1", "u1") == -480
        # 再扣 30 → -510 会触底，拒绝
        assert economy.spend_sync("g1", "u1", 30) is False
        assert economy.balance("g1", "u1") == -480  # 不变

    def test_deduct_coins_from_profile_allows_negative(self, economy):
        """deduct_coins_from_profile 允许余额变负。"""
        from app.models.profile import UserProfile

        profile = UserProfile(uid="u1", nick="Alice", coins=20)
        assert economy.deduct_coins_from_profile(profile, 30) is True
        assert profile.coins == -10

    def test_deduct_coins_from_profile_respects_floor(self, economy):
        """deduct_coins_from_profile 不能低于 DEBT_FLOOR。"""
        from app.models.profile import UserProfile

        profile = UserProfile(uid="u1", nick="Alice", coins=-480)
        assert economy.deduct_coins_from_profile(profile, 30) is False
        assert profile.coins == -480  # 不变

    def test_earn_accumulates(self, economy):
        """earn 正常工作（正余额累加）。"""
        economy.earn_sync("g1", "u1", 50, nick="Alice")
        assert economy.balance("g1", "u1") == 50

    def test_earn_reduces_debt(self, economy):
        """earn 在负余额时自动还债。"""
        # 先花到负余额
        economy.earn_sync("g1", "u1", 20, nick="Alice")
        economy.spend_sync("g1", "u1", 50)
        assert economy.balance("g1", "u1") == -30
        # 收入 20 → 余额 -10
        economy.earn_sync("g1", "u1", 20, nick="Alice")
        assert economy.balance("g1", "u1") == -10


# =============================================================================
# Part 3: 联动限制 — 打工拦截
# =============================================================================


class TestDebtWorkBlock:
    """负债时打工拦截测试。"""

    @pytest.fixture
    def tmp_paths(self, tmp_path):
        from app.storage.paths import Paths

        paths = Paths(str(tmp_path))
        paths.ensure_dirs()
        return paths

    @pytest.fixture
    def config(self):
        return PluginConfig(initial_coins=0, work_enabled=True)

    @pytest.fixture
    def locks(self):
        from app.storage.locks import GroupLocks

        return GroupLocks()

    def _setup_wife(self, paths, gid, uid):
        """快速给用户一个主老婆。"""
        from app.storage.stores import OwnershipStore
        from app.models.ownership import Ownership
        from app.models.enums import AcquireVia
        from app.utils.time import now_ts

        store = OwnershipStore(paths, gid)
        ownerships = store.load_all()
        ownership = Ownership(
            wid="w1",
            uid=uid,
            acquired_at=now_ts(),
            acquired_via=AcquireVia.DRAW,
            is_primary=True,
        )
        store.add(ownerships, ownership)
        store.save_all(ownerships)

    def _set_balance(self, paths, gid, uid, coins):
        """设置用户余额。"""
        from app.storage.stores import ProfileStore
        from app.models.profile import UserProfile

        store = ProfileStore(paths, gid)
        profiles = store.load_all()
        profiles[uid] = UserProfile(uid=uid, nick="Alice", coins=coins)
        store.save_all(profiles)

    async def test_start_work_refused_when_in_debt(self, tmp_paths, config, locks):
        """负债（余额 -100）时不能启动打工。"""
        from app.services.work_service import WorkService

        svc = WorkService(tmp_paths, config, locks)
        self._setup_wife(tmp_paths, "g1", "u1")
        self._set_balance(tmp_paths, "g1", "u1", -100)

        result = await svc.start_work("g1", "u1", "Alice", "normal", "2026-07-12")
        assert result.ok is False
        assert result.reason == "in_debt"

    async def test_start_work_succeeds_with_positive_balance(self, tmp_paths, config, locks):
        """正余额可正常启动打工。"""
        from app.services.work_service import WorkService

        svc = WorkService(tmp_paths, config, locks)
        self._setup_wife(tmp_paths, "g1", "u1")
        self._set_balance(tmp_paths, "g1", "u1", 50)

        result = await svc.start_work("g1", "u1", "Alice", "normal", "2026-07-12")
        assert result.ok is True

    async def test_start_work_refused_when_below_start_cost(self, tmp_paths, config, locks):
        """正余额但低于启动费（已有逻辑）。"""
        from app.services.work_service import WorkService

        svc = WorkService(tmp_paths, config, locks)
        self._setup_wife(tmp_paths, "g1", "u1")
        self._set_balance(tmp_paths, "g1", "u1", 5)  # < start_cost=10

        result = await svc.start_work("g1", "u1", "Alice", "normal", "2026-07-12")
        assert result.ok is False


# =============================================================================
# Part 4: 配置项
# =============================================================================


class TestDebtConfig:
    """负债配置项测试。"""

    def test_debt_config_defaults(self):
        """默认负债配置项。"""
        config = PluginConfig.default_for_test()
        assert config.debt_floor == -500
        assert config.debt_block_work is True
        assert config.debt_block_shop is True
        assert config.debt_block_single_draw is True
        assert config.debt_allow_ticket_draw is True

    def test_debt_config_from_dict(self):
        """从 dict 加载负债配置。"""
        config = PluginConfig.from_dict({
            "debt_floor": -1000,
            "debt_block_work": False,
            "debt_block_shop": False,
            "debt_block_single_draw": False,
            "debt_allow_ticket_draw": False,
        })
        assert config.debt_floor == -1000
        assert config.debt_block_work is False
        assert config.debt_block_shop is False
        assert config.debt_block_single_draw is False
        assert config.debt_allow_ticket_draw is False

    def test_debt_config_missing_keys_default(self):
        """缺失的负债配置项使用默认值。"""
        config = PluginConfig.from_dict({})
        assert config.debt_floor == -500
        assert config.debt_block_work is True
