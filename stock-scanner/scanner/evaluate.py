"""
Looks at picks logged more than HOLD_DAYS calendar days ago that haven't
been evaluated yet, fetches their current price, and records the actual
return since the pick was made (and relative to SPY over the same window).
"""

from datetime import date
import yfinance as yf

from scanner.store import load_track_record, save_track_record

HOLD_DAYS = 14  # how long to wait before judging a pick


def _days_since(date_str):
    picked = date.fromisoformat(date_str)
    return (date.today() - picked).days


def evaluate_matured_picks():
    records = load_track_record()
    pending = [r for r in records if not r["evaluated"] and _days_since(r["date_picked"]) >= HOLD_DAYS]

    if not pending:
        print("No matured picks ready to evaluate yet.")
        return records

    tickers = sorted({r["ticker"] for r in pending})
    print(f"Evaluating {len(pending)} matured picks across {len(tickers)} tickers...")

    symbols = tickers + ["SPY"]
    data = yf.download(symbols, period="5d", interval="1d", progress=False, group_by="ticker", threads=True)

    current_prices = {}
    for sym in symbols:
        try:
            current_prices[sym] = float(data[sym]["Close"].dropna().iloc[-1])
        except Exception:
            current_prices[sym] = None

    spy_now = current_prices.get("SPY")

    for r in pending:
        price_then = r.get("price_at_pick")
        price_now = current_prices.get(r["ticker"])
        spy_then = r.get("spy_price_at_pick")
        if price_then and price_now:
            stock_return = (price_now / price_then - 1.0) * 100.0
            r["outcome_return_pct"] = round(stock_return, 2)
            if spy_then and spy_now:
                spy_return = (spy_now / spy_then - 1.0) * 100.0
                r["outcome_rel_to_spy_pct"] = round(stock_return - spy_return, 2)
        r["evaluated"] = True

    save_track_record(records)
    print(f"Evaluation complete for {len(pending)} picks.")
    return records
