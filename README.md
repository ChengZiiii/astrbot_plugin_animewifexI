![:name](https://count.getloli.com/@astrbot_plugin_animewifexI?name=astrbot_plugin_animewifexI&theme=capoo-2&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_animewifexI

> ⚠️ **Phase 4 玩法升级开发中**
>
> Phase 4 目标：连续签到、对话/约会、NTR 降级补偿、打工系统、PK 重构、新排行榜。
> 详见 [ROADMAP_PHASE4_DETAILED.md](ROADMAP_PHASE4_DETAILED.md) 与 [PHASE4_EXECUTION_TICKETS.md](PHASE4_EXECUTION_TICKETS.md)。
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
- 完整单元测试覆盖（187 用例，脱离 AstrBot 框架本地可跑）
- 路线图驱动开发：Phase 1 ✅ / Phase 2 ✅ / Phase 3 ⏳（详见 [ROADMAP.md](ROADMAP.md)）

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
| Phase 3 | 经济 + 稀有度 + 求婚 + PK + 图鉴 | ⏳ 待开工 | `v3.0.0` |

详见 [ROADMAP.md](ROADMAP.md)。

## 本地开发与测试

本插件支持脱离 AstrBot 框架在源码目录直接跑单元测试（不污染 AstrBot 运行环境）：

```bash
# 安装测试依赖
pip install pytest pytest-asyncio tzdata

# 跑全部测试（280 用例，<4s）
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

AstrBot 运行环境的 QA 由本人在真实实例中亲自验证（参考仓库根 README 的 sync.bat 流程）。

## 指令

### 旧扁平命令（v2.x 兼容）

- `老婆帮助` 显示所有命令帮助
- `抽老婆` 抽取新老婆（每日1次免费，之后消耗单抽券）
- `十连` 十连抽卡（消耗十连券，9折优惠）
- `查老婆` 查看今日老婆；加 `@` 可查看别人老婆（支持不 `@` 昵称匹配）
- `牛老婆` `@用户` 概率牛别人老婆（支持不 `@` 昵称匹配）
- `重置牛` 重置牛老婆次数，也可 `@用户` 重置别人的次数，失败禁言；管理员不受限制
- `切换ntr开关状态` 管理员命令，开启/关闭牛老婆功能
- `换老婆` 重新抽取老婆
- `重置换` 重置换老婆次数，其余同重置牛
- `交换老婆` `@用户` 和对方交换老婆
- `同意交换` `@用户`同意
- `拒绝交换` `@用户`拒绝
- `查看交换请求` 查看交换老婆请求

### 分组命令（Phase 2 新增）

- `老婆 排行 [日|周|总] [牛|被牛|PK|收集]` — 查看排行榜（日榜/周榜/总榜/收集榜）
- `老婆 复仇 @用户` — 对最近牛走你老婆的人发起复仇（24 小时内有效，成功率翻倍）
- `老婆 摸头` — 消耗 5 币增加 3 亲密度
- `老婆 送礼` — 消耗 30 币增加 20 亲密度
- `老婆 帮助` — 显示帮助（新版入口）

### 分组命令（Phase 3 新增）

- `老婆 签到` — 每日领取老婆币
- `老婆 任务` — 查看每日任务进度 / 领取奖励
- `老婆 商城` — 查看可购买道具
- `老婆 购买 <道具> [数量]` — 购买道具
- `老婆 背包` — 查看已持有道具
- `老婆 锁定 <编号>` — 限期锁定老婆 7 天（消耗锁定卡）
- `老婆 解锁 <编号>` — 解锁老婆
- `老婆 PK @某人` — 老婆 PK 对战（胜者获 15 币 + 图鉴互通）
- `老婆 图鉴` — 查看收集进度（按稀有度统计）
- `老婆 面板` — 查看个人面板（持有老婆/统计/币）

### Phase 3 待开放

`老婆 列表` / `老婆 查` / `老婆 切换` 等，当前返回"未开放"提示。

### 管理员专属指令

以下指令需要在 `admins` 配置中添加对应 QQ 号才可使用：

- `切换ntr开关状态` — 开启/关闭牛老婆功能
- `老婆 重置本群` — 清空本群所有老婆数据（慎用！）
- `老婆 重置抽卡 [@某人]` — 重置目标的今日抽卡状态（可重新抽老婆）
- `老婆 测试抽卡 [次数]` — 模拟抽卡测试概率分布（不写入数据，用于验证稀有度/保底机制）
- `老婆 测试亲密度 @某人 <数值>` — 设置目标亲密度（方便测试求婚）
- `老婆 测试币 @某人 <数值>` — 设置目标老婆币余额

> 💡 测试抽卡示例：`老婆 测试抽卡 1000` 可查看 SSR/SR/R/N 概率分布、保底触发次数、最大连续非 SR 次数等统计数据。

更新日志见 [CHANGELOG.md](CHANGELOG.md)

## 相关

- 上游 fork：[astrbot_plugin_animewifex](https://github.com/monbed/astrbot_plugin_animewifex)（原 [zgojin/astrbot_plugin_AW](https://github.com/zgojin/astrbot_plugin_AW)）
- [Astrbot](https://astrbot.app/)
