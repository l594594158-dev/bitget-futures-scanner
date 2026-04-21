# 合约机器人修复文档
> 每次重大修复后记录于此，方便下次快速对照排查

---

## 修复记录

---

---

### 2026-04-21 | trailing_stop_v2.py API签名错误（两次Bug）

**症状表现**
- trailing_stop_v2.py 调用 all-position/single-position 返回 40037 或 40009 错误
- 用户明确指出"怎么可能是服务器故障，是你故障了"
- 实际：futures_scanner.py 能正常获取持仓，trailing_stop_v2.py 不能

**Bug1：API Key 和 Secret 互换了**
```python
# 错误（我的脚本）
API_KEY = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'  # 这是Secret！
API_SECRET = 'bg_55d7ddd792c3ebab233b4a6911f95f99'  # 这是Key！

# 正确（futures_scanner.py）
API_KEY = 'bg_55d7ddd792c3ebab233b4a6911f95f99'  # 以bg_开头
API_SECRET = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'  # hex字符串
```

**Bug2：缺少 40009 签名错误重试机制**
- Bitget 不同接口签名规则不同：
  - 持仓查询：用 path-only 签名（不含query）
  - 失败后需用 path+query 重试（40009错误时）
- trailing_stop_v2.py 原来只有 path-only 签名，失败后没有重试

**修复方案**
```python
# 1. 修正 API Key/Secret 顺序
API_KEY = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
API_SECRET = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'

# 2. 添加 40009 签名错误时自动用 path+query 重试
if code == '40009' and method == 'GET' and query and attempt < retries - 1:
    sign_str2 = timestamp + method.upper() + path + '?' + query + body_str
    signature2 = sign(sign_str2, API_SECRET)
    # 重试请求...
```

**验证**
```bash
cd /root/.openclaw/workspace && python3 << 'PYEOF'
import trailing_stop_v2 as ts
pos = ts.get_all_positions()
print(f"持仓数: {len(pos)}")  # 应输出 2
PYEOF
```

**涉及文件**
```
/root/.openclaw/workspace/trailing_stop_v2.py
  - API Key/Secret 顺序修正
  - api_request() 添加 40009 重试机制
```

**教训**
- 不能主观猜测 API Key 格式，必须对照已验证的代码
- Bitget 签名规则不统一，需要自动降级重试机制

---

### 2026-04-21 | all-position 返回格式判断错误

**症状表现**
- 用户询问"移动止盈监控了多少个代币"，回复"2个"
- 用户指出"明明有6个仓位"
- 实际交易所只有2个持仓，多出的4个（PIEVERSE/SUPER/SHIB/GUN/BASED）是幽灵记录
- trailing_stop.py 日志持续报错 `监控异常: unsupported hash type hashlib.sha256`

**根因分析**
- Bitget `/api/v2/mix/position/all-position` API 返回 **list**，不是 `dict{'data': list}`
- 原代码写法：`pos_all['data']` → 对 list 返回 `None`
- `None` 被当作空列表处理，但之前"6个持仓"是从缓存文件/旧日志来的错误数据
- 不是 trailing_stop.py 本身逻辑问题，是解析方式与 API 实际返回格式不匹配

**涉及文件**
```
/root/.openclaw/workspace/trailing_stop.py
  第91行：pos_data = self.api_request('GET', '/api/v2/mix/position/all-position', ...)
  原代码：pos_all['data'] → 错误
  修复：直接用 list 或 resp.get('data', []) 兼容
```

**实际持仓（交易所确认）**
```
SCRTUSDT:   🟢做多 176个  -1.41%  未激活
NAORISUSDT: 🟢做多 326个  +0.44%  未激活
```

**修复方案**
```python
# 修复前（错误）
if pos_all and 'data' in pos_all:
    positions = pos_all['data']

# 修复后（兼容两种格式）
if isinstance(pos_all, list):
    positions = [p for p in pos_all if float(p.get('total', 0)) > 0]
elif isinstance(pos_all, dict):
    positions = [p for p in pos_all.get('data', []) if float(p.get('total', 0)) > 0]
else:
    positions = []
```

**验证命令**
```bash
cd /root/.openclaw/workspace && python3 << 'PYEOF'
import sys; sys.path.insert(0, '.')
import futures_scanner as fs

pos_all = fs.api_request('GET', '/api/v2/mix/position/all-position',
    {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
print(f"返回类型: {type(pos_all)}")  # 应为 <class 'list'>
print(f"返回长度: {len(pos_all)}")   # 应为实际持仓数
PYEOF
```

**操作记录**
- 01:05 - 用户要求汇报当前持仓
- 01:06 - 深度检查发现 all-position 返回格式与代码不匹配
- 01:06 - 修复 db_positions.json 同步真实持仓
- 01:06 - 更新 REPAIR_LOG.md

**重要教训**
- Bitget 不同接口返回格式不同：`all-position` 返回 list，`single-position` 返回 list，`fills` 返回 dict
- 不能假设所有 API 都返回 `{'data': ...}` 格式
- 调试时必须先打印原始返回类型和结构，不能凭缓存/日志推断数据

---

### 2026-04-21 | 移动止盈监控漏持仓问题

**症状表现**
- 用户询问"移动止盈监控了多少个代币"
- 初始回复说"2个代币"（GUN + BASED）
- 用户指出"明明有6个仓位"
- 实际监控中：PIEVERSE做空、PIEVERSE做多、SUPER、SHIB都被漏了

**根因分析**
- 修复前调试时，用 `single-position` 接口逐个查询特定符号
- 只查询了 GUN/BASED/SPK 几个常见名，漏了 PIEVERSE/SUPER/SHIB
- trailing_stop.py 本身用 `/api/v2/mix/position/all-position` 正确获取了全部持仓
- 是调试代码的查询方法错了，不是 trailing_stop.py 本身的逻辑问题

**涉及文件**
```
/root/.openclaw/workspace/trailing_stop.py
  第91行：pos_data = self.api_request('GET', '/api/v2/mix/position/all-position', ...)
  → 正确：获取全部持仓
```

**实际监控状态（确认后）**
```
[监测] 6个持仓
  BASEDUSDT   🔴做空  184个  +8.43%  ✅已激活
  GUNUSDT     🔴做空  756个  +9.12%  ✅已激活
  PIEVERSEUSDT 🔴做空 197个  -5.35%  ⏳未激活
  SUPERUSDT   🟢做多  137个  -0.97%  ⏳未激活
  PIEVERSEUSDT 🟢做多 138个  -0.77%  ⏳未激活
  SHIBUSDT    🟢做多 1388个 -0.39%  ⏳未激活
```

**结论**
- trailing_stop.py 本身逻辑正确，all-position 接口正常工作
- 问题出在调试查询时的方法，不是生产代码的问题

---

### 2026-04-20 | 重复开仓 Bug + 移动止盈参数更新

---

#### Bug修复：同一信号重复开仓2笔

**症状表现**
- ORDIUSDT 信号触发后，连续开了2笔做空仓位（$5.125 + $5.117）
- 间隔仅5秒
- 原因：进程刚重启，`db_positions.json` 为空，冷却时间到了但本地无记录，下一个5秒循环再次判断"无持仓"→ 再次开仓

**根本原因**
- 开仓前只检查了 `positions` 本地记录，没有查交易所真实持仓
- `db_positions.json` 写入在开仓之后（开仓后才 save_positions），进程重启导致记录丢失

**修复方案**
```python
# 无持仓 -> 开仓（新增真实持仓检查）
cp = get_current_price(symbol)
if cp == 0: continue

# 🔧 防重复开仓：检查交易所真实持仓
real_size = get_position_size(symbol)
if real_size > 0:
    # 已有真实持仓，跳过开仓，只更新冷却
    logger.info(f"⚠️ {symbol} 已有持仓{real_size}，跳过开仓")
    cooldown[symbol] = now; save_cooldown(cooldown)
    # 若本地无记录，从交易所恢复本地持仓
    if not existing_local:
        pos_data = api_request('GET', '/api/v2/mix/position/single-position', ...)
        ...恢复本地记录...
    save_positions(positions); continue

sz = f"{POSITION_SIZE/cp*LEVERAGE:.4f}"  # 原有开仓逻辑
```

**涉及文件**
```
/root/.openclaw/workspace/futures_scanner.py
  - 第723行附近：开仓逻辑前新增 get_position_size() 检查
  - 第735-755行：本地记录缺失时从交易所恢复
```

**验证方法**
```
日志中出现：⚠️ ORDIUSDT 已有持仓7.8，跳过开仓
         ✅ 已从交易所恢复持仓记录: ORDIUSDT
```

---

#### 参数更新：移动止盈触发 +8% / 退出 -5%

**变更内容**
| 参数 | 原值 | 新值 |
|------|------|------|
| `TRAIL_TRIGGER_PCT` | 0.04 (+4%) | 0.08 (+8%) |
| `TRAIL_EXIT_PCT` | 0.03 (-3%) | 0.05 (-5%) |

**逻辑**
- 盈利 < 8%：不做任何操作
- 盈利 ≥ 8%：激活移动止盈跟踪，记录峰值
- 从峰值回撤 5%：市价止盈

**修复位置**
```python
# futures_scanner.py 第65-66行
TRAIL_TRIGGER_PCT = 0.08    # 移动止盈触发：盈利≥8%激活
TRAIL_EXIT_PCT = 0.05       # 移动止盈退出：从峰值回撤5%
```

---

### 2026-04-20 | productType 大小写错误导致无法读取真实持仓

**症状表现**
- 监测循环 `get_position_size()` 查询结果为空 `[]`
- 机器人误以为所有仓位不存在（手动平仓后记录残留）
- 但 `get_all_positions()` 的另一套逻辑（用 `total_openPrice`）能查到持仓
- 两种查询方法相互矛盾，监测逻辑混乱

**根本原因**
- `productType` 写成 `'usdt-futures'`（小写）
- Bitget 要求 `'USDT-FUTURES'`（大写）
- 参数错误 → API 返回 400172 → 查询失败 → 误判仓位为 0

**涉及函数**
| 函数 | 问题 | 修复 |
|------|------|------|
| `get_position_size()` | productType 小写 | → `USDT-FUTURES` |
| `get_all_positions()` | productType 小写 | → `USDT-FUTURES` |

**修复文件**
```
/root/.openclaw/workspace/futures_scanner.py
```

**修复命令**
```bash
# 全局替换所有 usdt-futures → USDT-FUTURES
sed -i "s/'productType': 'usdt-futures'/'productType': 'USDT-FUTURES'/g" /root/.openclaw/workspace/futures_scanner.py
```

**验证命令**
```bash
cd /root/.openclaw/workspace && python3 << 'PYEOF'
import futures_scanner as fs
data = fs.api_request('GET', '/api/v2/mix/position/single-position',
    {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT', 'symbol': 'CFGUSDT'})
print(f"返回: {data}")
print(f"持仓量: {fs.get_position_size('CFGUSDT')}")
PYEOF
```

**预期结果**
- API 返回 `[]`（无持仓）或含 `total` 字段的数据（有持仓）
- 不再返回 `None`

**进程重启**
```bash
kill <旧PID> && cd /root/.openclaw/workspace && nohup python3 futures_scanner.py --monitor > futures_scanner.log 2>&1 &
```

---

### 2026-04-17 | 余额查询 40037 降级策略

见 MEMORY.md 2026-04-17 条目

---

### 2026-04-16 | 签名格式修复（HEX → base64）

见 MEMORY.md 2026-04-16 条目

---

## 快速排错流程

**问：持仓数据对不上？**
1. 检查 `productType` 是否为 `USDT-FUTURES`（全文搜索）
2. 检查 `get_position_size()` vs `get_all_positions()` 是否用同一 productType
3. 手动验证：
   ```python
   fs.api_request('GET', '/api/v2/mix/position/single-position',
       {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT', 'symbol': '标的名'})
   ```
4. 看日志：`INFO [监测] DB1:X个 | 持仓:Y个`，Y 长期为 0 说明查不到真实持仓

**问：日志有大量 400172 错误？**
→ productType 大小写问题，参见本节修复

**问：同一币种开了2笔仓位？**
→ 在开仓逻辑前加上 `get_position_size(symbol)` 检查交易所真实持仓
→ 进程重启后先检查交易所持仓再决定是否开仓

---

## API 关键端点参考

| 功能 | 端点 | productType 要求 |
|------|------|----------------|
| 持仓查询（单币种） | `/api/v2/mix/position/single-position` | `USDT-FUTURES` |
| 持仓查询（全量） | `/api/v2/mix/position/all-position` | `USDT-FUTURES` |
| 行情tick | `/api/v2/mix/market/tickers` | `USDT-FUTURES` |
| K线 | `/api/v2/mix/market/candles` | `usdt-futures` ⚠️ |
| 市价开仓 | `/api/v2/mix/order/place-market-order` | `USDT-FUTURES` |

> 注意：K线接口用小写 `usdt-futures`，与其他接口不同！不要全局替换！

---

## 文件路径
- 机器人主程序：`/root/.openclaw/workspace/futures_scanner.py`
- 持仓记录：`/root/.openclaw/workspace/db_positions.json`
- 日志文件：`/root/.openclaw/workspace/futures_scanner.log`
- 冷却记录：`/root/.openclaw/workspace/cooldown.json`