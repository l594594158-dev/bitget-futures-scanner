#!/usr/bin/env python3
"""
移动止盈监控脚本 (trailing_stop.py)
独立运行，只负责持仓追踪和移动止盈

用法:
  python3 trailing_stop.py --start     启动监控
  python3 trailing_stop.py --stop      停止监控
  python3 trailing_stop.py --status     查看状态
  python3 trailing_stop.py --test       测试模式（不执行真实交易）

功能:
  - 每3秒扫描所有持仓
  - 记录做空最低价（做多最高价）作为峰值
  - 盈利>8%激活移动止盈
  - 从峰值回撤4%执行止盈
  - 完全独立于主扫描逻辑
"""

import sys
import os
import time
import json
import signal
import subprocess
from datetime import datetime

# 配置文件路径
WORKSPACE = '/root/.openclaw/workspace'
POSITIONS_FILE = f'{WORKSPACE}/db_positions.json'
PID_FILE = f'{WORKSPACE}/trailing_stop.pid'
LOG_FILE = f'{WORKSPACE}/trailing_stop.log'
CONFIG_FILE = f'{WORKSPACE}/trailing_config.json'

# 默认参数
TRAIL_TRIGGER_PCT = 0.08   # 激活: 盈利>8%
TRAIL_EXIT_PCT = 0.04       # 退出: 回撤4%
SCAN_INTERVAL = 3           # 扫描间隔（秒）
FIXED_STOP_PCT = 0.09      # 固定止损: 亏损>9%

class TrailingStop:
    def __init__(self, api_key, api_secret, passphrase, test_mode=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.test_mode = test_mode
        self.running = False
        self.positions_cache = {}
        
        # 读取配置
        self.config = self.load_config()
        
    def load_config(self):
        """加载配置"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {
            'trail_trigger_pct': TRAIL_TRIGGER_PCT,
            'trail_exit_pct': TRAIL_EXIT_PCT,
            'scan_interval': SCAN_INTERVAL,
            'fixed_stop_pct': FIXED_STOP_PCT
        }
    
    def save_config(self):
        """保存配置"""
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def sign(self, timestamp, method, path, body=''):
        """Bitget API 签名"""
        import hmac, base64
        message = f"{timestamp}{method}{path}{body}"
        mac = hmac.new(self.api_secret.encode('utf-8'), message.encode('utf-8'), digestmod='hashlib.sha256')
        return base64.b64encode(mac.digest()).decode()
    
    def api_request(self, method, path, body=None):
        """发送 API 请求"""
        import urllib.request, urllib.parse, urllib.error
        timestamp = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body else ''
        sign = self.sign(timestamp, method, path, body_str)

        base_url = 'https://api.bitget.com'
        headers = {
            'Content-Type': 'application/json',
            'ACCESS-KEY': self.api_key,
            'ACCESS-SIGN': sign,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': self.passphrase
        }

        try:
            req = urllib.request.Request(base_url + path, data=body_str.encode() if body_str else None, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            self.log(f"API请求失败: {e}")
            return None
    
    def log(self, msg):
        """写入日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line)
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    
    def get_positions(self):
        """获取所有持仓"""
        positions = []
        
        # 从交易所获取所有持仓
        pos_data = self.api_request('GET', '/api/v2/mix/position/all-position', 
            {'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
        
        if pos_data and 'data' in pos_data:
            for p in pos_data['data']:
                size = float(p.get('total', 0))
                if size > 0:
                    symbol = p.get('symbol', '')
                    direction = 'short' if p.get('holdSide') == 'short' else 'long'
                    ep = float(p.get('openPriceAvg', 0))
                    mark = float(p.get('markPrice', 0))
                    liq = float(p.get('liquidationPrice', 0))
                    margin = float(p.get('marginSize', 0))
                    leverage = int(p.get('leverage', 10))
                    unrealized = float(p.get('unrealizedPL', 0))
                    ct = int(p.get('cTime', 0))
                    
                    positions.append({
                        'symbol': symbol,
                        'direction': direction,
                        'size': size,
                        'entry_price': ep,
                        'mark_price': mark,
                        'liquidation_price': liq,
                        'margin': margin,
                        'leverage': leverage,
                        'unrealized': unrealized,
                        'open_time': ct
                    })
        
        return positions
    
    def get_ticker(self, symbol):
        """获取单个ticker"""
        data = self.api_request('GET', '/api/v2/mix/market/ticker',
            {'symbol': symbol, 'productType': 'USDT-FUTURES'})
        if data and 'data' in data and len(data['data']) > 0:
            return float(data['data'][0].get('lastPr', 0))
        return 0
    
    def get_all_tickers(self, symbols):
        """批量获取ticker（更高效）"""
        tickers = {}
        for symbol in symbols:
            tickers[symbol] = self.get_ticker(symbol)
        return tickers
    
    def load_local_positions(self):
        """从本地文件加载持仓峰值记录"""
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                return {p['symbol']: p for p in data.get('positions', [])}
        return {}
    
    def save_local_positions(self, positions_dict):
        """保存持仓峰值到本地文件"""
        positions_list = list(positions_dict.values())
        with open(POSITIONS_FILE, 'w') as f:
            json.dump({'positions': positions_list, 'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, f, indent=2, ensure_ascii=False)
    
    def calc_profit_pct(self, ep, mark, direction):
        """计算盈亏百分比"""
        if direction == 'short':
            return (ep - mark) / ep * 100
        else:
            return (mark - ep) / ep * 100
    
    def check_and_execute_trail(self, position, current_price):
        """检查并执行移动止盈"""
        symbol = position['symbol']
        ep = position['entry_price']
        size = position['size']
        direction = position['direction']
        ds = 1 if direction == 'long' else -1
        
        # 计算盈利
        pv = self.calc_profit_pct(ep, current_price, direction)
        
        # 获取或初始化峰值
        peak = position.get('peak_price', current_price)
        
        # 更新峰值（做空记录最低，做多记录最高）
        if direction == 'short' and current_price < peak:
            peak = current_price
        elif direction == 'long' and current_price > peak:
            peak = current_price
        
        # 激活检查
        trail_triggered = position.get('trail_triggered', False)
        trail_activated_price = position.get('trail_activated_price', None)
        
        trigger_pct = self.config['trail_trigger_pct']
        exit_pct = self.config['trail_exit_pct']
        fixed_stop_pct = self.config['fixed_stop_pct']
        
        actions = []
        
        # 固定止损检查
        if pv <= -fixed_stop_pct * 100:
            actions.append(('FIXED_STOP', pv, current_price))
        
        # 激活移动止盈
        if not trail_triggered and pv >= trigger_pct * 100:
            trail_triggered = True
            trail_activated_price = peak
            actions.append(('TRAIL_ACTIVATED', pv, peak))
        
        # 检查退出条件（已激活）
        if trail_triggered and trail_activated_price:
            if direction == 'short':
                # 做空回撤: (当前价 - 峰值) / 峰值
                drawdown = (current_price - trail_activated_price) / trail_activated_price * 100
            else:
                # 做多回撤: (峰值 - 当前价) / 峰值
                drawdown = (trail_activated_price - current_price) / trail_activated_price * 100
            
            if drawdown >= exit_pct * 100:
                actions.append(('TRAIL_EXIT', pv, current_price, drawdown, trail_activated_price))
        
        return actions, peak, trail_triggered, trail_activated_price
    
    def close_position(self, symbol, direction, size):
        """市价平仓"""
        if self.test_mode:
            self.log(f"[TEST] 平仓 {symbol} {direction} {size}")
            return True
        
        side = 'sell' if direction == 'short' else 'buy'
        body = {
            'symbol': symbol,
            'productType': 'USDT-FUTURES',
            'marginCoin': 'USDT',
            'side': side,
            'orderType': 'market',
            'size': str(size),
            'tradeSide': 'close'
        }
        
        result = self.api_request('POST', '/api/v2/mix/order/place-order', body)
        
        if result and result.get('code') == '0':
            self.log(f"✅ 平仓成功: {symbol} @ {side}")
            return True
        else:
            self.log(f"❌ 平仓失败: {symbol} - {result}")
            return False
    
    def monitor_loop(self):
        """主监控循环"""
        self.log("=" * 50)
        self.log("移动止盈监控启动")
        self.log(f"触发: >{self.config['trail_trigger_pct']*100:.0f}% | 退出: {self.config['trail_exit_pct']*100:.0f}%回撤")
        self.log("=" * 50)
        
        # 加载本地峰值记录
        local_positions = self.load_local_positions()
        
        while self.running:
            try:
                # 获取所有持仓
                positions = self.get_positions()
                
                if not positions:
                    self.log("[监测] 无持仓，等待中...")
                    time.sleep(self.config['scan_interval'])
                    continue
                
                # 获取所有ticker
                symbols = [p['symbol'] for p in positions]
                tickers = self.get_all_tickers(symbols)
                
                results = []
                positions_to_remove = []
                
                for pos in positions:
                    symbol = pos['symbol']
                    cp = tickers.get(symbol, 0)
                    
                    if cp == 0:
                        continue
                    
                    # 合并本地峰值记录
                    local = local_positions.get(symbol, {})
                    pos_with_peak = {**pos, **local}
                    
                    # 检查移动止盈
                    actions, peak, trail_triggered, trail_activated_price = self.check_and_execute_trail(pos_with_peak, cp)
                    
                    # 更新本地峰值
                    local_positions[symbol] = {
                        'symbol': symbol,
                        'direction': pos['direction'],
                        'size': pos['size'],
                        'entry_price': pos['entry_price'],
                        'peak_price': peak,
                        'trail_triggered': trail_triggered,
                        'trail_activated_price': trail_activated_price,
                        'open_time': pos.get('open_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    }
                    
                    # 执行动作
                    for action in actions:
                        action_type = action[0]
                        
                        if action_type == 'FIXED_STOP':
                            pv, price = action[1], action[2]
                            self.log(f"🛑 固定止损触发: {symbol} 亏损{pv:.2f}% 平仓价${price:.5f}")
                            if self.close_position(symbol, pos['direction'], pos['size']):
                                positions_to_remove.append(symbol)
                        
                        elif action_type == 'TRAIL_ACTIVATED':
                            pv, price = action[1], action[2]
                            self.log(f"📍 移动止盈激活: {symbol} 盈利{pv:.2f}% 峰值${price:.5f}")
                        
                        elif action_type == 'TRAIL_EXIT':
                            pv, price, drawdown, trail_price = action[1], action[2], action[3], action[4]
                            self.log(f"🟥 移动止盈平仓: {symbol} 平仓价${price:.5f} 回撤{drawdown:.2f}%")
                            if self.close_position(symbol, pos['direction'], pos['size']):
                                positions_to_remove.append(symbol)
                
                # 移除已平仓的记录
                for symbol in positions_to_remove:
                    if symbol in local_positions:
                        del local_positions[symbol]
                
                # 保存本地记录
                self.save_local_positions(local_positions)
                
                # 输出状态
                if positions:
                    status = f"[监测] {len(positions)}个持仓 | "
                    for pos in positions:
                        cp = tickers.get(pos['symbol'], 0)
                        pv = self.calc_profit_pct(pos['entry_price'], cp, pos['direction'])
                        local = local_positions.get(pos['symbol'], {})
                        trail = '✅' if local.get('trail_triggered') else '⏳'
                        results.append(f"{pos['symbol']}:{pv:+.1f}%{trail}")
                    self.log(status + " | ".join(results))
                
                time.sleep(self.config['scan_interval'])
                
            except Exception as e:
                self.log(f"监控异常: {e}")
                time.sleep(5)
        
        self.log("移动止盈监控已停止")
    
    def start(self):
        """启动监控"""
        # 检查是否已在运行
        if self.is_running():
            self.log("监控已在运行中")
            return False
        
        self.running = True
        
        # 写入PID
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        
        # 忽略SIGHUP，在后台运行
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        
        # 创建新的会话
        try:
            os.setsid()
        except:
            pass
        
        # 重定向输出
        sys.stdout.flush()
        sys.stderr.flush()
        
        # 启动监控循环
        self.monitor_loop()
    
    def stop(self):
        """停止监控"""
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
                self.log("已发送停止信号")
            except:
                pass
            os.remove(PID_FILE)
        self.running = False
    
    def is_running(self):
        """检查是否在运行"""
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                return True
            except:
                os.remove(PID_FILE)
                return False
        return False
    
    def status(self):
        """查看状态"""
        if self.is_running():
            with open(PID_FILE, 'r') as f:
                pid = f.read().strip()
            self.log(f"✅ 移动止盈监控运行中 (PID: {pid})")
        else:
            self.log("❌ 移动止盈监控未运行")
        
        # 显示本地记录
        local = self.load_local_positions()
        if local:
            self.log(f"\n本地峰值记录 ({len(local)}个):")
            for sym, pos in local.items():
                trail = '✅' if pos.get('trail_triggered') else '⏳'
                peak = pos.get('peak_price', 0)
                trigger = pos.get('trail_activated_price')
                ep = pos.get('entry_price', 0)
                direction = pos.get('direction', '')
                
                if trigger:
                    exit_line = trigger * (1 - TRAIL_EXIT_PCT) if direction == 'short' else trigger * (1 + TRAIL_EXIT_PCT)
                    self.log(f"  {sym}: peak=${peak:.5f} trigger=${trigger:.5f} exit=${exit_line:.5f} {trail}")
                else:
                    self.log(f"  {sym}: peak=${peak:.5f} 未激活 {trail}")
        else:
            self.log("\n无本地峰值记录")


def main():
    # 加载API配置（与 futures_scanner.py 共用）
    config_file = f'{WORKSPACE}/config.json'
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            cfg = json.load(f)
        api_key = cfg.get('api_key', '')
        api_secret = cfg.get('api_secret', '')
        passphrase = cfg.get('passphrase', '')
    else:
        # 尝试从 futures_scanner.py 提取（向后兼容）
        api_key = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
        api_secret = '55d7ddd792c3ebab233b4a6911f95f99753d7f5b8ad92c34f8bfb78f5f7db5b6'
        passphrase = 'liugang123'
    
    # 创建实例
    trailing = TrailingStop(api_key, api_secret, passphrase, test_mode=False)
    
    # 解析命令
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == '--start':
        # 清除日志文件（每次启动重新开始）
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
        trailing.start()
    
    elif command == '--stop':
        trailing.stop()
    
    elif command == '--status':
        trailing.status()
    
    elif command == '--test':
        # 测试模式
        trailing.test_mode = True
        print("=== 测试模式 ===")
        print(f"触发: >{TRAIL_TRIGGER_PCT*100:.0f}% | 退出: {TRAIL_EXIT_PCT*100:.0f}%回撤")
        print(f"间隔: {SCAN_INTERVAL}秒")
        
        # 获取持仓
        positions = trailing.get_positions()
        print(f"\n当前持仓: {len(positions)}个")
        for pos in positions:
            print(f"  {pos['symbol']}: {pos['direction']} {pos['size']}个 @ ${pos['entry_price']:.5f}")
    
    elif command == '--set':
        # 设置参数
        if len(sys.argv) >= 4:
            key = sys.argv[2]
            value = float(sys.argv[3])
            
            if key == 'trigger':
                trailing.config['trail_trigger_pct'] = value
            elif key == 'exit':
                trailing.config['trail_exit_pct'] = value
            elif key == 'interval':
                trailing.config['scan_interval'] = int(value)
            
            trailing.save_config()
            print(f"已设置 {key} = {value}")
        else:
            print("用法: --set trigger 0.08")
    
    else:
        print(__doc__)


if __name__ == '__main__':
    main()