#!/usr/bin/env python3
"""
24/7 全天候美股自动交易脚本
- 每5分钟扫描一次市场
- 评分最优 + 价位合适(30-75%) + 24h涨幅 > 0.5% → 买入信号
- 每个标的最多买1次/天，避免重复追高
- 每次买入上限10U，余额<10U停止
"""
import sys
import os
import json
import time
import fcntl
from datetime import datetime
sys.path.insert(0, '/root/.openclaw/workspace')
from bitget_trading_bot import Config, BitgetAPI

LOCK_FILE = '/tmp/trading_bot.lock'
LOG_FILE = '/root/.openclaw/workspace/trading_log.txt'
STATE_FILE = '/root/.openclaw/workspace/trading_state.json'
BUY_COOLDOWN_HOURS = 6   # 同一标的最低买入间隔

# ============ 重点关注标的 ============
TARGET_SYMBOLS = [
    ('NVDAONUSDT', 'NVDA', 'A+高波动'),
    ('AMDONUSDT', 'AMD', 'A成长'),
    ('AMZNONUSDT', 'AMZN', 'B/C蓝筹'),
    ('METAONUSDT', 'META', 'B/C蓝筹'),
    ('AAPLONUSDT', 'AAPL', 'B/C蓝筹'),
    ('GOOGLONUSDT', 'GOOGL', 'B/C蓝筹'),
    ('TSLAONUSDT', 'TSLA', 'A+高波动'),
    ('MSFTONUSDT', 'MSFT', 'B/C蓝筹'),
    ('QQQONUSDT', 'QQQ', '指数ETF'),
    ('SPYONUSDT', 'SPY', '指数ETF'),
]

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {'last_buy': {}, 'daily_buys': {}}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def is_cooldown(symbol, state):
    """检查标的是否在冷却期"""
    today = datetime.now().strftime('%Y-%m-%d')
    last = state['last_buy'].get(symbol, {})

    # 每天重置
    if last.get('date') != today:
        return False

    elapsed = (datetime.now() - datetime.fromisoformat(last['time'])).total_seconds() / 3600
    return elapsed < BUY_COOLDOWN_HOURS

def scan_and_score(api):
    """扫描市场并评分，返回排序结果"""
    api._refresh_ticker_cache()
    results = []

    for sym, name, cat in TARGET_SYMBOLS:
        t = api._ticker_cache.get(sym, {})
        price = float(t.get('lastPr', '0') or '0')
        if price <= 0:
            continue

        change = float(t.get('changeUtc24h', '0') or '0') * 100
        high = float(t.get('high24h', '0') or '0')
        low = float(t.get('low24h', '0') or '0')

        if high > low:
            range_pct = (price - low) / (high - low) * 100
        else:
            range_pct = 50

        # 评分：涨幅权重高 + 价位合适
        position_score = 100 - abs(range_pct - 55)
        score = change * 2 + position_score / 10

        results.append({
            'symbol': sym,
            'name': name,
            'cat': cat,
            'price': price,
            'change': change,
            'range_pct': range_pct,
            'score': score,
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results

def get_balance(api):
    try:
        assets = api._request("GET", "/api/v2/spot/account/assets")
        for a in assets:
            if a.get("coin") == "USDT":
                return float(a.get("available", "0"))
    except:
        pass
    return 0

def market_buy(api, symbol, usdt_amount):
    return api.place_order(
        symbol=symbol,
        side="buy",
        order_type="market",
        size=str(usdt_amount)
    )

def is_trading_window():
    """检查是否在交易时段：每天20:00 到 次日10:00（北京时间）"""
    now = datetime.now()
    hour = now.hour
    # 20:00-23:59 → 在窗口
    # 00:00-10:00 → 在窗口
    return hour >= 20 or hour < 10

def try_buy(api, state):
    """评估是否触发买入，返回(是否买入, 原因)"""
    if not is_trading_window():
        return False, f"非交易时段(20:00-10:00)"

    balance = get_balance(api)
    if balance < 10:
        return False, f"余额不足 {balance:.2f}U"

    results = scan_and_score(api)
    if not results:
        return False, "无市场数据"

    # 打印扫描结果（仅前3）
    top3 = results[:3]
    log(f"扫描: {[(r['name'], f"{r['change']:+.2f}%", f"{r['range_pct']:.0f}%", f"{r['score']:.1f}") for r in top3]}")

    # 筛选买入条件：
    # 1. 价位30-75%
    # 2. 24h涨幅 > 0.5%
    # 3. 不在冷却期
    candidates = [r for r in results
                  if 30 <= r['range_pct'] <= 75
                  and r['change'] > 0.5
                  and not is_cooldown(r['symbol'], state)]

    if not candidates:
        best = results[0]
        reason = f"最优:{best['name']} {best['change']:+.2f}% 价位{best['range_pct']:.0f}%"
        if best['change'] <= 0.5:
            reason += " (涨幅<0.5%)"
        elif best['range_pct'] > 75 or best['range_pct'] < 30:
            reason += " (价位不合适)"
        elif is_cooldown(best['symbol'], state):
            reason += " (冷却中)"
        return False, reason

    best = candidates[0]
    buy_amount = min(10.0, balance * 0.95)

    log(f"✅ 买入信号: {best['name']} {best['change']:+.2f}% 价位{best['range_pct']:.0f}% 评分{best['score']:.1f}")

    result = market_buy(api, best['symbol'], buy_amount)
    order_id = result.get("orderId", "")

    if order_id:
        # 更新状态
        now = datetime.now()
        state['last_buy'][best['symbol']] = {'time': now.isoformat(), 'date': now.strftime('%Y-%m-%d'), 'price': best['price'], 'amount': buy_amount}
        save_state(state)

        log(f"🎉 买入成功: {best['name']} {buy_amount:.2f}U @ ${best['price']:.2f} 订单:{order_id}")
        return True, f"✅{best['name']} {buy_amount:.2f}U @{best['price']:.2f}"
    else:
        log(f"❌ 买入失败: {result}")
        return False, f"订单失败: {result.get('msg', '未知')}"

def main():
    # 争取锁文件，防止多实例
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("另一个实例正在运行，退出")
        sys.exit(0)

    log("=" * 50)
    log(f"🤖 启动全天候交易机器人 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log("=" * 50)

    config = Config()
    api = BitgetAPI(config)
    state = load_state()

    # 每日UTC0点重置冷却（归零）
    today = datetime.now().strftime('%Y-%m-%d')
    if state.get('reset_date') != today:
        state['last_buy'].clear()
        state['reset_date'] = today
        save_state(state)
        log("⏰ 新交易日，重置买入记录")

    if not is_trading_window():
        log(f"🌙 非交易时段（20:00-10:00），跳过")
        return

    bought, reason = try_buy(api, state)

    if not bought:
        log(f"⏳ 本次不买入 ({reason})")

    log(f"💰 余额: {get_balance(api):.2f} USDT")
    fcntl.flock(lock_fd, fcntl.LOCK_UN)

if __name__ == "__main__":
    main()