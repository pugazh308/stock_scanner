"""
Fetches insider-buying data from OpenInsider (free, sourced from SEC Form 4 filings).
No API key needed. We scrape the public HTML tables.
"""

import requests
import pandas as pd

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal stock research script)"
}

# Different OpenInsider views depending on the digest period.
URLS = {
    "daily": "http://openinsider.com/top-insider-purchases-of-the-day",
    "weekly": "http://openinsider.com/top-insider-purchases-of-the-week",
    "monthly": "http://openinsider.com/top-insider-purchases-of-the-month",
}

CLUSTER_URL = "http://openinsider.com/latest-cluster-buys"
SCREENER_URL = "http://openinsider.com/screener"


def _clean_money(value):
    """Turn '+$1,234,567' or '$12.34' or '+19%' into a float."""
    if value is None:
        return 0.0
    s = str(value).replace("$", "").replace(",", "").replace("+", "").strip()
    s = s.replace("%", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fetch_table(url, params=None):
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(resp.text)
    main_table = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    return main_table


def _clean_table(df):
    """Shared cleanup for any OpenInsider table: normalize column names,
    drop junk rows, coerce money/percent columns to floats."""
    df.columns = [str(c).strip() for c in df.columns]
    rename_map = {}
    for c in df.columns:
        cl = c.lower()
        if "ticker" in cl:
            rename_map[c] = "Ticker"
        elif "company" in cl:
            rename_map[c] = "Company"
        elif "insider name" in cl:
            rename_map[c] = "Insider"
        elif cl == "title":
            rename_map[c] = "Title"
        elif "trade type" in cl:
            rename_map[c] = "TradeType"
        elif cl.startswith("price"):
            rename_map[c] = "Price"
        elif cl.startswith("qty"):
            rename_map[c] = "Qty"
        elif "own" in cl and "chg" in cl:
            rename_map[c] = "OwnChangePct"
        elif cl.startswith("value"):
            rename_map[c] = "Value"
        elif "filing date" in cl:
            rename_map[c] = "FilingDate"
        elif "trade date" in cl:
            rename_map[c] = "TradeDate"
    df = df.rename(columns=rename_map)

    keep_cols = [c for c in
                 ["FilingDate", "TradeDate", "Ticker", "Company", "Insider",
                  "Title", "TradeType", "Price", "Qty", "OwnChangePct", "Value"]
                 if c in df.columns]
    df = df[keep_cols].copy()

    df = df[df["Ticker"].astype(str).str.match(r"^[A-Z\.\-]{1,6}$", na=False)]

    if "Price" in df.columns:
        df["Price"] = df["Price"].apply(_clean_money)
    if "Value" in df.columns:
        df["Value"] = df["Value"].apply(_clean_money)
    if "OwnChangePct" in df.columns:
        df["OwnChangePct"] = df["OwnChangePct"].apply(_clean_money)

    return df.reset_index(drop=True)


def get_insider_buys(mode="daily"):
    """Returns a cleaned DataFrame of insider purchases for the given mode."""
    url = URLS.get(mode, URLS["daily"])
    df = _fetch_table(url)
    return _clean_table(df)


def get_cluster_buys():
    """Tickers where multiple insiders bought recently -- a stronger signal."""
    try:
        df = _fetch_table(CLUSTER_URL)
        df.columns = [str(c).strip() for c in df.columns]
        ticker_col = next((c for c in df.columns if "ticker" in c.lower()), None)
        if ticker_col is None:
            return set()
        tickers = df[ticker_col].astype(str).str.extract(r"([A-Z\.\-]{1,6})")[0]
        return set(tickers.dropna().tolist())
    except Exception:
        return set()


def get_historical_buys(days_back=365, min_value_k=25, max_pages=10):
    """
    Pulls insider PURCHASES filed in the last `days_back` days, value >=
    min_value_k thousand dollars, using OpenInsider's screener directly
    (the canned 'latest' pages above only show the most recent few days).
    Used for backfilling training data. OpenInsider caps each page at
    1000 rows, so we paginate up to max_pages (1 page = up to 1000 rows).
    """
    all_frames = []
    for page in range(1, max_pages + 1):
        params = {
            "fd": days_back, "td": 0, "xp": 1,  # xp=1 -> purchases only
            "vl": min_value_k, "sortcol": 0, "cnt": 1000, "page": page,
        }
        try:
            df = _fetch_table(SCREENER_URL, params=params)
        except Exception:
            break
        if df.empty or df.shape[0] < 2:
            break
        all_frames.append(df)
        if df.shape[0] < 1000:
            break  # last page reached
    if not all_frames:
        return pd.DataFrame()
    combined = pd.concat(all_frames, ignore_index=True)
    return _clean_table(combined)
