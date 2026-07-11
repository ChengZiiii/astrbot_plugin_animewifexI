"""老婆 查负债 命令单元测试。

Task G.1 / v3_经济_负债_分币.md [S7.1]：
- 查自己的负债状态（余额为负）
- 查他人的负债状态（@xxx）
- 余额为正时正常显示不标负债
"""

from __future__ import annotations

from typing import List

import pytest

from app.models.profile import UserProfile
from app.storage.stores import ProfileStore


# ========== Mock objects ==========


class _MockMessageObj:
    def __init__(self, gid: str, at_target: str = ""):
        self.group_id = gid
        self.message = []
        if at_target:
            # 使用 astrbot stub 的 At 类，确保 isinstance 检查通过
            from astrbot.api.message_components import At
            self.message.append(At(qq=at_target))


class _MockEvent:
    """最小化 AstrMessageEvent 桩，足以驱动查负债命令。"""

    def __init__(
        self,
        gid: str,
        uid: str,
        nick: str,
        message: str,
        at_target: str = "",
    ):
        self.message_str = message
        self.message_obj = _MockMessageObj(gid, at_target=at_target)
        self._uid = uid
        self._nick = nick
        self._gid = gid
        self.replies: List[str] = []

    def get_sender_id(self):
        return self._uid

    def get_sender_name(self):
        return self._nick

    def get_self_id(self):
        return "bot"

    def plain_result(self, text: str):
        self.replies.append(text)
        return text

    def chain_result(self, chain):
        self.replies.append(str(chain))
        return chain


def _make_ctx(tmp_paths, config, locks):
    from app.commands.context import CommandContext
    from app.services.ownership_service import OwnershipService
    from app.services.wife_service import WifeService

    class _MinimalWifeService(WifeService):
        def __init__(self):
            pass

        async def fetch_image(self):
            return None

    from zoneinfo import ZoneInfo

    return CommandContext(
        paths=tmp_paths,
        config=config,
        locks=locks,
        ownership_service=None,
        wife_service=_MinimalWifeService(),
        cooldown_service=None,
        tz=ZoneInfo("Asia/Shanghai"),
    )


def _set_profile(tmp_paths, gid, uid, nick, coins):
    """设置用户余额。"""
    store = ProfileStore(tmp_paths, gid)
    profiles = store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile.coins = coins
    store.save_all(profiles)
    return profile


# ========== Tests ==========


class TestDebtQuerySelf:
    """查自己负债状态。"""

    @pytest.mark.asyncio
    async def test_negative_balance_shows_debt_info(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        _set_profile(tmp_paths, gid, uid, nick, -150)

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 查负债")

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "Alice" in joined or "你" in joined
        assert "-150" in joined
        assert "触底保护" in joined
        assert "-500" in joined
        assert "距触底" in joined
        assert "350" in joined
        assert "利息" in joined
        assert "0%" in joined

    @pytest.mark.asyncio
    async def test_positive_balance_shows_normal(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        _set_profile(tmp_paths, gid, uid, nick, 200)

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 查负债")

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "200" in joined
        assert "触底保护" in joined
        assert "距触底" in joined
        # 正余额时距离触底 = 余额 - floor = 200 - (-500) = 700
        assert "700" in joined

    @pytest.mark.asyncio
    async def test_zero_balance_shows_normal(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        _set_profile(tmp_paths, gid, uid, nick, 0)

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 查负债")

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "0" in joined
        assert "距触底" in joined
        assert "500" in joined  # 0 - (-500) = 500

    @pytest.mark.asyncio
    async def test_no_profile_uses_zero(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        # 不创建 profile
        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 查负债")

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "0" in joined
        assert "触底保护" in joined

    @pytest.mark.asyncio
    async def test_at_floor_shows_zero_distance(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        _set_profile(tmp_paths, gid, uid, nick, -500)

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 查负债")

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "-500" in joined
        assert "距触底" in joined
        assert "0" in joined or "已达" in joined


class TestDebtQueryOther:
    """查他人负债（@xxx）。"""

    @pytest.mark.asyncio
    async def test_query_other_by_at(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        target_uid = "u2"
        target_nick = "Bob"
        _set_profile(tmp_paths, gid, target_uid, target_nick, -80)

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(
            gid, uid, nick, "老婆 查负债", at_target=target_uid
        )

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "Bob" in joined or target_nick in joined
        assert "-80" in joined
        assert "距触底" in joined
        assert "420" in joined  # -80 - (-500) = 420

    @pytest.mark.asyncio
    async def test_query_other_positive_balance(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        target_uid = "u2"
        target_nick = "Bob"
        _set_profile(tmp_paths, gid, target_uid, target_nick, 999)

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(
            gid, uid, nick, "老婆 查负债", at_target=target_uid
        )

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "Bob" in joined or target_nick in joined
        assert "999" in joined
        assert "1499" in joined  # 999 - (-500) = 1499

    @pytest.mark.asyncio
    async def test_query_other_no_profile(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        gid, uid, nick = "g1", "u1", "Alice"
        target_uid = "u2"
        # 不给 target 建 profile
        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(
            gid, uid, nick, "老婆 查负债", at_target=target_uid
        )

        async for _ in handle_debt_query(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "0" in joined
        assert "触底保护" in joined


class TestDebtQueryNonGroup:
    """非群聊事件应跳过。"""

    @pytest.mark.asyncio
    async def test_non_group_event_returns_nothing(
        self, tmp_paths, config, locks
    ):
        from app.commands.debt import handle_debt_query

        class NonGroupEvent:
            def __init__(self):
                self.message_str = "老婆 查负债"
                self.message_obj = type("Msg", (), {"group_id": None})()

            def get_sender_id(self):
                return "u1"

            def get_sender_name(self):
                return "Alice"

            def plain_result(self, text):
                return text

            async def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        event = NonGroupEvent()
        results = []
        async for item in handle_debt_query(event, ctx=None):
            results.append(item)
        assert len(results) == 0
