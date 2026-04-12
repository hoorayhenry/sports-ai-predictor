"""
Unified multi-market prediction model for any sport.
Trains separate classifiers for: 1X2 result, Over 2.5 goals, BTTS.
Uses XGBoost + LightGBM ensemble.
"""
import os
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from loguru import logger

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import log_loss, accuracy_score

from features.engineering import COMMON_FEATURES

MODEL_DIR = Path(__file__).parent.parent / "saved"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MARKETS = ["result", "over25", "btts"]


class SportModel:
    """
    One instance per sport_key. Holds three classifiers (result, over25, btts).
    Falls back gracefully when a market has insufficient data.
    """

    def __init__(self, sport_key: str):
        self.sport_key = sport_key
        self.models: dict = {}        # market -> classifier
        self.encoders: dict = {}      # market -> LabelEncoder (for result)
        self.features = COMMON_FEATURES

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(self, df: pd.DataFrame) -> dict[str, float]:
        """Train all markets. Returns dict of market -> log_loss scores."""
        scores = {}
        X = df[self.features].astype(float)

        for market in MARKETS:
            if market not in df.columns:
                continue
            y_raw = df[market].dropna()
            X_m = X.loc[y_raw.index]

            if len(y_raw) < 50:
                logger.warning(f"[{self.sport_key}] {market}: only {len(y_raw)} samples — skipping")
                continue

            if market == "result":
                le = LabelEncoder()
                y = le.fit_transform(y_raw)
                self.encoders["result"] = le
            else:
                y = y_raw.astype(int).values

            X_tr, X_val, y_tr, y_val = train_test_split(
                X_m, y, test_size=0.2, random_state=42, stratify=y if len(np.unique(y)) > 1 else None
            )

            clf = self._build_classifier(market, len(np.unique(y)))
            clf.fit(X_tr, y_tr)

            preds = clf.predict_proba(X_val)
            ll = log_loss(y_val, preds)
            acc = accuracy_score(y_val, clf.predict(X_val))
            scores[market] = ll
            logger.info(f"[{self.sport_key}] {market}: log_loss={ll:.4f}  acc={acc:.3f}")
            self.models[market] = clf

        return scores

    def _build_classifier(self, market: str, n_classes: int):
        """Build best available classifier with sensible hyperparameters."""
        params_xgb = dict(
            n_estimators=400, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric="mlogloss" if n_classes > 2 else "logloss",
            random_state=42, n_jobs=-1,
            num_class=n_classes if n_classes > 2 else None,
            objective="multi:softprob" if n_classes > 2 else "binary:logistic",
        )
        # Remove None values
        params_xgb = {k: v for k, v in params_xgb.items() if v is not None}

        params_lgb = dict(
            n_estimators=400, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, n_jobs=-1, verbose=-1,
            objective="multiclass" if n_classes > 2 else "binary",
            num_class=n_classes if n_classes > 2 else None,
        )
        params_lgb = {k: v for k, v in params_lgb.items() if v is not None}

        if HAS_XGB and HAS_LGB:
            return _EnsembleClassifier(
                XGBClassifier(**params_xgb),
                LGBMClassifier(**params_lgb),
                weights=(0.55, 0.45),
            )
        elif HAS_XGB:
            return XGBClassifier(**params_xgb)
        elif HAS_LGB:
            return LGBMClassifier(**params_lgb)
        else:
            return LogisticRegression(max_iter=1000, multi_class="auto")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def predict(self, X: pd.DataFrame) -> dict:
        """
        Returns dict with probabilities for each market.
        result: {"home": p, "draw": p, "away": p}  (or no draw for no-draw sports)
        over25: {"over": p, "under": p}
        btts:   {"yes": p, "no": p}
        """
        out = {}
        X_feat = X[self.features].astype(float)

        # --- result ---
        if "result" in self.models:
            clf = self.models["result"]
            le = self.encoders.get("result")
            proba = clf.predict_proba(X_feat)[0]
            classes = le.classes_ if le else ["home", "away"]
            out["result"] = {str(c): float(p) for c, p in zip(classes, proba)}

        # --- over25 ---
        if "over25" in self.models:
            p_over = float(self.models["over25"].predict_proba(X_feat)[0][1])
            out["over25"] = {"over": p_over, "under": 1 - p_over}

        # --- btts ---
        if "btts" in self.models:
            p_yes = float(self.models["btts"].predict_proba(X_feat)[0][1])
            out["btts"] = {"yes": p_yes, "no": 1 - p_yes}

        return out

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self):
        path = MODEL_DIR / f"{self.sport_key}_model.pkl"
        with open(path, "wb") as f:
            pickle.dump(self, f)
        logger.info(f"Model saved: {path}")

    @classmethod
    def load(cls, sport_key: str) -> "SportModel":
        path = MODEL_DIR / f"{sport_key}_model.pkl"
        if not path.exists():
            raise FileNotFoundError(f"No model found at {path}")
        with open(path, "rb") as f:
            return pickle.load(f)

    def is_trained(self) -> bool:
        return bool(self.models)


class _EnsembleClassifier:
    """Weighted average of two classifiers (XGBoost + LightGBM)."""

    def __init__(self, clf1, clf2, weights=(0.5, 0.5)):
        self.clf1 = clf1
        self.clf2 = clf2
        self.w1, self.w2 = weights
        self.classes_ = None

    def fit(self, X, y):
        self.clf1.fit(X, y)
        self.clf2.fit(X, y)
        self.classes_ = self.clf1.classes_ if hasattr(self.clf1, "classes_") else np.unique(y)
        return self

    def predict_proba(self, X):
        p1 = self.clf1.predict_proba(X)
        p2 = self.clf2.predict_proba(X)
        return self.w1 * p1 + self.w2 * p2

    def predict(self, X):
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)
