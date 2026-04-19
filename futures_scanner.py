#!/usr/bin/env python3
"""
Bitget 合约涨幅扫描器 + 10秒级监测机器人
==========================================
功能:
  --scan   每5分钟扫描全网537个USDT-M永续合约，日涨幅>20%则加入数据库1号
  --monitor  每10秒检查数据库1号代币，根据K线指标判断下跌条件
             满足条件则通过微信推送报警

用法:
  python3 futures_scanner.py --scan        # 一次性扫描（配合cron每5分钟执行）
  python3 futures_scanner.py --monitor      # 持续监测（配合cron每分钟执行，进程常驻）

依赖:
  Bitget API v2 (已配置 API Key: bg_55d7ddd792c3ebab233b4a6911f95f99)
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
LOG_FILE = f'{WORKSPACE}/futures_scanner.log'

API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"
API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
PASSPHRASE = "liugang123"
BASE_URL = "https://api.bitget.com"

GAIN_THRESHOLD = 0.20      # 日涨幅阈值 20%
MONITOR_INTERVAL = 10      # 监测间隔（秒）
MAX_DB_SIZE = 50           # 数据库1号最多存50个代币（按日涨幅排序）

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

def api_request(method: str, path: str, params: Dict = None) -> Dict:
    """发送带签名的API请求"""
    timestamp = str(int(time.time() * 1000))
    url = BASE_URL + path
    sign_path = path
    if params:
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        url += "?" + query
        sign_path += "?" + query

    body_str = ""
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
    if result.get('code') != '00000':
        raise Exception(f"API Error {result.get('code')}: {result.get('msg')}")
    return result.get('data', [])


# ==================== 数据库1号操作 ====================
def load_db() -> Dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return {"update_time": None, "contracts": []}

def save_db(db: Dict):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def update_db(new_contracts: List[Dict]):
    """更新数据库1号：合并新旧数据，按日涨幅排序"""
    db = load_db()
    existing = {c['symbol']: c for c in db['contracts']}

    for c in new_contracts:
        existing[c['symbol']] = c

    # 重新按涨幅排序，只保留前MAX_DB_SIZE个
    sorted_list = sorted(existing.values(), key=lambda x: x['change24h'], reverse=True)[:MAX_DB_SIZE]

    db['contracts'] = sorted_list
    db['update_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    save_db(db)
    return db


# ==================== 5分钟涨幅扫描 ====================
def scan_hot_contracts():
    """扫描所有USDT-M永续合约，筛选日涨幅>20%的"""
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
        db = update_db(hot)
        logger.info(f"📦 数据库1号已更新，共 {len(db['contracts'])} 个代币")

    return hot


# ==================== 技术指标计算 ====================
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
    """返回 (macd, signal, histogram) """
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
    """计算ADX和DI"""
    if len(closes) < period + 1:
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
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx  # simplified
        return adx, plus_di, minus_di
    except:
        return None, None, None

def compute_volume_ratio(volumes: List[float], period: int = 20) -> float:
    """当前成交量 / 过去N根均量"""
    if len(volumes) < period:
        return 1.0
    avg_vol = np.mean(volumes[-period:])
    if avg_vol == 0:
        return 1.0
    return volumes[-1] / avg_vol


# ==================== 下跌条件分析 ====================
def analyze_downward(symbol: str) -> Tuple[bool, str]:
    """
    分析代币是否满足"下跌条件"
    返回: (是否满足, 分析理由)
    """
    reasons = []
    score = 0

    # 获取5m K线 (用于短期信号)
    try:
        candles_5m = api_request('GET', '/api/v2/mix/market/candles', {
            'symbol': symbol,
            'productType': 'usdt-futures',
            'granularity': '5m',
            'limit': '100'
        })
    except Exception as e:
        return False, f"K线获取失败: {e}"

    if not candles_5m or len(candles_5m) < 30:
        return False, f"K线数据不足({len(candles_5m) if candles_5m else 0}根)"

    # 解析数据: [ts, open, high, low, close, vol, turnover]
    closes_5m = [float(c[4]) for c in candles_5m]
    highs_5m = [float(c[2]) for c in candles_5m]
    lows_5m = [float(c[3]) for c in candles_5m]
    vols_5m = [float(c[5]) for c in candles_5m]

    # 1h K线 (用于中期信号)
    try:
        candles_1h = api_request('GET', '/api/v2/mix/market/candles', {
            'symbol': symbol,
            'productType': 'usdt-futures',
            'granularity': '1h',
            'limit': '100'
        })
    except:
        candles_1h = []

    closes_1h = [float(c[4]) for c in candles_1h] if candles_1h else closes_5m
    highs_1h = [float(c[2]) for c in candles_1h] if candles_1h else highs_5m
    lows_1h = [float(c[3]) for c in candles_1h] if candles_1h else lows_5m
    vols_1h = [float(c[5]) for c in candles_1h] if candles_1h else vols_5m

    # ========== 指标1: RSI 超买 ==========
    rsi_5m = compute_rsi(closes_5m)
    rsi_1h = compute_rsi(closes_1h)
    if rsi_5m > 75:
        score += 2
        reasons.append(f"RSI5m={rsi_5m:.1f}>75(严重超买)")
    elif rsi_5m > 65:
        score += 1
        reasons.append(f"RSI5m={rsi_5m:.1f}>65(超买)")

    if rsi_1h > 70:
        score += 2
        reasons.append(f"RSI1h={rsi_1h:.1f}>70(中期超买)")

    # ========== 指标2: MACD 顶背离 / 空头信号 ==========
    macd_5m, signal_5m, hist_5m = compute_macd(closes_5m)
    macd_1h, signal_1h, hist_1h = compute_macd(closes_1h)
    if macd_5m is not None:
        if hist_5m < -0.5:  # MACDHistogram转负
            score += 2
            reasons.append(f"MACD5m柱线转负({hist_5m:.4f})")
        elif macd_5m < signal_5m:  # MACD死叉
            score += 1
            reasons.append("MACD5m死叉")

    # ========== 指标3: 布林带上轨压制 ==========
    bb_upper, bb_mid, bb_lower = compute_bollinger(closes_5m)
    bb_upper_1h, _, _ = compute_bollinger(closes_1h)
    if bb_upper is not None:
        price = closes_5m[-1]
        if price >= bb_upper * 0.995:  # 触及上轨
            score += 2
            reasons.append(f"触及布林上轨(${bb_upper:.4f})")
        elif price >= bb_upper * 0.98:
            score += 1
            reasons.append(f"逼近布林上轨(${bb_upper:.4f})")

    # ========== 指标4: 缩量上涨(量价背离) ==========
    vol_ratio_5m = compute_volume_ratio(vols_5m)
    vol_ratio_1h = compute_volume_ratio(vols_1h)
    price_up = closes_5m[-1] > closes_5m[-5] if len(closes_5m) >= 5 else False
    if price_up and vol_ratio_5m < 0.6:
        score += 2
        reasons.append(f"缩量上涨(vol_ratio={vol_ratio_5m:.2f})")
    elif price_up and vol_ratio_5m < 0.8:
        score += 1
        reasons.append(f"量能萎缩(vol_ratio={vol_ratio_5m:.2f})")

    # ========== 指标5: ADX减弱 + DI-上穿 ==========
    adx_1h, plus_di, minus_di = compute_adx(highs_1h, lows_1h, closes_1h)
    if adx_1h is not None:
        if adx_1h < 20:
            score += 1
            reasons.append(f"ADX1h={adx_1h:.1f}<20(趋势减弱)")
        if minus_di is not None and plus_di is not None:
            if minus_di > plus_di:
                score += 2
                reasons.append(f"DI-({minus_di:.1f})>DI+({plus_di:.1f})空头排列")

    # ========== 指标6: 1小时内大起大落(波动过大) ==========
    if len(closes_1h) >= 2:
        change_1h = abs(closes_1h[-1] - closes_1h[-2]) / closes_1h[-2] if closes_1h[-2] != 0 else 0
        if change_1h > 0.03:  # 1小时变动>3%
            score += 1
            reasons.append(f"1h波动剧烈({change_1h*100:.1f}%)")

    # 最终判断: score >= 4 认为满足下跌条件
    trigger = score >= 4
    reason_str = f"[{symbol}] 下跌评分:{score} | " + " | ".join(reasons)
    return trigger, reason_str


# ==================== 微信推送 ====================
def wechat_push(title: str, content: str):
    """通过OpenClaw消息服务推送微信通知"""
    try:
        import subprocess
        full_msg = f"{title}\n\n{content}"
        result = subprocess.run(
            ['openclaw', 'message', 'send',
             '--channel', 'openclaw-weixin',
             '--message', full_msg],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            logger.info(f"📤 微信推送成功: {title}")
        else:
            logger.warning(f"📤 微信推送响应: {result.stdout[:200]}")
    except Exception as e:
        logger.error(f"❌ 微信推送失败: {e}")


# ==================== 主函数 ====================
def main():
    if len(sys.argv) < 2:
        print("用法: python3 futures_scanner.py --scan | --monitor")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == '--scan':
        scan_hot_contracts()

    elif mode == '--monitor':
        logger.info("🚀 启动10秒级监测模式(数据库1号)")
        # 记录已推送的代币(避免重复推送)
        alerted = set()
        push_cooldown = {}  # symbol -> 上次推送时间

        while True:
            db = load_db()
            contracts = db.get('contracts', [])

            if not contracts:
                time.sleep(MONITOR_INTERVAL)
                continue

            logger.info(f"[监测] 数据库1号: {len(contracts)}个代币")

            for contract in contracts:
                symbol = contract['symbol']
                change = contract.get('change24h', 0)

                # 冷却机制: 同一代币至少间隔5分钟才能再次推送
                now = time.time()
                if symbol in push_cooldown and now - push_cooldown[symbol] < 300:
                    continue

                try:
                    trigger, reason = analyze_downward(symbol)
                    if trigger:
                        # 微信推送
                        msg = (
                            f"🚨 合约预警\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"代币: {symbol}\n"
                            f"日涨幅: +{change*100:.1f}%\n"
                            f"现价: ${contract.get('lastPr', '?')}\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"📉 下跌信号:\n{reason}\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
                        )
                        wechat_push(f"🚨 {symbol} 下跌预警(+{change*100:.0f}%)", msg)
                        push_cooldown[symbol] = now
                        logger.warning(f"🚨 触发预警: {symbol} | {reason}")
                    else:
                        logger.debug(f"✅ {symbol} 暂无下跌信号(score依据)")

                except Exception as e:
                    logger.error(f"❌ 分析{symbol}失败: {e}")

            time.sleep(MONITOR_INTERVAL)

    else:
        print("未知模式:", mode)
        sys.exit(1)


if __name__ == '__main__':
    main()
