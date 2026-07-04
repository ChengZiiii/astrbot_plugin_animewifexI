# AnimeWifeX Phase 4 Detailed Roadmap

> 目标：把 `animewifex_玩法升级策划案_减负版_v2.md` 落成一份可以直接交给“低智商但速度快”的模型执行的开发路线图。
>
> 本文不是从零设计，而是**基于当前 `v3.x` 代码现状做差量开发**。
>
> 状态：**已归档**。Phase 4 已完成，本文保留的是开发期拆解记录；当前功能状态请以 `README.md` 与 `CHANGELOG.md` 顶部为准。
>
> 原则：小步提交、文件级落点明确、测试先行、避免架构重写。
>
> 如果需要按最细颗粒度直接执行，请优先阅读：`PHASE4_EXECUTION_TICKETS.md`

---

## 1. 文档用途

这份路线图专门解决两个问题：

1. 后续模型上下文短，容易看不懂当前项目真实结构。
2. 策划案是玩法设计，不是可直接编码的工程拆解。

因此本文会额外提供：

- 当前代码基线
- 已锁定的实现决策
- 分阶段任务拆分
- 每阶段要改哪些文件
- 每阶段必须补哪些测试
- 哪些需求先做，哪些需求延后

后续模型执行时，**只需要按本文顺序推进**，不要自己重排阶段，不要自己补架构幻想。

---

## 2. 当前代码基线

先明确：这个插件已经不是策划案附录里假设的“半成品”，而是一个已经做完 `v3 phase1/2/3` 的模块化项目。

### 2.1 现有结构已经可复用

- 入口：`main.py`
- 装配：`app/plugin.py`
- 命令注册：`app/commands/registration.py`
- 命令层：`app/commands/*.py`
- 核心业务：`app/services/*.py`
- 存储层：`app/storage/*.py`
- 数据模型：`app/models/*.py`
- 单测：`tests/*.py`

### 2.2 已经存在的能力

- 双轨命令系统：旧扁平命令 + `老婆 xxx` 分组命令
- 抽卡、十连、图鉴、面板、签到、任务、商城、锁定、PK、亲密度、复仇
- JSON 原子写 + 群锁并发模型
- 完整 pytest 测试基座

### 2.3 和策划案目标的关键差距

1. `app/services/ownership_service.py` 的 `try_ntr()` 仍是 Phase 4 前的旧逻辑。
当前问题：
 - 固定基础概率 + 简单复仇倍率
 - 成功后被牛方亲密度直接清零
 - 没有复仇令牌、作恶值、新手保护、打工联动
 - 仍保留“攻击者替换掉旧主老婆”的旧语义，不符合多老婆养成目标

2. `app/services/economy_service.py` 的签到仍是固定奖励。
当前问题：
 - 无连续签到奖励
 - 无第 7 天送单抽券
 - 无周宝箱联动

3. `app/services/pk_service.py` 仍是旧 PK。
当前问题：
 - 战力公式仍是 `base_stats + intimacy*2`
 - 无属性克制
 - 无羁绊加成
 - 无打工减益
 - 无败方奖励 / 平局奖励 / 段位积分 / 同对手 24h 防刷

4. `app/services/quest_service.py` 仍是旧任务模板。
当前问题：
 - 任务还是“抽卡 / PK / 不被牛 / 牛成功”
 - 没有新手 3 日引导任务
 - 没有和对话、打工、养成新循环联动

5. `app/models/profile.py` / `app/models/ownership.py` 字段不够。
当前问题：
 - 没有 `registered_at`
 - 没有 `pk_score`
 - 没有 `evil_points`
 - 没有 `titles` / `active_title`
 - 没有打工相关字段

6. 命令层缺口明显。
当前问题：
 - `老婆 对话` 不存在
 - `老婆 约会` 不存在
 - `老婆 打工` 不存在
 - 排行榜还没有亲密度榜 / 恶人榜 / 打工榜 / 段位榜

结论：

- **当前最该做的不是重构目录，而是升级已有 service/command/model。**
- **不要再新造一套并行架构。**

---

## 3. 已锁定的实现决策

这一节最重要。后续模型不要自己改主意。

### 3.1 架构决策

1. **NTR 逻辑继续留在 `OwnershipService`。**
不要新建重型 `NtrService`，否则会和当前命令层、测试层、存储层冲突。

2. **打工系统单独新建 `app/services/work_service.py`。**
原因：打工既影响经济，也影响 NTR，也影响 PK；单独成服务最清晰。

3. **`main.py` 和 `app/plugin.py` 尽量不动。**
当前入口装饰器机制已经稳定，不要为了新玩法重构插件入口。

4. **命令优先复用现有文件。**
 - `app/commands/intimacy.py`：继续放 `摸头/送礼/对话/约会`
 - `app/commands/economy.py`：继续放 `签到/任务/商城/购买/背包`
 - `app/commands/pk.py`：继续放 PK
 - `app/commands/leaderboard.py`：继续扩榜单
 - 只新增一个 `app/commands/work.py`

### 3.2 数据决策

1. **`UserProfile.registered_at` 只对新用户在创建时写入。**
老用户没有这个字段时，`from_dict()` 默认 `0`，视为“老玩家，不享受新手保护”。

2. **不写一次性迁移脚本。**
本项目 dataclass `from_dict()` 已经支持向后兼容，优先用默认值兼容旧 JSON。

3. **复仇令牌放进 `profile.inventory`。**
不要单独新建 `revenge_tokens` 顶层字段。

建议新增库存 key：

- `revenge_token`
- `insurance_card`（如果进入第二波实现）

4. **打工运行态以 `Ownership` 为准，用户维度统计放 `UserProfile`。**

`Ownership` 新增：

- `is_working`
- `work_mode`
- `work_started_at`
- `work_ends_at`

`UserProfile` 新增：

- `work_streak`
- `work_last_settle_date`
- `work_week_key`
- `work_week_income`
- `work_contract_reserved`
- `work_partner_uid`
- `work_partner_date`
- `weekly_box_claimed_week`

注意：

- **不要在 `UserProfile` 再存一份 `start_ts/end_ts`。**
- **不要让同一份状态在两处重复为真源。**

5. **元素属性不持久化。**
策划案提到可在 `WifeMeta` 加 `element`，但为了减小迁移和回填复杂度，改为：

- 在 `PkService` 内根据 `base_stats` 的最高项实时推导
- 规则锁死：`atk -> 力量`，`hp -> 敏捷`，`def -> 智力`
- 如果并列：按 `atk > hp > def` 优先级裁决

6. **赛季/月度/周度重置全部做懒重置。**
不要新增 cron 或常驻任务。

- `pk_score`：按自然月 `YYYY-MM` 懒重置
- `evil_points`：按自然月 `YYYY-MM` 懒重置
- `work_week_income`：按 ISO 周 `YYYY-WW` 懒重置
- `weekly_box_claimed_week`：按 ISO 周检查

7. **NTR 成功后，攻击者保留原有老婆，不再删旧主老婆。**
新的语义是“偷到新的所有权”，不是“拿新老婆换掉旧老婆”。

锁定行为：

- 被偷到的老婆自动设为攻击者新主老婆
- 攻击者原主老婆降为非主老婆，但不删除

8. **保护符采用“自动触发、单次消耗”语义。**
不新增通用 `老婆 使用` 命令。

建议规则：

- 当用户背包里有 `protection_charm` 时，第一次遭受 NTR 尝试时自动生效
- 本次 NTR 概率额外乘 `0.3`
- 本次结算后消耗 1 个保护符（无论成功或失败）

9. **周宝箱改为“懒发放”，不做周日定时推送。**

触发入口：

- `老婆 签到`
- `老婆 任务`
- `老婆 面板`

这三个入口任一触发时，如果满足本周条件且未领取，再发箱子。

10. **打工完成也采用“懒结算”。**

结算入口：

- `老婆 打工`
- `查老婆`
- `老婆 面板`
- `老婆 PK`
- `牛老婆`
- `老婆 复仇`

如果老婆已到 `work_ends_at`，先结算打工，再继续当前命令。

11. **打工中被牛走时，收益在 NTR 成功当场结算给攻击者。**
不要把这笔收益留到未来再结算，否则会把亲密度奖励、归属判定都搞乱。

12. **以下内容放到第二波，不阻塞首发：**

- 打工搭档
- 打工合约
- 道具赠送
- 保险卡
- 亲密度自然衰减

原因：这些都不是闭环主路径，先保证“签到 -> 抽 -> 养 -> PK/NTR/打工 -> 回报”打通。

---

## 4. 交付范围分层

### 4.1 第一波必须完成

- 配置扩展
- 模型扩展
- 连续签到
- 对话 / 约会
- 亲密度 5 级体系与升级奖励
- NTR 降级补偿
- 新手保护
- 复仇令牌
- 作恶值
- 打工系统核心
- PK 重构核心
- 新排行榜
- 面板/查看展示增强
- 完整测试补齐

### 4.2 第二波再做

- 打工合约
- 打工搭档
- 周惊喜宝箱
- 称号附加效果细化
- 道具赠送
- 保险卡

### 4.3 观察期后再决定

- 亲密度自然衰减
- 更复杂的 AB 调参
- 跨群排行榜

---

## 5. 文件影响总表

### 5.1 必改文件

- `_conf_schema.json`
- `app/utils/time.py`
- `app/models/enums.py`
- `app/models/profile.py`
- `app/models/ownership.py`
- `app/storage/paths.py`
- `app/storage/stores.py`
- `app/services/plugin_config.py`
- `app/services/economy_service.py`
- `app/services/ownership_service.py`
- `app/services/pk_service.py`
- `app/services/quest_service.py`
- `app/services/shop_service.py`
- `app/services/rarity_service.py`
- `app/services/leaderboard_service.py`
- `app/commands/registration.py`
- `app/commands/admin.py`
- `app/commands/intimacy.py`
- `app/commands/economy.py`
- `app/commands/ntr.py`
- `app/commands/revenge.py`
- `app/commands/pk.py`
- `app/commands/leaderboard.py`
- `app/commands/panel.py`
- `app/commands/view.py`

### 5.2 新增文件

- `app/services/work_service.py`
- `app/commands/work.py`
- `tests/test_work_service.py`

### 5.3 高概率要改的测试文件

- `tests/test_models.py`
- `tests/test_economy_service.py`
- `tests/test_intimacy.py`
- `tests/test_ownership_service.py`
- `tests/test_revenge.py`
- `tests/test_pk_service.py`
- `tests/test_quest_service.py`
- `tests/test_shop_service.py`
- `tests/test_rarity_service.py`
- `tests/test_leaderboard_service.py`
- `tests/test_commands_registry.py`
- `tests/test_storage.py`

---

## 6. 具体开发阶段

下面每个阶段都按“先 service，再 command，再 test”的顺序做。

---

## Phase 0：基线冻结

### 目标

把当前工程状态固定下来，避免后续模型一边写一边猜。

### 任务

#### P0.1 跑基线测试

命令：

```powershell
$env:PYTHONPATH='.'; python -m pytest
```

要求：

- 记录当前总用例数
- 记录现有失败数
- 如果基线就失败，先修基线再进入 Phase 1

#### P0.2 建立 Phase 4 开发分支文档锚点

更新文件：

- `README.md`
- `CHANGELOG.md`

先只加一句：

- `在 README.md / CHANGELOG.md 顶部加入指向 ROADMAP_PHASE4_DETAILED.md 的入口说明`

目的：后续模型能快速定位本文。

### 验收标准

- 基线测试结果清楚
- 后续执行者知道该看哪份文档

---

## Phase 1：配置、模型、时间工具

### 目标

先把后续所有玩法需要的基础字段铺好，但暂时不改复杂行为。

### 任务

#### P1.1 扩展配置容器 `app/services/plugin_config.py`

必须新增的配置字段：

- `checkin_streak_3day_bonus`
- `checkin_streak_7day_bonus`
- `checkin_streak_7day_item`
- `chat_cooldown`
- `chat_intimacy_gain`
- `chat_coin_reward`
- `date_cooldown`
- `date_intimacy_gain`
- `date_coin_cost`
- `ntr_intimacy_retain_ratio`
- `ntr_coin_compensation_per_intimacy`
- `ntr_coin_compensation_max`
- `ntr_streak_penalty`
- `intimacy_shield_threshold`
- `intimacy_shield_reduction`
- `newbie_ntr_protection_days`
- `newbie_ntr_retain_ratio`
- `revenge_token_bonus`
- `revenge_success_intimacy_restore`
- `revenge_fail_consolation_coins`
- `evil_points_broadcast_threshold`
- `evil_points_compensation_multiplier`
- `pk_loser_reward`
- `pk_loser_reward_close_threshold`
- `pk_tie_reward`
- `pk_random_variance`
- `pk_score_per_win`
- `pk_score_per_lose`
- `pk_pair_cooldown_hours`
- `pk_score_decay_days`
- `pk_score_decay_amount`
- `pk_element_advantage`
- `pk_element_disadvantage`
- `duplicate_coin_compensation`
- `work_enabled`
- `work_modes`
- `work_streak_bonus`
- `intimacy_levelup_rewards`
- `weekly_surprise_box`
- `newbie_guide`

第二波再接的配置：

- `work_contract_cost`
- `work_contract_reward_multiplier`
- `work_partner_bonus`
- `work_partner_daily_limit`
- `intimacy_decay`

要求：

- dataclass 默认值齐全
- `from_dict()` 全部解析
- `default_for_test()` 不需要额外传参就能跑通

#### P1.2 扩展 `_conf_schema.json`

要求：

- 跟 `PluginConfig` 完全对齐
- object 类型继续使用 `items` 嵌套 schema
- 第一波和第二波字段都写进去，但第二波可在说明里标注“暂未启用”

#### P1.3 扩展 `app/utils/time.py`

新增辅助方法：

- `get_week_key(tz) -> str`，格式建议 `YYYY-WW`
- `get_month_key(tz) -> str`，格式建议 `YYYY-MM`
- `is_next_day(prev_date, today) -> bool`
- `hours_between(ts1, ts2) -> float`

注意：

- 不要引入第三方时间库
- 保持与当前时区工具一致

#### P1.4 扩展 `app/models/enums.py`

新增 `Action`：

- `CHECKIN`
- `INTIMACY`
- `CHAT`
- `DATE`
- `PK_TIE`
- `WORK_START`
- `WORK_COMPLETE`
- `WORK_STOLEN`

第二波预留：

- `SUPPORT`

#### P1.5 扩展 `app/models/profile.py`

新增字段：

- `registered_at: int = 0`
- `pk_score: int = 0`
- `pk_score_season: str = ""`
- `pk_last_active_date: str = ""`
- `evil_points: int = 0`
- `evil_points_month: str = ""`
- `titles: List[str] = []`
- `active_title: str = ""`
- `work_streak: int = 0`
- `work_last_settle_date: str = ""`
- `work_week_key: str = ""`
- `work_week_income: int = 0`
- `work_contract_reserved: str = ""`
- `work_partner_uid: str = ""`
- `work_partner_date: str = ""`
- `weekly_box_claimed_week: str = ""`
- `first_ntr_lost_done: bool = False`
- `newbie_guide_claimed: List[str] = []`

库存默认值新增：

- `revenge_token`
- `insurance_card`（第二波用，不先接逻辑也要预留）

#### P1.6 扩展 `app/models/ownership.py`

新增字段：

- `is_working: bool = False`
- `work_mode: str = ""`
- `work_started_at: int = 0`
- `work_ends_at: int = 0`

#### P1.7 更新 `app/storage/stores.py`

重点修改：`ProfileStore.get_or_create()`

要求：

- 新建 profile 时自动写 `registered_at`
- 旧 profile 缺字段时通过 dataclass 默认值补齐
- 不要新增单独迁移流程

#### P1.8 把重复抽卡补偿改成配置驱动

当前 `app/services/rarity_service.py` 里仍有硬编码重复补偿值，需要改成读取：

- `config.duplicate_coin_compensation[rarity]`

同时补测试覆盖：

- N/R/SR/SSR 四档补偿分别正确
- 缺失 rarity key 时回退到安全默认值

### 测试

- `tests/test_models.py`
 - 旧数据缺字段时可正常加载
 - 新字段能 round-trip
 - 新 inventory key 自动补齐
- `tests/test_rarity_service.py`
 - 重复补偿按稀有度读取配置

### 验收标准

- 所有新字段已可读写
- 老 JSON 文件不崩
- 这一阶段不要求新玩法可用，只要求“地基铺好”

---

## Phase 2：签到、互动、亲密度等级重构

### 目标

先打通“签到 -> 养成 -> 小额产出”的轻量正循环。

### 任务

#### P2.1 重构 `app/services/economy_service.py::daily_checkin`

改动目标：

- 连续签到 + 断签重置
- 第 3 天额外奖励
- 第 7 天额外奖励 + 单抽券
- 写入 `Action.CHECKIN`

实现规则锁死：

- 连续判断只看 `last_checkin_date`
- 隔天签到：`streak_days += 1`
- 同日重复：拒绝
- 中断后重置到 `1`

#### P2.2 重构亲密度等级工具

当前是 10 级线性表情，改为 5 档业务等级：

- Lv1 `0-19`
- Lv2 `20-39`
- Lv3 `40-59`
- Lv4 `60-79`
- Lv5 `80-100`

优先改动点：

- `app/services/ownership_service.py`
- `app/commands/intimacy.py`
- `app/commands/view.py`
- `app/commands/panel.py`

新增 helper：

- `get_intimacy_level_name(intimacy)`
- `get_intimacy_level_no(intimacy)`
- `get_intimacy_bonus_ratio(intimacy)`
- `has_intimacy_shield(intimacy)`

#### P2.3 给现有 `摸头/送礼` 接升级奖励

要求：

- 亲密度提升后，若跨过新等级阈值，则发等级奖励
- 奖励只发一次，不允许重复刷

建议做法：

- 通过“前等级 vs 后等级”比较判断是否升级
- 不额外持久化等级字段，按 intimacy 实时推导

#### P2.4 在 `app/commands/intimacy.py` 新增 `handle_chat` / `handle_date`

新增命令：

- `老婆 对话`
- `老婆 约会`

规则锁死：

- 对话：`+1 亲密 +5 币`，2h 冷却
- 约会：`+8 亲密`，12h 冷却，花 10 币

行为日志要求：

- `摸头/送礼/对话/约会` 全部都要写 `Action.INTIMACY`
- `对话` 额外写 `Action.CHAT`
- `约会` 额外写 `Action.DATE`

不要新建 `InteractService`。
直接继续放在 `OwnershipService` 内实现 `chat_wife()` / `date_wife()` 即可。

#### P2.5 更新命令注册和帮助文本

修改文件：

- `app/commands/registration.py`
- `app/commands/admin.py` 中帮助文本生成逻辑

### 测试

- `tests/test_economy_service.py`
 - 连签 + 断签 + 第 3/7 天奖励
- `tests/test_intimacy.py`
 - 新等级区间
 - 升级奖励只发一次
 - 对话冷却
 - 约会冷却与扣费
- `tests/test_commands_registry.py`
 - `老婆 对话`
 - `老婆 约会`

### 验收标准

- 签到奖励有成长感
- 亲密度玩法从“纯加数值”升级为“等级驱动”
- 玩家有除了摸头/送礼之外的低负担日常交互

---

## Phase 3：NTR 重构、新手保护、复仇令牌

### 目标

把当前最伤玩家体验的一段逻辑改成“可痛但不崩”。

### 任务

#### P3.1 重写 `OwnershipService.try_ntr()` 的成功率流水线

必须按固定顺序计算概率：

1. 基础概率 `ntr_possibility`
2. 亲密度护盾
3. 保护符
4. 锁定卡
5. 复仇加成
6. 同目标连续成功衰减
7. 新手保护
8. 打工加成（如果目标正在打工）

要求：

- 把每个倍率拆成可读变量
- 不要写一整条超长表达式
- 返回结果对象里增加 `final_probability` 便于测试和文案调试

#### P3.2 把“亲密度归零”改成“保留 + 补偿”

新规则：

- 普通玩家：保留 50%
- 新手玩家：保留 75%
- 币补偿：`lost_intimacy * 2`，上限 50

注意：

- 这里修改的是**被牛方失去老婆时的旧 ownership 数据**
- 转移到攻击者后的新 ownership 初始亲密度仍然是 `0`

#### P3.3 接入复仇令牌

实现要求：

- 被牛成功后，受害者 `inventory["revenge_token"] += 1`
- 首次被牛额外给 1 个，总共 2 个
- `老婆 复仇` 优先消耗 1 个令牌
- 有令牌时，复仇倍率再叠 `revenge_token_bonus`
- 失败后给 `revenge_fail_consolation_coins`

#### P3.4 新手保护

实现规则锁死：

- `registered_at == 0` 视为老玩家，不进入保护
- 新玩家保护窗口只按“注册时间差”判断
- 第 1 天直接免疫 NTR
- 第 1 天 PK 败方奖励翻倍放到 PK 阶段实现

#### P3.5 作恶值

要求：

- NTR 成功 +1
- 按月懒重置
- 达到 3：查看/面板提示危险用户
- 达到 5：本次受害者补偿翻倍 + 可触发群播报文案

#### P3.6 保护符自动触发

要求：

- 在 `try_ntr()` 中自动检查目标 `inventory["protection_charm"]`
- 本次概率乘 `0.3`
- 结算完成后扣掉 1 个

#### P3.7 改 `老婆 复仇` 成功语义

成功后：

- 抢回目标老婆
- 恢复到被牛前的 75% 亲密度
- 清空 `last_ntr_by`

为此需要在 profile 或 result 中增加“最近一次被牛前亲密度快照”吗？

锁定方案：

- **不额外持久化完整快照**
- 只在 `last_ntr_by` 中扩展 `wid` 和 `lost_intimacy`
- 复仇成功后用 `lost_intimacy` 推算恢复值

#### P3.8 更新命令文案

修改文件：

- `app/commands/ntr.py`
- `app/commands/revenge.py`
- `app/commands/view.py`
- `app/commands/panel.py`

文案必须体现：

- 保留亲密度
- 币补偿
- 复仇令牌数量
- 是否处于新手保护
- 是否触发保护符

### 测试

- `tests/test_ownership_service.py`
 - 普通 NTR 补偿
 - 新手保护
 - 同目标连续衰减
 - 保护符扣减
 - 攻击者不再删除旧主老婆
- `tests/test_revenge.py`
 - 有令牌 / 无令牌复仇
 - 失败安慰奖
 - 成功恢复亲密度 75%
- `tests/test_shop_service.py`
 - 保护符库存被自动消费

### 验收标准

- 被牛不再一夜回到解放前
- 复仇链闭环完整
- 新手前 24h 不会被玩法吓退

---

## Phase 4：打工系统核心

### 目标

把策划案中的“风险换收益”正式接入现有闭环。

### 任务

#### P4.1 新建 `app/services/work_service.py`

至少提供这些方法：

- `start_work(gid, uid, nick, mode)`
- `resolve_due_work(gid, uid, nick)`
- `resolve_stolen_work(gid, victim_uid, attacker_uid, wid)`
- `get_work_status(gid, uid)`
- `clear_work_state(ownership, profile)`

建议新建结果 dataclass：

- `WorkStartResult`
- `WorkResolveResult`

#### P4.2 核心打工模式先只做 3 种

- `normal`
- `overtime`
- `expedition`

规则以配置为准：

- 时长
- 启动费
- 收益区间
- NTR 概率乘数
- PK 战力惩罚
- 完成时亲密度增加
- 启动时写 `Action.WORK_START`
- 完成时写 `Action.WORK_COMPLETE`
- 被截胡时写 `Action.WORK_STOLEN`

#### P4.3 在 `OwnershipService.try_ntr()` 接打工联动

如果目标老婆 `is_working=True`：

- 概率乘对应打工倍率
- 若本次 NTR 成功，立刻调用 `WorkService.resolve_stolen_work()`
- 将打工收益发给攻击者
- 清空原打工状态

#### P4.4 在 `PkService` 接打工惩罚

如果主老婆正在打工：

- 战力按模式扣减

#### P4.5 新建 `app/commands/work.py`

先只做一个子命令入口：

- `老婆 打工`
- `老婆 打工 加班`
- `老婆 打工 远征`

不要在第一波里实现：

- `老婆 打工 合约`
- `老婆 打工 搭档`

#### P4.6 在这些命令入口前做“懒结算”

- `app/commands/work.py`
- `app/commands/view.py`
- `app/commands/panel.py`
- `app/commands/pk.py`
- `app/commands/ntr.py`
- `app/commands/revenge.py`

要求：

- 先 resolve
- 如果有已完成打工，先把结算消息发出来，再继续原命令

#### P4.7 更新展示

`view.py` / `panel.py` 需要显示：

- 是否打工中
- 打工模式
- 剩余时间
- 本周打工收入
- 连续打工天数

### 测试

- 新增 `tests/test_work_service.py`
 - 启动费扣除
 - 时间到后正常结算
 - 打工中被牛，收益转给攻击者
 - 打工状态清空
 - 打工时 PK 惩罚被读取
- `tests/test_commands_registry.py`
 - `老婆 打工`

### 验收标准

- 玩家可以启动打工
- 打工能在之后任意交互点懒结算
- 打工确实提升被牛风险并降低 PK 战力

---

## Phase 5：PK 重构核心

### 目标

让 PK 从“比大小”变成“有养成回报、有限策略、不可刷分”。

### 任务

#### P5.1 在 `app/services/pk_service.py` 重写 `_calc_power()`

新公式锁死为：

```text
power = (atk + def + hp*0.5)
      * (1 + intimacy/500)
      * (1 + bond_bonus)
      * (1 - work_penalty)
      * element_modifier
      * title_modifier
```

其中：

- `bond_bonus`：同作品 2/3/4+ 分别 `0.05/0.10/0.15`
- `work_penalty`：由打工模式决定
- `element_modifier`：克制 `1.2`，被克 `0.8`
- `title_modifier`：第一波只接 `PK 黄金 +2%`、`PK 钻石 +5%`

#### P5.2 新增羁绊加成 helper

位置建议：

- `OwnershipService.get_bond_bonus(gid, uid, primary_wid)`

不要单独新建 `BondService`。

#### P5.3 重写 `_pk_inner()` 的结算

必须新增：

- 败方奖励
- 平局奖励
- 新手败方翻倍
- `pk_score`
- `pk_last_active_date`
- `Action.PK_TIE`

建议规则锁死：

- 胜：`+15 币`，`+5 分`
- 败：
  - 战力差 <= 50%：`+5 币`，`+1 分`
  - 战力差 > 50%：`+1 币`，`+0 分`
- 平：双方 `+8 币`，双方 `+2 分`

#### P5.4 加同对手 24h 防刷

这里不要用内存冷却，必须持久化。

做法锁死：

- 在 `app/storage/stores.py` 新增一个轻量 `PkPairStore`
- 文件路径：`data/groups/{gid}/pk_pairs.json`
- key 用排序后的 `uid1|uid2`
- value 存最后一次 PK 时间戳

因此必须同步修改：

- `app/storage/paths.py`
- `tests/test_storage.py`

理由：

- 需要跨 reload 保持
- 不适合塞进 `CooldownService`

#### P5.5 加赛季分段位映射

段位规则锁死：

- 青铜：`0-99`
- 白银：`100-299`
- 黄金：`300-599`
- 钻石：`600+`

只做“当前段位”和“当前分数”，第一波不做赛季结算发奖。

#### P5.6 更新 `app/commands/pk.py`

战报文案要显示：

- 双方元素类型
- 双方最终战力
- 是否存在克制关系
- 胜/负/平
- 双方获得的币和积分
- 当前段位

### 测试

- `tests/test_pk_service.py`
 - 元素克制
 - 羁绊加成
 - 打工惩罚
 - 败方奖励
 - 平局奖励
 - 同对手 24h 防刷
 - 新手败方翻倍
 - 段位区间判断

### 验收标准

- PK 不是纯随机拼点
- 输也不是完全白打
- 段位和积分能驱动重复参与

---

## Phase 6：任务、排行榜、面板、称号

### 目标

把新增循环做成“看得见”的长期反馈。

### 任务

#### P6.1 重写 `app/services/quest_service.py`

改成双模式：

1. 新手引导任务
2. 标准每日任务

新手引导锁死为：

- `day1_draw_once`
- `day2_pet_and_chat`
- `day3_pk_once`

标准每日任务建议锁死为：

- 抽老婆 1 次
- 亲密互动 2 次
- PK 1 次
- 打工 1 次

注意：

- “亲密互动”通过 `Action.INTIMACY` 统计
- “打工 1 次”以 `Action.WORK_START` 计数

#### P6.2 扩展 `app/services/leaderboard_service.py`

新增榜单：

- `rank_pk_score()`
- `rank_primary_intimacy()`
- `rank_evil_points()`
- `rank_work_week_income()`
- `rank_work_streak()`

保持旧榜不删。

#### P6.3 扩展 `app/commands/leaderboard.py`

新增可识别关键词：

- `段位`
- `亲密`
- `恶人`
- `打工收入`
- `打工连续`

无参数时建议输出：

- 段位榜
- 亲密度榜
- 恶人榜
- 打工收入榜

#### P6.4 基础称号系统

第一波只实现这些称号：

- `深情之人`
- `复仇者`
- `打工之王`
- `恶名昭著`
- `PK 黄金`
- `PK 钻石`

实现位置：

- 直接在相关 service 里调用统一 helper
- helper 可放 `ownership_service.py` 或新建超轻量 `title` 辅助函数

不要为了称号系统再造一个大 service。

#### P6.5 更新 `panel.py` / `view.py`

面板需要新增显示：

- 当前称号
- 当前 PK 积分 / 段位
- 主老婆亲密度等级名
- 打工状态
- 复仇令牌数量
- 作恶值

#### P6.6 更新 `shop_service.py`

第一波只做两件事：

- 加入 `revenge_token` 不可购买、仅系统发放
- `protection_charm` 仍可购买但不允许超上限
- `老婆 商城` 文案里去掉未实现的 `老婆 使用 <道具名>` 提示

不要在第一波里实现：

- 道具赠送
- 保险卡

### 测试

- `tests/test_quest_service.py`
 - 新手任务和标准任务切换
- `tests/test_leaderboard_service.py`
 - 新榜单排序
- `tests/test_models.py`
 - titles / active_title round-trip

### 验收标准

- 玩家能明显看到自己的长期进度
- 榜单能展示打工、作恶、养成、PK 四条成长线

---

## Phase 7：第二波扩展功能

这一阶段只在 Phase 1-6 全绿后再做。

### 任务优先级

#### P7.1 打工合约

最小实现：

- `work_contract_reserved` 只存一个模式字符串
- 下一次同模式打工结算时收益 `x1.5`
- 打工中被牛则合约作废

#### P7.2 打工搭档

最小实现：

- 只支持一对一
- 只支持同日一次
- 任意一方被牛，搭档失效

#### P7.3 每周惊喜宝箱

实现要求：

- 依赖 `Action.CHECKIN` 统计本周签到天数
- 通过懒触发领取

#### P7.4 道具赠送

建议实现：

- 新命令 `老婆 赠送 <道具> @用户`
- 仅允许赠送可交易道具
- `revenge_token` 不可赠送

#### P7.5 保险卡

这个需求在策划案里没有写清楚，必须锁死后才能做。

建议规则：

- 被牛成功时若持有 `insurance_card`
- 自动消耗 1 个
- 本次额外返还 `20` 币并额外给 `1` 个 revenge token

如果不接受这个定义，就先不要做。

---

## 7. 每阶段建议的提交粒度

为了适配“低智商但速度快”的模型，每次提交不要超过以下粒度：

### 推荐批次

1. 一个 service 文件 + 一个测试文件
2. 一个 command 文件 + 一个 registry/help 更新 + 一个测试文件
3. 一个 model 文件 + `test_models.py`

### 不推荐批次

1. 同时改 8 个 service
2. 一次性把 Phase 3-6 全做完
3. 先写完所有代码再补测试

---

## 8. 每阶段的测试执行顺序

### 8.1 小步测试

每做完一个批次，先跑相关测试：

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_models.py
$env:PYTHONPATH='.'; python -m pytest tests/test_economy_service.py
$env:PYTHONPATH='.'; python -m pytest tests/test_ownership_service.py
$env:PYTHONPATH='.'; python -m pytest tests/test_pk_service.py
```

### 8.2 阶段测试

每完成一个 Phase，至少跑：

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_models.py tests/test_commands_registry.py tests/test_plugin.py
```

### 8.3 里程碑测试

Phase 3、Phase 4、Phase 6 完成后跑全量：

```powershell
$env:PYTHONPATH='.'; python -m pytest
```

---

## 9. 手工 QA 清单

每个里程碑至少手动过以下指令：

### 9.1 养成链

- `老婆 签到`
- `抽老婆`
- `老婆 摸头`
- `老婆 对话`
- `老婆 约会`
- `老婆 面板`

### 9.2 对抗链

- `牛老婆 @某人`
- `老婆 复仇 @某人`
- `老婆 PK @某人`
- `老婆 排行`

### 9.3 打工链

- `老婆 打工`
- 等待结束后 `老婆 面板`
- 打工中被牛
- 打工中 PK

### 9.4 新手链

- 新账号首抽
- 新账号 Day1 被 NTR
- 新账号 Day1 PK 失败
- 新账号完成 day1/day2/day3 引导任务

---

## 10. 明确禁止事项

后续模型执行时，禁止做以下事情：

1. 不要把 NTR 逻辑从 `OwnershipService` 拆成全新大 service。
2. 不要重写 `main.py` 的 AstrBot 装饰器入口。
3. 不要把 JSON 存储改成 SQLite/数据库。
4. 不要为了周宝箱/打工结算新增独立后台线程。
5. 不要在第一波实现里加入“老婆技能系统”“装备系统”“PVE”。
6. 不要引入新的复杂第三方依赖。
7. 不要为了元素系统去改现有全量 `wives_master.json` 数据格式。

---

## 11. 最终推荐执行顺序

如果只有一个快速模型在执行，严格按下面顺序：

1. `Phase 1` 配置 + 模型 + 时间工具
2. `Phase 2` 连签 + 对话 + 约会 + 新亲密度等级
3. `Phase 3` NTR 重构 + 新手保护 + 复仇令牌
4. `Phase 4` 打工系统核心
5. `Phase 5` PK 重构核心
6. `Phase 6` 任务 + 榜单 + 面板 + 称号
7. 全量测试 + 手工 QA
8. 再进入 `Phase 7` 第二波扩展

不要调换 `Phase 4` 和 `Phase 5`。
因为 PK 需要读取打工惩罚，而打工不依赖新 PK 逻辑。

---

## 12. 一句话总结

这一轮升级最关键的不是“多做功能”，而是按下面顺序打通真实闭环：

```text
连续签到 -> 抽卡 -> 互动养成 -> 打工/PK/NTR -> 排行/称号/补偿 -> 再投入
```

只要按本文顺序推进，后续模型即使能力一般，也能把复杂策划案拆成稳定、可测、可回滚的工程实现。
