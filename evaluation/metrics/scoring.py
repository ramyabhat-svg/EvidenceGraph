"""Reproducible metrics for aligned scientific claim predictions."""

from collections import Counter, defaultdict
from random import Random
from statistics import mean

VERDICTS = (
    "Supported", "Partially Supported", "Contradicted", "Unsupported", "Needs Review",
)


def ratio(n, d):
    """Return an undefined metric when the denominator is zero."""
    return n / d if d else None


def classification(pairs, labels=VERDICTS):
    """Return confusion matrix and per-class precision, recall and F1."""
    matrix = Counter(pairs)
    per_class = {}
    for label in labels:
        predicted = sum(matrix[expected, label] for expected in labels)
        actual = sum(matrix[label, guess] for guess in labels)
        true = matrix[label, label]
        per_class[label] = {
            "precision": ratio(true, predicted), "recall": ratio(true, actual),
            "f1": ratio(2 * true, predicted + actual), "support": actual,
        }
    scores = [item["f1"] for item in per_class.values() if item["f1"] is not None]
    return {
        "per_class": per_class, "macro_f1": mean(scores) if scores else None,
        "confusion_matrix": {a: {b: matrix[a, b] for b in labels} for a in labels},
    }


def cohen_kappa(pairs):
    """Compute unweighted Cohen's kappa over independently paired labels."""
    if not pairs:
        return None
    n = len(pairs)
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum(count * right[label] for label, count in left.items()) / n**2
    return ratio(observed - expected, 1 - expected)


def document_bootstrap(rows, seed=42, samples=1000):
    """Return a percentile macro-F1 interval by resampling whole documents."""
    groups = defaultdict(list)
    for document, expected, prediction in rows:
        groups[document].append((expected, prediction))
    documents = sorted(groups)
    if len(documents) < 2:
        return None
    rng = Random(seed)
    scores = sorted(classification([
        pair for document in rng.choices(documents, k=len(documents)) for pair in groups[document]
    ])["macro_f1"] for _ in range(samples))
    return [scores[int((samples - 1) * p)] for p in (0.025, 0.975)]


def calibration(samples, bins=10):
    """Score NLI entailment probability against annotated support."""
    if not samples:
        return None
    groups = defaultdict(list)
    for probability, supported in samples:
        if not 0 <= probability <= 1:
            raise ValueError("Entailment probability must be in [0, 1].")
        groups[min(int(probability * bins), bins - 1)].append((probability, supported))
    return {
        "count": len(samples), "brier": mean((p - y)**2 for p, y in samples),
        "ece": sum(len(group) * abs(mean(p for p, _ in group) - mean(y for _, y in group))
                   for group in groups.values()) / len(samples),
    }


def risk_coverage(scored):
    """Return selective error rates at confidence cutoffs, grouping ties."""
    counts = defaultdict(lambda: [0, 0])
    for confidence, correct in scored:
        counts[confidence][0] += 1
        counts[confidence][1] += not correct
    included = errors = 0
    result = []
    for confidence, (size, failures) in sorted(counts.items(), reverse=True):
        included += size
        errors += failures
        result.append({"threshold": confidence, "coverage": included / len(scored),
                       "risk": errors / included})
    return result
