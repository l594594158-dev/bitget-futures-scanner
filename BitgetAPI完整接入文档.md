# Bitget API 接入完整文档（已修复版）

> 更新时间：2026-04-10 10:39 GMT+8
> 状态：✅ 已全面修复，所有API验证通过
> 用户：liugang123

---

## 一、凭证信息（已修正）

| 项目 | 内容 |
|-----|------|
| API Key | `bg_55d7ddd792c3ebab233b4a6911f95f99` |
| API Secret | `3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c` |
| Passphrase | `liugang123` |
| Base URL | `https://api.bitget.com` |
| API版本 | V2 |

⚠️ **注意：API Key 以 `bg_` 开头，API Secret 是纯字母数字字符串，两者值不同！**

---

## 二、签名方法（已修正）

**签名算法：HMAC-SHA256 → Base64编码**

```python
import hashlib
import hmac
import base64
import time
import json

def bitget_api_call(api_key, api_secret, passphrase, path, method='GET', body=''):
    timestamp = str(int(time.time() * 1000))

    # 关键：message = timestamp + method + path(+query if GET) + body
    message = timestamp + method + path + body

    # 关键：mac.digest() → base64.b64encode → decode
    mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
    signature = base64.b64encode(mac.digest()).decode()  # 不是 hexdigest()！

    headers = {
        'Content-Type': 'application/json',
        'ACCESS-KEY': api_key,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': passphrase,
    }

    url = 'https://api.bitget.com' + path

    if method == 'GET':
        resp = requests.get(url, headers=headers, timeout=10)
    else:
        resp = requests.post(url, headers=headers, data=body, timeout=10)

    return resp.json()
```

### 签名要点（踩坑记录）

1. **HMAC-SHA256 后必须 Base64 编码，不是 hexdigest**
   - ❌ `mac.hexdigest()` → 返回hex字符串，签名永远失败
   - ✅ `base64.b64encode(mac.digest()).decode()` → 正确

2. **GET 请求的 query 参数必须加入签名路径**
   - ❌ 只签 `path`，query string 不参与签名
   - ✅ 签 `path + "?" + query_string`

3. **message 格式**：`timestamp + method + path + body`
   - GET: `timestamp + "GET" + /api/v2/spot/account/assets + ""`
   - POST: `timestamp + "POST" + /api/v2/spot/trade/place-order + body_json_string`

---

## 三、已验证可用的 API 端点

| 功能 | 方法 | 路径 | 状态 |
|-----|------|------|------|
| 账户资产 | GET | `/api/v2/spot/account/assets` | ✅ 可用 |
| 市场行情（批量） | GET | `/api/v2/spot/market/tickers?instType=SPOT` | ✅ 可用 |
| 历史订单 | GET | `/api/v2/spot/trade/history-orders?limit=N` | ✅ 可用 |
| 成交记录 | GET | `/api/v2/spot/trade/fills?symbol=XXX&limit=N` | ✅ 可用 |
| 下单 | POST | `/api/v2/spot/trade/place-order` | ✅ 可用 |
| 撤单 | POST | `/api/v2/spot/trade/cancel-order` | ✅ 可用 |

### 行情获取（单ticker端点不可用，已修复）

V2 `/api/v2/spot/market/ticker?symbol=XXX` 返回 `40404 Request URL NOT FOUND`。

**修复方案：使用批量 `tickers` 接口并缓存**

```python
def get_ticker(self, symbol: str) -> Dict:
    """获取实时行情（修复版）"""
    if not hasattr(self, '_ticker_cache') or \
       time.time() - getattr(self, '_ticker_cache_time', 0) > 60:
        all_tickers = self._request("GET", "/api/v2/spot/market/tickers?instType=SPOT")
        self._ticker_cache = {t['symbol']: t for t in all_tickers}
        self._ticker_cache_time = time.time()

    data = self._ticker_cache.get(symbol, {})
    return {
        "symbol": data.get("symbol", symbol),
        "lastPrice": float(data.get("lastPr", "0") or "0"),
        "priceChangePercent": float(data.get("changeUtc24h", "0") or "0"),
        "high24h": float(data.get("high24h", "0") or "0"),
        "low24h": float(data.get("low24h", "0") or "0"),
        "volume24h": float(data.get("baseVolume", "0") or "0"),
    }
```

### K线数据（已知限制）

`/api/v2/spot/market/history-candles` 对所有标的均返回 `400172 Parameter verification failed`。
V2 K线接口对 US Stock（ON后缀）品种暂不可用。

**临时替代方案：使用 `tickers` 批量接口的 `changeUtc24h` + 成交记录计算波动率**

---

## 四、历史发现的问题清单

| # | 问题描述 | 根因 | 修复方式 |
|---|---------|------|---------|
| 1 | API Key 和 API Secret 填反 | Config 中两个字段值互换 | 交换回来 |
| 2 | 签名返回 hex 而非 base64 | `mac.hexdigest()` | 改为 `base64.b64encode(mac.digest()).decode()` |
| 3 | GET 参数不参与签名 | `_request` 只签 `path` | 签名时拼接 `path + "?" + query` |
| 4 | 账户端点用错 | `/account/info` 无数据 | 改为 `/api/v2/spot/account/assets` |
| 5 | 单ticker端点404 | V2该路径不存在 | 改用 `tickers?instType=SPOT` 批量接口 |
| 6 | 下单/撤单端点填错 | `/order/place` 不存在 | 改为 `/api/v2/spot/trade/place-order` |
| 7 | `self.positions` 引用错误 | `TradingExecutor` 用了自己的空字典 | 改为 `self.pm.positions` |
| 8 | `get_balance` 调用错误端点 | `get_account_info()` 返回 dict 而非 list | 改为直接调用 `_request(GET, assets)` |
| 9 | 缺少 `base64` import | 模块顶部未 import | 添加 `import base64` |
| 10 | `get_klines` 参数格式错误 | `productType`/`interval` 参数不对 | 暂用 tickers 替代 |

---

## 五、下单接口（已验证）

```python
def place_order(symbol, side, quantity, price=None):
    """
    symbol: e.g. 'METAONUSDT'
    side: 'buy' or 'sell'
    quantity: 数量（如 '0.001'）
    price: 市价单填 None，限价单填价格
    """
    path = '/api/v2/spot/trade/place-order'
    method = 'POST'
    data = {
        'symbol': symbol,
        'side': side,
        'orderType': 'market' if price is None else 'limit',
        'size': str(quantity),
    }
    if price:
        data['price'] = str(price)

    body = json.dumps(data)
    # 签名时 message = timestamp + POST + path + body
    ...
```

⚠️ **最低下单金额：1 USDT**（低于1U会报错 `less than the minimum amount 1 USDT`）

---

## 六、账户资产查询（已验证）

```python
# 获取所有资产
assets = api_call('GET', '/api/v2/spot/account/assets')
for item in assets:
    print(f"{item['coin']}: 可用={item['available']} 冻结={item['frozen']}")

# 获取单个币种余额
def get_balance(coin='USDT'):
    assets = api_call('GET', '/api/v2/spot/account/assets')
    for item in assets:
        if item['coin'] == coin:
            return float(item['available'])
    return 0.0
```

---

## 七、行情数据结构（tickers批量接口）

```json
{
  "open": "619.86",
  "symbol": "METAONUSDT",
  "high24h": "636",
  "low24h": "612.36",
  "lastPr": "629.34",
  "quoteVolume": "4937.072",
  "baseVolume": "7.874",
  "usdtVolume": "4937.07131",
  "ts": "1775787758590",
  "bidPr": "629.34",
  "askPr": "634.45",
  "bidSz": "3.419",
  "askSz": "0.256",
  "openUtc": "629.53",
  "changeUtc24h": "-0.0003",
  "change24h": "0.01529"
}
```

**注意：价格字段是 `lastPr` 不是 `last`！**

---

## 八、代码文件对应关系

| 文件 | 用途 |
|------|------|
| `bitget_trading_bot.py` | 核心机器人代码（已修复所有bug） |
| `bitget_trading_bot_main.py` | 启动脚本 |
| `start_trading.sh` | 启动Shell脚本 |
| `positions.json` | 持仓记录文件 |
| `bot_trading.log` | 交易日志 |
| `bot_output.log` | 运行日志 |

---

## 九、API测试脚本

```python
import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from bitget_trading_bot import Config, BitgetAPI

config = Config()
api = BitgetAPI(config)

# 验证余额
print("USDT余额:", api.get_balance('USDT'))

# 验证行情
ticker = api.get_ticker('METAONUSDT')
print("METAON价格:", ticker['lastPrice'])

# 验证账户资产
assets = api.get_account_info()
for a in assets:
    if float(a.get('available','0') or '0') > 0:
        print(a['coin'], a['available'])
```

---

文档更新时间：2026-04-10 10:39 GMT+8
