"""
Fetches insider-buying data directly from SEC EDGAR Form 4 filings.
Uses SEC EDGAR EFTS search + JSON filing index for reliable XML discovery.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import time
import re

SEC_HEADERS = {
    "User-Agent": "StockResearchBot research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

EDGAR_BASE   = "https://www.sec.gov"
EFTS_SEARCH  = "https://efts.sec.gov/LATEST/search-index"


def _search_form4(days_back=5):
    end   = datetime.today()
    start = end - timedelta(days=max(days_back, 1))
    params = {
        "forms":      "4",
        "dateRange":  "custom",
        "startdt":    start.strftime("%Y-%m-%d"),
        "enddt":      end.strftime("%Y-%m-%d"),
        "hits.hits.total.value": 100,
    }
    print(f"[EDGAR] Searching {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
    resp = requests.get(EFTS_SEARCH, headers=SEC_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])
    print(f"[EDGAR] Raw hits: {len(hits)}")
    return hits


def _get_xml_url(cik, accession_no):
    """Use the JSON filing index to reliably find the primary XML document."""
    acc_clean = accession_no.replace("-", "")
    json_url  = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{accession_no}-index.json"
    try:
        time.sleep(0.1)
        resp = requests.get(json_url, headers=SEC_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        items = resp.json().get("items", [])
        for item in items:
            name = item.get("name", "")
            doc_type = item.get("type", "")
            # Primary Form 4 XML - not the index itself
            if (name.endswith(".xml") and
                "index" not in name.lower() and
                doc_type in ("4", "4/A", "")):
                return f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{name}"
        # Fallback: any non-index XML
        for item in items:
            name = item.get("name", "")
            if name.endswith(".xml") and "index" not in name.lower():
                return f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{name}"
    except Exception as e:
        print(f"[EDGAR] Index error for {accession_no}: {e}")
    return None


def _parse_form4(xml_url):
    try:
        time.sleep(0.15)
        resp = requests.get(xml_url, headers=SEC_HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        content = resp.content.decode("utf-8", errors="ignore")

        # Try direct parse first
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            m = re.search(r"(<ownershipDocument.*?</ownershipDocument>)", content, re.DOTALL)
            if not m:
                return []
            root = ET.fromstring(m.group(1))

        ticker_el = root.find(".//issuerTradingSymbol")
        ticker = (ticker_el.text or "").strip().upper() if ticker_el is not None else ""
        if not ticker or not re.match(r"^[A-Z]{1,6}$", ticker):
            return []

        name_el  = root.find(".//rptOwnerName")
        title_el = root.find(".//officerTitle")
        insider  = (name_el.text  or "Unknown").strip() if name_el  is not None else "Unknown"
        title    = (title_el.text or "").strip()         if title_el is not None else ""
        period   = (root.findtext(".//periodOfReport") or "").strip()

        rows = []
        for txn in root.findall(".//nonDerivativeTransaction"):
            code = (txn.findtext(".//transactionCode") or "").strip()
            if code != "P":
                continue
            try:
                shares = float((txn.findtext(".//transactionShares/value")        or "0").replace(",", ""))
                price  = float((txn.findtext(".//transactionPricePerShare/value") or "0").replace(",", ""))
                date   = (txn.findtext(".//transactionDate/value") or period).strip()
            except ValueError:
                continue
            value = shares * price
            if value < 1000:
                continue
            rows.append({
                "FilingDate":   period,
                "TradeDate":    date,
                "Ticker":       ticker,
                "Insider":      insider,
                "Title":        title,
                "TradeType":    "P - Purchase",
                "Price":        round(price, 4),
                "Qty":          shares,
                "Value":        round(value, 2),
                "OwnChangePct": 0.0,
            })
        return rows

    except Exception as e:
        print(f"[EDGAR] Parse error {xml_url}: {e}")
        return []


def get_insider_buys(mode="daily"):
    days_map  = {"daily": 3, "weekly": 7, "monthly": 30, "test": 7}
    days_back = days_map.get(mode, 3)
    print(f"[EDGAR] Mode={mode}, days_back={days_back}")

    try:
        hits = _search_form4(days_back)
    except Exception as e:
        print(f"[EDGAR] Search failed: {e}")
        return pd.DataFrame()

    all_rows  = []
    attempted = 0
    for hit in hits[:100]:
        src = hit.get("_source", {})
        acc = src.get("accession_no", "")
        if not acc:
            continue

        # Try to get CIK from source directly, fall back to parsing accession
        cik = str(src.get("entity_id", "") or src.get("cik", "") or "").strip().lstrip("0")
        if not cik:
            parts = acc.split("-")
            cik   = parts[0].lstrip("0") if parts else ""
        if not cik:
            continue

        xml_url = _get_xml_url(cik, acc)
        if not xml_url:
            continue

        attempted += 1
        rows = _parse_form4(xml_url)
        all_rows.extend(rows)

    print(f"[EDGAR] Attempted {attempted} XMLs, found {len(all_rows)} purchase rows")

    if not all_rows:
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
    print(f"[EDGAR] Historical backfill: {days_back} days")
    try:
        hits = _search_form4(days_back)
    except Exception as e:
        print(f"[EDGAR] Historical search failed: {e}")
        return pd.DataFrame()

    min_val  = min_value_k * 1000
    all_rows = []
    for hit in hits[:300]:
        src = hit.get("_source", {})
        acc = src.get("accession_no", "")
        if not acc:
            continue
        cik = str(src.get("entity_id", "") or "").strip().lstrip("0")
        if not cik:
            parts = acc.split("-")
            cik   = parts[0].lstrip("0") if parts else ""
        if not cik:
            continue
        xml_url = _get_xml_url(cik, acc)
        if xml_url:
            all_rows.extend([r for r in _parse_form4(xml_url) if r.get("Value", 0) >= min_val])

    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    return df.drop_duplicates(subset=["Ticker", "Insider", "TradeDate", "Value"]).reset_index(drop=True)
