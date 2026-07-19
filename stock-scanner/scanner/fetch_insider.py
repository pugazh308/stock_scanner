"""
Fetches insider-buying data directly from SEC EDGAR Form 4 filings.
No OpenInsider needed. SEC.gov is always reachable from GitHub Actions.
SEC explicitly allows programmatic access with a proper User-Agent.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import time
import re

SEC_HEADERS = {
    "User-Agent": "StockResearchBot research.bot@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

EDGAR_BASE  = "https://www.sec.gov"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"


def _search_form4(days_back=3):
    end   = datetime.today()
    start = end - timedelta(days=max(days_back, 1))
    params = {
        "forms": "4",
        "dateRange": "custom",
        "startdt": start.strftime("%Y-%m-%d"),
        "enddt":   end.strftime("%Y-%m-%d"),
    }
    resp = requests.get(
        EDGAR_SEARCH,
        headers={**SEC_HEADERS, "Host": "efts.sec.gov"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("hits", {}).get("hits", [])


def _cik_from_accession(accession_no):
    """CIK is the first segment of the accession number."""
    parts = accession_no.split("-")
    return parts[0].lstrip("0") or "0" if parts else None


def _xml_urls_from_index(cik, accession_no):
    acc_clean = accession_no.replace("-", "")
    index_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{accession_no}-index.htm"
    try:
        resp = requests.get(index_url, headers=SEC_HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        found = re.findall(
            r'/Archives/edgar/data/\d+/\d+/([^"\'<>\s]+\.xml)',
            resp.text,
        )
        return [
            f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{f}"
            for f in found
            if "index" not in f.lower()
        ]
    except Exception:
        return []


def _parse_form4(xml_url):
    try:
        time.sleep(0.15)
        resp = requests.get(xml_url, headers=SEC_HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            text = resp.content.decode("utf-8", errors="ignore")
            m = re.search(r"(<ownershipDocument.*?</ownershipDocument>)", text, re.DOTALL)
            if not m:
                return []
            root = ET.fromstring(m.group(1))
    except Exception:
        return []

    ticker_el = root.find(".//issuerTradingSymbol")
    ticker = (ticker_el.text or "").strip().upper() if ticker_el is not None else ""
    if not ticker or not re.match(r"^[A-Z]{1,5}$", ticker):
        return []

    name_el  = root.find(".//rptOwnerName")
    title_el = root.find(".//officerTitle")
    insider  = (name_el.text  or "Unknown").strip() if name_el  is not None else "Unknown"
    title    = (title_el.text or "").strip()         if title_el is not None else ""

    period_el   = root.find(".//periodOfReport")
    filing_date = (period_el.text or "").strip() if period_el is not None else ""

    rows = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = (txn.findtext(".//transactionCode") or "").strip()
        if code != "P":
            continue
        try:
            shares = float((txn.findtext(".//transactionShares/value")         or "0").replace(",", ""))
            price  = float((txn.findtext(".//transactionPricePerShare/value")  or "0").replace(",", ""))
            date   = (txn.findtext(".//transactionDate/value") or filing_date).strip()
        except ValueError:
            continue
        value = shares * price
        if value < 1000:
            continue
        rows.append({
            "FilingDate":    filing_date,
            "TradeDate":     date,
            "Ticker":        ticker,
            "Insider":       insider,
            "Title":         title,
            "TradeType":     "P - Purchase",
            "Price":         round(price, 4),
            "Qty":           shares,
            "Value":         round(value, 2),
            "OwnChangePct":  0.0,
        })
    return rows


def get_insider_buys(mode="daily"):
    days_map = {"daily": 2, "weekly": 7, "monthly": 30, "test": 5}
    days_back = days_map.get(mode, 2)
    print(f"[EDGAR] Searching Form 4 filings ({days_back}d)...")
    try:
        hits = _search_form4(days_back)
    except Exception as e:
        print(f"[EDGAR] Search error: {e}")
        return pd.DataFrame()

    print(f"[EDGAR] {len(hits)} filings found")
    all_rows = []
    for hit in hits[:80]:
        src = hit.get("_source", {})
        acc = src.get("accession_no", "")
        if not acc:
            continue
        cik = _cik_from_accession(acc)
        if not cik:
            continue
        for xml_url in _xml_urls_from_index(cik, acc)[:1]:
            all_rows.extend(_parse_form4(xml_url))

    if not all_rows:
        print("[EDGAR] No purchases found.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["Ticker", "Insider", "TradeDate", "Value"])
    df = df.sort_values("Value", ascending=False).reset_index(drop=True)
    print(f"[EDGAR] {len(df)} purchases across {df['Ticker'].nunique()} tickers")
    return df


def get_cluster_buys():
    try:
        df = get_insider_buys(mode="weekly")
        if df.empty:
            return set()
        counts = df.groupby("Ticker")["Insider"].nunique()
        return set(counts[counts >= 2].index.tolist())
    except Exception:
        return set()


def get_historical_buys(days_back=365, min_value_k=25, max_pages=10):
    print(f"[EDGAR] Historical backfill: {days_back} days...")
    try:
        hits = _search_form4(days_back)
    except Exception as e:
        print(f"[EDGAR] Historical error: {e}")
        return pd.DataFrame()

    min_val = min_value_k * 1000
    all_rows = []
    for hit in hits[:300]:
        src = hit.get("_source", {})
        acc = src.get("accession_no", "")
        cik = _cik_from_accession(acc) if acc else None
        if not cik:
            continue
        for xml_url in _xml_urls_from_index(cik, acc)[:1]:
            all_rows.extend([r for r in _parse_form4(xml_url) if r.get("Value", 0) >= min_val])

    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    return df.drop_duplicates(subset=["Ticker", "Insider", "TradeDate", "Value"]).reset_index(drop=True)
