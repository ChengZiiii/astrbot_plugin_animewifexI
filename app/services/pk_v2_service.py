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
from ..storage.stores import PkBattleStore, PkPairStore
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
        battle_store: Optional[Any] = None,   # 可注入 PkBattleStore 或 mock
        pair_store: Optional[Any] = None,    # 可注入 PkPairStore 或 mock
        profile_store_provider: Optional[Callable[[str], Any]] = None,
        ownership_store_provider: Optional[Callable[[str], Any]] = None,
    ):
        self._paths = paths
        self._config = config
        self._locks = locks
        self._send = send_message

        # 默认从 paths 构造；测试可注入 mock
        self._battle_store = battle_store
        self._pair_store = pair_store
        self._profile_store_provider = profile_store_provider
        self._ownership_store_provider = ownership_store_provider

        # in-memory umo 派发表（bot 重启会丢失 — spec §S7.6 兜底）
        self._battle_umos: Dict[str, str] = {}

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

    def _get_pair_store(self, gid: str) -> Any:
        if self._pair_store is not None:
            return self._pair_store
        if self._paths is not None:
            return PkPairStore(self._paths, gid)
        raise RuntimeError("PkV2Service: neither pair_store nor paths provided")

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

        1. 保存 ``battle`` 到 PkBattleStore（崩溃恢复用）
        2. 推送启动贴（带 umo + 双方编队 + 战力）
        3. ``asyncio.create_task(self._auto_advance_battle(battle, umo))``
           （无 running loop 时静默 try/except）
        4. 返回 ``"✅ 4v4 接力战启动！请查看后续战报..."``
        """
        # 1) 持 umo（in-memory dict）
        self._battle_umos[battle.battle_id] = umo

        # 2) 保存到 PkBattleStore
        self._save_battle(battle)

        # 3) 推启动贴
        await self._emit_init_message(battle, umo)

        # 4) 启动后台协程（defensive: 没有 loop 时静默失败）
        try:
            asyncio.create_task(self._auto_advance_battle(battle, umo))
        except RuntimeError as e:
            logger.warning(
                f"pk_v2 无法创建后台协程（无 running loop）: battle_id={battle.battle_id}, err={e}"
            )
            self._error = str(e)

        return "✅ 4v4 接力战启动！请查看后续战报..."

    # ---------- 内部：消息推送 ----------

    async def _safe_send(self, umo: str, text: str, *, tag: str = "") -> None:
        """包了 try/except 的 send，避免协程因网络错误崩溃。"""
        if self._send is None:
            logger.debug(f"pk_v2 send skipped (no sender): {tag}")
            return
        try:
            await self._send(umo, text)
        except Exception:
            logger.exception(f"pk_v2 send failed: {tag}, umo={umo}")

    async def _emit_init_message(self, battle: PkBattle, umo: str) -> None:
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
        await self._safe_send(umo, msg, tag="init_message")

    async def _emit_turn_message(
        self,
        battle: PkBattle,
        turn_idx: int,
        umo: str,
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
        await self._safe_send(umo, msg, tag=f"turn_{turn_idx}")

    async def _emit_death_message(
        self,
        battle: PkBattle,
        victim: FormationMember,
        next_member: Optional[FormationMember],
        side: str,
    ) -> None:
        umo = self._battle_umos.get(battle.battle_id, "")
        # 死亡贴用 [侧·昵称] 标签（attack_results 已经是 +1 events）
        tag_victim = _side_tag(victim, side)
        tag_next = _side_tag(next_member, side) if next_member else ""
        if tag_next:
            text = f"💀 [{tag_victim}] 倒下了！\n   [{tag_next}] 上场接战！"
        else:
            text = f"💀 [{tag_victim}] 倒下了！"
        await self._safe_send(umo, text, tag=f"death_{side}")

    async def _emit_settle_message(self, battle: PkBattle, umo: str) -> None:
        # 找 winner / loser / kills / dmg
        winner_uid = battle.winner_uid
        atk_kills = sum(m.kills for m in battle.atk_formation)
        def_kills = sum(m.kills for m in battle.def_formation)
        atk_dmg_total = sum(m.damage_dealt for m in battle.atk_formation)
        def_dmg_total = sum(m.damage_dealt for m in battle.def_formation)
        # 己方损耗 = 受到的伤害
        atk_taken = sum(m.damage_taken for m in battle.atk_formation)
        def_taken = sum(m.damage_taken for m in battle.def_formation)
        if winner_uid == battle.atk_uid:
            winner_nick = battle.atk_nick
            loser_uid = battle.def_uid
            loser_nick = battle.def_nick
            winner_kills = atk_kills
            loser_kills = def_kills
            winner_dmg_taken = atk_taken
            loser_dmg_taken = def_taken
        else:
            winner_nick = battle.def_nick
            loser_uid = battle.atk_uid
            loser_nick = battle.atk_nick
            winner_kills = def_kills
            loser_kills = atk_kills
            winner_dmg_taken = def_taken
            loser_dmg_taken = atk_taken

        # 段位
        from .pk_service import PkService
        winner_profile = self._load_profile(battle.gid, winner_uid)
        loser_profile = self._load_profile(battle.gid, loser_uid)
        winner_score = winner_profile.pk_score if winner_profile else 0
        loser_score = loser_profile.pk_score if loser_profile else 0
        winner_rank = PkService.get_pk_rank(winner_score)
        loser_rank = PkService.get_pk_rank(loser_score)

        # 奖励数字（实际发放见 _apply_rewards）
        if battle.end_reason == "timeout":
            reward_winner = self._config.pk_tie_reward
            reward_loser = self._config.pk_tie_reward
            score_gain = self._config.pk_score_per_lose
            winner_score_gain = score_gain
            loser_score_gain = score_gain
        else:
            reward_winner = self._config.pk_winner_reward
            winner_score_gain = self._config.pk_score_per_win
            # 战力差判 close_threshold（这里简化为 loser_close = 总伤害差 ≤ 200）
            power_diff = abs(winner_dmg_taken - loser_dmg_taken)
            if power_diff < 200:
                reward_loser = self._config.pk_loser_reward_close_threshold
                loser_score_gain = int(self._config.pk_score_per_lose)
            else:
                reward_loser = self._config.pk_loser_reward
                loser_score_gain = 0

        # 双方出过战的成员（一览）
        formations_hero: List[Tuple[str, int, bool]] = []
        for m in battle.atk_formation:
            formations_hero.append((m.nickname, m.kills, True))
        for m in battle.def_formation:
            formations_hero.append((m.nickname, m.kills, False))

        text = render_settle_message(
            winner_uid=winner_uid,
            winner_nick=winner_nick,
            loser_uid=loser_uid,
            loser_nick=loser_nick,
            atk_kills=atk_kills, def_kills=def_kills,
            atk_dmg_total=atk_dmg_total, def_dmg_total=def_dmg_total,
            reward_winner=int(reward_winner),
            reward_loser=int(reward_loser),
            winner_score_gain=int(winner_score_gain),
            loser_score_gain=int(loser_score_gain),
            winner_rank=winner_rank,
            loser_rank=loser_rank,
            formations_hero=formations_hero,
            target_needs_formation=False,
        )
        await self._safe_send(umo, text, tag="settle_message")

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

    def _record_pk_pair(self, battle: PkBattle) -> None:
        store = self._get_pair_store(battle.gid)
        data = store.load_all()
        try:
            store.record_pk(data, battle.atk_uid, battle.def_uid)
            store.save_all(data)
        except Exception:
            logger.exception("pk_v2 record_pk_pair 失败")

    def _load_profile(self, gid: str, uid: str):
        store = self._get_profile_store(gid)
        profiles = store.load_all()
        return profiles.get(uid)

    # ---------- 奖励（沿用 Phase 4 PK 规则） ----------

    def _apply_rewards(self, battle: PkBattle) -> None:
        """按 §S9 发放币 + 积分。winner / loser 加到对应 profile。"""
        gid = battle.gid
        winner_uid = battle.winner_uid
        if winner_uid == battle.atk_uid:
            loser_uid = battle.def_uid
        else:
            loser_uid = battle.atk_uid

        # 决定奖励
        if battle.end_reason == "timeout":
            winner_coins = int(self._config.pk_tie_reward)
            loser_coins = int(self._config.pk_tie_reward)
            winner_score = int(self._config.pk_score_per_lose)
            loser_score = int(self._config.pk_score_per_lose)
        else:
            winner_coins = int(self._config.pk_winner_reward)
            winner_score = int(self._config.pk_score_per_win)
            # 战力差判 close（用双方存活成员 HP 总量作近似）
            winner_total_hp = sum(
                m.base_hp for m in (battle.atk_formation if winner_uid == battle.atk_uid else battle.def_formation)
            )
            loser_total_hp = sum(
                m.base_hp for m in (battle.atk_formation if winner_uid != battle.atk_uid else battle.def_formation)
            )
            power_diff_ratio = abs(winner_total_hp - loser_total_hp) / max(winner_total_hp + loser_total_hp, 1)
            if power_diff_ratio < 0.5:
                loser_coins = int(self._config.pk_loser_reward_close_threshold)
                loser_score = int(self._config.pk_score_per_lose)
            else:
                loser_coins = int(self._config.pk_loser_reward)
                loser_score = 0

        # 加载 profiles
        store = self._get_profile_store(gid)
        profiles = store.load_all()
        from ..storage.stores import ProfileStore
        winner_profile = ProfileStore.get_or_create(
            profiles, winner_uid,
            battle.atk_nick if winner_uid == battle.atk_uid else battle.def_nick,
            self._config.initial_coins,
        )
        loser_profile = ProfileStore.get_or_create(
            profiles, loser_uid,
            battle.def_nick if winner_uid == battle.atk_uid else battle.atk_nick,
            self._config.initial_coins,
        )

        # pk_score 按月懒重置（沿用 PkService 规则）
        current_month = _current_month()
        if winner_profile.pk_score_season != current_month:
            winner_profile.pk_score = 0
            winner_profile.pk_score_season = current_month
        if loser_profile.pk_score_season != current_month:
            loser_profile.pk_score = 0
            loser_profile.pk_score_season = current_month

        winner_profile.coins += winner_coins
        winner_profile.pk_score += winner_score
        winner_profile.total_pk_win = winner_profile.total_pk_win + 1
        winner_profile.pk_last_active_date = _today_str()

        loser_profile.coins += loser_coins
        loser_profile.pk_score += loser_score
        loser_profile.total_pk_lost = loser_profile.total_pk_lost + 1
        loser_profile.pk_last_active_date = _today_str()

        store.save_all(profiles)
        logger.debug(
            f"pk_v2 rewards: winner={winner_uid} +{winner_coins}币 +{winner_score}分; "
            f"loser={loser_uid} +{loser_coins}币 +{loser_score}分"
        )

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
        delay_s = max(int(self._config.pk_v2_turn_delay_ms), 0) / 1000.0

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

            # ==== 推回合贴 ====
            await self._emit_turn_message(battle, turn_idx, umo, attack_events)

            # ==== 检测死亡换人 → 推死亡贴 ====
            new_atk_pos = battle.active_idx[0]
            new_df_pos = battle.active_idx[1]
            if new_atk_pos != prev_atk_pos:
                # prev_atk_pos 位置的成员死了
                if 1 <= prev_atk_pos <= len(battle.atk_formation):
                    dead = battle.atk_formation[prev_atk_pos - 1]
                    if not dead.is_alive:
                        next_m = (
                            battle.atk_formation[new_atk_pos - 1]
                            if 1 <= new_atk_pos <= len(battle.atk_formation)
                            else None
                        )
                        await self._emit_death_message(battle, dead, next_m, "atk")
            if new_df_pos != prev_df_pos:
                if 1 <= prev_df_pos <= len(battle.def_formation):
                    dead = battle.def_formation[prev_df_pos - 1]
                    if not dead.is_alive:
                        next_m = (
                            battle.def_formation[new_df_pos - 1]
                            if 1 <= new_df_pos <= len(battle.def_formation)
                            else None
                        )
                        await self._emit_death_message(battle, dead, next_m, "def")

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
            if delay_s > 0:
                await asyncio.sleep(delay_s)

        # 兜底：如果循环退出时没确定 winner（如某种 corner case），用 check_timeout 一次
        if not battle.winner_uid:
            winner_uid = check_timeout(battle)
            if winner_uid:
                battle.winner_uid = winner_uid
                battle.end_reason = "timeout" if battle.turn_idx >= PkV2Defaults.MAX_TURNS else "all_dead"

        # ==== 结算 ====
        battle.status = "done"
        battle.finished_at = now_ts()
        self._apply_rewards(battle)
        await self._emit_settle_message(battle, umo)

        # ==== 后置清理：record_pk + delete battle ====
        self._record_pk_pair(battle)
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
