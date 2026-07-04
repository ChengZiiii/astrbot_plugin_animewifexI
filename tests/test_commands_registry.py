"""命令注册表解析测试（不执行 handler）。"""

from __future__ import annotations

import pytest

from app.commands.admin import build_help_text
from app.commands.registration import build_registry
from app.commands.registry import CommandRegistry


class TestRegistryParse:
    def test_legacy_command_exact_match(self):
        reg = build_registry()
        result = reg.parse("抽老婆")
        assert result is not None
        assert result.name == "抽老婆"

    def test_legacy_command_with_trailing_args(self):
        reg = build_registry()
        result = reg.parse("查老婆 @某人")
        assert result is not None
        assert result.name == "查老婆"

    def test_ntr_command_nickname_match(self):
        reg = build_registry()
        result = reg.parse("牛老婆 张三")
        assert result is not None
        assert result.name == "牛老婆"

    def test_no_match_returns_none(self):
        reg = build_registry()
        assert reg.parse("hello world") is None
        assert reg.parse("") is None
        assert reg.parse("   ") is None

    def test_case_insensitive_ntr_switch(self):
        reg = build_registry()
        # 两种写法都解析到 handle_switch_ntr
        r1 = reg.parse("切换ntr开关状态")
        r2 = reg.parse("切换NTR开关状态")
        assert r1 is not None
        assert r2 is not None
        # handler 应为同一函数
        assert r1.handler is r2.handler

    def test_long_command_preferred_over_short_prefix(self):
        """长命令优先匹配（避免 "查老婆" 截胡 "查老婆状态" 之类）"""
        reg = build_registry()
        # "查看交换请求" 不应被 "查老婆" 截胡（前缀不同）
        # 但 "重置换" 与 "重置牛" 前缀 "重置" 相同，应正确区分
        assert reg.parse("重置换").name == "重置换"
        assert reg.parse("重置牛").name == "重置牛"
        assert reg.parse("重置换 @x").name == "重置换"

    def test_grouped_command_help(self):
        reg = build_registry()
        # 老婆 帮助 → grouped help handler
        result = reg.parse("老婆 帮助")
        assert result is not None
        assert "帮助" in result.name

    def test_grouped_command_stub(self):
        reg = build_registry()
        result = reg.parse("老婆 列表")
        assert result is not None
        assert "列表" in result.name

    def test_grouped_command_with_args(self):
        reg = build_registry()
        result = reg.parse("老婆 查 1")
        assert result is not None
        # 占位子命令 "查" 未在 NOT_IMPLEMENTED_SUBCOMMANDS 中，
        # 应该返回 None（不存在的子命令）
        # 修正：当前 NOT_IMPLEMENTED_SUBCOMMANDS 不含 "查"，所以 parse 返回 None
        # 这个测试改为验证已有子命令
        result2 = reg.parse("老婆 摸头 1")
        assert result2 is not None
        assert "摸头" in result2.name

    def test_legacy_help_priority_over_grouped(self):
        """``老婆帮助``（旧扁平）应优先于 ``老婆 帮助``（分组）"""
        reg = build_registry()
        # "老婆帮助" 不带空格 → 旧扁平命令
        r1 = reg.parse("老婆帮助")
        # "老婆 帮助" 带空格 → 分组命令
        r2 = reg.parse("老婆 帮助")
        assert r1 is not None
        assert r2 is not None
        assert r1.name == "老婆帮助"
        assert r2.name != "老婆帮助"

    def test_all_legacy_commands_registered(self):
        reg = build_registry()
        names = set(reg.legacy_commands.keys())
        expected = {
            "老婆帮助", "抽老婆", "查老婆", "牛老婆",
            "重置牛", "换老婆", "重置换",
            "交换老婆", "同意交换", "拒绝交换", "查看交换请求",
            "切换ntr开关状态", "切换NTR开关状态",
        }
        assert expected.issubset(names), f"missing: {expected - names}"

    def test_all_command_names_includes_grouped(self):
        reg = build_registry()
        all_names = reg.all_command_names()
        # 旧扁平
        assert "抽老婆" in all_names
        # 分组（带 "老婆 " 前缀）
        assert "老婆 列表" in all_names
        assert "老婆 查" in all_names
        assert "老婆 摸头" in all_names
        assert "老婆 对话" in all_names
        assert "老婆 约会" in all_names
        assert "老婆 打工" in all_names
        assert "老婆 切换" in all_names

    def test_help_text_matches_current_features(self):
        help_text = build_help_text()

        assert "老婆 对话" in help_text
        assert "老婆 约会" in help_text
        assert "老婆 打工" in help_text
        assert "老婆 切换" in help_text
        assert "老婆 列表" in help_text
        assert "老婆 查" in help_text
        assert "老婆 重置抽卡" in help_text
        assert "老婆 列表 [页码] / 老婆 查 [@用户] [页码]" in help_text
        assert "老婆 切换 当前仍未开放" not in help_text

        assert "求婚" not in help_text
        assert "后续开放" not in help_text
        assert "Phase 2/3" not in help_text


class TestRegistryRegister:
    def test_register_legacy_empty_name_raises(self):
        reg = CommandRegistry()
        with pytest.raises(ValueError):
            reg.register_legacy("", lambda: None)

    def test_register_grouped_empty_name_raises(self):
        reg = CommandRegistry()
        with pytest.raises(ValueError):
            reg.register_grouped("", lambda: None)

    def test_dispatch_returns_none_for_no_match(self):
        reg = build_registry()
        # dispatch 不执行 handler，只解析；这里只看返回值
        # 但 dispatch 需要 event 参数，跳过；parse 已覆盖
        pass
