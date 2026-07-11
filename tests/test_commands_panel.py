"""老婆 面板 命令单元测试 — 负债状态 + NTR 战绩。

Task G.2 / v3_经济_负债_分币.md [S7.3]：
- 余额为负时显示 ⚠️ 负债
- 新增 NTR 战绩行
- 无 NTR 记录时显示简洁模式
"""

from __future__ import annotations

from typing import List

import pytest

from app.models.ownership import Ownership
from app.models.profile import UserProfile
from app.models.wife import BaseStats, WifeMeta
from app.storage.stores import OwnershipStore, ProfileStore, WivesMasterStore


# ========== Mock objects ==========


class _MockMessageObj:
    def __init__(self, gid: str):
        self.group_id = gid
        self.message = []


class _MockEvent:
    """最小化 AstrMessageEvent 桩，足以驱动面板命令。"""

    def __init__(self, gid: str, uid: str, nick: str, message: str):
        self.message_str = message
        self.message_obj = _MockMessageObj(gid)
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

    from zoneinfo import ZoneInfo

    return CommandContext(
        paths=tmp_paths,
        config=config,
        locks=locks,
        ownership_service=None,
        wife_service=None,
        cooldown_service=None,
        tz=ZoneInfo("Asia/Shanghai"),
    )


def _setup_profile(tmp_paths, gid, uid, nick, coins, ntr_lost=0, ntr_comfort=0):
    """设置用户档案。"""
    store = ProfileStore(tmp_paths, gid)
    profiles = store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile.coins = coins
    profile.total_ntr_lost = ntr_lost
    profile.total_ntr_comfort_received = ntr_comfort
    store.save_all(profiles)
    return profile


def _setup_wife_meta(tmp_paths, wid, rarity="N"):
    """创建一条老婆元数据。"""
    store = WivesMasterStore(tmp_paths)
    meta = WifeMeta(
        wid=wid,
        img=f"{wid}.jpg",
        source="测试作品",
        chara=f"老婆{ wid[-1]}",
        rarity=rarity,
        base_stats=BaseStats(atk=10, defense=10, hp=50),
    )
    store.upsert(meta)
    return meta


def _setup_ownership(tmp_paths, gid, uid, wid):
    """给用户添加一个持有老婆。"""
    store = OwnershipStore(tmp_paths, gid)
    ownerships = store.load_all()
    o = Ownership(wid=wid, uid=uid, intimacy=10, acquired_at=1000000)
    store.add(ownerships, o)
    store.save_all(ownerships)
    return o


# ========== Tests ==========


class TestPanelDebtStatus:
    """余额为负时显示 ⚠️ 负债。"""

    @pytest.mark.asyncio
    async def test_negative_balance_shows_debt_warning(
        self, tmp_paths, config, locks
    ):
        from app.commands.panel import handle_panel

        gid, uid, nick = "g1", "u1", "Alice"
        _setup_profile(tmp_paths, gid, uid, nick, -150)
        # 至少需要一个老婆才能看到面板
        _setup_wife_meta(tmp_paths, "w1")
        _setup_ownership(tmp_paths, gid, uid, "w1")

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 面板")

        async for _ in handle_panel(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "⚠️ 负债" in joined

    @pytest.mark.asyncio
    async def test_positive_balance_no_warning(
        self, tmp_paths, config, locks
    ):
        from app.commands.panel import handle_panel

        gid, uid, nick = "g1", "u1", "Alice"
        _setup_profile(tmp_paths, gid, uid, nick, 200)
        _setup_wife_meta(tmp_paths, "w1")
        _setup_ownership(tmp_paths, gid, uid, "w1")

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 面板")

        async for _ in handle_panel(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "⚠️ 负债" not in joined
        assert "200" in joined

    @pytest.mark.asyncio
    async def test_zero_balance_no_warning(
        self, tmp_paths, config, locks
    ):
        from app.commands.panel import handle_panel

        gid, uid, nick = "g1", "u1", "Alice"
        _setup_profile(tmp_paths, gid, uid, nick, 0)
        _setup_wife_meta(tmp_paths, "w1")
        _setup_ownership(tmp_paths, gid, uid, "w1")

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 面板")

        async for _ in handle_panel(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "⚠️ 负债" not in joined


class TestPanelNtrStats:
    """面板 NTR 战绩展示。"""

    @pytest.mark.asyncio
    async def test_ntr_stats_shown_when_data_exists(
        self, tmp_paths, config, locks
    ):
        from app.commands.panel import handle_panel

        gid, uid, nick = "g1", "u1", "Alice"
        _setup_profile(
            tmp_paths, gid, uid, nick,
            coins=100, ntr_lost=5, ntr_comfort=250,
        )
        _setup_wife_meta(tmp_paths, "w1")
        _setup_ownership(tmp_paths, gid, uid, "w1")

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 面板")

        async for _ in handle_panel(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "NTR 战绩" in joined
        assert "被牛 5 次" in joined or "被牛 5" in joined
        assert "累计收安慰币 250 币" in joined or "安慰币 250" in joined

    @pytest.mark.asyncio
    async def test_ntr_stats_none_shows_concise(
        self, tmp_paths, config, locks
    ):
        from app.commands.panel import handle_panel

        gid, uid, nick = "g1", "u1", "Alice"
        _setup_profile(
            tmp_paths, gid, uid, nick,
            coins=100, ntr_lost=0, ntr_comfort=0,
        )
        _setup_wife_meta(tmp_paths, "w1")
        _setup_ownership(tmp_paths, gid, uid, "w1")

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 面板")

        async for _ in handle_panel(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "NTR 战绩" in joined
        assert "暂无" in joined

    @pytest.mark.asyncio
    async def test_ntr_stats_only_lost_no_comfort(
        self, tmp_paths, config, locks
    ):
        """被牛 3 次但安慰币为 0（理论不会发生，但测试边界）。"""
        from app.commands.panel import handle_panel

        gid, uid, nick = "g1", "u1", "Alice"
        _setup_profile(
            tmp_paths, gid, uid, nick,
            coins=100, ntr_lost=3, ntr_comfort=0,
        )
        _setup_wife_meta(tmp_paths, "w1")
        _setup_ownership(tmp_paths, gid, uid, "w1")

        ctx = _make_ctx(tmp_paths, config, locks)
        event = _MockEvent(gid, uid, nick, "老婆 面板")

        async for _ in handle_panel(event, ctx):
            pass

        joined = " ".join(event.replies)
        assert "NTR 战绩" in joined
        assert "被牛 3 次" in joined or "被牛 3" in joined
