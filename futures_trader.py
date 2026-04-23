#!/usr/bin/env python3
"""
合约交易任务
- 每30秒扫描数据库1号（热点库），评估开仓条件
- 开多/开空独立判断，满足条件即开仓
- 保证金2U，逐仓，10x
"""

import sys
import os
import time
import json
import hmac
import hashlib
import base64
import requests
import argparse
from datetime import datetime, timedelta, timezone

# ========== 配置 ==========
WORKSPACE = '/root/.openclaw/workspace'
DB_HOT = f'{WORKSPACE}/db_hot_contracts.json'     # 数据库1号：热点库
DB_V2 = f'{WORKSPACE}/db_positions_v2.json'       # 数据库2号：真实持仓
PID_FILE = f'{WORKSPACE}/futures_trader.pid'
LOG_FILE = f'{WORKSPACE}/futures_trader.log'

# API配置
API_KEY = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
API_SECRET = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
API_PASSPHRASE = 'liugang123'
BASE_URL = 'https://api.bitget.com'

# ========== 扫描参数 ==========
TRADE_SCAN_INTERVAL = 30        # 30秒扫描

# ========== 开仓参数 ==========
POSITION_SIZE = 2               # 保证金 2 USDT
LEVERAGE = 10                  # 杠杆 10x
MARGIN_MODE = 'isolated'       # 逐仓

# ========== 指标参数 ==========
RSI_PERIOD = 14                # RSI周期
MACD_FAST = 12                 # MACD快线
MACD_SLOW = 26                 # MACD慢线
MACD_SIGNAL = 9               # MACD信号线
VOL_LOOKBACK = 24              # 均量基准：前24根1h K线
HIGH_LOOKBACK = 7             # 前高参考：过去7天内

# ========== 开多条件阈值 ==========
LONG_GAIN_PCT = 0.05           # 30min-2h涨幅 ≥ 5%
LONG_VOL_RATIO = 2.5          # 成交量 ≥ 均量2.5倍
LONG_RSI_MIN = 40              # RSI下限
LONG_RSI_MAX = 70              # RSI上限

# ========== 开空条件阈值 ==========
SHORT_GAIN_PCT = 0.05          # 30min-2h涨幅 ≥ 5%
SHORT_RSI_MIN = 80             # RSI ≥ 80

# ========== 冷却 ==========
COOLDOWN_SEC = 600             # 同一标的冷却10分钟

# ========== API工具 ==========
def sign(message: str, secret: str) -> str:
    mac = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode('utf-8')

def api_request(method: str, path: str, params=None, body=None, retries=3, retry_delay=2):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ''
    query = ''
    if params:
        query = '&'.join([f"{k}={v}" for k, v in params.items()])

    for attempt in range(retries):
        try:
            url = BASE_URL + path
            sign_str = timestamp + method.upper() + path + ('?' + query if query else '') + body_str
            signature = sign(sign_str, API_SECRET)

            headers = {
                'Content-Type': 'application/json',
                'ACCESS-KEY': API_KEY,
                'ACCESS-SIGN': signature,
                'ACCESS-TIMESTAMP': timestamp,
                'ACCESS-PASSPHRASE': API_PASSPHRASE,
            }

            if method == 'GET':
                if query:
                    url += '?' + query
                resp = requests.get(url, headers=headers, timeout=10)
            else:
                resp = requests.request(method, url, headers=headers,
                                       data=body_str if body else None, timeout=10)

            data = resp.json()
            code = data.get('code')
            msg = data.get('msg', '')

            if code == '40037' and attempt < retries - 1:
                logger(f"API 40037错误，重试({attempt+1}/{retries})...")
                time.sleep(retry_delay)
                continue

            if code == '40009' and method == 'GET' and query and attempt < retries - 1:
                sign_str2 = timestamp + method.upper() + path + '?' + query + body_str
                signature2 = sign(sign_str2, API_SECRET)
                headers['ACCESS-SIGN'] = signature2
                resp2 = requests.get(url, headers=headers, timeout=10)
                data = resp2.json()
                code = data.get('code')
                if code == '00000' or code == '0':
                    return data.get('data')
                if code == '40037':
                    logger(f"API 40037错误，重试({attempt+1}/{retries})...")
                    time.sleep(retry_delay)
                    continue

            if code == '00000' or code == '0':
                return data.get('data')
            return data
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(retry_delay)
            else:
                logger(f"API异常: {e}")
                return None
    return None

# ========== 日志 ==========
def logger(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

# ========== 指标计算 ==========
def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def compute_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    # 计算EMA
    def ema_series(vals, p):
        k = 2 / (p + 1)
        ema = sum(vals[:p]) / p
        result = [ema]
        for v in vals[p:]:
            ema = v * k + ema * (1 - k)
            result.append(ema)
        return result

    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    # 对齐到同一长度
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    # Signal = EMA of macd_line
    if len(macd_line) < signal:
        return None, None, None
    sig = sum(macd_line[:signal]) / signal
    signal_line = [sig]
    k = 2 / (signal + 1)
    for m in macd_line[signal:]:
        sig = m * k + sig * (1 - k)
        signal_line.append(sig)
    return macd_line, signal_line, macd_line[-1] - signal_line[-1]

# ========== K线获取 ==========
def get_klines(symbol, period='1h', limit=100):
    """获取K线数据，返回 [(time, open, high, low, close, volume), ...]"""
    data = api_request('GET', '/api/v2/mix/market/candles',
                       params={'symbol': symbol, 'productType': 'USDT-FUTURES',
                               'granularity': period, 'limit': limit})
    if not data:
        return None
    if isinstance(data, dict):
        data = data.get('data', [])
    if not isinstance(data, list) or len(data) == 0:
        return None
    result = []
    for item in data:
        if len(item) >= 6:
            try:
                result.append({
                    'time': float(item[0]),
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'volume': float(item[5]),
                })
            except:
                continue
    return result

def get_ticker(symbol):
    """获取当前价格"""
    data = api_request('GET', '/api/v2/mix/market/tickers',
                       params={'productType': 'USDT-FUTURES'})
    if not data:
        return None
    if isinstance(data, dict):
        data = data.get('data', [])
    for t in data:
        if t.get('symbol') == symbol:
            return t
    return None

# ========== 数据库操作 ==========
def load_hot_db():
    if not os.path.exists(DB_HOT):
        return []
    with open(DB_HOT, 'r') as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get('contracts', [])

def load_v2():
    if not os.path.exists(DB_V2):
        return {'positions': {}, 'last_updated': ''}
    with open(DB_V2, 'r') as f:
        return json.load(f)

def save_v2(db):
    db['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(DB_V2, 'w') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def load_cooldown():
    db = load_v2()
    return db.get('cooldowns', {})

def save_cooldown(cooldowns):
    db = load_v2()
    db['cooldowns'] = cooldowns
    save_v2(db)

# ========== 冷却检查 ==========
def is_in_cooldown(symbol: str) -> bool:
    cooldowns = load_cooldown()
    last = cooldowns.get(symbol, 0)
    return (time.time() - last) < COOLDOWN_SEC

def set_cooldown(symbol: str):
    cooldowns = load_cooldown()
    cooldowns[symbol] = time.time()
    save_cooldown(cooldowns)

# ========== 检查是否已有持仓（只查Bitget API，不查本地DB）==========
def has_position(symbol: str) -> bool:
    """只通过Bitget API检查真实持仓，不用本地DB"""
    pos_data = api_request('GET', '/api/v2/mix/position/single-position',
                           params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
    pos_list = pos_data if isinstance(pos_data, list) else (pos_data.get('data', []) if isinstance(pos_data, dict) else [])
    return any(float(p.get('total', 0)) > 0 for p in pos_list)

# ========== 开仓操作 ==========
def open_position(symbol: str, side: str, size: float) -> bool:
    """开仓（逐仓10x）"""
    # 设置杠杆
    lev_res = api_request('POST', '/api/v2/mix/account/set-leverage', body={
        'symbol': symbol,
        'productType': 'USDT-FUTURES',
        'marginCoin': 'USDT',
        'leverage': str(LEVERAGE),
        'marginMode': MARGIN_MODE,
    })
    if lev_res and lev_res.get('code') not in ('00000', '0', None):
        logger(f"  ❌ 杠杆设置失败: {lev_res.get('msg')}")
        return False

    # 开仓
    order_body = {
        'symbol': symbol,
        'productType': 'USDT-FUTURES',
        'marginCoin': 'USDT',
        'marginMode': MARGIN_MODE,
        'side': side,
        'posSide': 'long' if side == 'buy' else 'short',
        'tradeSide': 'open',
        'orderType': 'market',
        'size': str(size),
    }
    res = api_request('POST', '/api/v2/mix/order/place-order', body=order_body)
    if res and (res.get('code') == '00000' or res.get('code') == '0'):
        order_id = res.get('data', {}).get('orderId', '')
        logger(f"  ✅ 开仓成功: {symbol} {side} {size}")
        return True
    else:
        logger(f"  ❌ 开仓失败: {res}")
        return False

def get_entry_price(symbol: str) -> float:
    data = api_request('GET', '/api/v2/mix/position/single-position',
                       params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
    if not data:
        return 0
    positions = data if isinstance(data, list) else []
    for p in positions:
        if float(p.get('total', 0)) > 0:
            return float(p.get('openPriceAvg', 0))
    return 0

def get_position_size(symbol: str) -> float:
    data = api_request('GET', '/api/v2/mix/position/single-position',
                       params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
    if not data:
        return 0
    positions = data if isinstance(data, list) else []
    for p in positions:
        total = float(p.get('total', 0))
        if total > 0:
            return total
    return 0

# ========== 条件评估 ==========
def eval_coin(symbol: str):
    """
    评估单个币的开多/开空条件
    完全按照用户原始条件实现，不简化

    开多条件：
    1. 30分钟-2小时涨幅 ≥ 5%（时间窗口 T-30min 到 T+2h，价格从最低到最高涨幅）
    2. 成交量 ≥ 均量5倍（均量基准：前24小时成交量均值，即24根1h K线）
    3. 价格突破日线前高（30天内最高点，需收盘价实体突破，非影线刺穿）
    4. 1h RSI 在 40-70（RSI参数14，40以下极弱，70以上追高，最佳50-60）
    5. 回踩不破前高支撑（回踩位置：急涨前一日/4h的前高价位；
       回踩时成交量 < 急涨时的30%；跌破回踩低点则信号失效）

    开空条件：
    1. 30分钟-2小时涨幅 ≥ 5%
    2. 1h RSI ≥ 80（RSI参数14，80以上极端超买区域）
    3. 价格创新高但MACD不创新高（MACD参数12,26,9；顶背离确认）
    4. 成交量开始萎缩（急涨时成交量为峰值，后续3根1h K线成交量递减）
    5. 跌破4h EMA20（收盘价穿过才生效，非影线瞬间刺穿）

    返回: 'long' / 'short' / None
    """
    # 获取多周期K线
    kline_30m = get_klines(symbol, '30m', 100)
    kline_1h = get_klines(symbol, '1H', 100)
    kline_4h = get_klines(symbol, '4H', 100)
    kline_1d = get_klines(symbol, '1D', 100)

    if not kline_30m or len(kline_30m) < 4:
        return None
    if not kline_1h or len(kline_1h) < 30:
        return None
    if not kline_1d or len(kline_1d) < 2:
        return None

    # 最新价格（当前1h K线收盘价）
    current_price = kline_1h[0]['close']

    # ===== 条件1：30分钟-2小时涨幅 ≥ 5% =====
    # 时间窗口：T-30min 到 T+2h，即最近4根30m K线
    # 计算：从这4根30m的最低点到最高点的涨幅
    recent_30m = kline_30m[:min(4, len(kline_30m))]
    min_in_window = min(k['low'] for k in recent_30m)
    max_in_window = max(k['high'] for k in recent_30m)
    gain_pct = (max_in_window - min_in_window) / min_in_window if min_in_window > 0 else 0

    # ===== 急涨区间峰值成交量（用于多空条件2/4）=====
    spike_vol_peak = max(k['volume'] for k in recent_30m)

    # ===== 条件2：成交量 ≥ 均量5倍 =====
    # 均量基准：前24根1h K线（24小时均值，排除UTC 0点统计偏差）
    # 取kline_1h中，急涨区间（最近4根1h）之外的24根
    if len(kline_1h) < 4 + VOL_LOOKBACK:
        return None
    baseline_vols_1h = [k['volume'] for k in kline_1h[4:4+VOL_LOOKBACK]]
    avg_vol_24h = sum(baseline_vols_1h) / len(baseline_vols_1h) if baseline_vols_1h else 0
    vol_ratio = spike_vol_peak / avg_vol_24h if avg_vol_24h > 0 else 0

    # ===== 日线前高（30天内）=====
    highs_30d = [k['high'] for k in kline_1d[:HIGH_LOOKBACK]]
    daily_high = max(highs_30d) if highs_30d else 0

    # 价格实体突破前高：收盘价 > 日线前高（非影线刺穿）
    price_broke_high = current_price > daily_high

    # ===== 1h RSI（参数14）=====
    closes_1h = [k['close'] for k in kline_1h]
    rsi_1h = compute_rsi(closes_1h, RSI_PERIOD)

    # ===== 4h EMA20 =====（用于空头条件5）
    ema20_4h = None
    if kline_4h and len(kline_4h) >= 25:
        closes_4h = [k['close'] for k in kline_4h]
        ema20_4h = compute_ema(closes_4h, 20)

    # ===== MACD（1h，参数12,26,9）=====（用于空头条件3）
    closes_1h_for_macd = [k['close'] for k in kline_1h]
    macd_line, signal_line, hist = compute_macd(closes_1h_for_macd,
                                                  MACD_FAST, MACD_SLOW, MACD_SIGNAL)

    # ===== 顶背离检查：价格创新高 vs MACD不创新高（30天内）=====
    price_new_high = current_price > daily_high
    macd_30d_high = None
    macd_not_new_high = False
    if macd_line and len(macd_line) >= HIGH_LOOKBACK:
        macd_30d_vals = macd_line[:HIGH_LOOKBACK]
        macd_30d_high = max(macd_30d_vals) if macd_30d_vals else 0
        macd_not_new_high = (macd_30d_high > 0 and
                             macd_line[-1] < macd_30d_high)

    # ===== 空头条件4：成交量萎缩 =====
    # 急涨时成交量为峰值（spike_vol_peak），后续3根1h K线成交量逐根递减
    recent_3h_vols = [k['volume'] for k in kline_1h[1:4]]  # 不含当前K线
    vol_declining = (
        len(recent_3h_vols) >= 3 and
        recent_3h_vols[0] > recent_3h_vols[1] > recent_3h_vols[2]
    )

    # ===== 多头条件5：回踩不破前高支撑 =====
    # 回踩位置：急涨前一日/4h的前高价位
    # 需满足：回踩时成交量 < 急涨时的30%；跌破回踩低点则信号失效
    # 实现：
    # - 回踩价位：取4h前高（如果有足够数据）或日线前一日高
    # - 回踩低点：取最近1h K线的最低点（作为回落的支撑区域）
    # - 回踩成交量：取最近1h K线的成交量
    pullback_low = kline_1h[0]['low']   # 当前1h低点（回落的支撑）
    pullback_vol = kline_1h[0]['volume']  # 当前1h成交量

    # 判断回踩不破：回踩时成交量 < spike峰值 * 30%
    vol_ok = pullback_vol < (spike_vol_peak * 0.30)

    # 判断支撑有效：当前价格 > 回踩低点（即没有跌破支撑）
    price_holds_support = current_price > pullback_low

    # 回踩支撑有效：成交量萎缩 + 价格未破支撑
    pullback_valid = vol_ok and price_holds_support

    # ===== 判断开多条件（5条全满足）=====
    long_ok = (
        gain_pct >= LONG_GAIN_PCT and
        vol_ratio >= LONG_VOL_RATIO and
        rsi_1h is not None and LONG_RSI_MIN <= rsi_1h <= LONG_RSI_MAX and
        pullback_valid
    )

    # ===== 判断开空条件（5条全满足）=====
    short_ok = (
        gain_pct >= SHORT_GAIN_PCT and
        rsi_1h is not None and rsi_1h >= SHORT_RSI_MIN and
        macd_not_new_high and
        vol_declining and
        ema20_4h is not None and current_price < ema20_4h
    )

    # 多空冲突时优先做空
    if short_ok and long_ok:
        logger(f"  ⚠️ {symbol} 多空信号同时满足，优先做空")
        return 'short'
    if short_ok:
        logger(f"  📊 {symbol} 开空信号满足 | 涨{gain_pct*100:.1f}% R{rsi_1h:.0f} 顶背{price_new_high and macd_not_new_high} 缩{vol_declining} ema20{ema20_4h and current_price < ema20_4h}")
        return 'short'
    if long_ok:
        logger(f"  📊 {symbol} 开多信号满足 | 涨{gain_pct*100:.1f}% 量{vol_ratio:.1f}x 前高{price_broke_high} R{rsi_1h:.0f} 支撑{pullback_valid}")
        return 'long'

    # 调试：打印各条件状态
    logger(f"  ❌ {symbol} 未达标 | 涨{gain_pct*100:.1f}% 量{vol_ratio:.1f}x R{rsi_1h:.0f} 顶背{price_new_high and macd_not_new_high} 缩{vol_declining} ema20{ema20_4h and current_price < ema20_4h} 支撑{pullback_valid}")

    return None

# ========== 主扫描 ==========
def scan_and_trade():
    hot = load_hot_db()
    if not hot:
        return

    logger("=" * 50)
    logger(f"交易扫描开始（{len(hot)}个热点代币）...")

    for coin in hot:
        symbol = coin['symbol']

        # 去重：检查数据库2号是否已有持仓
        if has_position(symbol):
            logger(f"  ⏭ {symbol} 已有持仓，跳过")
            continue

        # 冷却检查
        if is_in_cooldown(symbol):
            continue

        # 评估条件
        signal = eval_coin(symbol)
        if not signal:
            continue

        # 获取当前价格算size
        price = coin.get('last_price', '0')
        if not price or float(price) <= 0:
            ticker = get_ticker(symbol)
            if ticker:
                price = ticker.get('lastPr', '0')
        price = float(price)
        if price <= 0:
            logger(f"  ⚠️ {symbol} 无法获取价格")
            continue

        size = round(POSITION_SIZE / price * LEVERAGE, 4)
        if size <= 0:
            continue

        # 执行开仓
        side = 'buy' if signal == 'long' else 'sell'
        ok = open_position(symbol, side, size)
        if ok:
            set_cooldown(symbol)


# ========== 主循环 ==========
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', default='start')
    args = parser.parse_args()

    if args.action == 'start':
        pid = os.getpid()
        with open(PID_FILE, 'w') as f:
            f.write(str(pid))

        logger("=" * 50)
        logger("合约交易任务启动")
        logger(f"扫描频率: 每{TRADE_SCAN_INTERVAL}秒")
        logger(f"保证金: {POSITION_SIZE}U | 杠杆: {LEVERAGE}x | 模式: {MARGIN_MODE}")
        logger("开多: 涨幅≥5% + 量比≥2.5x + RSI(40-70) + 回踩不破支撑")
        logger("开空: 涨幅≥5% + RSI≥80 + 顶背离 + 缩量 + 跌破4h EMA20")
        logger("=" * 50)

        while True:
            try:
                scan_and_trade()
                time.sleep(TRADE_SCAN_INTERVAL)
            except KeyboardInterrupt:
                logger("已停止")
                break
            except Exception as e:
                logger(f"主循环异常: {e}")
                time.sleep(10)

if __name__ == '__main__':
    main()
