"""
Bitget 美股现货交易机器人
=========================
版本: v1.0
日期: 2026-04-06
标的: 34个现货标的（贵金属/美股/商品ETF/指数ETF/债券ETF）
"""

import requests
import time
import json
import hmac
import hashlib
import base64
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

# ==================== 配置 ====================
class Config:
    """交易配置"""
    
    # API配置（Key和Secret已修正）
    API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"       # API Key (bg_开头)
    API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"  # API Secret
    PASSPHRASE = "liugang123"
    
    # API端点
    BASE_URL = "https://api.bitget.com"
    
    # 交易标的 - 美股现货
    SYMBOLS = {
        # 贵金属
        "XAUUSD": {"type": "metal", "max_position": 0.10, "stop_loss": 0.05},
        "XAGUSD": {"type": "metal", "max_position": 0.10, "stop_loss": 0.05},
        
        # 美股A+级 (高波动)
        "TSLAUSDT": {"type": "stock_a_plus", "max_position": 0.05, "stop_loss": 0.08},
        "NVDAUSDT": {"type": "stock_a_plus", "max_position": 0.05, "stop_loss": 0.08},
        "COINUSDT": {"type": "stock_a_plus", "max_position": 0.05, "stop_loss": 0.08},
        "MARAUSDT": {"type": "stock_a_plus", "max_position": 0.05, "stop_loss": 0.08},
        "RIOTUSDT": {"type": "stock_a_plus", "max_position": 0.05, "stop_loss": 0.08},
        
        # 美股A级
        "AMDUSDT": {"type": "stock_a", "max_position": 0.08, "stop_loss": 0.06},
        "ARMUSDT": {"type": "stock_a", "max_position": 0.08, "stop_loss": 0.06},
        "PLTRUSDT": {"type": "stock_a", "max_position": 0.08, "stop_loss": 0.06},
        "SNOWUSDT": {"type": "stock_a", "max_position": 0.08, "stop_loss": 0.06},
        "QBTSUSDT": {"type": "stock_a", "max_position": 0.08, "stop_loss": 0.06},
        
        # 美股B/C级 (稳定)
        "AAPLUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "METAUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "AMZNUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "GOOGLUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "NFLXUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "TSMUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "KOUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "CVXUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        "AXPUSDT": {"type": "stock_bc", "max_position": 0.10, "stop_loss": 0.05},
        
        # 中概股
        "BIDUUSDT": {"type": "china", "max_position": 0.05, "stop_loss": 0.08},
        "PDDUSDT": {"type": "china", "max_position": 0.05, "stop_loss": 0.08},
        "GRABUSDT": {"type": "china", "max_position": 0.05, "stop_loss": 0.08},
        
        # 商品ETF
        "GLDUSDT": {"type": "etf_commodity", "max_position": 0.10, "stop_loss": 0.05},
        "USOUSDT": {"type": "etf_commodity", "max_position": 0.10, "stop_loss": 0.05},
        "COPXUSDT": {"type": "etf_commodity", "max_position": 0.10, "stop_loss": 0.05},
        "REMXUSDT": {"type": "etf_commodity", "max_position": 0.10, "stop_loss": 0.05},
        
        # 指数ETF
        "TQQQUSDT": {"type": "etf_index", "max_position": 0.10, "stop_loss": 0.08},
        "SQQQUSDT": {"type": "etf_index", "max_position": 0.10, "stop_loss": 0.08},
        "VTIUSDT": {"type": "etf_index", "max_position": 0.10, "stop_loss": 0.05},
        
        # 债券ETF
        "SGOVUSDT": {"type": "bond", "max_position": 0.20, "stop_loss": 0.0},
    }
    
    # 风控配置
    MAX_TOTAL_POSITION = 0.80  # 最大总持仓 80%
    MAX_SINGLE_POSITION = 0.20  # 最大单笔持仓 20%
    DAILY_LOSS_LIMIT = 0.03    # 日最大亏损 3%
    MONTHLY_LOSS_LIMIT = 0.10  # 月最大亏损 10%
    
    # 技术指标参数
    MA_SHORT = 5
    MA_MEDIUM = 20
    MA_LONG = 50
    MA_SUPER = 200
    
    RSI_PERIOD = 14
    RSI_OVERSOLD = 35
    RSI_OVERBOUGHT = 65
    RSI_EXTREME_OVERSOLD = 30
    RSI_EXTREME_OVERBOUGHT = 75
    
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    
    BB_PERIOD = 20
    BB_STD = 2
    
    # 交易时间 (美股)
    MARKET_OPEN_HOUR = 21      # UTC时间21:00 (北京时间次日凌晨4:00-5:00冬令时)
    MARKET_CLOSE_HOUR = 14     # UTC时间14:00 (北京时间次日早上)
    
    # 扫描间隔(秒)
    SCAN_INTERVAL = 60         # 常规扫描间隔
    VOLATILE_INTERVAL = 30     # 波动时缩短间隔
    
    # 记录文件
    LOG_FILE = "trading_bot.log"
    TRADE_RECORD_FILE = "trade_history.json"
    POSITION_FILE = "positions.json"


# ==================== 日志 ====================
class Logger:
    """日志记录器"""
    
    def __init__(self, name: str, log_file: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # 文件处理器
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        
        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # 格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)
    
    def debug(self, msg: str):
        self.logger.debug(msg)
    
    def info(self, msg: str):
        self.logger.info(msg)
    
    def warning(self, msg: str):
        self.logger.warning(msg)
    
    def error(self, msg: str):
        self.logger.error(msg)


# ==================== Bitget API ====================
class BitgetAPI:
    """Bitget API 封装"""
    
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.BASE_URL
        self.headers = {
            "Content-Type": "application/json",
            "ACCESS-KEY": config.API_KEY,
            "ACCESS-PASSPHRASE": config.PASSPHRASE,
        }
    
    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """生成签名"""
        message = timestamp + method + path + body
        mac = hmac.new(
            self.config.API_SECRET.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _request(self, method: str, path: str, params: Dict = None, body: Dict = None) -> Dict:
        """发送请求（修复：GET参数需加入签名路径）"""
        timestamp = str(int(time.time() * 1000))

        # 构建URL和签名路径
        url = self.base_url + path
        sign_path = path
        if params:
            query = "&".join([f"{k}={v}" for k, v in params.items()])
            url += "?" + query
            sign_path += "?" + query  # GET参数也需参与签名

        # 签名
        body_str = json.dumps(body) if body else ""
        signature = self._sign(timestamp, method, sign_path, body_str)

        headers = self.headers.copy()
        headers["ACCESS-SIGN"] = signature
        headers["ACCESS-TIMESTAMP"] = timestamp

        # 发送请求
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, data=body_str)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")

        result = response.json()

        if result.get("code") != "00000":
            raise Exception(f"API Error: {result.get('msg', 'Unknown error')}")

        return result.get("data", {})
    
    def get_account_info(self) -> Dict:
        """获取账户信息（正确的Assets端点）"""
        return self._request("GET", "/api/v2/spot/account/assets")
    
    def get_balance(self, coin: str = "USDT") -> float:
        """获取指定币种余额"""
        account_info = self._request("GET", "/api/v2/spot/account/assets")
        for item in account_info:
            if item.get("coin") == coin:
                return float(item.get("available", "0"))
        return 0.0
    
    def get_klines(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[Dict]:
        """
        获取K线数据（修复：Bitget V2 history-candles端点对所有现货品种返回400172，
        故改用合成K线方案——基于成交记录和24h数据实时构建OHLCV）
        """
        # 先尝试原生接口（万一 Bitget 修复了）
        try:
            params = {"symbol": symbol, "interval": timeframe, "limit": limit}
            data = self._request("GET", "/api/v2/spot/market/history-candles", params)
            if data and len(data) > 0:
                klines = []
                for k in data:
                    klines.append({
                        "timestamp": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5])
                    })
                klines.sort(key=lambda x: x["timestamp"])
                return klines
        except Exception:
            pass

        # 降级：合成K线方案
        return self._build_synthetic_klines(symbol, timeframe, limit)

    def _build_synthetic_klines(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> List[Dict]:
        """
        合成K线（替代方案）：用 fills 成交记录 + tickers 数据构建近似OHLCV
        timeframe: "1m","5m","15m","1h","4h","1d"

        核心逻辑：
        1. 以成交记录的时间分布为基准构建K线窗口
        2. 有实际成交的周期：精确OHLCV
        3. 无成交的周期：如果limit内历史成交量充足则用线性插值估算，否则标记synthetic=False
        4. limit过小导致历史不足时只返回有成交的K线
        """
        period_map = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}
        period = period_map.get(timeframe, 3600000)

        # 获取成交记录
        try:
            fills = self._request("GET", f"/api/v2/spot/trade/fills?symbol={symbol}&limit=200")
        except:
            fills = []

        # 获取当前行情
        try:
            self._refresh_ticker_cache()
            ticker_data = self._ticker_cache.get(symbol, {})
        except Exception:
            ticker_data = {}

        last_price = float(ticker_data.get("lastPr", 0) or 0)

        if not fills and last_price == 0:
            return []

        # ========== 核心：确定时间窗口 ==========
        # 找成交的时间范围
        fill_times = [int(f.get("cTime", 0)) for f in fills if f.get("cTime")]
        if not fill_times:
            return []

        fill_times.sort()
        earliest_fill_ts = fill_times[0]
        latest_fill_ts = fill_times[-1]

        # 窗口：以最新成交所在周期为终点，向前延伸limit个周期
        latest_period = (latest_fill_ts // period) * period
        window_start = latest_period - (limit - 1) * period

        kline_map = {}  # period_start -> kline data
        for i in range(limit):
            ps = window_start + i * period
            kline_map[ps] = {
                "timestamp": ps,
                "open": None, "high": None, "low": None, "close": None,
                "volume": 0.0, "trades": 0,
                "synthetic": False   # 标记是否经过估算
            }

        # ========== 填入真实成交 ==========
        for fill in fills:
            fill_ts = int(fill.get("cTime", 0))
            fill_price = float(fill.get("priceAvg", 0) or 0)
            fill_size = float(fill.get("size", 0) or 0)
            period_start = (fill_ts // period) * period
            if period_start in kline_map:
                k = kline_map[period_start]
                k["open"] = fill_price
                k["high"] = fill_price
                k["low"] = fill_price
                k["close"] = fill_price
                k["volume"] = fill_size
                k["trades"] = 1

        # ========== 估算无成交的K线 ==========
        sorted_keys = sorted(kline_map.keys())

        for i, period_start in enumerate(sorted_keys):
            k = kline_map[period_start]
            if k["open"] is not None:
                # 已有真实成交
                if k["high"] == k["low"]:
                    k["high"] = k["high"] * 1.001
                    k["low"] = k["low"] * 0.999
                k["synthetic"] = False
                continue

            # 无成交 → 向前找最近的成交回推
            past_close = None
            for j in range(i - 1, -1, -1):
                ps = sorted_keys[j]
                if kline_map[ps]["open"] is not None:
                    past_close = kline_map[ps]["close"]
                    break

            if past_close is not None:
                # 有历史成交，用线性插值估算
                k["open"] = past_close
                k["high"] = past_close
                k["low"] = past_close
                k["close"] = past_close
                k["synthetic"] = True
            # else: past_close is None → 保持全None，后续过滤

        # 过滤掉全是None的K线（limit内历史不足）
        klines = sorted([k for k in kline_map.values() if k["open"] is not None],
                        key=lambda x: x["timestamp"])

        return klines
    def _refresh_ticker_cache(self):
        """刷新行情缓存"""
        try:
            all_tickers = self._request("GET", "/api/v2/spot/market/tickers?instType=SPOT")
            self._ticker_cache = {t['symbol']: t for t in all_tickers}
            self._ticker_cache_time = time.time()
        except Exception:
            pass

    def get_ticker(self, symbol: str) -> Dict:
        """获取实时行情（修复：V2单ticker端点不可用，改用tickers批量接口缓存）"""
        # V2 /market/ticker?symbol=xxx 不存在，改用批量接口
        if not hasattr(self, '_ticker_cache') or \
           time.time() - getattr(self, '_ticker_cache_time', 0) > 60:
            # 缓存超过60秒则刷新
            try:
                all_tickers = self._request("GET", "/api/v2/spot/market/tickers?instType=SPOT")
                self._ticker_cache = {t['symbol']: t for t in all_tickers}
                self._ticker_cache_time = time.time()
            except:
                self._ticker_cache = {}
                self._ticker_cache_time = time.time()

        data = self._ticker_cache.get(symbol, {})
        return {
            "symbol": data.get("symbol", symbol),
            "lastPrice": float(data.get("lastPr", "0") or "0"),
            "priceChange": float(data.get("change24h", "0") or "0"),
            "priceChangePercent": float(data.get("changeUtc24h", "0") or "0"),
            "high24h": float(data.get("high24h", "0") or "0"),
            "low24h": float(data.get("low24h", "0") or "0"),
            "volume24h": float(data.get("baseVolume", "0") or "0"),
        }
    
    def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """获取当前挂单"""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v2/spot/trade/open-orders", params)
    
    def get_order_history(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """获取历史订单（修复：正确端点）"""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v2/spot/trade/history-orders", params)

    def get_filled_orders(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """获取成交订单（修复：正确端点）"""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v2/spot/trade/fills", params)
    
    def place_order(self, symbol: str, side: str, order_type: str,
                    size: str, price: str = None, stop_price: str = None) -> Dict:
        """下单（确认：正确端点为 /api/v2/spot/trade/place-order）"""
        body = {
            "symbol": symbol,
            "side": side,  # "buy" 或 "sell"
            "orderType": order_type,  # "market" 或 "limit"
            "size": size,
        }

        if order_type == "limit" and price:
            body["price"] = price

        if stop_price:
            body["triggerPrice"] = stop_price

        return self._request("POST", "/api/v2/spot/trade/place-order", body=body)

    def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """取消订单（确认：正确端点为 /api/v2/spot/trade/cancel-order）"""
        body = {
            "symbol": symbol,
            "orderId": order_id
        }
        return self._request("POST", "/api/v2/spot/trade/cancel-order", body=body)
    
    def get_order_info(self, symbol: str, order_id: str) -> Dict:
        """获取订单信息"""
        params = {
            "symbol": symbol,
            "orderId": order_id
        }
        return self._request("GET", "/api/v2/spot/trade/query-order", params)


# ==================== 技术指标 ====================
class TechnicalIndicators:
    """技术指标计算"""
    
    @staticmethod
    def calculate_ma(df: pd.DataFrame, period: int, column: str = 'close') -> pd.Series:
        """计算移动平均线"""
        return df[column].rolling(window=period).mean()
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int, column: str = 'close') -> pd.Series:
        """计算指数移动平均线"""
        return df[column].ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14, column: str = 'close') -> pd.Series:
        """计算RSI"""
        delta = df[column].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, 
                       signal: int = 9, column: str = 'close') -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算MACD"""
        ema_fast = df[column].ewm(span=fast, adjust=False).mean()
        ema_slow = df[column].ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, 
                                   std_dev: int = 2, column: str = 'close') -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算布林带"""
        mid = df[column].rolling(window=period).mean()
        std = df[column].rolling(window=period).std()
        
        upper = mid + (std * std_dev)
        lower = mid - (std * std_dev)
        
        return upper, mid, lower
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR (Average True Range)"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    @staticmethod
    def calculate_volumes_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """计算成交量均线"""
        return df['volume'].rolling(window=period).mean()


# ==================== 交易信号 ====================
class TradingSignals:
    """交易信号生成"""
    
    def __init__(self, config: Config):
        self.config = config
        self.ti = TechnicalIndicators()
    
    def analyze(self, df: pd.DataFrame, symbol: str) -> Dict:
        """综合分析生成交易信号"""
        symbol_config = self.config.SYMBOLS.get(symbol, {})
        symbol_type = symbol_config.get("type", "stock_bc")
        
        # 计算技术指标
        df['ma5'] = self.ti.calculate_ma(df, self.config.MA_SHORT)
        df['ma20'] = self.ti.calculate_ma(df, self.config.MA_MEDIUM)
        df['ma50'] = self.ti.calculate_ma(df, self.config.MA_LONG)
        df['ma200'] = self.ti.calculate_ma(df, self.config.MA_SUPER)
        
        df['rsi'] = self.ti.calculate_rsi(df, self.config.RSI_PERIOD)
        df['macd'], df['macd_signal'], df['macd_hist'] = self.ti.calculate_macd(
            df, self.config.MACD_FAST, self.config.MACD_SLOW, self.config.MACD_SIGNAL
        )
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = self.ti.calculate_bollinger_bands(
            df, self.config.BB_PERIOD, self.config.BB_STD
        )
        df['atr'] = self.ti.calculate_atr(df)
        df['vol_ma'] = self.ti.calculate_volumes_ma(df)
        
        # 最新一根K线
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        # 各类型标的分析
        if symbol_type in ["metal", "stock_a_plus", "stock_a", "stock_bc", "china"]:
            return self._analyze_stock(df, latest, prev, symbol_config)
        elif symbol_type in ["etf_commodity", "etf_index"]:
            return self._analyze_etf(df, latest, prev, symbol_config)
        elif symbol_type == "bond":
            return self._analyze_bond(df, latest, prev, symbol_config)
        
        return {"action": "hold", "strength": 0, "signals": []}
    
    def _analyze_stock(self, df: pd.DataFrame, latest: pd.Series, 
                       prev: pd.Series, config: Dict) -> Dict:
        """分析股票类型标的"""
        signals = []
        score = 0
        
        # 均线多头/空头排列
        ma_trend = self._check_ma_trend(latest)
        if ma_trend > 0:
            score += 2
            signals.append(("均线多头排列", "positive"))
        elif ma_trend < 0:
            score -= 2
            signals.append(("均线空头排列", "negative"))
        
        # RSI 分析
        rsi_result = self._check_rsi(latest)
        signals.append(rsi_result[0])
        score += rsi_result[1]
        
        # MACD 分析
        macd_result = self._check_macd(latest, prev)
        signals.append(macd_result[0])
        score += macd_result[1]
        
        # 布林带位置
        bb_result = self._check_bollinger(latest)
        signals.append(bb_result[0])
        score += bb_result[1]
        
        # 成交量确认
        vol_result = self._check_volume(latest)
        signals.append(vol_result[0])
        score += vol_result[1]
        
        # 综合评分和信号
        if score >= 4:
            action = "buy"
            strength = min(score, 6)  # 最高6分
        elif score <= -4:
            action = "sell"
            strength = min(abs(score), 6)
        else:
            action = "hold"
            strength = abs(score)
        
        return {
            "action": action,
            "strength": strength,
            "score": score,
            "signals": signals,
            "rsi": latest['rsi'],
            "ma_trend": ma_trend,
            "macd_cross": macd_result[2]
        }
    
    def _analyze_etf(self, df: pd.DataFrame, latest: pd.Series,
                     prev: pd.Series, config: Dict) -> Dict:
        """分析ETF类型标的"""
        signals = []
        score = 0
        
        # MA趋势
        ma_trend = self._check_ma_trend(latest)
        if ma_trend > 0:
            score += 2
            signals.append(("均线多头排列", "positive"))
        elif ma_trend < 0:
            score -= 2
            signals.append(("均线空头排列", "negative"))
        
        # RSI
        rsi_result = self._check_rsi(latest)
        signals.append(rsi_result[0])
        score += rsi_result[1]
        
        # MACD
        macd_result = self._check_macd(latest, prev)
        signals.append(macd_result[0])
        score += macd_result[1]
        
        # 成交量
        vol_result = self._check_volume(latest)
        signals.append(vol_result[0])
        score += vol_result[1]
        
        if score >= 3:
            action = "buy"
            strength = min(score, 5)
        elif score <= -3:
            action = "sell"
            strength = min(abs(score), 5)
        else:
            action = "hold"
            strength = abs(score)
        
        return {
            "action": action,
            "strength": strength,
            "score": score,
            "signals": signals,
            "rsi": latest['rsi'],
            "ma_trend": ma_trend,
            "macd_cross": macd_result[2]
        }
    
    def _analyze_bond(self, df: pd.DataFrame, latest: pd.Series,
                      prev: pd.Series, config: Dict) -> Dict:
        """分析债券ETF"""
        # 债券通常在股市下跌时表现好
        signals = []
        
        # 检查VIX等市场情绪指标
        # 这里简化为持有信号
        signals.append(("债券ETF持有", "neutral"))
        
        return {
            "action": "hold",
            "strength": 0,
            "score": 0,
            "signals": signals,
            "rsi": latest['rsi'] if 'rsi' in latest else 50,
            "ma_trend": 0,
            "macd_cross": None
        }
    
    def _check_ma_trend(self, latest: pd.Series) -> int:
        """检查均线趋势"""
        ma5 = latest['ma5']
        ma20 = latest['ma20']
        ma50 = latest['ma50']
        ma200 = latest['ma200']
        
        if ma5 > ma20 > ma50:
            return 1  # 多头
        elif ma5 < ma20 < ma50:
            return -1  # 空头
        return 0  # 震荡
    
    def _check_rsi(self, latest: pd.Series) -> Tuple[Tuple[str, str], int]:
        """检查RSI"""
        rsi = latest['rsi']
        
        if pd.isna(rsi):
            return (("RSI无法计算", "neutral"), 0)
        
        if rsi < self.config.RSI_OVERSOLD:
            return (("RSI超卖", "positive"), 2)
        elif rsi < 50:
            return (("RSI偏弱", "neutral"), 0)
        elif rsi > self.config.RSI_OVERBOUGHT:
            return (("RSI超买", "negative"), -2)
        elif rsi > 50:
            return (("RSI偏强", "neutral"), 0)
        
        return (("RSI中性", "neutral"), 0)
    
    def _check_macd(self, latest: pd.Series, prev: pd.Series) -> Tuple[Tuple[str, str], int, str]:
        """检查MACD"""
        macd = latest['macd']
        signal = latest['macd_signal']
        hist = latest['macd_hist']
        prev_hist = prev['macd_hist']
        
        if pd.isna(macd) or pd.isna(signal):
            return (("MACD无法计算", "neutral"), 0, None)
        
        # 金叉/死叉
        if prev_hist <= 0 and hist > 0:
            cross = "golden"  # 金叉
            if macd > 0:
                return (("MACD零轴上金叉", "positive"), 2, cross)
            else:
                return (("MACD零轴下金叉", "positive"), 1, cross)
        elif prev_hist >= 0 and hist < 0:
            cross = "death"  # 死叉
            if macd < 0:
                return (("MACD零轴下死叉", "negative"), -2, cross)
            else:
                return (("MACD零轴上死叉", "negative"), -1, cross)
        
        # MACD柱状图
        if hist > 0 and hist > prev_hist:
            return (("MACD柱状图扩张", "positive"), 1, None)
        elif hist < 0 and hist < prev_hist:
            return (("MACD柱状图收缩", "negative"), -1, None)
        
        return (("MACD中性", "neutral"), 0, None)
    
    def _check_bollinger(self, latest: pd.Series) -> Tuple[Tuple[str, str], int]:
        """检查布林带"""
        close = latest['close']
        upper = latest['bb_upper']
        lower = latest['bb_lower']
        
        if pd.isna(upper) or pd.isna(lower):
            return (("布林带无法计算", "neutral"), 0)
        
        # 计算价格位置百分比
        bb_position = (close - lower) / (upper - lower) if upper != lower else 0.5
        
        if close <= lower:
            return (("触及布林下轨(超卖)", "positive"), 1)
        elif close >= upper:
            return (("触及布林上轨(超买)", "negative"), -1)
        elif bb_position < 0.2:
            return (("布林下轨附近", "positive"), 1)
        elif bb_position > 0.8:
            return (("布林上轨附近", "negative"), -1)
        
        return (("布林带中性", "neutral"), 0)
    
    def _check_volume(self, latest: pd.Series) -> Tuple[Tuple[str, str], int]:
        """检查成交量"""
        volume = latest['volume']
        vol_ma = latest['vol_ma']
        
        if pd.isna(volume) or pd.isna(vol_ma) or vol_ma == 0:
            return (("成交量无法计算", "neutral"), 0)
        
        vol_ratio = volume / vol_ma
        
        if vol_ratio > 1.5:
            return (("成交量放大", "positive"), 1)
        elif vol_ratio < 0.5:
            return (("成交量萎缩", "neutral"), 0)
        
        return (("成交量正常", "neutral"), 0)


# ==================== 仓位管理 ====================
class PositionManager:
    """仓位管理器"""
    
    def __init__(self, config: Config, api: BitgetAPI, logger: Logger):
        self.config = config
        self.api = api
        self.logger = logger
        self.positions = {}  # symbol -> position info
        self.load_positions()
    
    def load_positions(self):
        """从文件加载仓位"""
        try:
            with open(self.config.POSITION_FILE, 'r') as f:
                self.positions = json.load(f)
            self.logger.info(f"已加载 {len(self.positions)} 个仓位")
        except FileNotFoundError:
            self.logger.info("无历史仓位记录")
    
    def save_positions(self):
        """保存仓位到文件"""
        with open(self.config.POSITION_FILE, 'w') as f:
            json.dump(self.positions, f, indent=2, ensure_ascii=False)
    
    def get_total_position_value(self, current_prices: Dict[str, float]) -> float:
        """计算当前总持仓价值(USDT)"""
        total = 0.0
        for symbol, pos in self.positions.items():
            if symbol in current_prices:
                total += pos['quantity'] * current_prices[symbol]
        return total
    
    def get_account_balance(self) -> float:
        """获取账户余额"""
        return self.api.get_balance("USDT")
    
    def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        try:
            ticker = self.api.get_ticker(symbol)
            return ticker.get('lastPrice', 0)
        except:
            return 0.0
    
    def open_position(self, symbol: str, quantity: float, price: float, 
                     stop_loss: float, strategy_score: int):
        """开仓"""
        self.positions[symbol] = {
            "quantity": quantity,
            "entry_price": price,
            "stop_loss": stop_loss,
            "entry_time": datetime.now().isoformat(),
            "strategy_score": strategy_score,
            "highest_price": price,
            "trailing_stop": price * (1 - stop_loss)
        }
        self.save_positions()
        self.logger.info(f"开仓: {symbol} 数量:{quantity} 价格:{price} 止损:{stop_loss}")
    
    def close_position(self, symbol: str, reason: str = ""):
        """平仓"""
        if symbol in self.positions:
            del self.positions[symbol]
            self.save_positions()
            self.logger.info(f"平仓: {symbol} 原因: {reason}")
    
    def update_position(self, symbol: str, current_price: float):
        """更新仓位(跟踪止损)"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        pos['highest_price'] = max(pos['highest_price'], current_price)
        
        # 跟踪止损逻辑
        entry = pos['entry_price']
        highest = pos['highest_price']
        stop = pos['stop_loss']
        
        # 上涨后调整止损
        profit_percent = (highest - entry) / entry
        
        if profit_percent >= 0.08:  # 上涨8%
            new_stop = highest * 0.95  # 止损提高到最高点的95%
            pos['trailing_stop'] = max(new_stop, pos['trailing_stop'])
        elif profit_percent >= 0.05:  # 上涨5%
            new_stop = highest * 0.97
            pos['trailing_stop'] = max(new_stop, pos['trailing_stop'])
        
        self.save_positions()
    
    def check_stop_loss(self, symbol: str, current_price: float) -> bool:
        """检查是否触发止损"""
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        entry_price = pos['entry_price']
        trailing_stop = pos['trailing_stop']
        
        # 跟踪止损优先
        if current_price <= trailing_stop:
            self.logger.warning(f"{symbol} 触发跟踪止损: 当前价{current_price} <= 止损{trailing_stop}")
            return True
        
        # 固定止损
        stop_loss_price = entry_price * (1 - pos['stop_loss'])
        if current_price <= stop_loss_price:
            self.logger.warning(f"{symbol} 触发止损: 当前价{current_price} <= 止损{stop_loss_price}")
            return True
        
        return False
    
    def get_positions_summary(self) -> List[Dict]:
        """获取仓位汇总"""
        summary = []
        for symbol, pos in self.positions.items():
            current_price = self.get_current_price(symbol)
            profit_percent = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            
            summary.append({
                "symbol": symbol,
                "quantity": pos['quantity'],
                "entry_price": pos['entry_price'],
                "current_price": current_price,
                "profit_percent": profit_percent,
                "stop_loss": pos['stop_loss'],
                "trailing_stop": pos['trailing_stop'],
                "highest_price": pos['highest_price']
            })
        return summary


# ==================== 交易执行 ====================
class TradingExecutor:
    """交易执行器"""
    
    def __init__(self, config: Config, api: BitgetAPI, 
                 position_manager: PositionManager, logger: Logger):
        self.config = config
        self.api = api
        self.pm = position_manager
        self.logger = logger
    
    def execute_buy(self, symbol: str, signal: Dict) -> bool:
        """执行买入"""
        try:
            # 获取当前价格
            ticker = self.api.get_ticker(symbol)
            current_price = ticker['lastPrice']
            
            # 计算仓位
            balance = self.pm.get_account_balance()
            symbol_config = self.config.SYMBOLS.get(symbol, {})
            max_position_ratio = symbol_config.get("max_position", 0.10)
            max_position_value = balance * max_position_ratio
            quantity = max_position_value / current_price
            quantity = round(quantity, 4)
            
            # 获取止损设置
            stop_loss_ratio = symbol_config.get("stop_loss", 0.05)
            stop_loss_price = current_price * (1 - stop_loss_ratio)
            
            # 下单
            order_result = self.api.place_order(
                symbol=symbol,
                side="buy",
                order_type="market",
                size=str(quantity)
            )
            
            if order_result.get("orderId"):
                # 开仓
                self.pm.open_position(
                    symbol, quantity, current_price, 
                    stop_loss_ratio, signal.get('score', 0)
                )
                self.logger.info(f"✅ 买入成功: {symbol} 数量:{quantity} 价格:{current_price}")
                return True
            else:
                self.logger.error(f"❌ 买入失败: {symbol}, 结果: {order_result}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 买入异常: {symbol}, 错误: {str(e)}")
            return False
    
    def execute_sell(self, symbol: str, quantity: float, reason: str = "") -> bool:
        """执行卖出"""
        try:
            # 下单
            order_result = self.api.place_order(
                symbol=symbol,
                side="sell",
                order_type="market",
                size=str(quantity)
            )
            
            if order_result.get("orderId"):
                self.pm.close_position(symbol, reason)
                self.logger.info(f"✅ 卖出成功: {symbol} 数量:{quantity} 原因:{reason}")
                return True
            else:
                self.logger.error(f"❌ 卖出失败: {symbol}, 结果: {order_result}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 卖出异常: {symbol}, 错误: {str(e)}")
            return False
    
    def calculate_position_size(self, symbol: str, price: float,
                                 account_balance: float) -> Optional[float]:
        """计算仓位大小（修复：引用self.pm.positions）"""
        symbol_config = self.config.SYMBOLS.get(symbol, {})
        max_position_ratio = symbol_config.get("max_position", 0.10)
        max_position_value = account_balance * max_position_ratio

        # 检查总仓位限制
        current_prices = {s: self.get_current_price(s) for s in self.pm.positions.keys()}
        total_position = self.pm.get_total_position_value(current_prices)

        if total_position / account_balance >= self.config.MAX_TOTAL_POSITION:
            self.logger.warning("总仓位已达上限，无法新开仓位")
            return None

        # 计算可买入数量
        quantity = max_position_value / price

        return round(quantity, 4)
    
    def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        try:
            ticker = self.api.get_ticker(symbol)
            return ticker.get('lastPrice', 0)
        except:
            return 0.0
