"""离婚命令处理器单元测试。

Phase D / v3 离婚系统：
- 完整流程：预览 → 确认 → 结算
- 二次确认超时
- 冷却拦截
- 打工中/战斗中拦截
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import AsyncGenerator, List
from unittest.mock import patch

import pytest

from app.commands.divorce import (
    _divorce_pending,
    _handle_confirm,
    _handle_cooldown_query,
    _handle_preview,
    handle_divorce,
    _DIVORCE_PREVIEW_TTL,
)
from app.models.ownership import Ownership
from app.models.profile import UserProfile
from app.services.divorce_service import (
    DIVORCE_COOLDOWN_DAYS,
    calc_divorce_return,
    calc_divorce_property_split_amount,
    calc_divorce_property_split_prob,
)
from app.storage.stores import OwnershipStore, ProfileStore, WivesMasterStore
from app.models.wife import WifeMeta, BaseStats


# ========== Fixtures ==========


class FakePaths:
    """模拟 Paths 对象供测试用。"""

    def __init__(self, tmp_path):
        self._tmp = tmp_path
        self.data_dir = str(tmp_path)
        self.wives_master_file = str(tmp_path / "wives_master.json")

    def group_ownership_file(self, gid: str) -> str:
        d = self._tmp / gid
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "ownership.json")

    def group_profiles_file(self, gid: str) -> str:
        d = self._tmp / gid
        d.mkdir(parents=True, exist_ok=True)
        return str(d / "profiles.json")


class FakeConfig:
    initial_coins = 50


class FakeEvent:
    """模拟 AstrMessageEvent，捕获 yield 的输出。"""

    def __init__(self, gid: str, uid: str, nick: str, text: str):
        self._gid = gid
        self._uid = uid
        self._nick = nick
        self.message_str = text
        self._replies: List[str] = []

    def get_sender_id(self):
        return self._uid

    def get_sender_name(self):
        return self._nick

    def plain_result(self, text: str):
        self._replies.append(text)
        return text

    def chain_result(self, components):
        text = "".join(str(c) for c in components)
        self._replies.append(text)
        return text

    @property
    def message_obj(self):
        return type("Msg", (), {"group_id": self._gid})()


class FakeCtx:
    """模拟 CommandContext"""

    def __init__(self, paths, gid):
        self.paths = paths
        self.config = FakeConfig()
        self._gid = gid

    def today(self):
        return "2026-07-19"


async def _collect(gen) -> List[str]:
    results = []
    async for item in gen:
        results.append(str(item))
    return results


@pytest.fixture
def setup(tmp_path):
    """初始化测试环境，包含一个玩家 + 持有 + 配置"""
    paths = FakePaths(tmp_path)
    gid = "g_test"
    uid = "u1"
    nick = "测试玩家"

    # 创建 profile
    profile_store = ProfileStore(paths, gid)
    profiles = profile_store.load_all()
    profile = ProfileStore.get_or_create(profiles, uid, nick)
    profile.coins = 500
    profile_store.save_all(profiles)

    # 创建 ownership
    ownership_store = OwnershipStore(paths, gid)
    ownerships = ownership_store.load_all()
    o = Ownership(
        wid="w_test",
        uid=uid,
        intimacy=50,
        acquired_at=1720000000,
    )
    ownership_store.add(ownerships, o)
    ownership_store.save_all(ownerships)

    # 创建 wifemeta
    wives_store = WivesMasterStore(paths)
    meta = WifeMeta(
        wid="w_test",
        img="test.jpg",
        source="测试作品",
        chara="测试妻",
        rarity="SSR",
        base_stats=BaseStats(atk=80, defense=60, hp=100),
    )
    wives_store.upsert(meta)

    ctx = FakeCtx(paths, gid)
    event = FakeEvent(gid, uid, nick, "")

    return {
        "paths": paths,
        "gid": gid,
        "uid": uid,
        "nick": nick,
        "ctx": ctx,
        "event": event,
        "profile_store": profile_store,
        "ownership_store": ownership_store,
    }


def _make_event(gid, uid, nick, text):
    return FakeEvent(gid, uid, nick, text)


# ========== Tests ==========


class TestDivorceCommandHelp:
    async def test_no_args_shows_help(self, setup):
        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "离婚系统用法" in replies[0]


class TestDivorceCommandCooldown:
    async def test_no_previous_divorce(self, setup):
        """从未离婚 → 冷却查询显示可以离婚"""
        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 冷却")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "还没有离过婚" in replies[0]

    async def test_cooldown_active(self, setup):
        """6 天前离婚 → 冷却中"""
        profile_store = setup["profile_store"]
        profiles = profile_store.load_all()
        profile = profiles[setup["uid"]]
        profile.last_divorce_date = "2026-07-13"  # 6 天前
        profile_store.save_all(profiles)

        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 冷却")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "还需等待" in replies[0]

    async def test_cooldown_expired(self, setup):
        """7 天前离婚 → 冷却已过"""
        profile_store = setup["profile_store"]
        profiles = profile_store.load_all()
        profile = profiles[setup["uid"]]
        profile.last_divorce_date = "2026-07-12"  # 7 天前
        profile_store.save_all(profiles)

        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 冷却")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "冷却已过" in replies[0]


class TestDivorceCommandPreview:
    async def test_preview_shows_info(self, setup):
        """预览显示离婚相关信息"""
        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "离婚预告" in replies[0]
        assert "测试妻" in replies[0]
        assert "SSR" in replies[0]
        assert "离婚返还" in replies[0]
        assert "分家产概率" in replies[0]

    async def test_preview_saves_pending(self, setup):
        """预览后应保存 pending 状态"""
        # 清空 pending
        _divorce_pending.clear()

        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1")
        async for _ in handle_divorce(event, setup["ctx"]):
            pass
        assert setup["uid"] in _divorce_pending
        assert _divorce_pending[setup["uid"]]["wid"] == "w_test"

    async def test_invalid_index(self, setup):
        """越界编号 → 错误提示"""
        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 999")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "超出范围" in replies[0]

    async def test_no_wives(self, setup):
        """没有老婆时 → 错误提示"""
        # 清空持有
        ownership_store = setup["ownership_store"]
        ownerships = ownership_store.load_all()
        ownership_store.remove_by_wid(ownerships, "w_test")
        ownership_store.save_all(ownerships)

        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1")
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "没有老婆" in replies[0]


class TestDivorceCommandConfirm:
    @pytest.fixture(autouse=True)
    def setup_pending(self, setup):
        """为测试设置 preview pending 状态"""
        _divorce_pending[setup["uid"]] = {
            "wid": "w_test",
            "created_at": datetime.now().timestamp(),
        }
        yield
        _divorce_pending.pop(setup["uid"], None)

    async def test_confirm_executes(self, setup):
        """确认执行后，所有权被删除，档案更新"""
        # 预处理：mock random 确保分家产不触发
        with patch("app.commands.divorce.random.random", return_value=1.0):  # 不触发分家产
            event = _make_event(
                setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
            )
            replies = []
            async for item in handle_divorce(event, setup["ctx"]):
                replies.append(str(item))

        assert len(replies) == 1
        assert "离婚完成" in replies[0]
        assert "测试妻" in replies[0]

        # 验证持有已删除
        ownership_store = setup["ownership_store"]
        ownerships = ownership_store.load_all()
        assert ownership_store.find_by_wid("w_test", ownerships) is None

        # 验证档案已更新
        profile_store = setup["profile_store"]
        profiles = profile_store.load_all()
        profile = profiles[setup["uid"]]
        assert profile.last_divorce_date == "2026-07-19"
        assert profile.total_divorces == 1
        assert profile.total_divorce_coins_earned > 0  # SSR+50=earn 180
        return_coin = calc_divorce_return("SSR", 50)
        assert profile.coins == 500 + return_coin

    async def test_confirm_with_split(self, setup):
        """确认执行且触发分家产"""
        with patch("app.commands.divorce.random.random", return_value=0.0):  # 触发分家产
            event = _make_event(
                setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
            )
            replies = []
            async for item in handle_divorce(event, setup["ctx"]):
                replies.append(str(item))

        assert len(replies) == 1
        assert "离婚完成" in replies[0]
        assert "分家产：触发" in replies[0]

        # 验证余额变化：500 - 分家产(100) + 返还(180) = 580
        profile_store = setup["profile_store"]
        profiles = profile_store.load_all()
        profile = profiles[setup["uid"]]
        return_coin = calc_divorce_return("SSR", 50)
        split_amount = calc_divorce_property_split_amount(500)
        expected = 500 - split_amount + return_coin
        assert profile.coins == expected

    async def test_confirm_no_pending(self, setup):
        """没有 preview 直接确认 → 提示先预览"""
        _divorce_pending.clear()

        event = _make_event(
            setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
        )
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "请先发送" in replies[0]

    async def test_confirm_expired(self, setup):
        """preview 已过期（超过 10 分钟）→ 提示重新预览"""
        _divorce_pending[setup["uid"]] = {
            "wid": "w_test",
            "created_at": datetime.now().timestamp() - _DIVORCE_PREVIEW_TTL - 60,
        }

        event = _make_event(
            setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
        )
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "预览已过期" in replies[0]

    async def test_confirm_wife_no_longer_owned(self, setup):
        """预览后老婆被抢走 → 离婚取消"""
        ownership_store = setup["ownership_store"]
        ownerships = ownership_store.load_all()
        ownership_store.remove_by_wid(ownerships, "w_test")
        ownership_store.save_all(ownerships)

        event = _make_event(
            setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
        )
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "已经不属于你了" in replies[0]

    async def test_confirm_cooldown_intercept(self, setup):
        """preview 后 7 天冷却期内再次离婚 → 拒绝"""
        # 设置冷却：6 天前离过婚
        profile_store = setup["profile_store"]
        profiles = profile_store.load_all()
        profile = profiles[setup["uid"]]
        profile.last_divorce_date = "2026-07-13"  # 6 天前 (today is 2026-07-19)
        profile_store.save_all(profiles)

        event = _make_event(
            setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
        )
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "刚离过婚" in replies[0]

    async def test_confirm_working_intercept(self, setup):
        """打工中的老婆 → 拒绝"""
        ownership_store = setup["ownership_store"]
        ownerships = ownership_store.load_all()
        target = ownership_store.find_by_wid("w_test", ownerships)
        target.is_working = True
        ownership_store.save_all(ownerships)

        event = _make_event(
            setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
        )
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "打工中" in replies[0]

    async def test_confirm_in_battle_intercept(self, setup):
        """战斗中的老婆 → 拒绝"""
        ownership_store = setup["ownership_store"]
        ownerships = ownership_store.load_all()
        target = ownership_store.find_by_wid("w_test", ownerships)
        target.is_in_battle = True
        ownership_store.save_all(ownerships)

        event = _make_event(
            setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
        )
        replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            replies.append(str(item))
        assert len(replies) == 1
        assert "战斗中" in replies[0]

    async def test_clears_pending_after_execution(self, setup):
        """确认执行后清理 pending 状态"""
        with patch("app.commands.divorce.random.random", return_value=1.0):
            event = _make_event(
                setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
            )
            async for _ in handle_divorce(event, setup["ctx"]):
                pass

        assert setup["uid"] not in _divorce_pending


class TestDivorceCommandIntegration:
    """完整流程：预览 → 确认"""

    async def test_full_flow(self, setup):
        """完整离婚流程"""
        _divorce_pending.clear()

        # Step 1: 预览
        event = _make_event(setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1")
        preview_replies = []
        async for item in handle_divorce(event, setup["ctx"]):
            preview_replies.append(str(item))
        assert len(preview_replies) == 1
        assert "离婚预告" in preview_replies[0]
        assert setup["uid"] in _divorce_pending

        # Step 2: 确认（不触发分家产）
        with patch("app.commands.divorce.random.random", return_value=1.0):
            event = _make_event(
                setup["gid"], setup["uid"], setup["nick"], "老婆 离婚 1 确认"
            )
            confirm_replies = []
            async for item in handle_divorce(event, setup["ctx"]):
                confirm_replies.append(str(item))

        assert len(confirm_replies) == 1
        assert "离婚完成" in confirm_replies[0]
        assert "分家产：未触发" in confirm_replies[0]

        # 验证数据
        ownership_store = setup["ownership_store"]
        ownerships = ownership_store.load_all()
        assert ownership_store.find_by_wid("w_test", ownerships) is None

        profile_store = setup["profile_store"]
        profiles = profile_store.load_all()
        profile = profiles[setup["uid"]]
        assert profile.total_divorces == 1
        assert profile.last_divorce_date == "2026-07-19"

        # 验证 pending 已清理
        assert setup["uid"] not in _divorce_pending
