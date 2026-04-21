# futures_scanner.py 修复记录

## 2026-04-21｜Bug：set_leverage 导致部分仓位实际杠杆 20x

### 问题现象
- db_positions.json 中 SCRTUSDT、PRLUSDT、TRADOORUSDT 的 leverage 显示 20x
- 日志中这几个仓位开仓时 set_leverage 返回 `marginMode: crossed`（全仓）而非 `isolated`
- Bitget 默认全仓模式最大杠杆 20x，导致实际成交杠杆与预期 10x 不符

### 根因分析
```
place_order()
  ├── set_leverage(symbol, 10, 'long')
  │     └── body 缺少 marginMode 字段
  │         └── Bitget 对部分币种默认 crossed（全仓）
  │             └── 全仓模式实际杠杆 = 20x（系统最大杠杆）
  │             └── API 返回 "crossed" 但代码只打 info 日志，未告警
  │
  └── place_order(marginMode='isolated')  ← 订单层无效，仓位层已设错
```

**Bitget set_leverage 关键规则：**
- leverage 参数本身不能独立决定仓位杠杆
- 必须配合 `marginMode: 'isolated'` 才能生效
- 不传 marginMode → Bitget 默认 crossed（全仓）→ 实际杠杆 20x

### 修复内容

**1. set_leverage 函数（574行）**
```python
body = {
    'symbol': symbol, 'productType': 'USDT-FUTURES',
    'marginCoin': 'USDT', 'leverage': str(leverage),
    'marginMode': 'isolated',  # ← 新增：必须显式指定
    'holdSide': hold_side
}
```

**2. set_leverage 返回值校验（新增）**
- 若返回 `marginMode != 'isolated'`，记录 `ERROR` 并重试（不带 holdSide）
- 若 `actual_leverage != target`，记录 `ERROR` 并重试

**3. 新增 verify_and_fix_leverage() 函数（605行）**
- 调用 Bitget single-position API 获取仓位真实杠杆和模式
- 若实际值与目标不符（LEVERAGE=10, mode=isolated），自动重新调用 set_leverage
- 修正后推送微信告警通知用户
- 校验通过打日志 `✅ XXX 杠杆校验OK`

**4. 三个调用点**
| 位置 | 时机 | 目的 |
|------|------|------|
| 持仓追踪循环（728行） | 每次心跳检查每个持仓 | 防止历史仓位带错杠杆 |
| 防重复开仓检测（878行） | 发现已有持仓时 | 防止 set_leverage 失效漏网 |
| 从交易所恢复持仓（909行） | 恢复历史记录时 | 恢复后立即校验 |

### 受影响仓位（已修正）
| 标的 | 修正前 | 修正后 |
|------|--------|--------|
| SCRTUSDT | 20x/crossed | 10x/isolated |
| PRLUSDT | 20x/crossed | 10x/isolated |
| TRADOORUSDT | 20x/crossed | 10x/isolated |

### 验证
- 机器人重启后所有 6 个持仓全部 `✅ XXX 杠杆校验OK: 10x/isolated`
- PID: 2062446

---

## 2026-04-20｜Bug：对冲模式平仓 side 方向反了

### 问题
- close_position 用反向 side（short 时 side=buy, long 时 side=sell）
- Bitget 对冲模式下平仓用同向 side
- 导致移动止盈触发时平仓失败（返回 None/22002）

### 修复
```python
close_side = 'sell' if direction == 'short' else 'buy'
```

---

## 2026-04-20｜Bug：setLeverage endpoint 路径错误

### 问题
- 错误路径：`POST /api/v2/mix/position/setLeverage` → 40404
- 正确路径：`POST /api/v2/mix/account/set-leverage`
- 影响：开仓前杠杆设置失败，Bitget 默认 20x

### 修复
- 新增 `set_leverage()` 函数，使用正确路径
- 在 `place_order()` 前调用

---

## 2026-04-20｜Bug：手动平仓后冷却时间不重置

### 问题
- 手动平仓后机器人立即反向开仓
- 只记录了开仓时的 cooldown，手动平仓检测路径漏了

### 修复
- 检测到 `real_size <= 0` 时同时写入 `cooldown[symbol] = now`

---

## 2026-04-20｜Bug：f-string 格式符内条件表达式语法错误

### 问题
```python
f"{value:.5f if value else 'N/A'}"  # → ValueError
```

### 修复
```python
f"{value:.5f}"  # 移除条件，简化
```
