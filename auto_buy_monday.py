#!/usr/bin/env python3
"""
周一美股自动买入脚本
- 使用 Bitget 批量tickers接口（绕过K线限制）
- 按评分挑选最优标的（30-75%价位区间）
- 市价买入，微信推送结果
"""
import sys
import json
import time
sys.path.insert(0, '/root/.openclaw/workspace')
from bitget_trading_bot import Config, BitgetAPI

# ============ 重点关注标的（ON后缀 = Bitget美股合成标的） ============
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

def scan_and_score(api):
    """扫描市场并评分"""
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

        # 评分：涨幅*2 + 价位合适度/10
        position_score = 100 - abs(range_pct - 55)
        score = change * 2 + position_score / 10

        results.append({
            'symbol': sym,
            'name': name,
            'cat': cat,
            'price': price,
            'change': change,
            'high': high,
            'low': low,
            'range_pct': range_pct,
            'score': score,
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results

def market_buy(api, symbol: str, usdt_amount: float) -> dict:
    """市价买入"""
    return api.place_order(
        symbol=symbol,
        side="buy",
        order_type="market",
        size=str(usdt_amount)
    )

def get_balance(api) -> float:
    """获取USDT余额"""
    try:
        assets = api._request("GET", "/api/v2/spot/account/assets")
        # _request 已提取 data 字段，直接是列表
        for a in assets:
            if a.get("coin") == "USDT":
                return float(a.get("available", "0"))
    except:
        pass
    return 0

def main():
    from datetime import datetime

    print(f"\n{'='*55}")
    print(f"  🤖 周一美股自动买入 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    config = Config()
    api = BitgetAPI(config)

    # 1. 扫描市场
    print("📡 扫描市场...")
    results = scan_and_score(api)
    print(f"   有效数据: {len(results)} 个\n")

    # 2. 打印所有标的
    print(f"{'代码':<6} {'名称':<6} {'现价':>10} {'24h涨跌':>8} {'价位':>6} {'评分':>6} {'评级'}")
    print("-" * 65)
    for r in results:
        arrow = "▲" if r['change'] >= 0 else "▼"
        zone = "🔴高位" if r['range_pct'] >= 85 else "🟡偏高" if r['range_pct'] >= 60 else "🟢适中" if r['range_pct'] >= 30 else "🔵低位"
        print(f"{r['name']:<6} {r['name']:<6} {r['price']:>10.2f} {arrow}{abs(r['change']):>6.2f}% {r['range_pct']:>5.0f}% {r['score']:>6.1f} {zone}")

    # 3. 筛选最佳标的（价位30-75%）
    buyable = [r for r in results if 30 <= r['range_pct'] <= 75]
    if not buyable:
        print("\n❌ 没有符合条件的标的（价位需在30-75%区间）")
        sys.exit(0)

    best = buyable[0]
    print(f"\n🏆 最佳标的: {best['name']} ({best['symbol']})")
    print(f"   评分={best['score']:.1f} | 24h涨跌={best['change']:+.2f}% | 价位={best['range_pct']:.0f}%")

    # 4. 检查余额
    balance = get_balance(api)
    print(f"\n💰 USDT 余额: {balance:.2f}")

    if balance < 15:
        print("❌ 余额不足 (< 15 USDT)")
        sys.exit(1)

    # 5. 执行买入（15U）
    buy_amount = min(15.0, balance * 0.95)
    print(f"\n✅ 执行市价买入: {buy_amount:.2f} USDT × {best['symbol']}")

    result = market_buy(api, best['symbol'], buy_amount)
    print(f"\n📋 订单结果: {json.dumps(result, ensure_ascii=False)}")

    # 成功判断：有 orderId 即成功（Bitget place_order 返回格式无 code 包装）
    order_id = result.get("orderId", "")
    if order_id:
        print(f"\n🎉 买入成功！")
        print(f"   标的: {best['name']} ({best['symbol']}) @ ${best['price']:.2f}")
        print(f"   金额: {buy_amount:.2f} USDT")
        print(f"   订单号: {order_id}")
        msg = f"✅ 自动买入成功\n标的: {best['name']}\n金额: {buy_amount:.2f} USDT\n价格: ${best['price']:.2f}\n订单号: {order_id}"
    else:
        msg = f"❌ 买入失败\n信息: {result.get('msg', '未知')}"
        print(f"\n❌ 买入失败: {result}")

    # 6. 最终余额
    time.sleep(2)
    final = get_balance(api)
    print(f"\n💰 买入后余额: {final:.2f} USDT")

    return msg

if __name__ == "__main__":
    msg = main()
    print(f"\n{'='*55}")
    print(msg)
