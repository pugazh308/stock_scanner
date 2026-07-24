"""
Tracks outcomes for NSE picks logged in data/nse_track_record.json.

Unlike scanner/evaluate.py (one point-in-time snapshot at a fixed hold
period), every still-active record here gets a running current_return_pct,
max_gain_pct, and max_drawdown_pct computed against entry_price using every
daily close observed from date_picked through today, plus frozen snapshots
at the 7/14/30/60-day marks the first time each threshold is crossed. Since
this only runs on NSE trading weekdays (and NSE has its own holidays), the
first check after a threshold is crossed can land a day or more late -- the
companion *_actual_days field records the true elapsed time so later
analysis isn't distorted by cron-cadence slack. Once the 60-day snapshot is
captured the record is marked evaluated and stops being touched.
"""

import os
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from scanner.store import load_json, save_json, DATA_DIR
from nse_scanner.universe import BENCHMARK

NSE_TRACK_FILE = os.path.join(DATA_DIR, "nse_track_record.json")
HORIZONS = (7, 14, 30, 60)
CHUNK_SIZE = 100
STALE_GRACE_DAYS = 14  # force-finalize if we never get data by 60+this many days


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _days_since(date_str):
    return (date.today() - date.fromisoformat(date_str)).days


def _extract_close(data, symbol, chunk_size):
    """Handles yfinance's flat-column fallback when a chunk has one symbol."""
    try:
        series = data[symbol]["Close"].dropna()
        if not series.empty:
            return series
    except (KeyError, TypeError):
        pass
    if chunk_size == 1:
        try:
            series = data["Close"].dropna()
            if not series.empty:
                return series
        except Exception:
            pass
    return None


def _fetch_close_series(symbols, start, end):
    """Returns {symbol: Close Series}. Missing/delisted/renamed symbols are
    simply absent rather than raising."""
    close_by_symbol = {}
    for chunk in _chunks(symbols, CHUNK_SIZE):
        try:
            data = yf.download(
                chunk, start=start, end=end, interval="1d",
                progress=False, group_by="ticker", threads=True, auto_adjust=True,
            )
        except Exception as e:
            print(f"[NSE-Eval] Chunk download failed ({len(chunk)} symbols): {e}")
            continue

        for sym in chunk:
            series = _extract_close(data, sym, len(chunk))
            if series is not None:
                close_by_symbol[sym] = series

    return close_by_symbol


def _window_return_pct(series, since_date, base_price):
    """Returns (latest, highest, lowest, return_pct) for the slice of
    series on/after since_date, vs. base_price. None-tuple if no data or
    base_price is missing/zero."""
    if series is None or not base_price:
        return None, None, None, None
    window = series[series.index >= pd.Timestamp(since_date)]
    if window.empty:
        return None, None, None, None
    latest = float(window.iloc[-1])
    highest = float(window.max())
    lowest = float(window.min())
    return latest, highest, lowest, (latest / base_price - 1.0) * 100.0


def evaluate_picks():
    records = load_json(NSE_TRACK_FILE, [])
    active = [r for r in records if not r.get("evaluated", False)]

    if not active:
        print("[NSE-Eval] No active picks to evaluate.")
        return records

    tickers = sorted({r["ticker"] for r in active})
    symbols = [f"{t}.NS" for t in tickers] + [BENCHMARK]
    earliest_pick = min(date.fromisoformat(r["date_picked"]) for r in active)
    start = earliest_pick.isoformat()
    end = (date.today() + timedelta(days=1)).isoformat()  # yfinance end is exclusive

    print(f"[NSE-Eval] Checking {len(active)} active picks across {len(tickers)} "
          f"tickers (window {start} -> {end})...")

    close_by_symbol = _fetch_close_series(symbols, start, end)
    benchmark_series = close_by_symbol.get(BENCHMARK)
    today_iso = date.today().isoformat()
    updated = 0

    for r in active:
        ticker = r["ticker"]
        symbol = f"{ticker}.NS"
        entry_price = r.get("entry_price")
        days_elapsed = _days_since(r["date_picked"])

        series = close_by_symbol.get(symbol)
        latest, highest, lowest, ret_pct = _window_return_pct(series, r["date_picked"], entry_price)

        if ret_pct is None:
            print(f"[NSE-Eval] No usable price data for {ticker}; leaving record as-is.")
            if days_elapsed >= 60 + STALE_GRACE_DAYS:
                r["evaluated"] = True
                r["last_checked_date"] = today_iso
                print(f"[NSE-Eval] {ticker}: no data after {days_elapsed}d, force-finalized.")
            continue

        _, _, _, nifty_ret_pct = _window_return_pct(
            benchmark_series, r["date_picked"], r.get("nifty_price_at_pick")
        )
        rel_pct = (ret_pct - nifty_ret_pct) if nifty_ret_pct is not None else None

        r["latest_price"] = round(latest, 4)
        r["highest_close"] = round(highest, 4)
        r["lowest_close"] = round(lowest, 4)
        r["current_return_pct"] = round(ret_pct, 2)
        r["current_return_vs_nifty_pct"] = round(rel_pct, 2) if rel_pct is not None else None
        r["max_gain_pct"] = round((highest / entry_price - 1.0) * 100.0, 2)
        r["max_drawdown_pct"] = round((lowest / entry_price - 1.0) * 100.0, 2)
        r["last_checked_date"] = today_iso

        for h in HORIZONS:
            field = f"return_{h}d_pct"
            if r.get(field) is None and days_elapsed >= h:
                r[field] = r["current_return_pct"]
                r[f"return_{h}d_actual_days"] = days_elapsed
                r[f"return_{h}d_vs_nifty_pct"] = r["current_return_vs_nifty_pct"]

        if r.get("return_60d_pct") is not None:
            r["evaluated"] = True

        updated += 1

    save_json(NSE_TRACK_FILE, records)
    print(f"[NSE-Eval] Updated {updated}/{len(active)} active picks.")
    return records
