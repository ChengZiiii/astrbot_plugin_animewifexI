"""OwnershipService 业务逻辑测试（最关键的业务路径）。

覆盖 v2.x 全部命令对应的服务流程：
- 抽老婆（首次/重复）
- 牛老婆（成功/失败/限额/无目标/被禁用）
- 换老婆（成功/失败/限额/无老婆）
- 交换老婆（发起/同意/拒绝/更换目标/限额返还）
- 重置（管理员/概率成功/概率失败禁言）
- 零点清理（跨天记录删除）
"""

from __future__ import annotations

import pytest

from app.models.enums import AcquireVia
from app.models.profile import UserProfile
from app.models.ownership import Ownership
from app.services.ownership_service import (
    DailyAction,
    NtrResult,
    OwnershipService,
    wid_for_img,
)
from app.storage.stores import DailyCountStore
from app.storage.stores import OwnershipStore, ProfileStore
from app.utils.time import now_ts


# ==================== 抽老婆 ====================


class TestDrawOrGetPrimary:
    @pytest.mark.asyncio
    async def test_first_draw_creates_primary(
        self, ownership_service, mock_wife_service, tmp_paths
    ):
        mock_wife_service.set_images(["进击的巨人!三笠.jpg"])
        result = await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        assert result.ok is True
        assert result.is_new is True
        assert result.img == "进击的巨人!三笠.jpg"
        assert result.wid == wid_for_img("进击的巨人!三笠.jpg")
        # 老婆元数据已写入 wives_master
        meta = ownership_service.get_wife_meta(result.wid)
        assert meta is not None
        assert meta.chara == "三笠"
        assert meta.source == "进击的巨人"

    @pytest.mark.asyncio
    async def test_repeat_draw_returns_same_primary(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["作品!角色.jpg"])
        r1 = await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        r2 = await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        assert r1.wid == r2.wid
        assert r2.is_new is False

    @pytest.mark.asyncio
    async def test_draw_updates_profile(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        profile = ownership_service.get_profile("g1", "u1", "张三")
        assert profile.total_draws == 1
        assert profile.last_draw_date == "2026-07-03"
        assert wid_for_img("作品!角色.jpg") in profile.collection

    @pytest.mark.asyncio
    async def test_draw_failed_returns_reason(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images([])
        result = await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        assert result.ok is False
        assert result.reason == "fetch_failed"


# ==================== 牛老婆 ====================


class TestTryNtr:
    @pytest.mark.asyncio
    async def test_ntr_success_transfers_ownership(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["作品A!角色A.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_victim", "受害者", "2026-07-03"
        )
        # 切换图片让攻击者抽到不同的老婆
        mock_wife_service.set_images(["作品B!角色B.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_attacker", "攻击者", "2026-07-03"
        )

        # NTR 成功（roll_seed=0 必成功）
        result = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03",
            roll_seed=0.0,
        )
        assert result.ok is True
        assert result.success is True
        assert result.wid == wid_for_img("作品A!角色A.jpg")
        # 攻击者旧主老婆被删除（v2.x 替换语义）
        assert ownership_service.get_primary_wid("g1", "u_attacker") == wid_for_img(
            "作品A!角色A.jpg"
        )
        # 受害者主老婆被夺走
        assert ownership_service.get_primary_wid("g1", "u_victim") is None

    @pytest.mark.asyncio
    async def test_ntr_failed_still_consumes_attempt(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_victim", "受害者", "2026-07-03"
        )
        await ownership_service.draw_or_get_primary(
            "g1", "u_attacker", "攻击者", "2026-07-03"
        )

        # roll=1.0 必失败
        result = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03",
            roll_seed=1.0,
        )
        assert result.ok is True
        assert result.success is False
        assert result.consumed_attempt is True
        assert result.reason == "roll_failed"
        # 受害者老婆未变
        assert ownership_service.get_primary_wid("g1", "u_victim") == wid_for_img(
            "作品!角色.jpg"
        )

    @pytest.mark.asyncio
    async def test_ntr_limit_reached(self, ownership_service, mock_wife_service, config):
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_victim", "受害者", "2026-07-03"
        )
        # 用完所有 NTR 次数（默认 3）
        for _ in range(config.ntr_max):
            await ownership_service.try_ntr(
                "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03",
                roll_seed=1.0,  # 失败也消耗
            )
        # 第 4 次应被限额拒绝
        result = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03",
            roll_seed=0.0,
        )
        assert result.ok is True
        assert result.success is False
        assert result.reason == "limit_reached"
        assert result.consumed_attempt is False

    @pytest.mark.asyncio
    async def test_ntr_invalid_target_self(
        self, ownership_service, mock_wife_service
    ):
        result = await ownership_service.try_ntr(
            "g1", "u1", "u1", "张三", "2026-07-03",
        )
        assert result.ok is False
        assert result.reason == "invalid_target"

    @pytest.mark.asyncio
    async def test_ntr_invalid_target_empty(self, ownership_service):
        result = await ownership_service.try_ntr(
            "g1", "u1", "", "张三", "2026-07-03",
        )
        assert result.ok is False
        assert result.reason == "invalid_target"

    @pytest.mark.asyncio
    async def test_ntr_disabled(self, ownership_service):
        ownership_service.set_ntr_enabled("g1", False)
        result = await ownership_service.try_ntr(
            "g1", "u1", "u2", "张三", "2026-07-03",
        )
        assert result.ok is False
        assert result.reason == "ntr_disabled"

    @pytest.mark.asyncio
    async def test_ntr_target_no_wife_consumes_attempt(
        self, ownership_service, mock_wife_service
    ):
        """目标无老婆：仍然消耗一次次数（与 v2.x 一致）"""
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_attacker", "攻击者", "2026-07-03"
        )
        result = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_no_wife", "攻击者", "2026-07-03",
            roll_seed=0.0,
        )
        assert result.ok is True
        assert result.success is False
        assert result.reason == "target_no_wife"
        assert result.consumed_attempt is True

    @pytest.mark.asyncio
    async def test_ntr_success_updates_profiles(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["作品A!A.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_victim", "受害者", "2026-07-03"
        )
        mock_wife_service.set_images(["作品B!B.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_attacker", "攻击者", "2026-07-03"
        )

        await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03",
            roll_seed=0.0,
        )
        attacker = ownership_service.get_profile("g1", "u_attacker")
        victim = ownership_service.get_profile("g1", "u_victim")
        assert attacker.total_ntr_success == 1
        assert victim.total_ntr_lost == 1
        assert victim.last_ntr_by["uid"] == "u_attacker"

    @pytest.mark.asyncio
    async def test_ntr_success_steals_work_reward_and_voids_contract(self, ownership_service, mock_wife_service, tmp_paths):
        mock_wife_service.set_images(["作品A!角色A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_victim", "受害者", "2026-07-03")
        mock_wife_service.set_images(["作品B!角色B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_attacker", "攻击者", "2026-07-03")

        ownership_store = OwnershipStore(tmp_paths, "g1")
        ownerships = ownership_store.load_all()
        ts = now_ts()
        victim_wid = wid_for_img("作品A!角色A.jpg")
        victim = next(o for o in ownerships if o.wid == victim_wid)
        victim.is_working = True
        victim.work_mode = "normal"
        victim.work_started_at = ts - 7200
        victim.work_ends_at = ts + 7200
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, "g1")
        profiles = profile_store.load_all()
        profiles["u_victim"].work_contract_reserved = "normal"
        profile_store.save_all(profiles)

        result = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03", roll_seed=0.0
        )

        assert result.ok is True
        assert result.success is True
        assert result.stolen_work_reward > 0
        assert result.contract_voided is True

        profiles = profile_store.load_all()
        assert profiles["u_victim"].work_contract_reserved == ""
        assert profiles["u_attacker"].coins >= result.stolen_work_reward

    @pytest.mark.asyncio
    async def test_ntr_success_triggers_insurance_card(self, ownership_service, mock_wife_service, tmp_paths):
        mock_wife_service.set_images(["作品A!角色A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_victim", "受害者", "2026-07-03")
        mock_wife_service.set_images(["作品B!角色B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_attacker", "攻击者", "2026-07-03")

        ownership_store = OwnershipStore(tmp_paths, "g1")
        ownerships = ownership_store.load_all()
        ts = now_ts()
        victim_wid = wid_for_img("作品A!角色A.jpg")
        victim = next(o for o in ownerships if o.wid == victim_wid)
        victim.is_working = True
        victim.work_mode = "normal"
        victim.work_started_at = ts - 7200
        victim.work_ends_at = ts + 7200
        ownership_store.save_all(ownerships)

        profile_store = ProfileStore(tmp_paths, "g1")
        profiles = profile_store.load_all()
        profiles["u_victim"].inventory["insurance_card"] = 1
        profile_store.save_all(profiles)

        result = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03", roll_seed=0.0
        )

        assert result.ok is True
        assert result.insurance_used is True
        assert result.insurance_bonus_coins == 20

        profiles = profile_store.load_all()
        assert profiles["u_victim"].inventory["insurance_card"] == 0
        assert profiles["u_victim"].inventory["revenge_token"] >= 1

    @pytest.mark.asyncio
    async def test_ntr_probability_includes_charm_and_same_target_streak(self, ownership_service, mock_wife_service, tmp_paths):
        wid_v1 = ownership_service._ensure_wife_meta("作品A!角色A.jpg")
        wid_v2 = ownership_service._ensure_wife_meta("作品A!角色B.jpg")
        wid_a = ownership_service._ensure_wife_meta("作品B!角色C.jpg")
        ownership_store = OwnershipStore(tmp_paths, "g1")
        ownerships = [
            Ownership(wid=wid_v1, uid="u_victim", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True),
            Ownership(wid=wid_v2, uid="u_victim", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=False),
            Ownership(wid=wid_a, uid="u_attacker", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True),
        ]
        ownership_store.save_all(ownerships)

        attacker_primary = next(o for o in ownerships if o.uid == "u_attacker" and o.is_primary)
        attacker_primary.intimacy = 60
        ownership_store.save_all(ownerships)

        first = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03", roll_seed=0.0, target_wid=wid_v1
        )
        assert first.ok is True
        assert first.success is True
        assert first.final_probability > 0.20

        second = await ownership_service.try_ntr(
            "g1", "u_attacker", "u_victim", "攻击者", "2026-07-03", roll_seed=0.19, target_wid=wid_v2
        )
        assert second.ok is True
        assert second.success is False
        assert second.final_probability < first.final_probability


# ==================== 换老婆 ====================


class TestChangePrimary:
    @pytest.mark.asyncio
    async def test_change_replaces_primary(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["旧!旧.jpg"])
        r1 = await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        old_wid = r1.wid

        mock_wife_service.set_images(["新!新.jpg"])
        r2 = await ownership_service.change_primary("g1", "u1", "张三", "2026-07-03")
        assert r2.ok is True
        assert r2.wid != old_wid
        assert r2.wid == wid_for_img("新!新.jpg")
        # 旧老婆所有权已删除
        assert ownership_service.get_primary_wid("g1", "u1") == r2.wid


class TestSwitchPrimary:
    @pytest.mark.asyncio
    async def test_switch_primary_to_owned_wife(self, ownership_service):
        wid_a = wid_for_img("作品A!A.jpg")
        wid_b = wid_for_img("作品B!B.jpg")
        ownership_store = ownership_service._ownership_store("g1")
        ownerships = ownership_store.load_all()
        ownerships.append(Ownership(wid=wid_a, uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid=wid_b, uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=False))
        ownership_store.save_all(ownerships)

        assert ownership_service.get_primary_wid("g1", "u1") == wid_a

        result = await ownership_service.switch_primary("g1", "u1", wid_b)
        assert result.ok is True
        assert result.wid == wid_b
        assert ownership_service.get_primary_wid("g1", "u1") == wid_b

    @pytest.mark.asyncio
    async def test_switch_primary_rejects_unowned_wife(self, ownership_service):
        wid_self = wid_for_img("作品A!A.jpg")
        other_wid = wid_for_img("作品B!B.jpg")
        ownership_store = ownership_service._ownership_store("g1")
        ownerships = ownership_store.load_all()
        ownerships.append(Ownership(wid=wid_self, uid="u1", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownerships.append(Ownership(wid=other_wid, uid="u2", acquired_at=0, acquired_via=AcquireVia.DRAW, is_primary=True))
        ownership_store.save_all(ownerships)

        result = await ownership_service.switch_primary("g1", "u1", other_wid)
        assert result.ok is False
        assert result.reason == "wife_not_found"

    @pytest.mark.asyncio
    async def test_change_limit_reached(
        self, ownership_service, mock_wife_service, config
    ):
        mock_wife_service.set_images(["初始!初始.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        for i in range(config.change_max_per_day):
            mock_wife_service.set_images([f"新{i}!新{i}.jpg"])
            await ownership_service.change_primary("g1", "u1", "张三", "2026-07-03")
        # 已达上限
        mock_wife_service.set_images(["超额!超额.jpg"])
        r = await ownership_service.change_primary("g1", "u1", "张三", "2026-07-03")
        assert r.ok is False
        assert r.reason == "limit_reached"

    @pytest.mark.asyncio
    async def test_change_no_wife(self, ownership_service):
        r = await ownership_service.change_primary("g1", "u1", "张三", "2026-07-03")
        assert r.ok is False
        assert r.reason == "no_wife"

    @pytest.mark.asyncio
    async def test_change_failed_fetch_keeps_state(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["旧!旧.jpg"])
        r1 = await ownership_service.draw_or_get_primary(
            "g1", "u1", "张三", "2026-07-03"
        )
        old_wid = r1.wid

        # 抽取失败
        mock_wife_service.set_images([])
        r2 = await ownership_service.change_primary("g1", "u1", "张三", "2026-07-03")
        assert r2.ok is False
        assert r2.reason == "fetch_failed"
        # 老婆和次数都没动
        assert ownership_service.get_primary_wid("g1", "u1") == old_wid
        used = ownership_service.get_daily_count(
            "g1", "u1", DailyAction.CHANGE_ATTEMPT, "2026-07-03"
        )
        assert used == 0


# ==================== 交换老婆 ====================


class TestSwap:
    @pytest.mark.asyncio
    async def test_create_and_accept_swap(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_a", "A", "2026-07-03"
        )
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_b", "B", "2026-07-03"
        )

        # 发起
        r1 = await ownership_service.create_swap_request(
            "g1", "u_a", "u_b", "2026-07-03"
        )
        assert r1.ok is True
        assert r1.consumed_attempt is True

        # 同意
        r2 = await ownership_service.accept_swap("g1", "u_a", "u_b", "2026-07-03")
        assert r2.ok is True
        # 互换 wid
        assert ownership_service.get_primary_wid("g1", "u_a") == wid_for_img("B!B.jpg")
        assert ownership_service.get_primary_wid("g1", "u_b") == wid_for_img("A!A.jpg")

    @pytest.mark.asyncio
    async def test_swap_with_self_rejected(self, ownership_service):
        r = await ownership_service.create_swap_request(
            "g1", "u_a", "u_a", "2026-07-03"
        )
        assert r.ok is False
        assert r.reason == "invalid_target"

    @pytest.mark.asyncio
    async def test_swap_self_no_wife(self, ownership_service, mock_wife_service):
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_b", "B", "2026-07-03"
        )
        r = await ownership_service.create_swap_request(
            "g1", "u_a_no_wife", "u_b", "2026-07-03"
        )
        assert r.ok is False
        assert r.reason == "self_no_wife"

    @pytest.mark.asyncio
    async def test_swap_target_no_wife(self, ownership_service, mock_wife_service):
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary(
            "g1", "u_a", "A", "2026-07-03"
        )
        r = await ownership_service.create_swap_request(
            "g1", "u_a", "u_b_no_wife", "2026-07-03"
        )
        assert r.ok is False
        assert r.reason == "target_no_wife"

    @pytest.mark.asyncio
    async def test_swap_repeated_target_refunds_old(
        self, ownership_service, mock_wife_service, config
    ):
        """已有待处理请求时重复发起视为更换目标：旧请求取消、次数返还"""
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_a", "A", "2026-07-03")
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_b", "B", "2026-07-03")
        mock_wife_service.set_images(["C!C.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_c", "C", "2026-07-03")

        # 第一次发起：消耗 1 次
        await ownership_service.create_swap_request("g1", "u_a", "u_b", "2026-07-03")
        assert ownership_service.get_daily_count(
            "g1", "u_a", DailyAction.SWAP_ATTEMPT, "2026-07-03"
        ) == 1

        # 第二次发起（换目标 u_c）：应返还第一次的次数
        r = await ownership_service.create_swap_request(
            "g1", "u_a", "u_c", "2026-07-03"
        )
        assert r.ok is True
        assert r.refunded_old is True
        # 净消耗仍为 1（返还 1 + 新扣 1）
        assert ownership_service.get_daily_count(
            "g1", "u_a", DailyAction.SWAP_ATTEMPT, "2026-07-03"
        ) == 1

    @pytest.mark.asyncio
    async def test_swap_limit_reached(
        self, ownership_service, mock_wife_service, config
    ):
        """限额触发：拒绝/同意清除 pending 后，used 不返还"""
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_a", "A", "2026-07-03")
        for target in ["u_b", "u_c"]:
            mock_wife_service.set_images([f"{target}!{target}.jpg"])
            await ownership_service.draw_or_get_primary(
                "g1", target, target, "2026-07-03"
            )

        # 用 swap_max_per_day 次（默认 2），每次都被拒绝（pending 清除，
        # used 不返还；与 v2.x 一致：拒绝不返还次数）
        for target in ["u_b", "u_c"]:
            await ownership_service.create_swap_request(
                "g1", "u_a", target, "2026-07-03"
            )
            await ownership_service.reject_swap("g1", "u_a", target, "2026-07-03")

        # 第 3 次：无 pending 可返还 → 限额拒绝
        r = await ownership_service.create_swap_request(
            "g1", "u_a", "u_b", "2026-07-03"
        )
        assert r.ok is False
        assert r.reason == "limit_reached"

    @pytest.mark.asyncio
    async def test_reject_swap(self, ownership_service, mock_wife_service):
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_a", "A", "2026-07-03")
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_b", "B", "2026-07-03")

        await ownership_service.create_swap_request("g1", "u_a", "u_b", "2026-07-03")
        r = await ownership_service.reject_swap("g1", "u_a", "u_b", "2026-07-03")
        assert r.ok is True
        # 老婆未变
        assert ownership_service.get_primary_wid("g1", "u_a") == wid_for_img("A!A.jpg")
        # 请求已删除
        assert "u_a" not in ownership_service.list_swap_requests("g1", "2026-07-03")

    @pytest.mark.asyncio
    async def test_accept_swap_mismatch(self, ownership_service, mock_wife_service):
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_a", "A", "2026-07-03")
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_b", "B", "2026-07-03")

        await ownership_service.create_swap_request("g1", "u_a", "u_b", "2026-07-03")
        # 错误的 accepter
        r = await ownership_service.accept_swap("g1", "u_a", "u_wrong", "2026-07-03")
        assert r.ok is False
        assert r.reason == "mismatch"

    @pytest.mark.asyncio
    async def test_accept_expired_swap(self, ownership_service, mock_wife_service, tmp_paths):
        """跨天的交换请求视为过期"""
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_a", "A", "2026-07-03")
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_b", "B", "2026-07-03")

        # 在 2026-07-03 发起
        await ownership_service.create_swap_request("g1", "u_a", "u_b", "2026-07-03")
        # 2026-07-04 才同意 → 过期
        r = await ownership_service.accept_swap("g1", "u_a", "u_b", "2026-07-04")
        assert r.ok is False
        assert r.reason == "expired"


# ==================== 重置 ====================


class TestReset:
    @pytest.mark.asyncio
    async def test_admin_reset_always_succeeds(self, ownership_service, mock_wife_service):
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u1", "张三", "2026-07-03")
        # 用掉一些次数
        await ownership_service.try_ntr(
            "g1", "u1", "u2", "张三", "2026-07-03", roll_seed=1.0
        )

        result = await ownership_service.reset_user_action(
            "g1", "u_admin", operator_is_admin=True,
            target_uid="u1", action=DailyAction.NTR_ATTEMPT,
            today="2026-07-03",
        )
        assert result["ok"] is True
        # 次数已清零
        assert ownership_service.get_daily_count(
            "g1", "u1", DailyAction.NTR_ATTEMPT, "2026-07-03"
        ) == 0

    @pytest.mark.asyncio
    async def test_normal_user_reset_success(self, ownership_service, mock_wife_service):
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u1", "张三", "2026-07-03")
        await ownership_service.try_ntr(
            "g1", "u1", "u2", "张三", "2026-07-03", roll_seed=1.0
        )

        result = await ownership_service.reset_user_action(
            "g1", "u_op", operator_is_admin=False,
            target_uid="u1", action=DailyAction.NTR_ATTEMPT,
            today="2026-07-03", roll_seed=0.0,  # 必成功
        )
        assert result["ok"] is True
        assert result["consumed_reset"] is True
        assert result["do_mute"] is False
        # 次数已清零
        assert ownership_service.get_daily_count(
            "g1", "u1", DailyAction.NTR_ATTEMPT, "2026-07-03"
        ) == 0

    @pytest.mark.asyncio
    async def test_normal_user_reset_failed_triggers_mute(
        self, ownership_service, mock_wife_service, config
    ):
        mock_wife_service.set_images(["作品!角色.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u1", "张三", "2026-07-03")
        await ownership_service.try_ntr(
            "g1", "u1", "u2", "张三", "2026-07-03", roll_seed=1.0
        )

        result = await ownership_service.reset_user_action(
            "g1", "u_op", operator_is_admin=False,
            target_uid="u1", action=DailyAction.NTR_ATTEMPT,
            today="2026-07-03", roll_seed=1.0,  # 必失败
        )
        assert result["ok"] is False
        assert result["do_mute"] is True
        assert result["mute_duration"] == config.reset_mute_duration
        assert result["consumed_reset"] is True
        # 次数未清零（重置失败）
        assert ownership_service.get_daily_count(
            "g1", "u1", DailyAction.NTR_ATTEMPT, "2026-07-03"
        ) == 1

    @pytest.mark.asyncio
    async def test_reset_limit_reached(self, ownership_service, config):
        # 用完 reset 次数
        for _ in range(config.reset_max_uses_per_day):
            await ownership_service.reset_user_action(
                "g1", "u_op", operator_is_admin=False,
                target_uid="u1", action=DailyAction.NTR_ATTEMPT,
                today="2026-07-03", roll_seed=1.0,
            )
        result = await ownership_service.reset_user_action(
            "g1", "u_op", operator_is_admin=False,
            target_uid="u1", action=DailyAction.NTR_ATTEMPT,
            today="2026-07-03", roll_seed=0.0,
        )
        assert result["ok"] is False
        assert result["reason"] == "limit_reached"


# ==================== 零点清理 ====================


class TestPrune:
    @pytest.mark.asyncio
    async def test_prune_daily_counts_removes_old_days(
        self, ownership_service, mock_wife_service
    ):
        """跨天清理：仅昨日做过动作的用户记录被删，今日做过动作的保留"""
        mock_wife_service.set_images(["作品!角色.jpg"])
        # u_yest: 昨日做过动作，今日没做（保留 2026-07-03 的记录）
        await ownership_service.draw_or_get_primary(
            "g1", "u_yest", "老用户", "2026-07-03"
        )
        await ownership_service.try_ntr(
            "g1", "u_yest", "u_no_one", "老用户", "2026-07-03", roll_seed=1.0
        )
        # u_today: 今日做过动作（会覆盖 2026-07-03 的记录为 2026-07-04）
        await ownership_service.draw_or_get_primary(
            "g1", "u_today", "新用户", "2026-07-04"
        )

        # 在 2026-07-04 零点清理
        changed = await ownership_service.prune_daily_counts_for_group(
            "g1", "2026-07-04"
        )
        assert changed is True
        # u_yest 的记录已删除（因为他们 2026-07-04 没做动作，记录还是 2026-07-03）
        # u_today 的记录保留（已覆盖为 2026-07-04）
        used_today = ownership_service.get_daily_count(
            "g1", "u_today", DailyAction.CHANGE_ATTEMPT, "2026-07-04"
        )
        # 这里只是 smoke：prune 没有删除今日用户的记录
        # 实际验证：u_yest 的记录在 prune 后应消失
        # 但 get_daily_count 会返回 0（因为记录不存在），无法区分"今日 0 次"与"已删除"
        # 改为直接读文件验证
        from app.storage.stores import DailyCountStore
        store = ownership_service._daily_count_store("g1")
        data = store.load_all()
        assert "u_yest" not in data  # 整个用户记录被清掉（无今日动作）

    @pytest.mark.asyncio
    async def test_prune_swap_requests_removes_old(
        self, ownership_service, mock_wife_service
    ):
        mock_wife_service.set_images(["A!A.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_a", "A", "2026-07-03")
        mock_wife_service.set_images(["B!B.jpg"])
        await ownership_service.draw_or_get_primary("g1", "u_b", "B", "2026-07-03")
        await ownership_service.create_swap_request("g1", "u_a", "u_b", "2026-07-03")

        changed = await ownership_service.prune_swap_requests_for_group(
            "g1", "2026-07-04"
        )
        assert changed is True
        # 2026-07-04 视图下，2026-07-03 的请求已删除
        assert ownership_service.list_swap_requests("g1", "2026-07-04") == {}

    @pytest.mark.asyncio
    async def test_prune_idempotent_when_clean(self, ownership_service):
        changed = await ownership_service.prune_daily_counts_for_group(
            "g1", "2026-07-03"
        )
        assert changed is False
