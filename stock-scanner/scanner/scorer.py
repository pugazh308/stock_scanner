"""
Combines insider-buying signal with momentum into one ranked score per ticker.

Weights are loaded from data/weights.json (created/updated by scanner/learn.py).
If that file doesn't exist yet, sensible defaults are used. This lets the
scoring formula adapt over time instead of being permanently hardcoded.
"""

from scanner.store import load_weights
from scanner.model import load_model, predict_score


def _title_weight(title, title_weights):
    if not isinstance(title, str):
        return 1.0
    title_l = title.lower()
    best = 1.0
    for key, weight in title_weights.items():
        if key in title_l:
            best = max(best, weight)
    return best


def build_ranking(insider_df, cluster_tickers, momentum_stats, top_n=15):
    """
    Returns a list of dicts sorted by score descending (length <= top_n).
    Each dict includes raw component values (not just the final score) so
    that scanner/learn.py can later correlate components with outcomes.
    """
    if insider_df.empty:
        return []

    weights = load_weights()
    title_weights = weights["title_weights"]
    model = load_model()

    grouped = {}
    for _, row in insider_df.iterrows():
        ticker = row.get("Ticker")
        if not ticker:
            continue
        value = row.get("Value", 0) or 0
        weight = _title_weight(row.get("Title", ""), title_weights)
        entry = grouped.setdefault(ticker, {
            "ticker": ticker,
            "company": row.get("Company", ""),
            "total_value": 0.0,
            "insiders": set(),
            "titles": set(),
        })
        entry["total_value"] += value
        entry["insiders"].add(row.get("Insider", ""))
        if row.get("Title"):
            entry["titles"].add(row.get("Title"))
        entry["_weight_sum"] = entry.get("_weight_sum", 0) + weight

    ranked = []
    for ticker, entry in grouped.items():
        n_insiders = len(entry["insiders"])
        avg_title_weight = entry["_weight_sum"] / max(n_insiders, 1)
        is_cluster = n_insiders > 1 or ticker in cluster_tickers
        cluster_bonus = weights["cluster_bonus"] if is_cluster else 1.0

        value_component = min(entry["total_value"] / weights["value_divisor"], 20)
        insider_score = value_component * avg_title_weight * cluster_bonus

        mom = momentum_stats.get(ticker, {})
        rel_strength = mom.get("rel_strength_1m") or 0
        volume_trend = mom.get("volume_trend") or 0
        momentum_score = (rel_strength * weights["rel_strength_coef"]) + \
                          (volume_trend * weights["volume_trend_coef"])

        heuristic_score = insider_score + momentum_score

        if model is not None:
            # Model predicts expected % outperformance vs SPY over the hold
            # period -- a more directly interpretable number than the
            # heuristic's arbitrary point scale.
            total_score = predict_score(model, value_component, avg_title_weight, is_cluster, rel_strength)
            scoring_method = "model"
        else:
            total_score = heuristic_score
            scoring_method = "heuristic"

        ranked.append({
            "ticker": ticker,
            "company": entry["company"],
            "total_value": entry["total_value"],
            "n_insiders": n_insiders,
            "titles": ", ".join(sorted(entry["titles"])),
            "is_cluster": is_cluster,
            "return_1m": mom.get("return_1m"),
            "rel_strength_1m": mom.get("rel_strength_1m"),
            "volume_trend": mom.get("volume_trend"),
            "last_price": mom.get("last_price"),
            # raw components, kept for the learning step later:
            "_value_component": round(value_component, 4),
            "_avg_title_weight": round(avg_title_weight, 4),
            "_is_cluster": is_cluster,
            "_insider_score": round(insider_score, 4),
            "_momentum_score": round(momentum_score, 4),
            "scoring_method": scoring_method,
            "score": round(total_score, 2),
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:top_n]
