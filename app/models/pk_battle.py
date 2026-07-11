"""v3 接力战战斗数据模型。

包含：

* :class:`BattleStatusLayer` —— 战斗中每个老婆持有的状态层（气魄 / 弱点 / 血性 / 狂暴）。
* :class:`FormationMember` —— 编队中的单个老婆快照（基础属性 + 战斗实时状态 + 战斗统计 + 被动 id）。
* :class:`PkBattle` —— 完整战斗会话（双方编队 + 状态层 + 回合进度 + RNG + 状态机）。

设计要点：

* 每个 dataclass 都提供 :meth:`to_dict` 与 :meth:`from_dict`，便于 JSON 持久化；
* 嵌套对象（``FormationMember`` / ``BattleStatusLayer``）在 round-trip 时按列表/对象分别重建；
* ``rng_state`` 使用 ``Any``（rng 对象不可 JSON 化，但战斗中会随 ``created_at`` 一起持久化为整数 seed），
  测试中可置 ``None``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Tuple

__all__ = ["BattleStatusLayer", "FormationMember", "PkBattle"]


@dataclass
class BattleStatusLayer:
    """战斗中累积的状态层。

    字段含义见 ``game_design/v3_接力战_主线.md`` §S3.7。
    """

    qi_po: int = 0       # 气魄（攻击命中后 +1，最多 5 层，每层 +3% atk）
    weak_point: int = 0  # 弱点（被攻击命中后 +1，最多 3 层，每层 +5% 受伤）
    bloodlust: int = 0   # 血性（5/8 回合激活 +10%/15% atk）
    frenzy: bool = False  # 狂暴（HP < 30% 激活，atk +25% / speed -25%）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "qi_po": self.qi_po,
            "weak_point": self.weak_point,
            "bloodlust": self.bloodlust,
            "frenzy": self.frenzy,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BattleStatusLayer":
        return cls(
            qi_po=int(data.get("qi_po", 0) or 0),
            weak_point=int(data.get("weak_point", 0) or 0),
            bloodlust=int(data.get("bloodlust", 0) or 0),
            frenzy=bool(data.get("frenzy", False)),
        )


@dataclass
class FormationMember:
    """编队中单个老婆的战斗快照。

    包含基础属性（rarity / element / base_atk 等）+ 战斗实时状态
    （current_hp / is_alive / is_active）+ 战斗统计（kills / damage_dealt / damage_taken）
    + 派生被动 id（``passive_id``）。
    """

    wid: str
    pos: int
    nickname: str
    rarity: str
    element: str
    base_atk: int
    base_def: int
    base_hp: int
    intimacy: int
    is_locked: bool
    current_hp: int
    is_alive: bool
    is_active: bool
    kills: int = 0
    damage_dealt: int = 0
    damage_taken: int = 0
    passive_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wid": self.wid,
            "pos": self.pos,
            "nickname": self.nickname,
            "rarity": self.rarity,
            "element": self.element,
            "base_atk": self.base_atk,
            "base_def": self.base_def,
            "base_hp": self.base_hp,
            "intimacy": self.intimacy,
            "is_locked": self.is_locked,
            "current_hp": self.current_hp,
            "is_alive": self.is_alive,
            "is_active": self.is_active,
            "kills": self.kills,
            "damage_dealt": self.damage_dealt,
            "damage_taken": self.damage_taken,
            "passive_id": self.passive_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FormationMember":
        return cls(
            wid=str(data.get("wid", "") or ""),
            pos=int(data.get("pos", 0) or 0),
            nickname=str(data.get("nickname", "") or ""),
            rarity=str(data.get("rarity", "") or ""),
            element=str(data.get("element", "") or ""),
            base_atk=int(data.get("base_atk", 0) or 0),
            base_def=int(data.get("base_def", 0) or 0),
            base_hp=int(data.get("base_hp", 0) or 0),
            intimacy=int(data.get("intimacy", 0) or 0),
            is_locked=bool(data.get("is_locked", False)),
            current_hp=int(data.get("current_hp", 0) or 0),
            is_alive=bool(data.get("is_alive", False)),
            is_active=bool(data.get("is_active", False)),
            kills=int(data.get("kills", 0) or 0),
            damage_dealt=int(data.get("damage_dealt", 0) or 0),
            damage_taken=int(data.get("damage_taken", 0) or 0),
            passive_id=str(data.get("passive_id", "") or ""),
        )


@dataclass
class PkBattle:
    """完整战斗会话。

    双方各持编队 ``formation``（每个成员是 :class:`FormationMember`）和
    状态层 ``status_layers``（每个成员是 :class:`BattleStatusLayer`），
    长度一致。``turn_idx`` / ``active_idx`` 推进回合，``status`` 控制状态机
    （``active`` / ``settling`` / ``done``），``log`` 留作战斗回放。
    """

    gid: str
    battle_id: str
    atk_uid: str
    atk_nick: str
    def_uid: str
    def_nick: str
    atk_formation: List[FormationMember] = field(default_factory=list)
    def_formation: List[FormationMember] = field(default_factory=list)
    atk_status_layers: List[BattleStatusLayer] = field(default_factory=list)
    def_status_layers: List[BattleStatusLayer] = field(default_factory=list)
    turn_idx: int = 0
    active_idx: Tuple[int, int] = (1, 1)
    rng_seed: int = 0
    rng_state: Any = None
    status: str = "active"
    winner_uid: str = ""
    end_reason: str = ""
    log: List[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    finished_at: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gid": self.gid,
            "battle_id": self.battle_id,
            "atk_uid": self.atk_uid,
            "atk_nick": self.atk_nick,
            "def_uid": self.def_uid,
            "def_nick": self.def_nick,
            "atk_formation": [m.to_dict() for m in self.atk_formation],
            "def_formation": [m.to_dict() for m in self.def_formation],
            "atk_status_layers": [s.to_dict() for s in self.atk_status_layers],
            "def_status_layers": [s.to_dict() for s in self.def_status_layers],
            "turn_idx": self.turn_idx,
            "active_idx": list(self.active_idx),
            "rng_seed": self.rng_seed,
            "rng_state": self.rng_state,
            "status": self.status,
            "winner_uid": self.winner_uid,
            "end_reason": self.end_reason,
            "log": list(self.log),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PkBattle":
        atk_formation_raw = data.get("atk_formation") or []
        if not isinstance(atk_formation_raw, list):
            atk_formation_raw = []
        def_formation_raw = data.get("def_formation") or []
        if not isinstance(def_formation_raw, list):
            def_formation_raw = []
        atk_layers_raw = data.get("atk_status_layers") or []
        if not isinstance(atk_layers_raw, list):
            atk_layers_raw = []
        def_layers_raw = data.get("def_status_layers") or []
        if not isinstance(def_layers_raw, list):
            def_layers_raw = []

        active_idx_raw = data.get("active_idx") or [1, 1]
        if (
            not isinstance(active_idx_raw, (list, tuple))
            or len(active_idx_raw) != 2
        ):
            active_idx_raw = (1, 1)
        else:
            active_idx_raw = (
                int(active_idx_raw[0] or 1),
                int(active_idx_raw[1] or 1),
            )

        log_raw = data.get("log") or []
        if not isinstance(log_raw, list):
            log_raw = []

        return cls(
            gid=str(data.get("gid", "") or ""),
            battle_id=str(data.get("battle_id", "") or ""),
            atk_uid=str(data.get("atk_uid", "") or ""),
            atk_nick=str(data.get("atk_nick", "") or ""),
            def_uid=str(data.get("def_uid", "") or ""),
            def_nick=str(data.get("def_nick", "") or ""),
            atk_formation=[FormationMember.from_dict(m) for m in atk_formation_raw],
            def_formation=[FormationMember.from_dict(m) for m in def_formation_raw],
            atk_status_layers=[BattleStatusLayer.from_dict(s) for s in atk_layers_raw],
            def_status_layers=[BattleStatusLayer.from_dict(s) for s in def_layers_raw],
            turn_idx=int(data.get("turn_idx", 0) or 0),
            active_idx=active_idx_raw,  # type: ignore[arg-type]
            rng_seed=int(data.get("rng_seed", 0) or 0),
            rng_state=data.get("rng_state"),
            status=str(data.get("status", "active") or "active"),
            winner_uid=str(data.get("winner_uid", "") or ""),
            end_reason=str(data.get("end_reason", "") or ""),
            log=[str(x) for x in log_raw],
            created_at=int(data.get("created_at", 0) or 0),
            updated_at=int(data.get("updated_at", 0) or 0),
            finished_at=int(data.get("finished_at", 0) or 0),
        )