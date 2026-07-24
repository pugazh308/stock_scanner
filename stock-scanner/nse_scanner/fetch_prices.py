"""
Batch-downloads daily OHLCV for the NSE scan universe via yfinance.
Needs ~14 months of history: 252 trading days for the 52-week high/DMA200
calculations plus headroom for holidays/gaps.
"""

import yfinance as yf

from nse_scanner.universe import get_universe, BENCHMARK

CHUNK_SIZE = 100


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_universe_history(period="14mo"):
    """
    Returns (price_data, benchmark_close) where price_data is a dict of
    ticker -> DataFrame (Open/High/Low/Close/Volume) and benchmark_close
    is the Nifty 50 index Close series. Tickers that fail to download are
    silently skipped -- yfinance batch calls don't hard-fail on one bad
    symbol, but chunking keeps any single chunk's failure from wiping out
    the whole run.
    """
    universe = get_universe()
    all_symbols = universe + [BENCHMARK]
    price_data = {}
    benchmark_close = None

    for chunk in _chunks(all_symbols, CHUNK_SIZE):
        try:
            data = yf.download(
                chunk,
                period=period,
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=True,
                auto_adjust=True,
            )
        except Exception as e:
            print(f"[NSE] Chunk download failed ({len(chunk)} tickers): {e}")
            continue

        for t in chunk:
            try:
                df = data[t].dropna(how="all")
                if df.empty:
                    continue
                if t == BENCHMARK:
                    benchmark_close = df["Close"].dropna()
                else:
                    price_data[t] = df
            except Exception:
                continue

    print(f"[NSE] Downloaded price history for {len(price_data)}/{len(universe)} universe tickers.")
    return price_data, benchmark_close
