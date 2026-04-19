#!/usr/bin/env python3
"""
Bitget 合约涨幅扫描 + 实战交易机器人 v2
=========================================
功能:
  --scan    每5分钟扫描537个USDT-M永续合约，日涨幅>20%加入数据库1号
  --monitor 每5秒监测数据库1号代币，满足上涨/下跌条件 → 开1U逐仓20x仓位
            移动止盈: ±3%后激活，从最高点滑落1.5%执行平仓
            冷却时间: 同一币种每仓间隔>5分钟

用法:
  python3 futures_scanner.py --scan        # cron每5分钟
  python3 futures_scanner.py --monitor    # 常驻进程，supervisor管理

⚠️ 注意: 实盘交易，谨慎操作
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

# ==================== 配置 ====================
WORKSPACE = '/root/.openclaw/workspace'
DB_FILE = f'{WORKSPACE}/db_hot_contracts.json'
POS_FILE = f'{WORKSPACE}/db_positions.json'     # 持仓数据库
LOG_FILE = f'{WORKSPACE}/futures_scanner.log'
ALERT_FILE = f'{WORKSPACE}/futures_alert_queue.json'

API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"
API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
PASSPHRASE = "liugang123"
BASE_URL = "https://api.bitget.com"

GAIN_THRESHOLD = 0.20       # 日涨幅阈值 20%
MONITOR_INTERVAL = 5        # 监测间隔（秒）
MAX_DB_SIZE = 50            # 数据库1号最多50个
POSITION_SIZE = 1.0         # 每仓保证金 1 USDT
LEVERAGE = 20              # 杠杆倍数
MARGIN_MODE = "isolated"    # 逐仓
COOLDOWN_SECONDS = 300      # 开仓冷却 5分钟

# 移动止盈参数
TRAIL_TRIGGER_PCT = 0.03   # 触发门槛: 价格偏离开仓价±3%
TRAIL_EXIT_PCT = 0.015     # 退出门槛: 从最高点滑落1.5%

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==================== API 基础 ====================
def sign(msg: str, secret: str) -> str:
    mac = hmac.new(secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def api_request(method: str, path: str, params: Dict = None, body: Dict = None) -> Dict:
    timestamp = str(int(time.time() * 1000))
    url = BASE_URL + path
    sign_path = path
    if params:
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        url += "?" + query
        sign_path += "?" + query

    body_str = json.dumps(body) if body else ""
    msg_str = timestamp + method + sign_path + body_str
    signature = sign(msg_str, API_SECRET)

    headers = {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json'
    }

    if method == "GET":
        resp = requests.get(url, headers=headers)
    else:
        resp = requests.post(url, headers=headers, data=body_str)

    result = resp.json()
    if result.get('code') not in ('00000', '0000', None):
        # 静默处理market数据的常见错误（400171/400172），交易端点错误仍上报
        if 'candle' not in path and 'ticker' not in path:
            logger.warning(f"API {path}: code={result.get('code')} msg={result.get('msg','')[:60]}")
    return result.get('data')


# ==================== 持仓数据库 ====================
def load_positions() -> Dict:
    if os.path.exists(POS_FILE):
        with open(POS_FILE) as f:
            return json.load(f)
    return {"positions": [], "last_updated": None}

def save_positions(data: Dict):
    data["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(POS_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_db() -> Dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return {"update_time": None, "contracts": []}

def save_db(db: Dict):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


# ==================== 5分钟涨幅扫描 ====================
def scan_hot_contracts():
    """扫描所有USDT-M永续合约，筛选日涨幅>20%"""
    logger.info("🔍 开始扫描全网合约(日涨幅>20%)...")
    tickers = api_request('GET', '/api/v2/mix/market/tickers', {'productType': 'USDT-FUTURES'})
    if not tickers:
        logger.error("❌ tickers接口返回空")
        return []

    hot = []
    for t in tickers:
        try:
            change = float(t.get('change24h', 0))
            if change > GAIN_THRESHOLD:
                hot.append({
                    'symbol': t['symbol'],
                    'lastPr': float(t.get('lastPr', 0)),
                    'high24h': float(t.get('high24h', 0)),
                    'low24h': float(t.get('low24h', 0)),
                    'change24h': change,
                    'quoteVolume': float(t.get('quoteVolume', 0)),
                    'baseVolume': float(t.get('baseVolume', 0)),
                    'fundingRate': float(t.get('fundingRate', 0)),
                    'add_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
        except (ValueError, TypeError):
            continue

    hot.sort(key=lambda x: x['change24h'], reverse=True)
    logger.info(f"📊 扫描完成: 537个合约中发现 {len(hot)} 个日涨幅>20%")
    for h in hot[:10]:
        logger.info(f"  🔥 {h['symbol']}: +{h['change24h']*100:.1f}% 现价${h['lastPr']}")

    if hot:
        db = load_db()
        existing = {c['symbol']: c for c in db.get('contracts', [])}
        for c in hot:
            existing[c['symbol']] = c
        sorted_list = sorted(existing.values(), key=lambda x: x['change24h'], reverse=True)[:MAX_DB_SIZE]
        db['contracts'] = sorted_list
        db['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        save_db(db)
        logger.info(f"📦 数据库1号已更新，共 {len(sorted_list)} 个代币")

    return hot


# ==================== 技术指标 ====================
def compute_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_macd(closes: List[float]):
    if len(closes) < 26:
        return None, None, None
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    signal = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    histogram = macd - signal
    return macd[-1], signal[-1], histogram[-1]

def compute_bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0):
    if len(closes) < period:
        return None, None, None
    series = pd.Series(closes[-period:])
    mid = series.mean()
    std = series.std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower

def compute_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14):
    if len(closes) < period + 2:
        return None, None, None
    try:
        highs_arr = np.array(highs)
        lows_arr = np.array(lows)
        closes_arr = np.array(closes)
        n = len(closes_arr)
        plus_dm = np.zeros(n - 1)
        minus_dm = np.zeros(n - 1)
        tr = np.zeros(n - 1)
        for i in range(1, n):
            high_diff = highs_arr[i] - highs_arr[i-1]
            low_diff = lows_arr[i-1] - lows_arr[i]
            plus_dm[i-1] = high_diff if (high_diff > low_diff and high_diff > 0) else 0
            minus_dm[i-1] = low_diff if (low_diff > high_diff and low_diff > 0) else 0
            tr[i-1] = max(
                highs_arr[i] - lows_arr[i],
                abs(highs_arr[i] - closes_arr[i-1]),
                abs(lows_arr[i] - closes_arr[i-1])
            )
        atr = np.mean(tr[-period:])
        if atr == 0:
            return None, None, None
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        return dx, plus_di, minus_di
    except:
        return None, None, None

def compute_vol_ratio(volumes: List[float], period: int = 20) -> float:
    if len(volumes) < period:
        return 1.0
    avg_vol = np.mean(volumes[-period:])
    if avg_vol == 0:
        return 1.0
    return volumes[-1] / avg_vol


# ==================== 趋势分析 ====================
def analyze_symbol(symbol: str) -> Tuple[Optional[str], str, int]:
    """
    分析代币是否满足上涨/下跌开仓条件
    返回: (方向或None, 分析理由, 评分)
    方向: 'long' = 做多, 'short' = 做空, None = 不操作
    """
    reasons = []
    long_score = 0   # 做多信号分
    short_score = 0  # 做空信号分

    # 获取5m K线
    try:
        candles_5m = api_request('GET', '/api/v2/mix/market/candles', {
            'symbol': symbol, 'productType': 'usdt-futures',
            'granularity': '5m', 'limit': '100'
        })
    except:
        return None, "K线获取失败", 0

    if not candles_5m or len(candles_5m) < 30:
        return None, f"K线不足({len(candles_5m) if candles_5m else 0}根)", 0

    closes_5m = [float(c[4]) for c in candles_5m]
    highs_5m = [float(c[2]) for c in candles_5m]
    lows_5m = [float(c[3]) for c in candles_5m]
    vols_5m = [float(c[5]) for c in candles_5m]

    # 获取1H K线（部分新代币不支持1H/4H，降级处理）
    try:
        candles_1h_raw = api_request('GET', '/api/v2/mix/market/candles', {
            'symbol': symbol, 'productType': 'usdt-futures',
            'granularity': '1H', 'limit': '100'
        })
        candles_1h = candles_1h_raw if candles_1h_raw else []
    except:
        candles_1h = []

    closes_1h = [float(c[4]) for c in candles_1h] if candles_1h else closes_5m
    highs_1h = [float(c[2]) for c in candles_1h] if candles_1h else highs_5m
    lows_1h = [float(c[3]) for c in candles_1h] if candles_1h else lows_5m
    vols_1h = [float(c[5]) for c in candles_1h] if candles_1h else vols_5m

    price = closes_5m[-1]
    price_change_pct = (closes_5m[-1] - closes_5m[-5]) / closes_5m[-5] if len(closes_5m) >= 5 else 0

    # ========== 指标计算 ==========
    rsi_5m = compute_rsi(closes_5m)
    rsi_1h = compute_rsi(closes_1h)
    macd_5m, sig_5m, hist_5m = compute_macd(closes_5m)
    macd_1h, sig_1h, hist_1h = compute_macd(closes_1h)
    bb_upper, bb_mid, bb_lower = compute_bollinger(closes_5m)
    bb_upper_1h, _, _ = compute_bollinger(closes_1h)
    adx_1h, plus_di, minus_di = compute_adx(highs_1h, lows_1h, closes_1h)
    vol_r_5m = compute_vol_ratio(vols_5m)
    vol_r_1h = compute_vol_ratio(vols_1h)

    # ========== 上涨条件 (做多) ==========
    # 1. RSI 回调至合理区间(35-60) = 蓄力
    if 35 <= rsi_5m <= 60:
        long_score += 2
        reasons.append(f"RSI5m={rsi_5m:.1f}(蓄力区间)")
    elif rsi_5m < 35:
        long_score += 1
        reasons.append(f"RSI5m={rsi_5m:.1f}(超卖)")

    # 2. MACD 金叉或柱线转正
    if hist_5m is not None and hist_5m > 0 and closes_5m[-1] > closes_5m[-3]:
        long_score += 2
        reasons.append("MACD5m金叉(动能转多)")
    elif hist_5m is not None and hist_5m > 0:
        long_score += 1
        reasons.append("MACD5m柱线为正")

    # 3. 放量配合上涨
    if vol_r_5m > 1.5 and price_change_pct > 0.005:
        long_score += 2
        reasons.append(f"放量上涨(vol={vol_r_5m:.1f}x)")
    elif vol_r_5m > 1.2 and price_change_pct > 0:
        long_score += 1
        reasons.append(f"温和放量(vol={vol_r_5m:.1f}x)")

    # 4. ADX强势 + DI+主导
    if adx_1h is not None:
        if adx_1h > 30 and plus_di > minus_di:
            long_score += 2
            reasons.append(f"ADX={adx_1h:.1f}+DI+主导(趋势强)")
        elif adx_1h > 20 and plus_di > minus_di:
            long_score += 1
            reasons.append(f"ADX={adx_1h:.1f}+多方排列")

    # 5. 回调至布林中轨支撑
    if bb_mid is not None and abs(price - bb_mid) / bb_mid < 0.02:
        long_score += 1
        reasons.append(f"回踩布林中轨支撑")

    # ========== 下跌条件 (做空) ==========
    # 1. RSI 超买
    if rsi_5m > 75:
        short_score += 3
        reasons.append(f"RSI5m={rsi_5m:.1f}(严重超买)")
    elif rsi_5m > 65:
        short_score += 2
        reasons.append(f"RSI5m={rsi_5m:.1f}(超买)")

    if rsi_1h > 72:
        short_score += 2
        reasons.append(f"RSI1h={rsi_1h:.1f}(中期超买)")

    # 2. MACD 死叉或柱线转负
    if hist_5m is not None and hist_5m < -0.5:
        short_score += 3
        reasons.append(f"MACD5m柱线转负({hist_5m:.4f})")
    elif macd_5m is not None and sig_5m is not None and macd_5m < sig_5m:
        short_score += 1
        reasons.append("MACD5m死叉")

    # 3. 缩量上涨(量价背离)
    if price_change_pct > 0.005 and vol_r_5m < 0.6:
        short_score += 3
        reasons.append(f"缩量上涨(vol={vol_r_5m:.2f}x, 量价背离)")
    elif price_change_pct > 0.002 and vol_r_5m < 0.8:
        short_score += 1
        reasons.append(f"量能萎缩(vol={vol_r_5m:.2f}x)")

    # 4. 触及/突破布林上轨
    if bb_upper is not None:
        if price >= bb_upper:
            short_score += 2
            reasons.append(f"触及布林上轨(${bb_upper:.4f})")
        elif price >= bb_upper * 0.98:
            short_score += 1
            reasons.append(f"逼近布林上轨(${bb_upper:.4f})")

    # 5. ADX趋弱 + DI-主导
    if adx_1h is not None:
        if adx_1h < 20:
            short_score += 2
            reasons.append(f"ADX1h={adx_1h:.1f}(趋势减弱)")
        if minus_di is not None and plus_di is not None and minus_di > plus_di:
            short_score += 2
            reasons.append(f"DI-({minus_di:.1f})>DI+({plus_di:.1f})空头排列")

    # ========== 决定方向 ==========
    direction = None
    trigger_score = 0

    if long_score >= 5 and long_score > short_score:
        direction = 'long'
        trigger_score = long_score
    elif short_score >= 4 and short_score >= long_score:
        direction = 'short'
        trigger_score = short_score

    reason_str = f"[{symbol}] 多:{long_score} 空:{short_score} | " + " | ".join(reasons)
    return direction, reason_str, trigger_score


# ==================== 交易执行 ====================
def get_current_price(symbol: str) -> float:
    """获取当前最新价格"""
    try:
        result = api_request('GET', '/api/v2/mix/market/ticker',
                           {'symbol': symbol, 'productType': 'usdt-futures'})
        if result:
            return float(result.get('lastPr', 0))
    except:
        pass
    return 0.0

def place_order(symbol: str, side: str, size: str) -> Optional[Dict]:
    """市价开仓"""
    try:
        data = api_request('POST', '/api/v2/mix/order/place-order', body={
            'symbol': symbol,
            'productType': 'usdt-futures',
            'marginCoin': 'USDT',
            'side': side,        # buy=做多, sell=做空
            'orderType': 'market',
            'size': size,
            'leverage': str(LEVERAGE),
            'marginMode': MARGIN_MODE,
            'tradeSide': 'open'
        })
        if data:
            return data
    except Exception as e:
        logger.error(f"❌ 开仓失败: {e}")
    return None

def close_position(symbol: str, side: str, size: str) -> Optional[Dict]:
    """市价平仓"""
    try:
        # 平仓时 side 相反
        close_side = 'sell' if side == 'buy' else 'buy'
        data = api_request('POST', '/api/v2/mix/order/place-order', body={
            'symbol': symbol,
            'productType': 'usdt-futures',
            'marginCoin': 'USDT',
            'side': close_side,
            'orderType': 'market',
            'size': size,
            'leverage': str(LEVERAGE),
            'marginMode': MARGIN_MODE,
            'tradeSide': 'close'
        })
        return data
    except Exception as e:
        logger.error(f"❌ 平仓失败: {e}")
    return None

def alert_to_queue(title: str, content: str):
    """写入告警队列"""
    try:
        queue = {"alerts": [], "last_sent": None}
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE) as f:
                queue = json.load(f)
        import uuid
        queue["alerts"].append({
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "content": content,
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        with open(ALERT_FILE, 'w') as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        logger.info(f"📤 告警入队: {title}")
    except Exception as e:
        logger.error(f"❌ 告警入队失败: {e}")


# ==================== 主监测循环 ====================
def monitor_loop():
    logger.info("🚀 启动5秒级监测+交易模式")
    positions = load_positions()
    cooldown = {}  # symbol -> 上次开仓时间

    while True:
        db = load_db()
        contracts = db.get('contracts', [])
        if not contracts:
            time.sleep(MONITOR_INTERVAL)
            continue

        logger.info(f"[监测] 数据库1号: {len(contracts)}个代币 | 持仓: {len(positions.get('positions',[]))}个")

        for contract in contracts:
            symbol = contract['symbol']
            now = time.time()

            # ========== 检查冷却 ==========
            last_open = cooldown.get(symbol, 0)
            if now - last_open < COOLDOWN_SECONDS:
                continue  # 还在冷却中

            # ========== 分析信号 ==========
            direction, reason, score = analyze_symbol(symbol)
            if not direction:
                continue

            # ========== 检查是否已有该币种持仓 ==========
            existing = [p for p in positions.get('positions', []) if p['symbol'] == symbol]
            if existing:
                # 已有持仓，检查移动止盈
                for pos in existing:
                    direction_sign = 1 if pos['direction'] == 'long' else -1
                    peak_price = pos.get('peak_price', pos['entry_price'])
                    entry_price = pos['entry_price']
                    current_price = get_current_price(symbol)

                    if current_price == 0:
                        continue

                    price_vs_entry = (current_price - entry_price) / entry_price * direction_sign

                    # 更新最高/最低价
                    if direction_sign == 1 and current_price > peak_price:
                        pos['peak_price'] = current_price
                        peak_price = current_price
                    elif direction_sign == -1 and current_price < peak_price:
                        pos['peak_price'] = current_price
                        peak_price = current_price

                    # 检查移动止盈
                    trail_triggered = pos.get('trail_triggered', False)
                    if not trail_triggered:
                        if price_vs_entry >= TRAIL_TRIGGER_PCT:
                            pos['trail_triggered'] = True
                            pos['trail_activated_price'] = peak_price
                            logger.info(f"📍 移动止盈激活: {symbol} 最高价${peak_price} (偏离{(price_vs_entry)*100:.1f}%)")
                    else:
                        # 已激活，计算从激活价滑落了多少
                        trail_activated = pos.get('trail_activated_price', peak_price)
                        drawdown = (peak_price - current_price) / trail_activated if direction_sign == 1 else (current_price - peak_price) / trail_activated
                        drawdown *= direction_sign  # 转为正值

                        if drawdown >= TRAIL_EXIT_PCT:
                            # 执行平仓
                            logger.warning(f"🟥 移动止盈平仓: {symbol} 当前价${current_price} 从峰值${trail_activated}滑落{drawdown*100:.1f}%")
                            close_result = close_position(symbol, pos['direction'], pos['size'])
                            if close_result:
                                pnl = (current_price - entry_price) * float(pos['size']) * direction_sign
                                alert_to_queue(
                                    f"✅ {symbol} 移动止盈平仓",
                                    f"方向: {'做空' if pos['direction']=='short' else '做多'}\n"
                                    f"开仓价: ${entry_price}\n平仓价: ${current_price}\n"
                                    f"数量: {pos['size']}\n"
                                    f"盈亏: {'+' if pnl >= 0 else ''}{pnl:.4f} USDT\n"
                                    f"峰值: ${peak_price} 触发价: ${trail_activated}\n"
                                    f"━━━━━━━━━━━━━━━━\n"
                                    f"⏰ {datetime.now().strftime('%H:%M:%S')}"
                                )
                                # 从持仓列表移除
                                positions['positions'] = [p for p in positions['positions'] if p['symbol'] != symbol]
                                save_positions(positions)
                            continue

                    # 更新持仓记录中的peak_price
                    for p in positions['positions']:
                        if p['symbol'] == symbol:
                            p['peak_price'] = peak_price

                save_positions(positions)
                continue

            # ========== 无持仓 -> 检查是否满足开仓条件 ==========
            current_price = get_current_price(symbol)
            if current_price == 0:
                continue

            logger.info(f"📡 {symbol} {'🟢做多' if direction=='long' else '🔴做空'} 信号强({score}分) | {reason[:80]}")

            # 计算开仓数量: 1 USDT / 当前价格 * 20倍杠杆
            size_float = POSITION_SIZE / current_price * LEVERAGE
            # Bitget要求size为正数，且需要取整到合适位数
            size_str = f"{size_float:.4f}"

            # 开仓
            side = 'buy' if direction == 'long' else 'sell'
            result = place_order(symbol, side, size_str)

            if result:
                cooldown[symbol] = now
                entry_price = current_price

                # 记录持仓
                pos_record = {
                    'symbol': symbol,
                    'direction': direction,
                    'side': side,
                    'entry_price': entry_price,
                    'size': size_str,
                    'peak_price': entry_price,
                    'open_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'trail_triggered': False,
                    'trail_activated_price': None,
                    'leverage': LEVERAGE,
                    'margin': POSITION_SIZE,
                    'entry_reason': reason[:200],
                    'change24h': contract.get('change24h', 0),
                    'order_id': result.get('orderId', '')
                }
                positions.setdefault('positions', []).append(pos_record)
                save_positions(positions)

                dir_text = '🟢做多' if direction == 'long' else '🔴做空'
                alert_to_queue(
                    f"📈 {dir_text} 开仓: {symbol}",
                    f"{'🟢 做多' if direction=='long' else '🔴 做空'} {'+'+str(contract.get('change24h',0)*100)[:4]+'%' if direction=='long' else ''}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"代币: {symbol}\n"
                    f"日涨幅: +{contract.get('change24h',0)*100:.1f}%\n"
                    f"开仓价: ${entry_price}\n"
                    f"数量: {size_str}\n"
                    f"保证金: {POSITION_SIZE} USDT\n"
                    f"杠杆: {LEVERAGE}x 逐仓\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📊 信号分析:\n{reason}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                logger.warning(f"🚨 {dir_text} 开仓: {symbol} @${entry_price} 数量{size_str}")
            else:
                logger.error(f"❌ 开仓失败: {symbol}")

        time.sleep(MONITOR_INTERVAL)


# ==================== 主函数 ====================
def main():
    if len(sys.argv) < 2:
        print("用法: python3 futures_scanner.py --scan | --monitor")
        sys.exit(1)

    mode = sys.argv[1]
    if mode == '--scan':
        scan_hot_contracts()
    elif mode == '--monitor':
        monitor_loop()
    else:
        print("未知模式:", mode)
        sys.exit(1)

if __name__ == '__main__':
    main()
