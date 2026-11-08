
from decimal import Decimal


# Canonical metric name -> words used in research papers
METRIC_ALIASES = {
    "accuracy": ["accuracy", "acc", "top-1 accuracy"],
    "f1": ["f1", "f1-score", "f1 score", "f-measure"],
    "precision": ["precision"],
    "recall": ["recall"],
    "auc": ["auc", "auroc", "roc auc"],
    "rmse": ["rmse", "root mean square error"],
    "mae": ["mae", "mean absolute error"],
}


# Metrics that can naturally be represented as ratios between 0 and 1
BOUNDED_RATIO_METRICS = {
    "accuracy",
    "f1",
    "precision",
    "recall",
    "auc",
}


# Entity aliases
ENTITY_ALIASES = {
    "ours": [
        "our model",
        "our method",
        "our approach",
        "proposed model",
        "proposed method",
        "ours",
    ]
}


# Dataset or experiment periods
PERIOD_ALIASES = {
    "test": ["test set", "testing set"],
    "train": ["training set", "train set"],
    "validation": ["validation set", "val set"],
}


# Multipliers for large numerical values
SCALES = {
    "K": Decimal(1000),
    "thousand": Decimal(1000),
    "M": Decimal(1000000),
    "million": Decimal(1000000),
    "B": Decimal(1000000000),
    "billion": Decimal(1000000000),
    "bn": Decimal(1000000000),
}


# Recognized measurement units
UNIT_TOKENS = {
    "ms": "ms",
    "s": "s",
    "sec": "s",
    "min": "min",
    "mg/L": "mg/L",
    "mg": "mg",
    "g": "g",
    "kg": "kg",
    "mL": "mL",
    "L": "L",
    "mm": "mm",
    "cm": "cm",
    "km": "km",
    "m": "m",
    "Hz": "Hz",
}
