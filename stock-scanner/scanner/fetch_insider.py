"""
Fetches insider-buying data directly from SEC EDGAR Form 4 filings.
Uses SEC EDGAR RSS feed - most reliable method for GitHub Actions.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import time
import re

SEC_HEADERS = {
    "User-Agent": "StockResearchBot pugazh308research@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}
EDGAR_BASE = "https://www.sec.gov"


def _get_rss_filing_urls(count=100):
    url = (f"{EDGAR_BASE}/cgi-bin/browse-edgar"
           f"?action=getcurrent&type=4&dateb=&owner=include"
           f"&count={count}&search_text=&output=atom")
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        urls = []
        for entry in entries:
            link = entry.find("atom:link", ns)
            if link is not None:
                href = link.get("href", "")
                if "Archives/edgar/data" in href:
                    urls.append(href)
        print(f"[EDGAR] RSS: {len(urls)} Form 4 filings found")
        return urls
    except Exception as e:
        print(f"[EDGAR] RSS error: {e}")
        return []


def _parse_index_url(index_url):
    """Extract CIK and accession number from EDGAR index URL."""
    m = re.search(r"/Archives/edgar/data/(\d+)/(\d{18})", index_url)
    if m:
        cik = m.group(1)
        raw = m.group(2)
        acc = f"{raw[:10]}-{raw[10:12]}-{raw[12:]}"
        return cik, acc
    m2 = re.search(r"/Archives/edgar/data/(\d+)/([\d]+-[\d]+-[\d]+)", index_url)
    if m2:
        return m2.group(1), m2.group(2)
    return None, None


def _get_xml_url(cik, accession_no):
    acc_clean = accession_no.replace("-", "")
    json_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{accession_no}-index.json"
    try:
        resp = requests.get(json_url, headers=SEC_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        for item in resp.json().get("items", []):
            name = item.get("name", "")
            dtype = item.get("type", "")
            if name.endswith(".xml") and "index" not in name.lower() and dtype in ("4", "4/A", ""):
                return f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{name}"
        for item in resp.json().get("items", []):
            name = item.get("name", "")
            if name.endswith(".xml") and "index" not in name.lower():
                return f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{acc_clean}/{name}"
    except Exception as e:
        print(f"[EDGAR] Index error {accession_no}: {e}")
    return None


def _parse_form4(xml_url):
    try:
        time.sleep(0.12)
        resp = requests.get(xml_url, headers=SEC_HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        content = resp.content.decode("utf-8", errors="ignore")
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
        insider  = (name_el.text or "Unknown").strip() if name_el is not None else "Unknown"
        title    = (title_el.text or "").strip() if title_el is not None else ""
        period   = (root.findtext(".//periodOfReport") or "").strip()

        rows = []
        for txn in root.findall(".//nonDerivativeTransaction"):
            code = (txn.findtext(".//transactionCode") or "").strip()
            if code != "P":
                continue
            try:
                shares = float((txn.findtext(".//transactionShares/value") or "0").replace(",", ""))
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
        print(f"[EDGAR] Parse error: {e}")
        return []


def get_insider_buys(mode="daily"):
    count_map = {"daily": 80, "weekly": 200, "monthly": 400, "test": 80}
    count = count_map.get(mode, 80)
    print(f"[EDGAR] Mode={mode}, fetching {count} recent Form 4s via RSS...")

    urls = _get_rss_filing_urls(count)
    if not urls:
        return pd.DataFrame()

    all_rows = []
    attempted = 0
    for index_url in urls:
        cik, acc = _parse_index_url(index_url)
        if not cik or not acc:
            continue
        xml_url = _get_xml_url(cik, acc)
        if not xml_url:
            continue
        attempted += 1
        all_rows.extend(_parse_form4(xml_url))

    print(f"[EDGAR] Parsed {attempted} XMLs → {len(all_rows)} purchase transactions")

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["Ticker", "Insider", "TradeDate", "Value"])
    df = df.sort_values("Value", ascending=False).reset_index(drop=True)
    print(f"[EDGAR] Final: {len(df)} purchases across {df['Ticker'].nunique()} tickers")
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
    print(f"[EDGAR] Historical backfill via RSS...")
    urls = _get_rss_filing_urls(count=400)
    min_val = min_value_k * 1000
    all_rows = []
    for index_url in urls:
        cik, acc = _parse_index_url(index_url)
        if not cik or not acc:
            continue
        xml_url = _get_xml_url(cik, acc)
        if xml_url:
            all_rows.extend([r for r in _parse_form4(xml_url) if r.get("Value", 0) >= min_val])
    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    return df.drop_duplicates(subset=["Ticker", "Insider", "TradeDate", "Value"]).reset_index(drop=True)
