# v3 实施交接说明（Handoff Note）

> 给新 session 的快速入门——所有设计、plan、决策摘要都在本目录下。
> 本说明由编排器在 2026-07-12 用户拍板"开始 B"后写入。

---

## 1. 一句话全局目标

`astrbot_plugin_animewifexI` 升级为支持 **4v4 编队接力战** + **离婚系统** + **负债经济** + **NTR 安慰币** 四套新玩法，全部按 game_design 下的规格文档落地为生产代码 + 测试 + QA。

---

## 2. 文件清单（按读顺序）

| 顺序 | 路径 | 用途 |
|------|------|------|
| 1 | `README.md` | 本文件 |
| 2 | `玩法升级策划案.md` | v2 基线（Phase 4 现状）— **既有现实** |
| 3 | `v3_接力战_主线.md` | 4v4 编队接力战（主子系统）— **用户拍板** |
| 4 | `v3_离婚系统.md` | 离婚 + 双向分家产 — **用户拍板** |
| 5 | `v3_经济_负债_分币.md` | 负债 + NTR 安慰币（无手续费）— **用户拍板 v3.1** |
| 6 | `plans/2026-07-12-v3-全套实施计划.md` | 8 Phase / 24 Task 实施 plan |

> **新 session 应该按 1 → 2 → 3 → 4 → 5 → 6 顺序读完后再开始执行。**

---

## 3. 用户决策摘要（v3.1 锁定）

```
接力战（v3_接力战_主线.md）：
  ✓ S2 简化被动 + 元素被动（4×3=12 双层组合）
  ✓ H2 每回合速度判定（赛尔号式）
  ✓ L1 锁定老婆可进编队但 PK 战力 -15%
  ✓ PK 浮动 ±20% / 命中 90% / 暴击 10%
  ✓ 元素克制深化 1.30 / 0.75
  ✓ 4 状态层（气魄 / 弱点 / 血性 / 狂暴）

离婚（v3_离婚系统.md）：
  ✓ Q1 温和曲线：N10/R25/SR60/SSR120
  ✓ Q2 保留图鉴、移除持有
  ✓ Q3 离婚返还 ≈ 8 单抽（默认合适）
  ✓ Q4 分家产双向百分比 ±200 封顶
    （用户原话："现实中的离婚分家产就是百分比分"）

经济（v3_经济_负债_分币.md）：
  ✓ 负债下限 -500 币（硬封顶）
  ✓ 0% 利息（用户决策：避免复杂）
  ✓ 优先抵债（产出先进还债桶）
  ✓ NTR 攻击者零代价（用户决策："把老婆抱回家，付什么手续费"）
  ✓ NTR 安慰币 = 离婚返还基础（被牛方收到，受害补偿）
  ✓ 复仇免费
  ✓ 系统池已撤
```

---

## 4. 启动步骤（新 session 第一件事）

### Step 1：定位项目根

```powershell
cd C:\Users\Soren\Desktop\AgentWorkCommon\astrbot_plugins\astrbot_plugin_animewifexI\
```

确认 `game_design/`、`app/`、`tests/` 存在。

### Step 2：跑基线

```powershell
$env:PYTHONPATH='.'; python -m pytest
```

期望：原 362 用例全绿（Phase 4 状态）。

### Step 3：读 spec 文档（按文件清单第 2-5 项）

### Step 4：读 plan（按文件清单第 6 项）

### Step 5：决定执行方式

| 方式 | 何时选 |
|------|--------|
| **Subagent** (mimo-dev + mimo-review) | > 3 独立任务 |
| **Inline** | ≤ 3 紧耦合任务 |

按当前 4 子系统结构——**Subagent 是推荐方式**。

### Step 6：调度顺序（建议）

1. **Phase A → B → C**：接力战子系统（最高改动量）
2. **Phase D**：离婚系统
3. **Phase E**：负债经济基础
4. **Phase F → G**：NTR 安慰币 + 命令接入
5. **Phase H → I**：QA + 同步

---

## 5. 关键技术约束

### AstrBot 装饰器必须在 main.py

- `main.py` 全量重执行
- `app/plugin.py` 的 `WifePluginCore` 是基类，**所有 `@filter` 装饰的方法必须在 main.py**
- reload 时装饰器才重新注册

详见 `ROADMAP_PHASE4_DETAILED.md` §10.3

### JSON 存储 + 群锁

- 所有读写走群锁 + 原子写
- 不要新增后台线程（用懒重置）
- `pk_battles.json` 是新增的（每群一份）

### 测试两套

1. **pytest** (`tests/`)：函数级正确性
2. **QA 脚本** (`data_qa/`)：端到端群聊交互模拟 — 改命令后必跑

### AstrBot 运行端 QA

- `sync.bat` 已经 `chcp 65001` 处理中文
- 同步不含 `game_design/`、`data_qa/`、`tests/`、`.venv` 等
- 同步完必须在 WebUI → 插件管理 → **Reload**

---

## 6. config schema 注意点

`_conf_schema.json` 的 `object` 类型必须用 `items` 嵌套 — 不能用顶层 `default`，否则 AstrBot `_parse_schema` 会 `KeyError: 'items'`。

新增 `pk_v2_*` / `divorce_*` / `debt_*` / `ntr_comfort_*` 等配置项，**每个 object 都用 items 嵌套**。

---

## 7. 当前 git 状态

- 仓库根不是 git
- `astrbot_plugin_animewifexI/` 是独立 git 仓库
- `game_design/` 在 `.gitignore` 里 + `sync.bat` 的 `/XD` 里
- 提交都在插件目录内部进行

提交惯例：
```bash
git add app/ tests/
git commit -m "feat(scope): 改动一句话"
```

---

## 8. 与外部 spec 的引用

各 spec 用 `[Sn]` 锚点标识章节，plan 的 task 用 `**Covers:**` 字段反向引用。

例：
- `v3_接力战_主线.md [S3.5]` ← `plans/...Task A.1 Covers: [S3.2][S3.3]`

不要重编号 spec 章节，否则 plan 的 Covers 引用会失效。

---

## 9. 不要做的事

- ❌ 不要把 NTR 逻辑从 `OwnershipService` 拆出来
- ❌ 不要重写 main.py 的 AstrBot 装饰器入口
- ❌ 不要把 JSON 存储改成 SQLite
- ❌ 不要为打工/离婚新增独立后台线程
- ❌ 不要从其他 AstrBot 插件"抄"AstrBot API 用法——查文档
- ❌ 不要再引入 NTR 手续费 / 系统池 —— **v3.1 已撤**
- ❌ 不要在 sync.bat 同步 game_design/

---

## 10. 常用 AstrBot 文档片段

`docs.astrbot.app/dev/star/plugin-new` 是权威。

**主动消息**（接力战回合贴、结算贴、NTR 成功贴等）：
```python
await self.context.send_message(umo, MessageChain().message(text))
# umo 必须从 event.unified_msg_origin 捕获并持久化
```

**被动响应**：
```python
yield event.plain_result("...")
# 或
yield event.chain_result(MessageChain().message(...).file_image(...))
```

---

## 11. 路径速查

| 用途 | 路径 |
|------|------|
| 插件源码 | `C:\Users\Soren\Desktop\AgentWorkCommon\astrbot_plugins\astrbot_plugin_animewifexI\` |
| 运行时插件数据 | `\\5300u\c\Users\soren\.astrbot_launcher\instances\<id>\core\data\plugins\astrbot_plugin_animewifexI` |
| 运行时小组数据 | `\\5300u\c\...\core\data\plugin_data\astrbot_plugin_animewifexI` |
| 设计文档 | `<plugin>/game_design/` |
| 实施 plan | `<plugin>/game_design/plans/` |
| 同步脚本 | `<plugin>/sync.bat` |
| pytest 配置 | `<plugin>/pytest.ini` |
| conftest | `<plugin>/tests/conftest.py` |

---

## 12. 启动时的第一句话示例

新 session 第一轮可以这样向自己（或 reader）说：

> **我从 `game_design/HANDOFF.md` 接手**
> 已读：玩法升级策划案.md（v2 基线）+ v3_接力战_主线.md + v3_离婚系统.md + v3_经济_负债_分币.md + plans/2026-07-12-v3-全套实施计划.md
> 下一步：跑基线 pytest（362 用例），然后开始 Phase A 的 Task A.1

---

> 文档已落 `game_design/HANDOFF.md`，新 session 接手即可。
> 当前编排器至此结束任务——你拍板的"开始 B"完成。
