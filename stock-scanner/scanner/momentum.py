"""
Computes simple momentum stats per ticker:
- 1-month price return
- relative strength vs SPY (the S&P 500 ETF) over the same window
- volume trend (recent 5-day avg volume vs prior 20-day avg volume)
"""

import yfinance as yf
import pandas as pd


def _pct_return(series):
    if len(series) < 2 or series.iloc[0] == 0:
        return 0.0
    return (series.iloc[-1] / series.iloc[0] - 1.0) * 100.0


def get_momentum_stats(tickers, benchmark="SPY"):
    """
    tickers: list of ticker symbols
    Returns: dict of ticker -> {return_1m, rel_strength_1m, volume_trend}
    """
    if not tickers:
        return {}

    all_symbols = list(dict.fromkeys(tickers + [benchmark]))
    data = yf.download(
        all_symbols,
        period="2mo",
        interval="1d",
        progress=False,
        group_by="ticker",
        threads=True,
    )

    results = {}

    # Benchmark return for relative strength comparison.
    try:
        bench_close = data[benchmark]["Close"].dropna()
        bench_return_1m = _pct_return(bench_close.tail(21))
        bench_last_price = round(float(bench_close.iloc[-1]), 4)
    except Exception:
        bench_return_1m = 0.0
        bench_last_price = None

    results["__benchmark__"] = {"ticker": benchmark, "last_price": bench_last_price}

    for t in tickers:
        try:
            close = data[t]["Close"].dropna()
            volume = data[t]["Volume"].dropna()
            ret_1m = _pct_return(close.tail(21))
            recent_vol = volume.tail(5).mean()
            prior_vol = volume.tail(25).head(20).mean()
            vol_trend = (recent_vol / prior_vol - 1.0) * 100.0 if prior_vol else 0.0

            results[t] = {
                "return_1m": round(ret_1m, 2),
                "rel_strength_1m": round(ret_1m - bench_return_1m, 2),
                "volume_trend": round(vol_trend, 2),
                "last_price": round(float(close.iloc[-1]), 4),
            }
        except Exception:
            results[t] = {"return_1m": None, "rel_strength_1m": None, "volume_trend": None, "last_price": None}

    return results
