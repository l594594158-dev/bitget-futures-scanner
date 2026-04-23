#!/usr/bin/env python3
"""
移动止盈脚本 v2
- 数据库: db_trailing_positions.json (与futures_trader分离)
- 扫描间隔: 5秒
- 移动止盈: 盈利>8%激活，峰值回撤4%止盈
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
DB_FILE = f'{WORKSPACE}/db_trailing_positions.json'
DB_COOLDOWN = f'{WORKSPACE}/db_positions_v2.json'  # 与futures_trader共用冷却文件
PID_FILE = f'{WORKSPACE}/trailing_stop_v2.pid'
LOG_FILE = f'{WORKSPACE}/trailing_stop_v2.log'

# API配置（注意：API_KEY以bg_开头，API_SECRET是hex字符串）
API_KEY = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
API_SECRET = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
API_PASSPHRASE = 'liugang123'
BASE_URL = 'https://api.bitget.com'

# 交易参数
TRAIL_TRIGGER_PCT = 0.05    # 盈利>5%激活
TRAIL_EXIT_PCT = 0.03       # 距离峰值3%止盈
# 固定止损已删除
SCAN_INTERVAL = 5            # 扫描间隔5秒
SYNC_INTERVAL = 30           # 从db_positions.json同步间隔30秒
PRODUCT_TYPE = 'USDT-FUTURES'

# ========== API工具 ==========
def sign(message: str, secret: str) -> str:
    mac = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode('utf-8')

def api_request(method: str, path: str, params=None, body=None, retries=3, retry_delay=2):
    """
    统一API请求，修复签名路径问题。
    Bitget API 签名规则：GET请求先用path-only签名，失败则用path+query重试
    """
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    
    # 构建 query string（用于URL，不用于签名）
    query = ""
    if params:
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    
    # 构建完整URL
    url = BASE_URL + path
    if query:
        url += "?" + query
    
    for attempt in range(retries):
        try:
            # 首先尝试 path-only 签名
            sign_str = timestamp + method.upper() + path + body_str
            signature = sign(sign_str, API_SECRET)
            
            headers = {
                'ACCESS-KEY': API_KEY,
                'ACCESS-SIGN': signature,
                'ACCESS-TIMESTAMP': timestamp,
                'ACCESS-PASSPHRASE': API_PASSPHRASE,
                'Content-Type': 'application/json'
            }
            
            if method == 'GET':
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                resp = requests.post(url, headers=headers, data=body_str, timeout=10)
            elif method == 'DELETE':
                resp = requests.delete(url, headers=headers, data=body_str, timeout=10)
            else:
                return None
            
            data = resp.json()
            code = data.get('code')
            
            # 40037是间歇性API错误，重试
            if code == '40037' and attempt < retries - 1:
                logger(f"API 40037错误，重试({attempt+1}/{retries})...")
                time.sleep(retry_delay)
                continue
            
            # 40009是签名错误，尝试 path+query 签名重试
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
                continue
            logger(f"API异常: {e}")
            return None
    return None

# ========== 日志 ==========
def logger(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{ts}] {msg}"
    print(log_line)
    with open(LOG_FILE, 'a') as f:
        f.write(log_line + '\n')

# ========== 数据库操作 ==========
def load_db():
    """加载数据库2"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {'positions': {}, 'last_updated': None}

def save_db(db: dict):
    """保存数据库2"""
    db['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

COOLDOWN_SEC = 900  # 平仓后冷却900秒（15分钟）

def _load_cooldown_db():
    """加载含冷却的共享数据库（与futures_trader共用db_positions_v2.json）"""
    if os.path.exists(DB_COOLDOWN):
        with open(DB_COOLDOWN, 'r') as f:
            return json.load(f)
    return {'positions': {}, 'cooldowns': {}, 'last_updated': ''}

def _save_cooldown_db(db):
    """保存含冷却的共享数据库"""
    db['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(DB_COOLDOWN, 'w') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def add_cooldown(symbol: str, reason: str, entry_price: float, exit_price: float, pnl: float):
    """添加冷却记录（写入共享数据库，与futures_trader共用）"""
    db = _load_cooldown_db()
    now = time.time()
    if 'cooldowns' not in db:
        db['cooldowns'] = {}
    db['cooldowns'][symbol] = {
        'closed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'timestamp': now,
        'reason': reason,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl': pnl
    }
    _save_cooldown_db(db)
    logger(f"🔒 {symbol} 进入冷却：{reason}，{COOLDOWN_SEC}秒后清除")

def get_active_cooldowns():
    """获取仍在冷却中的代币"""
    db = _load_cooldown_db()
    cooldowns = db.get('cooldowns', {})
    now = time.time()
    active = {}
    for sym, info in list(cooldowns.items()):
        elapsed = now - info['timestamp']
        if elapsed < COOLDOWN_SEC:
            remaining = COOLDOWN_SEC - elapsed
            active[sym] = remaining
        else:
            del cooldowns[sym]
            logger(f"🔓 {sym} 冷却结束，已清除")
    db['cooldowns'] = cooldowns
    _save_cooldown_db(db)
    return active

def init_db():
    """初始化数据库2"""
    db = load_db()
    if 'positions' not in db:
        db['positions'] = {}
    if 'last_updated' not in db:
        db['last_updated'] = None
    save_db(db)
    return db

# ========== 从db_positions.json同步峰值价格（仅补充已有持仓，不添加新记录） ==========
def sync_from_db2():
    """每30秒：从db_positions.json同步峰值价格，仅补充API已有持仓，不添加幽灵记录"""
    DB2_SRC = f'{WORKSPACE}/db_positions.json'
    if not os.path.exists(DB2_SRC):
        return

    try:
        with open(DB2_SRC, 'r') as f:
            src = json.load(f)
        src_positions = src.get('positions', [])
        if not src_positions:
            return

        db = load_db()
        db_syms = set(db['positions'].keys())

        synced = 0
        for pos in src_positions:
            sym = pos.get('symbol', '')
            direction = pos.get('direction', '')
            key = f"{sym}_{direction}"
            if key in db_syms:
                # 只同步峰值价格，不添加新记录
                if pos.get('peak_price'):
                    db['positions'][key]['peak_price'] = float(pos['peak_price'])
                    synced += 1

        if synced > 0:
            save_db(db)
            logger(f"🔄 同步峰值: {synced}个")
    except Exception as e:
        logger(f"⚠️ 同步异常: {e}")

# ========== 获取持仓 ==========
def get_all_positions():
    """获取所有持仓（带重试和降级）"""
    # 首先尝试 all-position
    pos_data = api_request('GET', '/api/v2/mix/position/all-position', 
        {'productType': PRODUCT_TYPE, 'marginCoin': 'USDT'}, retries=3, retry_delay=2)
    
    positions = []
    
    if pos_data:
        # 检查是否API错误响应（code存在但不是成功码）
        if isinstance(pos_data, dict) and 'code' in pos_data:
            code = pos_data.get('code')
            if code != '00000' and code != '0':
                # API返回错误，使用缓存
                pos_data = None
        
        if pos_data:
            # 兼容 list 和 dict{'data':list} 两种返回格式
            if isinstance(pos_data, list):
                positions = [p for p in pos_data if float(p.get('total', 0)) > 0]
            elif isinstance(pos_data, dict) and 'data' in pos_data:
                data_field = pos_data.get('data')
                if isinstance(data_field, list):
                    positions = [p for p in data_field if float(p.get('total', 0)) > 0]
        
        logger(f"📡 API持仓: {len(positions)}个")
    else:
        # all-position 失败，尝试从数据库缓存获取上次成功数据
        db = load_db()
        if db['positions']:
            logger(f"all-position API失败，使用缓存的 {len(db['positions'])} 个持仓")
            for sym, info in db['positions'].items():
                # 清理symbol：去掉末尾的 _long 或 _short（防止脏数据累积）
                base_symbol = sym.rsplit('_long', 1)[0].rsplit('_short', 1)[0]
                positions.append({
                    'symbol': base_symbol if base_symbol else sym,
                    'total': str(info.get('size', 0)),
                    'holdSide': info.get('direction', 'long'),
                    'openPriceAvg': str(info.get('entry_price', 0)),
                    'markPrice': str(info.get('current_price', 0)),
                    'liquidationPrice': str(info.get('liquidation_price', 0)),
                    'unrealizedPL': str(info.get('unrealized_pl', 0)),
                    'leverage': str(info.get('leverage', 10)),
                    'marginSize': str(info.get('margin', 0)),
                    'cTime': '0'
                })
    
    return positions

def get_ticker(symbol: str) -> dict:
    """获取单个币种行情"""
    ticker = api_request('GET', '/api/v2/mix/market/ticker',
        {'symbol': symbol, 'productType': PRODUCT_TYPE})
    if ticker and isinstance(ticker, list):
        return ticker[0]
    return ticker or {}

# ========== 止盈止损逻辑 ==========
def calculate_pnl(direction: str, entry_price: float, current_price: float) -> float:
    """计算盈亏百分比"""
    if direction == 'short':
        return (entry_price - current_price) / entry_price * 100
    else:  # long
        return (current_price - entry_price) / entry_price * 100

def should_trail_exit(direction: str, entry_price: float, current_price: float, 
                       peak_price: float, trail_triggered: bool) -> tuple:
    """
    判断是否触发移动止盈
    返回: (是否触发, 触发原因)
    """
    if not trail_triggered:
        return False, None
    
    pnl = calculate_pnl(direction, entry_price, current_price)
    
    # 移动止盈激活后，从峰值回撤4%退出
    if direction == 'short':
        # 做空：peak是最低价，回撤=(当前价-峰值)/峰值
        drawdown_pct = (current_price - peak_price) / peak_price * 100
        if drawdown_pct >= TRAIL_EXIT_PCT * 100:
            return True, f'移动止盈回撤({drawdown_pct:.2f}%≥4%)'
    else:  # long
        # 做多：peak是最高价，回撤=(峰值-当前价)/峰值
        drawdown_pct = (peak_price - current_price) / peak_price * 100
        if drawdown_pct >= TRAIL_EXIT_PCT * 100:
            return True, f'移动止盈回撤({drawdown_pct:.2f}%≥4%)'
    
    return False, None

def calculate_exit_price(direction: str, peak_price: float) -> float:
    """计算移动止盈平仓价格"""
    if direction == 'short':
        # 做空：exit = peak × 1.04（价格涨到峰值4%时卖出）
        return peak_price * (1 + TRAIL_EXIT_PCT)
    else:  # long
        # 做多：exit = peak × 0.96（价格跌到峰值4%时卖出）
        return peak_price * (1 - TRAIL_EXIT_PCT)

def should_activate_trail(pnl: float) -> bool:
    """判断是否激活移动止盈"""
    return pnl >= TRAIL_TRIGGER_PCT * 100

# ========== 平仓 ==========
def close_position(symbol: str, direction: str, size: float) -> bool:
    """市价平仓（hedge模式）"""
    # 平仓：side和开仓相反，但posSide/direction保持一致
    # 平多仓：side=buy, posSide=long
    # 平空仓：side=sell, posSide=short
    if direction == 'long':
        side = 'buy'
        pos_side = 'long'
    else:
        side = 'sell'
        pos_side = 'short'
    
    body = {
        'symbol': symbol,
        'productType': PRODUCT_TYPE,
        'marginCoin': 'USDT',
        'marginMode': 'isolated',
        'side': side,
        'posSide': pos_side,
        'tradeSide': 'close',
        'orderType': 'market',
        'size': str(int(size))
    }
    
    result = api_request('POST', '/api/v2/mix/order/place-order', body=body)
    # 有orderId即表示交易所已接受订单（平仓成功）
    # 部分响应有code=00000，部分只有orderId无code，都算成功
    if result and (result.get('code') in ('00000', '0') or 'orderId' in result):
        logger(f"✅ {symbol} 平仓成功: {side} {size}")
        return True
    else:
        logger(f"❌ {symbol} 平仓失败: {result}")
        return False

# ========== 主监控循环 ==========
def monitor_loop():
    """主监控循环"""
    logger("=" * 50)
    logger("移动止盈v2启动")
    logger(f"参数: 激活>{TRAIL_TRIGGER_PCT*100}% | 回撤>{TRAIL_EXIT_PCT*100}% 间隔{SCAN_INTERVAL}秒")
    logger("=" * 50)
    
    db = init_db()
    
    sync_counter = 0  # 0=立即同步
    while True:
        try:
            # 每SYNC_INTERVAL秒从db_positions.json同步一次
            if sync_counter <= 0:
                sync_from_db2()
                sync_counter = SYNC_INTERVAL // SCAN_INTERVAL
            sync_counter -= 1
            # 1. 获取所有持仓
            positions = get_all_positions()
            active_symbols = set()
            
            for p in positions:
                symbol = p.get('symbol', '')
                size = float(p.get('total', 0))
                if size <= 0:
                    continue
                
                direction = 'short' if p.get('holdSide') == 'short' else 'long'
                active_symbols.add(f"{symbol}_{direction}")
                side = 'sell' if direction == 'short' else 'buy'
                entry_price = float(p.get('openPriceAvg', 0))
                mark_price = float(p.get('markPrice', 0))
                liquidation_price = float(p.get('liquidationPrice', 0))
                unrealized_pl = float(p.get('unrealizedPL', 0))
                leverage = int(p.get('leverage', 10))
                
                if entry_price <= 0:
                    continue
                
                # 2. 获取当前行情
                ticker = get_ticker(symbol)
                current_price = float(ticker.get('lastPr', mark_price))
                
                # 3. 计算盈亏
                pnl = calculate_pnl(direction, entry_price, current_price)
                
                # 获取历史峰值（用symbol_direction作为key）
                pos_key = f"{symbol}_{direction}"
                pos_info = db['positions'].get(pos_key, {})
                
                # 获取历史峰值
                peak_price = pos_info.get('peak_price', current_price if direction == 'long' else current_price)
                trail_triggered = pos_info.get('trail_triggered', False)
                trail_activated_price = pos_info.get('trail_activated_price')
                
                # 更新峰值：做多记录最高，做空记录最低
                if direction == 'long':
                    if current_price > peak_price:
                        peak_price = current_price
                        logger(f"📈 {symbol} 新峰值: ${peak_price:.6f}")
                else:  # short
                    if current_price < peak_price:
                        peak_price = current_price
                        logger(f"📉 {symbol} 新峰值: ${peak_price:.6f}")
                
                # 5. 检查是否激活移动止盈
                if not trail_triggered and should_activate_trail(pnl):
                    trail_triggered = True
                    trail_activated_price = peak_price
                    logger(f"🚀 {symbol} 移动止盈激活! 盈利{pnl:.2f}% 峰值=${peak_price:.6f}")
                
                # 6. 检查是否触发止盈
                exit_reason = None
                exit_price = None
                should_exit, exit_reason = should_trail_exit(direction, entry_price, current_price, 
                                                            peak_price, trail_triggered)
                
                if should_exit:
                    exit_price = calculate_exit_price(direction, peak_price)
                    logger(f"🎯 {symbol} 触发{exit_reason}")
                    logger(f"   开仓${entry_price:.6f} 当前${current_price:.6f} 峰值${peak_price:.6f} 退出${exit_price:.6f}")
                    
                    # 执行平仓
                    close_ok = close_position(symbol, direction, size)
                    
                    # 计算平仓盈亏（无论成功失败都算，用于记录）
                    if direction == 'long':
                        realized_pnl = (exit_price - entry_price) / entry_price * 100
                    else:
                        realized_pnl = (entry_price - exit_price) / entry_price * 100
                    
                    # 添加冷却记录（平仓成功/失败/爆仓 都要冷却600秒）
                    add_cooldown(symbol, exit_reason, entry_price, exit_price, realized_pnl)
                    
                    if close_ok:
                        # 平仓成功：清除本地记录
                        db = load_db()
                        pos_key = f"{symbol}_{direction}"
                        if pos_key in db['positions']:
                            del db['positions'][pos_key]
                            save_db(db)
                            logger(f"🗑️ {symbol} 记录已清空")
                        continue
                    else:
                        # 平仓失败：保留记录，下个循环重试。不在这里重复add_cooldown（上面已加）
                        logger(f"⚠️ {symbol} 平仓失败，已进入冷却，下轮重试")
                        continue
                
                # 7. 写入数据库（key用symbol_direction区分多空）
                db = load_db()
                pos_key = f"{symbol}_{direction}"
                db['positions'][pos_key] = {
                    'symbol': symbol,
                    'direction': direction,
                    'side': side,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'size': size,
                    'leverage': leverage,
                    'peak_price': peak_price,
                    'trail_triggered': trail_triggered,
                    'trail_activated_price': trail_activated_price,
                    'pnl': pnl,
                    'unrealized_pl': unrealized_pl,
                    'liquidation_price': liquidation_price,
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                save_db(db)
            
            # 8. 清理已平仓/爆仓的记录（API已无此持仓）
            db = load_db()
            db_symbols = set(db['positions'].keys())
            closed_symbols = db_symbols - active_symbols
            if closed_symbols:
                for pos_key in closed_symbols:
                    sym = pos_key.rsplit('_', 1)[0]
                    # 从记录中获取成本/出场价，用于cooldown记录
                    info = db['positions'].get(pos_key, {})
                    entry_p = info.get('entry_price', 0)
                    exit_p = info.get('current_price', 0)
                    pnl_pct = info.get('pnl', 0)
                    direction = info.get('direction', 'long')
                    if direction == 'long':
                        realized = (exit_p - entry_p) / entry_p * 100 if entry_p else 0
                    else:
                        realized = (entry_p - exit_p) / entry_p * 100 if entry_p else 0
                    # 爆仓/被平：写入冷却记录
                    add_cooldown(sym, '爆仓/被平', entry_p, exit_p, realized)
                    logger(f"🗑️ {sym} 已平仓/爆仓，清除记录（冷却600秒）")
                    del db['positions'][pos_key]
                save_db(db)
            
            # 9. 打印状态
            db = load_db()
            if db['positions']:
                status = []
                for sym, info in db['positions'].items():
                    trail = '✅' if info['trail_triggered'] else '⏳'
                    status.append(f"{sym}: {trail}{info['pnl']:+.2f}%")
                logger(f"监控中: {len(db['positions'])}个 | {' | '.join(status)}")
            else:
                logger(f"监控中: 0个 (无持仓)")
            
        except Exception as e:
            logger(f"监控异常: {e}")
        
        time.sleep(SCAN_INTERVAL)

# ========== 启动/停止 ==========
def write_pid():
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def read_pid():
    if os.path.exists(PID_FILE):
        with open(PID_FILE, 'r') as f:
            return int(f.read().strip())
    return None

def is_running():
    pid = read_pid()
    if pid and os.path.exists(f'/proc/{pid}'):
        return pid
    return None

def start():
    """启动"""
    pid = is_running()
    if pid:
        print(f"已运行，PID: {pid}")
        return
    
    # 清空旧日志
    with open(LOG_FILE, 'w') as f:
        f.write('')
    
    pid = os.fork()
    if pid == 0:
        # 子进程
        os.setsid()
        sys.stdout.flush()
        sys.stderr.flush()
        write_pid()
        monitor_loop()
    else:
        print(f"启动成功，PID: {pid}")

def stop():
    """停止"""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, 9)
            print(f"已停止 PID: {pid}")
        except:
            print(f"进程不存在")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    else:
        print("未运行")

def status():
    """状态"""
    pid = is_running()
    if pid:
        print(f"运行中，PID: {pid}")
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                if lines:
                    print("最近日志:")
                    for line in lines[-5:]:
                        print(line.rstrip())
    else:
        print("未运行")

def log():
    """日志"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            print(f.read())
    else:
        print("无日志")

def db_show():
    """显示数据库"""
    db = load_db()
    print(json.dumps(db, indent=2, ensure_ascii=False))

# ========== 主程序 ==========
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='移动止盈v2')
    parser.add_argument('action', choices=['start', 'stop', 'status', 'log', 'db', 'restart'],
                       help='start|stop|status|log|db|restart')
    args = parser.parse_args()
    
    if args.action == 'start':
        start()
    elif args.action == 'stop':
        stop()
    elif args.action == 'status':
        status()
    elif args.action == 'log':
        log()
    elif args.action == 'db':
        db_show()
    elif args.action == 'restart':
        stop()
        time.sleep(1)
        start()
