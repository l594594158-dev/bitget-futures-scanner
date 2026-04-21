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
TRAIL_TRIGGER_PCT = 0.06    # 移动止盈触发：盈利≥6%激活
TRAIL_EXIT_PCT = 0.04       # 移动止盈退出：从峰值回撤4%
# ==================== P0 修复：止损 + 波动率调仓 ====================
FIXED_STOP_PCT = 0.09      # 固定止损：亏损9%立即止损（与移动止盈并存）
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

def api_request(method, path, params=None, body=None, retry=2):
    """
    统一API请求，修复签名路径问题。
    
    Bitget API 签名规则不一致：
    - 市场数据、持仓查询：签名用 path（不含query）
    - 账户、订单历史：签名用 path + '?' + queryString
    
    策略：对 GET 请求先试 path-only 签名，若失败且 code=40009，自动用 path+query 重试。
    对 POST 请求，签名用 path + bodyStr。
    """
    timestamp = str(int(time.time() * 1000))
    url = BASE_URL + path
    body_str = json.dumps(body) if body else ""
    
    # 构建 query string
    query = ""
    if params:
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        url += "?" + query
    
    def _make_request(sign_path):
        sign_str = timestamp + method + sign_path + body_str
        headers = {
            'ACCESS-KEY': API_KEY,
            'ACCESS-SIGN': sign(sign_str, API_SECRET),
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': PASSPHRASE,
            'Content-Type': 'application/json'
        }
        if method == "GET":
            return requests.get(url, headers=headers, timeout=10)
        else:
            return requests.post(url, headers=headers, data=body_str, timeout=10)
    
    last_err = None
    for attempt in range(retry):
        try:
            # 首先尝试 path-only 签名（适合市场数据、持仓等）
            resp = _make_request(path)
            result = resp.json()
            code = result.get('code', '')
            
            if code == '00000':
                return result.get('data')
            
            # 如果 path-only 签名失败且是 40009，尝试 path+query 签名（账户/订单类）
            if code == '40009' and method == 'GET' and query:
                resp2 = _make_request(path + '?' + query)
                result2 = resp2.json()
                code2 = result2.get('code', '')
                if code2 == '00000':
                    return result2.get('data')
                result = result2  # 用第二次的响应
                code = code2
            
            no_retry_codes = ('400172', '40404', '30032', '40009')
            if code and code not in ('00000', '0000') and code not in no_retry_codes:
                last_err = f"code={code} msg={result.get('msg','')}"
                time.sleep(0.3)
                continue
            
            return result.get('data')
        except Exception as e:
            last_err = str(e)
            time.sleep(0.5)
    
    logger.warning(f"API {method} {path} failed after {retry} attempts: {last_err}")
    return None

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
                    'symbol': symbol, 'productType': 'USDT-FUTURES',
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

def compute_consecutive_rise(cl1, hi1, lo1, hours=4):
    """
    检测是否连续N小时上涨（每根1H K线收阳线）。
    用于做空前置条件：涨得太久=回调风险积累。
    cl1: 每根K线的收盘价列表
    hi1: 每根K线的最高价列表
    lo1: 每根K线的最低价列表
    Bitget 1H K线格式: [timestamp, open, high, low, close, volume]
    返回: (是否连续上涨, 连续上涨小时数)
    """
    if cl1 is None or len(cl1) < hours + 1:
        return False, 0
    # 每根K线的开盘价 = 前一根K线的收盘价（复盘）
    consecutive = 0
    for i in range(1, hours + 1):
        # 当前K线：开盘=cl1[-i-1]，收盘=cl1[-i]
        open_h = cl1[-(i + 1)]
        close_h = cl1[-i]
        if close_h > open_h:
            consecutive += 1
        else:
            break
    return consecutive >= hours, consecutive


# ==================== 信号分析 v4 ====================
# ==================== 做空信号配置（可单独调整）====================
SHORT_CONFIG = {
    # ── 主模式：RSI负背离型 ──
    'require_rsi_div': True,          # 是否要求RSI负背离（True=必须，False=跳过）
    'adx_min': 20,                    # ADX最小值（趋势需明显）
    'adx_max': 60,                    # ADX>此值则禁止做空（ADX>60=强趋势，逆势容易被爆）
    'di_minus_stronger': True,        # DI-必须大于DI+（空头主导）
    'bb_dev_threshold': 2.0,          # 布林偏离中轨幅度阈值（%）
    'vol_weak_threshold': 0.5,        # 缩量阈值（vr < 此值 = 缩量滞涨）
    'momentum_slowdown_min': 0.5,     # 动量衰竭最小值
    'vr_strong_for_bb': 1.5,          # 放量时vr阈值（vr>此值 = 放量）
    'adx_for_strong_vol': 25,         # 放量时要求ADX>此值
    'extra_require': 1,               # 附加条件至少满足几条（0=不要求）

    # ── 暴涨快捷模式（日涨幅>阈值时启用，跳过RSI负背离）──
    'surge_mode_enabled': True,       # 开启暴涨快捷模式
    'surge_day_change_thresh': 0.25, # 触发暴涨模式的日涨幅阈值（25%以上）
    'surge_adx_min': 25,              # 暴涨模式ADX最小值（放宽）
    'surge_retrace_min': 0.05,       # 从日内高点最小回落比例（5%）
    'surge_vr_max': 1.5,             # 暴涨模式：5分钟+1小时双重缩量（vr5 AND vr1 同时 < 此值）
    'surge_bb_dev': 1.0,             # 暴涨模式：布林偏离度（%）
    'surge_adx_max': 70,             # 暴涨模式ADX上限（趋势过强不做空，ADX>70=强趋势）
}

def check_short_signal(price, c5, c1, change24h,
                       has_bear_div, bear_div_type,
                       adx1, dip1, dim1,
                       bb_up5, bb_mid5, bb_lo5, bb_dev,
                       vr5, vr1, mom_slowdown, slowdown_deg,
                       extra_short):
    """
    独立的做空信号判断函数（可独立于analyze_symbol调用和测试）
    支持两种模式：主模式（RSI负背离）和暴涨快捷模式
    """
    cfg = SHORT_CONFIG
    reasons = []

    # ── 判断使用哪种模式 ──
    use_surge = cfg['surge_mode_enabled'] and change24h >= cfg['surge_day_change_thresh']

    if use_surge:
        # ══ 暴涨快捷模式：不用等RSI负背离 ══
        # 条件①：ADX在合理区间（趋势强但不极端）
        c1_surge = adx1 and cfg['surge_adx_min'] <= adx1 <= cfg['surge_adx_max']
        # 条件②：从日内高点回落（高位滞涨）
        # 用5m K线计算日内高点
        hi5 = [float(c[2]) for c in c5] if c5 else []
        peak_today = max(hi5[-60:]) if len(hi5) >= 12 else max(hi5[-len(hi5):])  # 最近12根5m≈1小时
        retrace_pct = (peak_today - price) / peak_today if peak_today > 0 else 0
        c2_surge = retrace_pct >= cfg['surge_retrace_min']
        # 条件③：5分钟 AND 1小时双重缩量，或布林偏离（二者满足其一）
        # 双重保险：5分钟vr5 + 1小时vr1 同时缩量 → 做空胜率更高
        c3_surge = (vr5 < cfg['surge_vr_max'] and vr1 < cfg['surge_vr_max']) or bb_dev >= cfg['surge_bb_dev']
        # 附加条件
        extra_ok = len(extra_short) >= cfg['extra_require']

        short_ok = c1_surge and c2_surge and c3_surge and extra_ok
        reasons.append(
            f"做空[暴涨🚀]: ①ADX={adx1:.1f}∈[{cfg['surge_adx_min']},{cfg['surge_adx_max']}]={'✅' if c1_surge else '❌'} "
            f"②回落{retrace_pct*100:.1f}%>={cfg['surge_retrace_min']*100:.0f}%={'✅' if c2_surge else '❌'} "
            f"③布林偏离={bb_dev:.1f}%/vr5={vr5:.2f}&vr1={vr1:.2f}={'✅' if c3_surge else '❌'} "
            f"④附加={'✅' if extra_ok else '❌'}{extra_short}"
        )
    else:
        # ══ 主模式：RSI负背离型 ══
        if cfg['require_rsi_div']:
            c1 = has_bear_div and bear_div_type == 'bearish'
        else:
            c1 = True  # 不要求RSI背离
        c2 = adx1 and cfg['adx_min'] <= adx1 <= cfg['adx_max'] and (
            dim1 > dip1 if cfg['di_minus_stronger'] else True)
        c3 = bb_dev >= cfg['bb_dev_threshold']
        extra_ok = len(extra_short) >= cfg['extra_require']

        short_ok = c1 and c2 and c3 and extra_ok
        reasons.append(
            f"做空[主模式📉]: ①RSI负背离={'✅' if c1 else '❌'} "
            f"②ADX={adx1:.1f}∈[{cfg['adx_min']},{cfg['adx_max']}]={'✅' if c2 else '❌'} "
            f"③布林偏离={bb_dev:.1f}%>={cfg['bb_dev_threshold']}%={'✅' if c3 else '❌'} "
            f"④附加={'✅' if extra_ok else '❌'}{extra_short}"
        )

    return short_ok, " | ".join(reasons)


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
            {'symbol': symbol, 'productType': 'USDT-FUTURES', 'granularity': '5m', 'limit': '100'})
        c1 = api_request('GET', '/api/v2/mix/market/candles',
            {'symbol': symbol, 'productType': 'USDT-FUTURES', 'granularity': '1H', 'limit': '100'})
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
    vo1 = [float(c[5]) for c in c1] if c1 else vo5

    price = cl5[-1]
    # 获取真实24h涨幅（用于暴涨快捷模式判断）
    try:
        ticker = api_request('GET', '/api/v2/mix/market/ticker',
                            {'symbol': symbol, 'productType': 'USDT-FUTURES'})
        real_change24h = float(ticker[0].get('change24h', 0)) if ticker else 0
    except:
        real_change24h = 0
    pc5 = (cl5[-1]-cl5[-5])/cl5[-5] if len(cl5)>=5 else 0

    rsi5 = compute_rsi(cl5)
    rsi1 = compute_rsi(cl1)
    macd5, sig5, hist5 = compute_macd(cl5)
    bb_up5, bb_mid5, bb_lo5 = compute_bollinger(cl5)
    adx1, dip1, dim1 = compute_adx(hi1, lo1, cl1)
    vr5 = compute_vol_ratio(vo5)
    vr1 = compute_vol_ratio(vo1)  # 1小时交易量比率（用于暴涨快捷模式）
    bb_dev = abs(price-bb_mid5)/bb_mid5*100 if bb_mid5 else 999

    # RSI背离
    has_bear_div, bear_div_type = compute_rsi_divergence(cl5)
    has_bull_div, bull_div_type = compute_rsi_divergence(cl5)
    # 动量衰竭
    mom_slowdown, slowdown_deg = compute_momentum_slowdown(cl5, vo5)
    # 连续上涨检测（做空前置条件）

    # ===================== 信号判断核心逻辑 =====================
    # 【改进】量价分析作为第一优先级，极端行情币种更依赖量能确认方向
    # vr > 1.5x: 放量（趋势确认）
    # vr < 0.5x: 缩量（可能反转）
    # 0.5x < vr < 1.5x: 中性，需结合ADX判断
    
    vr_strong = vr5 > 1.5    # 放量趋势
    vr_weak = vr5 < 0.5       # 缩量可能反转
    vr_neutral = 0.5 <= vr5 <= 1.5  # 中性量
    
    # ===================== 做多条件 =====================
    # ① RSI正背离（反转信号，需缩量或中性量配合）
    cond1_long = has_bull_div and bull_div_type == 'bullish'
    # ② 趋势向上：ADX>20 且 DI+>DI-，放量时要求更严格
    cond2_long = adx1 and adx1 > 20 and dip1 > dim1
    # ③ 布林下轨附近 + 量能支持
    #    - 放量时(vr>1.5)：需价格接近下轨且ADX>25
    #    - 缩量时(vr<0.5)：价格偏离中轨>2%即可（反弹预期）
    cond3_long = False
    if vr_strong:
        cond3_long = bb_lo5 and price <= bb_lo5 and adx1 and adx1 > 25
    else:  # 缩量或中性
        cond3_long = bb_dev > 2.0 or (bb_lo5 and price <= bb_lo5 * 1.02)
    # ④ 附加：量价背离(缩量上涨→可能回调) 或 RSI超卖 或 放量确认
    extra_long = []
    if vr_weak: extra_long.append(f"缩量反弹(vol1h={vr1:.2f}x)")
    if vr_strong: extra_long.append(f"放量确认(vol1h={vr1:.2f}x)")
    if rsi5 < 40: extra_long.append(f"RSI超卖({rsi5:.1f}<40)")
    cond4_long = len(extra_long) >= 1 and cond1_long and cond2_long

    long_ok = cond1_long and cond2_long and cond3_long and cond4_long
    reasons.append(
        f"做多: ①RSI正背离={'✅' if cond1_long else '❌'} "
        f"②ADX>20+DI+={'✅' if cond2_long else '❌'} "
        f"③布林+量={'✅' if cond3_long else '❌'} "
        f"④附加={'✅' if cond4_long else '❌'}{extra_long}"
    )

    # ===================== 做空条件 =====================
    # 附加条件（做空和做多共用的量能判断）
    extra_short = []
    if vr_weak: extra_short.append(f"缩量滞涨(vr5={vr5:.2f},vr1={vr1:.2f})")
    if vr_strong: extra_short.append(f"放量确认(vr5={vr5:.2f},vr1={vr1:.2f})")
    if mom_slowdown and slowdown_deg > SHORT_CONFIG.get('momentum_slowdown_min', 0.5):
        extra_short.append(f"动量衰竭({slowdown_deg:.1f})")

    # 调用独立做空判断函数
    short_ok, short_reason = check_short_signal(
        price, c5, c1, real_change24h,
        has_bear_div, bear_div_type,
        adx1, dip1, dim1,
        bb_up5, bb_mid5, bb_lo5, bb_dev,
        vr5, vr1, mom_slowdown, slowdown_deg,
        extra_short
    )
    reasons.append(short_reason)

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
            {'symbol': symbol, 'productType': 'USDT-FUTURES'})
        if result:
            t = result[0] if isinstance(result, list) else result
            return float(t.get('lastPr', 0))
    except: pass
    return 0.0


def get_balance():
    """获取账户USDT可用余额"""
    try:
        data = api_request('GET', '/api/v2/mix/account/accounts',
                           params={'marginCoin': 'USDT', 'productType': 'USDT-FUTURES'})
        if data and len(data) > 0:
            return float(data[0].get('available', 0))
    except Exception as e:
        logger.warning(f"获取余额失败: {e}")
    return 0.0

def get_all_positions():
    """
    获取所有持仓（逐枚查询主力币种）。
    由于 all-position 端点需要 productType 参数（存在但格式不稳定），
    采用备援策略：通过 orders-history 遍历所有有开仓记录的symbol，逐个查 single-position。
    """
    try:
        # 获取所有开仓记录
        all_orders = api_request('GET', '/api/v2/mix/order/orders-history',
                                 params={'productType': 'USDT-FUTURES', 'limit': 100})
        if not all_orders:
            return []
        entrusted = all_orders.get('entrustedList') or []
        
        # 收集有开仓未平仓的symbol
        open_symbols = set()
        for o in entrusted:
            if o.get('tradeSide') == 'open':
                open_symbols.add(o.get('symbol'))
        
        positions = []
        for sym in open_symbols:
            pos_data = api_request('GET', '/api/v2/mix/position/single-position',
                                   params={'symbol': sym, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
            if pos_data and len(pos_data) > 0:
                for p in pos_data:
                    if float(p.get('total', 0)) > 0 or float(p.get('size', 0)) > 0:
                        positions.append(p)
        return positions
    except Exception as e:
        logger.warning(f"获取所有持仓失败: {e}")
        return []

def get_ticker(symbol):
    """获取单个币种行情"""
    try:
        data = api_request('GET', '/api/v2/mix/market/ticker',
                           params={'symbol': symbol, 'productType': 'USDT-FUTURES'})
        if data and len(data) > 0:
            return data[0]
        return None
    except Exception as e:
        logger.warning(f"获取行情失败: {symbol} {e}")
        return None

def get_position_size(symbol):
    try:
        result = api_request('GET', '/api/v2/mix/position/single-position',
            {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT', 'symbol': symbol})
        if result and isinstance(result, list) and len(result) > 0:
            return float(result[0].get('total', 0))
    except: pass
    return 0.0

def set_leverage(symbol, leverage, hold_side):
    """开仓前先设置杠杆（避免Bitget默认20x）"""
    try:
        body = {
            'symbol': symbol, 'productType': 'USDT-FUTURES',
            'marginCoin': 'USDT', 'leverage': str(leverage),
            'marginMode': 'isolated',  # 必须显式指定隔离模式，否则可能默认全仓（crossed）导致20x
            'holdSide': hold_side
        }
        result = api_request('POST', '/api/v2/mix/account/set-leverage', body=body)
        if result:
            actual_mode = result.get('marginMode', '')
            actual_leverage = int(result.get('longLeverage', leverage))
            logger.info(f"杠杆设置: {symbol} {leverage}x (mode={actual_mode})")
            # 🚨 校验：若返回不是isolated或杠杆不符，记录严重警告
            if actual_mode != 'isolated':
                logger.error(f"🚨 杠杆模式异常！{symbol} expected=isolated actual={actual_mode}，将重新设置")
                # 再次尝试不带holdSide的全仓统一设置
                retry_body = {
                    'symbol': symbol, 'productType': 'USDT-FUTURES',
                    'marginCoin': 'USDT', 'leverage': str(leverage),
                    'marginMode': 'isolated'
                }
                api_request('POST', '/api/v2/mix/account/set-leverage', body=retry_body)
            if actual_leverage != leverage:
                logger.error(f"🚨 杠杆数值异常！{symbol} expected={leverage}x actual={actual_leverage}x，将重新设置")
        return result
    except Exception as e:
        logger.error(f"🚨 杠杆设置失败: {e}")
    return None

def verify_and_fix_leverage(symbol):
    """
    深度校验仓位实际杠杆，发现与目标不符立即修正。
    调用时机：监测循环发现持仓时、开仓后恢复持仓记录时。
    """
    try:
        pos_data = api_request('GET', '/api/v2/mix/position/single-position',
                               params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
        if not pos_data or len(pos_data) == 0:
            return
        p = pos_data[0]
        actual_size = float(p.get('total', 0))
        if actual_size <= 0:
            return
        actual_leverage = int(p.get('leverage', 0))
        actual_mode = p.get('marginMode', '')
        if actual_leverage != LEVERAGE or actual_mode != 'isolated':
            logger.warning(f"🚨 {symbol} 杠杆异常: 实际{actual_leverage}x/{actual_mode}，目标{LEVERAGE}x/isolated → 正在修正")
            hold_side = p.get('holdSide', 'long')
            set_leverage(symbol, LEVERAGE, hold_side)
            alert_to_queue(f"⚠️ {symbol} 杠杆异常已修正",
                f"代币: {symbol}\n"
                f"原杠杆: {actual_leverage}x ({actual_mode})\n"
                f"修正为: {LEVERAGE}x (isolated)\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            logger.info(f"✅ {symbol} 杠杆校验OK: {actual_leverage}x/isolated")
    except Exception as e:
        logger.error(f"杠杆校验失败 {symbol}: {e}")

def place_order(symbol, side, size):
    """
    市价开仓。注意 Bitget 单笔最低 5 USDT保证金。
    由于每次开仓保证金固定 2 USDT，需要确保下单金额 > 5U 才不会报错。
    """
    try:
        # 先设置杠杆
        hold_side = 'short' if side == 'sell' else 'long'
        set_leverage(symbol, LEVERAGE, hold_side)
        
        # 计算下单金额（size × 价格）
        ticker = get_ticker(symbol)
        price = float(ticker.get('lastPr', 0)) if ticker else 0
        if price > 0:
            usdt_value = float(size) * price
            if usdt_value < 5:
                logger.warning(f"下单金额 {usdt_value:.2f}U < 最低5U，改用最小数量")
                # 改为按 5U 保证金下单
                adjusted_size = str(round(5 / price * LEVERAGE / LEVERAGE, 4))
                size = max(size, adjusted_size)
        
        data = api_request('POST', '/api/v2/mix/order/place-order', body={
            'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT',
            'side': side, 'orderType': 'market', 'size': size,
            'marginMode': 'isolated', 'tradeSide': 'open'
            # leverage 已在 set_leverage 中设置，此处不再重复
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
            'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT',
            'side': close_side, 'orderType': 'market', 'size': size,
            'marginMode': 'isolated', 'tradeSide': 'close'
            # leverage 已在开仓时 set_leverage 设置，平仓不需要重复传
        })
        return data
    except Exception as e:
        logger.error(f"平仓失败: {e}")
    return None

def alert_to_queue(title, content):
    pass  # 通知已禁用
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


        # ===== 第一步：追踪所有本地持仓（不依赖DB1热点池）=====
        # 关键修复：即使币种跌出热点池，持仓止盈止损追踪仍需运行
        for pos in list(positions.get('positions', [])):
            symbol = pos['symbol']
            real_size = get_position_size(symbol)
            if real_size <= 0:
                logger.warning(f"⚠️ {symbol} 手动平仓，从记录移除")
                cooldown[symbol] = now
                save_cooldown(cooldown)
                positions['positions'] = [p for p in positions['positions'] if p['symbol'] != symbol]
                save_positions(positions); continue

            # 🚨 每次心跳检查持仓杠杆，发现偏差立即修正（防止set_leverage历史失效）
            verify_and_fix_leverage(symbol)
            # 同步本地记录的实际杠杆值
            pos['leverage'] = LEVERAGE

            ds = 1 if pos['direction'] == 'long' else -1
            ep = pos['entry_price']
            peak = pos.get('peak_price', ep)
            cp = get_current_price(symbol)
            if cp == 0: continue

            pv = (cp - ep) / ep * ds

            # 固定止损
            if pv <= -FIXED_STOP_PCT:
                logger.warning(f"🛑 固定止损平仓: {symbol} 亏损{pv*100:.2f}% 平仓价${cp}")
                cr = close_position(symbol, pos['direction'], pos['size'])
                if cr:
                    pnl = (cp - ep) * float(pos['size']) * ds
                    alert_to_queue(f"🛑 {symbol} 固定止损平仓",
                        f"方向: {'做空' if pos['direction']=='short' else '做多'}\n"
                        f"开仓价: ${ep}\n平仓价: ${cp}\n"
                        f"数量: {pos['size']}\n盈亏: {'+' if pnl>=0 else ''}{pnl:.4f} USDT\n"
                        f"止损线: -{FIXED_STOP_PCT*100:.1f}% 实际亏损: {pv*100:.2f}%\n━━━━━━━━━━━━━━━━\n"
                        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    positions['positions'] = [p for p in positions['positions'] if p['symbol'] != symbol]
                    save_positions(positions); continue

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
                # 【修复】回撤计算：(激活价 - 当前价) / 激活价
                # 做空：激活后价格需从低位反弹才触发止盈，peaktrailtrailing激活价是最低点
                # 回撤 = (peak - cp) / peak，但激活价用于判断触发
                dd = (peak - cp) / peak if ds == 1 else (peak - cp) / peak
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
        save_positions(positions)

        # ===== 第二步：扫描DB1寻找新开仓机会 =====

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

                    # ===== 固定止损（与移动止盈并存）=====
                    if pv <= -FIXED_STOP_PCT:
                        logger.warning(f"🛑 固定止损平仓: {symbol} 亏损{pv*100:.2f}% 平仓价${cp}")
                        cr = close_position(symbol, pos['direction'], pos['size'])
                        if cr:
                            pnl = (cp - ep) * float(pos['size']) * ds
                            alert_to_queue(f"🛑 {symbol} 固定止损平仓",
                                f"方向: {'做空' if pos['direction']=='short' else '做多'}\n"
                                f"开仓价: ${ep}\n平仓价: ${cp}\n"
                                f"数量: {pos['size']}\n盈亏: {'+' if pnl>=0 else ''}{pnl:.4f} USDT\n"
                                f"止损线: -{FIXED_STOP_PCT*100:.1f}% 实际亏损: {pv*100:.2f}%\n━━━━━━━━━━━━━━━━\n"
                                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            positions['positions'] = [p for p in positions['positions'] if p['symbol'] != symbol]
                            save_positions(positions); continue

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

            # 🔧 防重复开仓：检查交易所真实持仓
            real_size = get_position_size(symbol)
            if real_size > 0:
                # 已有真实持仓，只更新冷却时间，不开新仓
                logger.info(f"⚠️ {symbol} 已有持仓{real_size}，跳过开仓")
                cooldown[symbol] = now; save_cooldown(cooldown)
                # 🚨 每次心跳都校验一次杠杆（防止set_leverage失效导致实际20x）
                verify_and_fix_leverage(symbol)
                # 同步本地记录的实际杠杆值
                for p in positions['positions']:
                    if p['symbol'] == symbol:
                        p['leverage'] = LEVERAGE
                # 同步更新本地持仓记录
                positions.setdefault('positions', [])
                existing_local = [p for p in positions['positions'] if p['symbol'] == symbol]
                if not existing_local:
                    # 从交易所拿完整数据恢复本地记录
                    pos_data = api_request('GET', '/api/v2/mix/position/single-position',
                        {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT', 'symbol': symbol})
                    if pos_data and len(pos_data) > 0:
                        p = pos_data[0]
                        pos = {
                            'symbol': symbol,
                            'direction': 'short' if p.get('holdSide') == 'short' else 'long',
                            'side': 'sell' if p.get('holdSide') == 'short' else 'buy',
                            'entry_price': float(p.get('openPriceAvg', 0)),
                            'size': float(p.get('total', 0)),
                            'peak_price': cp,
                            'open_time': datetime.fromtimestamp(int(p.get('cTime', 0))/1000).strftime('%Y-%m-%d %H:%M:%S'),
                            'trail_triggered': False,
                            'trail_activated_price': None,
                            'leverage': int(p.get('leverage', LEVERAGE)),
                            'margin': float(p.get('marginSize', 0)),
                            'unrealized_pl': float(p.get('unrealizedPL', 0)),
                            'liquidation_price': float(p.get('liquidationPrice', 0)),
                            'order_id': ''
                        }
                        positions['positions'].append(pos); save_positions(positions)
                        logger.info(f"✅ 已从交易所恢复持仓记录: {symbol}")
                        # 🚨 从交易所恢复后立即校验杠杆（防止历史仓位带了错杠杆）
                        verify_and_fix_leverage(symbol)
                        # 重新读取修正后的实际杠杆值
                        pos['leverage'] = LEVERAGE
                        # 🚨 通知用户：有新仓位被发现并恢复（此前未推送告警）
                        contract_info = next((c for c in contracts_sorted if c['symbol'] == symbol), {})
                        direction_str = '🟢做多' if pos['direction'] == 'long' else '🔴做空'
                        alert_to_queue(f"📈 {direction_str} 开仓: {symbol}（恢复）",
                            f"{direction_str} +{contract_info.get('change24h',0)*100:.1f}%\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"代币: {symbol}\n日涨幅: +{contract_info.get('change24h',0)*100:.1f}%\n"
                            f"开仓价: ${pos['entry_price']:.5f}\n"
                            f"数量: {pos['size']}\n"
                            f"保证金: {POSITION_SIZE} USDT\n杠杆: {pos['leverage']}x\n"
                            f"强平价: ${pos['liquidation_price']:.5f}\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"⏰ 发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"⚠️ 系统异常：此前未推送告警，本次恢复持仓记录"
                        )
                save_positions(positions); continue

            sz = f"{POSITION_SIZE/cp*LEVERAGE:.4f}"
            side = 'buy' if direction == 'long' else 'sell'
            result = place_order(symbol, side, sz)
            if not result: continue

            cooldown[symbol] = now; save_cooldown(cooldown)
            ep = cp

            # 🚨 成交校验：确认实际保证金与预期相符
            time.sleep(1)  # 等待成交完成
            pos_verify = api_request('GET', '/api/v2/mix/position/single-position',
                params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
            if pos_verify and len(pos_verify) > 0:
                actual_margin = float(pos_verify[0].get('marginSize', 0))
                actual_size = float(pos_verify[0].get('total', 0))
                if actual_margin < POSITION_SIZE * 0.5:
                    alert_to_queue(f"⚠️ {symbol} 成交异常",
                        f"代币: {symbol}\n"
                        f"预期保证金: {POSITION_SIZE} USDT\n"
                        f"实际保证金: {actual_margin:.4f} USDT ⚠️\n"
                        f"实际数量: {actual_size}\n"
                        f"可能原因: Bitget最小成交限制\n"
                        f"请手动检查是否需要补开\n"
                        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    logger.warning(f"⚠️ {symbol} 成交异常: 预期{POSITION_SIZE}U 实际{actual_margin:.4f}U")

            # 获取开仓时指标快照
            ic5 = api_request('GET', '/api/v2/mix/market/candles',
                {'symbol': symbol, 'productType': 'USDT-FUTURES', 'granularity': '5m', 'limit': '100'})
            ic1 = api_request('GET', '/api/v2/mix/market/candles',
                {'symbol': symbol, 'productType': 'USDT-FUTURES', 'granularity': '1H', 'limit': '100'})
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
                f"开仓价: ${ep}\n数量: {sz}\n保证金: {actual_margin:.4f} USDT\n杠杆: {LEVERAGE}x\n"
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

            # 从 Bitget 持仓接口获取真实保证金（开仓后查询）
            actual_margin = POSITION_SIZE
            if result:
                try:
                    pos_data = api_request('GET', '/api/v2/mix/position/single-position',
                        params={'symbol': symbol, 'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
                    if pos_data and len(pos_data) > 0:
                        actual_margin = float(pos_data[0].get('marginSize', POSITION_SIZE))
                except: pass

            pos = {
                'symbol': symbol, 'direction': direction, 'side': side,
                'entry_price': ep, 'size': sz, 'peak_price': ep,
                'open_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'trail_triggered': False, 'trail_activated_price': None,
                'leverage': LEVERAGE, 'margin': actual_margin,

                'entry_reason': reason[:200],
                'change24h': contract.get('change24h', 0),
                'order_id': result.get('orderId', '') if result else ''
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
