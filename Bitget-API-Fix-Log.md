# Bitget API 修复记录日志
# Bitget-API-Fix-Log.md
# 每次修复API问题时在此文件追加记录
# 格式：## [日期] 问题描述 | 修复方案 | 状态

---

## [2026-04-10 10:39 GMT+8] 第1次修复记录

### 问题6：TradingExecutor 中 self.positions 引用错误
- **文件**：`bitget_trading_bot.py`
- **位置**：`calculate_position_size()` 方法（约第885行）
- **现象**：机器人无法平仓，止盈止损逻辑完全失效
- **根因**：`TradingExecutor` 类有自己的 `self.positions = {}` 空字典，引用了错误的实例变量
- **修复**：
  ```python
  # 修复前（错误）
  current_prices = {s: self.get_current_price(s) for s in self.positions.keys()}
  total_position = self.get_total_position_value(current_prices)

  # 修复后（正确）
  current_prices = {s: self.get_current_price(s) for s in self.pm.positions.keys()}
  total_position = self.pm.get_total_position_value(current_prices)
  ```
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:35 GMT+8] 第2次修复记录

### 问题5：单ticker端点返回404，get_ticker完全失效
- **文件**：`bitget_trading_bot.py`
- **位置**：`get_ticker()` 方法
- **现象**：调用 `/api/v2/spot/market/ticker?symbol=METAONUSDT` 返回 `40404 Request URL NOT FOUND`
- **根因**：Bitget V2 API 中 `/market/ticker?symbol=XXX` 单票查询接口不存在
- **修复**：改用批量接口 `tickers?instType=SPOT` 并缓存60秒
  ```python
  def get_ticker(self, symbol: str) -> Dict:
      if not hasattr(self, '_ticker_cache') or \
         time.time() - getattr(self, '_ticker_cache_time', 0) > 60:
          all_tickers = self._request("GET", "/api/v2/spot/market/tickers?instType=SPOT")
          self._ticker_cache = {t['symbol']: t for t in all_tickers}
          self._ticker_cache_time = time.time()
      data = self._ticker_cache.get(symbol, {})
      return {
          "lastPrice": float(data.get("lastPr", "0") or "0"),  # 注意是 lastPr 不是 last
          ...
      }
  ```
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:32 GMT+8] 第3次修复记录

### 问题4：GET请求参数未参与签名（签名路径错误）
- **文件**：`bitget_trading_bot.py`
- **位置**：`_request()` 方法
- **现象**：`get_filled_orders()` 调用时报 `sign signature error`
- **根因**：签名时只用了 `path`，没有把 GET 的 query string 拼接进去
  - 签名消息应为 `timestamp + method + path + "?" + query_string + body`
  - 但代码只签了 `path + body`
- **修复**：
  ```python
  # 修复前（错误）
  sign_path = path

  # 修复后（正确）
  sign_path = path
  if params:
      query = "&".join([f"{k}={v}" for k, v in params.items()])
      url += "?" + query
      sign_path += "?" + query  # 签名路径也要包含query
  ```
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:28 GMT+8] 第4次修复记录

### 问题3：签名使用hexdigest而非base64（致命错误）
- **文件**：`bitget_trading_bot.py`
- **位置**：`_sign()` 方法（第182行）
- **现象**：所有API调用都报 `sign signature error`
- **根因**：`mac.hexdigest()` 返回16进制字符串，Bitget 要求 base64 编码的签名
- **修复**：
  ```python
  # 修复前（错误）
  return mac.hexdigest()

  # 修复后（正确）
  return base64.b64encode(mac.digest()).decode()
  ```
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:25 GMT+8] 第5次修复记录

### 问题2：缺少 base64 模块 import
- **文件**：`bitget_trading_bot.py`
- **位置**：文件头部 import 区
- **现象**：`name 'base64' is not defined`
- **根因**：新增 `base64.b64encode()` 调用但未 import base64 模块
- **修复**：在 import 区添加 `import base64`
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:22 GMT+8] 第6次修复记录

### 问题1：API Key 和 API Secret 值互换（最严重错误）
- **文件**：`bitget_trading_bot.py`
- **位置**：`Config` 类（约第25-26行）
- **现象**：API返回 `apikey does exist` 或 `sign signature error`
- **根因**：Config 中 `API_KEY` 字段填的是 Secret 的值，`API_SECRET` 字段填的是 Key 的值
  - `API_KEY = "3d485fc..."` ← 实际是Secret
  - `API_SECRET = "bg_55d7..."` ← 实际是Key
- **修复**：
  ```python
  # 修复前（错误）
  API_KEY = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
  API_SECRET = "bg_55d7ddd792c3ebab233b4a6911f95f99"

  # 修复后（正确）
  API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"       # bg_开头是Key
  API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
  ```
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:20 GMT+8] 第7次修复记录

### 额外修复1：账户端点错误
- **文件**：`bitget_trading_bot.py`
- **位置**：`get_account_info()` 方法
- **根因**：错误使用 `/api/v2/spot/account/info`（返回用户信息，无余额数据）
- **修复**：改为 `/api/v2/spot/account/assets`（返回余额数据）
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:20 GMT+8] 第8次修复记录

### 额外修复2：下单/撤单端点错误
- **文件**：`bitget_trading_bot.py`
- **位置**：`place_order()` 和 `cancel_order()` 方法
- **根因**：错误使用 `/api/v2/spot/order/place`（不存在）和 `/api/v2/spot/order/cancel`（不存在）
- **修复**：
  - 下单改为 `/api/v2/spot/trade/place-order` ✅ 已验证可用
  - 撤单改为 `/api/v2/spot/trade/cancel-order` ✅ 已验证可用
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:20 GMT+8] 第9次修复记录

### 额外修复3：缺少 PASSPHRASE 配置
- **文件**：`bitget_trading_bot.py`
- **位置**：`Config` 类
- **根因**：只添加了 `API_KEY` 和 `API_SECRET`，遗漏了 `PASSPHRASE`
- **修复**：添加 `PASSPHRASE = "liugang123"`
- **状态**：✅ 已修复并验证

---

## [2026-04-10 10:20 GMT+8] 已知限制记录

### K线/candles接口不可用
- **文件**：`bitget_trading_bot.py`
- **位置**：`get_klines()` 方法
- **现象**：所有标的的 `/api/v2/spot/market/history-candles` 均返回 `400172 Parameter verification failed`
- **影响**：MA/RSI/MACD/布林带等技术指标无法计算，策略信号生成受阻
- **临时方案**：使用 `tickers?instType=SPOT` 批量接口的 `changeUtc24h` 变化率作为参考
- **状态**：⚠️ 待解决（Bitget V2 API 对 ON后缀美股品种暂不支持K线）

---

# 修复记录追加模板
# ============================================
# 以后每次修复，在此处下方追加：
#
# ## [YYYY-MM-DD HH:MM GMT+8] 第N次修复记录
# ### 问题N：xxx
# - 文件：
# - 位置：
# - 现象：
# - 根因：
# - 修复：
#   ```python
#   # 修复前
#   xxx
#   # 修复后
#   xxx
#   ```
# - 状态：✅/⚠️
# ============================================

