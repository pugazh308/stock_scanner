"""
A deliberately simple learning rule -- not deep ML, but transparent and hard
to overfit with small data:

For each scoring factor (cluster bonus, title seniority, momentum), split
evaluated picks into "above median" vs "below median" for that factor, and
compare their average actual return. If the above-median group did better,
nudge that factor's weight up slightly; if not, nudge it down. Steps are
small (5%) and clamped, so it takes sustained evidence over many cycles to
move a weight very far.

Requires MIN_SAMPLES evaluated picks before adjusting anything -- with
fewer than that, differences are noise, not signal.
"""

from statistics import median

from scanner.store import load_track_record, load_weights, save_weights

MIN_SAMPLES = 30
STEP = 0.05          # 5% nudge per learning cycle
MIN_MULT, MAX_MULT = 0.5, 2.0  # how far a weight can drift from its default


def _split_and_compare(records, key):
    vals = [r[key] for r in records if r.get(key) is not None]
    if len(vals) < 4:
        return None
    m = median(vals)
    above = [r["outcome_return_pct"] for r in records if r.get(key) is not None and r[key] > m]
    below = [r["outcome_return_pct"] for r in records if r.get(key) is not None and r[key] <= m]
    if not above or not below:
        return None
    avg_above = sum(above) / len(above)
    avg_below = sum(below) / len(below)
    return avg_above - avg_below  # positive => high values of this factor outperformed


def update_weights():
    records = load_track_record()
    evaluated = [r for r in records if r.get("evaluated") and r.get("outcome_return_pct") is not None]

    if len(evaluated) < MIN_SAMPLES:
        print(f"Only {len(evaluated)} evaluated picks so far (need {MIN_SAMPLES}+) -- "
              f"collecting more data before adjusting weights.")
        return

    weights = load_weights()
    changes = []

    # Cluster bonus: did cluster buys actually outperform non-cluster buys?
    cluster_vals = [(1.0 if r.get("is_cluster") else 0.0) for r in evaluated]
    diff = _split_and_compare(
        [{"x": v, "outcome_return_pct": r["outcome_return_pct"]} for v, r in zip(cluster_vals, evaluated)],
        "x",
    )
    if diff is not None:
        direction = 1 if diff > 0 else -1
        old = weights["cluster_bonus"]
        new = max(MIN_MULT, min(MAX_MULT * 1.5, old * (1 + direction * STEP)))
        weights["cluster_bonus"] = round(new, 4)
        changes.append(f"cluster_bonus: {old} -> {new} (avg return diff {diff:+.2f}%)")

    # Insider seniority: did higher avg_title_weight picks outperform?
    diff = _split_and_compare(evaluated, "avg_title_weight")
    if diff is not None:
        direction = 1 if diff > 0 else -1
        for key in ["ceo", "cfo", "coo", "pres", "chairman", "cob", "dir", "officer", "vp", "gc", "10%"]:
            old = weights["title_weights"].get(key, 1.0)
            new = max(MIN_MULT, min(MAX_MULT * 2, old * (1 + direction * STEP * 0.5)))
            weights["title_weights"][key] = round(new, 4)
        changes.append(f"title_weights nudged {'up' if direction > 0 else 'down'} (avg return diff {diff:+.2f}%)")

    # Momentum: did higher momentum_score picks outperform?
    diff = _split_and_compare(evaluated, "momentum_score")
    if diff is not None:
        direction = 1 if diff > 0 else -1
        old = weights["rel_strength_coef"]
        new = max(0.1, min(2.0, old * (1 + direction * STEP)))
        weights["rel_strength_coef"] = round(new, 4)
        changes.append(f"rel_strength_coef: {old} -> {new} (avg return diff {diff:+.2f}%)")

    save_weights(weights)
    print(f"Updated weights based on {len(evaluated)} evaluated picks:")
    for c in changes:
        print(f"  - {c}")


if __name__ == "__main__":
    update_weights()
