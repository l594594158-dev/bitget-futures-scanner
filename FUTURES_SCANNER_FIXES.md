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

## 2026-04-21｜功能：做空条件拆分为独立函数 + 暴涨快捷模式（最终版）

### 问题背景
- 做空信号在暴涨行情（单日+20%~100%）里几乎永远触发不了
- RSI负背离需要价格"涨累了回调"才会出现，但暴涨币RSI一直钝化
- ADX经常60+直接触发>60禁止做空的限制
- 原有做空条件和做多混在一起，参数分散难以单独调整

---

### 完整做空策略

#### 🔀 双模式自动切换
| 条件 | 触发模式 |
|------|---------|
| 日涨幅 ≥ **25%** | 🚀 **暴涨快捷模式** |
| 日涨幅 ＜ 25% | 📉 **主模式（RSI负背离）** |

#### 📉 主模式（适用于普通行情）
4个条件**全部满足（AND）**：
| # | 条件 | 参数 | 说明 |
|---|------|------|------|
| ① | RSI负背离 | 必须 | 价格创新高但RSI没创新高 → 看空反转信号 |
| ② | ADX区间 | 20~75 | ADX<20趋势太弱，ADX>75趋势极端都禁止 |
| ③ | DI- > DI+ | 必须 | 空头必须主导市场 |
| ④ | 布林偏离 | ≥2% | 价格偏离布林中轨2%以上 |
| ⑤ | 附加条件（至少1个） | - | 缩量滞涨 / 动量衰竭 / 放量确认 |

#### 🚀 暴涨快捷模式（日涨幅≥25%时自动启用）
跳过RSI负背离，改用"高位回落"判断：
| # | 条件 | 参数 | 说明 |
|---|------|------|------|
| ① | ADX区间 | 25~85 | 趋势强但不极端（放宽限制） |
| ② | 从日内高点回落 | ≥5% | 价格从最近1小时高点跌超5% |
| ③ | 双重缩量或布林偏离 | vr5<1.5 AND vr1<1.5 | **5分钟+1小时同时缩量** |
| ④ | 附加条件（至少1个） | - | 缩量滞涨 / 动量衰竭 |

**关键：vr5（5分钟）和 vr1（1小时）必须同时缩量，才认定滞涨信号。**

#### ⚙️ `SHORT_CONFIG` 完整参数
```python
# ── 主模式 ──
'require_rsi_div': True,          # 是否要求RSI负背离（True=必须，False=跳过）
'adx_min': 20,                    # ADX最小值
'adx_max': 75,                    # ADX>75禁止做空
'di_minus_stronger': True,        # DI-必须大于DI+
'bb_dev_threshold': 2.0,          # 布林偏离中轨阈值（%）
'vol_weak_threshold': 0.5,        # 缩量阈值
'momentum_slowdown_min': 0.5,      # 动量衰竭最小值
'vr_strong_for_bb': 1.5,          # 放量vr阈值
'adx_for_strong_vol': 25,          # 放量时要求ADX>此值
'extra_require': 1,                # 附加条件至少满足几条

# ── 暴涨快捷模式 ──
'surge_mode_enabled': True,        # 开启暴涨快捷模式
'surge_day_change_thresh': 0.25,  # 日涨幅>25%触发
'surge_adx_min': 25,              # ADX下限
'surge_retrace_min': 0.05,        # 从日内高点回落>5%
'surge_vr_max': 1.5,              # 5分钟+1小时双重缩量阈值
'surge_bb_dev': 1.0,              # 布林偏离阈值（%）
'surge_adx_max': 85,              # ADX上限
```

#### 📐 双重保险逻辑
```
条件③ = (vr5 < 1.5 AND vr1 < 1.5)  ← 双重缩量
      OR bb_dev >= 1.0%             ← 布林偏离足够大
```

#### 📊 验证结果
| 标的 | 日涨幅 | 模式 | 回落 | vr5 | vr1 | 结果 |
|------|--------|------|------|-----|-----|------|
| BASEDUSDT | +37% | 暴涨 | 6.5% ✅ | 0.38 | 2.11 | 🔴 做空 |
| BASUSDT | +30% | 暴涨 | 6.3% ✅ | 0.17 | 0.80 | 🔴 做空 |
| RAVEUSDT | +109% | 暴涨 | 21.9% ✅ | 0.80 | 0.74 | ❌ 附加条件空 |
| ORDIUSDT | +21% | 主模式 | - | 0.23 | 0.98 | ❌ RSI负背离❌ |

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

---

## 2026-04-21｜调整：暴涨模式ADX上限收紧（85→70）

### 背景
- RAVEUSDT +139% 行情做空失败，ADX=78（强趋势）继续冲高，空单浮亏
- 强趋势下做空逆势容易被插针爆仓

### 改动
- `surge_adx_max`: 85 → **70**
- ADX > 70 = 强趋势 → 暴涨快捷模式直接跳过做空

### 效果
| 标的 | ADX | 之前 | 现在 |
|------|-----|------|------|
| RAVEUSDT | 80.3 | 做空❌ | **拦截** |
| UAIUSDT | 70.1 | 做空❌ | **拦截** |
| BASEDUSDT | 61.4 | 做空 | 通过 |

---

## 2026-04-21｜Bug：datetime UnboundLocalError 闪退

### 问题
- 报错：`UnboundLocalError: cannot access local variable 'datetime' where it is not associated with a value`
- 触发位置：第1060行 `f"{datetime.now().strftime(...)}"`

### 根因
- 文件头部第40行已有 `from datetime import datetime`
- 但第976行又在 `if not existing_local:` 条件块内重复写了 `from datetime import datetime`
- Python 将 `datetime` 变成该条件块的局部变量
- 当条件不满足跳过该块时，全局代码访问 `datetime` 报错

### 修复
- 删除条件块内的 `from datetime import datetime`（第976行）
- 保留文件头部的全局 import

### 验证
- 重启后正常运行，无报错
