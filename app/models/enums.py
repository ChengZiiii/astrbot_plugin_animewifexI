"""枚举：获取来源、稀有度、活动日志动作键。

使用 ``str`` 派生类而非 ``enum.Enum`` 是为了：

* JSON 序列化时直接是原生字符串，无需 ``to_json`` 适配；
* dataclass ``from_dict`` 时无需反向查找；
* 与配置项（如 ``rarity_weights``）直接以字符串 key 对齐。
"""

from __future__ import annotations

__all__ = ["AcquireVia", "Rarity", "Action", "RARITY_ORDER"]


class AcquireVia:
    """所有权获取来源"""

    DRAW = "draw"        # 抽老婆
    NTR = "ntr"          # 牛老婆（所有权转移）
    SWAP = "swap"        # 交换老婆
    GIFT = "gift"        #赠送（预留）
    SUMMON = "summon"    # 召唤（预留）

    ALL = (DRAW, NTR, SWAP, GIFT, SUMMON)


# 稀有度从低到高排序（用于保底判断、图鉴排序）
RARITY_ORDER = ("N", "R", "SR", "SSR")


class Rarity:
    """老婆稀有度代码"""

    N = "N"
    R = "R"
    SR = "SR"
    SSR = "SSR"

    ALL = RARITY_ORDER


class Action:
    """活动日志中的动作 key（与 ``activity[uid][date]`` 的字段一一对应）"""

    NTR_SUCCESS = "ntr_success"
    NTR_LOST = "ntr_lost"
    DRAW = "draw"
    SWAP = "swap"
    PK_WIN = "pk_win"
    PK_LOST = "pk_lost"
    COINS_EARNED = "coins_earned"
    COINS_SPENT = "coins_spent"
    # Phase 4 新增
    CHECKIN = "checkin"
    INTIMACY = "intimacy"
    CHAT = "chat"
    DATE = "date"
    PK_TIE = "pk_tie"
    WORK_START = "work_start"
    WORK_COMPLETE = "work_complete"
    WORK_STOLEN = "work_stolen"
    # Phase 4 第二波预留
    SUPPORT = "support"

    ALL = (
        NTR_SUCCESS,
        NTR_LOST,
        DRAW,
        SWAP,
        PK_WIN,
        PK_LOST,
        COINS_EARNED,
        COINS_SPENT,
        CHECKIN,
        INTIMACY,
        CHAT,
        DATE,
        PK_TIE,
        WORK_START,
        WORK_COMPLETE,
        WORK_STOLEN,
        SUPPORT,
    )
