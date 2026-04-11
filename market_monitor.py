#!/usr/bin/env python3
"""
美股市场监控脚本
用法: python3 market_monitor.py [扫描|分析|报警]
"""
import sys, time
sys.path.insert(0, '/root/.openclaw/workspace')
from bitget_trading_bot import Config, BitgetAPI

def scan_market():
    config = Config()
    api = BitgetAPI(config)
    api._refresh_ticker_cache()
    price_map = {t['symbol']: t for t in api._ticker_cache.values()}

    ts = time.strftime('%Y-%m-%d %H:%M GMT+8')

    # 重点关注标的
    targets = [
        ('NVDAONUSDT','NVDA','A+高波动'),
        ('AMDONUSDT','AMD','A成长'),
        ('AMZNONUSDT','AMZN','B/C蓝筹'),
        ('METAONUSDT','META','B/C蓝筹'),
        ('AAPLONUSDT','AAPL','B/C蓝筹'),
        ('GOOGLONUSDT','GOOGL','B/C蓝筹'),
        ('TSLAONUSDT','TSLA','A+高波动'),
        ('MSFTONUSDT','MSFT','B/C蓝筹'),
        ('QQQONUSDT','QQQ','指数ETF'),
        ('SPYONUSDT','SPY','指数ETF'),
    ]

    results = []
    for sym, name, cat in targets:
        t = price_map.get(sym, {})
        price = float(t.get('lastPr','0') or '0')
        vol = float(t.get('usdtVolume','0') or '0')
        if price <= 0:
            continue
        change = float(t.get('changeUtc24h','0') or '0') * 100
        high = float(t.get('high24h','0') or '0')
        low = float(t.get('low24h','0') or '0')
        range_pct = (price - low) / (high - low) * 100 if high > low else 50
        
        results.append({
            'sym': sym, 'name': name, 'cat': cat,
            'price': price, 'change': change, 'high': high, 'low': low,
            'vol': vol, 'range_pct': range_pct
        })

    # 排序：涨幅大 + 价位适中(30-80%)优先
    scored = []
    for r in results:
        # 分数 = 涨幅*2 + 价位合适度
        position_score = 100 - abs(r['range_pct'] - 55)  # 55为中心最佳
        score = r['change'] * 2 + position_score / 10
        r['score'] = score
        scored.append(r)

    scored.sort(key=lambda x: x['score'], reverse=True)

    print(f'[{ts}] 美股监控 - 重点标的 {len(results)} 只')
    print('='*70)
    print(f'{"代码":<6} {"现价":<10} {"24h涨跌":<10} {"价位":<8} {"评级"}')
    print('-'*70)
    for r in scored:
        arrow = '▲' if r['change'] >= 0 else '▼'
        if r['range_pct'] >= 85:
            zone = '🔴高位'
        elif r['range_pct'] >= 60:
            zone = '🟡偏高'
        elif r['range_pct'] >= 30:
            zone = '🟢适中'
        else:
            zone = '🔵低位'
        print(f'{r["name"]:<6} {r["price"]:<10.2f} {arrow}{abs(r["change"]):.2f}%   {r["range_pct"]:.0f}%     {zone}')

    # 推荐买入标的（价位30-75%，涨幅前3）
    print()
    print('【可选买入标的】(价位30-75%区间)')
    buyable = [r for r in scored if 30 <= r['range_pct'] <= 75][:5]
    if buyable:
        for i, r in enumerate(buyable, 1):
            arrow = '▲' if r['change'] >= 0 else '▼'
            print(f'  {i}. {r["name"]:<6} {arrow}{r["change"]:.2f}% 价位={r["range_pct"]:.0f}% 评分={r["score"]:.1f}')
    else:
        print('  当前无合适买点（均高于75%或低于30%区间）')

    return scored

if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if action == 'scan':
        scan_market()
    elif action == 'analyze':
        scan_market()
