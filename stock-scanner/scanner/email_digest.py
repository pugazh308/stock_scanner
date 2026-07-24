"""
Builds an HTML email digest from the ranked stock list and sends it via
SMTP using Gmail (or any SMTP provider) with credentials from environment
variables / GitHub Actions secrets.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

MODE_LABELS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}


def _fmt_money(v):
    if v is None:
        return "-"
    return f"${v:,.0f}"


def _fmt_pct(v):
    if v is None:
        return "-"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def build_html(ranked, mode):
    label = MODE_LABELS.get(mode, mode.title())
    today = date.today().isoformat()

    rows = ""
    for r in ranked:
        cluster_tag = " 🧩 cluster" if r["is_cluster"] else ""
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;"><b>{r['ticker']}</b></td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['company']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_money(r['total_value'])}{cluster_tag}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['n_insiders']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{r['titles']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_pct(r['return_1m'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;">{_fmt_pct(r['rel_strength_1m'])}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;"><b>{r['score']}</b></td>
        </tr>"""

    if not rows:
        rows = "<tr><td colspan='8' style='padding:12px;'>No qualifying stocks found today.</td></tr>"

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;color:#222;">
      <h2>{label} Insider + Momentum Digest -- {today}</h2>
      <p style="color:#555;">
        Ranked by a blend of insider buying conviction (dollar size, insider
        seniority, multiple-insider clusters) and 1-month price momentum
        relative to the S&amp;P 500. Not financial advice -- just a watchlist.
      </p>
      <table style="border-collapse:collapse;width:100%;font-size:14px;">
        <tr style="background:#f5f5f5;text-align:left;">
          <th style="padding:8px;">Ticker</th>
          <th style="padding:8px;">Company</th>
          <th style="padding:8px;">Insider $ Bought</th>
          <th style="padding:8px;">#Insiders</th>
          <th style="padding:8px;">Title(s)</th>
          <th style="padding:8px;">1mo Return</th>
          <th style="padding:8px;">Rel. Strength vs SPY</th>
          <th style="padding:8px;">Score</th>
        </tr>
        {rows}
      </table>
      <p style="color:#999;font-size:12px;margin-top:20px;">
        Data: SEC Form 4 filings via SEC EDGAR, prices via Yahoo Finance.
        Generated automatically -- always do your own research before trading.
      </p>
    </body>
    </html>
    """
    return html


def send_email(ranked, mode):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_PASSWORD"]
    recipient = os.environ.get("EMAIL_TO", sender)
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    label = MODE_LABELS.get(mode, mode.title())
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{label} Insider + Momentum Digest -- {date.today().isoformat()}"
    msg["From"] = sender
    msg["To"] = recipient

    html_body = build_html(ranked, mode)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"Sent {label} digest to {recipient} with {len(ranked)} tickers.")
