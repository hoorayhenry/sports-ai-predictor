"""
Unified multi-market prediction model — sport-aware.

Every sport has its own characteristics:
  - Binary (H/A only) vs 3-way (H/D/A) classification
  - Different betting markets (football: btts/over2.5, basketball: over215.5)
  - Different scoring scale (basketball 215 pts, baseball 9.4 runs, football 2.75 goals)
  - Different Pythagorean exponent

The model uses the same XGBoost+LightGBM ensemble for all sports.
What changes per sport:
  1. Label encoding: binary (2 classes) vs multinomial (3 classes)
  2. Which markets are trained (sport-specific MARKETS dict)
  3. predict() returns sport-appropriate probability dicts
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
from sklearn.metrics import log_loss, accuracy_score
from sklearn.isotonic import IsotonicRegression

from features.engineering import COMMON_FEATURES
from features.sport_profiles import get_profile, is_binary as _sport_is_binary
from features.tier1_models import SPORT_EXTRA_FEATURES

MODEL_DIR = Path(__file__).parent.parent / "saved"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def _markets_for_sport(sport_key: str) -> list[str]:
    """
    Return the betting markets to train for each sport.
    Markets outside this list won't be trained or predicted.
    """
    if sport_key == "football":
        return ["result", "over15", "over25", "over35", "btts", "home_cs", "away_cs"]
    elif sport_key == "handball":
        # Handball has draws (~12%) + BTTS is meaningful (high-scoring)
        return ["result", "over_main", "btts"]
    elif sport_key in ("basketball", "american_football", "baseball", "ice_hockey",
                       "rugby", "cricket", "volleyball"):
        profile = get_profile(sport_key)
        markets = ["result"]
        if profile.totals_lines:
            markets.append("over_main")
        return markets
    else:
        # Tennis, etc: result only (no natural totals market for sets)
        return ["result"]


class SportModel:
    """
    One instance per sport_key.

    Key design decisions:
    - Binary sports (basketball, baseball, hockey, NFL, tennis…): 2-class result
      classifier. No draws exist, so training with H/D/A wastes model capacity
      and gives systematically wrong probabilities.
    - 3-way sports (football, handball): standard H/D/A classification.
    - Totals market is calibrated to the sport's natural scoring scale.
      Football: over 2.5 goals (avg 2.75). Basketball: over 215.5 pts (avg 215).
    """

    def __init__(self, sport_key: str):
        self.sport_key = sport_key
        self.binary    = _sport_is_binary(sport_key)
        self.markets   = _markets_for_sport(sport_key)
        self.models: dict    = {}   # market -> classifier
        self.encoders: dict  = {}   # market -> LabelEncoder (for result)
        self.calibrators: dict = {} # market -> {class_idx: IsotonicRegression}
        # Build sport-specific feature list: COMMON_FEATURES + Tier 1 extras.
        # dict.fromkeys preserves order and deduplicates (in case of overlap).
        _extras = SPORT_EXTRA_FEATURES.get(sport_key, [])
        self.features = list(dict.fromkeys(COMMON_FEATURES + _extras))

    # ──────────────────────────────────────────────────────────────────────────
    # Training
    # ──────────────────────────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame, market_callback=None) -> dict[str, float]:
        """
        Train all sport-appropriate markets.

        Uses TIME-BASED split: train on oldest 80%, validate on most recent 20%.
        This prevents data leakage — future matches must never teach the model.

        For binary sports (basketball, baseball, hockey, NFL…):
          - 'result' classifier has 2 classes (H, A).
          - Any rows where result=='D' are dropped before training — draws are
            non-existent / OT artefacts and would confuse the classifier.

        market_callback: optional callable(market_name) called after each market trains.
        """
        scores = {}
        X = df[self.features].astype(float)

        has_weights   = "sample_weight" in df.columns
        weights_all   = df["sample_weight"].values if has_weights else None
        split_idx     = int(len(df) * 0.8)

        for market in self.markets:
            if market not in df.columns:
                logger.debug(f"[{self.sport_key}] {market}: not in training matrix — skip")
                continue

            y_raw = df[market].dropna()
            X_m   = X.loc[y_raw.index]
            w_m   = weights_all[y_raw.index] if has_weights else None

            if market == "result":
                # For binary sports: drop draws (rare OT artefacts; confuse binary model)
                if self.binary:
                    mask_no_draw = y_raw.isin(["H", "A"])
                    y_raw = y_raw[mask_no_draw]
                    X_m   = X_m[mask_no_draw]
                    w_m   = w_m[mask_no_draw] if w_m is not None else None
                    if len(y_raw) < 50:
                        logger.warning(f"[{self.sport_key}] result: only {len(y_raw)} non-draw samples — skipping")
                        continue

                le = LabelEncoder()
                y  = le.fit_transform(y_raw)
                self.encoders["result"] = le
                n_classes = len(le.classes_)
            else:
                y = y_raw.astype(int).values
                n_classes = 2

            if len(y_raw) < 50:
                logger.warning(f"[{self.sport_key}] {market}: only {len(y_raw)} samples — skipping")
                continue

            # Time-based split
            mask_train = y_raw.index < split_idx
            mask_val   = y_raw.index >= split_idx

            if mask_val.sum() < 10:
                n_val       = max(10, int(len(y) * 0.2))
                mask_train  = np.ones(len(y), dtype=bool)
                mask_train[-n_val:] = False
                mask_val    = ~mask_train

            X_tr  = X_m.values[mask_train]
            X_val = X_m.values[mask_val]
            y_tr  = y[mask_train]
            y_val = y[mask_val]
            w_tr  = w_m[mask_train] if w_m is not None else None

            if len(np.unique(y_tr)) < 2:
                logger.warning(f"[{self.sport_key}] {market}: only one class in train set — skipping")
                continue

            clf = self._build_classifier(market, n_classes)
            clf.fit(X_tr, y_tr, sample_weight=w_tr)

            preds = clf.predict_proba(X_val)
            ll    = log_loss(y_val, preds)
            acc   = accuracy_score(y_val, clf.predict(X_val))
            scores[market] = ll
            logger.info(
                f"[{self.sport_key}] {market}: log_loss={ll:.4f}  acc={acc:.3f}  "
                f"(train={len(y_tr)}, val={len(y_val)}, classes={n_classes})"
            )
            self.models[market] = clf
            if market_callback:
                market_callback(market)

            # Isotonic calibration per class
            n_cls = preds.shape[1]
            cals  = {}
            for ci in range(n_cls):
                y_binary = (y_val == ci).astype(int)
                iso = IsotonicRegression(out_of_bounds="clip")
                iso.fit(preds[:, ci], y_binary)
                cals[ci] = iso
            self.calibrators[market] = cals
            logger.debug(f"[{self.sport_key}] {market}: calibrators fitted ({n_cls} classes)")

        return scores

    def _build_classifier(self, market: str, n_classes: int):
        """Build best available classifier with sensible hyperparameters."""
        is_multi = n_classes > 2

        params_xgb = dict(
            n_estimators   = 500,
            max_depth      = 5,
            learning_rate  = 0.04,
            subsample      = 0.8,
            colsample_bytree = 0.8,
            min_child_weight = 3,
            gamma          = 0.1,
            reg_alpha      = 0.05,
            eval_metric    = "mlogloss" if is_multi else "logloss",
            random_state   = 42,
            n_jobs         = -1,
        )
        if is_multi:
            params_xgb["num_class"]  = n_classes
            params_xgb["objective"]  = "multi:softprob"
        else:
            params_xgb["objective"]  = "binary:logistic"

        params_lgb = dict(
            n_estimators     = 500,
            max_depth        = 5,
            learning_rate    = 0.04,
            subsample        = 0.8,
            colsample_bytree = 0.8,
            min_child_samples = 15,
            reg_alpha        = 0.05,
            random_state     = 42,
            n_jobs           = -1,
            verbose          = -1,
        )
        if is_multi:
            params_lgb["objective"] = "multiclass"
            params_lgb["num_class"] = n_classes
        else:
            params_lgb["objective"] = "binary"

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

    # ──────────────────────────────────────────────────────────────────────────
    # Inference
    # ──────────────────────────────────────────────────────────────────────────

    def predict(self, X: pd.DataFrame) -> dict:
        """
        Returns a dict of market → probabilities for this match.

        Football example:
          {"result":  {"H": 0.52, "D": 0.24, "A": 0.24},
           "over25":  {"over": 0.61, "under": 0.39},
           "btts":    {"yes": 0.48, "no": 0.52}, ...}

        Basketball example:
          {"result":  {"H": 0.63, "A": 0.37},
           "over_main": {"over": 0.55, "under": 0.45}}

        Tennis example:
          {"result":  {"H": 0.71, "A": 0.29}}
        """
        out = {}
        X_feat = X[self.features].astype(float)

        # --- result ---
        if "result" in self.models:
            clf    = self.models["result"]
            le     = self.encoders.get("result")
            proba  = clf.predict_proba(X_feat)[0]
            proba  = self._calibrate("result", proba)
            # le.classes_ is ["A","H"] for binary (sorted), or ["A","D","H"] for 3-way
            classes = list(le.classes_) if le else (["H", "A"] if self.binary else ["H", "D", "A"])
            out["result"] = {str(c): float(p) for c, p in zip(classes, proba)}

        # --- football-specific binary goal markets ---
        for mkt in ("over15", "over25", "over35"):
            if mkt in self.models:
                raw = self.models[mkt].predict_proba(X_feat)[0]
                cal = self._calibrate(mkt, raw)
                out[mkt] = {"over": float(cal[1]), "under": float(cal[0])}

        # --- btts ---
        if "btts" in self.models:
            raw = self.models["btts"].predict_proba(X_feat)[0]
            cal = self._calibrate("btts", raw)
            out["btts"] = {"yes": float(cal[1]), "no": float(cal[0])}

        # --- clean sheets ---
        for mkt in ("home_cs", "away_cs"):
            if mkt in self.models:
                raw = self.models[mkt].predict_proba(X_feat)[0]
                cal = self._calibrate(mkt, raw)
                out[mkt] = {"yes": float(cal[1]), "no": float(cal[0])}

        # --- sport-specific over/under (basketball/baseball/hockey/NFL/rugby...) ---
        if "over_main" in self.models:
            raw = self.models["over_main"].predict_proba(X_feat)[0]
            cal = self._calibrate("over_main", raw)
            profile = get_profile(self.sport_key)
            # Label the line so UI can show "Over 215.5" instead of generic "over_main"
            lines = profile.totals_lines
            line_label = str(lines[len(lines) // 2]) if lines else "total"
            out["over_main"] = {
                "over": float(cal[1]),
                "under": float(cal[0]),
                "line": line_label,
            }

        return out

    def _calibrate(self, market: str, proba: np.ndarray) -> np.ndarray:
        """Apply per-class isotonic calibration and renormalise to sum=1."""
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

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

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
            obj = pickle.load(f)
        # Patch old models that don't have the new attributes
        if not hasattr(obj, "binary"):
            obj.binary  = _sport_is_binary(sport_key)
        if not hasattr(obj, "markets"):
            obj.markets = _markets_for_sport(sport_key)
        if not hasattr(obj, "features") or obj.features == COMMON_FEATURES:
            # Rebuild with sport-aware extras
            _extras = SPORT_EXTRA_FEATURES.get(sport_key, [])
            obj.features = list(dict.fromkeys(COMMON_FEATURES + _extras))
        return obj

    def is_trained(self) -> bool:
        return bool(self.models)


class _EnsembleClassifier:
    """Weighted average of XGBoost + LightGBM probabilities."""

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
