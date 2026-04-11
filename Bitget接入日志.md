# Bitget API 接入日志
## 记录时间：2026-04-05 12:00 - 12:30 GMT+8
## 操作者：AI Assistant (OpenClaw)

---

## 用户提供的凭证

| 项目 | 内容 |
|-----|------|
| API Key | `3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c` |
| API Secret | `bg_55d7ddd792c3ebab233b4a6911f95f99` |
| Passphrase | `liugang123` |

---

## API Key 格式分析

| 项目 | 分析结果 |
|-----|---------|
| API Key 长度 | 64 字符 |
| API Key 格式 | 纯十六进制字符串 (0-9, a-f) |
| Secret 长度 | 35 字符 |
| Secret 格式 | `bg_` 开头，正常 Bitget 格式 |
| 结论 | API Key 看起来像 SHA256 哈希值，不像有效 API Key |

---

## 测试记录

### 1. 基础连接测试

| 测试 | 方法 | 端点 | 结果 |
|-----|------|------|------|
| 公开接口 | GET | /api/v2/spot/public/coins | ✅ 200 成功 |
| 账户接口 | GET | /api/v2/spot/account/assets | ❌ 40006 |

### 2. Header 格式测试

| Header 格式 | 错误码 | 含义 |
|------------|--------|------|
| B-API-KEY | 40006 | Invalid ACCESS_KEY |
| B-APIKEY | 40006 | Invalid ACCESS_KEY |
| ACCESS-KEY | 40037 | Apikey does not exist |
| api-key | 40006 | Invalid ACCESS_KEY |
| X-API-KEY | 40006 | Invalid ACCESS_KEY |

### 3. 签名算法测试

| 算法 | 密钥处理 | 结果 |
|-----|---------|------|
| HMAC-SHA256 | 标准 | ❌ 40006 |
| HMAC-SHA384 | 标准 | ❌ 40006 |
| HMAC-SHA512 | 标准 | ❌ 40006 |
| HMAC-SHA256 | Secret + Timestamp | ❌ 40006 |
| HMAC-SHA256 | Timestamp + Secret | ❌ 40006 |
| HMAC-SHA256 | 只签名 Timestamp | ❌ 40006 |

### 4. 消息格式测试

| 消息格式 | 结果 |
|---------|------|
| timestamp + method + path + body | ❌ 40006 |
| method + path + timestamp + body | ❌ 40006 |
| timestamp + method + path | ❌ 40006 |
| method + path + body | ❌ 40006 |
| timestamp\nmethod\npath\nbody (换行) | ❌ 40006 |

### 5. 密钥组合测试

| API Key | Secret | 结果 |
|--------|--------|------|
| 64字符hex | bg_前缀 | ❌ 40006 |
| bg_前缀 | 64字符hex | ❌ 40006 |
| 64字符hex (Key) | 64字符hex (Secret) | ❌ 40006 |
| bg_前缀 (Key) | bg_前缀 (Secret) | ❌ 40006 |

### 6. API Key 处理测试

| 处理方式 | 结果 |
|---------|------|
| 原始 | ❌ 40006 |
| SHA256 | ❌ 40006 |
| MD5 | ❌ 40006 |
| Base64 编码 | ❌ 40006 |
| 反转 | ❌ 40006 |
| Uppercase | ❌ 40006 |
| Lowercase | ❌ 40006 |

### 7. Secret 处理测试

| 处理方式 | 结果 |
|---------|------|
| 原始 | ❌ 40006 |
| SHA256 预处理 | ❌ 40006 |
| MD5 预处理 | ❌ 40006 |
| 双重 SHA256 | ❌ 40006 |

### 8. 端点测试

| 方法 | 端点 | 结果 |
|-----|------|------|
| GET | /api/v2/spot/account/assets | ❌ 40006 |
| GET | /api/v2/spot/account/info | ❌ 40006 |
| GET | /api/v2/spot/account/balance | ❌ 40404 |
| GET | /api/v2/spot/account/list | ❌ 40404 |
| POST | /api/v2/spot/order/place | ❌ 40404 |

---

## 错误码分析

| 错误码 | 消息 | 含义 |
|--------|------|------|
| 40006 | Invalid ACCESS_KEY | API Key 存在但验证失败 |
| 40037 | Apikey does not exist | API Key 不存在 |

**关键发现：**
- 使用 `B-API-KEY` 格式：真key和假key都返回 40006
- 使用 `ACCESS-KEY` 格式：真key和假key都返回 40037

这说明使用 ACCESS-KEY 格式可以区分真假 key，但两种格式都返回"不存在"的错误。

---

## 最终结论

**API Key 格式无效：`3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c`**

这串 64 位十六进制字符串看起来像 SHA256 哈希值，不是有效的 Bitget API Key。

正常的 Bitget API Key 应该像 `bg_55d7ddd792c3ebab233b4a6911f95f99` 这样，以 `bg_` 开头。

---

## 用户后续操作

用户要求"继续深度学习接入"，但经过 150+ 次测试后，确认 API Key 本身无效。

---

## 建议

1. 用户需要重新在 Bitget 后台创建新的 API Key
2. 新的 API Key 应该以 `bg_` 开头
3. 创建后需要重新配置

---

## 日志结束

记录时间：2026-04-05 12:30 GMT+8
