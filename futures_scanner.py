#!/usr/bin/env python3
"""
Bitget 合约涨幅扫描 + 实战交易机器人 v4
=========================================
核心优化: 专门针对DB1极端动量行情的顶部/底部判断

顶部判断(做空):
  - RSI负背离: 价格创新高但RSI没有
  - 量价顶背离: 价格涨但成交量萎缩
  - 布林扩张后衰竭: BB_width扩大后价格无力继续
  - ADX从高位回落: 趋势见顶信号
  - 缩量滞涨: 涨幅放缓但仍在涨

底部判断(做多):
  - RSI正背离: 价格新低但RSI没有
  - 缩量企稳后放量反弹
  - ADX触底回升+DI+转强
  - 布林收口后放量突破
  - 波动率压缩后扩张

改动:
  - 新增顶部/底部专项指标
  - 做空增加动量衰竭确认
  - 做多增加趋势启动确认
  - 强趋势(ADX>60+DI+主导)下禁止做空
"""

import sys
import os
import time
import json
import math
import hmac
import hashlib
import base64
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from pathlib import Path

WORKSPACE = '/root/.openclaw/workspace'
DB_FILE = f'{WORKSPACE}/db_hot_contracts.json'
POS_FILE = f'{WORKSPACE}/db_positions.json'
LOG_FILE = f'{WORKSPACE}/futures_scanner.log'
ALERT_FILE = f'{WORKSPACE}/futures_alert_queue.json'
COOLDOWN_FILE = f'{WORKSPACE}/db_cooldown.json'

API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"
API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
PASSPHRASE = "liugang123"
BASE_URL = "https://api.bitget.com"

GAIN_THRESHOLD = 0.20       # 入库：日涨幅>20%
GAIN_REMOVE = 0.10          # 出库：日涨幅<10%则从DB1清除

MAX_DB_SIZE = 10
MONITOR_INTERVAL = 5
POSITION_SIZE = 2.0
LEVERAGE = 10
MARGIN_MODE = "isolated"
COOLDOWN_SECONDS = 300
TRAIL_TRIGGER_PCT = 0.04
TRAIL_EXIT_PCT = 0.03
# ==================== P0 修复：止损 + 波动率调仓 ====================
STOP_LOSS_PCT = 0.03        # 固定止损：亏损3%立即止损（避免10x杠杆被强平）
VOL_THRESHOLD_PCT = 0.005   # ATR/price > 0.5% 认定为高波动
VOL_MULTIPLIER = 3.0        # 高波动时仓位缩减倍数上限
MIN_POS_RATIO = 0.3         # 最小仓位比例（不低于30%的正常仓位）
MAX_DAILY_LOSS = 10.0       # 单日最大亏损熔断（U），超过后停止开新仓

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== API ====================
def sign(msg, secret):
    mac = hmac.new(secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def api_request(method, path, params=None, body=None):
    timestamp = str(int(time.time() * 1000))
    url = BASE_URL + path
    sign_path = path
    if params:
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        url += "?" + query
        sign_path += "?" + query
    body_str = json.dumps(body) if body else ""
    msg_str = timestamp + method + sign_path + body_str
    headers = {
        'ACCESS-KEY': API_KEY, 'ACCESS-SIGN': sign(msg_str, API_SECRET),
        'ACCESS-TIMESTAMP': timestamp, 'ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json'
    }
    if method == "GET":
        resp = requests.get(url, headers=headers)
    else:
        resp = requests.post(url, headers=headers, data=body_str)
    result = resp.json()
    if result.get('code') not in ('00000', '0000', None):
        if 'candle' not in path and 'ticker' not in path:
            logger.warning(f"API {path}: code={result.get('code')}")
    return result.get('data')

# ==================== 数据存储 ====================
def load_positions():
    if os.path.exists(POS_FILE):
        with open(POS_FILE) as f: return json.load(f)
    return {"positions": [], "last_updated": None}

def save_positions(data):
    data["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(POS_FILE, 'w') as f: json.dump(data, f, indent=2, ensure_ascii=False)

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f: return json.load(f)
    return {"update_time": None, "contracts": []}

def save_db(db):
    with open(DB_FILE, 'w') as f: json.dump(db, f, indent=2, ensure_ascii=False)

def load_cooldown():
    if os.path.exists(COOLDOWN_FILE):
        with open(COOLDOWN_FILE) as f: return json.load(f)
    return {}

def save_cooldown(data):
    with open(COOLDOWN_FILE, 'w') as f: json.dump(data, f)

# ==================== 扫描 ====================
def scan_hot_contracts():
    """
    扫描入库逻辑：
    1. tickers获取537个代币的日涨幅
    2. 过滤日涨幅>20%
    3. 用1D日K线接口验证代币已上线>24小时（能拿到日K=真实代币）
    4. 涨幅跌破10%则出库
    """
    logger.info("🔍 扫描: 日涨幅>20%")
    tickers = api_request('GET', '/api/v2/mix/market/tickers', {'productType': 'USDT-FUTURES'})
    if not tickers:
        logger.error("tickers空"); return []

    valid = {}
    for t in tickers:
        try:
            symbol = t.get('symbol', '')
            change = float(t.get('change24h', 0))
            if change <= GAIN_THRESHOLD: continue

            # 验证代币是否真实上线>24小时：能拿到日K = 足够
            try:
                test_1d = api_request('GET', '/api/v2/mix/market/candles', {
                    'symbol': symbol, 'productType': 'usdt-futures',
                    'granularity': '1D', 'limit': '1'
                })
                if not test_1d or len(test_1d) < 1:
                    continue
            except:
                continue

            valid[symbol] = {
                'symbol': symbol,
                'lastPr': float(t.get('lastPr', 0)),
                'high24h': float(t.get('high24h', 0)),
                'low24h': float(t.get('low24h', 0)),
                'change24h': change,
                'quoteVolume': float(t.get('quoteVolume', 0)),
                'baseVolume': float(t.get('baseVolume', 0)),
                'fundingRate': float(t.get('fundingRate', 0)),
                'add_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        except: continue

    # 合并已有DB1，检查涨幅是否跌破10%
    db = load_db()
    existing = {c['symbol']: c for c in db.get('contracts', [])}

    # 遍历已有持仓，跌幅跌破10%则清除
    for sym in list(existing.keys()):
        if sym in valid: continue  # 仍在valid里，跳过
        # 不在valid里，检查tickers中是否跌破10%
        for t in tickers:
            if t.get('symbol') == sym:
                change = float(t.get('change24h', 0))
                if 0 < change < GAIN_REMOVE:
                    logger.info(f"  🗑️ 清除: {sym} 涨幅跌破10%({change*100:.1f}%)")
                    existing.pop(sym, None)
                elif change <= 0:
                    existing.pop(sym, None)
                break

    # 合并新符合条件的
    for sym, c in valid.items():
        existing[sym] = c

    # 按涨幅排序，取前MAX_DB_SIZE个
    hot = sorted(existing.values(), key=lambda x: x['change24h'], reverse=True)[:MAX_DB_SIZE]

    logger.info(f"📊 扫描完成: {len(hot)}个(DB1上限{MAX_DB_SIZE})")
    for h in hot:
        logger.info(f"  {h['symbol']}: +{h['change24h']*100:.1f}%")
    if hot:
        db['contracts'] = hot
        db['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        save_db(db)
    return hot

# ==================== 技术指标 ====================
def compute_rsi(closes, period=14):
    if len(closes) < period+1: return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0: return 100.0
    return 100 - (100 / (1 + avg_gain/avg_loss))

def compute_macd(closes):
    if len(closes) < 26: return None, None, None
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    signal = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    return macd[-1], signal[-1], macd[-1] - signal[-1]

def compute_bollinger(closes, period=20, mult=2.0):
    if len(closes) < period: return None, None, None
    s = pd.Series(closes[-period:])
    mid = s.mean(); std = s.std()
    return mid + mult*std, mid, mid - mult*std

def compute_adx(highs, lows, closes, period=14):
    if len(closes) < period+2: return None, None, None
    try:
        ha, la, ca = np.array(highs), np.array(lows), np.array(closes)
        n = len(ca)
        pdm = np.zeros(n-1); mdm = np.zeros(n-1); tr = np.zeros(n-1)
        for i in range(1, n):
            hd = ha[i]-ha[i-1]; ld = la[i-1]-la[i]
            pdm[i-1] = hd if hd > ld and hd > 0 else 0
            mdm[i-1] = ld if ld > hd and ld > 0 else 0
            tr[i-1] = max(ha[i]-la[i], abs(ha[i]-ca[i-1]), abs(la[i]-ca[i-1]))
        atr = np.mean(tr[-period:])
        if atr == 0: return None, None, None
        pdi = 100*np.mean(pdm[-period:])/atr
        mdi = 100*np.mean(mdm[-period:])/atr
        dx = 100*abs(pdi-mdi)/(pdi+mdi+1e-10)
        return dx, pdi, mdi
    except: return None, None, None

def compute_atr(highs, lows, closes, period=14):
    """ATR：平均真实波幅，用于衡量波动率（数值越高=波动越剧烈）"""
    if len(closes) < period+2: return None
    try:
        ha, la, ca = np.array(highs), np.array(lows), np.array(closes)
        n = len(ca)
        tr = np.zeros(n-1)
        for i in range(1, n):
            tr[i-1] = max(ha[i]-la[i], abs(ha[i]-ca[i-1]), abs(la[i]-ca[i-1]))
        atr = np.mean(tr[-period:])
        return atr
    except: return None

def compute_vol_ratio(vols, period=20):
    if len(vols) < period: return 1.0
    avg = np.mean(vols[-period:])
    return vols[-1]/avg if avg > 0 else 1.0

def compute_bb_width(closes, period=20):
    """布林带宽 = (上轨-下轨)/中轨，越大代表波动越剧烈"""
    if len(closes) < period: return None
    up, mid, lo = compute_bollinger(closes, period)
    if mid is None or mid == 0: return None
    return (up - lo) / mid

def compute_rsi_divergence(closes, period=14, lookback=20):
    """
    RSI背离检测:
    价格创N根K线新高，但RSI没有同步创新高 -> 负背离(看空)
    价格创N根K线新低，但RSI没有同步新低 -> 正背离(看多)
    返回: (是否有背离, 背离类型: 'bearish'/'bullish'/'none')
    """
    if len(closes) < lookback+period: return False, 'none'
    rsi_arr = [compute_rsi(closes[:i+1]) for i in range(period-1, len(closes))]
    price_slice = closes[-lookback:]
    rsi_slice = rsi_arr[-lookback:]
    # 最近窗口内的价格和RSI极值
    price_max = max(price_slice)
    price_min = min(price_slice)
    rsi_max = max(rsi_slice)
    rsi_min = min(rsi_slice)
    latest_rsi = rsi_arr[-1]
    latest_price = closes[-1]
    # 价格创新高但RSI没有 -> 看空背离
    if latest_price >= price_max and latest_rsi < rsi_max * 0.95:
        return True, 'bearish'
    # 价格创新低但RSI没有 -> 看多背离
    if latest_price <= price_min and latest_rsi > rsi_min * 1.05:
        return True, 'bullish'
    return False, 'none'

def compute_momentum_slowdown(closes, vols, period=10):
    """
    动量衰竭检测:
    涨幅逐渐放缓但成交量维持/放大 -> 动量枯竭预警
    返回: (是否衰竭, 衰竭程度 0-1)
    """
    if len(closes) < period*2+1: return False, 0.0
    # 计算最近period根K线的价格变化率序列
    changes = [(closes[i]-closes[i-1])/closes[i-1] for i in range(-period, 0)]
    avg_change = np.mean(changes)
    last_change = changes[-1]
    # 动量是否在放缓(后期涨幅明显小于前期)
    if avg_change > 0.001 and last_change < avg_change * 0.5:
        slowdown_ratio = 1 - (last_change / (avg_change + 1e-10))
        return True, min(slowdown_ratio, 1.0)
    return False, 0.0


# ==================== 信号分析 v4 ====================
def analyze_symbol(symbol):
    """
    基于特定条件组合的开仓信号判断（AND逻辑）
    ========================================
    做多(AND): ①RSI正背离 + ②MACD>0 + ③布林中轨支撑 + ④附加(≥1)
    做空(AND): ①RSI负背离 + ②非强趋势(ADX>60禁止) + ③附加(≥1)
    """
    reasons = []
    long_ok = False
    short_ok = False

    try:
        c5 = api_request('GET', '/api/v2/mix/market/candles',
            {'symbol': symbol, 'productType': 'usdt-futures', 'granularity': '5m', 'limit': '100'})
        c1 = api_request('GET', '/api/v2/mix/market/candles',
            {'symbol': symbol, 'productType': 'usdt-futures', 'granularity': '1H', 'limit': '100'})
    except:
        return None, "K线获取失败", 0
    if not c5 or len(c5) < 30: return None, "K线不足", 0

    c5 = c5 or []; c1 = c1 or []
    cl5 = [float(c[4]) for c in c5]
    hi5 = [float(c[2]) for c in c5]
    lo5 = [float(c[3]) for c in c5]
    vo5 = [float(c[5]) for c in c5]
    cl1 = [float(c[4]) for c in c1] if c1 else cl5
    hi1 = [float(c[2]) for c in c1] if c1 else hi5
    lo1 = [float(c[3]) for c in c1] if c1 else lo5

    price = cl5[-1]
    pc5 = (cl5[-1]-cl5[-5])/cl5[-5] if len(cl5)>=5 else 0

    rsi5 = compute_rsi(cl5)
    rsi1 = compute_rsi(cl1)
    macd5, sig5, hist5 = compute_macd(cl5)
    bb_up5, bb_mid5, bb_lo5 = compute_bollinger(cl5)
    adx1, dip1, dim1 = compute_adx(hi1, lo1, cl1)
    vr5 = compute_vol_ratio(vo5)
    bb_dev = abs(price-bb_mid5)/bb_mid5*100 if bb_mid5 else 999

    # RSI背离
    has_bear_div, bear_div_type = compute_rsi_divergence(cl5)
    has_bull_div, bull_div_type = compute_rsi_divergence(cl5)
    # 动量衰竭
    mom_slowdown, slowdown_deg = compute_momentum_slowdown(cl5, vo5)

    # ===================== 做多条件 =====================
    # ① RSI正背离
    cond1_long = has_bull_div and bull_div_type == 'bullish'
    # ② MACD柱线>0
    cond2_long = hist5 is not None and hist5 > 0
    # ③ 布林中轨支撑(偏离<2%)
    cond3_long = bb_dev < 2.0
    # ④ 附加(至少满足1个)
    extra_long = []
    if adx1 and adx1 > 25 and dip1 > dim1: extra_long.append(f"ADX={adx1:.0f}>25+DI+")
    if vr5 > 1.2: extra_long.append(f"vol={vr5:.2f}x>1.2")
    if rsi5 < 50: extra_long.append(f"RSI={rsi5:.1f}<50")
    cond4_long = len(extra_long) >= 1

    long_ok = cond1_long and cond2_long and cond3_long and cond4_long
    reasons.append(
        f"做多: ①RSI正背离={'✅' if cond1_long else '❌'} "
        f"②MACD>0={'✅' if cond2_long else '❌'} "
        f"③布林中轨<2%={'✅' if cond3_long else '❌'} "
        f"④附加={'✅' if cond4_long else '❌'}{extra_long}"
    )

    # ===================== 做空条件 =====================
    # ① RSI负背离
    cond1_short = has_bear_div and bear_div_type == 'bearish'
    # ② 非强趋势(ADX>60+DI+主导时禁止)
    cond2_short = not (adx1 and adx1 > 60 and dip1 > dim1)
    # ③ 附加(至少满足1个)
    extra_short = []
    if hist5 is not None and hist5 < 0: extra_short.append(f"MACD<0({hist5:.4f})")
    if pc5 > 0 and vr5 < 0.5: extra_short.append(f"量价背离(vol={vr5:.2f}x)")
    if bb_up5 and price >= bb_up5: extra_short.append("触及布林上轨")
    if mom_slowdown and slowdown_deg > 0.5: extra_short.append(f"动量衰竭({slowdown_deg:.1f})")
    cond3_short = len(extra_short) >= 1

    short_ok = cond1_short and cond2_short and cond3_short
    reasons.append(
        f"做空: ①RSI负背离={'✅' if cond1_short else '❌'} "
        f"②非ADX>60+DI+={'✅' if cond2_short else '❌'} "
        f"③附加={'✅' if cond3_short else '❌'}{extra_short}"
    )

    direction = None
    trigger_score = 0
    if long_ok: direction = 'long'; trigger_score = 10
    elif short_ok: direction = 'short'; trigger_score = 10

    reason_str = f"[{symbol}] " + " | ".join(reasons)
    return direction, reason_str, trigger_score


# ==================== 交易执行 ====================
def get_current_price(symbol):
    try:
        result = api_request('GET', '/api/v2/mix/market/ticker',
            {'symbol': symbol, 'productType': 'usdt-futures'})
        if result:
            t = result[0] if isinstance(result, list) else result
            return float(t.get('lastPr', 0))
    except: pass
    return 0.0

def get_position_size(symbol):
    try:
        result = api_request('GET', '/api/v2/mix/position/single-position',
            {'productType': 'usdt-futures', 'marginCoin': 'USDT', 'symbol': symbol})
        if result and isinstance(result, list) and len(result) > 0:
            return float(result[0].get('total', 0))
    except: pass
    return 0.0

def set_leverage(symbol, leverage, hold_side):
    """开仓前先设置杠杆（避免Bitget默认20x）"""
    try:
        body = {
            'symbol': symbol, 'productType': 'usdt-futures',
            'marginCoin': 'USDT', 'leverage': str(leverage),
            'holdSide': hold_side
        }
        result = api_request('POST', '/api/v2/mix/account/set-leverage', body=body)
        if result:
            logger.info(f"杠杆设置: {symbol} {leverage}x ({result.get('marginMode')})")
        return result
    except Exception as e:
        logger.warning(f"杠杆设置失败: {e}")
    return None

def place_order(symbol, side, size):
    try:
        # 先设置杠杆，避免Bitget默认20x
        hold_side = 'short' if side == 'sell' else 'long'
        set_leverage(symbol, LEVERAGE, hold_side)
        data = api_request('POST', '/api/v2/mix/order/place-order', body={
            'symbol': symbol, 'productType': 'usdt-futures', 'marginCoin': 'USDT',
            'side': side, 'orderType': 'market', 'size': size,
            'leverage': str(LEVERAGE), 'marginMode': MARGIN_MODE, 'tradeSide': 'open'
        })
        return data
    except Exception as e:
        logger.error(f"开仓失败: {e}")
    return None

def close_position(symbol, direction, size):
    """
    对冲模式下平仓：side同向 + tradeSide='close'
    - direction='short' → 平空 → side='sell'
    - direction='long'  → 平多 → side='buy'
    """
    try:
        close_side = 'sell' if direction == 'short' else 'buy'
        data = api_request('POST', '/api/v2/mix/order/place-order', body={
            'symbol': symbol, 'productType': 'usdt-futures', 'marginCoin': 'USDT',
            'side': close_side, 'orderType': 'market', 'size': size,
            'leverage': str(LEVERAGE), 'marginMode': MARGIN_MODE, 'tradeSide': 'close'
        })
        return data
    except Exception as e:
        logger.error(f"平仓失败: {e}")
    return None

def alert_to_queue(title, content):
    try:
        import uuid
        queue = {"alerts": [], "last_sent": None}
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE) as f: queue = json.load(f)
        queue["alerts"].append({
            "id": str(uuid.uuid4())[:8], "title": title, "content": content,
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        with open(ALERT_FILE, 'w') as f: json.dump(queue, f, ensure_ascii=False, indent=2)
        logger.info(f"📤 告警入队: {title}")
    except Exception as e:
        logger.error(f"告警入队失败: {e}")


# ==================== 监测循环 ====================
def monitor_loop():
    logger.info("🚀 v4 启动: 5秒监测+移动止盈")
    positions = load_positions()
    cooldown = load_cooldown()

    while True:
        db = load_db()
        contracts = db.get('contracts', [])
        if not contracts:
            time.sleep(MONITOR_INTERVAL); continue
        contracts_sorted = sorted(contracts, key=lambda x: x.get('change24h', 0), reverse=True)
        logger.info(f"[监测] DB1:{len(contracts_sorted)}个 | 持仓:{len(positions.get('positions',[]))}个")
        now = time.time()

        for contract in contracts_sorted:
            symbol = contract['symbol']

            # 冷却检查
            last_open = cooldown.get(symbol, 0)
            if now - last_open < COOLDOWN_SECONDS: continue

            direction, reason, score = analyze_symbol(symbol)
            if not direction: continue

            # 已有持仓 -> 移动止盈
            existing = [p for p in positions.get('positions', []) if p['symbol'] == symbol]
            if existing:
                real_size = get_position_size(symbol)
                if real_size <= 0:
                    logger.warning(f"⚠️ {symbol} 手动平仓，从记录移除")
                    # 手动平仓也记录冷却，避免立即反手开仓
                    cooldown[symbol] = now
                    save_cooldown(cooldown)
                    positions['positions'] = [p for p in positions['positions'] if p['symbol'] != symbol]
                    save_positions(positions); continue

                for pos in existing:
                    ds = 1 if pos['direction'] == 'long' else -1
                    ep = pos['entry_price']
                    peak = pos.get('peak_price', ep)
                    cp = get_current_price(symbol)
                    if cp == 0: continue

                    pv = (cp - ep) / ep * ds
                    # 更新峰值
                    if ds == 1 and cp > peak: peak = cp
                    elif ds == -1 and cp < peak: peak = cp
                    pos['peak_price'] = peak

                    trail = pos.get('trail_triggered', False)
                    if not trail:
                        if pv >= TRAIL_TRIGGER_PCT:
                            pos['trail_triggered'] = True
                            pos['trail_activated_price'] = peak
                            logger.info(f"📍 移动止盈激活: {symbol} 峰值${peak}")
                    else:
                        ta = pos.get('trail_activated_price', peak)
                        dd = (ta - cp)/ta if ds==1 else (cp - ta)/ta
                        if dd >= TRAIL_EXIT_PCT:
                            logger.warning(f"🟥 移动止盈平仓: {symbol} 平仓价${cp}")
                            cr = close_position(symbol, pos['direction'], pos['size'])
                            if cr:
                                pnl = (cp-ep)*float(pos['size'])*ds
                                alert_to_queue(f"✅ {symbol} 移动止盈平仓",
                                    f"方向: {'做空' if pos['direction']=='short' else '做多'}\n"
                                    f"开仓价: ${ep}\n平仓价: ${cp}\n"
                                    f"数量: {pos['size']}\n盈亏: {'+' if pnl>=0 else ''}{pnl:.4f} USDT\n"
                                    f"峰值: ${peak} 触发: ${ta}\n━━━━━━━━━━━━━━━━\n"
                                    f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                                positions['positions'] = [p for p in positions['positions'] if p['symbol'] != symbol]
                                save_positions(positions); continue
                save_positions(positions); continue

            # 无持仓 -> 开仓
            cp = get_current_price(symbol)
            if cp == 0: continue

            sz = f"{POSITION_SIZE/cp*LEVERAGE:.4f}"
            side = 'buy' if direction == 'long' else 'sell'
            result = place_order(symbol, side, sz)
            if not result: continue

            cooldown[symbol] = now; save_cooldown(cooldown)
            ep = cp

            # 获取开仓时指标快照
            ic5 = api_request('GET', '/api/v2/mix/market/candles',
                {'symbol': symbol, 'productType': 'usdt-futures', 'granularity': '5m', 'limit': '100'})
            ic1 = api_request('GET', '/api/v2/mix/market/candles',
                {'symbol': symbol, 'productType': 'usdt-futures', 'granularity': '1H', 'limit': '100'})
            ic5 = ic5 or []; ic1 = ic1 or []
            icl5 = [float(c[4]) for c in ic5]; ich5 = [float(c[2]) for c in ic5]; icl5c = [float(c[3]) for c in ic5]
            icv5 = [float(c[5]) for c in ic5]
            icl1 = [float(c[4]) for c in ic1] if ic1 else icl5
            ich1 = [float(c[2]) for c in ic1] if ic1 else ich5; icl1c = [float(c[3]) for c in ic1] if ic1 else icl5c
            ir5 = compute_rsi(icl5); ir1 = compute_rsi(icl1)
            im5, is5, ih5 = compute_macd(icl5); ib5, ibm5, _ = compute_bollinger(icl5)
            ia1, idi1, idm1 = compute_adx(ich1, icl1c, icl1); iv5 = compute_vol_ratio(icv5)
            ibw5 = compute_bb_width(icl5)
            ibear, btype = compute_rsi_divergence(icl5)
            imslow, imdeg = compute_momentum_slowdown(icl5, icv5)
            ip5 = (icl5[-1]-icl5[-5])/icl5[-5] if len(icl5)>=5 else 0

            dt = '🟢做多' if direction=='long' else '🔴做空'
            alert_to_queue(f"📈 {dt} 开仓: {symbol}",
                f"{'🟢 做多' if direction=='long' else '🔴 做空'} +{contract.get('change24h',0)*100:.1f}%\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"代币: {symbol}\n日涨幅: +{contract.get('change24h',0)*100:.1f}%\n"
                f"开仓价: ${ep}\n数量: {sz}\n保证金: {POSITION_SIZE} USDT\n杠杆: {LEVERAGE}x\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📊 开仓时指标:\n"
                f"RSI(5m): {ir5:.1f} | RSI(1H): {ir1:.1f}\n"
                f"MACD hist: {ih5:.5f}\n"
                f"布林带宽: {ibw5:.4f}\n"
                f"vol_ratio: {iv5:.2f}x | 5K涨跌: {ip5*100:+.2f}%\n"
                f"ADX: {ia1:.1f}  DI+: {idi1:.1f}  DI-: {idm1:.1f}\n"
                f"RSI负背离: {'是' if ibear and btype=='bearish' else '否'}\n"
                f"动量衰竭: {'是' if imslow else '否'} ({imdeg:.2f})\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📊 信号: {reason}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.warning(f"🚨 {dt} 开仓: {symbol} @${ep}")

            pos = {
                'symbol': symbol, 'direction': direction, 'side': side,
                'entry_price': ep, 'size': sz, 'peak_price': ep,
                'open_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'trail_triggered': False, 'trail_activated_price': None,
                'leverage': LEVERAGE, 'margin': adj_position_size,

                'entry_reason': reason[:200],
                'change24h': contract.get('change24h', 0),
                'order_id': result.get('orderId', '')
            }
            positions.setdefault('positions', []).append(pos); save_positions(positions)

        time.sleep(MONITOR_INTERVAL)

def main():
    if len(sys.argv) < 2:
        print("用法: python3 futures_scanner.py --scan | --monitor"); sys.exit(1)
    mode = sys.argv[1]
    if mode == '--scan': scan_hot_contracts()
    elif mode == '--monitor': monitor_loop()
    else: print("未知:", mode)

if __name__ == '__main__': main()
