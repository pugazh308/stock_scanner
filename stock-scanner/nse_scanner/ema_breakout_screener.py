"""
EMA trend + tight-range breakout screener for the NSE universe.

Filter 1 (all must hold -- confirmed uptrend with strong momentum):
  - Close > EMA(20)
  - EMA(20) > EMA(50)
  - EMA(50) > EMA(200)
  - RSI(14) > 55
  - Volume > 500,000 shares (today's volume)
  - Close > 100

Filter 2 (at least one must hold -- price is coiled near the highs rather
than extended, i.e. a tight base that could resolve into a breakout):
  - (20d High - 20d Low) / 20d Low < 10%
  - Close within 3% of the 20d High
  - 20d High / 20d Low < 1.10

A candidate must pass Filter 1 AND at least one Filter 2 condition.
"""

MIN_VOLUME = 500_000
MIN_CLOSE = 100.0
RSI_FLOOR = 55.0
EMA_FAST, EMA_MED, EMA_SLOW = 20, 50, 200
RANGE_LOOKBACK = 20

RANGE_PCT_CEILING = 10.0
NEAR_HIGH_PCT_CEILING = 3.0
HIGH_LOW_RATIO_CEILING = 1.10

MIN_HISTORY_DAYS = EMA_SLOW + 10


def _ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close, period=14):
    """Wilder's RSI. Returns the latest value, or None if not computable."""
    s = close.dropna()
    if len(s) < period + 1:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema_breakout_metrics(price_data):
    """Computes EMA/RSI/range metrics for every ticker with enough history.
    Filters are NOT applied here (same separation of concerns as
    screener.py: compute everything, filter/rank in rank_ema_breakout)."""
    rows = []
    for ticker, df in price_data.items():
        close = df["Close"].dropna()
        volume = df["Volume"].dropna()
        if len(close) < MIN_HISTORY_DAYS or len(volume) < MIN_HISTORY_DAYS:
            continue
        if len(close) < RANGE_LOOKBACK:
            continue

        last_close = float(close.iloc[-1])
        last_volume = float(volume.iloc[-1])
        ema20 = float(_ema(close, EMA_FAST).iloc[-1])
        ema50 = float(_ema(close, EMA_MED).iloc[-1])
        ema200 = float(_ema(close, EMA_SLOW).iloc[-1])
        rsi14 = _rsi(close)

        hh20 = float(close.tail(RANGE_LOOKBACK).max())
        ll20 = float(close.tail(RANGE_LOOKBACK).min())
        if hh20 <= 0 or ll20 <= 0:
            continue

        range_pct = (hh20 - ll20) / ll20 * 100.0
        pct_from_high = (hh20 - last_close) / hh20 * 100.0
        high_low_ratio = hh20 / ll20

        rows.append({
            "ticker": ticker.replace(".NS", ""),
            "last_close": round(last_close, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "rsi14": round(rsi14, 2) if rsi14 is not None else None,
            "volume": int(last_volume),
            "hh20": round(hh20, 2),
            "ll20": round(ll20, 2),
            "range_pct": round(range_pct, 2),
            "pct_from_high": round(pct_from_high, 2),
            "high_low_ratio": round(high_low_ratio, 4),
        })
    return rows


def rank_ema_breakout(rows, top_n=20):
    """Applies Filter 1 (all must hold) and Filter 2 (any one must hold),
    scores survivors by how tightly they're coiled near the highs, and
    returns the top_n sorted by score desc."""
    survivors = []
    for r in rows:
        if r["rsi14"] is None:
            continue

        trend_ok = r["last_close"] > r["ema20"] > r["ema50"] > r["ema200"]
        momentum_ok = r["rsi14"] > RSI_FLOOR
        liquidity_ok = r["volume"] > MIN_VOLUME
        price_ok = r["last_close"] > MIN_CLOSE
        if not (trend_ok and momentum_ok and liquidity_ok and price_ok):
            continue

        tight_range = r["range_pct"] < RANGE_PCT_CEILING
        near_high = r["pct_from_high"] <= NEAR_HIGH_PCT_CEILING
        tight_ratio = r["high_low_ratio"] < HIGH_LOW_RATIO_CEILING
        if not (tight_range or near_high or tight_ratio):
            continue

        survivors.append(r)

    for r in survivors:
        # Tighter 20d range + closer to the high = more coiled for a
        # breakout, so it ranks higher. Both components normalized to
        # roughly 0-100 before combining.
        tightness_component = max(0.0, 100.0 - r["range_pct"] * 5.0)
        proximity_component = max(0.0, 100.0 - r["pct_from_high"] * 10.0)
        r["score"] = round((tightness_component + proximity_component) / 2.0, 2)

    survivors.sort(key=lambda r: r["score"], reverse=True)
    return survivors[:top_n]
