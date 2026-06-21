"""
Run with: python backfill_historical.py [--days-back 365]

Pulls real historical insider purchases (not just the last few days) from
OpenInsider's screener, computes what each pick's price did over the
following ~14 days using Yahoo Finance historical data, and writes the
results directly into data/track_record.json as already-evaluated entries.

This needs real internet access to openinsider.com and Yahoo Finance, which
is why it's meant to run via GitHub Actions (workflow_dispatch) or on your
own machine -- not something Claude can execute from its sandboxed
environment, which can only reach package registries.

This is a one-time (or occasional) bootstrap. The live daily/weekly/monthly
runs keep adding fresh real data on top of this automatically.
"""

import argparse
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from scanner.fetch_insider import get_historical_buys
from scanner.store import load_weights, load_track_record, save_track_record

HOLD_DAYS = 14


def _title_weight(title, title_weights):
    if not isinstance(title, str):
        return 1.0
    title_l = title.lower()
    best = 1.0
    for key, weight in title_weights.items():
        if key in title_l:
            best = max(best, weight)
    return best


def _price_on_or_after(close_series, target_date):
    """First available close on/after target_date, using nearest-prior
    trading day if target_date itself isn't a trading day."""
    idx = close_series.index[close_series.index >= pd.Timestamp(target_date)]
    if len(idx) == 0:
        return None
    return float(close_series.loc[idx[0]])


def backfill(days_back=365, min_value_k=25):
    print(f"Fetching insider purchases from the last {days_back} days (>= ${min_value_k}k)...")
    df = get_historical_buys(days_back=days_back, min_value_k=min_value_k)
    if df.empty:
        print("No historical data returned -- nothing to backfill.")
        return

    df = df.dropna(subset=["FilingDate", "Ticker"])
    df["FilingDateParsed"] = pd.to_datetime(df["FilingDate"], errors="coerce").dt.date
    df = df.dropna(subset=["FilingDateParsed"])
    print(f"Got {len(df)} historical purchase rows across "
          f"{df['Ticker'].nunique()} tickers.")

    weights = load_weights()
    title_weights = weights["title_weights"]

    # Group by (ticker, filing date) so multiple insiders buying the same
    # stock on/around the same day count as one "pick" with a cluster flag,
    # same as the live scorer does.
    grouped = df.groupby(["Ticker", "FilingDateParsed"]).agg(
        Company=("Company", "first"),
        total_value=("Value", "sum"),
        n_insiders=("Insider", "nunique"),
    ).reset_index()
    title_weight_per_row = df.apply(lambda r: _title_weight(r.get("Title"), title_weights), axis=1)
    df["_tw"] = title_weight_per_row
    avg_tw = df.groupby(["Ticker", "FilingDateParsed"])["_tw"].mean().reset_index(name="avg_title_weight")
    grouped = grouped.merge(avg_tw, on=["Ticker", "FilingDateParsed"])

    # Also flag tickers bought by multiple distinct insiders ANYWHERE in the
    # whole pulled window (not just same-day) as cluster picks -- approximates
    # the live cluster-buy signal.
    ticker_insider_counts = df.groupby("Ticker")["Insider"].nunique()
    cluster_tickers = set(ticker_insider_counts[ticker_insider_counts > 1].index)

    tickers = sorted(grouped["Ticker"].unique().tolist())
    print(f"Downloading price history for {len(tickers)} tickers + SPY (this can take a few minutes)...")

    earliest = min(grouped["FilingDateParsed"]) - timedelta(days=45)
    latest = max(grouped["FilingDateParsed"]) + timedelta(days=HOLD_DAYS + 5)
    today = datetime.today().date()
    latest = min(latest, today)

    symbols = tickers + ["SPY"]
    price_data = yf.download(symbols, start=earliest, end=latest + timedelta(days=1),
                              interval="1d", progress=False, group_by="ticker", threads=True)

    try:
        spy_close = price_data["SPY"]["Close"].dropna()
    except Exception:
        spy_close = pd.Series(dtype=float)

    records = []
    skipped = 0
    for _, row in grouped.iterrows():
        ticker = row["Ticker"]
        pick_date = row["FilingDateParsed"]
        outcome_date = pick_date + timedelta(days=HOLD_DAYS)
        if outcome_date > today:
            skipped += 1
            continue  # too recent to know the outcome yet

        try:
            close = price_data[ticker]["Close"].dropna()
        except Exception:
            skipped += 1
            continue

        price_then = _price_on_or_after(close, pick_date)
        price_now = _price_on_or_after(close, outcome_date)
        spy_then = _price_on_or_after(spy_close, pick_date)
        spy_now = _price_on_or_after(spy_close, outcome_date)

        prior_window_start = pick_date - timedelta(days=35)
        prior_close = close[close.index <= pd.Timestamp(pick_date)]
        momentum_1m = None
        if len(prior_close) > 5:
            base = prior_close.iloc[max(0, len(prior_close) - 22)]
            if base:
                momentum_1m = (prior_close.iloc[-1] / base - 1.0) * 100.0

        if not price_then or not price_now:
            skipped += 1
            continue

        outcome_return_pct = round((price_now / price_then - 1.0) * 100.0, 2)
        outcome_rel_to_spy_pct = None
        if spy_then and spy_now:
            spy_return = (spy_now / spy_then - 1.0) * 100.0
            outcome_rel_to_spy_pct = round(outcome_return_pct - spy_return, 2)

        is_cluster = row["n_insiders"] > 1 or ticker in cluster_tickers
        value_component = min(row["total_value"] / weights["value_divisor"], 20)
        rel_strength = (momentum_1m or 0)
        momentum_score = rel_strength * weights["rel_strength_coef"]
        insider_score = value_component * row["avg_title_weight"] * (weights["cluster_bonus"] if is_cluster else 1.0)

        records.append({
            "date_picked": pick_date.isoformat(),
            "mode": "backfill",
            "ticker": ticker,
            "score": round(insider_score + momentum_score, 2),
            "price_at_pick": price_then,
            "spy_price_at_pick": spy_then,
            "is_cluster": bool(is_cluster),
            "avg_title_weight": round(float(row["avg_title_weight"]), 4),
            "value_component": round(value_component, 4),
            "insider_score": round(insider_score, 4),
            "momentum_score": round(momentum_score, 4),
            "rel_strength_1m_at_pick": round(rel_strength, 2) if rel_strength is not None else None,
            "evaluated": True,
            "outcome_return_pct": outcome_return_pct,
            "outcome_rel_to_spy_pct": outcome_rel_to_spy_pct,
        })

    existing = load_track_record()
    save_track_record(existing + records)
    print(f"Backfilled {len(records)} historical picks ({skipped} skipped -- too recent or missing price data).")
    print("These are now in data/track_record.json as evaluated picks, ready for training.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--min-value-k", type=int, default=25)
    args = parser.parse_args()
    backfill(days_back=args.days_back, min_value_k=args.min_value_k)
