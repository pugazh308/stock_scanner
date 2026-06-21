"""
Run with: python evaluate_and_learn.py

Checks back on picks made HOLD_DAYS+ ago, records what actually happened,
and (once there's enough evaluated data) nudges the scoring weights.
Run this on a schedule separate from main.py -- it doesn't send any email,
it just updates data/track_record.json and data/weights.json.
"""

from scanner.evaluate import evaluate_matured_picks
from scanner.learn import update_weights
from scanner.model import train_model

if __name__ == "__main__":
    evaluate_matured_picks()
    update_weights()
    train_model()
