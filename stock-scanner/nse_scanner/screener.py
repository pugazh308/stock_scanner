"""
Price-action screener for the NSE universe.

Hard filters (a candidate must pass all of these to be considered):
  - enough history to compute a 200-day moving average
  - minimum average daily traded value (liquidity floor)
  - trend template: close > 50DMA > 200DMA (classic "stage 2 uptrend" filter)

Ranking, for names that pass the filters, blends:
  - relative strength vs Nifty 50 over 3 months (primary weight)
  - relative strength vs Nifty 50 over 1 month
  - volume breakout: today's volume vs the trailing 20-day average
  - proximity to the 52-week high

This mirrors the shape of scanner/scorer.py in the US module (component
scores kept alongside the total so a future learning step can reweight
them against real outcomes), but the weights here are fixed constants
for now rather than loaded from a learned weights file.
"""

MIN_AVG_DAILY_TURNOVER = 1_00_00_000  # INR 1 crore/day, min liquidity floor
MIN_HISTORY_DAYS = 210

WEIGHTS = {
    "rel_strength_3m": 0.45,
    "rel_strength_1m": 0.25,
    "volume_breakout": 0.20,
    "near_52w_high": 0.10,
}


def _pct_return(series, lookback):
    s = series.dropna()
    if len(s) <= lookback or s.iloc[-lookback - 1] == 0:
        return None
    return (s.iloc[-1] / s.iloc[-lookback - 1] - 1.0) * 100.0


def _bench_return(benchmark_close, lookback):
    return _pct_return(benchmark_close, lookback) if benchmark_close is not None else None


def compute_metrics(price_data, benchmark_close):
    bench_1m = _bench_return(benchmark_close, 21) or 0.0
    bench_3m = _bench_return(benchmark_close, 63) or 0.0

    rows = []
    for ticker, df in price_data.items():
        close = df["Close"].dropna()
        volume = df["Volume"].dropna()
        if len(close) < MIN_HISTORY_DAYS or len(volume) < MIN_HISTORY_DAYS:
            continue

        last_close = float(close.iloc[-1])
        dma50 = float(close.tail(50).mean())
        dma200 = float(close.tail(200).mean())
        high_52w = float(close.tail(252).max())
        vol_avg_20 = float(volume.tail(21).iloc[:-1].mean())
        vol_today = float(volume.iloc[-1])
        avg_daily_turnover = float((close.tail(20) * volume.tail(20)).mean())

        ret_1m = _pct_return(close, 21)
        ret_3m = _pct_return(close, 63)
        if ret_1m is None or ret_3m is None:
            continue

        trend_ok = last_close > dma50 > dma200
        pct_off_high = (last_close / high_52w - 1.0) * 100.0
        vol_breakout_ratio = (vol_today / vol_avg_20) if vol_avg_20 else 0.0

        rows.append({
            "ticker": ticker.replace(".NS", ""),
            "last_close": round(last_close, 2),
            "dma50": round(dma50, 2),
            "dma200": round(dma200, 2),
            "high_52w": round(high_52w, 2),
            "pct_off_52w_high": round(pct_off_high, 2),
            "vol_breakout_ratio": round(vol_breakout_ratio, 2),
            "avg_daily_turnover": avg_daily_turnover,
            "trend_ok": trend_ok,
            "return_1m": round(ret_1m, 2),
            "return_3m": round(ret_3m, 2),
            "rel_strength_1m": round(ret_1m - bench_1m, 2),
            "rel_strength_3m": round(ret_3m - bench_3m, 2),
        })

    return rows


def rank_candidates(rows, top_n=20):
    """Applies hard filters, scores survivors, returns the top_n sorted by score desc."""
    survivors = [
        r for r in rows
        if r["trend_ok"] and r["avg_daily_turnover"] >= MIN_AVG_DAILY_TURNOVER
    ]

    for r in survivors:
        vol_breakout_component = min(max(r["vol_breakout_ratio"] - 1.0, 0.0), 3.0) * 33.3
        near_high_component = max(0.0, 100.0 + r["pct_off_52w_high"] * 5)  # 0% off = 100, -20% off = 0

        score = (
            r["rel_strength_3m"] * WEIGHTS["rel_strength_3m"]
            + r["rel_strength_1m"] * WEIGHTS["rel_strength_1m"]
            + vol_breakout_component * WEIGHTS["volume_breakout"]
            + near_high_component * WEIGHTS["near_52w_high"]
        )
        r["_vol_breakout_component"] = round(vol_breakout_component, 2)
        r["_near_high_component"] = round(near_high_component, 2)
        r["score"] = round(score, 2)

    survivors.sort(key=lambda r: r["score"], reverse=True)
    return survivors[:top_n]
