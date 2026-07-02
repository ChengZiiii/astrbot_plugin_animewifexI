"""旧数据归档（Q6 = 清空重来，不做语义迁移）。

启动时检测 v2.x 数据文件（``config/records.json``、``config/{gid}.json``、
``config/swap_requests.json``、``config/ntr_status.json``），存在则整体移动到
``data/archive_v1/<timestamp>/``，并写入 ``MIGRATED.md`` 记录清单。

设计要点：

* 只移动文件，不解析、不转换；老用户首次启动时按新结构空数据起步；
* 归档操作幂等：已归档过的目录不会再次触发（``config/`` 不存在则跳过）；
* 移动失败时记录日志但不抛异常，让插件仍能继续加载（以空数据起步）；
* 首次启动老用户补偿：调用方可在归档后给已知老用户发放 ``initial_coins``，
  本模块只负责归档，不负责补偿逻辑（由 ``WifePlugin.__init__`` 决策）。
"""

from __future__ import annotations

import os
import shutil
import time
from typing import List, Optional, Tuple

try:
    from astrbot.api import logger as _logger
    _info = _logger.info
    _error = _logger.error
except Exception:  # pragma: no cover
    import logging
    _log = logging.getLogger("astrbot_plugin_animewifex")
    _info = _log.info
    _error = _log.error

from .paths import Paths

__all__ = ["archive_legacy_data", "has_legacy_data", "list_legacy_files"]


def has_legacy_data(paths: Paths) -> bool:
    """检测是否存在 v2.x 旧数据

    满足以下任一即视为存在：
    * ``config/records.json`` 存在
    * ``config/swap_requests.json`` 存在
    * ``config/ntr_status.json`` 存在
    * ``config/`` 下存在任意 ``{gid}.json``（群配置）

    ``wife_list_cache.txt`` 与图库图片不计入判定（缓存/资源非业务数据）。
    """
    cfg_dir = paths.legacy_config_dir
    if not os.path.isdir(cfg_dir):
        return False
    for marker in (
        paths.legacy_records_file,
        paths.legacy_swap_requests_file,
        paths.legacy_ntr_status_file,
    ):
        if os.path.exists(marker):
            return True
    # 检查 {gid}.json 群配置
    for entry in os.listdir(cfg_dir):
        if entry.endswith(".json") and entry not in (
            "records.json",
            "swap_requests.json",
            "ntr_status.json",
        ):
            return True
    return False


def list_legacy_files(paths: Paths) -> List[str]:
    """列出 ``config/`` 下所有需要归档的文件绝对路径"""
    cfg_dir = paths.legacy_config_dir
    if not os.path.isdir(cfg_dir):
        return []
    result: List[str] = []
    for entry in os.listdir(cfg_dir):
        # 归档所有 .json 与 wife_list_cache.txt（缓存一并搬走，避免误读）
        if entry.endswith(".json") or entry == "wife_list_cache.txt":
            result.append(os.path.join(cfg_dir, entry))
    return result


def archive_legacy_data(paths: Paths) -> Optional[str]:
    """将 v2.x 数据整体归档到 ``data/archive_v1/<timestamp>/``

    返回归档目录路径；不存在旧数据时返回 ``None``。
    """
    if not has_legacy_data(paths):
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    archive_subdir = os.path.join(paths.archive_dir, timestamp)
    os.makedirs(archive_subdir, exist_ok=True)

    files = list_legacy_files(paths)
    moved: List[str] = []
    for src in files:
        dst = os.path.join(archive_subdir, os.path.basename(src))
        try:
            shutil.move(src, dst)
            moved.append(os.path.basename(src))
        except Exception:
            _error(f"归档旧数据失败: {src}")

    # 写入迁移说明
    readme_path = os.path.join(archive_subdir, "MIGRATED.md")
    try:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(_render_migrated_md(timestamp, moved))
    except Exception:
        _error(f"写入 MIGRATED.md 失败: {readme_path}")

    # config/ 目录若已空，删除以保持整洁（删除失败忽略）
    try:
        if os.path.isdir(paths.legacy_config_dir):
            remaining = os.listdir(paths.legacy_config_dir)
            if not remaining:
                os.rmdir(paths.legacy_config_dir)
    except OSError:
        pass

    _info(f"已归档 v2.x 旧数据到 {archive_subdir}（共 {len(moved)} 个文件）")
    return archive_subdir


def _render_migrated_md(timestamp: str, files: List[str]) -> str:
    """生成 ``MIGRATED.md`` 内容"""
    file_list = "\n".join(f"- `{name}`" for name in files) or "- (无文件)"
    return f"""# v2.x → v3.x 数据归档

归档时间：**{timestamp}**

## 归档文件清单

{file_list}

## 说明

按 ROADMAP.md §一 Q6 决策（清空重来，不做语义迁移），v2.x 数据不再被 v3.x 加载，
启动时统一归档到此处保留 90 天（见 §7.2 回滚策略），用户首次启动后按新结构空数据起步。

老用户补偿：可在 WebUI 配置 ``initial_coins``，老用户重新发消息时会自动创建新档案
并发放初始老婆币（由 ``ProfileStore.get_or_create`` 触发，无需手动操作）。
"""
