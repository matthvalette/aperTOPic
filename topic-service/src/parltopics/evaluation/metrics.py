"""Metrics for multi-label and binary topic predictions. Pure Python, no I/O."""

from __future__ import annotations

from collections.abc import Sequence

Probabilities = dict[str, float]


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def multilabel_at_threshold(
    probs: Sequence[Probabilities], gold: Sequence[set[str]], threshold: float
) -> dict:
    """Micro and macro precision/recall/F1, exact match and Jaccard at one threshold."""
    tp = fp = fn = 0
    per_topic: dict[str, list[int]] = {}
    exact = 0
    jaccard = 0.0
    for p, g in zip(probs, gold):
        predicted = {k for k, v in p.items() if v >= threshold}
        for k in set(p) | g:
            counts = per_topic.setdefault(k, [0, 0, 0])
            if k in predicted and k in g:
                counts[0] += 1
            elif k in predicted:
                counts[1] += 1
            elif k in g:
                counts[2] += 1
        tp += len(predicted & g)
        fp += len(predicted - g)
        fn += len(g - predicted)
        exact += predicted == g
        union = predicted | g
        jaccard += len(predicted & g) / len(union) if union else 1.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    topic_rows = {}
    for k, (t_p, f_p, f_n) in per_topic.items():
        p_k = t_p / (t_p + f_p) if t_p + f_p else 0.0
        r_k = t_p / (t_p + f_n) if t_p + f_n else 0.0
        topic_rows[k] = {"support": t_p + f_n, "precision": p_k, "recall": r_k, "f1": _f1(p_k, r_k)}
    supported = [row for row in topic_rows.values() if row["support"] > 0]
    n = max(len(gold), 1)
    return {
        "threshold": threshold,
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": _f1(precision, recall),
        "macro_f1": sum(r["f1"] for r in supported) / len(supported) if supported else 0.0,
        "exact_match": exact / n,
        "mean_jaccard": jaccard / n,
        "labels_per_affair_predicted": (tp + fp) / n,
        "labels_per_affair_gold": (tp + fn) / n,
        "per_topic": topic_rows,
    }


def ranking_metrics(probs: Sequence[Probabilities], gold: Sequence[set[str]]) -> dict:
    """Threshold-free: is the top topic correct, are the gold topics near the top?"""
    top1 = recall3 = oracle_tp = oracle_n = 0.0
    for p, g in zip(probs, gold):
        ranked = sorted(p, key=p.get, reverse=True)
        top1 += ranked[0] in g if ranked else 0
        recall3 += len(set(ranked[:3]) & g) / len(g) if g else 0
        k = len(g)
        oracle_tp += len(set(ranked[:k]) & g)
        oracle_n += k
    n = max(len(gold), 1)
    return {
        "top1_accuracy": top1 / n,
        "recall_at_3": recall3 / n,
        # Predict exactly as many topics as the gold labels have: precision = recall here.
        "oracle_k_f1": oracle_tp / oracle_n if oracle_n else 0.0,
        "macro_auc": macro_auc(probs, gold),
    }


def auc(scores_pos: Sequence[float], scores_neg: Sequence[float]) -> float | None:
    """Probability that a random positive scores above a random negative (ties count half)."""
    if not scores_pos or not scores_neg:
        return None
    labelled = sorted([(s, 1) for s in scores_pos] + [(s, 0) for s in scores_neg])
    rank_sum = 0.0
    i = 0
    while i < len(labelled):
        j = i
        while j < len(labelled) and labelled[j][0] == labelled[i][0]:
            j += 1
        average_rank = (i + j + 1) / 2  # ranks are 1-based
        rank_sum += average_rank * sum(label for _, label in labelled[i:j])
        i = j
    n_pos, n_neg = len(scores_pos), len(scores_neg)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def macro_auc(probs: Sequence[Probabilities], gold: Sequence[set[str]]) -> float | None:
    topics = {k for p in probs for k in p}
    values = []
    for k in topics:
        pos = [p.get(k, 0.0) for p, g in zip(probs, gold) if k in g]
        neg = [p.get(k, 0.0) for p, g in zip(probs, gold) if k not in g]
        value = auc(pos, neg)
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else None


def best_threshold(
    probs: Sequence[Probabilities], gold: Sequence[set[str]], grid: Sequence[float] | None = None
) -> float:
    grid = grid or [round(0.05 * i, 2) for i in range(1, 20)]
    return max(grid, key=lambda t: (multilabel_at_threshold(probs, gold, t)["micro_f1"], -abs(t - 0.5)))


def frequency_baseline(train_gold: Sequence[set[str]], test_gold: Sequence[set[str]]) -> dict:
    """Predict the k most frequent topics for every affair (k = average labels per affair)."""
    counts: dict[str, int] = {}
    for g in train_gold:
        for k in g:
            counts[k] = counts.get(k, 0) + 1
    k = max(1, round(sum(map(len, train_gold)) / max(len(train_gold), 1)))
    top = sorted(counts, key=counts.get, reverse=True)[:k]
    fake = [{t: 1.0 for t in top} for _ in test_gold]
    result = multilabel_at_threshold(fake, test_gold, 0.5)
    return {"k": k, "topics": top, "micro_f1": result["micro_f1"], "macro_f1": result["macro_f1"]}


def binary_metrics(scores: Sequence[float], labels: Sequence[bool], threshold: float) -> dict:
    tp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y)
    fp = sum(1 for s, y in zip(scores, labels) if s >= threshold and not y)
    fn = sum(1 for s, y in zip(scores, labels) if s < threshold and y)
    tn = sum(1 for s, y in zip(scores, labels) if s < threshold and not y)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "accuracy": (tp + tn) / max(len(labels), 1),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "auc": auc([s for s, y in zip(scores, labels) if y], [s for s, y in zip(scores, labels) if not y]),
    }
