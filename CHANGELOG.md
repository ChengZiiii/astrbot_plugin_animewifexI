# 更新日志

## v3.0.0-phase4

**Phase 4 玩法升级已完成**

- 新增：连续签到奖励、对话/约会、打工系统、NTR 补偿、扩展排行榜
- 命令级 QA：全量 86/86、深度 17/17
- 单元测试：338 passed
- 详见 [ROADMAP_PHASE4_DETAILED.md](ROADMAP_PHASE4_DETAILED.md) 与 [PHASE4_EXECUTION_TICKETS.md](PHASE4_EXECUTION_TICKETS.md)

---

## v3.0.0-phase2

**Phase 2 核心玩法上线（参考 [ROADMAP.md](ROADMAP.md) §四）**

### 新增

- **冷却参数化（P2.1）**：
  - NTR/抽老婆/交换请求 3 个动作接入 `CooldownService`（锁前 check + 成功后 update）
  - 冷却配置：`ntr_cooldown`=60s / `draw_cooldown`=0s / `swap_cooldown`=30s / `pk_cooldown`=120s
  - 命令层处理 `cooldown` reason，显示剩余冷却秒数
  - 换老婆不加冷却（已有 `change_max_per_day` 限制）

- **排行榜（P2.2）**：
  - `services/leaderboard_service.py`：日榜/周榜/总榜/收集榜 4 种排行聚合
  - `commands/leaderboard.py`：`老婆 排行 [日|周|总] [牛|被牛|PK|收集]`
  - 零点循环新增 `prune_activity_logs_for_group`（清理 `activity_window_days` 外的日期 key）

- **亲密度系统（P2.3）**：
  - `pet_wife` / `gift_wife`：消耗币增加亲密度（摸头 +3 / 送礼 +20）
  - `daily_intimacy_increment_for_group`：零点递增（幂等，每日只加一次）
  - NTR 成功时被牛方亲密度归零（转移后 ownership 从 0 开始）
  - 亲密度等级：❤️ Lv.1~10（线性分段，每 10 点一级）
  - `commands/intimacy.py`：`老婆 摸头` / `老婆 送礼`
  - view 命令展示亲密度等级

- **复仇机制（P2.4）**：
  - `try_ntr(is_revenge=True)`：检查 `last_ntr_by` 的 uid + 时间窗口
  - 复仇时 `ntr_prob = min(1.0, ntr_possibility * revenge_success_multiplier)`
  - 复仇成功后清空 `last_ntr_by`（防链式复仇）
  - `commands/revenge.py`：`老婆 复仇 @x`

- **命令注册更新**：
  - `registration.py`：接入排行/复仇/摸头/送礼 4 个真实 handler
  - `grouped_stubs.py`：移除已实现的摸头/送礼/复仇/排行
  - 帮助文本更新为 Phase 2

- **测试扩展**：
  - 新增 4 个测试文件：`test_cooldown_service` / `test_leaderboard_service` / `test_revenge` / `test_intimacy`
  - 总计 187 个 pytest 用例全绿（原有 139 + 新增 48）

### 修复

- `find_by_wid` 参数顺序修正为 `(wid, ownerships)`
- `plugin.py` CooldownService 初始化顺序修正
- `last_ntr_by` 清空用 `{}` 而非 `None`（序列化兼容）

### Phase 2 验收

- ✅ 4 个玩法独立可跑（冷却/排行榜/亲密度/复仇）
- ✅ 187 单元测试全绿
- ✅ ROADMAP.md Phase 2 全部复选框标记完成
- ✅ git tag: `v3.0.0-phase2`

---

## v3.0.0-phase1

**Phase 1 重构完成（参考 [ROADMAP.md](ROADMAP.md) §三）**

### 不兼容变更（升级前必读）

- **数据布局整体迁移**：`config/` 下的 v2.x 数据（`records.json`、`{gid}.json`、
  `swap_requests.json`、`ntr_status.json`）启动时**整体归档**到 `data/archive_v1/<时间戳>/`，
  并写入 `MIGRATED.md` 清单，**不做语义迁移**（Q6 = 清空重来决策）。
- **新数据结构**：每群独立目录 `data/groups/{gid}/`，包含
  `ownership.json` / `profiles.json` / `activity.json` / `swap_requests.json` /
  `daily_counts.json`；全局老婆元数据在 `data/wives_master.json`。
- 老用户首次启动后按新结构空数据起步；可通过 `initial_coins`（默认 50）发放老婆币补偿。

### 新增

- **模块化分层架构**（`app/` 目录）：
  - `models/`：dataclass 形式的实体（`WifeMeta` / `Ownership` / `UserProfile` / `ActivityLog`）
    + 枚举（`AcquireVia` / `Rarity` / `Action`）
  - `storage/`：`Paths` 路径常量、`json_store` 原子读写、`GroupLocks` 群锁、
    6 个 Store 类（`WivesMaster` / `Ownership` / `Profile` / `Activity` / `SwapRequest` /
    `NtrStatus` / `DailyCount`）、`migrations` 旧数据归档
  - `services/`：`PluginConfig` 配置容器、`WifeService` 图片获取、
    `OwnershipService` 业务编排（抽/牛/换/交换/重置完整流程）、
    `CooldownService` 内存冷却表 + 后续玩法扩展位（`IntimacyService` 等）
  - `commands/`：`CommandRegistry` 双轨注册表 + 12 个旧命令处理器 + 分组命令扩展位
  - `api/`：`events` AstrMessageEvent 解析 + `messaging` 消息链构建
  - `utils/`：`time` / `image` / `random_utils` / `format` 纯函数
- **配置 schema 扩展**至 40+ 项（`_conf_schema.json`），全部带默认值与 Phase 归属 hint：
  - 持有上限（`default_capacity` / `max_capacity`）
  - 冷却（NTR/抽/交换/PK 各自秒数）
  - NTR（窗口/复仇倍率）
  - 亲密度（每日增长/上限/阈值/摸头/送礼）
  - 榜单（窗口天数 / TOP N）
  - 稀有度（权重 / 保底）
  - 经济（初始币 / 签到 / 换老婆消耗 / PK 奖励 / 任务奖励）
  - 商城（5 种道具价格）
  - 锁定/婚配相关扩展位（后续演进为锁定卡等配置）
- **本地测试工具集**：139 个 pytest 用例（不依赖 AstrBot 框架），覆盖
  storage / models / utils / ownership_service / migrations / registry / plugin 装配。
  命令 `PYTHONPATH=. python -m pytest` 可在源码目录直接跑通。
- **wid 稳定哈希**：老婆全局 ID 由 `sha1(img)[:8]` 派生，跨运行稳定。
- **零点清理扩展**：原 v2.x 仅清理 `swap_requests`/`records`；v3.x 同时清理
  `daily_counts.json` 与 `swap_requests.json` 的跨天记录。

### 优化

- `main.py` 精简为 5 行（仅插件入口），所有业务委托给 `app/plugin.py`
- 纯逻辑层（`utils` / `storage` / `models` / 大部分 `services`）零 astrbot 依赖，
  便于本地单测
- 业务方法返回 dataclass 结果（`DrawResult` / `NtrResult` / `ChangeResult` / `SwapResult`），
  命令层只做格式化
- 每日次数计数（NTR/换/交换/重置）由 `OwnershipService` 在群锁内统一管理，
  命令层不再自行维护 records 字典
- NTR/换/交换/抽的所有权变动后，自动取消相关的今日交换请求并返还次数（保留 v2.x 行为）

### 修复

- 修复 `OwnershipStore.remove_by_wid` 不就地修改的潜在 bug（原返回新列表，
  调用方仍在原引用操作，导致 NTR 成功后旧 ownership 残留——被 `set_primary` 降级
  但未删除，Phase 3 多老婆功能会受污染）

### Phase 1 验收

- ✅ 清空数据后，旧 12 个扁平命令全部能跑通抽/查/牛/换/交换/重置/开关
- ✅ 新数据结构完整生效（多老婆持有已就绪，UI 暂未完全暴露）
- ✅ 单元测试覆盖：storage 层、registry 解析、归档逻辑、service 业务流程
- ✅ README + CHANGELOG 同步更新
- ✅ git tag: `v3.0.0-phase1`

---

## v2.0.1

**修复**
- 解析命令目标时跳过指向机器人自身的 At：通过 @机器人 唤醒时，唤醒用的 @ 不再被误当作牛/交换/重置的目标（此前会导致同意交换失效、重置白耗次数）
- records.json / swap_requests.json 内层结构被外部改坏时，记录日志并丢弃非法条目，不再导致插件加载失败（补全 v2.0.0 中仅覆盖顶层的损坏降级）
- 查老婆、查看交换请求改用安全方式读取记录字段（owner/target），数据文件被外部改坏导致字段缺失时不再报错
- 数据文件被外部以非 UTF-8 编码保存时，记录日志并以空数据载入，不再导致插件加载失败或命令报错（与缓存列表读取的编码容错对齐）

**优化**
- 导入语句按 PEP 8 分组排列（标准库 → 第三方 → 框架）

## v2.0.0

**升级注意（不兼容变更）**
- 管理员列表改为插件配置项 `admins`（WebUI 中配置），不再读取 data/cmd_config.json，升级后需重新填写管理员
- 老婆数据格式由列表升级为字典 `{"img", "date", "owner"}`，旧数据加载时自动迁移；迁移落盘后**不可降级**回旧版本

**修复**
- 修复每日次数限制的并发竞态：限额检查与自增收进同一群锁，连发刷指令无法再突破上限
- 同意交换前在锁内二次校验双方老婆仍有效，配置被外部改动或损坏时不再崩溃
- JSON 改为原子写入（临时文件 + 替换），写入中断不再损坏数据；损坏时记录日志而非静默清空
- 换老婆改为「先抽到新老婆再替换」，抽取失败时老婆与次数都不再丢失
- 命令匹配按长度降序，短命令不再截胡长命令
- 网络获取老婆列表成功但缓存写入失败时，不再丢弃本次结果
- 抽取本地图库时过滤子目录与非文件条目，坏条目不再被抽中并持久化为当日老婆
- 修复无事件循环时后台任务协程未关闭的告警
- 本地读取图片前校验路径未逃逸出图库目录，图片列表源被劫持时无法再读取任意本地文件
- 数据文件被外部改成非字典的合法 JSON 时，记录日志并以空数据载入，不再导致插件加载失败
- 远程图片列表与缓存按行裁剪首尾空白，杂质条目不再进入图片链接拼接
- 修复零点后、定时清理执行前的窗口期内，换/牛老婆会把昨日已过期的交换请求误报为「自动取消并返还次数」的问题（取消播报只针对当日请求，过期请求仍由过期机制静默清理）

**优化**
- 过期交换请求改为每日零点定时清理（替代抽老婆时顺带清理），同意/拒绝/查看时对陈旧请求即时兜底
- 启动与每日零点自动清理跨天失效的次数记录，records.json 不再无限累积
- 时间处理改用时区感知对象，并跟随 AstrBot 全局时区配置（WebUI 系统设置 `timezone`，默认 Asia/Shanghai；时区数据由 requirements.txt 声明的 tzdata 保证），替代新版 Python 已弃用的 `datetime.utcnow()`
- 全部状态收敛为插件实例属性，import 阶段零副作用
- 显式导入替代 `from astrbot.api.all import *` 通配符导入
- 锁内不再发送消息（统一出锁后发送），缩短持锁时间
- 关键异常（JSON 损坏、保存失败、定时任务出错）记录 error 级日志
- At 消息组件不再强转 int，兼容非纯数字用户 ID 的平台
- 提取公共辅助方法（消息链构建、通用重置逻辑、有效老婆判断），消除重复代码与重复落盘
- 已有待处理交换请求时重复发起视为更换目标：自动取消旧请求、返还当日次数并提示；当日次数用满但有挂起请求时仍可更换目标
- 拒绝跨天的过期交换请求时明确提示「已过期」，与同意交换的提示对齐
- 「切换NTR开关状态」命令支持大写 NTR 输入

## v1.7.6
- 移除废弃的 @register 装饰器，统一使用 metadata.yaml 管理插件信息
- 迁移至 @filter.event_message_type 事件装饰器

## v1.7.5
- 添加老婆列表本地缓存（1小时有效期），减少网络请求，网络失败时自动兜底

## v1.7.4
- 隔日抽老婆时自动清理过期的交换请求

## v1.7.3
- 修改默认URL

## v1.7.2
- 精简代码

## v1.7.1
- 修复牛老婆成功立刻显示

## v1.7.0
- 去除牛老婆成功立刻显示

## v1.6.9
- 修复群消息监听中发送未注册命令导致的属性访问异常

## v1.6.8
- 修复牛老婆和交换老婆的数据交换逻辑

## v1.6.7
- 修改为仅对群触发

## v1.6.6
- 修改昵称匹配方式为完整昵称匹配

## v1.6.5
- 添加并发锁保护，支持多用户同时操作
- 合并记录文件
- 添加老婆帮助命令
- 支持前缀开关配置
- 代码结构优化

## v1.6.4
- 优化老婆名称显示，过滤路径前缀

## v1.6.3
- 支持从GitHub获取图片

## v1.6.2
- 添加logo

## v1.6.1
- 修复重置换老婆逻辑

## v1.6.0
- 添加重置换老婆功能，重置功能合并，共享使用次数

## v1.5.9
- 使用!代替#拼接老婆出处与名称，解决图床访问问题

## v1.5.8
- 润色各种提示信息

## v1.5.7
- 交换老婆成功也会清理其它交换请求

## v1.5.6
- 老婆信息显示出处，需要更新图包

## v1.5.5
- 完善交换老婆逻辑，牛老婆成功后立刻显示
