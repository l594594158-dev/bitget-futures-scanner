def check_signal_long(symbol, change24h):
    """纯动量做多：15m动量未衰竭则顺势开多"""
    klines = get_klines(symbol, '15m', 100)
    if not klines:
        return False, "无K线数据"
    try:
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
    except:
        return False, "K线解析失败"

    mom_ok, deg = compute_momentum_slowdown(closes, volumes)
    cond = not mom_ok  # 未衰竭 = 做多信号

    return cond, (
        f"做多: 动量{'未衰竭✅' if cond else '衰竭❌'} deg={deg:.3f}"
    )

def check_signal_short(symbol, change24h):
    """纯动量做空：15m动量衰竭则顺势做空"""
    klines = get_klines(symbol, '15m', 100)
    if not klines:
        return False, "无K线数据"
    try:
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
    except:
        return False, "K线解析失败"

    mom_ok, deg = compute_momentum_slowdown(closes, volumes)
    cond = mom_ok and deg > 0.25  # 衰竭且明显

    return cond, (
        f"做空: 动量衰竭={'✅' if cond else '❌'} deg={deg:.3f}"
    )

