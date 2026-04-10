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
- 🔄 美股交易机器人测试 (2026-04-06 晚上美股开盘后)
  - 启动命令: `bash /root/.openclaw/workspace/start_trading.sh`
  - 测试内容: 扫描、信号分析、自动买卖、微信推送
  - 注意事项: API Key 需确认有效 (上次测试返回 apikey does exist)

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
