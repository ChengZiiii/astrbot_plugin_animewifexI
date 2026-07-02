"""老婆元数据 dataclass（全局，按 wid 索引）。

对应 ``data/wives_master.json`` 的单条记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from .enums import Rarity

__all__ = ["WifeMeta", "BaseStats"]


@dataclass
class BaseStats:
    """老婆基础战力（PK 用）"""

    atk: int = 0
    defense: int = 0  # 避免与内置 def 关键字混淆
    hp: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {"atk": self.atk, "def": self.defense, "hp": self.hp}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaseStats":
        return cls(
            atk=int(data.get("atk", 0) or 0),
            defense=int(data.get("def", 0) or 0),
            hp=int(data.get("hp", 0) or 0),
        )

    def power(self) -> int:
        """基础战力总和"""
        return self.atk + self.defense + self.hp


@dataclass
class WifeMeta:
    """老婆全局元数据：图片、来源、稀有度、基础战力等

    ``wid`` 为稳定 ID（推荐 ``w_<6位hex>`` 形式，见 :func:`app.utils.image` 相关工具）。
    """

    wid: str
    img: str
    source: str = ""
    chara: str = ""
    rarity: str = Rarity.N
    base_stats: BaseStats = field(default_factory=BaseStats)
    birthday: str = ""           # MM-DD，可空
    first_seen: int = 0          # 首次被抽到的 Unix 时间戳

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wid": self.wid,
            "img": self.img,
            "source": self.source,
            "chara": self.chara,
            "rarity": self.rarity,
            "base_stats": self.base_stats.to_dict(),
            "birthday": self.birthday,
            "first_seen": self.first_seen,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WifeMeta":
        stats_raw = data.get("base_stats") or {}
        return cls(
            wid=str(data.get("wid", "")),
            img=str(data.get("img", "")),
            source=str(data.get("source", "")),
            chara=str(data.get("chara", "")),
            rarity=str(data.get("rarity", Rarity.N) or Rarity.N),
            base_stats=BaseStats.from_dict(stats_raw if isinstance(stats_raw, Mapping) else {}),
            birthday=str(data.get("birthday", "") or ""),
            first_seen=int(data.get("first_seen", 0) or 0),
        )
