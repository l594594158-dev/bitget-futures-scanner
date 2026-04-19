import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from eth_futures_trader import Config, BitgetFuturesAPI, CandleData, SignalAnalyzer

config = Config()
api = BitgetFuturesAPI(config)
candles = CandleData(api)
analyzer = SignalAnalyzer(candles)

print('正在加载K线数据...')
if not candles.refresh():
    print('FAIL: K线加载失败')
    sys.exit(1)

print('OK: 数据加载成功\n')

ind_5m = candles.compute_indicators('5m')
ind_1H = candles.compute_indicators('1H')
ind_4H = candles.compute_indicators('4H')
ind_1D = candles.compute_indicators('1D')

print('=== 当前市场状态 ===')
print('5m 价格: %.2f' % ind_5m['close'])
print('5m %b:   %.3f' % ind_5m['percent_b'])
print('5m RSI:  %.1f' % ind_5m['rsi'])
print('5m ADX:  %.1f' % ind_5m['adx'])
print('5m 放量:  %.2fx' % ind_5m['volume_ratio'])
print('5m MA7:  %.2f' % ind_5m['ma7'])
print('5m MACD: %.4f' % ind_5m['macd'])
print()
print('1H ADX:  %.1f' % ind_1H['adx'])
print('1H MA7:  %.2f  价格: %.2f' % (ind_1H['ma7'], ind_1H['close']))
print('1H MACD: %.4f' % ind_1H['macd'])
print()
print('4H ADX:  %.1f' % ind_4H['adx'])
print('4H MA7:  %.2f  价格: %.2f' % (ind_4H['ma7'], ind_4H['close']))
print('4H MACD: %.4f' % ind_4H['macd'])
print()
print('1D MA7:  %.2f  价格: %.2f' % (ind_1D['ma7'], ind_1D['close']))
print('1D MACD: %.4f' % ind_1D['macd'])

print()
print('=== 趋势判断 ===')
def is_bullish(ind):
    return ind['ma7'] < ind['close'] and ind['macd'] > 0
def is_bearish(ind):
    return ind['ma7'] > ind['close'] and ind['macd'] < 0
print('4H 多头: %s / 空头: %s' % (is_bullish(ind_4H), is_bearish(ind_4H)))
print('1D 多头: %s / 空头: %s' % (is_bullish(ind_1D), is_bearish(ind_1D)))
print()
print('=== 三层过滤 ===')
adx1h_pass = ind_1H['adx'] > 25
vol_pass = ind_5m['volume_ratio'] > 1.5
print('1h ADX>25?  %s  当前=%.1f' % ('OK' if adx1h_pass else 'FAIL', ind_1H['adx']))
print('放量>1.5x?   %s  当前=%.2fx' % ('OK' if vol_pass else 'FAIL', ind_5m['volume_ratio']))
if is_bearish(ind_4H) or is_bearish(ind_1D):
    adx4h_pass = ind_4H['adx'] < 40
    print('4h ADX<40?   %s  当前=%.1f' % ('OK' if adx4h_pass else 'FAIL', ind_4H['adx']))
else:
    print('顺势信号，不检查4h ADX<40')
print()

# 检查各信号条件
pct_b = ind_5m['percent_b']
rsi = ind_5m['rsi']
adx_5m = ind_5m['adx']
vol = ind_5m['volume_ratio']
adx_4h = ind_4H['adx']

print('=== 信号条件检查 ===')
print()
print('【做多A - 逆势抄底】4h空头+1d空头+4hADX<40+5m超卖:')
bull_bear_4h = is_bearish(ind_4H)
bull_bear_1d = is_bearish(ind_1D)
cond_adx4h = adx_4h < 40
cond_pctb = pct_b < 0.2
cond_rsi = rsi < 40
cond_adx5m = adx_5m > 25
cond_vol = vol > 1.5
print('  4h空头: %s' % bull_bear_4h)
print('  1d空头: %s' % bull_bear_1d)
print('  4hADX<40: %s' % cond_adx4h)
print('  %b<0.2: %s' % cond_pctb)
print('  RSI<40: %s' % cond_rsi)
print('  5mADX>25: %s' % cond_adx5m)
print('  放量>1.5x: %s' % cond_vol)
print('  -> %s' % ('满足!' if all([bull_bear_4h, bull_bear_1d, cond_adx4h, cond_pctb, cond_rsi, cond_adx5m, cond_vol]) else '不满足'))
print()
print('【做多B - 顺势回调】4h多头+1d多头+5m回调RSI35-60:')
bull_4h = is_bullish(ind_4H)
bull_1d = is_bullish(ind_1D)
cond_rsi_b = 35 < rsi < 60
print('  4h多头: %s' % bull_4h)
print('  1d多头: %s' % bull_1d)
print('  %b<0.2: %s' % cond_pctb)
print('  RSI 35-60: %s (当前%.1f)' % (cond_rsi_b, rsi))
print('  5mADX>25: %s' % cond_adx5m)
print('  放量>1.5x: %s' % cond_vol)
print('  -> %s' % ('满足!' if all([bull_4h, bull_1d, cond_pctb, cond_rsi_b, cond_adx5m, cond_vol]) else '不满足'))
print()
print('【做空A - 顺势高抛】4h多头+1d多头+5m超买RSI>=82:')
cond_rsi_a = rsi >= 82
cond_pctb_up = pct_b > 0.85
print('  4h多头: %s' % bull_4h)
print('  1d多头: %s' % bull_1d)
print('  %b>0.85: %s' % cond_pctb_up)
print('  RSI>=82: %s' % cond_rsi_a)
print('  5mADX>25: %s' % cond_adx5m)
print('  放量>1.5x: %s' % cond_vol)
print('  -> %s' % ('满足!' if all([bull_4h, bull_1d, cond_pctb_up, cond_rsi_a, cond_adx5m, cond_vol]) else '不满足'))
print()
print('【做空B - 逆势摸顶】4h空头+1d空头+4hADX<40+5m反弹RSI>=82:')
cond_rsi_b2 = rsi >= 82
print('  4h空头: %s' % bull_bear_4h)
print('  1d空头: %s' % bull_bear_1d)
print('  4hADX<40: %s' % cond_adx4h)
print('  %b>0.85: %s' % cond_pctb_up)
print('  RSI>=82: %s' % cond_rsi_b2)
print('  5mADX>25: %s' % cond_adx5m)
print('  放量>1.5x: %s' % cond_vol)
print('  -> %s' % ('满足!' if all([bull_bear_4h, bull_bear_1d, cond_adx4h, cond_pctb_up, cond_rsi_b2, cond_adx5m, cond_vol]) else '不满足'))

print()
print('=== 最终信号 ===')
signal, reason = analyzer.check()
print('信号: %s' % signal)
print('原因: %s' % reason)
