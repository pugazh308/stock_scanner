# Insider Buying + Momentum Stock Scanner

Sends you a daily, weekly, and monthly email of stocks worth watching, based on:

1. **Insider buying** — execs/directors buying their own company's stock
   (pulled from SEC Form 4 filings via openinsider.com), weighted by dollar
   size and how senior the insider is, with a bonus for "cluster buys"
   (multiple insiders buying the same stock around the same time).
2. **Momentum overlay** — 1-month price return and relative strength vs the
   S&P 500 (SPY), plus recent volume trend.

Everything is combined into one score and ranked, top 15 per email.

It runs for free on GitHub Actions — no server, no laptop needed to be on.

## 1. Push this to GitHub

```bash
cd stock-scanner
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

(Or use GitHub's "Upload files" web UI if you'd rather not use git commands.)

## 2. Create a Gmail App Password

You'll send the email from your own Gmail using an "app password" (not your
real password):

1. Go to https://myaccount.google.com/security
2. Turn on 2-Step Verification if it isn't already on
3. Go to https://myaccount.google.com/apppasswords
4. Create a new app password (name it "stock scanner") — copy the 16-character code

## 3. Add GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these three:

| Secret name      | Value                                      |
|-------------------|---------------------------------------------|
| `EMAIL_FROM`      | your Gmail address                         |
| `EMAIL_PASSWORD`  | the 16-character app password from step 2  |
| `EMAIL_TO`        | the address you want the digest sent to (can be the same Gmail) |

## 4. Test it manually

Go to your repo's **Actions** tab → **Stock Scanner Digest** → **Run workflow**
→ pick a mode (daily/weekly/monthly) → Run. Check the logs, then check your inbox.

## 5. Let it run on schedule

Once the manual test works, it'll run automatically:
- **Daily**: weekdays at 12:00 UTC (~8am ET, before market open)
- **Weekly**: every Monday at 12:00 UTC
- **Monthly**: the 1st of each month at 12:00 UTC

You can change these times by editing the `cron` lines in
`.github/workflows/scanner.yml`. (Use https://crontab.guru to build new ones.)

Note: GitHub Actions schedules can run a few minutes late during high load —
that's normal and not something to worry about.

## How it learns over time

Every time the scanner runs, it logs its picks (and *why* it picked them —
dollar value, insider seniority, cluster status, momentum) to
`data/track_record.json`, which the workflow commits back to your repo.

About 2 weeks later, a second step (`evaluate_and_learn.py`, runs right
after the digest each time) checks what those stocks actually did and
records the real return — both raw and relative to SPY — into the same file.

Once there are **at least 30 evaluated picks** (roughly 2-6 weeks of data
depending on mode), it starts nudging its own scoring weights in
`data/weights.json`: if cluster buys, senior-insider buys, or momentum
*actually* correlated with better returns, those factors get weighted up a
little; if not, they get weighted down. Nudges are small (5% per cycle) and
capped, so it takes sustained evidence to move a weight far — it won't
overreact to one good or bad week.

**Be realistic about this**: with maybe 10-15 picks a week, you won't have
a statistically meaningful sample for a couple of months. Until then, the
system is mostly just collecting data faithfully — that data collection is
the valuable part early on, not the (still negligible) weight adjustments.
You can check progress by reading `data/track_record.json` in your repo at
any time.



- `scanner/fetch_insider.py` — change which OpenInsider views are used
  (e.g. require a higher dollar threshold, focus only on CEO/CFO buys)
- `scanner/scorer.py` — tune `TITLE_WEIGHTS` or the scoring formula
- `scanner/momentum.py` — add more indicators (RSI, moving averages, etc.)
- `main.py` — change `top_n` to email more/fewer stocks per digest

## Training a real model on historical data

Beyond the simple weight-nudging described above, you can train an actual
ML model (gradient-boosted trees via scikit-learn) instead of waiting
months for live data to accumulate:

1. Go to your repo's **Actions** tab → **Backfill Historical Data** → **Run workflow**
2. It pulls ~1 year of real historical insider purchases (configurable),
   looks up what each one's price actually did over the following 14 days
   using Yahoo Finance, and writes all of that into `data/track_record.json`
   as already-evaluated picks — typically several hundred real data points
   in one run, instead of the ~10-15/week you'd get organically.
3. It then trains a model on that data and saves it to `data/model.pkl`.
   From then on, `scanner/scorer.py` automatically uses the trained model
   to rank picks instead of the hand-tuned heuristic.
4. The regular daily/weekly/monthly runs keep retraining this model as more
   real outcomes come in (via `evaluate_and_learn.py`), so it keeps
   improving over time.

**Honest limitations of this approach:**
- It requires at least 50 usable historical samples before it'll train at
  all, and it reports cross-validated R² in the workflow logs every time —
  if that's negative (worse than just guessing the average), it refuses to
  use the model and falls back to the heuristic. Check the Actions logs
  after a backfill run to see this number; don't just assume it worked.
- The "cluster buy" detection in the backfill is an approximation (same
  ticker, multiple distinct insiders, anywhere in the pulled window) since
  precise date-windowed clustering would need a lot more scraping calls.
- OpenInsider's scraped data is "best effort" — occasional missing rows or
  format quirks are expected over a year of history. The script skips rows
  it can't parse rather than failing the whole run.
- A model trained on ~1 year of data has only seen one market regime. It
  may not generalize well if conditions change (rate environment, sector
  rotation, etc.) — this is true of any backtested strategy, not unique to
  this script.

## Limitations to know about

- OpenInsider and Yahoo Finance are free, unofficial data sources scraped via
  their public pages — they can occasionally change format or rate-limit,
  which would break the script until you fix the matching code. This isn't
  meant to replace a professional data feed.
- This is a watchlist tool, not investment advice or an auto-trader. It
  doesn't place trades or know your portfolio/risk tolerance.
- If a Monday happens to also be the 1st of the month, you'll get 3 emails
  that morning (daily + weekly + monthly) — that's expected, not a bug.
