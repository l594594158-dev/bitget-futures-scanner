# surge_trader.py / trailing_stop_v2.py 修复文档

## 修复日期：2026-04-22

---

### 1. 信号条件简化（删除布林带）

**文件：** `surge_trader.py`

**改动：** 做多信号从5个条件简化为4个，删除 BB偏离 条件

| 条件 | 旧值 | 新值 |
|------|------|------|
| BB偏离 | ≥4.0% | 已删除 |
| ADX | ≥40 | ≥30 |

**涉及代码：** `check_signal_long()` 函数

---

### 2. 开仓失败写冷却

**文件：** `surge_trader.py`

**问题：** 开仓失败时没有写入冷却时间，导致同一信号在每次扫描时重复触发、重复尝试开仓，仓位被追加放大。

**修复：** 开仓失败（order_id 为空）时也调用 `set_cooldown()`，并 `continue` 跳过后续流程。

**涉及代码：** `scan_and_trade()` 内 `open_position()` 调用后

---

### 3. 开仓前去重验证（双重检查）

**文件：** `surge_trader.py`

**问题：** 缺乏仓位存在检查，导致信号触发时盲目开仓。

**新增检查顺序：**
1. 读取 `DB_V2`（`db_positions_v2.json`），检查该币是否已有 `symbol_direction` 键
2. 调用 Bitget `single-position` API，检查 `total > 0`

任一检查通过则跳过开仓，打印 `⏭ {symbol} 数据库2号已有仓位/ API已有仓位，跳过`

**涉及代码：** `scan_and_trade()` 主循环开始处

---

### 4. 新增常量

```python
DB_V2 = f'{WORKSPACE}/db_positions_v2.json'  # 数据库2号：真实持仓（与Bitget同步）
```

---

### 5. trailing_stop_v2 数据库key污染Bug

**文件：** `trailing_stop_v2.py`

**问题：** `db_positions_v2.json` 中 key 格式错误，变为 `symbol_long_long_long_long...`。

**根因：** `pos_key = f"{symbol}_{direction}"` 在循环中反复覆盖，但 symbol 字段在某些情况下被污染（包含 `_long` 后缀），导致 key 越来越长。

**修复：** 所有 key 一律使用 `f"{symbol}_{direction}"` 格式，确保 symbol 干净。数据库已清空重建。

**涉及代码：** `monitor_loop()` 第388-510行

---

### 6. API 40037 诊断总结

**结论：** `40037 Apikey does not exist` 在账户类接口中实际表示"服务暂时不可用"，非权限问题。市场数据接口（tickers）始终正常。

| 接口类型 | 示例 | 状态 |
|---------|------|------|
| 市场数据 | `market/tickers` | ✅ 始终正常 |
| 账户/持仓 | `position/all-position` | ⚠️ 间歇性40037 |
| 交易 | `order/place-order` | ⚠️ 间歇性40037 |

---

### 7. 杠杆设置失败时取消开仓

**文件：** `surge_trader.py`

**问题：** `set-leverage` 失败后仍继续开仓，导致使用默认杠杆（可能20x非10x）。

**修复：** `set-leverage` 返回非成功码时，直接 `return None` 取消开仓。

---

### 8. 开仓后验证实际杠杆

**文件：** `surge_trader.py`

**问题：** 杠杆设置接口可能静默失败，导致实际仓位杠杆偏离预期。

**修复：** 开仓成功后立即查询 `single-position` 验证实际杠杆，非10x则立即市价平仓取消。

---

### 9. API Key/Secret 位置调换Bug

**文件：** `surge_trader.py` / `trailing_stop_v2.py`

**问题：** 代码中 `API_KEY`（hex字符串）和 `API_SECRET`（bg_开头）的赋值被调换。

**修复：** 两个值对调：
```python
API_KEY = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'   # hex字符串
API_SECRET = 'bg_55d7ddd792c3ebab233b4a6911f95f99'  # bg_开头
```

---

### 10. 移动止盈激活阈值调整

**文件：** `trailing_stop_v2.py`

**改动：** `TRAIL_TRIGGER_PCT` 从 0.08（8%）调整为 0.05（5%）

---

### 11. 机器人重启状态（10:40）

```
surge_trader.py     PID 2430425  ✅ 运行中
trailing_stop_v2.py PID 2430301  ✅ 运行中
db_positions_v2.json: 空 ✅
db_positions.json cooldown: 7个币在冷却中 ✅
服务器出口IP: 101.33.45.56
```
