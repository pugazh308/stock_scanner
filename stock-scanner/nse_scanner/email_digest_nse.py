"""
Builds and sends the HTML digest for the NSE price-action watchlist.
Reuses the same SMTP env vars / secrets as scanner/email_digest.py.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

import yfinance as yf


def _company_name(ticker):
    try:
        info = yf.Ticker(f"{ticker}.NS").info
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker


def _fmt_pct(v):
    if v is None:
        return "-"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def _fmt_inr(v):
    if v is None:
        return "-"
    return f"₹{v:,.2f}"


def _buy_level_rows(buy_ranked):
    rows = ""
    for r in buy_ranked:
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;"><b>{r['ticker']}</b></td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_inr(r['last_close'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">-{r['drawdown_pct']:.1f}%</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">+{r['above_low_pct']:.1f}%</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['rsi14']:.0f}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['vol_breakout_ratio']:.2f}x</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['_basing']:.0f}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['_hammer_signal']:.0f}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;"><b>{r['score']}</b></td>
        </tr>"""
    if not rows:
        rows = "<tr><td colspan='9' style='padding:12px;'>No qualifying buy-level setups today.</td></tr>"
    return rows


def build_html(ranked, buy_ranked=None):
    today = date.today().isoformat()
    buy_ranked = buy_ranked or []

    rows = ""
    for r in ranked:
        company = _company_name(r["ticker"])
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;"><b>{r['ticker']}</b></td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{company}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_inr(r['last_close'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_pct(r['rel_strength_1m'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_pct(r['rel_strength_3m'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['vol_breakout_ratio']:.2f}x</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['pct_off_52w_high']:.1f}%</td>
          <td style="padding:8px;border-bottom:1px solid #eee;"><b>{r['score']}</b></td>
        </tr>"""

    if not rows:
        rows = "<tr><td colspan='8' style='padding:12px;'>No qualifying stocks found today.</td></tr>"

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#222;">
      <h2>NSE Daily Watchlist -- {today}</h2>
      <p style="color:#555;">
        NIFTY 500 universe, screened for a confirmed uptrend (price above the
        50-day and 200-day moving averages), then ranked by relative strength
        vs the Nifty 50 (3-month and 1-month), volume breakout vs the
        20-day average, and proximity to the 52-week high. Not financial
        advice -- a price-action watchlist only.
      </p>
      <table style="border-collapse:collapse;width:100%;font-size:14px;">
        <tr style="background:#f5f5f5;text-align:left;">
          <th style="padding:8px;">Ticker</th>
          <th style="padding:8px;">Company</th>
          <th style="padding:8px;">Last Price</th>
          <th style="padding:8px;">1mo RS vs Nifty</th>
          <th style="padding:8px;">3mo RS vs Nifty</th>
          <th style="padding:8px;">Vol Breakout</th>
          <th style="padding:8px;">Off 52w High</th>
          <th style="padding:8px;">Score</th>
        </tr>
        {rows}
      </table>

      <h2 style="margin-top:32px;">Buy-Level Watchlist (Fallen Quality)</h2>
      <p style="color:#555;">
        The inverse screen: liquid names 25-60% off their 52-week high,
        within 25% of the 52-week low, RSI under 55, today's volume at
        least 2x the trailing 20-day average, ranked on reversal
        evidence -- volatility contraction vs the decline phase, down-day
        volume drying up, 20DMA reclaim progress, and hammer candles at
        the lows. <b>These are NOT entries.</b> Set alerts, then wait for
        a confirmed bullish daily candle at support with volume at or
        above the 10-day average before trading anything here.
      </p>
      <table style="border-collapse:collapse;width:100%;font-size:14px;">
        <tr style="background:#f5f5f5;text-align:left;">
          <th style="padding:8px;">Ticker</th>
          <th style="padding:8px;">Last Price</th>
          <th style="padding:8px;">Off 52w High</th>
          <th style="padding:8px;">Above 52w Low</th>
          <th style="padding:8px;">RSI</th>
          <th style="padding:8px;">Vol Breakout</th>
          <th style="padding:8px;">Basing</th>
          <th style="padding:8px;">Hammer</th>
          <th style="padding:8px;">Score</th>
        </tr>
        {_buy_level_rows(buy_ranked)}
      </table>

      <p style="color:#999;font-size:12px;margin-top:20px;">
        Data: NSE (NIFTY 500 universe), prices via Yahoo Finance. This is a
        price-action shortlist only -- ask directly for the 10-point
        qualitative writeup (catalyst, fundamentals, ownership, valuation,
        bull/bear case) on any name here before trading it.
        Generated automatically -- always do your own research before trading.
      </p>
    </body>
    </html>
    """
    return html


def send_email(ranked, buy_ranked=None):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_PASSWORD"]
    recipient = os.environ.get("EMAIL_TO", sender)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"NSE Daily Watchlist -- {date.today().isoformat()}"
    msg["From"] = sender
    msg["To"] = recipient

    html_body = build_html(ranked, buy_ranked)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"[NSE] Sent daily digest to {recipient}: "
          f"{len(ranked)} momentum + {len(buy_ranked or [])} buy-level tickers.")
