"""
Model Registry for i2b2-etl ML pipeline.

Centralizes model pipeline + hyperparameter grid definitions so new models
can be added without modifying apply_build_model_ml.py at all - just add a
new factory function here and register it in MODEL_REGISTRY.

Each factory function returns a tuple: (pipeline, param_grid, display_name)
  - pipeline: built via make_pipeline(clf, selector_estimator) - the same
    scale -> SMOTE -> feature-selection -> classifier structure used
    throughout this ML module.
  - param_grid: hyperparameter grid for GridSearchCV, using the same
    "selector__..." / "clf__..." naming convention as existing models.
  - display_name: string used in logging/output (e.g. "SVM", "RandomForest").

USAGE (from apply_build_model_ml.py):
    from i2b2_cdi.ML.model_registry import build_model
    model_type = blob.get("model_type", "logistic").lower()
    hyperparameter_overrides = blob.get("hyperparameters", {})
    pipeline, param_grid, name = build_model(model_type, hyperparameter_overrides)

HYPERPARAMETER OVERRIDES:
    Callers can pass a dict of {grid_key: [values]} to override or extend
    any model's default search grid, without editing this file. Keys must
    match the "clf__..." / "selector__..." naming convention used below.

    Example blob:
        {
            "model_type": "random_forest",
            "hyperparameters": {
                "clf__n_estimators": [50, 300, 500],
                "clf__max_depth": [3, 6, 9, 15]
            }
        }
    This REPLACES the default grid values for those specific keys, while
    keeping any other keys (e.g. "selector__threshold") at their default.
"""

from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier
from sklearn.dummy import DummyClassifier
from sklearn.neural_network import MLPClassifier

try:
    from xgboost import XGBClassifier
    _XGBOOST_AVAILABLE = True
except ImportError:
    _XGBOOST_AVAILABLE = False

from i2b2_cdi.ML.build_model_ML_helper import make_pipeline


def _logistic_regression():
    pipeline = make_pipeline(
        LogisticRegression(solver="saga", penalty="elasticnet", class_weight="balanced", max_iter=30000),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__C": [0.1, 1, 10],
        "clf__l1_ratio": [0.0, 0.5, 1.0],
    }
    return pipeline, grid, "LogisticRegression"


def _svm():
    pipeline = make_pipeline(
        SVC(kernel="rbf", probability=True, class_weight="balanced"),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__C": [0.1, 1, 10],
        "clf__gamma": ["scale", "auto"],
    }
    return pipeline, grid, "SVM"


def _random_forest():
    pipeline = make_pipeline(
        RandomForestClassifier(class_weight="balanced", random_state=42),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__n_estimators": [100, 200],
        "clf__max_depth": [None, 5, 10],
    }
    return pipeline, grid, "RandomForest"


def _xgboost():
    if not _XGBOOST_AVAILABLE:
        raise ImportError(
            "xgboost is not installed in this environment. "
            "model_type='xgboost' cannot be used until it is installed."
        )
    pipeline = make_pipeline(
        XGBClassifier(eval_metric="logloss"),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__n_estimators": [100, 200],
        "clf__max_depth": [3, 5, 7],
    }
    return pipeline, grid, "XGBoost"


def _knn():
    pipeline = make_pipeline(
        KNeighborsClassifier(),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__n_neighbors": [3, 5, 7, 9, 11],
        "clf__weights": ["uniform", "distance"],
    }
    return pipeline, grid, "KNN"


def _naive_bayes():
    pipeline = make_pipeline(
        GaussianNB(),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__var_smoothing": [1e-9, 1e-8, 1e-7],
    }
    return pipeline, grid, "NaiveBayes"


def _decision_tree():
    pipeline = make_pipeline(
        DecisionTreeClassifier(class_weight="balanced", random_state=42),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__max_depth": [3, 5, 10, None],
        "clf__min_samples_split": [2, 5, 10],
    }
    return pipeline, grid, "DecisionTree"


def _dummy():
    pipeline = make_pipeline(
        DummyClassifier(strategy="most_frequent"),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
    }
    return pipeline, grid, "DummyBaseline"


def _ann():
    pipeline = make_pipeline(
        MLPClassifier(max_iter=2000, random_state=42, early_stopping=True),
        LogisticRegression(solver="saga", penalty="l1", class_weight="balanced"),
    )
    grid = {
        "selector__threshold": ["median"],
        "clf__hidden_layer_sizes": [(16,), (32,), (16, 8)],
        "clf__alpha": [0.0001, 0.001, 0.01],
        "clf__learning_rate_init": [0.001, 0.01],
    }
    return pipeline, grid, "ANN"


MODEL_REGISTRY = {
    "logistic": _logistic_regression,
    "svm": _svm,
    "random_forest": _random_forest,
    "xgboost": _xgboost,
    "knn": _knn,
    "naive_bayes": _naive_bayes,
    "decision_tree": _decision_tree,
    "dummy": _dummy,
    "ann": _ann,
}


def build_model(model_type, hyperparameter_overrides=None):
    factory = MODEL_REGISTRY.get(model_type, _logistic_regression)
    pipeline, grid, name = factory()

    if hyperparameter_overrides:
        grid = dict(grid)
        grid.update(hyperparameter_overrides)

    return pipeline, grid, name
