#!/usr/bin/env python3
"""
Bitget 美股现货交易机器人 - 修复版 v2
=====================================
美股时段每5分钟扫描，40U开仓，自动买卖，推送通知
"""

import requests
import time
import json
import hmac
import hashlib
import base64
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
import sys
sys.path.insert(0, ".")
from news_analyzer import NewsAnalyzer

# ==================== 配置 ====================
API_KEY = "bg_55d7ddd792c3ebab233b4a6911f95f99"
API_SECRET = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
PASSPHRASE = "liugang123"
BASE_URL = "https://api.bitget.com"

# 每笔开仓金额 (USDT) - 最低2U
POSITION_SIZE = 40

# 扫描间隔 (秒) - 美股时段10分钟
SCAN_INTERVAL = 600

# 交易标的 - 全部代币化美股(17个)
SYMBOLS = {
    # 个股
    "TSLAONUSDT": {"name": "Tesla", "stop_loss": 0.08},
    "NVDAONUSDT": {"name": "Nvidia", "stop_loss": 0.08},
    "AAPLONUSDT": {"name": "Apple", "stop_loss": 0.05},
    "METAONUSDT": {"name": "Meta", "stop_loss": 0.05},
    "AMZNONUSDT": {"name": "Amazon", "stop_loss": 0.05},
    "GOOGLONUSDT": {"name": "Google", "stop_loss": 0.05},
    "MSFTONUSDT": {"name": "Microsoft", "stop_loss": 0.05},
    "AMDONUSDT": {"name": "AMD", "stop_loss": 0.06},
    # 指数ETF
    "SPYONUSDT": {"name": "S&P500 ETF", "stop_loss": 0.05},
    "IVVONUSDT": {"name": "S&P500 ETF", "stop_loss": 0.05},
    "QQQONUSDT": {"name": "Nasdaq ETF", "stop_loss": 0.06},
    "IWMONUSDT": {"name": "Russell2000 ETF", "stop_loss": 0.06},
    "ITOTONUSDT": {"name": "Total Market ETF", "stop_loss": 0.05},
    # 商品
    "IAUONUSDT": {"name": "Gold ETF", "stop_loss": 0.04},
    "SLVONUSDT": {"name": "Silver ETF", "stop_loss": 0.05},
    # 其他
    "KATUSDT": {"name": "Katana", "stop_loss": 0.10},
    "CVXUSDT": {"name": "Chevron", "stop_loss": 0.05},
}

# 持仓记录文件
POSITIONS_FILE = "bot_positions.json"
LOG_FILE = "bot_trading.log"


# ==================== 日志 ====================
def get_logger():
    logger = logging.getLogger("TradingBot")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

logger = get_logger()


# ==================== Bitget API ====================
class BitgetAPI:
    def __init__(self):
        self.base_url = BASE_URL
    
    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """签名: HMAC-SHA256 + Base64"""
        message = timestamp + method + path
        if body:
            message = timestamp + method + path + body
        mac = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()
    
    def _headers(self, timestamp: str, signature: str) -> Dict:
        return {
            "Content-Type": "application/json",
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
        }
    
    def _request(self, method: str, path: str, body: Dict = None) -> Dict:
        timestamp = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body else ""
        signature = self._sign(timestamp, method, path, body_str)
        headers = self._headers(timestamp, signature)
        
        url = self.base_url + path
        
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            resp = requests.post(url, headers=headers, data=body_str, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        result = resp.json()
        if result.get("code") != "00000":
            raise Exception(f"API Error {result.get('code')}: {result.get('msg', 'Unknown')}")
        return result.get("data", {})
    
    def get_news_score(self, symbol: str, config: Dict) -> Tuple[float, List[str], List[Dict]]:
        """Get news sentiment score and events"""
        cache_key = f"{symbol}_news"
        now = datetime.now()
        if cache_key in self.last_news_refresh:
            last_refresh = self.last_news_refresh[cache_key]
            if (now - last_refresh).seconds < 300:
                return 0, [], []
        try:
            name = config.get("name", symbol.replace("ONUSDT", ""))
            result = self.news_analyzer.analyze_stock(symbol.replace("ONUSDT", ""), name)
            self.last_news_refresh[cache_key] = now
            score = result.get("score", 0)
            signals = result.get("signals", [])
            events = result.get("major_events", [])
            return score, signals, events
        except Exception as e:
            logger.debug(f"News fetch failed {symbol}: {e}")
            return 0, [], []

    def get_balance(self) -> float:
        """获取USDT余额"""
        try:
            data = self._request("GET", "/api/v2/spot/account/assets")
            for item in data:
                if item.get("coin") == "USDT":
                    return float(item.get("available", "0"))
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
        return 0.0

    def get_coin_balance(self, coin: str) -> float:
        """获取指定币种可用余额"""
        try:
            data = self._request("GET", "/api/v2/spot/account/assets")
            for item in data:
                if item.get("coin") == coin:
                    return float(item.get("available", "0"))
        except Exception as e:
            logger.error(f"获取{coin}余额失败: {e}")
        return 0.0
    
    def get_klines(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取K线数据"""
        try:
            # 公开接口不需要签名
            url = f"{self.base_url}/api/v2/spot/market/candles?symbol={symbol}&granularity=1h&limit={limit}"
            resp = requests.get(url, timeout=10)
            result = resp.json()
            
            if result.get("code") != "00000":
                return []
            
            klines = []
            for k in result.get("data", []):
                klines.append({
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "timestamp": int(k[0])
                })
            return klines[-limit:]
        except Exception as e:
            logger.error(f"获取K线失败 {symbol}: {e}")
            return []
    
    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取实时行情"""
        try:
            url = f"{self.base_url}/api/v2/spot/market/tickers"
            resp = requests.get(url, timeout=10)
            result = resp.json()
            
            if result.get("code") == "00000":
                for item in result.get("data", []):
                    if item.get("symbol") == symbol:
                        return {
                            "price": float(item.get("lastPr", "0")),
                            "change24h": float(item.get("change24h", "0")),
                        }
        except Exception as e:
            logger.error(f"获取行情失败 {symbol}: {e}")
        return None
    
    def place_order(self, symbol: str, side: str, size: float) -> Optional[str]:
        """下单 - buy时size是USDT金额，sell时size是标的数量"""
        try:
            body = {
                "symbol": symbol,
                "side": side,
                "orderType": "market",
                "size": str(round(size, 6))  # 买入=USDT金额，卖出=实际数量
            }
            result = self._request("POST", "/api/v2/spot/trade/place-order", body)
            
            if result.get("orderId"):
                return result["orderId"]
        except Exception as e:
            logger.error(f"下单失败 {symbol} {side}: {e}")
        return None
    
    def get_order_fill(self, symbol: str) -> Optional[Dict]:
        """获取订单成交信息"""
        try:
            # 查询最近成交
            params = {"symbol": symbol, "limit": "1"}
            result = self._request("GET", "/api/v2/spot/trade/fills", params)
            if result:
                return result[0] if isinstance(result, list) else result
        except:
            pass
        return None


# ==================== 技术指标 ====================
class TechIndicators:
    @staticmethod
    def ma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()
    
    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram


# ==================== 信号分析 ====================
class SignalAnalyzer:
    def __init__(self):
        self.ti = TechIndicators()
    
    def analyze(self, klines: List[Dict]) -> Dict:
        if len(klines) < 60:
            return {"action": "hold", "strength": 0}
        
        df = pd.DataFrame(klines)
        closes = df['close']
        
        # 计算指标
        ma5 = self.ti.ma(closes, 5)
        ma20 = self.ti.ma(closes, 20)
        ma50 = self.ti.ma(closes, 50)
        rsi = self.ti.rsi(closes, 14)
        macd_line, signal_line, hist = self.ti.macd(closes)
        
        latest_close = closes.iloc[-1]
        latest_rsi = rsi.iloc[-1]
        latest_macd_hist = hist.iloc[-1]
        prev_macd_hist = hist.iloc[-2]
        
        score = 0
        signals = []
        
        # 均线多头排列
        if not pd.isna(ma5.iloc[-1]) and not pd.isna(ma20.iloc[-1]) and not pd.isna(ma50.iloc[-1]):
            if ma5.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1]:
                score += 2
                signals.append("均线多头")
            elif ma5.iloc[-1] < ma20.iloc[-1] < ma50.iloc[-1]:
                score -= 2
                signals.append("均线空头")
        
        # RSI分析
        if not pd.isna(latest_rsi):
            if latest_rsi < 35:
                score += 2
                signals.append(f"RSI超卖({latest_rsi:.1f})")
            elif latest_rsi < 45:
                score += 1
                signals.append(f"RSI偏弱({latest_rsi:.1f})")
            elif latest_rsi > 70:
                score -= 2
                signals.append(f"RSI超买({latest_rsi:.1f})")
            elif latest_rsi > 60:
                score -= 1
                signals.append(f"RSI偏强({latest_rsi:.1f})")
        
        # MACD分析
        if not pd.isna(latest_macd_hist) and not pd.isna(prev_macd_hist):
            if prev_macd_hist <= 0 and latest_macd_hist > 0:
                score += 2
                signals.append("MACD金叉")
            elif prev_macd_hist >= 0 and latest_macd_hist < 0:
                score -= 2
                signals.append("MACD死叉")
            elif latest_macd_hist > 0 and latest_macd_hist > prev_macd_hist:
                score += 1
                signals.append("MACD扩张")
            elif latest_macd_hist < 0 and latest_macd_hist < prev_macd_hist:
                score -= 1
                signals.append("MACD收缩")
        
        # 决定操作
        if score >= 4:
            action = "buy"
        elif score <= -4:
            action = "sell"
        else:
            action = "hold"
        
        return {
            "action": action,
            "strength": abs(score),
            "score": score,
            "signals": signals,
            "rsi": round(latest_rsi, 1) if not pd.isna(latest_rsi) else 50,
            "price": latest_close
        }


# ==================== 持仓管理 ====================
class PositionManager:
    def __init__(self):
        self.positions = {}
        self.load()
    
    def load(self):
        try:
            with open(POSITIONS_FILE, 'r') as f:
                self.positions = json.load(f)
        except:
            self.positions = {}
    
    def save(self):
        with open(POSITIONS_FILE, 'w') as f:
            json.dump(self.positions, f, indent=2, ensure_ascii=False)
    
    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions
    
    def add_position(self, symbol: str, entry_price: float, stop_loss: float, size_usdt: float, quantity: float):
        self.positions[symbol] = {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "size_usdt": size_usdt,
            "quantity": quantity,
            "entry_time": datetime.now().isoformat(),
            "highest_price": entry_price
        }
        self.save()
        logger.info(f"开仓: {symbol} 价格:{entry_price} 数量:{quantity} ({size_usdt}U)")
    
    def remove_position(self, symbol: str):
        if symbol in self.positions:
            del self.positions[symbol]
            self.save()
            logger.info(f"平仓: {symbol}")
    
    def update_and_check(self, symbol: str, current_price: float, stop_loss_pct: float) -> Tuple[bool, str]:
        """检查持仓，返回(是否触发卖出, 原因)"""
        if symbol not in self.positions:
            return False, ""
        
        pos = self.positions[symbol]
        entry = pos['entry_price']
        highest = pos['highest_price']
        
        # 更新最高价
        if current_price > highest:
            pos['highest_price'] = current_price
            highest = current_price
        
        # 跟踪止损
        profit_pct = (highest - entry) / entry
        
        trailing_stop = entry * (1 - stop_loss_pct)
        if profit_pct >= 0.08:
            trailing_stop = highest * 0.95
        elif profit_pct >= 0.05:
            trailing_stop = highest * 0.97
        
        pos['trailing_stop'] = trailing_stop
        self.save()
        
        # 检查止损
        if current_price <= trailing_stop:
            return True, f"跟踪止损({current_price:.4f}<={trailing_stop:.4f})"
        
        fixed_stop = entry * (1 - stop_loss_pct)
        if current_price <= fixed_stop:
            return True, f"固定止损({current_price:.4f}<={fixed_stop:.4f})"
        
        return False, ""


# ==================== 交易机器人 ====================
class TradingBot:
    def __init__(self):
        self.api = BitgetAPI()
        self.analyzer = SignalAnalyzer()
        self.news_analyzer = NewsAnalyzer()
        self.last_news_refresh = {}
        self.pm = PositionManager()
    
    def get_market_session(self) -> str:
        """获取美股交易时段状态
        返回值:
            - open: 开盘交易时段 (21:30-04:00 北京时间)
            - pre_market: 盘前时段 (04:00-09:00)
            - after_hours: 盘后时段 (09:00-21:30 周一到周四)
            - closed: 收盘/周末
        """
        now = datetime.now()  # 使用本地时间（北京时间）
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute
        
        # 周末
        if weekday >= 5:
            return "closed"
        
        # 美股交易时段: 北京时间 21:30 - 次日 04:00
        # 21:30-23:59
        if hour >= 21 or hour < 4:
            return "open"
        # 盘前: 04:00-09:00
        elif hour >= 4 and hour < 9:
            return "pre_market"
        # 盘后: 09:00-21:30 (周一到周四)
        else:
            return "after_hours"
    
    def is_trading_time(self) -> bool:
        """是否处于交易时段"""
        return self.get_market_session() == "open"
    
    def get_news_score(self, symbol: str, config: Dict) -> Tuple[float, List[str], List[Dict]]:
        """Get news sentiment score and events"""
        cache_key = f"{symbol}_news"
        now = datetime.now()
        if cache_key in self.last_news_refresh:
            last_refresh = self.last_news_refresh[cache_key]
            if (now - last_refresh).seconds < 300:
                return 0, [], []
        try:
            name = config.get("name", symbol.replace("ONUSDT", ""))
            result = self.news_analyzer.analyze_stock(symbol.replace("ONUSDT", ""), name)
            self.last_news_refresh[cache_key] = now
            score = result.get("score", 0)
            signals = result.get("signals", [])
            events = result.get("major_events", [])
            return score, signals, events
        except Exception as e:
            logger.debug(f"News fetch failed {symbol}: {e}")
            return 0, [], []

    def get_balance(self) -> float:
        return self.api.get_balance()
    
    def scan_and_trade(self) -> Tuple[int, int, List[str]]:
        """扫描并执行交易"""
        buy_count = 0
        sell_count = 0
        messages = []
        
        balance = self.get_balance()
        
        for symbol, config in SYMBOLS.items():
            try:
                klines = self.api.get_klines(symbol, limit=100)
                if len(klines) < 60:
                    continue
                
                ticker = self.api.get_ticker(symbol)
                if not ticker:
                    continue
                
                current_price = ticker['price']
                if current_price <= 0:
                    continue
                
                signal = self.analyzer.analyze(klines)
                
                # Get news sentiment
                news_score, news_signals, major_events = self.get_news_score(symbol, config)
                
                # Combine scores - 新闻评分占比限制为±1分
                tech_score = signal["score"]
                news_score_capped = max(-1, min(1, news_score))  # 限制在±1
                total_score = tech_score + news_score_capped
                stop_loss_pct = config['stop_loss']
                name = config.get('name', symbol)
                
                # 检查持仓
                should_sell, sell_reason = self.pm.update_and_check(symbol, current_price, stop_loss_pct)
                
                # 持仓中
                if self.pm.has_position(symbol):
                    # 策略卖出信号
                    if total_score <= -4:
                        should_sell = True
                        sell_reason = f"Sell(tech:{tech_score} + news:{news_score:.1f})"
                        should_sell = True
                        sell_reason = f"策略卖出(评分:{signal['score']})"
                    
                    # RSI极端超买
                    if signal['rsi'] > 80:
                        should_sell = True
                        sell_reason = f"RSI超买({signal['rsi']})"
                    
                    if major_events and news_score < -3:
                        should_sell = True
                        sell_reason = f"Major neg event news:{news_score:.1f}"
                    
                    # 执行卖出
                    if should_sell:
                        pos = self.pm.positions.get(symbol)
                        if pos:
                            # 卖出数量 = 实际持有量（修复：查真实余额，不超过持仓）
                            base_coin = symbol.replace("USDT", "")
                            available = self.api.get_coin_balance(base_coin)
                            if available < 0.0001:
                                logger.warning(f"{symbol} 实际余额不足，跳过卖出")
                                self.pm.remove_position(symbol)
                                continue
                            sell_qty = round(min(available, pos['quantity']), 3)
                            sell_value = sell_qty * current_price
                            # 小于最小下单金额1U，跳过实际卖出
                            if sell_value < 1:
                                logger.warning(f"{symbol} 持仓价值${sell_value:.2f}<1U，跳过卖出并清理记录")
                                self.pm.remove_position(symbol)
                                continue
                            order_id = self.api.place_order(symbol, "sell", sell_qty)
                            if order_id:
                                self.pm.remove_position(symbol)
                                sell_count += 1
                                profit = (current_price - pos['entry_price']) / pos['entry_price'] * 100
                                msg = f"🔴 卖出 {name}({symbol})\n价格: {current_price:.4f}\n原因: {sell_reason}\n盈亏: {profit:+.2f}%"
                                messages.append(msg)
                                logger.info(msg.replace('\n', ' '))
                                # 写入通知文件
                                try:
                                    with open('/root/.openclaw/workspace/trading_notifications.txt', 'a') as nf:
                                        nf.write(f"[BUY] {datetime.now().strftime('%H:%M:%S')} {msg}\n")
                                except:
                                    pass
                
                # 无持仓时买入
                else:
                    if balance < POSITION_SIZE:
                        continue
                    
                    if total_score >= 4 and news_score_capped >= -1:
                        # 下单金额
                        order_id = self.api.place_order(symbol, "buy", POSITION_SIZE)
                        if order_id:
                            # 计算实际买入数量
                            quantity = POSITION_SIZE / current_price
                            self.pm.add_position(symbol, current_price, stop_loss_pct, POSITION_SIZE, quantity)
                            buy_count += 1
                            balance -= POSITION_SIZE
                            
                            all_signals = signal["signals"] + news_signals
                            entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            quantity = POSITION_SIZE / current_price
                            msg = f"🟢 开仓提醒\n名称：{name}({symbol})\n开仓评分：{total_score:.1f}分\n开仓数量：{quantity:.6f}\n开仓价格：${current_price:.4f}\n开仓资金：{POSITION_SIZE}U\n开仓时间：{entry_time}\n信号：{', '.join(all_signals[:3])}"
                            messages.append(msg)
                            logger.info(msg.replace('\n', ' '))
                            with open('/root/.openclaw/workspace/trading_notifications.txt', 'a') as nf:
                                nf.write(f"[BUY] {datetime.now().strftime('%H:%M:%S')} {msg}\n")
                
                time.sleep(0.3)
                
            except Exception as e:
                logger.error(f"处理 {symbol} 时出错: {e}")
        
        return buy_count, sell_count, messages
    
    def run(self):
        """运行主循环"""
        logger.info("=" * 50)
        logger.info("🚀 Bitget 美股交易机器人 v3 启动")
        logger.info(f"监控标的: {len(SYMBOLS)} 个")
        logger.info(f"开仓金额: {POSITION_SIZE} U/笔")
        logger.info("=" * 50)
        logger.info("交易时段规则:")
        logger.info("  📈 开盘交易: 21:30-04:00 (每5分钟扫描)")
        logger.info("  🌅 盘前准备: 04:00-09:00 (每30分钟检查)")
        logger.info("  🌙 盘后时段: 09:00-21:30 (每小时检查)")
        logger.info("  🚫 周末: 每2小时检查一次")
        logger.info("=" * 50)
        
        while True:
            try:
                session = self.get_market_session()
                balance = self.get_balance()
                
                if session == "open":
                    # 开盘时段：每5分钟扫描
                    logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] 📈 美股开盘中 | 余额: {balance:.2f} U")
                    
                    buy_cnt, sell_cnt, msgs = self.scan_and_trade()
                    
                    if buy_cnt > 0 or sell_cnt > 0:
                        logger.info(f"本次操作: 买入{buy_cnt}笔, 卖出{sell_cnt}笔")
                        for msg in msgs:
                            print(msg)
                    else:
                        logger.info("本次扫描: 无交易信号")
                    
                    time.sleep(300)  # 5分钟
                    
                elif session == "pre_market":
                    # 盘前时段：每30分钟检查一次
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🌅 盘前准备中 (04:00-09:00)")
                    logger.info("等待美股开盘...")
                    time.sleep(1800)  # 30分钟
                    
                elif session == "after_hours":
                    # 盘后时段：每小时检查一次
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🌙 盘后时段 (09:00-21:30)")
                    logger.info("等待下次美股开盘...")
                    time.sleep(3600)  # 1小时
                    
                else:
                    # 周末/节假日：每2小时检查一次
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 🚫 周末/节假日")
                    logger.info("等待周一美股开盘...")
                    time.sleep(7200)  # 2小时
                
            except KeyboardInterrupt:
                logger.info("\n收到停止信号，机器人退出")
                break
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                time.sleep(60)


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
