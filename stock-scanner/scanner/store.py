"""
Tiny JSON-file persistence layer. Files live in data/ and get committed back
to the git repo by the GitHub Actions workflow after each run, so they
persist across runs (GitHub Actions containers are otherwise stateless).
"""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TRACK_FILE = os.path.join(DATA_DIR, "track_record.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "weights.json")

DEFAULT_WEIGHTS = {
    "title_weights": {
        "ceo": 3.0, "cfo": 3.0, "coo": 2.5, "pres": 2.5, "chairman": 2.0,
        "cob": 2.0, "dir": 1.5, "officer": 1.5, "vp": 1.2, "gc": 1.0, "10%": 0.7,
    },
    "value_divisor": 50000.0,   # higher = insider $ amount matters less
    "cluster_bonus": 1.5,
    "rel_strength_coef": 0.6,
    "volume_trend_coef": 0.1,
}


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    _ensure_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_track_record():
    return load_json(TRACK_FILE, [])


def save_track_record(records):
    save_json(TRACK_FILE, records)


def load_weights():
    saved = load_json(WEIGHTS_FILE, None)
    if saved is None:
        return DEFAULT_WEIGHTS
    # Backfill any new keys added since the file was last saved.
    merged = dict(DEFAULT_WEIGHTS)
    merged.update(saved)
    merged["title_weights"] = {**DEFAULT_WEIGHTS["title_weights"], **saved.get("title_weights", {})}
    return merged


def save_weights(weights):
    save_json(WEIGHTS_FILE, weights)
