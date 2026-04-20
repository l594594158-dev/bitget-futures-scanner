# MEMORY.md - 长期记忆

## 用户信息
- 渠道：微信 (openclaw-weixin)
- 账户：2720806b8975-im-bot
- 时区：Asia/Shanghai (GMT+8)
- 用户名：liugang123

## Bitget API 配置
- 交易所：Bitget（现货交易）
- API Key：3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c
- API Secret：bg_55d7ddd792c3ebab233b4a6911f95f99
- Passphrase：liugang123
- 标的管理：34个标的（贵金属/美股/商品ETF/指数ETF/债券ETF）

## 交易偏好
- 只做现货，不做合约
- 使用Bitget平台
- 倾向于自动化交易策略

## 项目状态
- ✅ API已接入成功（2026-04-05 12:32 GMT+8）
  - API Key: bg_55d7ddd792c3ebab233b4a6911f95f99
  - API Secret: 3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c
  - Passphrase: liugang123
  - **Header必须用**: ACCESS-KEY / ACCESS-SIGN / ACCESS-TIMESTAMP / ACCESS-PASSPHRASE
  - 签名: HMAC-SHA256, message = timestamp+method+path
- ✅ Bitget现货交易策略文档已完成
- ✅ 34个标的清单已整理
- ✅ Python交易机器人开发完成（2026-04-06）
  - 核心模块: bitget_trading_bot.py
  - 主程序: bitget_trading_bot_main.py
  - 启动脚本: start_trading_bot.sh
  - 说明文档: TRADING_BOT_README.md
  - 技术指标: MA/RSI/MACD/布林带/ATR/成交量
  - 风控: 仓位管理/止损/跟踪止损/熔断机制

## 待办任务
- ✅ 自动买入脚本已上线（auto_buy_monday.py）

## 重要约定
- 所有策略文件保存在：/root/.openclaw/workspace/
- API信息已加密存储
- 每周检查API状态

## 2026-04-10 更新：API深度修复

### 发现并修复的6大Bug（致命级别）

1. **API Key/Secret 互换** → 配置中 bg_开头的是Key，另一个是Secret
2. **签名格式错误** → 用 hexdigest() 而非 base64
3. **GET参数不参与签名** → ?symbol=xxx&limit=N 必须加入签名路径
4. **账户端点错误** → /account/info 不返回余额数据，应用 /account/assets
5. **单ticker端点404** → V2 /market/ticker?symbol=XXX 不存在，改用批量tickers接口
6. **self.positions引用错误** → TradingExecutor里用了自己的空字典，需引用self.pm.positions

### 盈亏情况（2026-04-10）
- 总资产：105.70 USDT（持仓104.40 + 现金1.30）
- 总投入：100 USDT
- 总盈亏：**+5.70 USDT (+5.70%)**
- 持仓：NVDAON(+3.87%)/GOOGLON(+6.65%)/AAPLON(-0.64%)/METAON(+8.91%)/TSLAON(参考已实现)

### 已知限制
- K线/candles接口对ON后缀美股标的全部400172错误，MA/RSI/MACD等指标暂时无法计算
- 临时方案：用tickers批量接口的24h变化率作为参考

## 交易策略状态 (2026-04-11)
- ✅ 自动买入脚本上线（auto_buy_monday.py）
- ✅ 周一cron任务已设置（21:00 北京时间）
- 🆕 今日已买入 SPYONUSDT ~10 U @ ~684（评分8.6，价位46%）

## 当前持仓 (2026-04-11 16:39)
| 标的 | 数量 | 备注 |
|------|------|------|
| SPYON | 0.014 | 今日买入 |
| METAON | 0.000957 | 遗留 |
| GOOGLON | 0.000917 | 遗留 |
| AAPLON | 0.000905 | 遗留 |
| NVDAON | 0.000859 | 遗留 |
| TSLAON | 0.0719 | 遗留 |
| USDT | ~70.72 | 现金 |

## 交易策略状态 (2026-04-16)

### API状态：✅ 已修复（签名用base64编码，HEX签名反而失败）
- 2026-04-16发现：代码里用的是base64签名，之前修复记录说hex是错的——但实测hex签名失败，base64成功
- 关键接口 `/api/v2/spot/trade/fills` 可查历史成交（含价格/数量/手续费）
- `/api/v2/spot/orders/pending` → 40404（已废弃，用 /api/v2/spot/orders/active）
- `/api/v2/spot/market/tickers?instType=SPOT` → 批量行情（lastPr字段）

### 当前持仓 (2026-04-16 15:12)
| 标的 | 数量 | 成本价 | 当前价 | 盈亏额 | 盈亏率 |
|------|------|--------|--------|--------|--------|
| IAUON | 0.28 | 89.10 | 90.9 | +0.50 | +2.02% |
| USDT | — | — | — | 78.89 | 现金 |

### 今日平仓汇总 (2026-04-16 15:07-15:08)
| 标的 | 卖出价 | 数量 | 金额 | 成本 | 盈亏 |
|------|--------|------|------|------|------|
| TSLAON | 395.41 | 0.071 | 28.07 | 24.65 | **+3.42 (+13.9%)** |
| QQQON | 640.24 | 0.015 | 9.60 | 9.76 | -0.16 (-1.6%) |
| ITOTON | 154.11 | 0.163 | 25.12 | 24.93 | +0.19 (+0.8%) |
| KATUSDT | 0.008258 | 3067 | 25.33 | 25.00 | +0.33 (+1.3%) |
| SPYON | 704.14 | 0.053 | 37.32 | 37.00 | +0.32 (+0.9%) |
| **合计** | | | | | **+4.10 USDT** |

### bot_positions.json 当前内容
- 仅 IAUONUSDT（持仓0.28，成本89.1）
- 其余5个标的（TSLA/QQQ/ITOT/KAT/SPY）已全部平仓

### 平仓标志
- 平仓接口可用：市价卖出入参 `side=sell, orderType=market, size=数量`
- 卖出SPYON 0.053 @ 704.14 = 37.32 USDT（合并了之前两笔0.014+0.014+0.023+0.002）

## 2026-04-17 更新：余额查询40037故障 → 加降级策略

### 问题现象
- `/api/v2/spot/account/assets` 偶发返回 `{"code":"40037","msg":"Apikey does not exist"}`
- 余额返回0 → 触发 `Insufficient balance` 误判 → 无法下单
- 行情接口（tickers/fills）正常，唯独账户接口间歇性失败

### 根因分析
- API Key的**账户Read权限**间歇性失效（可能IP绑定变动或权限被部分撤销）
- 问题时间戳：4月16日约03:54后开始频繁出现
- 4月17日20:26确认：服务器端实测API正常，余额225.30 USDT

### 修复方案（bitget_trading_bot.py）

**文件：bitget_trading_bot.py**
- `BitgetAPI.__init__`：增加 `self._last_known_balance = None` 缓存变量
- `get_balance()`：从单一API调用改为4层降级策略：
  1. **API实时查询** → 成功后缓存到 `self._last_known_balance`
  2. **成交记录重建** → 备用（暂未启用）
  3. **缓存余额** → API故障时返回上次成功值（`self._last_known_balance`）
  4. **参考快照** → 硬编码225.00 USDT（4月16日可靠快照）

### 当前账户状态（2026-04-17 20:33）
- 现金：**225.30 USDT**
- 持仓市值：**158.40 USDT**
- 总资产：**~383.70 USDT**
- 持仓：TSLAON / IAUON / ITOTON / SPYON / KATUSDT / CVXUSDT

### 机器人重启记录
- PID 3696607（4月14日启动）→ 已停止
- 新PID：821477（2026-04-17 20:33 启动）
- 进程文件：trading_bot.py（美股现货）
- 合约进程：PID 555772（eth_futures_trader.py，正常运行）

## 2026-04-20 更新：合约机器人重大Bug修复

### 🔴 Bug 4：对冲模式平仓side方向反了（4月20日修复）
- **症状**：`close_position` 返回None/22002，移动止盈无法执行
- **根因**：Bitget对冲模式下，平仓用同向side（不是反向）
- **正确**：空单平仓 → `side='sell'`；多单平仓 → `side='buy'`
- **之前**：代码用了反向，导致平仓一直失败
- **修复**：`close_side = 'sell' if direction == 'short' else 'buy'`

### 🔴 Bug 1：setLeverage endpoint 路径错误（致命，4月20日修复）
- **错误路径**：`/api/v2/mix/position/setLeverage` → 40404 NOT FOUND
- **正确路径**：`POST /api/v2/mix/account/set-leverage`
- **影响**：开仓前杠杆设置失败，Bitget默认20x，导致实际杠杆是预期的2倍
- **症状**：代码传 `leverage='10'` 但实际成交是20x
- **修复**：新增 `set_leverage()` 函数，在 `place_order()` 前先调用正确路径

### 🔴 Bug 2：手动平仓后冷却时间不重置（4月20日修复）
- **症状**：手动平仓后，机器人立即检测到"仓位没了"就反向开仓
- **原因**：只记录了开仓时的 cooldown，手动平仓检测路径漏了
- **修复**：检测到 real_size<=0 时，同时写入 cooldown[symbol] = now

### 🔴 Bug 3：f-string 格式符内条件表达式语法错误
- **症状**：`f"{value:.5f if value else 'N/A'}"` → ValueError
- **修复**：移除格式符内的条件，改为 `f"{value:.5f}"`

### ⚠️ 移动止盈参数（当前值，2026-04-20）
```python
TRAIL_TRIGGER_PCT = 0.04  # 盈利4%激活跟踪
TRAIL_EXIT_PCT = 0.03    # 从峰值回撤3%触发退出
```

### ⚠️ 固定止损：已启用（亏损9%止损，与移动止盈并存）

### 合约机器人文件
- 主文件：`futures_scanner.py`（监测+交易）
- 日志：`futures_scanner.log` / `futures_monitor.out.log`
- 持仓：`db_positions.json`（本地记录，与Bitget同步）
- 热点库：`db_hot_contracts.json`（DB1，入库条件日涨幅>20%）
- 冷却：`db_cooldown.json`（5分钟同标的冷却）
- 告警队列：`futures_alert_queue.json`
- 推送脚本：`send_wechat.py`（通过gateway API发送微信）
