"""
Logs every pick from every run so we can check back later and see what
actually happened to the price -- this is the data the learning step needs.
"""

from datetime import date
from scanner.store import load_track_record, save_track_record


def record_picks(ranked, mode, spy_price_at_pick=None):
    records = load_track_record()
    today = date.today().isoformat()

    for r in ranked:
        records.append({
            "date_picked": today,
            "mode": mode,
            "ticker": r["ticker"],
            "score": r["score"],
            "price_at_pick": r.get("last_price"),
            "spy_price_at_pick": spy_price_at_pick,
            "is_cluster": r.get("_is_cluster"),
            "avg_title_weight": r.get("_avg_title_weight"),
            "value_component": r.get("_value_component"),
            "insider_score": r.get("_insider_score"),
            "momentum_score": r.get("_momentum_score"),
            "rel_strength_1m_at_pick": r.get("rel_strength_1m"),
            "evaluated": False,
            "outcome_return_pct": None,
            "outcome_rel_to_spy_pct": None,
        })

    save_track_record(records)
    print(f"Logged {len(ranked)} picks to the track record.")
