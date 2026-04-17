# ETH合约自动交易任务 · 代码执行级汇报

> 版本：v2.3（2026-04-17 对齐BTC策略4信号系统）
> 标的：ETH/USDT（Bitget U本位永续合约）
> 启动命令：python3 /root/.openclaw/workspace/eth_futures_trader.py

---

## 一、核心配置参数

| 参数 | 值 | 说明 |
|------|---|------|
| SYMBOL | ETHUSDT | 交易标的 |
| PRODUCT_TYPE | usdt-futures | 合约类型 |
| LEVERAGE | 20x | 杠杆倍数 |
| SIZE | 0.5 ETH | 每笔开仓数量（约$1260 @ $2520） |
| STOP_LOSS_PCT | 1.5% | 固定止损比例 |
| TAKE_PROFIT_PCT | 2.0% | 固定止盈比例（全仓一次性） |
| SCAN_INTERVAL | 10秒 | 每轮扫描间隔 |
| COOLDOWN_SECONDS | 300秒 | 平仓后冷却5分钟 |
| MAX_CONSECUTIVE_LOSS | 3次 | 连亏3次暂停30分钟 |
| ADX_THRESHOLD | 25 | 1h ADX>25过滤（第一关） |
| VOLUME_RATIO_THRESHOLD | 1.5 | 成交量>1.5x过滤（第二关） |

---

## 二、技术指标参数

| 指标 | 参数 | 说明 |
|------|------|------|
| 布林带 | 周期20，2倍标准差 | %b = (价格-下轨)/(上轨-下轨) |
| MACD | 快线12，慢线26，信号9 | 判断趋势方向 |
| RSI | 周期14 | 超买>70 / 超卖<30 |
| MA7 | 7周期均线 | 短期方向判断 |
| ADX | 窗口14 | 趋势强度 |
| 成交量比率 | 当前量/20根均量 | 信号质量确认 |

---

## 三、三层风控过滤（顺序执行）

### 第一层：1h ADX > 25
- 目的：确认主趋势有方向，非震荡市
- 代码逻辑：
```python
if adx_1h < 25:
    return None, f"ADX={adx_1h:.1f}<25 震荡市，观望"
```

### 第二层：成交量 > 1.5x 均量
- 目的：缩量视为假信号，不开仓
- 代码逻辑：
```python
if vol_ratio < 1.5:
    return None, f"缩量vol={vol_ratio:.2f}x，观望"
```

### 第三层：逆势信号额外检查 4h ADX < 40
- 目的：逆势信号（做多A/做空B）在趋势过强时易被碾压
- 代码逻辑：
```python
if trend_4h_bear and trend_1d_bear:  # 做多A / 做空B
    if adx_4h >= 40:
        pass  # 趋势过强，跳过该信号
```

---

## 四、大周期方向判断

```python
def is_bullish(ind):
    return ind['ma7'] < ind['close'] and ind['macd'] > 0
    # MA7在价格下方 → 多头

def is_bearish(ind):
    return ind['ma7'] > ind['close'] and ind['macd'] < 0
    # MA7在价格上方 → 空头
```

多头：MA7在价格下方 AND MACD柱 > 0
空头：MA7在价格上方 AND MACD柱 < 0

---

## 五、4个开仓信号（代码级详细条件）

### 信号① 做多A — 逆势抄底

**触发条件（全部满足）：**
```python
if trend_4h_bear and trend_1d_bear:         # 4h+1d均线空头
    if adx_4h < 40:                          # 4h ADX<40（趋势未过强）
        if pct_b < 0.2:                      # 5m %b<0.2 超卖
            if rsi < 40:                      # 5m RSI<40 超卖确认
                if adx_5m > 25:              # 5m ADX>25 趋势强度确认
                    # → return 'long', reason
```

**逻辑：** 大周期下跌趋势衰竭（但趋势不能太强），价格跌到布林下轨极端超卖，5m出现反弹迹象，逆势做多。

---

### 信号② 做多B — 顺势回调

**触发条件（全部满足）：**
```python
if trend_4h_bull and trend_1d_bull:         # 4h+1d均线多头
    if pct_b < 0.2:                          # 5m %b<0.2 布林下轨
        if 35 < rsi < 60:                    # 5m RSI 35~60 回调到位
            if adx_5m > 25:                  # 5m ADX>25 趋势强度确认
                # → return 'long', reason
```

**逻辑：** 大周期上涨趋势健康，价格回调到布林下轨支撑，RSI从低位回升确认回调结束，顺势做多。

---

### 信号③ 做空A — 顺势高抛

**触发条件（全部满足）：**
```python
if trend_4h_bull and trend_1d_bull:         # 4h+1d均线多头
    if pct_b > 0.85:                        # 5m %b>0.85 布林上轨超买
        if rsi >= 82:                       # 5m RSI>=82 极端超买
            if adx_5m > 25:                  # 5m ADX>25 趋势强度确认
                # → return 'short', reason
```

**逻辑：** 大周期上涨趋势中，价格冲到布林上轨极端超买，RSI达到82以上的极端区域，短期需要修复，顺势做空。

---

### 信号④ 做空B — 逆势摸顶

**触发条件（全部满足）：**
```python
if trend_4h_bear and trend_1d_bear:         # 4h+1d均线空头
    if adx_4h < 40:                          # 4h ADX<40（趋势未过强）
        if pct_b > 0.85:                    # 5m %b>0.85 布林上轨
            if rsi >= 82:                   # 5m RSI>=82 极端超买
                if adx_5m > 25:              # 5m ADX>25 趋势强度确认
                    # → return 'short', reason
```

**逻辑：** 大周期下跌趋势衰竭（但趋势不能太强），价格反弹到布林上轨极端超买，RSI达到82以上的极端区域，逆势做空。

---

## 六、执行流程（10秒/轮）

```
每轮循环（10秒）:
│
├── ① 刷新K线：5m + 1H + 4H + 1D
│
├── ② 检查持仓状态
│   ├── 有持仓 → 打印状态，等待止盈/止损触发
│   └── 无持仓 → 继续下一步
│
├── ③ 调用 analyzer.check() 执行三层过滤 + 4信号判断
│   │   返回: ('long', reason) / ('short', reason) / (None, reason)
│   │
│   ├── 有信号 → trader.open_position(side, reason)
│   │           → 市价开仓 + 挂止损止盈预设
│   │           → 推送微信通知
│   │           → 标记 in_position=True
│   │
│   └── 无信号 → 打印观望原因（每分钟1次）
│
└── ④ sleep(10秒) 继续下一轮
```

---

## 七、开仓执行细节

```python
# 获取当前价格
price = self.api.get_ticker()['lastPr']

# 做多止损/止盈
stop_loss = round(price * (1 - 0.015), 2)      # $2497.2 @ $2520
take_profit = round(price * (1 + 0.020), 2)   # $2570.4 @ $2520

# 做空止损/止盈
stop_loss = round(price * (1 + 0.015), 2)      # $2557.8 @ $2520
take_profit = round(price * (1 - 0.020), 2)   # $2469.6 @ $2520

# 下单接口：presetStopSurplusPrice=止盈价，presetStopLossPrice=止损价
api.place_order(
    direction=side,           # 'long' 或 'short'
    order_type='market',      # 市价单
    size='0.5',               # 0.5 ETH
    stop_surplus_price=take_profit,
    stop_loss_price=stop_loss
)
```

---

## 八、止损止盈设置

| 方向 | 止损 | 止盈 |
|------|------|------|
| 做多 | 入场价 × 0.985（-1.5%） | 入场价 × 1.020（+2.0%）全仓 |
| 做空 | 入场价 × 1.015（+1.5%） | 入场价 × 0.980（-2.0%）全仓 |

**接口参数：** `presetStopSurplusPrice`（止盈）、`presetStopLossPrice`（止损）
**注意：** 市价平仓时止盈止损预设自动撤销

---

## 九、风控机制

| 规则 | 参数 | 说明 |
|------|------|------|
| 平仓后冷却 | 300秒（5分钟） | 防止频繁开仓 |
| 连亏暂停 | 3次连亏，暂停30分钟 | 保护本金 |
| 逐仓模式 | isolated | 单笔亏损不影响整体仓位 |
| 止损执行 | 市价平仓 | 触发了立即执行 |

---

## 十、微信通知模板

**开仓通知：**
```
🚨 ETH开仓通知
━━━━━━━━━━━━━━━━
方向: 🟢 做多 / 🔴 做空
杠杆: 20x
数量: 0.5 ETH
开仓价: $xxxxx
━━━━━━━━━━━━━━━━
止损: $xxxxx (-1.5%)
止盈: $xxxxx (+2.0%) 全仓一次性
━━━━━━━━━━━━━━━━
📋 开仓理由:
【做多A】4h空头+1d空头，价格72%布林偏离
5m RSI=69.8 ADX=21.8>25，放量1.52x
4h ADX=18.9<40趋势未过强，逆势抄底
━━━━━━━━━━━━━━━━
⏰ HH:MM:SS
📋 订单号: xxxxx
```

**平仓通知：**
```
📤 ETH平仓通知
━━━━━━━━━━━━━━━━
方向: 🟢 做多
盈亏: ✅ +2.00% (+40.0%仓位损益 @20x)
━━━━━━━━━━━━━━━━
平仓理由: 止盈
━━━━━━━━━━━━━━━━
统计: 共N笔 | 胜X 负Y
━━━━━━━━━━━━━━━━
⏰ HH:MM:SS
```

---

## 十一、版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v2.3 | 2026-04-17 | 对齐BTC策略4信号系统；ADX门槛25；SignalAnalyzer重写为4信号conditional逻辑 |
| v2.2 | 2026-04-11 | 止损止盈从ATR倍数改为固定百分比 |
| v2.1 | 2026-04-10 | 新增ADX>25过滤、成交量>1.5x过滤 |
| v2.0 | 2026-04-08 | 初始版本，评分制 |

---

*本文档由 OpenClaw Agent 根据实际代码生成 | 最后更新: 2026-04-17*
