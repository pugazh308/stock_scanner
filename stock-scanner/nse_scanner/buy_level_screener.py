"""
Buy-level ("fallen quality") screener for the NSE universe.

This is the philosophical INVERSE of screener.py. The momentum screener
finds stocks already in a confirmed uptrend (close > 50DMA > 200DMA,
near highs, strong RS). This one finds quality stocks that have been
beaten down and are showing the FIRST signs of a base/reversal -- the
Redington-at-210 setup, not the Redington-at-320 chase.

Hard filters (a candidate must pass all of these):
  - enough history (same MIN_HISTORY_DAYS as the momentum screener)
  - minimum average daily traded value (same liquidity floor -- a fallen
    stock with no liquidity is a trap, not a bargain)
  - drawdown from 52-week high between MIN_DRAWDOWN and MAX_DRAWDOWN:
    down enough to be interesting, not so destroyed that the business is
    probably broken
  - RSI(14) below RSI_CEILING: not already running
  - close within NEAR_LOW_CEILING of the 52-week low: actually near the
    floor, not halfway down and still falling fast
  - today's volume at least MIN_VOL_BREAKOUT_RATIO times the trailing
    20-day average: demand actually showing up today, not just price
    sitting near the low on ordinary volume

Reversal evidence (scored, not filtered -- these are the "first signs"):
  - basing: 20-day realized volatility contracting vs the prior 20 days
    (sellers exhausting; tight ranges near lows precede reversals)
  - selling exhaustion: down-day volume drying up vs 3 months ago
  - reclaim progress: close vs the 20DMA (first MA a bottoming stock
    reclaims; close > 20DMA near lows is the earliest trend evidence)
  - hammer/long-lower-shadow candle in the last N days at/near the low
    (demand showing up exactly where it should)

All score components are normalized to 0-100 BEFORE weighting so no
single raw-scale component can dominate (the scale-mismatch bug in the
momentum screener's scoring is deliberately not repeated here).

IMPORTANT: this screener produces a WATCHLIST, not entries. The correct
use is: alert on these names, then wait for a confirmed bullish daily
candle at support with volume >= the 10-day average before entering.
The screener finds the zone; the candle triggers the trade.
"""

MIN_AVG_DAILY_TURNOVER = 1_00_00_000  # INR 1 crore/day, same floor as screener.py
MIN_HISTORY_DAYS = 210

# --- Hard filter bounds ---
MIN_DRAWDOWN_PCT = 25.0    # must be at least this far below the 52w high
MAX_DRAWDOWN_PCT = 60.0    # beyond this, assume the business may be broken
RSI_CEILING = 55.0         # not already running. A stock basing sideways after a
                           # fall naturally recovers to RSI ~50-55; stocks that are
                           # actually running again sit at 60+. Filtering at 50
                           # would exclude names at the exact moment the first
                           # reversal evidence appears.
NEAR_LOW_CEILING_PCT = 25.0  # close must be within this % of the 52w low
MIN_VOL_BREAKOUT_RATIO = 2.0  # today's volume must be >= 2x the trailing 20d
                               # average -- same breakout signature the momentum
                               # screener requires, applied here to today's demand
                               # rather than a chase-the-trend confirmation

# --- Reversal-evidence lookbacks ---
HAMMER_LOOKBACK_DAYS = 10
HAMMER_SHADOW_BODY_RATIO = 2.0  # lower shadow >= 2x body (Nison's hammer rule)

WEIGHTS = {
    "basing": 0.30,             # volatility contraction near lows
    "selling_exhaustion": 0.25, # down-volume drying up
    "reclaim_progress": 0.25,   # close vs 20DMA
    "hammer_signal": 0.20,      # bullish candle evidence at the low
}


def _rsi(close, period=14):
    """Wilder's RSI. Returns the latest value, or None if not computable."""
    s = close.dropna()
    if len(s) < period + 1:
        return None
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _clamp01(x):
    return min(max(x, 0.0), 1.0)


def _basing_score(close):
    """0-100. Higher = recent 20d realized volatility has contracted vs the
    volatility of the preceding ~4 months (the decline phase). Comparing
    against the decline -- not against the immediately prior 20 days -- means
    a base that is 2+ months old still scores well; comparing adjacent 20d
    windows would read a mature quiet base as "no contraction" since both
    windows sit inside the base."""
    pct = close.pct_change().dropna()
    if len(pct) < 100:
        return 0.0
    recent = float(pct.tail(20).std())
    decline_phase = float(pct.tail(100).head(80).std())  # days 20-100 back
    if decline_phase <= 0:
        return 0.0
    contraction = 1.0 - (recent / decline_phase)  # +ve when quieter now
    # 40%+ contraction vs the decline maps to a full score; expansion -> 0.
    return _clamp01(contraction / 0.40) * 100.0


def _selling_exhaustion_score(close, volume):
    """0-100. Higher = volume on down days recently is much lighter than
    volume on down days ~3 months ago (sellers running out)."""
    pct = close.pct_change()
    down_mask = pct < 0
    down_vol = volume.where(down_mask).dropna()
    if len(down_vol) < 30:
        return 0.0
    recent_down_vol = float(down_vol.tail(10).mean())
    older_down_vol = float(down_vol.tail(60).head(30).mean())
    if older_down_vol <= 0:
        return 0.0
    drying = 1.0 - (recent_down_vol / older_down_vol)
    # 50%+ drying maps to a full score.
    return _clamp01(drying / 0.50) * 100.0


def _reclaim_progress_score(close):
    """0-100. Where is the close relative to the 20DMA? Reclaiming the
    20DMA is the first objective trend evidence for a bottoming stock.
    close 5%+ below 20DMA -> 0; at the 20DMA -> ~62; 3%+ above -> 100."""
    if len(close) < 20:
        return 0.0
    dma20 = float(close.tail(20).mean())
    if dma20 <= 0:
        return 0.0
    gap = (float(close.iloc[-1]) / dma20 - 1.0)  # e.g. +0.02 = 2% above
    # Map [-5%, +3%] linearly onto [0, 100].
    return _clamp01((gap + 0.05) / 0.08) * 100.0


def _hammer_signal_score(df):
    """0-100. Did a hammer / long-lower-shadow candle print in the last
    HAMMER_LOOKBACK_DAYS, with its low at/near the recent low? Scores the
    best (most recent, most textbook) such candle; 0 if none."""
    tail = df.tail(HAMMER_LOOKBACK_DAYS)
    if tail.empty:
        return 0.0
    window_low = float(df["Low"].tail(60).min())
    if window_low <= 0:
        return 0.0

    best = 0.0
    for _, row in tail.iterrows():
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        body = abs(c - o)
        lower_shadow = min(o, c) - l
        candle_range = h - l
        if candle_range <= 0 or body <= 0:
            continue
        # Textbook hammer: long lower shadow, small body near the top.
        if lower_shadow < HAMMER_SHADOW_BODY_RATIO * body:
            continue
        # The hammer only means something if it printed near the lows.
        if l > window_low * 1.05:  # low must be within 5% of the 60d low
            continue
        shadow_quality = _clamp01(lower_shadow / (candle_range * 0.66))
        close_strength = 1.0 if c >= o else 0.7  # green hammer > red hammer
        best = max(best, shadow_quality * close_strength * 100.0)
    return best


def compute_buy_level_metrics(price_data):
    """Computes buy-level metrics for every ticker with enough history.
    Filters are NOT applied here (same separation of concerns as
    screener.py: compute everything, filter/rank in rank_buy_level)."""
    rows = []
    for ticker, df in price_data.items():
        close = df["Close"].dropna()
        volume = df["Volume"].dropna()
        if len(close) < MIN_HISTORY_DAYS or len(volume) < MIN_HISTORY_DAYS:
            continue

        last_close = float(close.iloc[-1])
        high_52w = float(close.tail(252).max())
        low_52w = float(close.tail(252).min())
        dma200 = float(close.tail(200).mean())
        avg_daily_turnover = float((close.tail(20) * volume.tail(20)).mean())

        vol_avg_20 = float(volume.tail(21).iloc[:-1].mean())
        vol_today = float(volume.iloc[-1])
        vol_breakout_ratio = (vol_today / vol_avg_20) if vol_avg_20 else 0.0

        if high_52w <= 0 or low_52w <= 0:
            continue

        drawdown_pct = (1.0 - last_close / high_52w) * 100.0
        above_low_pct = (last_close / low_52w - 1.0) * 100.0
        rsi14 = _rsi(close)

        rows.append({
            "ticker": ticker.replace(".NS", ""),
            "last_close": round(last_close, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "dma200": round(dma200, 2),
            "below_200dma": last_close < dma200,
            "drawdown_pct": round(drawdown_pct, 2),
            "above_low_pct": round(above_low_pct, 2),
            "rsi14": round(rsi14, 2) if rsi14 is not None else None,
            "avg_daily_turnover": avg_daily_turnover,
            "vol_breakout_ratio": round(vol_breakout_ratio, 2),
            "_basing": round(_basing_score(close), 2),
            "_selling_exhaustion": round(_selling_exhaustion_score(close, volume), 2),
            "_reclaim_progress": round(_reclaim_progress_score(close), 2),
            "_hammer_signal": round(_hammer_signal_score(df), 2),
        })
    return rows


def rank_buy_level(rows, top_n=15):
    """Applies the buy-level hard filters, scores survivors on normalized
    0-100 reversal-evidence components, returns top_n by score desc."""
    survivors = []
    for r in rows:
        if r["avg_daily_turnover"] < MIN_AVG_DAILY_TURNOVER:
            continue
        if not (MIN_DRAWDOWN_PCT <= r["drawdown_pct"] <= MAX_DRAWDOWN_PCT):
            continue
        if r["rsi14"] is None or r["rsi14"] >= RSI_CEILING:
            continue
        if r["above_low_pct"] > NEAR_LOW_CEILING_PCT:
            continue
        if r["vol_breakout_ratio"] < MIN_VOL_BREAKOUT_RATIO:
            continue
        survivors.append(r)

    for r in survivors:
        r["score"] = round(
            r["_basing"] * WEIGHTS["basing"]
            + r["_selling_exhaustion"] * WEIGHTS["selling_exhaustion"]
            + r["_reclaim_progress"] * WEIGHTS["reclaim_progress"]
            + r["_hammer_signal"] * WEIGHTS["hammer_signal"],
            2,
        )

    survivors.sort(key=lambda r: r["score"], reverse=True)
    return survivors[:top_n]
