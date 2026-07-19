"""
Fetches insider-buying data from OpenInsider (free, sourced from SEC Form 4 filings).
No API key needed. We scrape the public HTML tables.
Uses cloudscraper to bypass Cloudflare protection.
"""

import cloudscraper
import pandas as pd
import time

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)

URLS = {
    "daily":   "https://openinsider.com/top-insider-purchases-of-the-day",
    "weekly":  "https://openinsider.com/top-insider-purchases-of-the-week",
    "monthly": "https://openinsider.com/top-insider-purchases-of-the-month",
}

CLUSTER_URL  = "https://openinsider.com/latest-cluster-buys"
SCREENER_URL = "https://openinsider.com/screener"


def _clean_money(value):
    if value is None:
        return 0.0
    s = str(value).replace("$", "").replace(",", "").replace("+", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fetch_table(url, params=None):
    resp = scraper.get(url, params=params, timeout=30)
    resp.raise_for_status()
    html = resp.text
    if "<!doctype html>" in html.lower() and "<table" not in html.lower():
        raise ValueError(f"Got block page instead of data from {url}")
    tables = pd.read_html(html)
    if not tables:
        raise ValueError(f"No tables found at {url}")
    main_table = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    return main_table


def _clean_table(df):
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
    url = URLS.get(mode, URLS["daily"])
    df = _fetch_table(url)
    return _clean_table(df)


def get_cluster_buys():
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
    all_frames = []
    for page in range(1, max_pages + 1):
        params = {
            "fd": days_back, "td": 0, "xp": 1,
            "vl": min_value_k, "sortcol": 0, "cnt": 1000, "page": page,
        }
        try:
            df = _fetch_table(SCREENER_URL, params=params)
        except Exception:
            break
        if df.empty or df.shape[0] < 2:
            break
        all_frames.append(df)
        time.sleep(1)
        if df.shape[0] < 1000:
            break
    if not all_frames:
        return pd.DataFrame()
    return _clean_table(pd.concat(all_frames, ignore_index=True))
