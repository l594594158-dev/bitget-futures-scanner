def check_signal_long(symbol, change24h):
    """检测做多信号（多周期验证：大周期确认方向，小周期找入场点）"""
    # 三个周期K线
    klines_15m = get_klines(symbol, '15m', 100)
    klines_1h = get_klines(symbol, '1h', 100)
    klines_4h = get_klines(symbol, '4h', 100)

    if not klines_15m or not klines_1h:
        return False, "K线数据不足"

    try:
        # 15m数据
        c15 = [float(k[4]) for k in klines_15m]
        h15 = [float(k[2]) for k in klines_15m]
        l15 = [float(k[3]) for k in klines_15m]
        v15 = [float(k[5]) for k in klines_15m]

        # 1h数据
        c1 = [float(k[4]) for k in klines_1h]
        v1 = [float(k[5]) for k in klines_1h]

        # 4h数据（降级到1h）
        if klines_4h:
            c4 = [float(k[4]) for k in klines_4h]
            h4 = [float(k[2]) for k in klines_4h]
            l4 = [float(k[3]) for k in klines_4h]
        else:
            c4, h4, l4 = c1, h15, l15
    except:
        return False, "K线解析失败"

    price = c15[-1]

    # === 条件1：4h ADX趋势确认（方向） ===
    adx4, dip4, dim4 = compute_adx(h4, l4, c4) if len(c4) >= 15 else compute_adx(h15, l15, c15)
    cond1 = adx4 >= LONG_ADX and dip4 > dim4

    # === 条件2：1h成交量比（回调健康=缩量） ===
    vr1 = compute_vol_ratio(v1)
    cond2 = vr1 < LONG_VR_MAX

    # === 条件3：多周期RSI（4h有空间 + 1h确认 + 15m入场点） ===
    rsi4 = compute_rsi(c4) if len(c4) >= 15 else 50
    rsi1 = compute_rsi(c1)
    rsi15 = compute_rsi(c15)
    # 4h RSI 50~68：还有上涨空间，不过热
    # 1h RSI ≥52：确认上涨中
    # 15m RSI ≤72：入场不太追高（比之前75放宽一点，配合4h空间）
    cond3 = 50 <= rsi4 <= 68 and rsi1 >= 52 and rsi15 <= 72

    # === 条件4：15m动量未衰竭 ===
    mom_slowdown, slowdown_deg = compute_momentum_slowdown(c15, v15)
    cond4 = not (mom_slowdown and slowdown_deg > 0.3)

    reasons = (
        f"做多: ①ADX4h={adx4:.1f}≥{LONG_ADX}+DI+={'✅' if cond1 else '❌'} "
        f"②vr1={vr1:.2f}<{LONG_VR_MAX}={'✅' if cond2 else '❌'} "
        f"③RSI4h={rsi4:.0f}(50~68) RSI1h={rsi1:.0f}(≥52) RSI15m={rsi15:.0f}(≤72)={'✅' if cond3 else '❌'} "
        f"④动量={'✅' if cond4 else '❌'}"
    )

    return (cond1 and cond2 and cond3 and cond4), reasons
