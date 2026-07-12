"""v3 接力战 · PkV2Service：4v4 战斗服务 + 主动消息协程。

对应 spec `v3_接力战_主线.md`：

* §S4.2 — ``start_battle`` 启动入口（前置编队校验 + 启动贴 + 后台协程）
* §S5 — 战斗状态机（INIT → TURN ×N → SETTLE → DONE）
* §S7.6 — 24h 同对手防刷 + 结算清理
* §S9 — 结算奖励（15 币/5 分胜 / 5 币/1 分败 / 8 币/2 分平）
* §S10 — 配置项（``pk_v2_turn_delay_ms`` 等）

设计要点：

* **构造函数注入** 关键依赖（``send_message`` / ``battle_store`` / ``pair_store`` /
  ``profile_store_provider``），便于单测与不在生产环境跑 AstrBot 真实接口。
* **umo 不持久化到 PkBattle**（Phase B 已定字段不可改）：用服务级 in-memory dict
  ``_battle_umos`` 按 ``battle_id`` 保存；bot 重启会丢失 umo，按 spec §S7.6 兜底。
* **do_turn + 速度 + 13 乘数** 直接复用 :func:`app.services.pk_v2_battle` 中的函数。
* **奖励** 通过现有 ``ProfileStore`` + economy 加分，避免触动 Phase E/F 的 economy_service。
* **协程异常被吞**：每条 send 包 try/except；不让 bot 崩溃。
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..models.pk_battle import BattleStatusLayer, FormationMember, PkBattle
from ..storage.stores import PkBattleStore, ProfileStore
from ..utils.time import now_ts
from .pk_v2_battle import (
    PkV2Defaults,
    check_timeout,
    do_turn,
)
from .pk_v2_messages import (
    render_death_message,
    render_init_message,
    render_settle_message,
    render_turn_message,
)

logger = logging.getLogger("astrbot_plugin_animewifex.pk_v2")

__all__ = ["PkV2Service", "PkStartResult"]

SendMessage = Callable[[str, str], Awaitable[None]]
SendNodes = Callable[[str, int, str, Sequence[str]], Awaitable[None]]


@dataclass
class PkStartResult:
    """``start_battle`` 的返回结果。"""

    ok: bool
    ack_text: str = ""
    reason: str = ""
    battle_id: str = ""

    def __bool__(self) -> bool:  # pragma: no cover (用 ok 字段即可)
        return self.ok


class PkV2Service:
    """v3 接力战战斗服务。

    生产路径：从 ``cmd_ctx`` 注入 ``paths`` / ``config`` / ``locks`` / ``send_message``；
    测试路径：注入 mock 依赖直接调用 ``start_battle`` / ``_auto_advance_battle``。
    """

    def __init__(
        self,
        paths,
        config,
        locks=None,
        *,
        send_message: Optional[SendMessage] = None,
        send_node: Optional["SendNodes"] = None,
        forward_sender_id: int = 0,
        forward_sender_name: str = "哆啦b梦",
        battle_store: Optional[Any] = None,   # 可注入 PkBattleStore 或 mock
        profile_store_provider: Optional[Callable[[str], Any]] = None,
        ownership_store_provider: Optional[Callable[[str], Any]] = None,
        lifespan_service: Optional[Any] = None,  # Phase 6: 寿命系统
    ):
        self._paths = paths
        self._config = config
        self._locks = locks
        self._send = send_message
        # 合并转发发送回调：args(umo, sender_id, sender_name, texts)
        # 当提供时，_flush_buffer 把缓存里每条文本包成一个 Node 一起发；
        # 不提供时回退到 _send 把所有文本拼成一条长消息。
        self._send_node = send_node
        self._forward_sender_id = int(forward_sender_id or 0)
        self._forward_sender_name = forward_sender_name or "哆啦b梦"

        # 默认从 paths 构造；测试可注入 mock
        self._battle_store = battle_store
        self._profile_store_provider = profile_store_provider
        self._ownership_store_provider = ownership_store_provider
        self._lifespan = lifespan_service

        # in-memory umo 派发表（bot 重启会丢失 — spec §S7.6 兜底）
        self._battle_umos: Dict[str, str] = {}

        # 消息缓存：battle_id → 合并转发的文本列表
        self._message_buffers: Dict[str, List[str]] = {}

        # 标记，便于测试断言
        self._settled: bool = False
        self._error: Optional[str] = None

    # ---------- 工厂方法（供生产使用） ----------

    def _get_battle_store(self, gid: str) -> Any:
        if self._battle_store is not None:
            return self._battle_store
        if self._paths is not None:
            return PkBattleStore(self._paths, gid)
        raise RuntimeError("PkV2Service: neither battle_store nor paths provided")

    def _get_profile_store(self, gid: str) -> Any:
        if self._profile_store_provider is not None:
            return self._profile_store_provider(gid)
        from ..storage.stores import ProfileStore
        return ProfileStore(self._paths, gid)

    def _get_ownership_store(self, gid: str) -> Any:
        if self._ownership_store_provider is not None:
            return self._ownership_store_provider(gid)
        from ..storage.stores import OwnershipStore
        return OwnershipStore(self._paths, gid)

    # ---------- 公共 API ----------

    async def start_battle(
        self,
        battle: PkBattle,
        umo: str,
    ) -> str:
        """启动战斗并返回给用户的同步回复文本。

        流程：

        1. 初始化消息缓存（battle_id → []）
        2. 保存 ``battle`` 到 PkBattleStore（崩溃恢复用）
        3. 推送启动贴 **到缓存**（合并后一次性发送）
        4. ``asyncio.create_task(self._auto_advance_battle(battle, umo))``
           （无 running loop 时静默 try/except）
        5. 返回 ``"✅ 4v4 接力战启动！请查看后续战报..."``
        """
        # 1) 初始化消息缓存
        self._message_buffers[battle.battle_id] = []
        self._battle_umos[battle.battle_id] = umo

        # 2) 推送启动贴 → 缓存
        await self._buffer_init_message(battle)

        # 3) 保存到 PkBattleStore
        self._save_battle(battle)

        # 4) 启动后台协程（defensive: 没有 loop 时静默失败）
        try:
            asyncio.create_task(self._auto_advance_battle(battle, umo))
        except RuntimeError as e:
            logger.warning(
                f"pk_v2 无法创建后台协程（无 running loop）: battle_id={battle.battle_id}, err={e}"
            )
            self._error = str(e)

        return "✅ 4v4 接力战启动！正在生成战报..."

    # ---------- 内部：消息缓存 + 合并发送 ----------

    def _buffer_append(self, battle_id: str, text: str) -> None:
        """向合并转发缓存追加一条消息文本。"""
        if battle_id in self._message_buffers:
            self._message_buffers[battle_id].append(text)

    async def _flush_buffer(self, battle_id: str, umo: str) -> None:
        """将所有缓存消息一次性推送。

        * 有 ``send_node`` 回调时：每条文本 = 一个 Node → 走合并转发（QQ 聊天记录卡片）
        * 否则：回退到老逻辑 —— 所有文本拼成一条长消息发出
        """
        msgs = self._message_buffers.pop(battle_id, [])
        if not msgs:
            return
        # 优先用合并转发（每条独立 Node，UI 可折叠展开）
        if self._send_node is not None and self._forward_sender_id > 0:
            try:
                await self._send_node(
                    umo,
                    self._forward_sender_id,
                    self._forward_sender_name,
                    list(msgs),
                )
                return
            except Exception:
                logger.exception(
                    f"pk_v2 flush_buffer send_node failed: battle_id={battle_id}，回退到 send_message"
                )
        # 回退：合并为一条长消息
        combined = "\n\n────────────\n\n".join(msgs)
        if self._send is not None:
            try:
                await self._send(umo, combined)
            except Exception:
                logger.exception(f"pk_v2 flush_buffer send failed: battle_id={battle_id}")

    async def _buffer_init_message(self, battle: PkBattle) -> None:
        atk_f = list(battle.atk_formation)
        def_f = list(battle.def_formation)
        msg = render_init_message(
            atk_formation=atk_f,
            def_formation=def_f,
            atk_uid=battle.atk_uid,
            atk_nick=battle.atk_nick,
            def_uid=battle.def_uid,
            def_nick=battle.def_nick,
        )
        self._buffer_append(battle.battle_id, msg)

    def _buffer_turn_message(
        self,
        battle: PkBattle,
        turn_idx: int,
        attack_events: Sequence[dict],
    ) -> None:
        atk_pos = battle.active_idx[0]
        df_pos = battle.active_idx[1]
        atk_member = battle.atk_formation[atk_pos - 1]
        df_member = battle.def_formation[df_pos - 1]
        atk_status = battle.atk_status_layers[atk_pos - 1]
        df_status = battle.def_status_layers[df_pos - 1]
        msg = render_turn_message(
            turn_idx=turn_idx,
            atk_member=atk_member,
            df_member=df_member,
            atk_status=atk_status,
            df_status=df_status,
            attack_results=attack_events,
        )
        self._buffer_append(battle.battle_id, msg)

    def _buffer_death_message(
        self,
        battle: PkBattle,
        victim: FormationMember,
        next_member: Optional[FormationMember],
        side: str,
    ) -> None:
        tag_victim = _side_tag(victim, side)
        tag_next = _side_tag(next_member, side) if next_member else ""
        if tag_next:
            text = f"💀 [{tag_victim}] 倒下了！\n   [{tag_next}] 上场接战！"
        else:
            text = f"💀 [{tag_victim}] 倒下了！"
        self._buffer_append(battle.battle_id, text)

    def _buffer_settle_message(self, battle: PkBattle) -> None:
        # 单一奖励决策（显示与发放共用）
        rewards = self.decide_rewards(battle, self._config)
        is_tie = rewards["is_tie"]
        winner_uid = rewards["winner_uid"]
        loser_uid = rewards["loser_uid"]

        atk_kills = sum(m.kills for m in battle.atk_formation)
        def_kills = sum(m.kills for m in battle.def_formation)
        atk_dmg_total = sum(m.damage_dealt for m in battle.atk_formation)
        def_dmg_total = sum(m.damage_dealt for m in battle.def_formation)

        if is_tie:
            winner_nick = battle.atk_nick
            loser_nick = battle.def_nick
        else:
            winner_nick = battle.atk_nick if winner_uid == battle.atk_uid else battle.def_nick
            loser_nick = battle.def_nick if winner_uid == battle.def_uid else battle.atk_nick

        from .pk_service import PkService
        atk_profile = self._load_profile(battle.gid, battle.atk_uid)
        def_profile = self._load_profile(battle.gid, battle.def_uid)
        atk_score = atk_profile.pk_score if atk_profile else 0
        def_score = def_profile.pk_score if def_profile else 0
        if is_tie:
            winner_score, loser_score = atk_score, def_score
        elif winner_uid == battle.atk_uid:
            winner_score, loser_score = atk_score, def_score
        else:
            winner_score, loser_score = def_score, atk_score
        winner_rank = PkService.get_pk_rank(winner_score)
        loser_rank = PkService.get_pk_rank(loser_score)

        formations_hero: List[Tuple[str, int, bool]] = []
        for m in battle.atk_formation:
            formations_hero.append((m.nickname, m.kills, True))
        for m in battle.def_formation:
            formations_hero.append((m.nickname, m.kills, False))

        atk_total = len(battle.atk_formation)
        def_total = len(battle.def_formation)
        atk_total_hp = sum(m.base_hp for m in battle.atk_formation)
        def_total_hp = sum(m.base_hp for m in battle.def_formation)

        if is_tie:
            target_needs_formation = False
        else:
            loser_formation = battle.def_formation if loser_uid == battle.def_uid else battle.atk_formation
            target_needs_formation = len(loser_formation) < 4

        text = render_settle_message(
            winner_uid=winner_uid,
            winner_nick=winner_nick,
            loser_uid=loser_uid,
            loser_nick=loser_nick,
            atk_kills=atk_kills, def_kills=def_kills,
            atk_dmg_total=atk_dmg_total, def_dmg_total=def_dmg_total,
            reward_winner=int(rewards["win_coins"]),
            reward_loser=int(rewards["lose_coins"]),
            winner_score_gain=int(rewards["win_score"]),
            loser_score_gain=int(rewards["lose_score"]),
            winner_rank=winner_rank,
            loser_rank=loser_rank,
            formations_hero=formations_hero,
            target_needs_formation=target_needs_formation,
            is_tie=is_tie,
            atk_total=atk_total, def_total=def_total,
            atk_total_hp=atk_total_hp, def_total_hp=def_total_hp,
            # 平局分支渲染"攻方/守方"行需要这两个玩家昵称
            atk_nick=battle.atk_nick,
            def_nick=battle.def_nick,
        )
        self._buffer_append(battle.battle_id, text)

    # ---------- 持久化 ----------

    def _save_battle(self, battle: PkBattle) -> None:
        store = self._get_battle_store(battle.gid)
        try:
            store.save(battle.gid, battle.battle_id, battle)
        except Exception:
            logger.exception(f"pk_v2 save battle 失败: {battle.battle_id}")

    def _delete_battle(self, battle: PkBattle) -> None:
        store = self._get_battle_store(battle.gid)
        try:
            store.delete(battle.gid, battle.battle_id)
        except Exception:
            logger.exception(f"pk_v2 delete battle 失败: {battle.battle_id}")

    def _load_profile(self, gid: str, uid: str):
        store = self._get_profile_store(gid)
        profiles = store.load_all()
        return profiles.get(uid)

    # ---------- 奖励（§S9 经济表：单一决策驱动显示 + 发放） ----------

    def decide_rewards(self, battle: PkBattle, config) -> dict:
        """单一奖励决策：同时驱动 ``_emit_settle_message``（显示）与 ``_apply_rewards``（发放）。

        按 spec §S9 / §S7.1 判定：

        * 用双方**剩余 HP（存活成员 current_hp）** 判胜负（HP 比定胜）。
        * 双方都存活且剩余 HP 相等 → 真·平局（``is_tie=True``），双方 +8 币 / +2 分。
        * 否则胜方：+15 币 / +5 分。
        * 负方按"战力差 ≤ 50%" 区分：
          - 败方剩余 HP ≥ 胜方剩余 HP 的 50%（即战力差小、险胜）→ +5 币 / +1 分；
          - 否则（大劣势）→ +1 币 / +0 分。

        返回 dict：
            win_coins / win_score / lose_coins / lose_score / is_tie /
            winner_uid / loser_uid
        """
        atk_total = sum(m.current_hp for m in battle.atk_formation if m.is_alive)
        def_total = sum(m.current_hp for m in battle.def_formation if m.is_alive)

        win_coins = int(config.pk_winner_reward)
        win_score = int(config.pk_score_per_win)

        # 真·平局：双方都存活且剩余 HP 相等
        if atk_total > 0 and def_total > 0 and atk_total == def_total:
            tie_coins = int(config.pk_tie_reward)
            return {
                "win_coins": tie_coins, "win_score": 2,
                "lose_coins": tie_coins, "lose_score": 2,
                "is_tie": True,
                "winner_uid": battle.atk_uid,   # 平局占位，显示用
                "loser_uid": battle.def_uid,
            }

        # 非平局：HP 比判胜（沿用 §S7.1）
        if atk_total > def_total:
            winner_uid, loser_uid = battle.atk_uid, battle.def_uid
            winner_total_hp, loser_total_hp = atk_total, def_total
        elif def_total > atk_total:
            winner_uid, loser_uid = battle.def_uid, battle.atk_uid
            winner_total_hp, loser_total_hp = def_total, atk_total
        else:
            # 双方剩余 HP 均为 0（全灭且 HP 同为 0）→ 沿用状态机已判定的 winner
            winner_uid = battle.winner_uid or battle.atk_uid
            loser_uid = battle.def_uid if winner_uid == battle.atk_uid else battle.atk_uid
            winner_total_hp, loser_total_hp = 0, 0

        # 战力差：败方剩余 HP 占胜方比例（≥ 0.5 = 险胜/近战差）
        ratio = (loser_total_hp / winner_total_hp) if winner_total_hp > 0 else 0.0
        if ratio >= 0.5:
            lose_coins = int(config.pk_loser_reward)
            lose_score = int(config.pk_score_per_lose)
        else:
            lose_coins = 1
            lose_score = 0

        return {
            "win_coins": win_coins, "win_score": win_score,
            "lose_coins": lose_coins, "lose_score": lose_score,
            "is_tie": False, "winner_uid": winner_uid, "loser_uid": loser_uid,
        }

    def _apply_rewards(self, battle: PkBattle) -> None:
        """按 §S9 发放币 + 积分。实际数字全部来自 ``decide_rewards``（单一决策）。"""
        gid = battle.gid
        rewards = self.decide_rewards(battle, self._config)

        store = self._get_profile_store(gid)
        profiles = store.load_all()

        def _get(uid: str, nick: str):
            return ProfileStore.get_or_create(profiles, uid, nick, self._config.initial_coins)

        def _season_reset(p) -> None:
            current_month = _current_month()
            if p.pk_score_season != current_month:
                p.pk_score = 0
                p.pk_score_season = current_month

        if rewards["is_tie"]:
            # 平局：双方都 +8 币 / +2 分，不计胜负场次
            for uid, nick, coins, score in (
                (battle.atk_uid, battle.atk_nick, rewards["win_coins"], rewards["win_score"]),
                (battle.def_uid, battle.def_nick, rewards["lose_coins"], rewards["lose_score"]),
            ):
                p = _get(uid, nick)
                _season_reset(p)
                p.coins += coins
                p.pk_score += score
                p.pk_last_active_date = _today_str()
            store.save_all(profiles)
            logger.debug(
                f"pk_v2 rewards (tie): atk={battle.atk_uid} +{rewards['win_coins']}币; "
                f"def={battle.def_uid} +{rewards['lose_coins']}币"
            )
            return

        winner_uid = rewards["winner_uid"]
        loser_uid = rewards["loser_uid"]
        winner_nick = battle.atk_nick if winner_uid == battle.atk_uid else battle.def_nick
        loser_nick = battle.def_nick if winner_uid == battle.def_uid else battle.atk_nick

        wp = _get(winner_uid, winner_nick)
        _season_reset(wp)
        lp = _get(loser_uid, loser_nick)
        _season_reset(lp)

        wp.coins += rewards["win_coins"]
        wp.pk_score += rewards["win_score"]
        wp.total_pk_win = wp.total_pk_win + 1
        wp.pk_last_active_date = _today_str()

        lp.coins += rewards["lose_coins"]
        lp.pk_score += rewards["lose_score"]
        lp.total_pk_lost = lp.total_pk_lost + 1
        lp.pk_last_active_date = _today_str()

        store.save_all(profiles)
        logger.debug(
            f"pk_v2 rewards: winner={winner_uid} +{rewards['win_coins']}币 +{rewards['win_score']}分; "
            f"loser={loser_uid} +{rewards['lose_coins']}币 +{rewards['lose_score']}分"
        )

        # Phase 6: 战斗后扣寿命 + 死亡检查
        self._apply_lifespan_damage(battle)

    def _apply_lifespan_damage(self, battle: PkBattle) -> None:
        """Phase 6: 战斗结束后对所有参战老婆扣寿命 + 死亡检查。

        新算法（v2，按 hp 损失比例折算）：

        - 胜方参战老婆：不扣寿命（打赢了不受惩罚）
        - 平局每个参战老婆：扣 lifespan_loss_pk_tie（默认 8）
        - 败方被击败老婆（is_alive=False）：扣 pk_loser_defeat_penalty（默认 5）
        - 败方存活老婆：按 hp 损失比例折算
            loss = max(1, min(int(hp_ratio * hp_loss_per_point / 100 * lifespan_max),
                              pk_loser_defeat_penalty * 2))

        死亡检查走 lifespan_service.apply_damage。
        """
        if not self._lifespan:
            return
        if not getattr(self._config, "lifespan_enabled", True):
            return

        from .lifespan_service import DEATH_CAUSE_PK

        is_tie = bool(battle.end_reason == "tie" or (
            battle.winner_uid == battle.atk_uid and battle.winner_uid == battle.def_uid
        ))
        lifespan_max = int(getattr(self._config, "lifespan_max", 100))
        defeat_penalty = int(getattr(self._config, "pk_loser_defeat_penalty", 5))
        hp_loss_per_point = float(getattr(self._config, "hp_loss_per_point", 2.0))
        tie_loss = int(getattr(self._config, "lifespan_loss_pk_tie", 8))

        def _is_winner_side(member: FormationMember) -> bool:
            """判断 member 是否在胜方编队中"""
            if is_tie:
                return False
            if not battle.winner_uid:
                return False
            if battle.winner_uid == battle.atk_uid:
                return member in battle.atk_formation
            return member in battle.def_formation

        def _calc_loss(member: FormationMember) -> int:
            """返回单个参战老婆的寿命扣减值"""
            if is_tie:
                return tie_loss
            # 胜方不扣
            if _is_winner_side(member):
                return 0
            # 败方：被打死的固定战败费
            if not member.is_alive:
                return defeat_penalty
            # 败方存活：按 hp 损失折算
            if member.base_hp <= 0:
                return defeat_penalty
            hp_ratio = member.damage_taken / member.base_hp
            raw = int(hp_ratio * hp_loss_per_point / 100 * lifespan_max)
            return max(1, min(raw, defeat_penalty * 2))

        today = datetime.now().strftime("%Y-%m-%d")
        try:
            os_store = self._get_ownership_store(battle.gid)
            ownerships = os_store.load_all()
            any_dead = []
            for w in {m.wid for m in battle.atk_formation if m.wid}:
                tgt = next((o for o in ownerships if o.wid == w), None)
                if tgt is None or tgt.is_dead:
                    continue
                member = next((m for m in battle.atk_formation if m.wid == w), None)
                if member is None:
                    continue
                loss = _calc_loss(member)
                if loss <= 0:
                    continue
                damage = self._lifespan.apply_damage_inplace(
                    tgt, loss, cause=DEATH_CAUSE_PK, today=today,
                )
                if damage.death_occurred:
                    any_dead.append(tgt)
            for w in {m.wid for m in battle.def_formation if m.wid}:
                tgt = next((o for o in ownerships if o.wid == w), None)
                if tgt is None or tgt.is_dead:
                    continue
                member = next((m for m in battle.def_formation if m.wid == w), None)
                if member is None:
                    continue
                loss = _calc_loss(member)
                if loss <= 0:
                    continue
                damage = self._lifespan.apply_damage_inplace(
                    tgt, loss, cause=DEATH_CAUSE_PK, today=today,
                )
                if damage.death_occurred:
                    any_dead.append(tgt)
            os_store.save_all(ownerships)
            for tgt in any_dead:
                self._lifespan._record_death_event(battle.gid, tgt, today)
        except Exception:
            logger.exception("pk_v2 寿命扣减失败（非阻塞）")

    # ---------- 后台协程：状态机主循环 ----------

    async def _auto_advance_battle(
        self,
        battle: PkBattle,
        umo: str,
    ) -> None:
        """状态机主循环：每回合 do_turn → 推回合贴 → 检查结束 → 结算。

        异常保护：每条 send 包 try/except；整段逻辑被外层 try/except 包住，
        让协程崩了也不会影响其他协程。
        """
        # 确保 buffer 存在（直接调 _auto_advance_battle 的测试场景）
        if battle.battle_id not in self._message_buffers:
            self._message_buffers[battle.battle_id] = []
        try:
            await self._auto_advance_battle_inner(battle, umo)
        except Exception:
            logger.exception(
                f"pk_v2 _auto_advance_battle 崩了: battle_id={battle.battle_id}"
            )
            self._error = "coroutine crashed"

    async def _auto_advance_battle_inner(
        self,
        battle: PkBattle,
        umo: str,
    ) -> None:
        from .pk_v2_battle import PkV2Defaults

        rng = random.Random(battle.rng_seed or now_ts())

        # 记录双方上回合 active，便于检测死亡换人
        prev_atk_pos = battle.active_idx[0]
        prev_df_pos = battle.active_idx[1]

        while (
            battle.turn_idx < PkV2Defaults.MAX_TURNS
            and battle.status == "active"
        ):
            turn_idx = battle.turn_idx
            # ==== do_turn ====
            result = do_turn(battle, turn_idx, rng)
            attack_events = result.get("attack_events", []) if isinstance(result, dict) else []

            # ==== 缓存回合贴 ====
            self._buffer_turn_message(battle, turn_idx, attack_events)

            # ==== 检测死亡换人 → 缓存死亡贴 ====
            new_atk_pos = battle.active_idx[0]
            new_df_pos = battle.active_idx[1]
            if new_atk_pos != prev_atk_pos:
                if 1 <= prev_atk_pos <= len(battle.atk_formation):
                    dead = battle.atk_formation[prev_atk_pos - 1]
                    if not dead.is_alive:
                        next_m = (
                            battle.atk_formation[new_atk_pos - 1]
                            if 1 <= new_atk_pos <= len(battle.atk_formation)
                            else None
                        )
                        self._buffer_death_message(battle, dead, next_m, "atk")
            if new_df_pos != prev_df_pos:
                if 1 <= prev_df_pos <= len(battle.def_formation):
                    dead = battle.def_formation[prev_df_pos - 1]
                    if not dead.is_alive:
                        next_m = (
                            battle.def_formation[new_df_pos - 1]
                            if 1 <= new_df_pos <= len(battle.def_formation)
                            else None
                        )
                        self._buffer_death_message(battle, dead, next_m, "def")

            # ==== 持久化 ====
            self._save_battle(battle)

            # ==== 检查结束 ====
            winner_uid = check_timeout(battle)
            if winner_uid:
                battle.winner_uid = winner_uid
                battle.end_reason = "all_dead" if (
                    winner_uid != battle.atk_uid or _no_alive(battle.atk_formation)
                ) else "all_dead"
                battle.status = "settling"
                if battle.turn_idx >= PkV2Defaults.MAX_TURNS:
                    battle.end_reason = "timeout"
                break

            # ==== 推进回合 ====
            battle.turn_idx = turn_idx + 1
            prev_atk_pos = new_atk_pos
            prev_df_pos = new_df_pos

        # 兜底
        if not battle.winner_uid:
            winner_uid = check_timeout(battle)
            if winner_uid:
                battle.winner_uid = winner_uid
                battle.end_reason = "timeout" if battle.turn_idx >= PkV2Defaults.MAX_TURNS else "all_dead"

        # ==== 结算 ====
        battle.status = "done"
        battle.finished_at = now_ts()
        self._apply_rewards(battle)
        self._buffer_settle_message(battle)

        # ==== 合并发送全部缓存（替代逐条推送） ====
        await self._flush_buffer(battle.battle_id, umo)

        # ==== 后置清理 ====
        self._delete_battle(battle)
        self._settled = True
        logger.debug(f"pk_v2 战斗结束: battle_id={battle.battle_id}, winner={battle.winner_uid}, end_reason={battle.end_reason}")


# ============== helpers ==============


def _side_tag(m: FormationMember, side: str) -> str:
    side_label = "攻" if side == "atk" else "守"
    intimacy = m.intimacy if m.intimacy else 0
    return f"{side_label}·{m.nickname} {m.rarity} ❤️{intimacy}"


def _no_alive(formation: Iterable[FormationMember]) -> bool:
    return not any(m.is_alive for m in formation)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")
