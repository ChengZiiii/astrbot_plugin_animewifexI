![:name](https://count.getloli.com/@astrbot_plugin_animewifexI?name=astrbot_plugin_animewifexI&theme=capoo-2&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_animewifexI

> ✅ **Phase 4 玩法已落地**
>
> 当前版本已包含：连续签到、对话/约会、NTR 失败/被牛补偿、打工系统、PK/排行榜扩展、图鉴/面板、管理员测试与重置工具。
> 规划与实现细节见 [ROADMAP.md](ROADMAP.md)、[ROADMAP_PHASE4_DETAILED.md](ROADMAP_PHASE4_DETAILED.md) 与 [CHANGELOG.md](CHANGELOG.md)。
>
> **升级注意（Phase 1 不兼容变更）**：
> - 旧 v2.x 数据启动时自动归档到 `data/archive_v1/<时间戳>/`，**不做语义迁移**。
> - 老用户首次启动后按新结构空数据起步，可通过 `initial_coins` 配置发放老婆币补偿。

本仓库是 [astrbot_plugin_animewifex](https://github.com/monbed/astrbot_plugin_animewifex)（原 [zgojin/astrbot_plugin_AW](https://github.com/zgojin/astrbot_plugin_AW)）的 fork，主要变更：

- 模块化分层重构（`app/` 下分 `models` / `storage` / `services` / `commands` / `api` / `utils`）
- 数据结构升级支持多老婆持有（Phase 1 就绪，Phase 3 UI 开放）
- 40+ 配置项 WebUI 可调（含亲密度、经济、稀有度、商城等）
- 冷却参数化：NTR/抽老婆/交换请求各自独立冷却
- 排行榜：日榜/周榜/总榜/收集榜
- 亲密度：摸头/送礼/每日递增/等级展示
- 复仇机制：被牛后 24 小时内复仇，成功率翻倍
- 完整单元测试覆盖（338 用例，脱离 AstrBot 框架本地可跑）
- 命令级 QA 脚本已补齐全量与深度验证（`data_qa/`）
- 路线图驱动开发：Phase 1 ✅ / Phase 2 ✅ / Phase 3 ✅ / Phase 4 ✅（详见 [ROADMAP.md](ROADMAP.md)）

**本插件代码为 AI 生成，下面图床的也是。**

配套图床（沿用上游）：https://github.com/monbed/wife

从 GitHub 获取：

如果你的 BOT 能够正常访问 GitHub 获取图片

图片服务器基础 URL 填写：https://raw.githubusercontent.com/monbed/wife/main/

图片列表 URL 填写：https://animewife.dpdns.org/list.txt

或者使用可以直连的反代（自行测试网络问题）如：

https://fastly.jsdelivr.net/gh/monbed/wife@main/

https://cdn.jsdmirror.com/gh/monbed/wife@main/

图片列表同上

也可以手动下载图片，放入 AstrBot `data/plugin_data/astrbot_plugin_animewifexI/img/wife` 目录。

## 重构进度（v3.x）

| Phase | 范围 | 状态 | Tag |
|---|---|---|---|
| Phase 1 | 模块化 + 归档 + 双轨命令 | ✅ 已完成 | `v3.0.0-phase1` |
| Phase 2 | 冷却 + 榜单 + 亲密度 + 复仇 | ✅ 已完成 | `v3.0.0-phase2` |
| Phase 3 | 经济 + 稀有度 + 锁定 + PK + 图鉴 + 面板 | ✅ 已完成 | `v3.0.0-phase3-gacha` |
| Phase 4 | 连签 + 对话/约会 + 打工 + NTR补偿 + 排行扩展 | ✅ 已完成 | `v3.0.0-phase4` |

详见 [ROADMAP.md](ROADMAP.md)。

## 本地开发与测试

本插件支持脱离 AstrBot 框架在源码目录直接跑单元测试（不污染 AstrBot 运行环境）：

```bash
# 安装测试依赖
pip install pytest pytest-asyncio tzdata

# 跑全部测试（338 用例）
PYTHONPATH=. python -m pytest
```

测试覆盖：

- `tests/test_storage.py`：JSON 原子写、群锁、路径校验
- `tests/test_models.py`：dataclass 往返 + 跨版本兼容
- `tests/test_utils.py`：时间/图片/随机/格式化纯函数
- `tests/test_ownership_service.py`：抽老婆/牛老婆/换老婆/交换/重置/清理完整流程
- `tests/test_migrations.py`：v2.x → v3.x 归档
- `tests/test_commands_registry.py`：双轨命令解析
- `tests/test_plugin.py`：插件装配 + 启动归档
- `tests/test_cooldown_service.py`：冷却检查/更新/剩余/重置
- `tests/test_leaderboard_service.py`：日榜/周榜/总榜/收集榜聚合
- `tests/test_revenge.py`：复仇窗口/清空/错误目标/亲密度归零
- `tests/test_intimacy.py`：摸头/送礼/每日递增/幂等/等级计算
- `tests/test_economy_service.py`：余额/收支/签到
- `tests/test_quest_service.py`：每日任务完成/进度/防重领
- `tests/test_shop_service.py`：商城/购买/使用/背包/持有上限
- `tests/test_work_service.py`：打工启动/结算/连工/模式差异
- `data_qa/qa_full_test.py`：全量命令级 QA（86/86）
- `data_qa/qa_deep_test.py`：复杂状态与回归 QA（17/17）

AstrBot 运行环境的 QA 也已在真实实例中验证；本地 QA 产物统一放在 `data_qa/`，不会污染插件主目录与同步目录。

## 指令

### 旧扁平命令（v2.x 兼容）

- `老婆帮助` 显示所有命令帮助
- `抽老婆` 抽取新老婆（每日1次免费，之后消耗单抽券）
- `查老婆` 查看老婆列表；加 `@用户` 可查看别人，支持页码与部分昵称匹配
- `牛老婆 [@用户] [编号]` 概率牛别人老婆；可指定目标第 N 个老婆
- `重置牛 [@用户]` 重置牛老婆次数，失败会禁言；管理员不受限制
- `切换ntr开关状态` / `切换NTR开关状态` 管理员命令，开启/关闭牛老婆功能
- `换老婆` 重新抽取老婆
- `重置换 [@用户]` 重置换老婆次数，其余同重置牛
- `交换老婆 @用户` 和对方交换老婆
- `同意交换 @用户` / `拒绝交换 @用户` 处理交换请求
- `查看交换请求` 查看当前交换请求

### 分组命令（当前可用）

- `老婆 帮助` — 显示帮助
- `老婆 十连` — 十连抽卡（消耗十连券，9 折）
- `老婆 排行 [日|周|总] [牛|被牛|PK|收集]` — 查看排行榜（日榜/周榜/总榜/收集榜）
- `老婆 复仇 @用户` — 对最近牛走你老婆的人发起复仇（24 小时内有效，成功率翻倍）
- `老婆 摸头` — 消耗 5 币增加 3 亲密度
- `老婆 送礼` — 消耗 30 币增加 20 亲密度
- `老婆 签到` — 每日领取老婆币
- `老婆 任务` — 查看每日任务进度，完成后自动领取奖励
- `老婆 商城` — 查看可购买道具（换老婆券 / 锁定卡 / 复活药水 / 保护符 / 单抽券 / 十连券）
- `老婆 购买 <道具> [数量]` — 购买道具，支持中文名或内部键名
- `老婆 背包` — 查看已持有道具
- `老婆 锁定 <编号>` — 限期锁定老婆 7 天（消耗锁定卡）
- `老婆 解锁 <编号>` — 解锁老婆
- `老婆 切换 <编号>` — 将指定编号的老婆设为主老婆
- `老婆 PK @某人 [我方编号] [对方编号]` — 老婆 PK 对战；不写编号默认双方主老婆
- `老婆 图鉴` — 查看收集进度（按稀有度统计）
- `老婆 面板` — 查看个人面板（持有老婆/统计/币）
- `老婆 对话` — 2 小时冷却，+1 亲密度并获得老婆币
- `老婆 约会` — 12 小时冷却，消耗老婆币换取更高亲密度
- `老婆 打工 [编号] [加班|远征]` — 指定 1 位老婆打工；不写编号默认主老婆，再次发送会自动尝试结算

> 💡 老婆编号以 `查老婆` / `老婆 面板` 中显示的序号为准；`老婆 打工` 每次只会派出 1 位老婆，不会随机或全体出动。

### 当前仍为占位的分组命令

- `老婆 列表`
- `老婆 查`

以上命令当前仍返回“未开放”提示。

### 管理员专属指令

以下指令需要在 `admins` 配置中添加对应 QQ 号才可使用：

- `切换ntr开关状态` — 开启/关闭牛老婆功能
- `老婆 重置本群` — 清空本群所有老婆数据（慎用！）
- `老婆 重置抽卡 [@某人]` — 重置目标的今日抽卡状态并清理抽卡冷却（可重新抽老婆）
- `老婆 测试抽卡 [次数]` — 模拟抽卡测试概率分布（不写入数据，用于验证稀有度/保底机制）
- `老婆 测试亲密度 @某人 <数值>` — 设置目标亲密度
- `老婆 测试币 @某人 <数值>` — 设置目标老婆币余额

> 💡 测试抽卡示例：`老婆 测试抽卡 1000` 可查看 SSR/SR/R/N 概率分布、保底触发次数、最大连续非 SR 次数等统计数据。

更新日志见 [CHANGELOG.md](CHANGELOG.md)

## 相关

- 上游 fork：[astrbot_plugin_animewifex](https://github.com/monbed/astrbot_plugin_animewifex)（原 [zgojin/astrbot_plugin_AW](https://github.com/zgojin/astrbot_plugin_AW)）
- [Astrbot](https://astrbot.app/)
