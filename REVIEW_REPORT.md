# 代码 Review 报告（v3.0.0-phase3-gacha）

审查时间：2026-07-03
审查范围：Phase 1-3 全部服务层 + 命令层 + 存储层
总测试：280 passed

---

## 一、CRITICAL — 数据损坏风险（4 项）

### C1. Phase 3 五个服务无群锁保护

**文件**：`economy_service.py` / `shop_service.py` / `marry_service.py` / `pk_service.py` / `quest_service.py`

**问题**：所有 Phase 3 服务的 load→modify→save 流程均在 GroupLocks 外执行。并发操作（两人同时买道具、同时 PK、同时签到等）会导致后写覆盖先写，数据丢失。

**现状**：
```
OwnershipService    ✅ 全部 async with self._locks.acquire(gid)
EconomyService      ❌ 无锁
ShopService         ❌ 无锁
MarryService        ❌ 无锁
PkService           ❌ 无锁
QuestService        ❌ 无锁
```

**修复方案**：将 Phase 3 服务的所有公开方法改为 `async`，内部走 `async with self._locks.acquire(gid):`。需要：
1. 5 个 Service 的 `__init__` 加 `locks: GroupLocks` 参数
2. 所有 load→modify→save 方法加 `async` + 群锁
3. 命令层对应改为 `await` 调用
4. 测试 fixture 同步更新

**影响范围**：14 个文件、约 30 个方法签名变更

---

### C2. PK 胜负统计永远不递增

**文件**：`pk_service.py:127-141`

**问题**：`profile.total_pk_win` / `total_pk_lost` 字段存在且面板展示，但 `PkService.pk()` 从不写入，永远显示 0/0。

**修复**：
```python
# pk_service.py:127 附近，在 earn 之后
winner_profile.total_pk_win += 1
loser_profile = profiles.get(loser_uid)
if loser_profile:
    loser_profile.total_pk_lost += 1
```

---

### C3. 十连券 double-spend

**文件**：`draw.py:97-111`

**问题**：十连券检查+扣减在锁外执行。两个并发十连可同时通过 `inventory > 0` 检查，1 张券抽 20 次。

**修复方案**：将券检查+扣减移入 `draw_or_get_primary` 的群锁内，或在命令层加独立群锁包装整个十连流程。

**推荐方案**：在 `handle_draw_ten` 中用 `ctx.locks.acquire(gid)` 包裹整个流程（券检查→扣减→10 次抽卡→失败回退），而非修改底层 `draw_or_get_primary`。

---

### C4. wives_master.json 全局文件无并发保护

**文件**：`rarity_service.py:156-183`（被 `draw_or_get_primary` 调用）

**问题**：`WivesMasterStore.save_all()` 是全局单文件。跨群并发抽卡同时写入可能损坏图鉴元数据。

**修复方案**：引入进程级全局锁 `WIVES_MASTER_LOCK = asyncio.Lock()`，在 `WivesMasterStore.save_all` 内部加锁。或在 `rarity_service.draw` 的 `upsert` 路径加全局锁。

---

## 二、HIGH — 功能 Bug（4 项）

### H1. NTR 不检查 is_locked（路线图违规）

**文件**：`ownership_service.py:478-543`

**问题**：ROADMAP §5.3 明确规定"目标老婆 is_locked 时直接失败"，但 `try_ntr` 完全没校验。

**修复**：
```python
# ownership_service.py:497 附近，target_primary 判空之后
if MarryService.is_locked(target_primary):
    return NtrResult(
        ok=True, success=False, consumed_attempt=True,
        reason="target_locked", remaining_attempts=remaining,
    )
```

---

### H2. 十连遇 draw_cooldown 只出 1 张

**文件**：`ownership_service.py:302-306`

**问题**：`skip_check` 只跳过免费/券检查，冷却检查仍在锁前执行。十连第 1 抽成功后更新冷却，第 2 抽立即被冷却拦截。

**修复**：将冷却检查移入 `if not skip_check` 块内，或添加 `skip_cooldown` 参数。

**推荐**：最简方案 — 将冷却检查移入 `if not skip_check:` 块：
```python
if not skip_check:
    # 冷却检查
    if self._cooldown and self._config.draw_cooldown > 0:
        if not self._cooldown.check(...):
            return DrawResult(ok=False, reason="cooldown")
    # 免费/券检查
    ...
```

---

### H3. admin 重置抽卡重置错字段

**文件**：`admin.py:269-278`

**问题**：重置 `last_draw_date` 而非 `today_draw_date`/`today_draws`/`today_free_draws`，实际无效。

**修复**：
```python
# admin.py:271 替换为
target.last_draw_date = ""
target.today_draw_date = ""
target.today_draws = 0
target.today_free_draws = 0
```

---

### H4. `is_locked()` 有副作用

**文件**：`marry_service.py:144-158`

**问题**：检查方法会 mutate ownership 对象（过期自动解锁），但调用方不一定 save。面板等只读场景不会调此方法，导致过期锁定仍显示为已锁定。

**修复**：
1. `is_locked()` 保持副作用（过期自动解锁是合理行为），但调用方需 save
2. 面板 `panel.py:108` 改为调用 `MarryService.is_locked(o)` 判断

---

## 三、MEDIUM — 一致性/健壮性（7 项）

| # | 文件 | 问题 | 修复 |
|---|---|---|---|
| M1 | `ownership_service.py:253-267` | `get_profile` 只读也 save | 判断 nick 非空且 profile 不存在时才 save |
| M2 | `ntr.py:81` / `change.py:43` | `cancel_swap_for_users` 在锁外调用 | Phase 1 已知竞态，可暂缓 |
| M3 | `admin.py:222-417` | 管理员命令无锁 | admin 是低频操作，可暂缓 |
| M4 | `pk_service.py:129+132` | 重复 save profiles.json | 合并为一次 save（修 C1 时一并解决） |
| M5 | `panel.py:108` | 面板显示过期锁定为已锁定 | 调用 `MarryService.is_locked()` |
| M6 | `stores.py:174-198` | `transfer()` 不重置 is_primary | 当前调用方已补刀，可加断言防护 |
| M7 | `ownership_service.py:269-277` | `ntr_status.json` 全局文件无锁 | 同 C4 全局锁方案 |

---

## 四、修复计划

### 第一批：CRITICAL（防止数据丢失）

| 序号 | 任务 | 涉及文件 | 预估改动 |
|---|---|---|---|
| C1 | Phase 3 服务加 GroupLocks | 5 service + 4 command + conftest.py | ~200 行 |
| C2 | PK 统计递增 | pk_service.py | ~5 行 |
| C3 | 十连券锁内扣减 | draw.py | ~30 行 |
| C4 | wives_master 全局锁 | rarity_service.py 或 locks.py | ~20 行 |

### 第二批：HIGH（功能正确性）

| 序号 | 任务 | 涉及文件 | 预估改动 |
|---|---|---|---|
| H1 | NTR 锁定校验 | ownership_service.py | ~8 行 |
| H2 | 十连冷却跳过 | ownership_service.py | ~10 行 |
| H3 | admin 重置字段 | admin.py | ~5 行 |
| H4 | is_locked 副作用 | marry_service.py + panel.py | ~10 行 |

### 第三批：MEDIUM（可暂缓）

M1-M7 按需修复，不阻塞发布。

---

**总计预估**：~280 行改动，涉及 15 个文件
**风险**：改动面大，每批完成后需跑全量 280 测试 + 同步 AstrBot 实测

请确认是否执行，或调整优先级。
