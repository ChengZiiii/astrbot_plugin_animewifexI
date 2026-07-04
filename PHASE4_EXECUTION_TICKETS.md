# Phase 4 Execution Tickets

> 用途：把 `ROADMAP_PHASE4_DETAILED.md` 再拆成可机械执行的开发票据。
>
> 目标读者：上下文短、理解力一般、但写代码速度快的模型。

---

## 0. 执行规则

### 0.1 总规则

1. 严格按票据顺序执行，不要跳票，不要并票。
2. 一次只做一张票，做完就跑该票指定测试。
3. 除非票据明确要求，否则不要新建 service、不要改架构、不要顺手清理 unrelated code。
4. 任何数据变更必须兼容旧 JSON，禁止写破坏性迁移。
5. 每张票都要先改 service/model/store，再改 command，最后改 test。

### 0.2 票据完成格式

每张票完成后，输出必须包含：

1. 改了哪些文件
2. 跑了哪些测试
3. 测试结果
4. 是否有未做项

### 0.3 禁止事项

1. 不要把 JSON 存储换成数据库。
2. 不要重写 `main.py` 的 AstrBot 入口装饰器。
3. 不要把 `OwnershipService` 的 NTR 逻辑整体迁出。
4. 不要在第一波实现里加入 PVE、技能、装备、联盟、公会。
5. 不要引入新三方依赖，除非票据明确写出。

---

## T00 基线冻结

### 目标

记录当前工程测试基线，并让后续模型知道文档入口。

### 前置

- 无

### 只允许修改

- `README.md`
- `CHANGELOG.md`

### 必须执行

1. 跑一次全量 `pytest`，记录用例数和失败数。
2. 在 `README.md` 加一句 Phase 4 开发入口说明。
3. 在 `CHANGELOG.md` 顶部加一句 Phase 4 开发中说明。

### 不要做

1. 不要顺手修测试失败，除非基线已经红了且阻塞后续。
2. 不要改业务代码。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest
```

### 完成定义

- 基线结果已记录
- `README.md` / `CHANGELOG.md` 能引导到 Phase 4 文档

---

## T01 扩展 PluginConfig

### 目标

先把 Phase 4 第一波和第二波配置字段补齐到 `PluginConfig`。

### 前置

- T00

### 只允许修改

- `app/services/plugin_config.py`

### 必须实现

新增并解析这些字段：

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

第二波字段也先加默认值：

- `work_contract_cost`
- `work_contract_reward_multiplier`
- `work_partner_bonus`
- `work_partner_daily_limit`
- `intimacy_decay`

### 不要做

1. 不要改 `_conf_schema.json`。
2. 不要提前实现任何业务逻辑。

### 测试

- 暂不新增测试文件
- 先跑 `test_models.py` 和 `test_plugin.py` 确认默认配置不炸

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_models.py tests/test_plugin.py
```

### 完成定义

- `PluginConfig` 默认构造可用
- `from_dict()` 能解析新增字段

---

## T02 扩展配置 Schema

### 目标

让 WebUI schema 和 `PluginConfig` 对齐。

### 前置

- T01

### 只允许修改

- `_conf_schema.json`

### 必须实现

1. 把 T01 的字段全部补到 schema。
2. object 类型继续使用 `items` 嵌套写法。
3. 第二波字段可在描述里注明“暂未启用”，但 schema 先保留。

### 不要做

1. 不要修改 Python 代码。
2. 不要调整现有配置 key 名称。

### 测试

- 无 Python 单测
- 只做人工检查：字段名是否与 `PluginConfig` 一致

### 完成定义

- `PluginConfig` 和 `_conf_schema.json` 字段完全一致

---

## T03 时间工具和行为枚举

### 目标

补齐懒重置和新任务统计要用的时间工具、Action 枚举。

### 前置

- T01

### 只允许修改

- `app/utils/time.py`
- `app/models/enums.py`
- `tests/test_utils.py`
- `tests/test_models.py`

### 必须实现

`time.py` 新增：

- `get_week_key(tz)`
- `get_month_key(tz)`
- `is_next_day(prev_date, today)`
- `hours_between(ts1, ts2)`

`Action` 新增：

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

### 不要做

1. 不要修改 quest / leaderboard / ownership 逻辑。
2. 不要引入新的时间库。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_utils.py tests/test_models.py
```

### 完成定义

- 时间 helper 可用
- 新 Action 被 `ActivityLog.empty_day()` 自动覆盖

---

## T04 扩展 UserProfile

### 目标

把 Phase 4 用到的用户态字段和 inventory key 先补齐。

### 前置

- T03

### 只允许修改

- `app/models/profile.py`
- `tests/test_models.py`

### 必须实现

新增字段：

- `registered_at`
- `pk_score`
- `pk_score_season`
- `pk_last_active_date`
- `evil_points`
- `evil_points_month`
- `titles`
- `active_title`
- `work_streak`
- `work_last_settle_date`
- `work_week_key`
- `work_week_income`
- `work_contract_reserved`
- `work_partner_uid`
- `work_partner_date`
- `weekly_box_claimed_week`
- `first_ntr_lost_done`
- `newbie_guide_claimed`

inventory 默认 key 新增：

- `revenge_token`
- `insurance_card`

### 不要做

1. 不要改 Store。
2. 不要实现 title / work / NTR 逻辑。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_models.py
```

### 完成定义

- 旧 profile JSON 缺字段时仍能加载
- 新字段可 round-trip

---

## T05 扩展 Ownership

### 目标

给打工系统增加老婆级运行态。

### 前置

- T04

### 只允许修改

- `app/models/ownership.py`
- `tests/test_models.py`

### 必须实现

新增字段：

- `is_working`
- `work_mode`
- `work_started_at`
- `work_ends_at`

### 不要做

1. 不要写 `WorkService`。
2. 不要改 `OwnershipService`。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_models.py
```

### 完成定义

- 旧 ownership JSON 兼容
- 新字段可 round-trip

---

## T06 ProfileStore 创建逻辑补 registered_at

### 目标

确保新用户建档时自动带 `registered_at`。

### 前置

- T04

### 只允许修改

- `app/storage/stores.py`
- `tests/test_storage.py`

### 必须实现

1. `ProfileStore.get_or_create()` 新建档案时写 `registered_at`。
2. 老档案不补写历史注册时间，仍保持 `0`。

### 不要做

1. 不要改 `UserProfile.from_dict()` 以外的模型逻辑。
2. 不要顺手改别的 Store。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_storage.py tests/test_models.py
```

### 完成定义

- 新建档案有 `registered_at`
- 老档案保持兼容语义

---

## T07 重复抽卡补偿改配置驱动

### 目标

去掉 `rarity_service.py` 里写死的重复补偿常量。

### 前置

- T01

### 只允许修改

- `app/services/rarity_service.py`
- `tests/test_rarity_service.py`

### 必须实现

1. 删除硬编码 `DUPLICATE_COIN_COMPENSATION = 10` 的行为依赖。
2. 按 `config.duplicate_coin_compensation[rarity]` 发币。
3. 缺失 key 时回退到安全默认值，不抛异常。

### 不要做

1. 不要改 `OwnershipService.draw_or_get_primary()`。
2. 不要动抽卡概率逻辑。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_rarity_service.py
```

### 完成定义

- N/R/SR/SSR 重复补偿分别正确

---

## T10 连续签到

### 目标

把签到从固定奖励改成连续奖励。

### 前置

- T01
- T03
- T04

### 只允许修改

- `app/services/economy_service.py`
- `tests/test_economy_service.py`

### 必须实现

1. 连签判断只看 `last_checkin_date`。
2. 隔天签：`streak_days += 1`。
3. 断签：`streak_days = 1`。
4. 第 3 天额外加 `checkin_streak_3day_bonus`。
5. 第 7 天额外加 `checkin_streak_7day_bonus` 并发 `checkin_streak_7day_item`。
6. 活动日志写 `Action.CHECKIN`。

### 不要做

1. 不要做周宝箱。
2. 不要改命令层文案格式以外的逻辑。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_economy_service.py
```

### 完成定义

- 连签、断签、第 3 天、第 7 天行为正确

---

## T11 亲密度等级工具改 5 档

### 目标

把当前 10 级线性显示改成策划案的 5 档业务等级。

### 前置

- T01

### 只允许修改

- `app/services/ownership_service.py`
- `tests/test_intimacy.py`

### 必须实现

新增 helper：

- `get_intimacy_level_no()`
- `get_intimacy_level_name()`
- `get_intimacy_bonus_ratio()`
- `has_intimacy_shield()`

等级规则：

- 0-19
- 20-39
- 40-59
- 60-79
- 80-100

### 不要做

1. 不要改命令注册。
2. 不要接入升级奖励。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_intimacy.py
```

### 完成定义

- 等级区间和护盾判断正确

---

## T12 摸头/送礼接升级奖励和行为日志

### 目标

让现有亲密互动具备等级奖励和统一互动统计。

### 前置

- T11

### 只允许修改

- `app/services/ownership_service.py`
- `tests/test_intimacy.py`

### 必须实现

1. `pet_wife()` / `gift_wife()` 提升后检测是否跨级。
2. 按 `intimacy_levelup_rewards` 发放奖励。
3. 奖励只按本次跨级发一次，不可重复刷。
4. 摸头/送礼都写 `Action.INTIMACY`。

### 不要做

1. 不要改 command 文案结构。
2. 不要实现对话和约会。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_intimacy.py
```

### 完成定义

- 升级奖励能发
- 重复同级不重复发

---

## T13 对话/约会 service 方法

### 目标

在 `OwnershipService` 内加 `chat_wife()` 和 `date_wife()`。

### 前置

- T01
- T03
- T11

### 只允许修改

- `app/services/ownership_service.py`
- `tests/test_intimacy.py`

### 必须实现

1. `chat_wife()`：2h 冷却，`+1 intimacy`，`+5 coins`。
2. `date_wife()`：12h 冷却，花 10 币，`+8 intimacy`。
3. 两者都写 `Action.INTIMACY`。
4. `chat_wife()` 额外写 `Action.CHAT`。
5. `date_wife()` 额外写 `Action.DATE`。

### 不要做

1. 不要新建 `InteractService`。
2. 不要改 command 注册。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_intimacy.py
```

### 完成定义

- 冷却、收益、扣费、日志都正确

---

## T14 对话/约会命令接线

### 目标

把 `老婆 对话` 和 `老婆 约会` 接到命令系统。

### 前置

- T13

### 只允许修改

- `app/commands/intimacy.py`
- `app/commands/registration.py`
- `app/commands/admin.py`
- `tests/test_commands_registry.py`

### 必须实现

1. 新增 `handle_chat()`。
2. 新增 `handle_date()`。
3. 在 `registration.py` 注册 `老婆 对话` / `老婆 约会`。
4. 帮助文本同步更新。

### 不要做

1. 不要改 PK / NTR / Economy 命令。
2. 不要做打工命令。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_commands_registry.py
```

### 完成定义

- 两个新命令可被解析

---

## T20 NTR 概率流水线骨架

### 目标

先把 `try_ntr()` 改成可读的概率流水线，不先落补偿细节。

### 前置

- T01
- T11

### 只允许修改

- `app/services/ownership_service.py`
- `tests/test_ownership_service.py`

### 必须实现

1. 给 `NtrResult` 增加 `final_probability`。
2. 把概率计算拆成独立变量：
 - base
 - intimacy shield
 - charm
 - lock
 - revenge
 - streak penalty
 - newbie
 - work
3. 逻辑暂时可以先只接通已存在项，缺的倍率先留 TODO 占位变量，但结构必须成型。

### 不要做

1. 不要在这张票里改所有权转移语义。
2. 不要实现复仇令牌。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_ownership_service.py tests/test_revenge.py
```

### 完成定义

- `try_ntr()` 的概率结构可读
- 结果对象里能看到最终概率

---

## T21 NTR 降级补偿和新手保护

### 目标

把“被牛亲密度归零”改成“保留 + 币补偿 + 新手保护”。

### 前置

- T20

### 只允许修改

- `app/services/ownership_service.py`
- `tests/test_ownership_service.py`

### 必须实现

1. 被牛成功后：普通玩家保留 50%，新手保留 75%。
2. 补偿币 = `lost_intimacy * per_intimacy`，封顶 `max`。
3. 新手 Day1 免疫 NTR。
4. `registered_at == 0` 视为老玩家，不进新手保护。
5. 攻击者 NTR 成功后不再删除自己的旧主老婆，只切主老婆。

### 不要做

1. 不要实现复仇令牌消耗。
2. 不要做 evil points。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_ownership_service.py
```

### 完成定义

- NTR 成功后的亲密度和补偿逻辑正确
- 新手 Day1 免疫正确
- 攻击者保留旧老婆正确

---

## T22 保护符自动触发和首次被牛安抚

### 目标

接入 `protection_charm` 自动触发，顺手把首次被牛安抚也补上。

### 前置

- T21

### 只允许修改

- `app/services/ownership_service.py`
- `tests/test_ownership_service.py`
- `tests/test_shop_service.py`

### 必须实现

1. 目标背包有 `protection_charm` 时，本次 NTR 概率乘 `0.3`。
2. 本次结算后消耗 1 个保护符。
3. 玩家首次被牛时：
 - `revenge_token` 额外 +1
 - `first_ntr_lost_done = True`
4. `last_ntr_by` 结构扩展保存：
 - `uid`
 - `ts`
 - `wid`
 - `lost_intimacy`

### 不要做

1. 不要更新 revenge 命令。
2. 不要做 evil points。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_ownership_service.py tests/test_shop_service.py
```

### 完成定义

- 保护符能自动扣减
- `last_ntr_by` 数据足够后续复仇恢复使用

---

## T23 复仇令牌和复仇命令重构

### 目标

把 `老婆 复仇` 补成完整链路。

### 前置

- T22

### 只允许修改

- `app/services/ownership_service.py`
- `app/commands/revenge.py`
- `tests/test_revenge.py`

### 必须实现

1. 被牛后给 `revenge_token`。
2. 复仇时优先消耗 1 个令牌。
3. 有令牌时额外叠 `revenge_token_bonus`。
4. 失败给安慰币。
5. 成功后按 `lost_intimacy * revenge_success_intimacy_restore` 恢复亲密度。
6. 无论成败都清空 `last_ntr_by`。

### 不要做

1. 不要在这张票里改 NTR 普通命令文案。
2. 不要做 evil points。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_revenge.py tests/test_ownership_service.py
```

### 完成定义

- 复仇成功率、令牌消耗、安慰奖、亲密度恢复都正确

---

## T24 作恶值和危险用户展示

### 目标

给 NTR 成功者增加作恶值，并在查询展示层提示。

### 前置

- T21

### 只允许修改

- `app/services/ownership_service.py`
- `app/commands/view.py`
- `app/commands/panel.py`
- `tests/test_ownership_service.py`

### 必须实现

1. NTR 成功 `evil_points += 1`。
2. 按自然月懒重置。
3. 达到 3 时在查看/面板展示危险提示。
4. 达到 5 时受害者补偿翻倍。

### 不要做

1. 不要接排行榜。
2. 不要做全群播报优化。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_ownership_service.py
```

### 完成定义

- evil points 累加与月重置正确
- 展示层能看出危险用户

---

## T30 新建 WorkService 启动流程

### 目标

先实现打工开始，不处理懒结算。

### 前置

- T01
- T05

### 只允许修改

- `app/services/work_service.py`
- `tests/test_work_service.py`

### 必须实现

1. 新建 `WorkService`。
2. 实现 `start_work()`。
3. 检查：有主老婆、余额足够、未在打工、模式合法。
4. 扣启动费。
5. 写 `is_working/work_mode/work_started_at/work_ends_at`。
6. profile 侧写 `Action.WORK_START`。

### 不要做

1. 不要接命令层。
2. 不要写 resolve 逻辑。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_work_service.py
```

### 完成定义

- 能开始打工
- 状态和扣费正确

---

## T31 WorkService 结算流程

### 目标

补齐正常完成和被截胡结算。

### 前置

- T30

### 只允许修改

- `app/services/work_service.py`
- `tests/test_work_service.py`

### 必须实现

1. `resolve_due_work()`：
 - 时间到后结算收益
 - 增加亲密度
 - 更新 `work_streak`
 - 更新 `work_week_income`
 - 写 `Action.WORK_COMPLETE`
2. `resolve_stolen_work()`：
 - 打工中被牛时，收益给攻击者
 - 清空原状态
 - 写 `Action.WORK_STOLEN`
3. `clear_work_state()` 独立封装。

### 不要做

1. 不要接命令。
2. 不要接 NTR/PK。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_work_service.py
```

### 完成定义

- 正常完成和被截胡两条结算链都正确

---

## T32 打工命令接线

### 目标

让玩家可以发起三种打工命令。

### 前置

- T30

### 只允许修改

- `app/commands/work.py`
- `app/commands/registration.py`
- `app/commands/admin.py`
- `tests/test_commands_registry.py`

### 必须实现

1. 新建 `handle_work()`。
2. 支持：
 - `老婆 打工`
 - `老婆 打工 加班`
 - `老婆 打工 远征`
3. 注册到 command registry。
4. 帮助文本更新。

### 不要做

1. 不要实现合约和搭档。
2. 不要做懒结算。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_commands_registry.py
```

### 完成定义

- 打工命令能解析到 handler

---

## T33 打工懒结算接入命令入口

### 目标

在常用命令入口前先结算已到时的打工。

### 前置

- T31
- T32

### 只允许修改

- `app/commands/work.py`
- `app/commands/view.py`
- `app/commands/panel.py`
- `app/commands/pk.py`
- `app/commands/ntr.py`
- `app/commands/revenge.py`
- `tests/test_work_service.py`

### 必须实现

1. 在上述命令进入主逻辑前，先调用一次 `resolve_due_work()`。
2. 若有结算结果，先发送结算消息，再继续原命令。

### 不要做

1. 不要改 service 层打工结算规则。
2. 不要做排行榜。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_work_service.py
```

### 完成定义

- 打工到时后，不需要单独定时器也能结算

---

## T34 打工接入 NTR 和 PK

### 目标

把打工风险真实写进对抗系统。

### 前置

- T31

### 只允许修改

- `app/services/work_service.py`
- `app/services/ownership_service.py`
- `app/services/pk_service.py`
- `tests/test_work_service.py`
- `tests/test_pk_service.py`
- `tests/test_ownership_service.py`

### 必须实现

1. `try_ntr()` 读取打工中的倍率加成。
2. NTR 成功且目标在打工中时，调用 `resolve_stolen_work()`。
3. `_calc_power()` 读取打工惩罚。

### 不要做

1. 不要重写整套 PK 公式。
2. 不要接排行榜。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_work_service.py tests/test_pk_service.py tests/test_ownership_service.py
```

### 完成定义

- 打工确实提高被牛概率，并降低 PK 战力

---

## T40 PK 公式重构

### 目标

把 PK 从“纯比大小”改成“属性 + 亲密 + 羁绊 + 打工 + 称号”。

### 前置

- T11
- T34

### 只允许修改

- `app/services/pk_service.py`
- `app/services/ownership_service.py`
- `tests/test_pk_service.py`

### 必须实现

1. `_calc_power()` 改成：
 - base `atk + def + hp*0.5`
 - intimacy bonus `1 + intimacy/500`
 - bond bonus
 - work penalty
 - element modifier
 - title modifier
2. 元素类型不要持久化，实时推导。
3. `OwnershipService` 新增 `get_bond_bonus()`。

### 不要做

1. 不要做积分/段位。
2. 不要做防刷持久化。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_pk_service.py
```

### 完成定义

- 新战力公式可用
- 元素克制和羁绊加成正确

---

## T41 PK 对手防刷持久化

### 目标

加 `PkPairStore` 和 `pk_pairs.json`，实现同对手 24h 防刷。

### 前置

- T40

### 只允许修改

- `app/storage/paths.py`
- `app/storage/stores.py`
- `app/services/pk_service.py`
- `tests/test_storage.py`
- `tests/test_pk_service.py`

### 必须实现

1. `paths.py` 增加 `group_pk_pairs_file(gid)`。
2. `stores.py` 新增轻量 `PkPairStore`。
3. `pk_service.py` 接入 24h 同对手限制。

### 不要做

1. 不要在 `CooldownService` 里硬塞这个逻辑。
2. 不要改命令层文案细节。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_storage.py tests/test_pk_service.py
```

### 完成定义

- `pk_pairs.json` 能持久化
- 同对手 24h 重复 PK 被拒绝

---

## T42 PK 结算、积分、段位

### 目标

补齐胜负平奖励、积分、段位和新手败方翻倍。

### 前置

- T41

### 只允许修改

- `app/services/pk_service.py`
- `tests/test_pk_service.py`

### 必须实现

1. 胜方奖励：币 + 分。
2. 败方奖励：近战力差给 5 币/1 分，否则安慰 1 币/0 分。
3. 平局奖励：双方 8 币/2 分。
4. 新手 Day1 败方奖励翻倍。
5. `pk_score` / `pk_score_season` / `pk_last_active_date` 按月懒重置。
6. 提供段位 helper。

### 不要做

1. 不要做赛季结算发奖。
2. 不要改 leaderboard。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_pk_service.py
```

### 完成定义

- 胜负平奖励正确
- 积分和段位正确

---

## T43 PK 命令战报重构

### 目标

让 `老婆 PK` 输出可读战报。

### 前置

- T42

### 只允许修改

- `app/commands/pk.py`

### 必须实现

战报至少显示：

- 双方老婆名
- 双方元素
- 双方最终战力
- 是否存在克制
- 胜/负/平
- 双方币变化
- 双方积分变化
- 当前段位

### 不要做

1. 不要改 `PkService`。
2. 不要做排行榜。

### 测试

- 无新增单测硬要求
- 至少跑现有 PK service 测试确保不被文案改坏

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_pk_service.py
```

### 完成定义

- PK 输出信息完整

---

## T50 重写 QuestService

### 目标

把任务改成“新手引导 + 标准每日任务”双模式。

### 前置

- T14
- T33
- T42

### 只允许修改

- `app/services/quest_service.py`
- `tests/test_quest_service.py`

### 必须实现

1. 新手任务：
 - `day1_draw_once`
 - `day2_pet_and_chat`
 - `day3_pk_once`
2. 标准任务：
 - 抽老婆 1 次
 - 亲密互动 2 次
 - PK 1 次
 - 打工 1 次
3. “亲密互动”通过 `Action.INTIMACY` 统计。
4. “PK 1 次”通过 `PK_WIN/PK_LOST/PK_TIE` 求和统计。
5. 完成新手任务后，切到标准任务。

### 不要做

1. 不要改命令层文案太多。
2. 不要做周宝箱。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_quest_service.py
```

### 完成定义

- 新手任务和标准任务都能正确判断

---

## T51 扩展 LeaderboardService

### 目标

给榜单层加 PK 分、亲密度、恶人值、打工收入、打工连续天数。

### 前置

- T24
- T31
- T42

### 只允许修改

- `app/services/leaderboard_service.py`
- `tests/test_leaderboard_service.py`

### 必须实现

新增方法：

- `rank_pk_score()`
- `rank_primary_intimacy()`
- `rank_evil_points()`
- `rank_work_week_income()`
- `rank_work_streak()`

### 不要做

1. 不要改 command 解析。
2. 不要做跨群榜。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_leaderboard_service.py
```

### 完成定义

- 新榜单聚合结果正确

---

## T52 扩展排行榜命令

### 目标

让 `老婆 排行` 能看新榜单。

### 前置

- T51

### 只允许修改

- `app/commands/leaderboard.py`
- `app/commands/admin.py`

### 必须实现

新增关键词：

- `段位`
- `亲密`
- `恶人`
- `打工收入`
- `打工连续`

无参数时默认输出：

- 段位榜
- 亲密榜
- 恶人榜
- 打工收入榜

### 不要做

1. 不要改 service 聚合逻辑。
2. 不要顺手改 collection 榜逻辑。

### 测试

- 无硬性新单测
- 至少回归 `leaderboard_service` 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_leaderboard_service.py
```

### 完成定义

- 新榜单命令能用

---

## T53 面板/查看/称号展示

### 目标

把前面新增的长期进度都展示出来。

### 前置

- T24
- T31
- T42
- T51

### 只允许修改

- `app/commands/panel.py`
- `app/commands/view.py`
- `app/services/ownership_service.py`
- `tests/test_models.py`

### 必须实现

1. 展示当前称号。
2. 展示 PK 分数和段位。
3. 展示主老婆亲密度等级名。
4. 展示打工状态。
5. 展示复仇令牌数量。
6. 展示作恶值。
7. 在合适的 service 位置加轻量 title helper。

### 不要做

1. 不要单独新建 `TitleService`。
2. 不要做称号发奖以外的复杂被动系统。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_models.py
```

### 完成定义

- 用户看 `查老婆/面板` 能感知长期成长线

---

## T60 第二波：打工合约

### 目标

在不影响首发闭环的前提下加合约。

### 前置

- T31 全绿

### 只允许修改

- `app/services/work_service.py`
- `app/commands/work.py`
- `tests/test_work_service.py`

### 必须实现

1. 支持预约下次打工合约。
2. 下一次打工成功收益 `x1.5`。
3. 打工中被牛则合约作废。

### 不要做

1. 不要做搭档。
2. 不要改 PK/NTR 主逻辑。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_work_service.py
```

### 完成定义

- 合约只影响下一次打工

---

## T61 第二波：打工搭档

### 目标

增加轻量协作玩法。

### 前置

- T31 全绿

### 只允许修改

- `app/services/work_service.py`
- `app/commands/work.py`
- `tests/test_work_service.py`

### 必须实现

1. 每日限一次搭档。
2. 双方同时打工时加收益。
3. 任一方被牛，搭档关系解除。

### 不要做

1. 不要改任务系统。
2. 不要改排行榜。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_work_service.py
```

### 完成定义

- 搭档加成和失效都正确

---

## T62 第二波：每周惊喜宝箱

### 目标

加懒触发周宝箱。

### 前置

- T10
- T50

### 只允许修改

- `app/services/economy_service.py`
- `app/commands/economy.py`
- `app/commands/panel.py`
- `tests/test_economy_service.py`

### 必须实现

1. 用周 key 判断是否已领取。
2. 用 `Action.CHECKIN` 判断本周签到天数。
3. 通过 `签到/任务/面板` 懒触发发奖。

### 不要做

1. 不要加定时推送。
2. 不要改 WorkService。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_economy_service.py tests/test_quest_service.py
```

### 完成定义

- 周宝箱能懒领取且不会重复领

---

## T63 第二波：商城提示清理和可选扩展

### 目标

收尾非核心商城问题，避免误导文案。

### 前置

- T23
- T53

### 只允许修改

- `app/services/shop_service.py`
- `app/commands/economy.py`
- `tests/test_shop_service.py`

### 必须实现

1. `revenge_token` 不可购买。
2. `protection_charm` 保持购买上限。
3. `老婆 商城` 去掉未实现的 `老婆 使用 <道具名>` 提示。

### 不要做

1. 不要在这张票里实现完整道具赠送。
2. 不要实现 insurance card 真正效果。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest tests/test_shop_service.py
```

### 完成定义

- 商城提示不再误导

---

## T99 全量回归和文档同步

### 目标

所有 Phase 4 第一波完成后，统一回归并更新文档。

### 前置

- T53

### 只允许修改

- `README.md`
- `CHANGELOG.md`
- `ROADMAP_PHASE4_DETAILED.md`

### 必须实现

1. 跑全量测试。
2. 手工 QA 跑一遍：
 - `老婆 签到`
 - `抽老婆`
 - `老婆 对话`
 - `老婆 约会`
 - `老婆 打工`
 - `老婆 PK @某人`
 - `牛老婆 @某人`
 - `老婆 复仇 @某人`
 - `老婆 排行`
 - `老婆 面板`
3. 更新 README/CHANGELOG 的 Phase 4 完成说明。

### 不要做

1. 不要再加新功能。
2. 不要顺手重构老代码。

### 测试

```powershell
$env:PYTHONPATH='.'; python -m pytest
```

### 完成定义

- 第一波功能全绿
- 文档已同步

---

## 推荐执行顺序摘要

只看顺序时，用这一条：

`T00 -> T01 -> T02 -> T03 -> T04 -> T05 -> T06 -> T07 -> T10 -> T11 -> T12 -> T13 -> T14 -> T20 -> T21 -> T22 -> T23 -> T24 -> T30 -> T31 -> T32 -> T33 -> T34 -> T40 -> T41 -> T42 -> T43 -> T50 -> T51 -> T52 -> T53 -> T99`

第二波功能只在第一波全绿后再开：

`T60 -> T61 -> T62 -> T63`
