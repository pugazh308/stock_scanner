"""
Logs each day's NSE shortlist so outcomes can be checked later, same idea
as scanner/track_record.py for the US pipeline but kept in its own file
since the two universes (and benchmarks) aren't comparable.
"""

import os
from datetime import date

from scanner.store import load_json, save_json, DATA_DIR

NSE_TRACK_FILE = os.path.join(DATA_DIR, "nse_track_record.json")


def record_picks(ranked, nifty_price_at_pick=None):
    records = load_json(NSE_TRACK_FILE, [])
    today = date.today().isoformat()

    for r in ranked:
        records.append({
            "date_picked": today,
            "ticker": r["ticker"],
            "score": r["score"],
            "entry_price": r.get("last_close"),
            "nifty_price_at_pick": nifty_price_at_pick,
            "rel_strength_1m_at_pick": r.get("rel_strength_1m"),
            "rel_strength_3m_at_pick": r.get("rel_strength_3m"),
            "vol_breakout_ratio_at_pick": r.get("vol_breakout_ratio"),
            "pct_off_52w_high_at_pick": r.get("pct_off_52w_high"),
            "liquidity_at_pick": r.get("avg_daily_turnover"),
            "evaluated": False,
            "last_checked_date": None,
            "latest_price": None,
            "current_return_pct": None,
            "current_return_vs_nifty_pct": None,
            "highest_close": None,
            "max_gain_pct": None,
            "lowest_close": None,
            "max_drawdown_pct": None,
            "return_7d_pct": None, "return_7d_actual_days": None, "return_7d_vs_nifty_pct": None,
            "return_14d_pct": None, "return_14d_actual_days": None, "return_14d_vs_nifty_pct": None,
            "return_30d_pct": None, "return_30d_actual_days": None, "return_30d_vs_nifty_pct": None,
            "return_60d_pct": None, "return_60d_actual_days": None, "return_60d_vs_nifty_pct": None,
        })

    save_json(NSE_TRACK_FILE, records)
    print(f"[NSE] Logged {len(ranked)} picks to the NSE track record.")
