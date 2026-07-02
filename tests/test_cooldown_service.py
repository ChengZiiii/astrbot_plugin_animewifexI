"""CooldownService 单元测试。"""

from __future__ import annotations

import time

import pytest

from app.services.cooldown_service import CooldownService
from app.storage.locks import GroupLocks


@pytest.fixture
def cooldown():
    return CooldownService(GroupLocks())


class TestCooldownCheck:
    def test_no_history_allows(self, cooldown):
        assert cooldown.check("g1", "u1", "ntr", 60) is True

    def test_zero_cooldown_always_allows(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 0) is True

    def test_within_cooldown_blocks(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 60) is False

    def test_after_cooldown_allows(self, cooldown):
        cooldown.update("g1", "u1", "ntr", ts=time.time() - 61)
        assert cooldown.check("g1", "u1", "ntr", 60) is True

    def test_exact_boundary_blocks(self, cooldown):
        cooldown.update("g1", "u1", "ntr", ts=time.time() - 60)
        # At exactly 60s, (time.time() - last) >= 60 should be True
        assert cooldown.check("g1", "u1", "ntr", 60) is True

    def test_different_users_independent(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 60) is False
        assert cooldown.check("g1", "u2", "ntr", 60) is True

    def test_different_groups_independent(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 60) is False
        assert cooldown.check("g2", "u1", "ntr", 60) is True

    def test_different_actions_independent(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 60) is False
        assert cooldown.check("g1", "u1", "draw", 60) is True


class TestCooldownRemaining:
    def test_no_history_returns_zero(self, cooldown):
        assert cooldown.remaining("g1", "u1", "ntr", 60) == 0

    def test_zero_cooldown_returns_zero(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.remaining("g1", "u1", "ntr", 0) == 0

    def test_within_cooldown_returns_positive(self, cooldown):
        cooldown.update("g1", "u1", "ntr", ts=time.time() - 10)
        r = cooldown.remaining("g1", "u1", "ntr", 60)
        assert 49 <= r <= 51  # ~50 seconds remaining

    def test_expired_returns_zero(self, cooldown):
        cooldown.update("g1", "u1", "ntr", ts=time.time() - 61)
        assert cooldown.remaining("g1", "u1", "ntr", 60) == 0


class TestCooldownUpdateReset:
    def test_update_then_reset(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 60) is False
        cooldown.reset("g1", "u1", "ntr")
        assert cooldown.check("g1", "u1", "ntr", 60) is True

    def test_reset_nonexistent_is_noop(self, cooldown):
        cooldown.reset("g1", "u1", "ntr")  # should not raise

    def test_reset_cleans_empty_dicts(self, cooldown):
        cooldown.update("g1", "u1", "ntr")
        cooldown.reset("g1", "u1", "ntr")
        # Internal table should be clean
        assert cooldown._table.get("g1") is None or cooldown._table["g1"].get("u1") is None
