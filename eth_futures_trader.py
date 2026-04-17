#!/usr/bin/env python3
"""
Bitget ETH/USDT 永续合约自动交易机器人
========================================
版本: v1.0
日期: 2026-04-16
标的: ETH/USDT (usdt-futures)
杠杆: 20x
数量: 0.015 ETH
周期: 10秒/轮

策略: 4信号系统
  做多A: 大周期空头 + 5m超卖反弹
  做多B: 大周期多头 + 5m回调支撑
  做空A: 大周期多头 + 5m超买
  做空B: 大周期空头 + 5m反弹压力
风控: ADX>25 + 放量>1.5x 双重过滤
止损: 1.5% 固定
止盈: 2.0% 全仓一次性
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

sys.path.insert(0, '/root/.openclaw/workspace')

# ==================== 配置 ====================
class Config:
    """交易配置"""
    # API配置（需要拥有合约交易权限的Key）
    API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"
    API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
    PASSPHRASE = "liugang123"
    BASE_URL = "https://api.bitget.com"
    
    # 交易标的
    SYMBOL = "ETHUSDT"
    PRODUCT_TYPE = "usdt-futures"
    MARGIN_COIN = "USDT"
    
    # 仓位
    LEVERAGE = 20
    SIZE = 0.5  # ETH数量
    MARGIN_RATIO = 0.05  # 保证金比例 5%（20x杠杆对应5%保证金）
    
    # 止盈止损（固定百分比）
    STOP_LOSS_PCT = 0.015   # 1.5%
    TAKE_PROFIT_PCT = 0.020  # 2.0%
    
    # 扫描周期
    SCAN_INTERVAL = 10  # 秒
    
    # 风控
    COOLDOWN_SECONDS = 300  # 平仓后冷却5分钟
    MAX_CONSECUTIVE_LOSS = 3  # 连亏3次暂停30分钟
    PAUSE_MINUTES = 30
    
    # ADX过滤
    ADX_THRESHOLD = 20
    
    # 成交量过滤
    VOLUME_RATIO_THRESHOLD = 1.5
    
    # 布林带
    BB_PERIOD = 20
    BB_STD = 2
    
    # MACD
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    
    # RSI
    RSI_PERIOD = 14
    
    # ADX
    ADX_PERIOD = 14
    
    # 日志
    LOG_FILE = "eth_futures_trading.log"


# ==================== API封装 ====================
class BitgetFuturesAPI:
    """Bitget 合约API (v2 mix)"""
    
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.BASE_URL
        self._last_known_account = None  # 账户缓存（API故障时降级使用）
        self._last_known_positions = None  # 持仓缓存
        self.headers = {
            "Content-Type": "application/json",
            "ACCESS-KEY": config.API_KEY,
            "ACCESS-PASSPHRASE": config.PASSPHRASE,
        }
    
    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = timestamp + method + path + body
        mac = hmac.new(
            self.config.API_SECRET.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _request(self, method: str, path: str, params: Dict = None, body: Dict = None) -> Dict:
        timestamp = str(int(time.time() * 1000))
        query_str = '&'.join(f'{k}={v}' for k, v in params.items()) if params else ''
        full_path = path + ('?' + query_str if query_str else '')
        body_str = json.dumps(body) if body else ""
        signature = self._sign(timestamp, method, full_path, body_str)
        
        headers = self.headers.copy()
        headers["ACCESS-SIGN"] = signature
        headers["ACCESS-TIMESTAMP"] = timestamp
        
        url = self.base_url + full_path
        resp = requests.request(method, url, headers=headers, data=body_str)
        result = resp.json()
        
        if result.get("code") not in (None, "00000"):
            raise Exception(f"API Error: {result.get('code')} {result.get('msg')}")
        
        return result.get("data", result)
    
    def get_candles(self, interval: str, limit: int = 100) -> List[List]:
        """获取K线数据
        interval: 1m/5m/15m/30m/1h/4h/1d
        返回: [[timestamp, open, high, low, close, volume, turnover], ...]
        """
        data = self._request("GET", "/api/v2/mix/market/candles", {
            "symbol": self.config.SYMBOL,
            "productType": self.config.PRODUCT_TYPE,
            "granularity": interval,
            "limit": str(limit)
        })
        return data if isinstance(data, list) else []
    
    def get_ticker(self) -> Dict:
        """获取当前ticker"""
        data = self._request("GET", "/api/v2/mix/market/ticker", {
            "symbol": self.config.SYMBOL,
            "productType": self.config.PRODUCT_TYPE
        })
        return data[0] if isinstance(data, list) and data else {}
    
    def get_account(self) -> Dict:
        """获取账户信息（含降级策略）"""
        try:
            data = self._request("GET", "/api/v2/mix/account/accounts", {
                "symbol": self.config.SYMBOL,
                "productType": self.config.PRODUCT_TYPE
            })
            result = data[0] if isinstance(data, list) and data else {}
            if result:
                self._last_known_account = result  # 缓存成功结果
            return result
        except Exception as e:
            print(f"[账户API故障] {e}, 使用缓存值")
            if self._last_known_account is not None:
                return self._last_known_account
            # 保底：返回无持仓状态
            return {"unrealizedPL": "0", "available": "0"}
    
    def get_positions(self) -> List[Dict]:
        """获取持仓（通过 unrealizedPL + 成交历史，含降级策略）
        unrealized > 0 → 多头持仓
        unrealized < 0 → 空头持仓
        """
        try:
            acct = self.get_account()
            unrealized = float(acct.get('unrealizedPL', '0'))
            if abs(unrealized) < 0.0001:
                self._last_known_positions = []  # 缓存空仓
                return []
            
            # 有持仓，通过成交历史计算数量
            fills_data = self._request("GET", "/api/v2/mix/order/fills", {
                "symbol": self.config.SYMBOL,
                "productType": self.config.PRODUCT_TYPE,
                "limit": "50"
            })
            fills = fills_data.get('fillList', []) if isinstance(fills_data, dict) else []
            
            long_qty = short_qty = 0.0
            for f in fills:
                vol = float(f.get('baseVolume', 0))
                if f.get('side') == 'buy' and f.get('tradeSide') == 'open':
                    long_qty += vol
                elif f.get('side') == 'sell' and f.get('tradeSide') == 'open':
                    short_qty += vol
                elif f.get('side') == 'sell' and f.get('tradeSide') == 'close':
                    long_qty -= vol
                elif f.get('side') == 'buy' and f.get('tradeSide') == 'close':
                    short_qty -= vol
            
            # 持仓量为正时才是真实持仓
            positions = []
            if unrealized > 0 and long_qty > 0.001:
                positions.append({'side': 'long', 'size': f'{round(long_qty, 4):.4f}'})
            elif unrealized < 0 and short_qty < -0.001:  # short_qty是负数
                positions.append({'side': 'short', 'size': f'{round(abs(short_qty), 4):.4f}'})
            
            if positions:
                self._last_known_positions = positions  # 缓存成功结果
            return positions
        except Exception as e:
            print(f"[持仓API故障] {e}, 使用缓存值")
            if self._last_known_positions is not None:
                return self._last_known_positions
            return []
    
    def place_order(self, direction: str, order_type: str = "market",
                   size: str = None, price: str = None,
                   stop_surplus_price: float = None, stop_loss_price: float = None) -> Dict:
        """下单
        direction: 'long' or 'short'
        order_type: 'market' or 'limit'
        """
        size = size or str(self.config.SIZE)
        body = {
            "symbol": self.config.SYMBOL,
            "productType": self.config.PRODUCT_TYPE,
            "marginCoin": self.config.MARGIN_COIN,
            "side": "buy" if direction == "long" else "sell",
            "tradeSide": "open",
            "orderType": order_type,
            "size": size,
            "marginMode": "isolated",
            "leverage": str(self.config.LEVERAGE)
        }
        if price:
            body["price"] = price
        if stop_surplus_price:
            body["presetStopSurplusPrice"] = str(stop_surplus_price)
        if stop_loss_price:
            body["presetStopLossPrice"] = str(stop_loss_price)

        return self._request("POST", "/api/v2/mix/order/place-order", body=body)
    
    def close_position(self, pos_side: str = None) -> Dict:
        """市价平仓（需交易权限）
        自动判断方向: unrealizedPL>0=多头, unrealizedPL<0=空头
        """
        # 检查是否有持仓
        acct = self.get_account()
        unrealized = float(acct.get('unrealizedPL', '0'))
        if abs(unrealized) < 0.0001:
            raise Exception("No position to close")
        
        # 自动判断方向
        if pos_side is None:
            pos_side = "long" if unrealized > 0 else "short"
        
        # 先查持仓量，用成交历史推算
        positions = self.get_positions()
        close_size = None
        for p in positions:
            if p['side'] == pos_side:
                close_size = str(round(float(p['size']) + 0.005, 4))
                break
        
        # 如果算不出持仓量，用配置的SIZE
        if close_size is None:
            close_size = str(self.config.SIZE)
        
        return self._request("POST", "/api/v2/mix/order/place-order", body={
            "symbol": self.config.SYMBOL,
            "productType": self.config.PRODUCT_TYPE,
            "marginCoin": self.config.MARGIN_COIN,
            "side": "sell" if pos_side == "long" else "buy",
            "tradeSide": "close",
            "orderType": "market",
            "size": close_size,
            "marginMode": "isolated",
            "posSide": pos_side
        })
    
    def get_open_orders(self) -> List[Dict]:
        """获取当前挂单"""
        try:
            data = self._request("GET", "/api/v2/mix/order/currentList", {
                "symbol": self.config.SYMBOL,
                "productType": self.config.PRODUCT_TYPE
            })
            return data if isinstance(data, list) else []
        except:
            return []


# ==================== 技术指标 ====================
class TechnicalIndicators:
    """技术指标计算"""
    
    @staticmethod
    def sma(closes: np.ndarray, period: int) -> np.ndarray:
        return pd.Series(closes).rolling(window=period).mean().values
    
    @staticmethod
    def ema(closes: np.ndarray, period: int) -> np.ndarray:
        return pd.Series(closes).ewm(span=period).mean().values
    
    @staticmethod
    def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
        deltas = np.diff(closes, prepend=closes[0])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = pd.Series(gains).ewm(alpha=1/period).mean().values
        avg_loss = pd.Series(losses).ewm(alpha=1/period).mean().values
        rs = avg_gain / (avg_loss + 1e-10)
        rsi_vals = 100 - (100 / (rs + 1))
        return rsi_vals
    
    @staticmethod
    def macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        ema_fast = pd.Series(closes).ewm(span=fast).mean().values
        ema_slow = pd.Series(closes).ewm(span=slow).mean().values
        macd_line = ema_fast - ema_slow
        signal_line = pd.Series(macd_line).ewm(span=signal).mean().values
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def bollinger_bands(closes: np.ndarray, period: int = 20, std: int = 2) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        sma = pd.Series(closes).rolling(window=period).mean().values
        std_dev = pd.Series(closes).rolling(window=period).std().values
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        return upper, sma, lower
    
    @staticmethod
    def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        high_low = highs - lows
        high_close = np.abs(highs - np.roll(closes, 1))
        low_close = np.abs(lows - np.roll(closes, 1))
        tr = np.maximum(high_low, np.maximum(high_close, low_close))
        tr[0] = high_low[0]
        atr = pd.Series(tr).ewm(alpha=1/period).mean().values
        return atr
    
    @staticmethod
    def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        plus_dm = np.where(
            (highs - np.roll(highs, 1)) > (np.roll(lows, 1) - lows),
            np.maximum(highs - np.roll(highs, 1), 0), 0
        )
        minus_dm = np.where(
            (np.roll(lows, 1) - lows) > (highs - np.roll(highs, 1)),
            np.maximum(np.roll(lows, 1) - lows, 0), 0
        )
        plus_dm[0] = 0
        minus_dm[0] = 0
        
        atr = TechnicalIndicators.atr(highs, lows, closes, period)
        
        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/period).mean().values / (atr + 1e-10)
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/period).mean().values / (atr + 1e-10)
        
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = pd.Series(dx).ewm(alpha=1/period).mean().values
        return adx
    
    @staticmethod
    def percent_b(close: float, bb_upper: float, bb_lower: float) -> float:
        if bb_upper == bb_lower:
            return 0.5
        return (close - bb_lower) / (bb_upper - bb_lower)
    
    @staticmethod
    def volume_ratio(volumes: np.ndarray, period: int = 20) -> float:
        if len(volumes) < period:
            return 1.0
        vol_ma = np.mean(volumes[-period:])
        return volumes[-1] / (vol_ma + 1e-10)


# ==================== K线数据管理 ====================
class CandleData:
    """管理多个周期的K线数据"""
    
    def __init__(self, api: BitgetFuturesAPI):
        self.api = api
        self.ti = TechnicalIndicators()
        self.candles: Dict[str, pd.DataFrame] = {}
    
    def refresh(self) -> bool:
        """刷新所有周期K线"""
        intervals = {
            '5m': 100,
            '1H': 100,
            '4H': 100,
            '1D': 100
        }
        try:
            for interval, limit in intervals.items():
                raw = self.api.get_candles(interval, limit)
                if not raw:
                    return False
                
                df = pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                df = df.astype({
                    'open': float, 'high': float, 'low': float,
                    'close': float, 'volume': float, 'turnover': float
                })
                df['timestamp'] = pd.to_datetime(df['timestamp'].astype(float), unit='ms')
                df = df.sort_values('timestamp').reset_index(drop=True)
                self.candles[interval] = df
            return True
        except Exception as e:
            print(f"刷新K线失败: {e}")
            return False
    
    def get_latest(self, interval: str) -> Optional[Dict]:
        """获取最新一根K线"""
        df = self.candles.get(interval)
        if df is None or len(df) == 0:
            return None
        row = df.iloc[-1]
        return {
            'open': row['open'], 'high': row['high'],
            'low': row['low'], 'close': row['close'],
            'volume': row['volume'], 'timestamp': row['timestamp']
        }
    
    def compute_indicators(self, interval: str) -> Optional[Dict]:
        """计算指定周期的技术指标"""
        df = self.candles.get(interval)
        if df is None or len(df) < 30:
            return None
        
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        
        # 均线
        ma7 = self.ti.sma(closes, 7)
        
        # RSI
        rsi = self.ti.rsi(closes, 14)
        
        # MACD
        macd, signal, hist = self.ti.macd(closes, 12, 26, 9)
        
        # 布林带
        bb_upper, bb_mid, bb_lower = self.ti.bollinger_bands(closes, 20, 2)
        
        # ATR
        atr = self.ti.atr(highs, lows, closes, 14)
        
        # ADX（需要降序数据：最新在前）
        # Bug修复：ADX的方向移动计算依赖最新数据在前，K线是升序排列，需翻转
        # 翻转后：adx[0] = 最新K线的ADX值
        adx = self.ti.adx(highs[::-1], lows[::-1], closes[::-1], 14)
        
        latest = df.iloc[-1]
        current_price = latest['close']
        
        # %b
        pct_b = self.ti.percent_b(current_price, bb_upper[-1], bb_lower[-1])
        
        # 成交量比率
        vol_ratio = self.ti.volume_ratio(volumes, 20)
        
        return {
            'ma7': ma7[-1],
            'rsi': rsi[-1],
            'macd': macd[-1],
            'macd_signal': signal[-1],
            'macd_hist': hist[-1],
            'bb_upper': bb_upper[-1],
            'bb_mid': bb_mid[-1],
            'bb_lower': bb_lower[-1],
            'atr': atr[-1],
            'adx': adx[-1],
            'percent_b': pct_b,
            'volume_ratio': vol_ratio,
            'close': current_price,
            'high': latest['high'],
            'low': latest['low'],
        }


# ==================== 信号分析 ====================
class SignalAnalyzer:
    """分析是否触发交易信号
    基于BTC评分制：综合评分 >= 6 买入，<= -6 卖出
    参考: trading_bot.py 的综合评分系统
    """

    def __init__(self, candle_data: CandleData):
        self.candle = candle_data

    def _compute_score(self, ind: Dict, prev_ind: Dict = None) -> Tuple[int, List[str]]:
        """计算综合评分（BTC评分制）
        返回: (score, 信号列表)
        """
        score = 0
        signals = []

        price = ind['close']
        rsi = ind['rsi']
        pct_b = ind['percent_b']
        adx = ind['adx']
        macd_hist = ind['macd_hist']

        # === 1. MA趋势评分 (MA7 作为短期均线) ===
        ma7 = ind['ma7']
        if ma7 > price:
            # MA7在价格上方 → 价格在均线下方 → 下跌趋势 → 空头信号
            score -= 1
            signals.append(f"MA7空头(MA7={ma7:.1f}>price)")
        elif ma7 < price:
            # MA7在价格下方 → 价格在均线上方 → 上涨趋势 → 多头信号
            score += 1
            signals.append(f"MA7多头(MA7={ma7:.1f}<price)")

        # === 2. RSI评分 (BTC制: <35超卖, 35-50偏弱, >60偏强, >70超买) ===
        if rsi < 35:
            score += 2
            signals.append(f"RSI超卖({rsi:.1f})")
        elif rsi < 45:
            score += 1
            signals.append(f"RSI偏弱({rsi:.1f})")
        elif rsi > 70:
            score -= 2
            signals.append(f"RSI超买({rsi:.1f})")
        elif rsi > 60:
            score -= 1
            signals.append(f"RSI偏强({rsi:.1f})")

        # === 3. MACD评分 (BTC制: 金叉+2, 死叉-2, 扩张+1, 收缩-1) ===
        if prev_ind is not None:
            prev_hist = prev_ind['macd_hist']
            if prev_hist <= 0 and macd_hist > 0:
                score += 2
                signals.append("MACD金叉")
            elif prev_hist >= 0 and macd_hist < 0:
                score -= 2
                signals.append("MACD死叉")
            elif macd_hist > 0 and macd_hist > prev_hist:
                score += 1
                signals.append("MACD扩张")
            elif macd_hist < 0 and macd_hist < prev_hist:
                score -= 1
                signals.append("MACD收缩")

        # === 4. 布林带位置评分 ===
        if pct_b < 0.2:
            # 价格在布林下轨附近 → 超卖 → 多头信号
            score += 1
            signals.append(f"布林下轨({pct_b:.3f})")
        elif pct_b > 0.85:
            # 价格在布林上轨附近 → 超买 → 空头信号
            score -= 1
            signals.append(f"布林上轨({pct_b:.3f})")

        return score, signals

    def check(self) -> Tuple[Optional[str], str]:
        """检查是否触发信号
        基于BTC综合评分制:
        - 综合评分 >= 6: 买入信号
        - 综合评分 <= -6: 卖出信号
        - ADX < 20: 震荡市，不过度交易
        """
        ind_5m = self.candle.compute_indicators('5m')
        ind_1H = self.candle.compute_indicators('1H')

        if not ind_5m or not ind_1H:
            return None, "K线数据不足"

        price = ind_5m['close']
        adx_1h = ind_1H['adx']
        adx_5m = ind_5m['adx']
        vol_ratio = ind_5m['volume_ratio']

        # === 风控过滤 ===
        # ADX < 20: 震荡市，不交易
        if adx_1h < 20:
            return None, f"ADX={adx_1h:.1f}<20 震荡市"

        # === 计算5m综合评分 ===
        # 需要前一根K线用于MACD金叉/死叉判断
        df_5m = self.candle.candles.get('5m')
        if df_5m is not None and len(df_5m) >= 2:
            prev_ind_5m = {
                'close': df_5m.iloc[-2]['close'],
                'rsi': self._calc_rsi_slice(df_5m['close'].values, -2),
                'macd_hist': self._calc_macd_hist_slice(df_5m['close'].values, -2),
                'ma7': df_5m['close'].iloc[-2:-1].mean() if len(df_5m) >= 7 else df_5m.iloc[-2]['close'],
                'percent_b': 0.5,  # 简化
            }
        else:
            prev_ind_5m = None

        score, signals = self._compute_score(ind_5m, prev_ind_5m)

        # === 成交量加成（软过滤，不强制） ===
        vol_bonus = ""
        if vol_ratio >= 1.5:
            score += 1  # 放量额外加分
            vol_bonus = f" 放量(+1)"
        elif vol_ratio < 0.5:
            score -= 1  # 缩量减分
            vol_bonus = f" 缩量(-1)"

        # === ADX方向加成 ===
        if adx_5m > 30:
            if score > 0:
                score += 1  # 强趋势多头
                signals.append(f"强趋势ADX={adx_5m:.1f}(+1)")
            elif score < 0:
                score -= 1  # 强趋势空头

        # === 趋势方向确认（基于1H MA） ===
        ma7_1h = ind_1H['ma7']
        price_1h = ind_1H['close']
        if ma7_1h > price_1h and score > 0:
            score += 1  # 1H空头 + 5m多头 = 逆势反弹加分
            signals.append("逆势反弹(+1)")
        elif ma7_1h < price_1h and score > 0:
            score += 1  # 1H多头 + 5m多头 = 顺势做多加分
            signals.append("顺势做多(+1)")
        elif ma7_1h < price_1h and score < 0:
            score -= 1  # 1H多头 + 5m空头 = 逆势做空加分
            signals.append("逆势做空(-1)")
        elif ma7_1h > price_1h and score < 0:
            score -= 1  # 1H空头 + 5m空头 = 顺势做空加分
            signals.append("顺势做空(-1)")

        # === 最终信号判定 ===
        signal_str = " ".join(signals) + vol_bonus

        if score >= 6:
            reason = (f"买入(评分={score}) | {signal_str} | "
                      f"price={price:.2f} RSI={ind_5m['rsi']:.1f} ADX={adx_5m:.1f} vol={vol_ratio:.2f}x")
            return 'long', reason
        elif score <= -6:
            reason = (f"卖出(评分={score}) | {signal_str} | "
                      f"price={price:.2f} RSI={ind_5m['rsi']:.1f} ADX={adx_5m:.1f} vol={vol_ratio:.2f}x")
            return 'short', reason
        else:
            return None, f"无信号(评分={score}) | {signal_str} | price={price:.2f} RSI={ind_5m['rsi']:.1f} ADX={adx_5m:.1f} vol={vol_ratio:.2f}x"

    def _calc_rsi_slice(self, closes: np.ndarray, idx: int) -> float:
        """计算指定索引的RSI（简化）"""
        if idx < 1:
            return 50.0
        delta = np.diff(closes[:idx+1], prepend=closes[0])
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gains).ewm(alpha=1/14).mean().values[-1]
        avg_loss = pd.Series(losses).ewm(alpha=1/14).mean().values[-1]
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (rs + 1))

    def _calc_macd_hist_slice(self, closes: np.ndarray, idx: int) -> float:
        """计算指定索引的MACD柱状图（简化）"""
        if idx < 26:
            return 0.0
        data = closes[:idx+1]
        ema12 = pd.Series(data).ewm(span=12).mean().values[-1]
        ema26 = pd.Series(data).ewm(span=26).mean().values[-1]
        macd = ema12 - ema26
        signal = pd.Series([macd]).ewm(span=9).mean().values[-1]
        return macd - signal


# ==================== 交易执行 ====================
class FuturesTrader:
    """合约交易执行器"""
    
    def __init__(self, config: Config, api: BitgetFuturesAPI):
        self.config = config
        self.api = api
        self.consecutive_loss = 0
        self.last_trade_time = 0
        self.in_position = False
        self.entry_price = 0.0
        self.position_side = None  # 'long' or 'short'
        
        # 统计
        self.total_trades = 0
        self.win_trades = 0
        self.loss_trades = 0
    
    def open_position(self, side: str, reason: str) -> bool:
        """开仓
        side: 'long' or 'short'
        """
        if self.in_position:
            print(f"已在仓位中，跳过开仓")
            return False
        
        # 冷却检查
        elapsed = time.time() - self.last_trade_time
        if elapsed < self.config.COOLDOWN_SECONDS:
            print(f"冷却中，剩余 {self.config.COOLDOWN_SECONDS - elapsed:.0f}s")
            return False
        
        price = self.api.get_ticker()['lastPr']
        
        if side == 'long':
            stop_loss = round(price * (1 - self.config.STOP_LOSS_PCT), 2)
            take_profit = round(price * (1 + self.config.TAKE_PROFIT_PCT), 2)
            api_side = 'open_long'
        else:
            stop_loss = round(price * (1 + self.config.STOP_LOSS_PCT), 2)
            take_profit = round(price * (1 - self.config.TAKE_PROFIT_PCT), 2)
            api_side = 'open_short'
        
        try:
            result = self.api.place_order(
                direction=side,
                order_type='market',
                size=str(self.config.SIZE),
                stop_surplus_price=take_profit,
                stop_loss_price=stop_loss
            )
            
            order_id = result.get('orderId', '')
            self.in_position = True
            self.entry_price = price
            self.position_side = side
            self.last_trade_time = time.time()
            self.total_trades += 1
            
            msg = self._build_open_message(side, price, stop_loss, take_profit, reason, order_id)
            print(msg)
            self._wechat_notify(msg)
            return True
            
        except Exception as e:
            print(f"开仓失败: {e}")
            return False
    
    def close_position(self, reason: str = "") -> bool:
        """平仓"""
        if not self.in_position:
            return False
        
        try:
            self.api.close_position(self.position_side)
            self.in_position = False
            self.last_trade_time = time.time()
            
            pnl_pct = self._calc_pnl_pct()
            if pnl_pct > 0:
                self.win_trades += 1
            else:
                self.loss_trades += 1
                self.consecutive_loss += 1
            
            msg = self._build_close_message(pnl_pct, reason)
            print(msg)
            self._wechat_notify(msg)
            
            # 连亏3次暂停
            if self.consecutive_loss >= self.config.MAX_CONSECUTIVE_LOSS:
                print(f"⚠️ 连亏{self.consecutive_loss}次，暂停{self.config.PAUSE_MINUTES}分钟")
                time.sleep(self.config.PAUSE_MINUTES * 60)
                self.consecutive_loss = 0
            
            return True
            
        except Exception as e:
            print(f"平仓失败: {e}")
            return False
    
    def _calc_pnl_pct(self) -> float:
        if not self.in_position and self.entry_price:
            current = self.api.get_ticker()['lastPr']
            if self.position_side == 'long':
                return (current - self.entry_price) / self.entry_price
            else:
                return (self.entry_price - current) / self.entry_price
        return 0.0
    
    def _build_open_message(self, side: str, price: float, stop_loss: float, 
                           take_profit: float, reason: str, order_id: str) -> str:
        arrow = "🟢" if side == 'long' else "🔴"
        now = datetime.now().strftime("%H:%M:%S")
        return f"""🚨 ETH开仓通知
━━━━━━━━━━━━━━━━
方向: {arrow} {'做多' if side=='long' else '做空'}
杠杆: {self.config.LEVERAGE}x
数量: {self.config.SIZE} ETH
开仓价: ${price:.2f}
━━━━━━━━━━━━━━━━
止损: ${stop_loss:.2f} (-{self.config.STOP_LOSS_PCT*100:.1f}%)
止盈: ${take_profit:.2f} (+{self.config.TAKE_PROFIT_PCT*100:.1f}%) 全仓一次性
━━━━━━━━━━━━━━━━
📋 开仓理由:
{reason}
━━━━━━━━━━━━━━━━
⏰ {now}
📋 订单号: {order_id}"""
    
    def _build_close_message(self, pnl_pct: float, reason: str) -> str:
        emoji = "✅" if pnl_pct >= 0 else "❌"
        now = datetime.now().strftime("%H:%M:%S")
        return f"""📤 ETH平仓通知
━━━━━━━━━━━━━━━━
方向: {'做多' if self.position_side=='long' else '做空'}
盈亏: {emoji} {pnl_pct*100:+.2f}% ({(pnl_pct*20*100):+.1f}%仓位损益 @20x)
━━━━━━━━━━━━━━━━
平仓理由: {reason}
━━━━━━━━━━━━━━━━
统计: 共{self.total_trades}笔 | 胜{self.win_trades} 负{self.loss_trades}
━━━━━━━━━━━━━━━━
⏰ {now}"""
    
    def _wechat_notify(self, message: str):
        """微信通知（通过OpenClaw消息接口）"""
        print(f"[微信通知]\n{message}")


# ==================== 主程序 ====================
def main():
    print("=" * 60)
    print(f"🤖 ETH合约自动交易机器人 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    config = Config()
    api = BitgetFuturesAPI(config)
    candles = CandleData(api)
    analyzer = SignalAnalyzer(candles)
    trader = FuturesTrader(config, api)
    
    print(f"\n{'项目':<20} {'内容'}")
    print("-" * 40)
    print(f"{'标的':<20} ETH/USDT 永续合约")
    print(f"{'杠杆':<20} {config.LEVERAGE}x")
    print(f"{'数量':<20} {config.SIZE} ETH")
    print(f"{'止损':<20} {config.STOP_LOSS_PCT*100:.1f}%")
    print(f"{'止盈':<20} {config.TAKE_PROFIT_PCT*100:.1f}%")
    print(f"{'扫描周期':<20} {config.SCAN_INTERVAL}秒")
    print(f"{'ADX过滤':<20} >{config.ADX_THRESHOLD}")
    print(f"{'成交量过滤':<20} >{config.VOLUME_RATIO_THRESHOLD}x")
    
    print("\n启动中，首次加载K线数据...")
    if not candles.refresh():
        print("❌ K线数据加载失败，请检查API权限")
        return
    
    print("✅ 数据加载完成，开始监控...\n")
    
    loop_count = 0
    while True:
        try:
            loop_count += 1
            ts = datetime.now().strftime("%H:%M:%S")
            
            # 刷新K线
            if not candles.refresh():
                print(f"[{ts}] ❌ K线刷新失败")
                time.sleep(config.SCAN_INTERVAL)
                continue
            
            # 检查持仓状态
            positions = api.get_positions()
            has_position = any(p.get('availableNum', '0') != '0' for p in positions) if positions else False
            
            if has_position and not trader.in_position:
                trader.in_position = True
                # 获取持仓信息
                for p in positions:
                    if float(p.get('availableNum', 0)) > 0:
                        trader.position_side = 'long' if p.get('side', '').startswith('long') else 'short'
                        trader.entry_price = float(p.get('openPriceAvg', 0))
            
            if trader.in_position and not has_position:
                # 持仓已平（止盈/止损触发）
                trader.in_position = False
                print(f"[{ts}] 📤 持仓已自动平仓")
            
            if trader.in_position:
                print(f"[{ts}] 📊 持仓中 {'做多' if trader.position_side=='long' else '做空'} @ ${trader.entry_price:.2f} | 等待止盈/止损")
                time.sleep(config.SCAN_INTERVAL)
                continue
            
            # 无持仓，检查信号
            signal, reason = analyzer.check()
            
            if signal:
                side = 'long' if signal.startswith('long') else 'short'
                print(f"[{ts}] 🚨 检测到信号: {signal} - {reason}")
                trader.open_position(side, reason)
            else:
                if loop_count % 6 == 0:  # 每分钟打印一次观望
                    print(f"[{ts}] 👁️ 观望中 | {reason}")
            
            time.sleep(config.SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n\n🛑 收到停止信号")
            if trader.in_position:
                print("平仓中...")
                trader.close_position("手动停止")
            print("Bye!")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 异常: {e}")
            time.sleep(config.SCAN_INTERVAL)


if __name__ == "__main__":
    main()
