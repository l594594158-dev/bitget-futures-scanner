# Bitget 美股现货交易机器人

## 📋 简介

这是一个基于 Bitget 交易所的 **美股现货自动交易机器人**，支持 34 个交易标的（贵金属、美股、ETF等）。

## 🎯 功能特性

- ✅ **只做现货** - 不使用合约/杠杆，规避爆仓风险
- ✅ **技术分析** - MA、RSI、MACD、布林带等技术指标
- ✅ **自动交易** - 自动买入、止损、止盈
- ✅ **仓位管理** - 分级仓位控制，最大持仓 80%
- ✅ **风控体系** - 日亏损熔断、跟踪止损、连续亏损减仓
- ✅ **34个标的** - 贵金属/美股/商品ETF/指数ETF/债券ETF

## 📁 文件结构

```
workspace/
├── bitget_trading_bot.py      # 核心交易逻辑
├── bitget_trading_bot_main.py # 主程序入口
├── start_trading_bot.sh       # 启动脚本
├── trading_bot.log            # 运行日志
├── positions.json             # 仓位记录
├── trade_history.json         # 交易历史
└── TRADING_BOT_README.md      # 本说明
```

## 🚀 快速开始

### 1. 测试扫描（推荐先运行）

```bash
cd /root/.openclaw/workspace
python3 bitget_trading_bot_main.py --mode scan
```

这会扫描所有 34 个标的，生成信号报告，**不会进行实际交易**。

### 2. 实盘运行

```bash
python3 bitget_trading_bot_main.py --mode live
```

机器人将持续运行，每分钟扫描一次信号并执行交易。

### 3. 定时任务模式

```bash
python3 bitget_trading_bot_main.py --mode schedule
```

每天定时执行：
- 22:00 (美股开盘前)
- 02:00 (美股盘中)
- 09:00 (美股收盘后)

## 📊 交易标的

| 类别 | 标的 | 仓位上限 | 止损 |
|-----|------|---------|------|
| 贵金属 | XAUUSD, XAGUSD | 10% | 5% |
| 美股A+ | TSLA, NVDA, COIN, MARA, RIOT | 5% | 8% |
| 美股A级 | AMD, ARM, PLTR, SNOW, QBTS | 8% | 6% |
| 美股B/C级 | AAPL, META, AMZN, GOOGL, NFLX... | 10% | 5% |
| 中概股 | BIDU, PDD, GRAB | 5% | 8% |
| 商品ETF | GLD, USO, COPX, REMX | 10% | 5% |
| 指数ETF | TQQQ, SQQQ, VTI | 10% | 8% |
| 债券ETF | SGOV | 20% | 无 |

## 🎮 信号评分系统

| 评分 | 信号 | 操作 |
|-----|------|------|
| ≥4 | 强烈买入 | 买入 |
| ≤-4 | 强烈卖出 | 卖出 |
| <4 且 >-4 | 中性 | 观望 |

**评分因素：**
- 均线多头排列 (+2)
- RSI超卖 (+2)
- MACD金叉 (+1~2)
- 布林下轨 (+1)
- 成交量放大 (+1)

## ⚠️ 风险管理

| 规则 | 限制 |
|-----|------|
| 单笔最大仓位 | 账户 20% |
| 总持仓上限 | 账户 80% |
| 日最大亏损 | 3% |
| 月最大亏损 | 10% |
| 连续亏损2次 | 仓位减半 |
| 连续亏损5次 | 当日停止 |

## 🔧 配置说明

配置文件：`bitget_trading_bot.py` 中的 `Config` 类

主要配置项：
- `API_KEY` / `API_SECRET` - Bitget API 密钥
- `MAX_TOTAL_POSITION` - 总持仓上限 (默认 80%)
- `DAILY_LOSS_LIMIT` - 日亏损限制 (默认 3%)
- `SCAN_INTERVAL` - 扫描间隔 (默认 60秒)

## 📝 查看日志

```bash
# 实时查看日志
tail -f trading_bot.log

# 查看最近100行
tail -100 trading_bot.log
```

## 🛑 停止机器人

在运行中的终端按 `Ctrl+C`，或发送停止信号。

## ⚠️ 风险提示

- 本机器人仅供技术研究使用
- 外汇/加密货币交易存在极高风险
- 请勿投入超过承受能力的资金
- 过去表现不代表未来收益
- 建议先用模拟盘或小额资金测试

## 📞 支持

如有问题，请检查：
1. `trading_bot.log` 错误日志
2. API 密钥是否正确
3. 网络连接是否正常
4. 账户余额是否充足

---

*交易有风险，投资需谨慎*
