import asyncio
import json
import os
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp

from astrbot.api import logger, AstrBotConfig
from astrbot.api.star import Star, Context, StarTools
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import EventMessageType
from astrbot.api.message_components import At, Plain, Image

# IANA 时区数据由 requirements.txt 声明的 tzdata 保证
DEFAULT_TIMEZONE = "Asia/Shanghai"

# ==================== 通用工具函数 ====================


def get_today(tz: ZoneInfo) -> str:
    """获取指定时区的当前日期字符串"""
    return datetime.now(tz).date().isoformat()


def seconds_until_next_midnight(tz: ZoneInfo) -> float:
    """距指定时区下一个零点的秒数"""
    now = datetime.now(tz)
    next_midnight = datetime.combine(
        (now + timedelta(days=1)).date(), datetime.min.time(), tzinfo=tz
    )
    return (next_midnight - now).total_seconds()


def load_json(path: str) -> dict:
    """安全加载 JSON 文件"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error(f"JSON 文件解析失败，可能已损坏，将以空数据载入: {path}")
        return {}
    except OSError:
        logger.error(f"读取 JSON 文件失败，将以空数据载入: {path}")
        return {}
    if not isinstance(data, dict):
        logger.error(f"JSON 文件顶层不是字典，可能被外部修改，将以空数据载入: {path}")
        return {}
    return data


def save_json(path: str, data: dict) -> None:
    """原子方式保存 JSON 文件：先写临时文件再替换，避免写入中断导致文件损坏

    注意：函数内不能引入 await 点，全程同步执行才能保证
    不同群锁下的并发协程不会交错写同一文件。
    """
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        logger.exception(f"保存 JSON 文件失败: {path}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def sanitize_group_records(data, desc: str) -> dict:
    """校验 {群: {用户: 记录字典}} 两层嵌套结构，被外部改坏的非法条目记 error 后丢弃

    load_json 只保证顶层是字典；内层结构损坏若不在加载时过滤，
    会在启动清理或命令处理中抛 AttributeError 导致插件加载失败。
    """
    if data is None:
        return {}
    if not isinstance(data, dict):
        logger.error(f"{desc} 不是字典，可能被外部修改，已丢弃")
        return {}
    cleaned = {}
    for gid, grp in data.items():
        if not isinstance(grp, dict):
            logger.error(f"{desc} 中群 {gid} 的数据不是字典，可能被外部修改，已丢弃")
            continue
        for uid, rec in grp.items():
            if not isinstance(rec, dict):
                logger.error(
                    f"{desc} 中群 {gid} 用户 {uid} 的记录不是字典，可能被外部修改，已丢弃"
                )
        cleaned[gid] = {uid: rec for uid, rec in grp.items() if isinstance(rec, dict)}
    return cleaned


def migrate_wife_data(data) -> dict | None:
    """老婆数据统一为 {"img", "date", "owner"} 字典；旧版位置列表自动迁移，无法识别返回 None"""
    if isinstance(data, dict) and "img" in data:
        return data
    if isinstance(data, list) and len(data) >= 3:
        return {"img": data[0], "date": data[1], "owner": data[2]}
    return None


def has_today_wife(cfg: dict, uid: str, today: str) -> bool:
    """判断用户在群配置中是否拥有今天的老婆"""
    wife = cfg.get(uid)
    return isinstance(wife, dict) and wife.get("date") == today


# ==================== 主插件类 ====================


class WifePlugin(Star):
    """二次元老婆插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._init_config()
        self._init_commands()
        self._init_storage()
        coro = self._daily_cleanup_loop()
        try:
            self._daily_cleanup_task = asyncio.create_task(coro)
        except RuntimeError:
            # 无运行中的事件循环时关闭协程，避免 "coroutine never awaited" 告警
            coro.close()
            self._daily_cleanup_task = None

    def _init_config(self):
        """初始化配置参数（带默认值兜底，避免配置缺项导致加载失败）"""
        self.tz = self._resolve_timezone()
        self.admins = self.config.get("admins", [])
        self.need_prefix = self.config.get("need_prefix", False)
        self.ntr_max = self.config.get("ntr_max", 3)
        self.ntr_possibility = self.config.get("ntr_possibility", 0.20)
        self.change_max_per_day = self.config.get("change_max_per_day", 3)
        self.swap_max_per_day = self.config.get("swap_max_per_day", 2)
        self.reset_max_uses_per_day = self.config.get("reset_max_uses_per_day", 3)
        self.reset_success_rate = self.config.get("reset_success_rate", 0.30)
        self.reset_mute_duration = self.config.get("reset_mute_duration", 300)
        base_url = (
            self.config.get("image_base_url")
            or "https://cdn.jsdmirror.com/gh/monbed/wife@main"
        )
        self.image_base_url = base_url.rstrip("/") + "/"
        self.image_list_url = (
            self.config.get("image_list_url") or "https://animewife.dpdns.org/list.txt"
        )

    def _resolve_timezone(self) -> ZoneInfo:
        """读取 AstrBot 全局时区配置（WebUI 系统设置 timezone），缺失或无效时回退默认值"""
        tz_name = self.context.get_config().get("timezone")
        if not tz_name:
            return ZoneInfo(DEFAULT_TIMEZONE)
        try:
            return ZoneInfo(str(tz_name))
        except Exception:
            logger.error(
                f"AstrBot 全局时区配置无效: {tz_name!r}，已回退 {DEFAULT_TIMEZONE}"
            )
            return ZoneInfo(DEFAULT_TIMEZONE)

    def _init_commands(self):
        """初始化命令映射表"""
        self.commands = {
            "老婆帮助": self.wife_help,
            "抽老婆": self.animewife,
            "查老婆": self.search_wife,
            "牛老婆": self.ntr_wife,
            "重置牛": self.reset_ntr,
            "切换ntr开关状态": self.switch_ntr,
            "切换NTR开关状态": self.switch_ntr,
            "换老婆": self.change_wife,
            "重置换": self.reset_change_wife,
            "交换老婆": self.swap_wife,
            "同意交换": self.agree_swap_wife,
            "拒绝交换": self.reject_swap_wife,
            "查看交换请求": self.view_swap_requests,
        }
        # 按命令名长度降序排列，匹配时避免较短的命令意外截胡更长的命令
        self._command_names = sorted(self.commands, key=len, reverse=True)

    def _init_storage(self):
        """初始化数据目录并加载持久化数据"""
        plugin_dir = StarTools.get_data_dir("astrbot_plugin_animewifex")
        self.config_dir = os.path.join(plugin_dir, "config")
        self.img_dir = os.path.join(plugin_dir, "img", "wife")
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.img_dir, exist_ok=True)

        self.records_file = os.path.join(self.config_dir, "records.json")
        self.swap_requests_file = os.path.join(self.config_dir, "swap_requests.json")
        self.ntr_status_file = os.path.join(self.config_dir, "ntr_status.json")
        self.wife_list_cache_file = os.path.join(self.config_dir, "wife_list_cache.txt")

        # 群组级状态锁：保护该群的配置、各类次数记录与交换请求
        self.group_locks = {}

        raw = load_json(self.records_file)
        # ntr=牛老婆次数 change=换老婆次数 reset=重置机会次数 swap=交换请求次数
        self.records = {
            key: sanitize_group_records(raw.get(key), f"records.json[{key}]")
            for key in ("ntr", "change", "reset", "swap")
        }
        # 启动阶段尚无并发，清理无需加锁；校验丢弃过非法条目时同样需要落盘
        today = get_today(self.tz)
        changed = any(self.records[key] != raw.get(key, {}) for key in self.records)
        for gid in {gid for recs in self.records.values() for gid in recs}:
            changed |= self._prune_group_records(gid, today)
        if changed:
            self.save_records()
        self.swap_requests = self._load_swap_requests()
        self.ntr_statuses = load_json(self.ntr_status_file)

    # ==================== 并发与持久化 ====================

    def get_group_lock(self, group_id: str) -> asyncio.Lock:
        """获取或创建群组级状态锁"""
        if group_id not in self.group_locks:
            self.group_locks[group_id] = asyncio.Lock()
        return self.group_locks[group_id]

    def save_records(self):
        save_json(self.records_file, self.records)

    def _prune_group_records(self, gid: str, today: str) -> bool:
        """删除某群各类别中日期不是今天的次数记录，群内清空后移除该群条目，返回是否有变动

        处理协程可能在群锁内持有群记录字典的引用跨越 await 点，
        运行期调用必须先持有该群的锁，避免删除群条目后协程写入悬空字典。
        """
        changed = False
        for recs in self.records.values():
            grp = recs.get(gid)
            if grp is None:
                continue
            stale = [uid for uid, rec in grp.items() if rec.get("date") != today]
            for uid in stale:
                del grp[uid]
            if stale or not grp:
                changed = True
            if not grp:
                del recs[gid]
        return changed

    def _load_swap_requests(self) -> dict:
        """加载交换请求，过滤结构非法的条目并清理过期数据"""
        raw = load_json(self.swap_requests_file)
        sanitized = sanitize_group_records(raw, "swap_requests.json")
        today = get_today(self.tz)
        cleaned = {}
        for gid, reqs in sanitized.items():
            valid = {uid: rec for uid, rec in reqs.items() if rec.get("date") == today}
            if valid:
                cleaned[gid] = valid
        if raw != cleaned:
            save_json(self.swap_requests_file, cleaned)
        return cleaned

    def save_swap_requests(self):
        save_json(self.swap_requests_file, self.swap_requests)

    def save_ntr_statuses(self):
        save_json(self.ntr_status_file, self.ntr_statuses)

    def load_group_config(self, group_id: str) -> dict:
        """加载群组配置，旧版列表格式的老婆数据自动迁移为字典，无法识别的条目丢弃"""
        raw = load_json(os.path.join(self.config_dir, f"{group_id}.json"))
        cfg = {}
        for uid, data in raw.items():
            wife = migrate_wife_data(data)
            if wife is not None:
                cfg[uid] = wife
        return cfg

    def save_group_config(self, group_id: str, cfg: dict):
        save_json(os.path.join(self.config_dir, f"{group_id}.json"), cfg)

    # ==================== 目标解析 ====================

    def parse_at_target(self, event: AstrMessageEvent) -> str | None:
        """解析消息中的@目标用户

        跳过所有指向机器人自身的 At，返回第一个有效的目标用户 QQ 号；未找到时返回 None
        """
        if not event.message_obj or not hasattr(event.message_obj, "message"):
            return None
        self_id = str(event.get_self_id())
        for comp in event.message_obj.message:
            if isinstance(comp, At) and str(comp.qq) != self_id:
                return str(comp.qq)
        return None

    def parse_target(self, event: AstrMessageEvent) -> str | None:
        """解析命令目标用户"""
        target = self.parse_at_target(event)
        if target:
            return target

        msg = event.message_str.strip()
        if msg.startswith("牛老婆") or msg.startswith("查老婆"):
            parts = msg.split(maxsplit=1)
            if len(parts) > 1:
                name = parts[1]
                group_id = str(event.message_obj.group_id)
                cfg = self.load_group_config(group_id)
                for uid, wife in cfg.items():
                    if wife.get("owner") == name:
                        return uid
        return None

    # ==================== 消息处理 ====================

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_all_messages(self, event: AstrMessageEvent):
        """消息分发处理（仅群聊监听）"""
        if not event.message_obj or not hasattr(event.message_obj, "group_id"):
            return

        if self.need_prefix and not event.is_at_or_wake_command:
            return

        text = event.message_str.strip()
        for cmd in self._command_names:
            if text.startswith(cmd):
                async for res in self.commands[cmd](event):
                    yield res
                break

    # ==================== 抽老婆与查询 ====================

    async def animewife(self, event: AstrMessageEvent):
        """抽老婆"""
        gid = str(event.message_obj.group_id)
        uid = str(event.get_sender_id())
        nick = event.get_sender_name()
        today = get_today(self.tz)

        async with self.get_group_lock(gid):
            cfg = self.load_group_config(gid)

            if not has_today_wife(cfg, uid, today):
                img = await self._fetch_wife_image()
                if img:
                    cfg[uid] = {"img": img, "date": today, "owner": nick}
                    self.save_group_config(gid, cfg)
            else:
                img = cfg[uid]["img"]

        if not img:
            yield event.plain_result("抱歉，今天的老婆获取失败了，请稍后再试~")
            return
        yield event.chain_result(self._build_wife_message(img, nick))

    async def search_wife(self, event: AstrMessageEvent):
        """查老婆"""
        gid = str(event.message_obj.group_id)
        tid = self.parse_target(event) or str(event.get_sender_id())
        today = get_today(self.tz)

        cfg = self.load_group_config(gid)

        if not has_today_wife(cfg, tid, today):
            yield event.plain_result("没有发现老婆的踪迹，快去抽一个试试吧~")
            return

        img = cfg[tid]["img"]
        owner = cfg[tid].get("owner", "未知用户")
        chara, source = self._parse_wife_name(img)
        if source:
            text = f"{owner}的老婆是来自《{source}》的{chara}，羡慕吗？"
        else:
            text = f"{owner}的老婆是{chara}，羡慕吗？"
        yield event.chain_result(self._build_chain(text, img))

    async def _fetch_wife_image(self) -> str | None:
        """获取老婆图片，依次尝试：本地图库 → 有效缓存 → 网络列表 → 过期缓存兜底"""
        try:
            with os.scandir(self.img_dir) as entries:
                local_imgs = [e.name for e in entries if e.is_file()]
            if local_imgs:
                return random.choice(local_imgs)
        except OSError:
            pass

        cached_lines = []
        cache_expired = True
        if os.path.exists(self.wife_list_cache_file):
            try:
                cache_expired = (
                    time.time() - os.path.getmtime(self.wife_list_cache_file)
                ) >= 3600
                with open(self.wife_list_cache_file, "r", encoding="utf-8") as f:
                    cached_lines = [
                        s for s in (line.strip() for line in f.read().splitlines()) if s
                    ]
            except (OSError, UnicodeDecodeError):
                pass

        if not cache_expired and cached_lines:
            return random.choice(cached_lines)

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.image_list_url) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        lines = [
                            s for s in (line.strip() for line in text.splitlines()) if s
                        ]
                        if lines:
                            # 缓存写入失败不影响本次结果
                            try:
                                with open(
                                    self.wife_list_cache_file, "w", encoding="utf-8"
                                ) as f:
                                    f.write("\n".join(lines))
                            except OSError:
                                pass
                            return random.choice(lines)
        except Exception:
            pass

        if cached_lines:
            return random.choice(cached_lines)

        return None

    def _parse_wife_name(self, img: str) -> tuple[str, str | None]:
        """从图片标识解析出 (角色名, 作品来源)，无来源时来源为 None"""
        name = os.path.splitext(img)[0].split("/")[-1]
        if "!" in name:
            source, chara = name.split("!", 1)
            return chara, source
        return name, None

    def _build_image_component(self, img: str):
        """根据图片标识构建图片消息组件（本地优先，回退到 URL），失败返回 None"""
        try:
            # 图片标识来自远程列表，本地读取前校验路径未逃逸出图库目录
            base = os.path.abspath(self.img_dir)
            path = os.path.abspath(os.path.join(base, img))
            if os.path.commonpath([base, path]) == base and os.path.exists(path):
                return Image.fromFileSystem(path)
            return Image.fromURL(self.image_base_url + img)
        except Exception:
            return None

    def _build_chain(self, text: str, img: str) -> list:
        """构建「文字 + 图片」消息链，图片组件构建失败时仅保留文字"""
        chain = [Plain(text)]
        img_comp = self._build_image_component(img)
        if img_comp is not None:
            chain.append(img_comp)
        return chain

    def _build_wife_message(self, img: str, nick: str) -> list:
        """构建「你今天的老婆是…」消息链"""
        chara, source = self._parse_wife_name(img)
        if source:
            text = f"{nick}，你今天的老婆是来自《{source}》的{chara}，请好好珍惜哦~"
        else:
            text = f"{nick}，你今天的老婆是{chara}，请好好珍惜哦~"
        return self._build_chain(text, img)

    # ==================== 帮助命令 ====================

    async def wife_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """
【基础命令】
• 抽老婆 - 每天抽取一个二次元老婆
• 查老婆 [@用户] - 查看别人的老婆

【牛老婆功能】(概率较低😭)
• 牛老婆 [@用户] - 有概率抢走别人的老婆
• 重置牛 [@用户] - 重置牛的次数(失败会禁言)

【换老婆功能】
• 换老婆 - 丢弃当前老婆换新的
• 重置换 [@用户] - 重置换老婆的次数(失败会禁言)

【交换功能】
• 交换老婆 [@用户] - 向别人发起老婆交换请求
• 同意交换 [@发起者] - 同意交换请求
• 拒绝交换 [@发起者] - 拒绝交换请求
• 查看交换请求 - 查看当前的交换请求

【管理员命令】
• 切换ntr开关状态 - 开启/关闭NTR功能

💡 提示：部分命令有每日使用次数限制
"""
        yield event.plain_result(help_text.strip())

    # ==================== 牛老婆相关 ====================

    async def ntr_wife(self, event: AstrMessageEvent):
        """牛老婆"""
        gid = str(event.message_obj.group_id)
        uid = str(event.get_sender_id())
        nick = event.get_sender_name()
        today = get_today(self.tz)

        tid = self.parse_target(event)

        # 锁内只收集回复、出锁后统一发送，避免持锁等待消息发送
        replies = []
        async with self.get_group_lock(gid):
            grp = self.records["ntr"].setdefault(gid, {})
            rec = grp.get(uid, {"date": today, "count": 0})
            if rec["date"] != today:
                rec = {"date": today, "count": 0}

            cfg = self.load_group_config(gid)
            if not self.ntr_statuses.get(gid, True):
                replies.append(
                    event.plain_result("牛老婆功能还没开启哦，请联系管理员开启~")
                )
            elif not tid or tid == uid:
                msg = (
                    "请@你想牛的对象，或输入完整的昵称哦~"
                    if not tid
                    else "不能牛自己呀，换个人试试吧~"
                )
                replies.append(event.plain_result(f"{nick}，{msg}"))
            elif rec["count"] >= self.ntr_max:
                replies.append(
                    event.plain_result(
                        f"{nick}，你今天已经牛了{self.ntr_max}次啦，明天再来吧~"
                    )
                )
            elif not has_today_wife(cfg, tid, today):
                replies.append(event.plain_result("对方今天还没有老婆可牛哦~"))
            else:
                rec["count"] += 1
                grp[uid] = rec
                self.save_records()

                if random.random() < self.ntr_possibility:
                    img = cfg[tid]["img"]
                    cfg[uid] = {"img": img, "date": today, "owner": nick}
                    del cfg[tid]
                    self.save_group_config(gid, cfg)
                    cancel_msg = self.cancel_swap_on_wife_change(gid, [uid, tid])

                    replies.append(
                        event.plain_result(
                            f"{nick}，牛老婆成功！老婆已归你所有，恭喜恭喜~"
                        )
                    )
                    if cancel_msg:
                        replies.append(event.plain_result(cancel_msg))
                    replies.append(
                        event.chain_result(self._build_wife_message(img, nick))
                    )
                else:
                    remaining = self.ntr_max - rec["count"]
                    replies.append(
                        event.plain_result(
                            f"{nick}，很遗憾，牛失败了！你今天还可以再试{remaining}次~"
                        )
                    )

        for reply in replies:
            yield reply

    async def switch_ntr(self, event: AstrMessageEvent):
        """切换 NTR 开关（仅管理员）"""
        uid = str(event.get_sender_id())
        nick = event.get_sender_name()

        if uid not in self.admins:
            yield event.plain_result(f"{nick}，你没有权限操作哦~")
            return

        gid = str(event.message_obj.group_id)
        async with self.get_group_lock(gid):
            new_status = not self.ntr_statuses.get(gid, True)
            self.ntr_statuses[gid] = new_status
            self.save_ntr_statuses()

        state = "开启" if new_status else "关闭"
        yield event.plain_result(f"{nick}，NTR已{state}")

    # ==================== 换老婆相关 ====================

    async def change_wife(self, event: AstrMessageEvent):
        """换老婆"""
        gid = str(event.message_obj.group_id)
        uid = str(event.get_sender_id())
        nick = event.get_sender_name()
        today = get_today(self.tz)

        replies = []
        # 次数检查、自增与更换老婆在同一临界区内完成，避免并发绕过每日上限
        async with self.get_group_lock(gid):
            recs = self.records["change"].setdefault(gid, {})
            rec = recs.get(uid, {"date": "", "count": 0})

            cfg = self.load_group_config(gid)
            if rec["date"] == today and rec["count"] >= self.change_max_per_day:
                replies.append(
                    event.plain_result(
                        f"{nick}，你今天已经换了{self.change_max_per_day}次老婆啦，明天再来吧~"
                    )
                )
            elif not has_today_wife(cfg, uid, today):
                replies.append(
                    event.plain_result(f"{nick}，你今天还没有老婆，先去抽一个再来换吧~")
                )
            else:
                # 先抽到新老婆再替换；抽取失败时老婆和次数都保持不动
                img = await self._fetch_wife_image()
                if not img:
                    replies.append(
                        event.plain_result(
                            "抱歉，新老婆获取失败了，本次更换未生效，请稍后再试~"
                        )
                    )
                else:
                    cfg[uid] = {"img": img, "date": today, "owner": nick}
                    self.save_group_config(gid, cfg)

                    if rec["date"] != today:
                        rec = {"date": today, "count": 1}
                    else:
                        rec["count"] += 1
                    recs[uid] = rec
                    self.save_records()

                    cancel_msg = self.cancel_swap_on_wife_change(gid, [uid])
                    if cancel_msg:
                        replies.append(event.plain_result(cancel_msg))
                    replies.append(
                        event.chain_result(self._build_wife_message(img, nick))
                    )

        for reply in replies:
            yield reply

    # ==================== 重置相关 ====================

    async def _do_reset(
        self, event: AstrMessageEvent, category: str, label: str, short: str
    ):
        """通用重置逻辑

        category: records 中要被重置的类别键（"ntr" / "change"）
        label:    消息中的完整名称（如 "牛老婆"）
        short:    失败提示中的简称（如 "牛"）
        """
        gid = str(event.message_obj.group_id)
        uid = str(event.get_sender_id())
        nick = event.get_sender_name()
        today = get_today(self.tz)
        tid = self.parse_at_target(event) or uid

        if uid in self.admins:
            async with self.get_group_lock(gid):
                grp = self.records[category].setdefault(gid, {})
                if tid in grp:
                    del grp[tid]
                    self.save_records()
            yield event.chain_result(
                [Plain("管理员操作：已重置"), At(qq=tid), Plain(f"的{label}次数。")]
            )
            return

        # 限额检查与自增在同一临界区内完成
        replies = []
        do_ban = False
        async with self.get_group_lock(gid):
            grp_reset = self.records["reset"].setdefault(gid, {})
            rec = grp_reset.get(uid, {"date": today, "count": 0})
            if rec.get("date") != today:
                rec = {"date": today, "count": 0}

            if rec["count"] >= self.reset_max_uses_per_day:
                replies.append(
                    event.plain_result(
                        f"{nick}，你今天已经用完{self.reset_max_uses_per_day}次重置机会啦，明天再来吧~"
                    )
                )
            else:
                rec["count"] += 1
                grp_reset[uid] = rec

                if random.random() < self.reset_success_rate:
                    self.records[category].setdefault(gid, {}).pop(tid, None)
                    replies.append(
                        event.chain_result(
                            [Plain("已重置"), At(qq=tid), Plain(f"的{label}次数。")]
                        )
                    )
                else:
                    do_ban = True
                    replies.append(
                        event.plain_result(
                            f"{nick}，重置{short}失败，被禁言{self.reset_mute_duration}秒，下次记得再接再厉哦~"
                        )
                    )

                # 自增与可能的删除合并为一次落盘
                self.save_records()

        if do_ban:
            try:
                await event.bot.set_group_ban(
                    group_id=int(gid),
                    user_id=int(uid),
                    duration=self.reset_mute_duration,
                )
            except Exception:
                pass

        for reply in replies:
            yield reply

    async def reset_ntr(self, event: AstrMessageEvent):
        """重置牛老婆次数"""
        async for res in self._do_reset(event, "ntr", "牛老婆", "牛"):
            yield res

    async def reset_change_wife(self, event: AstrMessageEvent):
        """重置换老婆次数"""
        async for res in self._do_reset(event, "change", "换老婆", "换"):
            yield res

    # ==================== 交换老婆相关 ====================

    async def swap_wife(self, event: AstrMessageEvent):
        """发起交换老婆请求"""
        gid = str(event.message_obj.group_id)
        uid = str(event.get_sender_id())
        tid = self.parse_at_target(event)
        nick = event.get_sender_name()
        today = get_today(self.tz)

        replies = []
        # 次数检查、自增与请求记录在同一临界区内完成
        async with self.get_group_lock(gid):
            grp_limit = self.records["swap"].setdefault(gid, {})
            rec_lim = grp_limit.get(uid, {"date": "", "count": 0})
            if rec_lim["date"] != today:
                rec_lim = {"date": today, "count": 0}

            # 已有待处理请求时重复发起视为更换目标：旧请求取消、今天消耗的次数返还，
            # 因此限额按返还后的值校验，保证换目标不被当日上限挡住
            old_req = self.swap_requests.get(gid, {}).get(uid)
            refundable = (
                1
                if old_req and old_req.get("date") == today and rec_lim["count"] > 0
                else 0
            )

            if rec_lim["count"] - refundable >= self.swap_max_per_day:
                replies.append(
                    event.plain_result(
                        f"{nick}，你今天已经发起了{self.swap_max_per_day}次交换请求啦，明天再来吧~"
                    )
                )
            elif not tid or tid == uid:
                # 次数未用完，再校验是否@了交换对象（保持原版校验顺序）
                replies.append(
                    event.plain_result(f"{nick}，请在命令后@你想交换的对象哦~")
                )
            else:
                cfg = self.load_group_config(gid)
                no_wife_who = None
                for x in (uid, tid):
                    if not has_today_wife(cfg, x, today):
                        no_wife_who = nick if x == uid else "对方"
                        break

                if no_wife_who:
                    replies.append(
                        event.plain_result(
                            f"{no_wife_who}，今天还没有老婆，无法进行交换哦~"
                        )
                    )
                else:
                    cancel_note = None
                    if old_req is not None:
                        rec_lim["count"] -= refundable
                        cancel_note = (
                            "已自动取消你之前发起的交换请求并返还次数~"
                            if refundable
                            else "已自动取消你之前发起的交换请求~"
                        )

                    rec_lim["count"] += 1
                    grp_limit[uid] = rec_lim
                    self.save_records()

                    self.swap_requests.setdefault(gid, {})[uid] = {
                        "target": tid,
                        "date": today,
                    }
                    self.save_swap_requests()

                    if cancel_note:
                        replies.append(event.plain_result(cancel_note))
                    replies.append(
                        event.chain_result(
                            [
                                Plain(f"{nick} 想和 "),
                                At(qq=tid),
                                Plain(
                                    ' 交换老婆啦！请对方用"同意交换 @发起者"或"拒绝交换 @发起者"来回应~'
                                ),
                            ]
                        )
                    )

        for reply in replies:
            yield reply

    async def agree_swap_wife(self, event: AstrMessageEvent):
        """同意交换老婆"""
        gid = str(event.message_obj.group_id)
        tid = str(event.get_sender_id())
        uid = self.parse_at_target(event)
        nick = event.get_sender_name()
        today = get_today(self.tz)

        replies = []
        async with self.get_group_lock(gid):
            grp = self.swap_requests.get(gid, {})
            rec = grp.get(uid)

            if rec and rec.get("date") != today:
                # 跨天后的陈旧请求视为已过期（定时清理在每日零点执行，此处兜底）
                del grp[uid]
                self.save_swap_requests()
                replies.append(
                    event.plain_result("该交换请求已过期，请重新发起交换吧~")
                )
            elif not rec or rec.get("target") != tid:
                replies.append(
                    event.plain_result(
                        f'{nick}，请在命令后@发起者，或用"查看交换请求"命令查看当前请求哦~'
                    )
                )
            else:
                cfg = self.load_group_config(gid)
                # 兜底校验：插件内的老婆变动会同步取消请求，但配置文件被外部修改或损坏时，
                # 请求可能仍指向已不存在的老婆，直接交换会抛 KeyError，这里转为友好失败
                if not has_today_wife(cfg, uid, today) or not has_today_wife(
                    cfg, tid, today
                ):
                    del grp[uid]
                    self.save_swap_requests()
                    replies.append(
                        event.plain_result(
                            "交换失败，有一方的老婆已经发生变化，请重新发起交换吧~"
                        )
                    )
                else:
                    # 仅交换图片标识，各自保留昵称与日期
                    cfg[uid]["img"], cfg[tid]["img"] = cfg[tid]["img"], cfg[uid]["img"]
                    self.save_group_config(gid, cfg)

                    del grp[uid]
                    self.save_swap_requests()

                    cancel_msg = self.cancel_swap_on_wife_change(gid, [uid, tid])

                    replies.append(
                        event.plain_result("交换成功！你们的老婆已经互换啦，祝幸福~")
                    )
                    if cancel_msg:
                        replies.append(event.plain_result(cancel_msg))

        for reply in replies:
            yield reply

    async def reject_swap_wife(self, event: AstrMessageEvent):
        """拒绝交换老婆"""
        gid = str(event.message_obj.group_id)
        tid = str(event.get_sender_id())
        uid = self.parse_at_target(event)
        nick = event.get_sender_name()
        today = get_today(self.tz)

        replies = []
        async with self.get_group_lock(gid):
            grp = self.swap_requests.get(gid, {})
            rec = grp.get(uid)

            if rec and rec.get("date") != today:
                # 跨天后的陈旧请求视为已过期（定时清理在每日零点执行，此处兜底）
                del grp[uid]
                self.save_swap_requests()
                replies.append(event.plain_result("该交换请求已过期，无需拒绝啦~"))
            elif not rec or rec.get("target") != tid:
                replies.append(
                    event.plain_result(
                        f'{nick}，请在命令后@发起者，或用"查看交换请求"命令查看当前请求哦~'
                    )
                )
            else:
                del grp[uid]
                self.save_swap_requests()
                replies.append(
                    event.chain_result(
                        [At(qq=uid), Plain("，对方婉拒了你的交换请求，下次加油吧~")]
                    )
                )

        for reply in replies:
            yield reply

    async def view_swap_requests(self, event: AstrMessageEvent):
        """查看当前交换请求"""
        gid = str(event.message_obj.group_id)
        me = str(event.get_sender_id())
        today = get_today(self.tz)

        grp = {
            uid: rec
            for uid, rec in self.swap_requests.get(gid, {}).items()
            if rec.get("date") == today
        }
        cfg = self.load_group_config(gid)

        my_req = grp.get(me)
        my_target = my_req.get("target") if my_req else None
        sent_targets = [my_target] if my_target else []
        received_from = [uid for uid, rec in grp.items() if rec.get("target") == me]

        if not sent_targets and not received_from:
            yield event.plain_result("你当前没有任何交换请求哦~")
            return

        parts = []
        for tid in sent_targets:
            name = (cfg.get(tid) or {}).get("owner", "未知用户")
            parts.append(f"→ 你发起给 {name} 的交换请求")

        for uid in received_from:
            name = (cfg.get(uid) or {}).get("owner", "未知用户")
            parts.append(f"→ {name} 发起给你的交换请求")

        text = (
            "当前交换请求如下：\n"
            + "\n".join(parts)
            + '\n请在"同意交换"或"拒绝交换"命令后@发起者进行操作~'
        )
        yield event.plain_result(text)

    def cancel_swap_on_wife_change(self, gid: str, user_ids: list) -> str | None:
        """老婆发生变动时，取消相关的交换请求并返还发起次数（需在群锁内调用）"""
        today = get_today(self.tz)
        grp = self.swap_requests.get(gid, {})
        grp_limit = self.records["swap"].setdefault(gid, {})

        # 只取消今天的活请求；昨日的死请求交给过期机制（兜底提示 + 零点清理），
        # 避免零点后清理前的窗口期把已过期请求误报为"因老婆变动取消"
        to_cancel = [
            req_uid
            for req_uid, req in grp.items()
            if req.get("date") == today
            and (req_uid in user_ids or req.get("target") in user_ids)
        ]

        if not to_cancel:
            return None

        for req_uid in to_cancel:
            rec_lim = grp_limit.get(req_uid, {"date": "", "count": 0})
            if rec_lim.get("date") == today and rec_lim.get("count", 0) > 0:
                rec_lim["count"] = max(0, rec_lim["count"] - 1)
                grp_limit[req_uid] = rec_lim
            del grp[req_uid]

        self.save_swap_requests()
        self.save_records()

        return f"已自动取消 {len(to_cancel)} 条相关的交换请求并返还次数~"

    # ==================== 定时清理 ====================

    async def _daily_cleanup_loop(self):
        """每天零点清理跨天失效的数据：过期交换请求与历史次数记录"""
        while True:
            try:
                # 多等一分钟，避免时钟误差导致在日期变更前执行
                await asyncio.sleep(seconds_until_next_midnight(self.tz) + 60)
                await self._cleanup_expired_swap_requests()
                await self._cleanup_expired_records()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("定时清理过期数据失败")

    async def _cleanup_expired_swap_requests(self):
        """逐群清理日期不是今天的交换请求"""
        today = get_today(self.tz)
        for gid in list(self.swap_requests.keys()):
            async with self.get_group_lock(gid):
                reqs = self.swap_requests.get(gid, {})
                expired = [uid for uid, rec in reqs.items() if rec.get("date") != today]
                for uid in expired:
                    del reqs[uid]
                if not reqs:
                    self.swap_requests.pop(gid, None)
                if expired:
                    self.save_swap_requests()

    async def _cleanup_expired_records(self):
        """逐群清理历史次数记录（在群锁内执行，避免与处理协程交错）"""
        today = get_today(self.tz)
        changed = False
        for gid in {gid for recs in self.records.values() for gid in recs}:
            async with self.get_group_lock(gid):
                if self._prune_group_records(gid, today):
                    changed = True
        if changed:
            self.save_records()

    async def terminate(self):
        """插件卸载时停止后台任务"""
        task = getattr(self, "_daily_cleanup_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
