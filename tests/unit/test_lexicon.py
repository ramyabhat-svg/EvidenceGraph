
from decimal import Decimal

from domain_packs.scientific_research import lexicon as lx


def test_metric_aliases():
    assert "acc" in lx.METRIC_ALIASES["accuracy"]
    assert "f1-score" in lx.METRIC_ALIASES["f1"]
    assert "auroc" in lx.METRIC_ALIASES["auc"]


def test_bounded_ratio_metrics():
    assert "accuracy" in lx.BOUNDED_RATIO_METRICS
    assert "auc" in lx.BOUNDED_RATIO_METRICS


def test_entity_aliases():
    assert "proposed model" in lx.ENTITY_ALIASES["ours"]


def test_period_aliases():
    assert "test set" in lx.PERIOD_ALIASES["test"]
    assert "training set" in lx.PERIOD_ALIASES["train"]


def test_scales():
    assert lx.SCALES["K"] == Decimal(1000)
    assert lx.SCALES["M"] == Decimal(1000000)
    assert lx.SCALES["B"] == Decimal(1000000000)


def test_units():
    assert lx.UNIT_TOKENS["ms"] == "ms"
    assert lx.UNIT_TOKENS["sec"] == "s"
    assert lx.UNIT_TOKENS["kg"] == "kg"
