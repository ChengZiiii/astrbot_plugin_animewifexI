# Astrbot Plugin Animewifex 重构路线图 v1.0

> 本文档是插件从 v2.x（单一所有权模型）重构到 v3.x（多老婆 + 富属性 + 经济系统）的完整执行路线图。
> 后续 AI 开发者严格按 Phase 顺序执行，每个 Phase 完成后打 tag 并跑完整测试。

---

## 一、决策记录（已锁定，不可变）

| # | 决策项 | 选择 | 影响 |
|---|---|---|---|
| Q1 | 老婆持有上限 | 默认值 + 经济扩容 + 用户可配置上限 | 默认 3，道具扩容到 `max_capacity` 上限 |
| Q2 | 老婆唯一性 | 群内全局唯一 | NTR = 所有权转移，保住稀缺性 |
| Q3 | 经济系统 | 完整经济（币 + 商城 + 任务 + 道具） | Phase 3 重点 |
| Q4 | 存储格式 | JSON + 群锁 + 原子写 | 沿用现有并发模型 |
| Q5 | 命令风格 | 双轨兼容 | 旧扁平命令保留 + 新功能 `老婆 xxx` 分组 |
| Q6 | 旧数据 | 清空重来（自动归档） | 启动时旧文件移到 `archive_v1/`，不做语义迁移 |
| Q7 | 重构范围 | 模块化重写 | `app/` 目录分层 |

---

## 二、目标架构

### 2.1 目录结构

```
astrbot_plugin_animewifexI/
├── main.py                     # 仅插件注册（精简）
├── metadata.yaml
├── _conf_schema.json           # 扩展配置 schema
├── README.md / CHANGELOG.md
├── ROADMAP.md                  # 本文档
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── plugin.py               # WifePlugin 主类
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── registry.py         # 双轨命令注册表 + 解析器
│   │   ├── draw.py
│   │   ├── view.py
│   │   ├── ntr.py
│   │   ├── swap.py
│   │   ├── shop.py
│   │   ├── pk.py
│   │   ├── marry.py
│   │   ├── leaderboard.py
│   │   ├── collection.py
│   │   ├── profile.py
│   │   ├── quest.py
│   │   └── admin.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── wife_service.py        # 抽取/查询/图片获取
│   │   ├── ownership_service.py   # 所有权 CRUD、上限校验
│   │   ├── ntr_service.py         # NTR + 复仇
│   │   ├── intimacy_service.py    # 亲密度
│   │   ├── economy_service.py     # 老婆币/余额/交易
│   │   ├── pk_service.py          # PK 战斗
│   │   ├── leaderboard_service.py # 榜单聚合
│   │   ├── cooldown_service.py    # 通用冷却
│   │   ├── rarity_service.py      # 稀有度抽卡
│   │   ├── marry_service.py       # 求婚/锁定
│   │   ├── shop_service.py        # 商城
│   │   └── quest_service.py       # 每日任务
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── json_store.py       # 通用 JSON 原子读写
│   │   ├── stores.py           # 各实体 Store 类
│   │   ├── locks.py            # 群锁
│   │   ├── paths.py            # 路径常量
│   │   └── migrations.py       # 旧数据归档
│   ├── models/
│   │   ├── __init__.py
│   │   ├── wife.py
│   │   ├── ownership.py
│   │   ├── profile.py
│   │   ├── activity.py
│   │   └── enums.py            # AcquireVia / Rarity / Action
│   ├── api/
│   │   ├── __init__.py
│   │   ├── events.py           # AstrMessageEvent 工具
│   │   └── messaging.py        # 消息链构建
│   └── utils/
│       ├── __init__.py
│       ├── time.py
│       ├── image.py
│       ├── random_utils.py
│       └── format.py
├── data/                       # 运行时（不入库）
│   ├── archive_v1/             # 旧版本归档
│   ├── wives_master.json       # 全局老婆元数据
│   └── groups/{gid}/
│       ├── ownership.json
│       ├── profiles.json
│       ├── activity.json
│       ├── swap_requests.json
│       └── ntr_status.json
└── tests/
    ├── __init__.py
    ├── test_storage.py
    ├── test_commands_registry.py
    ├── test_ntr_logic.py
    ├── test_leaderboard.py
    ├── test_economy.py
    ├── test_intimacy.py
    └── test_pk.py
```

### 2.2 数据 Schema

#### wives_master.json（全局老婆元数据，按 wid 索引）

```json
{
  "w_a1b2c3": {
    "wid": "w_a1b2c3",
    "img": "进击的巨人!三笠.jpg",
    "source": "进击的巨人",
    "chara": "三笠",
    "rarity": "SSR",
    "base_stats": {"atk": 80, "def": 60, "hp": 100},
    "birthday": "12-25",
    "first_seen": 1720000000
  }
}
```

#### data/groups/{gid}/ownership.json（老婆-用户所有权关系表）

```json
[
  {
    "wid": "w_a1b2c3",
    "uid": "12345",
    "acquired_at": 1720000000,
    "acquired_via": "draw",
    "intimacy": 50,
    "intimacy_updated_date": "2026-07-03",
    "is_locked": false,
    "lock_expires_at": null,
    "is_primary": true
  }
]
```

#### data/groups/{gid}/profiles.json（用户档案）

```json
{
  "12345": {
    "uid": "12345",
    "nick": "张三",
    "coins": 100,
    "capacity": 3,
    "streak_days": 7,
    "last_draw_date": "2026-07-03",
    "last_checkin_date": "2026-07-03",
    "quest_completed_date": "2026-07-03",
    "total_draws": 30,
    "total_ntr_success": 5,
    "total_ntr_lost": 2,
    "total_pk_win": 3,
    "total_pk_lost": 1,
    "collection": ["w_a1b2c3", "w_x9y8z7"],
    "inventory": {"lock_item": 2, "reroll_ticket": 1, "revive_potion": 0, "protection_charm": 0},
    "last_ntr_by": {"uid": "67890", "ts": 1719900000},
    "pity_counter": 0
  }
}
```

#### data/groups/{gid}/activity.json（滚动 N 天活动日志，榜单数据源）

```json
{
  "12345": {
    "2026-07-03": {
      "ntr_success": 2,
      "ntr_lost": 1,
      "draw": 1,
      "swap": 0,
      "pk_win": 1,
      "pk_lost": 0,
      "coins_earned": 50,
      "coins_spent": 30
    }
  }
}
```

#### 内存（不持久化）

- `cooldowns: {gid: {uid: {action: ts}}}`

### 2.3 命令双轨设计

**旧扁平命令**（语义保留，底层重写）：

```
抽老婆 / 查老婆 [@x] / 牛老婆 [@x] / 换老婆
重置牛 [@x] / 重置换 [@x]
交换老婆 [@x] / 同意交换 [@x] / 拒绝交换 [@x] / 查看交换请求
切换ntr开关状态 / 老婆帮助
```

**新分组命令**（`老婆 xxx`）：

```
老婆 列表                       # 查看持有的所有老婆
老婆 查 <编号|@x>              # 查看具体老婆详情
老婆 切换 <编号>               # 设置主老婆
老婆 摸头 <编号>               # 加亲密度（消耗币）
老婆 送礼 <编号>               # 大幅加亲密度（高消耗）
老婆 复仇 @x                   # 24h 内对牛过自己的人复仇
老婆 PK @x                     # 老婆对决
老婆 求婚 <编号>               # 锁定一只老婆
老婆 锁 <编号> / 老婆 解锁 <编号>
老婆 排行 [日|周|总] [牛|被牛|PK|收集]
老婆 图鉴 [作品名]
老婆 面板                      # 个人综合面板
老婆 签到                      # 每日签到领币
老婆 商城 / 老婆 购买 <道具> / 老婆 背包
老婆 任务                      # 查看每日任务
```

### 2.4 配置 schema 完整清单（_conf_schema.json 新增）

```yaml
# ========== 基础（已有，保留） ==========
admins: list                   # 管理员用户 ID 列表
need_prefix: bool              # 启用触发前缀
image_base_url: string         # 图片服务器基础 URL
image_list_url: string         # 图片列表 URL

# ========== 持有上限 ==========
default_capacity: int = 3      # 新用户初始持有上限
max_capacity: int = 10         # 道具扩容绝对上限

# ========== 冷却（秒） ==========
ntr_cooldown: int = 60
draw_cooldown: int = 0
swap_cooldown: int = 30
pk_cooldown: int = 120

# ========== NTR ==========
ntr_max: int = 3               # 每日可牛老婆次数（已有）
ntr_possibility: float = 0.20  # NTR 成功概率（已有）
revenge_window_hours: int = 24
revenge_success_multiplier: float = 2.0

# ========== 换/交换/重置 ==========
change_max_per_day: int = 3    # 已有
swap_max_per_day: int = 2      # 已有
reset_max_uses_per_day: int = 3
reset_success_rate: float = 0.30
reset_mute_duration: int = 300

# ========== 亲密度 ==========
intimacy_per_day: int = 10
intimacy_max: int = 100
intimacy_marry_threshold: int = 60
intimacy_pet_coin_cost: int = 5
intimacy_pet_gain: int = 3
intimacy_gift_coin_cost: int = 30
intimacy_gift_gain: int = 20

# ========== 榜单 ==========
activity_window_days: int = 7
leaderboard_top_n: int = 10

# ========== 稀有度 ==========
rarity_weights:                # 抽卡权重
  SSR: 5
  SR: 20
  R: 50
  N: 25
pity_threshold: int = 10       # 保底次数
pity_min_rarity: str = "SR"

# ========== 经济 ==========
initial_coins: int = 50
daily_checkin_coins: int = 20
reroll_cost: int = 30          # 换老婆消耗（可被 reroll_ticket 抵扣）
pk_winner_reward: int = 15
quest_complete_coins: int = 10

# ========== 商城价格 ==========
shop_prices:
  reroll_ticket: 30
  capacity_expansion: 100      # 扩容 +1
  lock_item: 50
  revive_potion: 80
  protection_charm: 60         # 24h 免疫一次 NTR

# ========== 求婚 ==========
marry_coin_cost: int = 100
```

### 2.5 并发模型

沿用：每群一把 `asyncio.Lock`，所有读写都在锁内。`save_json` 原子写（先 `.tmp` 再 `os.replace`）。

新增：所有 service 方法接受 `gid` 参数，内部走 `locks.acquire(gid)`。

---

## 三、Phase 1：地基重构（2-3 周）

### 3.1 任务清单

#### P1.1 模块骨架（独立可交付）

- [ ] 创建 `app/` 完整目录树 + 所有 `__init__.py`
- [ ] `storage/paths.py`：定义所有文件路径常量（基于 `StarTools.get_data_dir`）
- [ ] `storage/json_store.py`：移植 `load_json` / `save_json` / `sanitize_group_records`，新增 typed load（基于 dataclass）
- [ ] `storage/locks.py`：移植 `get_group_lock`
- [ ] `utils/time.py`：移植 `get_today` / `seconds_until_next_midnight` / 时区解析
- [ ] `utils/image.py`：移植 `_parse_wife_name` / `_build_image_component` / URL 构建

#### P1.2 数据模型层

- [ ] `models/enums.py`：
  - `AcquireVia`（draw / ntr / swap / gift / summon）
  - `Rarity`（N / R / SR / SSR）
  - `Action`（用于活动日志 key）
- [ ] `models/wife.py`：`WifeMeta` dataclass
- [ ] `models/ownership.py`：`Ownership` dataclass
- [ ] `models/profile.py`：`UserProfile` dataclass
- [ ] `models/activity.py`：`ActivityLog` dataclass

#### P1.3 持久化层

- [ ] `storage/stores.py`：每个实体一个 Store 类
  - `WivesMasterStore`（全局，无群锁）
  - `OwnershipStore`：`add(gid, ownership)` / `remove(gid, wid)` / `list_by_user(gid, uid)` / `find_by_wife(gid, wid)` / `set_primary(gid, uid, wid)`
  - `ProfileStore`：`get_or_create(gid, uid, nick)` / `update(gid, uid, ...)`
  - `ActivityStore`：`log(gid, uid, action, delta)` / `prune_old(gid, days)`
  - `SwapStore` / `NtrStatusStore`：复用现有逻辑
- [ ] 所有 Store 方法走群锁 + 原子写

#### P1.4 业务服务层骨架

- [ ] `services/wife_service.py`：抽老婆核心（移植 `_fetch_wife_image`，新增元数据生成入口）
- [ ] `services/ownership_service.py`：所有权 CRUD + 上限校验
  - 校验 `len(user_owns) < profile.capacity` 或 `max_capacity`
- [ ] `services/cooldown_service.py`：内存冷却表
- [ ] 其他 service 占位文件 + 接口签名（不实现）

#### P1.5 旧数据归档（Q6 = 清空重来）

- [ ] `storage/migrations.py`：
  - 启动时检测 `data/records.json`、`data/{gid}.json`、`data/swap_requests.json`、`data/ntr_status.json`
  - 存在则整体移动到 `data/archive_v1/<timestamp>/`
  - 写入 `archive_v1/MIGRATED.md` 记录归档时间与文件清单
- [ ] 不做语义转换（按 Q6 决策）
- [ ] README 顶部加大字号变更公告 + 老婆币补偿说明（首次启动给老用户 `initial_coins`）

#### P1.6 命令路由重写

- [ ] `commands/registry.py`：
  - 维护两张映射表：`LEGACY_COMMANDS` + `GROUPED_COMMANDS`
  - 提供统一 `dispatch(event)` 入口
  - 解析 @target / 编号参数 / 子命令
  - 按命令名长度降序匹配（避免短命令截胡长命令）
- [ ] `app/plugin.py`：`on_all_messages` 简化为调 `registry.dispatch`
- [ ] 所有旧命令基于新数据模型重新实现

#### P1.7 配置 schema 扩展

- [ ] `_conf_schema.json` 按上述完整清单更新
- [ ] `app/plugin.py` 加载所有配置项 + 默认值兜底（避免老配置文件升级失败）

#### P1.8 main.py 精简

- [ ] 仅保留：插件注册、config 注入、生命周期（`_daily_cleanup_loop` 启动）
- [ ] 所有业务委托给 `app/plugin.py`

### 3.2 Phase 1 验收标准

- ✅ 清空数据后，旧 12 个扁平命令全部能跑通抽/查/牛/换/交换/重置/开关
- ✅ 新数据结构完整生效（多老婆持有已就绪，UI 暂未完全暴露）
- ✅ 单元测试覆盖：storage 层、registry 解析、归档逻辑
- ✅ README + CHANGELOG 同步更新
- ✅ git tag: `v3.0.0-phase1`

---

## 四、Phase 2：核心玩法（2 周）

### 4.1 任务清单

#### P2.1 冷却参数化

- [ ] `services/cooldown_service.py`：
  - `check(gid, uid, action) -> bool`（是否已过冷却）
  - `update(gid, uid, action, ts=None)`（记录最新时间戳）
- [ ] 接入：NTR / 抽老婆 / 换老婆 / 交换 / PK 五个动作
- [ ] 配置驱动各自动作冷却时长
- [ ] 测试：并发绕过、重启后行为（重启重置，文档明确）

#### P2.2 活动日志 + 排行榜

- [ ] `services/activity_service.py`：`log(gid, uid, action, delta=1)`
- [ ] NTR 成功双写：
  - `activity[uid].ntr_success++`
  - `activity[tid].ntr_lost++`
  - `profile.total_ntr_success++` / `profile.total_ntr_lost++`
- [ ] `services/leaderboard_service.py`：
  - `aggregate(gid, action, days)`：聚合最近 N 天 → 排序列表
  - 日榜 = `days=1`，周榜 = `days=7`
  - 总榜 = 从 `profile.total_*` 读取
- [ ] 命令：`老婆 排行 [日|周|总] [牛|被牛|PK|收集]`
- [ ] 零点清理循环扩展：删除 `activity_window_days` 之外的日期 key
- [ ] 测试：空数据、单用户、TOP_N 截断、同分并列、跨天边界

#### P2.3 亲密度系统

- [ ] ownership 字段 `intimacy`、`intimacy_updated_date`
- [ ] 零点循环：所有持有老婆 +`intimacy_per_day`（每日一次，依据 `intimacy_updated_date` 判断幂等）
- [ ] 命令 `老婆 摸头 <编号>`：
  - 消耗 `intimacy_pet_coin_cost` 币
  - `intimacy += intimacy_pet_gain`
- [ ] 命令 `老婆 送礼 <编号>`：高消耗高加成
- [ ] 亲密度阈值校验（求婚、PK 加成解锁）
- [ ] 展示消息显示亲密度等级（❤️ Lv.1~10）
- [ ] 被牛走时亲密度清零（写入新主人的记录从 0 开始）
- [ ] 测试：累加幂等、跨天、被牛清零、阈值边界

#### P2.4 复仇机制

- [ ] profile 字段 `last_ntr_by: {uid, ts}`
- [ ] NTR 成功时写入对方 profile
- [ ] `ntr_service.try_ntr` 检测复仇条件：
  - `now - last_ntr_by.ts < revenge_window_hours * 3600`
  - `target_uid == last_ntr_by.uid`
  - 单人每日复仇上限（可复用 `ntr_max`）
- [ ] 复仇时 `ntr_possibility *= revenge_success_multiplier`
- [ ] 命令 `老婆 复仇 @x`（独立路径，明确区分普通牛）
- [ ] 复仇成功后清空 `last_ntr_by`（防链式复仇）
- [ ] 测试：复仇窗口、过期、链式阻断

### 4.2 Phase 2 验收标准

- ✅ 4 个玩法独立可跑
- ✅ 集成测试：完整 NTR → 被牛 → 复仇 → 上榜 → 亲密度清零流程
- ✅ 性能基准：1000 用户群榜单聚合 < 50ms
- ✅ CHANGELOG 更新玩法说明
- ✅ git tag: `v3.0.0-phase2`

---

## 五、Phase 3：扩展玩法（3-4 周）

### 5.1 经济系统（最先做，因 Q1 依赖扩容）

- [ ] `services/economy_service.py`：
  - `balance(gid, uid) -> int`
  - `earn(gid, uid, amount, reason)` / `spend(gid, uid, amount) -> bool`
  - 所有扣款走 spend，余额不足返回 False 由调用方决定提示
- [ ] 每日签到 `老婆 签到`：发放 `daily_checkin_coins`，写入 `last_checkin_date` 防重领
- [ ] 任务系统 `services/quest_service.py`：
  - 每日任务模板：抽老婆 1 次 / 参与 PK 1 次 / 被牛 0 次 / 牛成功 1 次
  - 完成自动发币，写入 `quest_completed_date`
- [ ] 商城 `services/shop_service.py`：
  - 道具清单：`reroll_ticket` / `capacity_expansion` / `lock_item` / `revive_potion` / `protection_charm`
  - `老婆 商城` 列表，`老婆 购买 <道具>` 交易
- [ ] 背包：`profile.inventory` dict
- [ ] 换老婆消耗 `reroll_cost` 币（有 `reroll_ticket` 时抵扣）
- [ ] 测试：余额一致性、并发扣款、越权防护、通胀监控（产出/消耗统计）

### 5.2 老婆稀有度 + 抽卡

- [ ] `services/rarity_service.py`：
  - `roll_rarity()`：根据 `rarity_weights` 加权随机
  - `pick_wife_by_rarity(rarity)`：从 `wives_master` 过滤候选
  - 首次抽到新角色时自动写入 `wives_master`（解析 img → source/chara，按 hash 派生稀有度）
- [ ] 保底机制：`pity_counter`，连续 N 次未达 `pity_min_rarity` 时强制保底
- [ ] 抽卡展示：稀有度边框色、emoji（✨ SSR / 🌟 SR / ⭐ R / · N）
- [ ] 抽到已收集的角色 → 自动转换为"重复"，给予老婆币补偿
- [ ] 测试：概率分布（蒙特卡洛 10000 次）、保底触发、稀有度筛选、重复处理

### 5.3 求婚/锁定系统

- [ ] `services/marry_service.py`：
  - `propose(gid, uid, wid)`：校验亲密度 ≥ 阈值、扣 `marry_coin_cost` 币、设置 `is_locked=true` + `lock_expires_at=null`
  - `lock(gid, uid, wid)`：消耗 `lock_item`，限期锁定（如 7 天）
  - `unlock(gid, uid, wid)`：主动解锁
- [ ] `ntr_service` 前置校验：目标老婆 `is_locked` 时直接失败（友好提示）
- [ ] 复活药水：被牛 24h 内可消耗 `revive_potion` 召唤回（所有权转移回原主，亲密度半减）
- [ ] 保护符：`protection_charm` 装备后下次被牛时自动消耗、阻止转移
- [ ] 命令：`老婆 求婚 <编号>` / `老婆 锁 <编号>` / `老婆 解锁 <编号>`
- [ ] 测试：锁定 NTR 失败、过期自动解锁、复活窗口、保护符消耗

### 5.4 老婆 PK

- [ ] `services/pk_service.py`：
  - 双方各出主老婆（或指定编号）
  - 战力公式：`power = base_stats.atk + base_stats.def + base_stats.hp * 0.5 + intimacy * 2`
  - 加入随机扰动 ±20%
  - 高战力胜，平局随机
  - 胜方奖励：`pk_winner_reward` 币 + 双方图鉴互通（胜方 collection += 对方 wid）
- [ ] 挑战计数（每日上限，可配置 `pk_max_per_day`）
- [ ] PK 战报消息：双方战力、伤害明细、结果
- [ ] 命令：`老婆 PK @x`
- [ ] 测试：战力平衡、跨天计数、平局处理

### 5.5 图鉴系统完善

- [ ] `profile.collection` 记录历史所有 wid（永久）
- [ ] `老婆 图鉴`：分稀有度展示进度（如 SSR 3/15、SR 8/40）
- [ ] `老婆 图鉴 <作品>`：按作品过滤
- [ ] 收集成就：解锁特定作品全集 → 触发老婆币奖励
- [ ] 测试：图鉴写入幂等、查询性能、成就触发

### 5.6 个人面板

- [ ] `老婆 面板` 命令综合展示：
  - 持有老婆列表（编号 / 稀有度 / 亲密度 / 锁定状态）
  - 累计统计（总抽卡 / 总牛 / 总被牛 / PK 胜率）
  - 当前连续天数 + 老婆币余额
  - 今日活动概览 + 任务进度
- [ ] 可选：图片渲染（PIL 生成面板图）

### 5.7 跨群总榜（可选，最后做）

- [ ] 异步聚合所有群 activity 到全局榜
- [ ] 隐私脱敏：仅展示昵称
- [ ] 缓存：每小时刷新一次（内存 + 持久化到 `data/global_leaderboard_cache.json`）
- [ ] 命令：`老婆 排行 跨群`

### 5.8 Phase 3 验收标准

- ✅ 经济闭环（产出/消耗比合理，1 周观察期无通胀）
- ✅ 抽卡概率符合配置（蒙特卡洛测试报告）
- ✅ 求婚/PK/锁定链路完整
- ✅ 个人面板信息齐全
- ✅ 性能基准：10000 用户跨群榜聚合 < 500ms
- ✅ git tag: `v3.0.0`

---

## 六、测试策略

### 6.1 测试金字塔

- **单元测试**（70%）：service、storage、utils
- **集成测试**（20%）：完整命令流程、并发场景
- **端到端测试**（10%）：模拟群聊事件

### 6.2 覆盖优先级

1. 存储层（原子写、并发安全）— **阻塞所有后续**
2. 归档逻辑（不丢数据）
3. 命令路由（双轨解析）
4. 经济系统（余额一致性）— **最高业务优先级**
5. 榜单聚合（边界场景）
6. 复仇/PK（时序逻辑）
7. 抽卡概率（蒙特卡洛）

### 6.3 性能基准

| 场景 | 目标 |
|---|---|
| 单群 1000 用户榜单聚合 | < 50ms |
| 抽老婆命令端到端 | < 200ms |
| 持久化保存（5000 条记录） | < 100ms |
| 10000 用户跨群榜聚合 | < 500ms |

---

## 七、风险与回滚

### 7.1 风险矩阵

| ID | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | 重构期老用户流失（清空数据） | 中 | 公告 + 公测期补偿老婆币 + 图鉴保留（如有诉求） |
| R2 | 并发 bug 数据损坏 | 高 | 群锁 + 原子写 + 单元测试 + save 后回读校验 |
| R3 | 性能回退 | 中 | 性能基准 + 灰度发布（先单群试运行） |
| R4 | 经济通胀/通缩 | 中 | 定期审计产出消耗比、配置可热调 |
| R5 | 抽卡概率偏差 | 低 | 蒙特卡洛测试 + 日志采样 |
| R6 | 命令解析冲突（双轨） | 低 | 注册表按长度降序匹配 + 单元测试 |

### 7.2 回滚策略

- 每个 Phase 完成 → 打 git tag（`v3.0.0-phase1` 等）
- 旧数据归档保留 90 天
- 严重 bug 时：回滚到上一 tag + 恢复对应归档数据
- 配置灰度：新功能可独立开关（`feature_flags`，可选实现）

---

## 八、时间表

| 阶段 | 预估 | 关键交付 | Tag |
|---|---|---|---|
| Phase 1 | 2-3 周 | 模块化 + 归档 + 双轨命令 | `v3.0.0-phase1` |
| Phase 2 | 2 周 | 冷却 + 榜单 + 亲密度 + 复仇 | `v3.0.0-phase2` |
| Phase 3 | 3-4 周 | 经济 + 稀有度 + 求婚 + PK + 图鉴 | `v3.0.0` |
| **总计** | **7-9 周** | **完整新版本** | |

---

## 九、实施建议（给后续 AI 执行者）

1. **严格按 Phase 顺序**，每个 Phase 完成后跑完整测试 + 打 tag
2. **每个 service 方法写 docstring + 类型注解**，便于 LLM 后续接手
3. **数据变更必走 Store 层**，禁止命令层直接操作 JSON
4. **新增配置项必须有默认值**，避免老配置文件升级失败
5. **任何破坏性变更前**：先更新 ROADMAP.md + CHANGELOG.md
6. **遇到设计抉择未覆盖的情况**：回到本文档决策记录章节补充，不要自行假设
7. **遵循现有代码风格**：
   - 中文 docstring + 注释
   - 原子写 + 群锁并发模型
   - `logger.error` / `logger.exception` 记录异常
   - 错误兜底优先于抛异常（参考现有 `load_json`）
