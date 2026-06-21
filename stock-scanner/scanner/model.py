"""
Trains a real model (scikit-learn GradientBoostingRegressor) on whatever
evaluated picks exist in data/track_record.json, predicting forward return
relative to SPY from the same features the heuristic scorer uses.

Why gradient boosting with shallow trees: it can capture interactions
between features (e.g. "cluster buys only matter when momentum is also
positive") that the linear heuristic in scanner/learn.py can't, while still
being hard to overfit badly if we keep max_depth and n_estimators small
relative to sample size.

Falls back gracefully: if scikit-learn isn't available or there isn't
enough data, scanner/scorer.py just uses the hand-tuned weights instead.
"""

import os
import joblib
import numpy as np

from scanner.store import load_track_record, DATA_DIR

MODEL_PATH = os.path.join(DATA_DIR, "model.pkl")
MIN_SAMPLES = 50
FEATURES = ["value_component", "avg_title_weight", "is_cluster", "rel_strength_1m_at_pick"]


def _to_matrix(records):
    X, y = [], []
    for r in records:
        if any(r.get(f) is None for f in FEATURES):
            continue
        if r.get("outcome_rel_to_spy_pct") is None:
            continue
        row = [
            r["value_component"],
            r["avg_title_weight"],
            1.0 if r["is_cluster"] else 0.0,
            r["rel_strength_1m_at_pick"],
        ]
        X.append(row)
        y.append(r["outcome_rel_to_spy_pct"])
    return np.array(X), np.array(y)


def train_model():
    records = load_track_record()
    evaluated = [r for r in records if r.get("evaluated")]
    X, y = _to_matrix(evaluated)

    if len(X) < MIN_SAMPLES:
        print(f"Only {len(X)} usable evaluated samples (need {MIN_SAMPLES}+) -- skipping model training.")
        return None

    try:
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import cross_val_score
    except ImportError:
        print("scikit-learn not installed -- skipping model training.")
        return None

    # Shallow, few trees: deliberately conservative given modest sample sizes.
    model = GradientBoostingRegressor(
        n_estimators=min(100, len(X) * 2),
        max_depth=2,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )

    # 5-fold CV so we can report honest out-of-sample performance, not just
    # training-set fit (which would look great and mean nothing).
    cv_scores = cross_val_score(model, X, y, cv=min(5, len(X) // 10 or 1), scoring="r2")
    print(f"Cross-validated R^2: {cv_scores.mean():.3f} (+/- {cv_scores.std():.3f}) "
          f"across {len(cv_scores)} folds, {len(X)} samples.")
    if cv_scores.mean() < 0:
        print("WARNING: model performs worse than just predicting the average -- "
              "not using it yet. Heuristic weights will keep being used until "
              "there's enough data for the model to actually generalize.")
        return None

    model.fit(X, y)
    os.makedirs(DATA_DIR, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"Trained model on {len(X)} samples and saved to {MODEL_PATH}.")
    return model


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        return joblib.load(MODEL_PATH)
    except Exception:
        return None


def predict_score(model, value_component, avg_title_weight, is_cluster, rel_strength_1m):
    x = np.array([[value_component, avg_title_weight, 1.0 if is_cluster else 0.0, rel_strength_1m or 0.0]])
    return float(model.predict(x)[0])


if __name__ == "__main__":
    train_model()
