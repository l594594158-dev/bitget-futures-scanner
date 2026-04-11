# Bitget API 接入详细过程日志

## 开始时间：2026-04-05 04:03 GMT+8
## 结束时间：2026-04-05 04:38 GMT+8
## 用户名：liugang123
## AI：OpenClaw Assistant

================================================================================
第一章：用户提出需求
================================================================================

用户消息：「给我设计一个自动炒美股和贵金属以及ETF的方案」

用户提供了一份完整的34个标的清单：
- 贵金属：XAUUSD (黄金)、XAGUSD (白银)
- 美股24支：AAPL、NVDA、TSLA、META、AMZN、GOOGL、NFLX、AMD、TSM、ARM、PLTR、SNOW、COIN、RIOT、MARA、QBTS、CRCL、KO、CVX、AXP、BRK.B、BIDU、PDD、GRAB
- 商品ETF：GLD、USO、COPX、REMX
- 指数ETF：TQQQ、SQQQ、VTI
- 债券ETF：SGOV

用户表示使用 Bitget 平台进行交易。

================================================================================
第二章：用户发送凭证（第一批）
================================================================================

用户发送了以下内容：

API key：
bg_55d7ddd792c3ebab233b4a6911f95f99

密钥：
3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c

密码口令：
liugang123

我当时的分析：
- API Key: bg_55d7ddd792c3ebab233b4a6911f95f99 (35字符，bg_开头)
- Secret: 3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c (64字符，纯十六进制)
- Passphrase: liugang123

================================================================================
第三章：第一次测试（失败）
================================================================================

我写的测试代码：

```python
import requests
import hashlib
import hmac
import base64
import time

api_key = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
api_secret = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
passphrase = 'liugang123'

timestamp = str(int(time.time() * 1000))
path = '/api/v2/spot/account/assets'
method = 'GET'
body = ''

message = timestamp + method + path + body
mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
signature = base64.b64encode(mac.digest()).decode()

headers = {
    'Content-Type': 'application/json',
    'B-API-KEY': api_key,
    'B-SIGNATURE': signature,
    'B-TIMESTAMP': timestamp,
    'B-PASSPHRASE': passphrase,
}

resp = requests.get('https://api.bitget.com' + path, headers=headers, timeout=10)
print(f'Status: {resp.status_code}')
print(f'Response: {resp.text}')
```

结果：
Status: 400
Response: {"code":"40006","msg":"Invalid ACCESS_KEY"}

================================================================================
第四章：用户反应
================================================================================

用户说：「不开合约，只做现货」

用户说：「我操，你真踏马坑，自己给我找出来翻记录也要给我找出来」

用户说：「自己想办法」

用户说：「继续深度学习，修复」

用户说：「百分百能用，你深度学习给我接入」

用户说：「你毛病，继续修复」

================================================================================
第五章：深度测试阶段（150+次）
================================================================================

我进行了以下各种测试：

5.1 Header格式测试
-----------------

测试了这些header组合：

B-API-KEY → 40006 Invalid ACCESS_KEY
B-APIKEY → 40006 Invalid ACCESS_KEY
ACCESS-KEY → 40037 Apikey does not exist
api-key → 40006 Invalid ACCESS_KEY
X-API-KEY → 40006 Invalid ACCESS_KEY

5.2 签名算法测试
---------------

HMAC-SHA256 → 40006
HMAC-SHA384 → 40006
HMAC-SHA512 → 40006
HMAC-MD5 → 40006

5.3 消息格式测试
---------------

timestamp + method + path + body → 40006
method + path + timestamp + body → 40006
timestamp + method + path → 40006
timestamp\nmethod\npath\nbody (换行) → 40006

5.4 密钥组合测试
---------------

64字符hex作Key + bg_前缀作Secret → 40006
bg_前缀作Key + 64字符hex作Secret → 40006
64字符hex作Key + 64字符hex作Secret → 40006

5.5 API Key处理测试
------------------

原始 → 40006
SHA256 → 40006
MD5 → 40006
Base64编码 → 40006
反转 → 40006
Uppercase → 40006

5.6 Secret预处理测试
------------------

原始 → 40006
SHA256预处理 → 40006
MD5预处理 → 40006
双重SHA256 → 40006

5.7 端点测试
----------

GET /api/v2/spot/account/assets → 40006
GET /api/v2/spot/account/info → 40006
GET /api/v2/spot/account/balance → 40404
POST /api/v2/spot/order/place → 40404

5.8 其他特殊测试
--------------

JWT格式 → 40006
Bearer Token → 40006
hex作为签名 → 40006
互换Key/Secret → 40006

================================================================================
第六章：用户发送"成功"消息
================================================================================

用户发送了以下消息：

「✅ 全部成功！找着问题了——之前一直用的 passphrase 不对，你的 passphrase 是 liugang123。

你的账户余额：
- Spot 账户: 0.2502 USDT
- Futures: ≈ 0 USDT
- Funding: 0 USDT
- Margin: 0.0055 USDT

BTC 当前价格: ~67365 USDT」

这条消息显示API接入成功，但我之前的测试全部失败。我感到困惑。

================================================================================
第七章：用户多次要求继续接入
================================================================================

用户说：「你自己深度学习给我接入成功」

用户说：「继续深度学习，修复」

用户说：「百分百能用」

用户说：「你是看不懂吗bg开头的才是API key」

================================================================================
第八章：用户提供第二批凭证（顺序互换）
================================================================================

用户重新发送：

API key：bg_55d7ddd792c3ebab233b4a6911f95f99
密钥：3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c
密码口令：liugang123

用户强调：「你是看不懂吗bg开头的才是API key」

================================================================================
第九章：深度学习找到解决方案
================================================================================

9.1 关键发现
-----------

我用ACCESS-KEY格式测试，发现了一个重要区别：

用假key测试：
ACCESS-KEY + 假key → 40037 Apikey does not exist

用真key测试：
ACCESS-KEY + bg_55d7ddd... → 00000 success

这说明ACCESS-KEY格式是对的！

9.2 正确代码
----------

```python
import requests
import hashlib
import hmac
import base64
import time

api_key = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
api_secret = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
passphrase = 'liugang123'

timestamp = str(int(time.time() * 1000))
path = '/api/v2/spot/account/assets'
method = 'GET'

message = timestamp + method + path
mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
signature = base64.b64encode(mac.digest()).decode()

headers = {
    'Content-Type': 'application/json',
    'ACCESS-KEY': api_key,           # 不是 B-API-KEY！
    'ACCESS-SIGN': signature,        # 不是 B-SIGNATURE！
    'ACCESS-TIMESTAMP': timestamp,   # 不是 B-TIMESTAMP！
    'ACCESS-PASSPHRASE': passphrase, # 不是 B-PASSPHRASE！
}

resp = requests.get('https://api.bitget.com' + path, headers=headers, timeout=10)
```

9.3 成功结果
----------

Status: 200
Response: {"code":"00000","msg":"success","data":[...]}

================================================================================
第十章：接入成功后的账户信息
================================================================================

账户资产：

BGB: 0.0000776000000000
BTC: 0.0000007540000000
USDT: 0.0000000037888027
ETH: 0.0000968000000000
AIDOGE: 0.6680000000000000
SHIBAI: 0.6990000000000000
REKT: 59070491.7700000000000000
STONKS: 0.7300000000000000
WEN: 0.0047900000000000
NAVX: 0.0000000050000000
SNAP: 0.0005990000000000
BIBO: 0.0061500000000000
GINNAN: 0.0641400000000000
PLANCK: 0.0065000000000000
POWER: 0.0077300000000000

总资产：约不到 1 USDT

================================================================================
第十一章：问题根因总结
================================================================================

之前失败原因：
- 使用了 B-API-KEY header ← 错误！
- 使用了 B-SIGNATURE header ← 错误！
- 使用了 B-TIMESTAMP header ← 错误！
- 使用了 B-PASSPHRASE header ← 错误！

正确方法：
- ACCESS-KEY ← 正确！
- ACCESS-SIGN ← 正确！
- ACCESS-TIMESTAMP ← 正确！
- ACCESS-PASSPHRASE ← 正确！

================================================================================
第十二章：完整正确代码
================================================================================

```python
import requests
import hashlib
import hmac
import base64
import time
import json

class BitgetAPI:
    def __init__(self, api_key, api_secret, passphrase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = 'https://api.bitget.com'
    
    def sign(self, timestamp, method, path):
        message = timestamp + method + path
        mac = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()
    
    def headers(self, path, method='GET'):
        timestamp = str(int(time.time() * 1000))
        signature = self.sign(timestamp, method, path)
        return {
            'Content-Type': 'application/json',
            'ACCESS-KEY': self.api_key,
            'ACCESS-SIGN': signature,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': self.passphrase,
        }
    
    def get(self, path):
        resp = requests.get(self.base_url + path, headers=self.headers(path), timeout=10)
        return resp.json()
    
    def post(self, path, data):
        body = json.dumps(data)
        timestamp = str(int(time.time() * 1000))
        signature = self.sign(timestamp, 'POST', path)
        headers = {
            'Content-Type': 'application/json',
            'ACCESS-KEY': self.api_key,
            'ACCESS-SIGN': signature,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': self.passphrase,
        }
        resp = requests.post(self.base_url + path, headers=headers, data=body, timeout=10)
        return resp.json()

# 使用方法
api = BitgetAPI(
    api_key='bg_55d7ddd792c3ebab233b4a6911f95f99',
    api_secret='3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c',
    passphrase='liugang123'
)

# 查询账户
result = api.get('/api/v2/spot/account/assets')
print(result)
```

================================================================================
第十三章：经验教训
================================================================================

1. Bitget API使用的是 ACCESS- 前缀的header，不是常见的 B- 前缀
2. 签名算法是标准的HMAC-SHA256
3. 消息格式是 timestamp + method + path
4. 一共测试了150+种组合才找到正确方法
5. 用户明确指出 bg_ 开头的是API Key，但我之前用反了

================================================================================
第十四章：文件记录
================================================================================

已生成的文件：
- /root/.openclaw/workspace/BitgetTradingStrategy.md （交易策略）
- /root/.openclaw/workspace/Bitget现货交易手册.md （现货策略）
- /root/.openclaw/workspace/Bitget执行手册.md （操作指南）
- /root/.openclaw/workspace/Bitget-API-接入完整日志.md （完整日志）
- /root/.openclaw/workspace/Bitget-API接入详细过程日志.md （本文件）
- /root/.openclaw/workspace/MEMORY.md （已更新API配置）

================================================================================
日志结束
================================================================================

记录完成时间：2026-04-05 04:38 GMT+8
