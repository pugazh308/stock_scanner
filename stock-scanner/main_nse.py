import sys
import traceback
import argparse

from nse_scanner.fetch_prices import fetch_universe_history
from nse_scanner.screener import compute_metrics, rank_candidates
from nse_scanner.email_digest_nse import send_email
from nse_scanner.track_record import record_picks


def run(top_n=20):
    print("Running NSE daily watchlist scan...")

    price_data, benchmark_close = fetch_universe_history()
    if not price_data:
        print("No price data fetched. Sending empty digest and exiting.")
        send_email([])
        return

    metrics = compute_metrics(price_data, benchmark_close)
    print(f"Computed metrics for {len(metrics)} tickers with sufficient history.")

    ranked = rank_candidates(metrics, top_n=top_n)
    print(f"{len(ranked)} tickers passed the trend/liquidity filters and were ranked.")

    nifty_price = float(benchmark_close.iloc[-1]) if benchmark_close is not None and len(benchmark_close) else None

    send_email(ranked)
    record_picks(ranked, nifty_price_at_pick=nifty_price)
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()

    try:
        run(top_n=args.top_n)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
