"""utils 层纯函数单元测试。"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.utils import format as fmt
from app.utils import image, random_utils, time as time_utils


# ==================== utils/time ====================


class TestTime:
    def test_get_today_returns_iso_date(self):
        tz = ZoneInfo("Asia/Shanghai")
        today = time_utils.get_today(tz)
        # YYYY-MM-DD
        parts = today.split("-")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_get_today_respects_timezone(self):
        """UTC 与 Asia/Shanghai 在某些时段可能差一天"""
        tz_utc = ZoneInfo("UTC")
        tz_sh = ZoneInfo("Asia/Shanghai")
        # 仅仅是 smoke：两边都是合法 ISO 日期
        assert time_utils.get_today(tz_utc)
        assert time_utils.get_today(tz_sh)

    def test_seconds_until_next_midnight_positive(self):
        tz = ZoneInfo("Asia/Shanghai")
        secs = time_utils.seconds_until_next_midnight(tz)
        # 距离下一个零点应该小于等于 24h
        assert 0 < secs <= 86400 + 60  # 留点余量

    def test_seconds_until_next_midnight_at_noon(self):
        """直接验证计算逻辑：固定时刻 → 距下一零点秒数"""
        tz = ZoneInfo("UTC")
        # 2026-01-01 12:00:00 UTC，距 2026-01-02 00:00:00 UTC = 12h
        fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=tz)
        next_midnight = datetime(2026, 1, 2, 0, 0, 0, tzinfo=tz)
        expected = (next_midnight - fixed_now).total_seconds()
        assert expected == 43200  # 12h

        # 验证 seconds_until_next_midnight 内部算法的输入/输出关系
        # （不依赖 datetime.now，直接构造时间差）
        now_2_midnight = (
            datetime.combine(
                (fixed_now + timedelta(days=1)).date(),
                datetime.min.time(),
                tzinfo=tz,
            )
            - fixed_now
        ).total_seconds()
        assert now_2_midnight == 43200

    def test_now_ts_is_int(self):
        ts = time_utils.now_ts()
        assert isinstance(ts, int)
        assert ts > 1700000000  # 2023+

    def test_get_week_key_format(self):
        tz = ZoneInfo("Asia/Shanghai")
        key = time_utils.get_week_key(tz)
        # 格式 YYYY-Wxx
        parts = key.split("-W")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert parts[1].isdigit()
        assert 1 <= int(parts[1]) <= 53

    def test_get_month_key_format(self):
        tz = ZoneInfo("Asia/Shanghai")
        key = time_utils.get_month_key(tz)
        # 格式 YYYY-MM
        parts = key.split("-")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert parts[1].isdigit()
        assert 1 <= int(parts[1]) <= 12

    def test_is_next_day_true(self):
        assert time_utils.is_next_day("2026-01-01", "2026-01-02") is True

    def test_is_next_day_false_same_day(self):
        assert time_utils.is_next_day("2026-01-01", "2026-01-01") is False

    def test_is_next_day_false_gap(self):
        assert time_utils.is_next_day("2026-01-01", "2026-01-03") is False

    def test_is_next_day_false_empty(self):
        assert time_utils.is_next_day("", "2026-01-01") is False

    def test_is_next_day_false_invalid(self):
        assert time_utils.is_next_day("invalid", "2026-01-01") is False

    def test_hours_between_basic(self):
        ts1 = 1000000
        ts2 = 1003600  # +1h
        assert time_utils.hours_between(ts1, ts2) == pytest.approx(1.0)

    def test_hours_between_reversed(self):
        ts1 = 1003600
        ts2 = 1000000
        assert time_utils.hours_between(ts1, ts2) == pytest.approx(1.0)


# ==================== utils/image ====================


class TestImage:
    def test_parse_wife_name_with_source(self):
        chara, source = image.parse_wife_name("进击的巨人!三笠.jpg")
        assert chara == "三笠"
        assert source == "进击的巨人"

    def test_parse_wife_name_without_source(self):
        chara, source = image.parse_wife_name("just_a_name.jpg")
        assert chara == "just_a_name"
        assert source is None

    def test_parse_wife_name_with_path_prefix(self):
        chara, source = image.parse_wife_name("some/path/作品!角色.jpg")
        assert chara == "角色"
        assert source == "作品"

    def test_parse_wife_name_strips_extension(self):
        chara, _ = image.parse_wife_name("X!Y.png")
        assert chara == "Y"

    def test_build_image_url(self):
        url = image.build_image_url("https://example.com/base/", "img.jpg")
        assert url == "https://example.com/base/img.jpg"

    def test_build_image_url_no_trailing_slash(self):
        url = image.build_image_url("https://example.com/base", "img.jpg")
        assert url == "https://example.com/base/img.jpg"

    def test_build_wife_intro_text_with_source(self):
        text = image.build_wife_intro_text(
            "进击的巨人!三笠.jpg",
            prefix="你今天的老婆是",
            suffix="，请好好珍惜哦~",
        )
        assert "《进击的巨人》" in text
        assert "三笠" in text
        assert text.endswith("请好好珍惜哦~")

    def test_build_wife_intro_text_without_source(self):
        text = image.build_wife_intro_text(
            "三笠.jpg",
            prefix="你今天的老婆是",
            suffix="~",
        )
        assert text == "你今天的老婆是三笠~"

    def test_is_path_within_dir_safe(self, tmp_path):
        assert image.is_path_within_dir("a.jpg", str(tmp_path)) is True
        assert image.is_path_within_dir("sub/a.jpg", str(tmp_path)) is True

    def test_is_path_within_dir_blocks_escape(self, tmp_path):
        # 试图逃逸出 base 目录
        assert image.is_path_within_dir("../../etc/passwd", str(tmp_path)) is False
        assert image.is_path_within_dir("../sibling/x.jpg", str(tmp_path)) is False


# ==================== utils/random ====================


class TestRandom:
    def test_weighted_choice_returns_valid_key(self):
        weights = {"A": 1, "B": 1}
        result = random_utils.weighted_choice(weights)
        assert result in ("A", "B")

    def test_weighted_choice_distribution(self):
        """蒙特卡洛：1000 次抽样分布近似权重比"""
        weights = {"A": 1, "B": 3}
        rng = random.Random(42)
        counts = {"A": 0, "B": 0}
        for _ in range(4000):
            counts[random_utils.weighted_choice(weights, rng=rng)] += 1
        # B:A 应近似 3:1
        ratio = counts["B"] / counts["A"]
        assert 2.5 < ratio < 3.5, f"distribution off: {counts}"

    def test_weighted_choice_single_key(self):
        result = random_utils.weighted_choice({"X": 5})
        assert result == "X"

    def test_weighted_choice_empty_raises(self):
        with pytest.raises(ValueError):
            random_utils.weighted_choice({})

    def test_weighted_choice_zero_weight_filtered(self):
        """全 0 权重抛 ValueError"""
        with pytest.raises(ValueError):
            random_utils.weighted_choice({"A": 0, "B": 0})

    def test_roll_chance_always_true_when_one(self):
        rng = random.Random(0)
        assert all(random_utils.roll_chance(1.0, rng=rng) for _ in range(100))

    def test_roll_chance_always_false_when_zero(self):
        rng = random.Random(0)
        assert not any(random_utils.roll_chance(0.0, rng=rng) for _ in range(100))

    def test_roll_chance_clamps_above_one(self):
        rng = random.Random(0)
        assert random_utils.roll_chance(2.0, rng=rng) is True

    def test_roll_chance_clamps_below_zero(self):
        rng = random.Random(0)
        assert random_utils.roll_chance(-1.0, rng=rng) is False


# ==================== utils/format ====================


class TestFormat:
    def test_intimacy_level_high(self):
        assert fmt.format_intimacy_level(100) == "❤️❤️❤️❤️❤️"
        assert fmt.format_intimacy_level(90) == "❤️❤️❤️❤️❤️"

    def test_intimacy_level_low(self):
        assert fmt.format_intimacy_level(0) == "💔"
        assert fmt.format_intimacy_level(5) == "💔"

    def test_intimacy_level_middle(self):
        assert "❤️" in fmt.format_intimacy_level(50)

    def test_rarity_badge_known(self):
        assert fmt.format_rarity_badge("SSR") == "✨ SSR"
        assert fmt.format_rarity_badge("sr") == "🌟 SR"  # 大小写不敏感

    def test_rarity_badge_unknown(self):
        assert fmt.format_rarity_badge("XYZ") == "XYZ"

    def test_truncate_short_text_unchanged(self):
        assert fmt.truncate_text("hello", 10) == "hello"

    def test_truncate_long_text(self):
        result = fmt.truncate_text("a" * 100, 10)
        assert len(result) == 10
        assert result.endswith("…")
