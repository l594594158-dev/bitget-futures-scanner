# 合约交易机器人完整逐项汇报
**报告时间：** 2026-04-21 01:40 GMT+8
**文件版本：** futures_scanner.py v4

---

## 第一部分：代币筛选系统（DB1热点池）

### 1.1 入池条件

```python
GAIN_THRESHOLD = 0.20    # 日涨幅 > 20% 才入池
GAIN_REMOVE = 0.10      # 日涨幅 < 10% 则出池
MAX_DB_SIZE = 10        # 最多10个代币
```

### 1.2 筛选流程（逐行解析）

```
第一步：获取全部行情
  GET /api/v2/mix/market/tickers?productType=USDT-FUTURES
  → 返回537个USDT合约的24h数据

第二步：过滤日涨幅 > 20%
  candidates = [c for c in all if c.change24h > 0.20]

第三步：验证代币是否真实上线 > 24小时
  GET /api/v2/mix/market/candles?symbol=X&granularity=1D&limit=1
  → 能拿到日K线 = 真实上线代币（防假币/新币）
  → 拿不到 = 上架不足24h，丢弃

第四步：检查已有代币是否跌破10%
  已有代币如果日涨幅 < 10% → 从DB1清除

第五步：按日涨幅降序，取前10名
  sorted(candidates, key=lambda x: x.change24h, reverse=True)[:10]

第六步：写入 db_hot_contracts.json
```

### 1.3 数据库结构

```json
db_hot_contracts.json:
{
  "update_time": "2026-04-21 01:40:00",
  "contracts": [
    {
      "symbol": "GUNUSDT",
      "lastPr": 0.01859,
      "high24h": 0.02100,
      "low24h": 0.01500,
      "change24h": 0.212,
      "quoteVolume": 1000000,
      "baseVolume": 50000000,
      "fundingRate": 0.00005,
      "add_time": "2026-04-21 01:40:00"
    }
  ]
}
```

---

## 第二部分：技术指标计算体系

### 2.1 指标列表

| 指标 | 计算公式 | 用途 |
|------|---------|------|
| **RSI(14)** | 平均涨/(平均涨+平均跌)×100 | 超买>70 超卖<30 |
| **MACD(12,26,9)** | EMA12-EMA26=MACD; MACD-Signal=柱线 | 趋势方向/动量 |
| **布林带(20,2)** | 中轨=20期均线; 上轨=中轨+2σ; 下轨=中轨-2σ | 支撑/压力位 |
| **ADX** | 趋向指数 | 趋势强度 >25有趋势 >60强趋势 |
| **DI+/DI-** | 正向/负向趋向指标 | DI+>DI-多头; DI->DI+空头 |
| **vol_ratio** | 当前成交量/20期均值 | >1.5放量; <0.5缩量 |
| **BB_width** | (上轨-下轨)/中轨 | 波动扩张程度 |
| **RSI背离** | 价格创新高但RSI未同步创新高=负背离 | 顶底预警 |
| **动量衰竭** | 后期涨幅<前期50%=衰竭 | 趋势放缓预警 |

### 2.2 K线数据源

```
5分钟K线 × 100根 → 短期信号（RSI/MACD/布林/量能）
1小时K线 × 100根 → 趋势判断（ADX/DI+/DI-）
```

### 2.3 RSI背离检测逻辑

```python
lookback = 20根K线

# 负背离（看空）：
价格创20K线新高 AND RSI < 前高×0.95 → 触发

# 正背离（看多）：
价格创20K线新低 AND RSI > 前低×1.05 → 触发
```

### 2.4 动量衰竭检测逻辑

```python
period = 10根K线
计算最后10根平均涨幅 vs 第10根涨幅
如果：后期涨幅 < 前期平均涨幅 × 50% → 衰竭确认
```

---

## 第三部分：信号判断逻辑（做空/做多）

### 3.1 做空信号（四条件AND）

| 条件 | 要求 | 代码变量 |
|------|------|---------|
| ① RSI负背离 | 价格创新高但RSI未同步 | `cond1_short = has_bear_div and bear_div_type == 'bearish'` |
| ② 趋势向下 | ADX>20 AND DI->DI+ | `cond2_short = adx1 > 20 and dim1 > dip1` |
| ③ 布林上轨 | 价格接近上轨或偏离>2% | `cond3_short = bb_dev > 2.0 or price >= bb_up5` |
| ④ 附加条件 | 量价背离(vr<0.5) OR 动量衰竭 | `extra_short` 至少1项 |

**量能分级：**
```
vr > 1.5x  → 放量（趋势确认）
vr < 0.5x  → 缩量（可能反转）
0.5x≤vr≤1.5x → 中性
```

### 3.2 做多信号（四条件AND）

| 条件 | 要求 | 代码变量 |
|------|------|---------|
| ① RSI正背离 | 价格创新低但RSI未同步 | `cond1_long = has_bull_div and bull_div_type == 'bullish'` |
| ② 趋势向上 | ADX>20 AND DI+>DI- | `cond2_long = adx1 > 20 and dip1 > dim1` |
| ③ 布林下轨 | 价格接近下轨或偏离>2% | `cond3_long = bb_dev > 2.0 or price <= bb_lo5` |
| ④ 附加条件 | 量价背离(vr<0.5) OR RSI<40 OR 放量 | `extra_long` 至少1项 |

### 3.3 信号判断完整代码逻辑

```python
# 量能作为第一优先级
vr_strong = vr5 > 1.5    # 放量
vr_weak = vr5 < 0.5       # 缩量

# 做多
cond1_long = has_bull_div and bull_div_type == 'bullish'
cond2_long = adx1 and adx1 > 20 and dip1 > dim1
cond3_long = bb_dev > 2.0 or (bb_lo5 and price <= bb_lo5 * 1.02)
extra_long = [缩量反弹/放量确认/RSI超卖] 至少1项
long_ok = cond1_long and cond2_long and cond3_long and len(extra_long) >= 1

# 做空
cond1_short = has_bear_div and bear_div_type == 'bearish'
cond2_short = adx1 and adx1 > 20 and dim1 > dip1
cond3_short = bb_dev > 2.0 or (bb_up5 and price >= bb_up5 * 0.98)
extra_short = [缩量滞涨/放量确认/动量衰竭] 至少1项
short_ok = cond1_short and cond2_short and cond3_short and len(extra_short) >= 1

# 评分
if long_ok: direction='long'; score=10
elif short_ok: direction='short'; score=10
else: direction=None; score=0
```

---

## 第四部分：开仓逻辑

### 4.1 开仓流程逐行

```
第一步：冷却检查
  cooldown.get(symbol, 0) 检查是否在冷却中
  冷却中（距上次平仓<300秒）→ 跳过

第二步：信号分析
  analyze_symbol(symbol) 执行技术指标计算
  无信号 → 跳过

第三步：持仓检查（防重复开仓）
  get_position_size(symbol) 从交易所查真实持仓
  有持仓 → 跳过，不重复开仓

第四步：计算数量
  size = (2 USDT × 10杠杆) / 当前价格

第五步：设置杠杆
  set_leverage(10x, isolated)
  → POST /api/v2/mix/account/set-leverage

第六步：市价开仓
  place_order(symbol, side, size)
  → POST /api/v2/mix/order/place-order
  注意：不再传leverage参数（已修复）

第七步：记录保存
  cooldown[symbol] = now
  save_positions(positions)
  alert_to_queue() 推送告警
```

### 4.2 开仓参数

| 参数 | 值 |
|------|-----|
| 保证金 | 2 USDT/仓位 |
| 杠杆 | 10x（逐仓） |
| 冷却时间 | 300秒 |
| 仓位模式 | 逐仓（isolated） |
| 最低下单金额 | 5 USDT（Bitget限制） |

### 4.3 防重复开仓机制

```python
# 开仓前必须检查交易所真实持仓
real_size = get_position_size(symbol)
if real_size > 0:
    logger.info(f"⚠️ {symbol} 已有持仓{real_size}，跳过开仓")
    cooldown[symbol] = now
    # 如果本地无记录，从交易所恢复
    if not existing_local:
        pos_data = api_request('/single-position', ...)
        # 恢复本地持仓记录
```

---

## 第五部分：止盈止损逻辑

### 5.1 参数配置

| 参数 | 值 |
|------|-----|
| 移动止盈激活 | 盈利 ≥ 8% |
| 移动止盈退出 | 从峰值回撤 4% |
| 固定止损 | 亏损 > 9% |

### 5.2 止盈止损判断逻辑

```python
# 固定止损（优先判断）
if pnl <= -FIXED_STOP_PCT:  # -9%
    → 市价平仓，推送告警

# 移动止盈激活
if not trail_triggered and pnl >= TRAIL_TRIGGER_PCT:  # +8%
    → 激活移动止盈，记录激活价

# 移动止盈退出（激活后才判断）
if trail_triggered:
    # 做空：回撤 = (当前价 - 峰值) / 峰值
    # 做多：回撤 = (峰值 - 当前价) / 峰值
    if 回撤 >= TRAIL_EXIT_PCT:  # 4%
        → 市价平仓，推送告警
```

### 5.3 峰值追踪

```python
# 做多：追踪最高价
if direction == 'long' and current_price > peak_price:
    peak_price = current_price

# 做空：追踪最低价
if direction == 'short' and current_price < peak_price:
    peak_price = current_price
```

---

## 第六部分：持仓监测循环

### 6.1 监测流程

```
每5秒执行一次：

【第一步】追踪所有本地持仓（不依赖DB1）
  for pos in positions:
    → 检查真实持仓是否还在
    → 计算浮动盈亏
    → 检查固定止损
    → 更新峰值
    → 检查移动止盈激活/退出
    → 已平仓则清除记录

【第二步】扫描DB1寻找新开仓机会
  for contract in DB1_sorted:
    → 冷却检查
    → 信号分析
    → 防重复开仓检查
    → 开仓
    → 记录保存
```

### 6.2 关键修复记录

**修复1：持仓追踪不依赖DB1**
- 原问题：只扫描热点池，已出池的持仓失去追踪
- 修复：第一步遍历所有本地持仓，不依赖DB1

**修复2：杠杆设置**
- 原问题：place_order body带leverage参数覆盖set_leverage
- 修复：place_order不再传leverage参数

---

## 第七部分：API签名机制

### 7.1 签名规则

```
Bitget API 签名规则不一致：
  - 市场数据、持仓查询：签名用 path（不含query）
  - 账户、订单历史：签名用 path + '?' + queryString

策略：
  1. 先试 path-only 签名
  2. 若返回40009错误，自动用 path+query 重试
```

### 7.2 签名算法

```python
timestamp = str(int(time.time() * 1000))
sign_str = timestamp + method + path + body_str
signature = base64(hmac_sha256(sign_str, API_SECRET))
```

---

## 第八部分：当前配置参数汇总

```python
GAIN_THRESHOLD = 0.20       # 入库：日涨幅>20%
GAIN_REMOVE = 0.10          # 出库：日涨幅<10%
MAX_DB_SIZE = 10            # DB1上限10个
MONITOR_INTERVAL = 5         # 监测间隔5秒
POSITION_SIZE = 2.0          # 保证金2 USDT
LEVERAGE = 10               # 杠杆10x
MARGIN_MODE = "isolated"    # 逐仓模式
COOLDOWN_SECONDS = 300      # 冷却300秒
TRAIL_TRIGGER_PCT = 0.08    # 移动止盈激活8%
TRAIL_EXIT_PCT = 0.04       # 移动止盈退出回撤4%
FIXED_STOP_PCT = 0.09       # 固定止损9%
```

---

## 第九部分：当前持仓状态

```
更新时间: 2026-04-21 01:40

SCRTUSDT
  方向: 🟢做多  数量: 176个  杠杆: 10x
  开仓价: $0.11360  当前价: $0.11200
  浮亏: -1.41%  移动止盈: ⏳未激活

NAORISUSDT
  方向: 🟢做多  数量: 326个  杠杆: 10x
  开仓价: $0.06144  当前价: $0.06155
  浮盈: +0.18%  移动止盈: ⏳未激活
```

---

## 第十部分：文件路径汇总

| 文件 | 用途 |
|------|------|
| futures_scanner.py | 主机器人（信号分析+开仓+监测） |
| trailing_stop_v2.py | 移动止盈独立监控脚本 |
| db_hot_contracts.json | 热点币池数据库 |
| db_positions.json | 持仓记录 |
| db_positions_v2.json | 移动止盈数据库 |
| db_cooldown.json | 冷却记录 |
| futures_alert_queue.json | 告警队列 |
| REPAIR_LOG.md | 修复文档 |
| FUTURES_TASKS_REPORT.md | 本汇报文件 |

---

**汇报完毕，一字不漏，可供检查。**
