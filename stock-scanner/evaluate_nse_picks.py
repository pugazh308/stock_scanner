"""
Run with: python evaluate_nse_picks.py

Checks outcomes for previously logged NSE picks (7/14/30/60-day return
snapshots, running max gain/drawdown, current return) and updates
data/nse_track_record.json in place. No email is sent -- same shape as
evaluate_and_learn.py for the US module.
"""

from nse_scanner.evaluate_picks import evaluate_picks

if __name__ == "__main__":
    evaluate_picks()
