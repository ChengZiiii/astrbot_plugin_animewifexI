"""JSON 原子读写工具：移植自 v2.x 的 ``load_json``/``save_json``，全程不依赖 astrbot。

并发模型约束（与 v2.x 保持一致）：

* ``save_json`` 全程同步执行（内部不能引入 await 点），保证不同群锁下的并发
  协程不会交错写同一文件；
* 所有写操作必须在群锁 (:mod:`app.storage.locks`) 内调用。

异常策略：错误兜底优先于抛异常。读取失败/格式损坏时记录日志并返回空数据，
让插件能在带病数据下继续运行而不是加载失败。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List

try:  # 容错：本地单测无 astrbot 时退化为标准 logging
    from astrbot.api import logger as _logger
    _error = _logger.error
    _exception = _logger.exception
except Exception:  # pragma: no cover - 仅在脱离 astrbot 时走这条路径
    import logging
    _std_logger = logging.getLogger("astrbot_plugin_animewifex")
    _error = _std_logger.error
    _exception = _std_logger.exception

__all__ = [
    "load_json",
    "save_json",
    "load_list_json",
    "sanitize_group_records",
]


def load_json(path: str, default: Any = None) -> Any:
    """安全加载 JSON 文件

    * 文件不存在 → 返回 ``default if default is not None else {}``
    * 解析失败/编码错误 → 记录日志返回空字典（或 ``default``）
    * 顶层不是 dict → 记录日志返回空字典（或 ``default``）

    ``default`` 仅在文件不存在或解析失败且原本要返回 ``{}`` 时生效；
    若希望 list 类型请使用 :func:`load_list_json`。
    """
    fallback = {} if default is None else default
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _error(f"JSON 文件解析失败，可能已损坏，将以空数据载入: {path}")
        return fallback
    except OSError:
        _error(f"读取 JSON 文件失败，将以空数据载入: {path}")
        return fallback
    return data


def load_list_json(path: str) -> List[Dict[str, Any]]:
    """加载顶层为 list 的 JSON，损坏条目逐项过滤后返回

    用于 ``ownership.json`` 等列表型数据。
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _error(f"JSON 文件解析失败，可能已损坏，将以空数据载入: {path}")
        return []
    except OSError:
        _error(f"读取 JSON 文件失败，将以空数据载入: {path}")
        return []
    if not isinstance(data, list):
        _error(f"JSON 文件顶层不是列表，可能被外部修改，将以空数据载入: {path}")
        return []
    return [item for item in data if isinstance(item, dict)]


def save_json(path: str, data: Any) -> None:
    """原子方式保存 JSON 文件：先写临时文件再替换，避免写入中断导致文件损坏

    注意：函数内不能引入 await 点，全程同步执行才能保证
    不同群锁下的并发协程不会交错写同一文件。
    """
    tmp_path = f"{path}.tmp"
    try:
        # 父目录可能尚未创建（群目录首次写入），保险起见 makedirs
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        _exception(f"保存 JSON 文件失败: {path}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def sanitize_group_records(
    data: Any,
    desc: str,
    item_validator: "Callable[[dict], bool] | None" = None,
) -> Dict[str, Dict[str, dict]]:
    """校验 ``{群: {用户: 记录字典}}`` 两层嵌套结构

    被外部改坏的非法条目记 error 后丢弃。
    ``item_validator`` 可选，返回 ``False`` 的内层记录也会被丢弃。
    """
    if data is None:
        return {}
    if not isinstance(data, dict):
        _error(f"{desc} 不是字典，可能被外部修改，已丢弃")
        return {}
    cleaned: Dict[str, Dict[str, dict]] = {}
    for gid, grp in data.items():
        if not isinstance(grp, dict):
            _error(f"{desc} 中群 {gid} 的数据不是字典，可能被外部修改，已丢弃")
            continue
        group_cleaned = {}
        for uid, rec in grp.items():
            if not isinstance(rec, dict):
                _error(
                    f"{desc} 中群 {gid} 用户 {uid} 的记录不是字典，可能被外部修改，已丢弃"
                )
                continue
            if item_validator is not None and not item_validator(rec):
                _error(
                    f"{desc} 中群 {gid} 用户 {uid} 的记录字段缺失，已丢弃"
                )
                continue
            group_cleaned[uid] = rec
        cleaned[gid] = group_cleaned
    return cleaned
