"""老婆 编队（formation）命令的单元测试。

覆盖：
* 4 位编队设置
* 默认 / 清除
* 编号越界 / 重复 / 持有不足 / 未持有等错误
* 编队持久化 round-trip
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest


# ---------- mock event / message_obj ----------


class _MockMessageObj:
    def __init__(self, gid: str):
        self.group_id = gid
        self.message = []


class _MockEvent:
    """最小化 AstrMessageEvent 桩，足以驱动编队命令。"""

    def __init__(self, gid: str, uid: str, nick: str, message: str):
        self.message_str = message
        self.message_obj = _MockMessageObj(gid)
        self._uid = uid
        self._nick = nick
        self.replies: List[str] = []

    def get_sender_id(self):
        return self._uid

    def get_sender_name(self):
        return self._nick

    def plain_result(self, text: str):
        self.replies.append(text)
        return text

    def chain_result(self, chain):
        self.replies.append(str(chain))
        return chain


# ---------- 工具函数 ----------


def _make_ctx(tmp_paths, config, locks, mock_wife_service):
    from app.commands.context import CommandContext
    from app.services.ownership_service import OwnershipService

    ownership_service = OwnershipService(
        paths=tmp_paths,
        config=config,
        locks=locks,
        wife_service=mock_wife_service,
    )
    from zoneinfo import ZoneInfo

    return CommandContext(
        paths=tmp_paths,
        config=config,
        locks=locks,
        ownership_service=ownership_service,
        wife_service=mock_wife_service,
        cooldown_service=None,  # formation 命令不用
        tz=ZoneInfo("Asia/Shanghai"),
    )


def _seed_owned_wives(tmp_paths, gid, uid, nick, count):
    """为 uid 写入 ``count`` 条 ownership 记录，返回 wid 列表"""
    from app.models.ownership import Ownership
    from app.storage.stores import OwnershipStore
    from app.utils.time import now_ts

    store = OwnershipStore(tmp_paths, gid)
    ownerships = store.load_all()
    wids = []
    for i in range(count):
        wid = f"w_test_{uid}_{i + 1}"
        wids.append(wid)
        o = Ownership(
            wid=wid,
            uid=uid,
            acquired_at=now_ts(),
            acquired_via="draw",
            intimacy=10,
            intimacy_updated_date="2026-07-12",
        )
        OwnershipStore.add(ownerships, o)
    store.save_all(ownerships)
    return wids


def _get_formation(tmp_paths, gid, uid):
    from app.storage.stores import ProfileStore

    profiles = ProfileStore(tmp_paths, gid).load_all()
    p = profiles.get(uid)
    return list(p.formation) if p else []


# ---------- tests ----------


class TestFormationCommand:
    @pytest.mark.asyncio
    async def test_formation_empty_shows_usage_hint(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        _seed_owned_wives(tmp_paths, gid, uid, nick, 4)

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        event = _MockEvent(gid, uid, nick, "老婆 编队")

        async for _ in handle_formation(event, ctx):
            pass

        assert event.replies, "expected a reply"
        # 默认未设置时返回空数组提示用法
        assert _get_formation(tmp_paths, gid, uid) == []
        assert any("编队" in r or "老婆" in r for r in event.replies)

    @pytest.mark.asyncio
    async def test_formation_set_four_in_order(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        wids = _seed_owned_wives(tmp_paths, gid, uid, nick, 4)

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        # 用户指定 2 4 1 3 → wid[1] wid[3] wid[0] wid[2]
        event = _MockEvent(gid, uid, nick, f"老婆 编队 2 4 1 3")
        async for _ in handle_formation(event, ctx):
            pass

        assert _get_formation(tmp_paths, gid, uid) == [wids[1], wids[3], wids[0], wids[2]]
        assert any("编队" in r for r in event.replies)

    @pytest.mark.asyncio
    async def test_formation_set_partial_two(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        wids = _seed_owned_wives(tmp_paths, gid, uid, nick, 4)

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        event = _MockEvent(gid, uid, nick, "老婆 编队 2 1")
        async for _ in handle_formation(event, ctx):
            pass

        assert _get_formation(tmp_paths, gid, uid) == [wids[1], wids[0]]
    @pytest.mark.asyncio
    async def test_formation_default_populates_from_holdings(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        """``老婆 编队 默认`` —— 按持有列表前 N 个填充 formation（N = min(持有数, 4)）。

        spec §S4.1：
          * 持有 ≥ 4 → 填 4 个（前 4 位）；
          * 持有 < 4 → 填持有数；
          * 持有 = 0 → 返回错误，不写入编队。
        """
        from app.commands.formation import handle_formation

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)

        # --- 场景 1：持有 5 → 填前 4 个（覆盖原 5 4 3 2 编队） ---
        gid1, uid1, nick1 = "g1", "u1", "Alice"
        wids5 = _seed_owned_wives(tmp_paths, gid1, uid1, nick1, 5)
        # 先设一个非默认顺序
        event0 = _MockEvent(gid1, uid1, nick1, "老婆 编队 5 4 3 2")
        async for _ in handle_formation(event0, ctx):
            pass
        assert len(_get_formation(tmp_paths, gid1, uid1)) == 4

        event1 = _MockEvent(gid1, uid1, nick1, "老婆 编队 默认")
        async for _ in handle_formation(event1, ctx):
            pass
        formation1 = _get_formation(tmp_paths, gid1, uid1)
        assert len(formation1) == 4
        assert formation1 == [wids5[0], wids5[1], wids5[2], wids5[3]]
        assert any("默认" in r for r in event1.replies)

        # --- 场景 2：持有 3 → 填 3 个（持有数 < 4） ---
        gid2, uid2, nick2 = "g2", "u2", "Bob"
        wids3 = _seed_owned_wives(tmp_paths, gid2, uid2, nick2, 3)
        event2 = _MockEvent(gid2, uid2, nick2, "老婆 编队 默认")
        async for _ in handle_formation(event2, ctx):
            pass
        formation2 = _get_formation(tmp_paths, gid2, uid2)
        assert len(formation2) == 3
        assert formation2 == [wids3[0], wids3[1], wids3[2]]

        # --- 场景 3：持有 0 → 返回错误，不写入编队 ---
        gid3, uid3, nick3 = "g3", "u3", "Charlie"
        # 不 seed ownership
        event3 = _MockEvent(gid3, uid3, nick3, "老婆 编队 默认")
        async for _ in handle_formation(event3, ctx):
            pass
        assert _get_formation(tmp_paths, gid3, uid3) == []
        joined3 = " ".join(event3.replies)
        assert any(kw in joined3 for kw in ("没有老婆", "先去抽"))


    @pytest.mark.asyncio
    async def test_formation_clear_alias(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        _seed_owned_wives(tmp_paths, gid, uid, nick, 4)

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        # 先设置
        event = _MockEvent(gid, uid, nick, "老婆 编队 1 2 3 4")
        async for _ in handle_formation(event, ctx):
            pass

        # 清除 = 清空
        event2 = _MockEvent(gid, uid, nick, "老婆 编队 清除")
        async for _ in handle_formation(event2, ctx):
            pass
        assert _get_formation(tmp_paths, gid, uid) == []

    @pytest.mark.asyncio
    async def test_formation_index_out_of_range(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        _seed_owned_wives(tmp_paths, gid, uid, nick, 2)  # 只持有 2 个

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        event = _MockEvent(gid, uid, nick, "老婆 编队 3")
        async for _ in handle_formation(event, ctx):
            pass

        # 越界 → 不应写入编队
        assert _get_formation(tmp_paths, gid, uid) == []
        # 应有错误提示
        joined = " ".join(event.replies)
        assert any(kw in joined for kw in ("超出", "超过", "不存在", "范围"))

    @pytest.mark.asyncio
    async def test_formation_duplicate_index_rejected(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        _seed_owned_wives(tmp_paths, gid, uid, nick, 4)

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        # 重复 1
        event = _MockEvent(gid, uid, nick, "老婆 编队 1 1 2 3")
        async for _ in handle_formation(event, ctx):
            pass

        assert _get_formation(tmp_paths, gid, uid) == []
        joined = " ".join(event.replies)
        assert any(kw in joined for kw in ("重复", "不能"))

    @pytest.mark.asyncio
    async def test_formation_user_has_no_wives(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        # 没有 ownership 记录
        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        event = _MockEvent(gid, uid, nick, "老婆 编队 1")
        async for _ in handle_formation(event, ctx):
            pass

        assert _get_formation(tmp_paths, gid, uid) == []
        joined = " ".join(event.replies)
        assert any(kw in joined for kw in ("没有老婆", "持有", "先去抽"))

    @pytest.mark.asyncio
    async def test_formation_too_many_indices(
        self, tmp_paths, config, locks, mock_wife_service
    ):
        from app.commands.formation import handle_formation

        gid, uid, nick = "g1", "u1", "Alice"
        _seed_owned_wives(tmp_paths, gid, uid, nick, 5)

        ctx = _make_ctx(tmp_paths, config, locks, mock_wife_service)
        # 5 个编号超过上限 4
        event = _MockEvent(gid, uid, nick, "老婆 编队 1 2 3 4 5")
        async for _ in handle_formation(event, ctx):
            pass

        assert _get_formation(tmp_paths, gid, uid) == []
        joined = " ".join(event.replies)
        assert any(kw in joined for kw in ("过多", "最多", "1-4", "1～4", "上限"))


class TestFormationRegistry:
    """`老婆 编队` 子命令注册到全局命令注册表"""

    def test_formation_subcommand_registered(self):
        from app.commands.registration import build_registry

        reg = build_registry()
        result = reg.parse("老婆 编队")
        assert result is not None
        assert "编队" in result.name

    def test_formation_subcommand_with_args(self):
        from app.commands.registration import build_registry

        reg = build_registry()
        result = reg.parse("老婆 编队 1 2 3 4")
        assert result is not None
        assert "编队" in result.name