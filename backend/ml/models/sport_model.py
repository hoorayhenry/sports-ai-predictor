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
from sklearn.isotonic import IsotonicRegression

from features.engineering import COMMON_FEATURES

MODEL_DIR = Path(__file__).parent.parent / "saved"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MARKETS = ["result", "over15", "over25", "over35", "btts", "home_cs", "away_cs"]


class SportModel:
    """
    One instance per sport_key. Holds three classifiers (result, over25, btts).
    Falls back gracefully when a market has insufficient data.
    """

    def __init__(self, sport_key: str):
        self.sport_key = sport_key
        self.models: dict = {}        # market -> classifier
        self.encoders: dict = {}      # market -> LabelEncoder (for result)
        self.calibrators: dict = {}   # market -> {class_idx: IsotonicRegression}
        self.features = COMMON_FEATURES

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(self, df: pd.DataFrame) -> dict[str, float]:
        """
        Train all markets. Returns dict of market -> log_loss scores.

        Uses a TIME-BASED split (not random): the model trains on the older 80%
        of matches and validates on the most recent 20%.  This prevents data
        leakage — future matches must never teach the model about the past.
        """
        scores = {}
        X = df[self.features].astype(float)

        # Recency weights from build_training_matrix
        has_weights = "sample_weight" in df.columns
        weights_all = df["sample_weight"].values if has_weights else None

        # ── Time-based split ────────────────────────────────────────────
        # df is ordered oldest → newest (guaranteed by build_training_matrix
        # which pulls from the DB ordered by match_date).
        # Train on the first 80%, validate on the last 20%.
        split_idx = int(len(df) * 0.8)

        for market in MARKETS:
            if market not in df.columns:
                continue
            y_raw = df[market].dropna()
            X_m   = X.loc[y_raw.index]
            w_m   = weights_all[y_raw.index] if has_weights else None

            if len(y_raw) < 50:
                logger.warning(f"[{self.sport_key}] {market}: only {len(y_raw)} samples — skipping")
                continue

            if market == "result":
                le = LabelEncoder()
                y = le.fit_transform(y_raw)
                self.encoders["result"] = le
            else:
                y = y_raw.astype(int).values

            # Time-based split on the (possibly filtered) index
            # Positions within y_raw.index relative to the global split_idx
            mask_train = y_raw.index < split_idx
            mask_val   = y_raw.index >= split_idx

            # Fallback to last 20% by position if index gap too small
            if mask_val.sum() < 10:
                n_val  = max(10, int(len(y) * 0.2))
                mask_train = np.ones(len(y), dtype=bool)
                mask_train[-n_val:] = False
                mask_val   = ~mask_train

            X_tr  = X_m.values[mask_train]
            X_val = X_m.values[mask_val]
            y_tr  = y[mask_train]
            y_val = y[mask_val]
            w_tr  = w_m[mask_train] if w_m is not None else None

            if len(np.unique(y_tr)) < 2:
                logger.warning(f"[{self.sport_key}] {market}: only one class in train set — skipping")
                continue

            clf = self._build_classifier(market, len(np.unique(y)))
            clf.fit(X_tr, y_tr, sample_weight=w_tr)

            preds = clf.predict_proba(X_val)
            ll  = log_loss(y_val, preds)
            acc = accuracy_score(y_val, clf.predict(X_val))
            scores[market] = ll
            logger.info(f"[{self.sport_key}] {market}: log_loss={ll:.4f}  acc={acc:.3f}  "
                        f"(train={len(y_tr)}, val={len(y_val)})")
            self.models[market] = clf

            # ── Isotonic calibration per class ────────────────────────
            n_classes = preds.shape[1]
            cals = {}
            for ci in range(n_classes):
                y_binary = (y_val == ci).astype(int)
                iso = IsotonicRegression(out_of_bounds="clip")
                iso.fit(preds[:, ci], y_binary)
                cals[ci] = iso
            self.calibrators[market] = cals
            logger.debug(f"[{self.sport_key}] {market}: calibrators fitted ({n_classes} classes)")

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
        Returns dict with probabilities for each trained market.

        Trained markets:
          result:   {"H": p, "D": p, "A": p}
          over15:   {"over": p, "under": p}
          over25:   {"over": p, "under": p}
          over35:   {"over": p, "under": p}
          btts:     {"yes": p, "no": p}
          home_cs:  {"yes": p, "no": p}  (home team clean sheet)
          away_cs:  {"yes": p, "no": p}  (away team clean sheet)
        """
        out = {}
        X_feat = X[self.features].astype(float)

        # --- result ---
        if "result" in self.models:
            clf    = self.models["result"]
            le     = self.encoders.get("result")
            proba  = clf.predict_proba(X_feat)[0]
            proba  = self._calibrate("result", proba)
            classes = le.classes_ if le else ["H", "A"]
            out["result"] = {str(c): float(p) for c, p in zip(classes, proba)}

        # --- binary goal markets ---
        for mkt, label in [("over15", "over"), ("over25", "over"), ("over35", "over")]:
            if mkt in self.models:
                raw = self.models[mkt].predict_proba(X_feat)[0]
                cal = self._calibrate(mkt, raw)
                out[mkt] = {"over": cal[1], "under": cal[0]}

        # --- btts ---
        if "btts" in self.models:
            raw = self.models["btts"].predict_proba(X_feat)[0]
            cal = self._calibrate("btts", raw)
            out["btts"] = {"yes": cal[1], "no": cal[0]}

        # --- clean sheets ---
        if "home_cs" in self.models:
            raw = self.models["home_cs"].predict_proba(X_feat)[0]
            cal = self._calibrate("home_cs", raw)
            out["home_cs"] = {"yes": cal[1], "no": cal[0]}

        if "away_cs" in self.models:
            raw = self.models["away_cs"].predict_proba(X_feat)[0]
            cal = self._calibrate("away_cs", raw)
            out["away_cs"] = {"yes": cal[1], "no": cal[0]}

        return out

    def _calibrate(self, market: str, proba: np.ndarray) -> np.ndarray:
        """
        Apply per-class isotonic calibration and renormalise to sum=1.
        Falls back to raw probabilities if no calibrators are fitted.
        """
        cals = self.calibrators.get(market)
        if not cals:
            return proba
        calibrated = np.array([
            float(cals[ci].predict([proba[ci]])[0]) if ci in cals else proba[ci]
            for ci in range(len(proba))
        ])
        total = calibrated.sum()
        if total > 0:
            calibrated /= total
        return calibrated

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

    def fit(self, X, y, sample_weight=None):
        self.clf1.fit(X, y, sample_weight=sample_weight)
        self.clf2.fit(X, y, sample_weight=sample_weight)
        self.classes_ = self.clf1.classes_ if hasattr(self.clf1, "classes_") else np.unique(y)
        return self

    def predict_proba(self, X):
        p1 = self.clf1.predict_proba(X)
        p2 = self.clf2.predict_proba(X)
        return self.w1 * p1 + self.w2 * p2

    def predict(self, X):
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)
