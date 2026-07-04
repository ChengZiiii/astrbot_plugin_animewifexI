# Phase 4 T01-T10 QA 测试用例

测试环境：AstrBot 实例，群聊中发送命令

---

## 变更范围

| 票号 | 变更内容 | 可测命令 |
|------|----------|----------|
| T01 | PluginConfig 新增 40+ Phase 4 配置字段 | 无（底层配置） |
| T02 | _conf_schema.json 与 PluginConfig 对齐 | WebUI 配置页面 |
| T03 | 时间工具 + Action 枚举扩展 | 无（底层工具） |
| T04 | UserProfile 新增 18 个字段 + inventory 新 key | 无（底层模型） |
| T05 | Ownership 新增打工状态字段 | 无（底层模型） |
| T06 | 新建档案自动写 registered_at | 无（底层逻辑） |
| T07 | 重复抽卡补偿改配置驱动 | `抽老婆` |
| T10 | 连续签到奖励 | `老婆 签到` |

---

## 快速 QA 流程

### 第 1 步：准备

```
老婆 重置本群
```

清空所有数据，开始干净测试。

### 第 2 步：测试新用户注册（T06 验证）

```
抽老婆
```

确认：新用户首次操作时自动建档，`registered_at` 为当前时间戳（可在 profiles.json 中查看）。

### 第 3 步：测试连续签到（T10 验证）

**Day 1 签到：**
```
老婆 签到
```
确认：
- 签到成功，获得 20 币（daily_checkin_coins 默认值）
- 连续天数显示 1 天

**Day 2 签到（需跨天或重置）：**
```
老婆 重置抽卡
老婆 签到
```
确认：
- 签到成功，获得 20 币
- 连续天数显示 2 天

**Day 3 签到（连续第 3 天）：**
```
老婆 签到
```
确认：
- 签到成功，获得 20 + 30 = 50 币（含第 3 天额外奖励）
- 提示"连续签到 3 天额外奖励"

**Day 7 签到（连续第 7 天）：**
```
老婆 签到
```
确认：
- 签到成功，获得 20 + 100 = 120 币（含第 7 天额外奖励）
- 获得道具"单抽券"
- 提示"连续签到 7 天额外奖励"
- 连续天数重置为 0

**断签测试：**
```
（隔 2 天不签到）
老婆 签到
```
确认：
- 签到成功，获得 20 币
- 连续天数重置为 1（断签后重新计算）

### 第 4 步：测试重复抽卡补偿（T07 验证）

```
老婆 测试抽卡 100
```

确认：
- N 重复补偿：5 币
- R 重复补偿：10 币
- SR 重复补偿：20 币
- SSR 重复补偿：50 币

（补偿值可在 `_conf_schema.json` → `duplicate_coin_compensation` 中配置）

### 第 5 步：测试 WebUI 配置（T02 验证）

打开 AstrBot WebUI → 插件配置 → animewifexI

确认新增配置项可见：
- 连续签到相关：`checkin_streak_3day_bonus`, `checkin_streak_7day_bonus`, `checkin_streak_7day_item`
- 对话/约会相关：`chat_cooldown`, `chat_intimacy_gain`, `date_cooldown` 等
- NTR 补偿相关：`ntr_intimacy_retain_ratio`, `ntr_coin_compensation_per_intimacy` 等
- 打工系统相关：`work_enabled`, `work_modes`, `work_streak_bonus` 等
- PK 增强相关：`pk_loser_reward`, `pk_score_per_win`, `pk_element_advantage` 等
- 重复补偿配置：`duplicate_coin_compensation`

---

## 验收清单

### T01 PluginConfig 扩展
- [ ] `PluginConfig.default_for_test()` 可正常构造
- [ ] `PluginConfig.from_dict({})` 可正常解析（缺失字段用默认值）

### T02 配置 Schema
- [ ] WebUI 配置页显示所有新增字段
- [ ] 字段名与 PluginConfig 完全一致

### T03 时间工具 + 枚举
- [ ] `get_week_key()` 返回 YYYY-WW 格式
- [ ] `get_month_key()` 返回 YYYY-MM 格式
- [ ] `is_next_day()` 正确判断相邻日期
- [ ] `hours_between()` 正确计算小时差
- [ ] Action 枚举包含 CHECKIN, INTIMACY, CHAT, DATE, PK_TIE, WORK_START, WORK_COMPLETE, WORK_STOLEN

### T04 UserProfile 扩展
- [ ] 旧 profile JSON 缺字段时可正常加载（向后兼容）
- [ ] 新字段 registered_at, pk_score, evil_points, titles 等可正常读写
- [ ] inventory 默认包含 revenge_token 和 insurance_card

### T05 Ownership 扩展
- [ ] 旧 ownership JSON 缺字段时可正常加载（向后兼容）
- [ ] 新字段 is_working, work_mode, work_started_at, work_ends_at 可正常读写

### T06 ProfileStore 注册时间
- [ ] 新建档案时 registered_at 自动写入当前时间戳
- [ ] 老档案 registered_at 保持 0（视为老玩家）

### T07 重复抽卡补偿配置驱动
- [ ] N 重复补偿：5 币
- [ ] R 重复补偿：10 币
- [ ] SR 重复补偿：20 币
- [ ] SSR 重复补偿：50 币
- [ ] 配置缺失时回退到安全默认值

### T10 连续签到
- [ ] 首日签到：20 币，连续天数 1
- [ ] 连续第 2 天：20 币，连续天数 2
- [ ] 连续第 3 天：50 币（20+30），连续天数 3
- [ ] 连续第 7 天：120 币（20+100）+ 单抽券，连续天数重置
- [ ] 断签后：连续天数重置为 1
- [ ] 签到写入活动日志 Action.CHECKIN

---

## 单元测试验证

```powershell
$env:PYTHONPATH='.'; python -m pytest
```

预期结果：286 passed

---

## 已知限制

- T10 连续签到的"第 3 天/第 7 天"奖励需要真实跨天触发，无法在同一日内测试完整流程
- T02 配置 Schema 需要在 WebUI 中人工检查字段显示

测试完成后告知结果。
