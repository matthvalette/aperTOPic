import pytest

from parltopics.evaluation import metrics


def test_multilabel_at_threshold():
    probs = [{"a": 0.9, "b": 0.6, "c": 0.1}, {"a": 0.2, "b": 0.7, "c": 0.8}]
    gold = [{"a"}, {"b", "c"}]
    m = metrics.multilabel_at_threshold(probs, gold, 0.5)
    # predicted {a, b} and {b, c}: tp 3, fp 1, fn 0
    assert m["micro_precision"] == pytest.approx(0.75)
    assert m["micro_recall"] == pytest.approx(1.0)
    assert m["exact_match"] == pytest.approx(0.5)


def test_ranking_metrics():
    probs = [{"a": 0.9, "b": 0.6, "c": 0.1}, {"a": 0.9, "b": 0.7, "c": 0.8}]
    gold = [{"a"}, {"b", "c"}]
    r = metrics.ranking_metrics(probs, gold)
    assert r["top1_accuracy"] == pytest.approx(0.5)
    assert r["oracle_k_f1"] == pytest.approx(2 / 3)


def test_auc():
    assert metrics.auc([0.9, 0.8], [0.1, 0.2]) == pytest.approx(1.0)
    assert metrics.auc([0.1], [0.9]) == pytest.approx(0.0)
    assert metrics.auc([0.5], [0.5]) == pytest.approx(0.5)
    assert metrics.auc([], [0.5]) is None


def test_best_threshold_prefers_better_f1():
    probs = [{"a": 0.3, "b": 0.1}, {"a": 0.1, "b": 0.35}]
    gold = [{"a"}, {"b"}]
    assert metrics.best_threshold(probs, gold) <= 0.3
