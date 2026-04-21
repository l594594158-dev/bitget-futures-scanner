#!/usr/bin/env python3
"""
极端行情交易机器人
- 热点库：每5分钟扫描所有合约，日涨幅>20%写入数据库1号
- 交易：每30秒扫描数据库1号代币，5个条件全满足开仓
- 仓位：2U保证金，逐仓，10x
- 止盈：限价挂单±8%
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
from datetime import datetime

# ========== 配置 ==========
WORKSPACE = '/root/.openclaw/workspace'
DB_HOT = f'{WORKSPACE}/db_hot_contracts.json'    # 数据库1号：热点库
DB_POS = f'{WORKSPACE}/db_positions.json'         # 数据库1号：持仓记录
PID_FILE = f'{WORKSPACE}/surge_trader.pid'
LOG_FILE = f'{WORKSPACE}/surge_trader.log'

# API配置
API_KEY = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
API_SECRET = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
API_PASSPHRASE = 'liugang123'
BASE_URL = 'https://api.bitget.com'

# ========== 热点库参数 ==========
HOT_SCAN_INTERVAL = 300          # 5分钟扫描热点库
GAIN_THRESHOLD = 0.20           # 入库：日涨幅>20%
REMOVE_THRESHOLD = 0.10         # 出库：日涨幅<10%
MAX_HOT_SIZE = 10               # 热点库上限

# ========== 交易扫描参数 ==========
TRADE_SCAN_INTERVAL = 30        # 30秒扫描交易信号

# ========== 开仓参数 ==========
POSITION_SIZE = 2               # 每仓保证金 2 USDT
LEVERAGE = 10                  # 杠杆 10x
MARGIN_MODE = 'isolated'        # 逐仓

# ========== 止盈参数 ==========
LIMIT_STOP_PCT = 0.08           # 止损：多单-8%，空单+8%

# ========== 做多信号条件（5个全满足）==========
LONG_BB_DEV = 4.0               # 布林偏离≥4%
LONG_ADX = 40                   # ADX≥40
LONG_VR_MAX = 1.5               # vr1<1.5
LONG_RETRACE_MAX = 0.10         # 回踩≤10%
LONG_RSI_MIN = 55               # RSI≥55
LONG_RSI_MAX = 75               # RSI≤75

# ========== 做空信号条件（5个全满足）==========
SHORT_BB_DEV = 5.0              # 布林偏离≥5%
SHORT_ADX = 35                  # ADX≥35
SHORT_VR_MIN = 2.0              # vr1>2.0
SHORT_RSI_MIN = 75              # RSI≥75
SHORT_RSI_MAX = 92              # RSI≤92
SHORT_RETRACE_MIN = 0.08        # 日内回落≥8%

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

# ========== 技术指标 ==========
def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_bollinger(closes, period=20, mult=2):
    if len(closes) < period:
        return closes[-1], closes[-1], closes[-1]
    sma = sum(closes[-period:]) / period
    std = (sum((c - sma) ** 2 for c in closes[-period:]) / period) ** 0.5
    return sma + mult * std, sma, sma - mult * std

def compute_adx(highs, lows, closes, period=14):
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return 0, 0, 0
    trs = []
    plus_dms = []
    minus_dms = []
    for i in range(1, len(highs)):
        high, low, prev_high, prev_low, prev_close = highs[i], lows[i], highs[i-1], lows[i-1], closes[i-1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        up = high - prev_high
        down = prev_low - low
        plus_dm = up if up > down and up > 0 else 0
        minus_dm = down if down > up and down > 0 else 0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    tr14 = sum(trs[-period:])
    plus_dm14 = sum(plus_dms[-period:])
    minus_dm14 = sum(minus_dms[-period:])

    if tr14 == 0:
        return 0, 0, 0
    plus_di = (plus_dm14 / tr14) * 100
    minus_di = (minus_dm14 / tr14) * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    adx = dx  # 简化
    return adx, plus_di, minus_di

def compute_vol_ratio(volumes):
    if len(volumes) < 5:
        return 1.0
    avg = sum(volumes[-5:]) / 5
    return volumes[-1] / avg if avg > 0 else 1.0

def compute_momentum_slowdown(closes, volumes):
    if len(closes) < 5:
        return False, 0
    gains = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    if len(gains) < 3:
        return False, 0
    recent = sum(gains[-2:]) / 2
    older = sum(gains[:-2]) / (len(gains) - 2) if len(gains) > 2 else gains[0]
    if older <= 0:
        return False, 0
    slowdown_deg = (older - recent) / older
    return slowdown_deg > 0.3, slowdown_deg

# ========== K线数据获取 ==========
def get_klines(symbol, period='5m', limit=100):
    """获取5分钟K线"""
    data = api_request('GET', '/api/v2/mix/market/candles',
                       params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'period': period, 'limit': limit})
    if not data:
        return None
    if isinstance(data, dict):
        data = data.get('data', [])
    if not isinstance(data, list) or len(data) == 0:
        return None
    # 返回: [time, open, high, low, close, volume, ...]
    return data

# ========== 数据库操作 ==========
def load_hot_db():
    if not os.path.exists(DB_HOT):
        return []
    with open(DB_HOT, 'r') as f:
        return json.load(f)

def save_hot_db(coins):
    with open(DB_HOT, 'w') as f:
        json.dump(coins, f, ensure_ascii=False, indent=2)

def load_pos_db():
    if not os.path.exists(DB_POS):
        return {'positions': []}
    with open(DB_POS, 'r') as f:
        return json.load(f)

def save_pos_db(db):
    with open(DB_POS, 'w') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# ========== 热点库扫描（每5分钟）==========
def scan_hot_contracts():
    """扫描所有合约，找出日涨幅>20%的币"""
    logger("=" * 50)
    logger("开始扫描热点库...")

    # 获取全市场行情
    tickers = api_request('GET', '/api/v2/mix/market/tickers',
                          params={'productType': 'USDT-FUTURES'})
    if not tickers:
        logger("获取行情失败")
        return

    hot = []
    for t in tickers:
        try:
            change = float(t.get('change24h', 0))
            symbol = t.get('symbol', '')
            if not symbol:
                continue
            if change >= GAIN_THRESHOLD:
                hot.append({
                    'symbol': symbol,
                    'change24h': change,
                    'last_price': t.get('lastPr', '0'),
                    'volume': t.get('volume24h', '0'),
                    'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
        except:
            continue

    if not hot:
        logger("无热点合约")
        return

    # 按涨幅排序
    hot.sort(key=lambda x: x['change24h'], reverse=True)

    # 截取前10个
    hot = hot[:MAX_HOT_SIZE]

    # 移除低于10%的
    hot = [h for h in hot if h['change24h'] >= REMOVE_THRESHOLD]

    save_hot_db(hot)
    logger(f"热点库更新: {len(hot)}个代币")
    for h in hot:
        logger(f"  {h['symbol']} 涨幅: {h['change24h']*100:.2f}%")

# ========== 信号检测 ==========
def check_signal_long(symbol, change24h):
    """检测做多信号（5个条件全满足）"""
    klines = get_klines(symbol, '5m', 100)
    if not klines:
        return False, "无K线数据"

    # 解析K线
    try:
        c5 = [float(k[4]) for k in klines]     # close
        h5 = [float(k[2]) for k in klines]     # high
        l5 = [float(k[3]) for k in klines]     # low
        v5 = [float(k[5]) for k in klines]     # volume
        o5 = [float(k[1]) for k in klines]     # open
    except:
        return False, "K线解析失败"

    # 获取1小时K线（用于vr1）
    klines_1h = get_klines(symbol, '1h', 100)
    if klines_1h:
        try:
            v1 = [float(k[5]) for k in klines_1h]
        except:
            v1 = v5
    else:
        v1 = v5

    price = c5[-1]
    bb_up, bb_mid, bb_lo = compute_bollinger(c5)
    bb_dev = abs(price - bb_mid) / bb_mid * 100 if bb_mid > 0 else 0

    rsi5 = compute_rsi(c5)
    adx1, dip1, dim1 = compute_adx(h5, l5, c5)

    vr5 = compute_vol_ratio(v5)
    vr1 = compute_vol_ratio(v1)

    # 日内高点回踩
    day_high = max(h5[-60:]) if len(h5) >= 60 else max(h5)
    intraday_retrace = (day_high - price) / day_high if day_high > 0 else 0

    mom_slowdown, slowdown_deg = compute_momentum_slowdown(c5, v5)

    # 5个条件
    c1 = bb_dev >= LONG_BB_DEV
    c2 = adx1 >= LONG_ADX and dip1 > dim1
    c3 = vr1 < LONG_VR_MAX and intraday_retrace <= LONG_RETRACE_MAX
    c4 = LONG_RSI_MIN <= rsi5 <= LONG_RSI_MAX
    c5 = not (mom_slowdown and slowdown_deg > 0.3)

    reasons = (
        f"做多: ①BB偏离={bb_dev:.1f}%≥{LONG_BB_DEV}%={'✅' if c1 else '❌'} "
        f"②ADX={adx1:.1f}≥{LONG_ADX}+DI+={'✅' if c2 else '❌'} "
        f"③vr1={vr1:.2f}<{LONG_VR_MAX}+回踩={intraday_retrace*100:.1f}%≤{LONG_RETRACE_MAX*100:.0f}%={'✅' if c3 else '❌'} "
        f"④RSI={rsi5:.1f}∈[{LONG_RSI_MIN},{LONG_RSI_MAX}]={'✅' if c4 else '❌'} "
        f"⑤动量={'✅' if c5 else '❌'}"
    )

    return (c1 and c2 and c3 and c4 and c5), reasons

def check_signal_short(symbol, change24h):
    """检测做空信号（5个条件全满足）"""
    klines = get_klines(symbol, '5m', 100)
    if not klines:
        return False, "无K线数据"

    try:
        c5 = [float(k[4]) for k in klines]
        h5 = [float(k[2]) for k in klines]
        l5 = [float(k[3]) for k in klines]
        v5 = [float(k[5]) for k in klines]
    except:
        return False, "K线解析失败"

    klines_1h = get_klines(symbol, '1h', 100)
    if klines_1h:
        try:
            v1 = [float(k[5]) for k in klines_1h]
        except:
            v1 = v5
    else:
        v1 = v5

    price = c5[-1]
    bb_up, bb_mid, bb_lo = compute_bollinger(c5)
    bb_dev = abs(price - bb_mid) / bb_mid * 100 if bb_mid > 0 else 0

    rsi5 = compute_rsi(c5)
    adx1, dip1, dim1 = compute_adx(h5, l5, c5)

    vr5 = compute_vol_ratio(v5)
    vr1 = compute_vol_ratio(v1)

    day_high = max(h5[-60:]) if len(h5) >= 60 else max(h5)
    intraday_retrace = (day_high - price) / day_high if day_high > 0 else 0

    mom_slowdown, slowdown_deg = compute_momentum_slowdown(c5, v5)

    # 5个条件
    c1 = bb_dev >= SHORT_BB_DEV
    c2 = adx1 >= SHORT_ADX
    c3 = vr1 > SHORT_VR_MIN
    c4 = SHORT_RSI_MIN <= rsi5 <= SHORT_RSI_MAX
    c5 = intraday_retrace >= SHORT_RETRACE_MIN

    reasons = (
        f"做空: ①BB偏离={bb_dev:.1f}%≥{SHORT_BB_DEV}%={'✅' if c1 else '❌'} "
        f"②ADX={adx1:.1f}≥{SHORT_ADX}={'✅' if c2 else '❌'} "
        f"③vr1={vr1:.2f}>{SHORT_VR_MIN}={'✅' if c3 else '❌'} "
        f"④RSI={rsi5:.1f}∈[{SHORT_RSI_MIN},{SHORT_RSI_MAX}]={'✅' if c4 else '❌'} "
        f"⑤回落={intraday_retrace*100:.1f}%≥{SHORT_RETRACE_MIN*100:.0f}%={'✅' if c5 else '❌'}"
    )

    return (c1 and c2 and c3 and c4 and c5), reasons

# ========== 开仓操作 ==========
def open_position(symbol: str, side: str, size: float) -> bool:
    """开仓（逐仓10x）"""
    # 先设置杠杆
    leverage_path = '/api/v2/mix/account/set-leverage'
    leverage_body = {
        'symbol': symbol,
        'productType': 'USDT-FUTURES',
        'marginCoin': 'USDT',
        'leverage': str(LEVERAGE),
        'marginMode': MARGIN_MODE,
    }
    lev_res = api_request('POST', leverage_path, body=leverage_body)
    if lev_res and lev_res.get('code') not in ('00000', '0', None):
        logger(f"  杠杆设置失败: {lev_res.get('msg')}")

    # 开仓（hedge模式需要tradeSide=open）
    order_path = '/api/v2/mix/order/place-order'
    order_body = {
        'symbol': symbol,
        'productType': 'USDT-FUTURES',
        'marginCoin': 'USDT',
        'marginMode': MARGIN_MODE,
        'side': side,          # buy=多, sell=空
        'posSide': 'long' if side == 'buy' else 'short',
        'tradeSide': 'open',
        'orderType': 'market',
        'size': str(size),
    }
    res = api_request('POST', order_path, body=order_body)
    if res and (res.get('code') == '00000' or res.get('code') == '0'):
        order_id = res.get('data', {}).get('orderId', '')
        logger(f"  ✅ 开仓成功: {symbol} {side} {size} @市价")
        return order_id
    else:
        logger(f"  ❌ 开仓失败: {res}")
        return None

def place_limit_close(symbol: str, side: str, entry_price: float, size: float) -> bool:
    """挂限价平仓单±8%（hedge模式）"""
    if side == 'buy':      # 多单：挂低于开仓价
        exit_price = entry_price * (1 - LIMIT_STOP_PCT)
        close_side = 'buy'       # 平多仓用buy（不是sell！）
        pos_side = 'long'
    else:                  # 空单：挂高于开仓价
        exit_price = entry_price * (1 + LIMIT_STOP_PCT)
        close_side = 'sell'      # 平空仓用sell（不是buy！）
        pos_side = 'short'

    order_path = '/api/v2/mix/order/place-order'
    order_body = {
        'symbol': symbol,
        'productType': 'USDT-FUTURES',
        'marginCoin': 'USDT',
        'marginMode': MARGIN_MODE,
        'side': close_side,
        'posSide': pos_side,
        'tradeSide': 'close',
        'orderType': 'limit',
        'size': str(size),
        'price': str(round(exit_price, 6)),
    }
    res = api_request('POST', order_path, body=order_body)
    if res and (res.get('code') == '00000' or res.get('code') == '0'):
        logger(f"  ✅ 限价止损单已挂: {symbol} {close_side} @ {exit_price:.6f} (±{LIMIT_STOP_PCT*100:.0f}%)")
        return True
    else:
        logger(f"  ⚠️ 限价止损单失败: {res}")
        return False

def get_entry_price(symbol: str) -> float:
    """获取持仓开仓价"""
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
    """获取当前持仓数量"""
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

# ========== 冷却检查 ==========
def is_in_cooldown(symbol: str) -> bool:
    db = load_pos_db()
    cooldowns = db.get('cooldowns', {})
    last_time = cooldowns.get(symbol, 0)
    if time.time() - last_time < 300:  # 5分钟冷却
        return True
    return False

def set_cooldown(symbol: str):
    db = load_pos_db()
    if 'cooldowns' not in db:
        db['cooldowns'] = {}
    db['cooldowns'][symbol] = time.time()
    save_pos_db(db)

# ========== 交易扫描（每30秒）==========
def scan_and_trade():
    """扫描热点库代币，检查信号，开仓"""
    hot = load_hot_db()
    if not hot:
        return

    logger("=" * 50)
    logger(f"开始交易扫描（{len(hot)}个热点代币）...")

    for coin in hot:
        symbol = coin['symbol']
        change24h = coin['change24h']

        if is_in_cooldown(symbol):
            continue

        # 检查做多信号
        long_ok, long_reason = check_signal_long(symbol, change24h)
        if long_ok:
            logger(f"✅ {symbol} 做多信号触发!")
            logger(f"  {long_reason}")
            # 计算开仓数量
            price = float(coin.get('last_price', 0))
            if price <= 0:
                ticker = api_request('GET', '/api/v2/mix/market/ticker',
                                     params={'symbol': symbol, 'productType': 'USDT-FUTURES'})
                if ticker:
                    price = float(ticker[0].get('lastPr', 0)) if isinstance(ticker, list) else float(ticker.get('lastPr', 0))
            if price <= 0:
                logger(f"  ⚠️ 无法获取价格，跳过")
                continue
            size = round(POSITION_SIZE / price * LEVERAGE, 4)
            if size <= 0:
                continue
            order_id = open_position(symbol, 'buy', size)
            if order_id:
                time.sleep(1)
                entry_price = get_entry_price(symbol)
                if entry_price > 0:
                    place_limit_close(symbol, 'buy', entry_price, size)
                    set_cooldown(symbol)
            continue

        # 检查做空信号
        short_ok, short_reason = check_signal_short(symbol, change24h)
        if short_ok:
            logger(f"✅ {symbol} 做空信号触发!")
            logger(f"  {short_reason}")
            price = float(coin.get('last_price', 0))
            if price <= 0:
                ticker = api_request('GET', '/api/v2/mix/market/ticker',
                                     params={'symbol': symbol, 'productType': 'USDT-FUTURES'})
                if ticker:
                    price = float(ticker[0].get('lastPr', 0)) if isinstance(ticker, list) else float(ticker.get('lastPr', 0))
            if price <= 0:
                logger(f"  ⚠️ 无法获取价格，跳过")
                continue
            size = round(POSITION_SIZE / price * LEVERAGE, 4)
            if size <= 0:
                continue
            order_id = open_position(symbol, 'sell', size)
            if order_id:
                time.sleep(1)
                entry_price = get_entry_price(symbol)
                if entry_price > 0:
                    place_limit_close(symbol, 'sell', entry_price, size)
                    set_cooldown(symbol)
            continue

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
        logger("极端行情交易机器人启动")
        logger(f"热点库: 每{HOT_SCAN_INTERVAL}秒扫描")
        logger(f"交易扫描: 每{TRADE_SCAN_INTERVAL}秒")
        logger(f"做多: BB≥{LONG_BB_DEV}% ADX≥{LONG_ADX} vr1<{LONG_VR_MAX} RSI∈[{LONG_RSI_MIN},{LONG_RSI_MAX}] 动量未衰竭")
        logger(f"做空: BB≥{SHORT_BB_DEV}% ADX≥{SHORT_ADX} vr1>{SHORT_VR_MIN} RSI∈[{SHORT_RSI_MIN},{SHORT_RSI_MAX}] 回落≥{SHORT_RETRACE_MIN*100:.0f}%")
        logger(f"仓位: {POSITION_SIZE}U {LEVERAGE}x {MARGIN_MODE}")
        logger(f"止盈: 限价±{LIMIT_STOP_PCT*100:.0f}%")
        logger("=" * 50)

        hot_scan_counter = 0
        trade_scan_counter = 0

        while True:
            try:
                # 启动时先扫描一次热点库
                if hot_scan_counter <= 0:
                    scan_hot_contracts()
                    hot_scan_counter = HOT_SCAN_INTERVAL // TRADE_SCAN_INTERVAL
                hot_scan_counter -= 1

                # 交易信号扫描
                scan_and_trade()

                # 等待下次扫描
                time.sleep(TRADE_SCAN_INTERVAL)
            except KeyboardInterrupt:
                logger("已停止")
                break
            except Exception as e:
                logger(f"主循环异常: {e}")
                time.sleep(10)

if __name__ == '__main__':
    main()
