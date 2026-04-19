import hmac, base64, time, requests, json, hashlib, numpy as np

KEY = '3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c'
SECRET = 'bg_55d7ddd792c3ebab233b4a6911f95f99'
PASSPHRASE = 'liugang123'
BASE = 'https://api.bitget.com'

def sign(method, path, body=''):
    ts = str(int(time.time()*1000))
    msg = ts+method+path+body
    mac = hmac.new(SECRET.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode(), ts

# Get ticker
params = {'symbol': 'ETHUSDT', 'productType': 'usdt-futures'}
query = '&'.join(f'{k}={v}' for k,v in params.items())
path = f'/api/v2/mix/market/ticker?{query}'
sig, ts = sign('GET', path)
r = requests.get(BASE+path, headers={'ACCESS-KEY':KEY,'ACCESS-SIGN':sig,'ACCESS-TIMESTAMP':ts,'ACCESS-PASSPHRASE':PASSPHRASE}, timeout=10)
ticker = r.json()['data'][0] if r.json().get('data') else {}
last_pr = ticker.get('lastPr', '0')
change_24h = ticker.get('change24h', '0')
high_24h = ticker.get('high24h', '0')
low_24h = ticker.get('low24h', '0')

# Get 1H candles
params2 = {'symbol': 'ETHUSDT', 'productType': 'usdt-futures', 'granularity': '1H', 'limit': '60'}
query2 = '&'.join(f'{k}={v}' for k,v in params2.items())
path2 = f'/api/v2/mix/market/candles?{query2}'
sig2, ts2 = sign('GET', path2)
r2 = requests.get(BASE+path2, headers={'ACCESS-KEY':KEY,'ACCESS-SIGN':sig2,'ACCESS-TIMESTAMP':ts2,'ACCESS-PASSPHRASE':PASSPHRASE}, timeout=10)
candles = r2.json().get('data') or []

if not candles:
    print('K线数据为空')
    exit()

closes = [float(c[4]) for c in candles]
highs = [float(c[2]) for c in candles]
lows = [float(c[3]) for c in candles]
volumes = [float(c[5]) for c in candles]

last_close = closes[-1]
ma7 = sum(closes[-7:])/7
ma20 = sum(closes[-20:])/20
ma60 = sum(closes[-60:])/60 if len(closes)>=60 else sum(closes)/len(closes)

# RSI calc
def calc_rsi(prices, n=14):
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-n:])
    avg_loss = np.mean(losses[-n:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

rsi = calc_rsi(np.array(closes))

# Simple ADX
def calc_adx(h, l, c, n=14):
    h = np.array(h[::-1])
    l = np.array(l[::-1])
    c = np.array(c[::-1])
    h_f = np.flip(h)
    l_f = np.flip(l)
    c_f = np.flip(c)
    plus_dm = np.where((h_f[1:] - h_f[:-1]) > (l_f[:-1] - l_f[1:]), np.maximum(h_f[1:] - h_f[:-1], 0), 0)
    minus_dm = np.where((l_f[:-1] - l_f[1:]) > (h_f[1:] - h_f[:-1]), np.maximum(l_f[:-1] - l_f[1:], 0), 0)
    tr = np.maximum(h_f[1:] - l_f[1:], np.abs(h_f[1:] - c_f[:-1]), np.abs(l_f[1:] - c_f[:-1]))
    atr = float(np.convolve(tr, np.ones(n)/n, mode='valid')[-1]) if len(tr) >= n else float(tr[-1])
    if atr == 0:
        return 0
    plus_di = float(np.mean(plus_dm[-n:]) / atr * 100)
    minus_di = float(np.mean(minus_dm[-n:]) / atr * 100)
    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) else 0
    return dx

adx = calc_adx(highs, lows, closes)

# Volume
avg_vol = np.mean(volumes[-20:])
vol_ratio = volumes[-1] / avg_vol if avg_vol else 0

print(f'=== ETH 1H 策略指标 ===')
print(f'当前价格: ${last_close:.2f}')
print(f'24h高: ${high_24h} | 24h低: ${low_24h} | 24h变化: {change_24h}%')
print(f'MA7:  {ma7:.2f}  {"↑" if last_close > ma7 else "↓"}')
print(f'MA20: {ma20:.2f}  {"↑" if last_close > ma20 else "↓"}')
print(f'MA60: {ma60:.2f}  {"↑" if last_close > ma60 else "↓"}')
print(f'RSI:  {rsi:.1f}')
print(f'ADX:  {adx:.1f}  {"✅趋势强" if adx >= 25 else "❌震荡"}')
print(f'成交量: {vol_ratio:.2f}x均量')
print(f'---')
print(f'MA7>MA20: {"✅" if ma7 > ma20 else "❌"}')
print(f'ADX>=25:  {"✅" if adx >= 25 else "❌"}')
print(f'RSI非超买:{"✅" if rsi < 70 else "❌"}')
score = 0
if ma7 > ma20: score += 1
if ma20 > ma60: score += 1
if rsi < 70: score += 1
if adx >= 25: score += 1
if vol_ratio > 1.5: score += 1
print(f'综合评分: {score}/5 {"✅可开仓" if score >= 4 else "❌继续观望"}')
