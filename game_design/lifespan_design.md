# 寿命 / 死亡 / 复活 系统设计

## 数据模型

`Ownership` 新增 4 个字段（向后兼容：老数据自动按 `lifespan_max` 初始化）：

- `lifespan: int` — 当前寿命，0 ~ max
- `lifespan_updated_date: str` — YYYY-MM-DD，最后一次寿命变动日期
- `is_dead: bool` — 是否已死亡
- `death_date: str` — YYYY-MM-DD
- `death_cause: str` — `work_exhaustion` / `pk_exhaustion` / `impact` / `manual` 等

`UserProfile` 新增 3 个统计字段：

- `total_wife_deaths: int` — 累计死亡次数
- `total_lifespan_restored: int` — 累计修复次数
- `total_coins_spent_on_revive: int` — 累计花在复活上的币

## 公式

### 死亡概率（每次有寿命消耗的事件后）

```python
# 二次方：lifespan=max → p=0；lifespan=0 → p=base
ratio = 1.0 - lifespan / lifespan_max
p_death = death_probability_base * (ratio ** 2)
```

默认 `death_probability_base=0.50`：lifespan=0 时有 50% 概率当场死。
但只有"有消耗的事件"才检查 — 不是每秒都跑。
例：lifespan=20 / max=100 → ratio=0.8 → p=0.50 × 0.64 = 0.32 → 32% 概率猝死。
lifespan=50 → ratio=0.5 → p=0.125 → 12.5%。
lifespan=80 → ratio=0.2 → p=0.02 → 2%。

### 修复价格

```python
# 基础价 × 紧急度倍率（1.0~2.0）
urgency = 1.0 + (1.0 - current_lifespan / lifespan_max)
price = rarity_base[rarity] * urgency
```

例：SSR (base=250)，lifespan=50 → 250 × 1.5 = 375 币。
lifespan=0（死了）→ 250 × 2.0 = 500 币。
lifespan=100（满血）→ 250 × 1.0 = 250 币，**但满血不需要修复**，返回 0。

实际上 "满血修复" 返回 0，"半血" 修复按上面公式。
死了的修复就是 lifespan=0 → 上面公式套用即可。

### 寿命损失（来源不同）

- 打工结算：`lifespan_loss_work[mode]`，默认 {normal: 5, overtime: 10, expedition: 20}
- PK 战斗结束：`lifespan_loss_pk`，默认 8
- impact 用户 ri 别人老婆：调用方算后传 delta，**我们**只扣
  - size < 30 → delta = 0（调用方已短路，不调我们）
  - size >= 30 → 调用方算 delta，传过来

## 死亡后行为

- 老婆**仍存在** ownership.json（不删除）
- `is_dead=True` 后：
  - 打工 → 拒绝（"她已离世，无法打工"）
  - PK → 拒绝
  - 亲密度互动（pet/gift/chat/date）→ 拒绝
  - 切换主老婆 → 允许（让用户切换到活的那个）
  - **可被离婚**（不返不扣任何币）
  - **不可被 NTR**（尸体不让牛走）
  - **可被花钱复活**（满血）
- `is_dead=True` 时：寿命条显示 ☠️
- 死亡老婆**不进入** PK 编队可选列表（强制只用活老婆）

## 跨插件接口（impact 调用）

`WifeInterop` 加 `apply_lifespan_damage_from_impact`：

```python
async def apply_lifespan_damage_from_impact(
    self, gid: str, wid: str, actor_uid: str, delta: int
) -> Dict[str, Any]:
    """impact 调用：用户 ri 别人老婆时根据丁丁尺寸计算寿命损失
    
    Args:
        gid: 群 ID
        wid: 目标老婆 wid
        actor_uid: 发起人 uid
        delta: 寿命减少量（调用方按丁丁尺寸算好；0 时直接返回 ok=True 无变化）
    
    Returns:
        {ok, new_lifespan, lifespan_max, dead, wife_owner_uid, death_occurred}
    """
```

调用方在 `impact_service_gameplay.py` 的 `handle_fuck_wife` 加：
```python
if not is_self and sender_length >= 30:
    size_delta = clamp(int((sender_length - 30) * 0.5), 0, 20)  # 0~20 寿命
    interop_result = await interop.apply_lifespan_damage_from_impact(
        gid, wid, sender_uid, size_delta
    )
    # 把寿命结果加到 reply 中
```

注意 impact 里边的 `gid` 是 `int`，animewifexI 这边是 `str` — 调用时转一下。

## 命令

`老婆 休息 [编号]` / `养老婆 [编号]` — 修复指定老婆（满血复活死亡 / 修复寿命）
- 不指定编号：列出所有老婆的修复价格（按编号），提示 `老婆 休息 <编号>` 确认
- 指定编号：扣币，把 lifespan 设为 max，清 is_dead
- 死亡老婆复活：按 `lifespan=0` 算价格（rarity_base × 2）
- 活老婆修复：按当前 lifespan 算价格

也支持 alias：`老婆 复活` (这个跟"休息"是同一回事)。

## 配置项

8 个新字段：
- `lifespan_enabled: bool` — 总开关
- `lifespan_max: int = 100`
- `lifespan_loss_work: dict = {normal: 5, overtime: 10, expedition: 20}`
- `lifespan_loss_pk: int = 8`
- `death_probability_base: float = 0.50`
- `revive_base_cost: dict = {N: 30, R: 60, SR: 120, SSR: 250}`
- `revive_urgent_multiplier: float = 1.0`（1.0=简单 2x 紧急度；>1.0 加成）

## 死亡检查时机

- 打工结算时：只检查**正在结算的那个**老婆（不是全部）
- 打工被牛：检查被牛的老婆
- PK 战斗结束：检查**败方所有活过的老婆**（按参与数扣 1-2 次寿命）+ 胜方
- 老婆币购买修复时：不检查
- 用户 ri 别人老婆后：检查该老婆

## QA 覆盖

- 抽老婆默认寿命=max
- 打工后寿命扣
- 寿命低时打工可能猝死
- 死亡后打工/牛/亲密度 全部拒绝
- 死亡后离婚不返不扣
- 死亡后复活按 rarity_base × 2
- 修复价格随 lifespan/rarity 变
- `老婆 休息` 不指定编号列价格
- 多次打工累积扣寿命
- impact 接口：delta=0 不变；delta>0 扣到可能死

## 涉及文件

- `app/models/ownership.py` — 加 5 字段
- `app/models/profile.py` — 加 3 字段
- `app/models/enums.py` — 加 `Action.LIFESPAN_LOSS` / `LIFESPAN_RESTORE` / `WIFE_DEATH`
- `app/services/plugin_config.py` — 8 字段
- `_conf_schema.json` — 8 项
- `app/services/lifespan_service.py` — **新文件**，核心服务
- `app/services/divorce_service.py` — 死亡老婆不走返还公式
- `app/services/work_service.py` — 结算时扣寿命 + 死亡检查；start_work 拒绝死亡
- `app/services/ownership_service.py` — pet/gift/chat/date 拒绝死亡；switch_primary 跳过死亡
- `app/services/ntr_service.py` (在 ownership_service) — 死亡老婆不能被牛
- `app/services/pk_v2_service.py` — `_apply_rewards` 后扣寿命 + 死亡检查
- `app/interop.py` — `apply_lifespan_damage_from_impact`
- `app/commands/rest.py` — **新文件**
- `app/commands/registration.py` — 注册 "休息" / "养老婆" / "复活"
- `app/commands/divorce.py` — 死亡老婆走"尸葬"路径
- `app/commands/view.py` / `panel.py` — 显示 ☠️ 标记
- `app/commands/work.py` — 拒绝死亡老婆
- `app/plugin.py` — `CommandContext` 注入 lifespan_service
- `app/commands/context.py` — lifespan_service 字段
- `tests/test_lifespan_service.py` — **新**
- `tests/test_commands_rest.py` — **新**
- `tests/test_interop.py` — 加 lifespan 接口测试
- `tests/test_models.py` — 加 lifespan 字段测试
- `tests/test_divorce.py` — 死亡离婚测试
- `tests/conftest.py` — lifespan_service fixture
- `data_qa/qa_lifespan.py` — **新**，端到端 QA
