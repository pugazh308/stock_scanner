"""
Entry point. Run with: python main.py --mode daily|weekly|monthly

Pulls insider buying data, cross-references with cluster buys, computes
momentum stats via yfinance, scores/ranks everything, emails the digest,
and logs the picks so the learning loop can check back on them later.
"""

import argparse
import sys

from scanner.fetch_insider import get_insider_buys, get_cluster_buys
from scanner.momentum import get_momentum_stats
from scanner.scorer import build_ranking
from scanner.email_digest import send_email
from scanner.track_record import record_picks


def run(mode, top_n=15):
    print(f"Running {mode} scan...")

    insider_df = get_insider_buys(mode)
    print(f"Fetched {len(insider_df)} insider purchase rows.")

    cluster_tickers = get_cluster_buys()
    print(f"Found {len(cluster_tickers)} cluster-buy tickers.")

    tickers = insider_df["Ticker"].dropna().unique().tolist()
    momentum_stats = get_momentum_stats(tickers)
    spy_price = (momentum_stats.get("__benchmark__") or {}).get("last_price")

    ranked = build_ranking(insider_df, cluster_tickers, momentum_stats, top_n=top_n)
    print(f"Ranked {len(ranked)} tickers for the digest.")

    send_email(ranked, mode)
    record_picks(ranked, mode, spy_price_at_pick=spy_price)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly", "monthly"], default="daily")
    parser.add_argument("--top-n", type=int, default=15)
    args = parser.parse_args()

    try:
        run(args.mode, top_n=args.top_n)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
