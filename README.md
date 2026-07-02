![:name](https://count.getloli.com/@astrbot_plugin_animewifex?name=astrbot_plugin_animewifex&theme=capoo-2&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_animewifex

> ⚠️ **v3.0.0-phase1 已发布（重大重构）**
>
> 本版本对内部架构做了完整重构（模块化分层 + 多老婆数据结构就绪）。
> 详见 [CHANGELOG.md](CHANGELOG.md) 与 [ROADMAP.md](ROADMAP.md)。
>
> **升级注意（不兼容变更）**：
> - 旧 v2.x 数据（`config/records.json`、`config/{gid}.json` 等）启动时自动归档到
>   `data/archive_v1/<时间戳>/`，**不做语义迁移**（Q6 决策：清空重来）。
> - 老用户首次启动后按新结构空数据起步，可通过 `initial_coins` 配置发放老婆币补偿。
> - 旧 12 个扁平命令语义保持不变；新分组命令（`老婆 xxx`）部分功能在 Phase 2/3 开放。

原插件：https://github.com/zgojin/astrbot_plugin_AW

在此基础上添加了几个功能，更改了数据目录，支持插件面板配置。

**本插件代码为 AI 生成，下面图床的也是。**

配套图床：https://github.com/monbed/wife

从 GitHub 获取：

如果你的 BOT 能够正常访问 GitHub 获取图片

图片服务器基础 URL 填写：https://raw.githubusercontent.com/monbed/wife/main/

图片列表 URL 填写：https://animewife.dpdns.org/list.txt

或者使用可以直连的反代（自行测试网络问题）如：

https://fastly.jsdelivr.net/gh/monbed/wife@main/

https://cdn.jsdmirror.com/gh/monbed/wife@main/

图片列表同上

也可以手动下载图片，放入 AstrBot `data/plugin_data/astrbot_plugin_animewifex/img/wife` 目录。

## 重构进度（v3.x）

| Phase | 范围 | 状态 | Tag |
|---|---|---|---|
| Phase 1 | 模块化 + 归档 + 双轨命令 | ✅ 已完成 | `v3.0.0-phase1` |
| Phase 2 | 冷却 + 榜单 + 亲密度 + 复仇 | ⏳ 待开工 | `v3.0.0-phase2` |
| Phase 3 | 经济 + 稀有度 + 求婚 + PK + 图鉴 | ⏳ 待开工 | `v3.0.0` |

详见 [ROADMAP.md](ROADMAP.md)。

## 本地开发与测试

本插件支持脱离 AstrBot 框架在源码目录直接跑单元测试（不污染 AstrBot 运行环境）：

```bash
# 安装测试依赖
pip install pytest pytest-asyncio tzdata

# 跑全部测试（约 140 用例，<2s）
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

AstrBot 运行环境的 QA 由本人在真实实例中亲自验证（参考仓库根 README 的 sync.bat 流程）。

## 指令（Phase 1）

### 旧扁平命令（v2.x 兼容）

- `老婆帮助` 显示所有命令帮助
- `抽老婆` 每天一次，随机抽一张二次元老婆
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

### 分组命令（Phase 2/3 开放）

形如 `老婆 列表` / `老婆 摸头` / `老婆 PK` 等，当前会返回"未开放"提示。
完整清单见 [ROADMAP.md §2.3](ROADMAP.md#23-命令双轨设计)。

更新日志见 [CHANGELOG.md](CHANGELOG.md)

## 相关

- [astrbot_plugin_AW](https://github.com/zgojin/astrbot_plugin_AW)
- [Astrbot](https://astrbot.app/)
