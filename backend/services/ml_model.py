"""scikit-learn projection model trained on real historical box scores.

Per-game targets (minutes + the 11 raw stats behind the nine categories) are modelled
with HistGradientBoostingRegressor on leakage-free pre-game features. Validation is
strictly chronological:

    train      : 2024-25 season + 2025-26 games before SPLIT_DATE
    validation : 2025-26 games on/after SPLIT_DATE
    test       : 2026-27 games played so far (out-of-season holdout)

For each stat the model is only used in production if it beats the explainable
weighted-average baseline on the validation window; otherwise the baseline is used.
After evaluation every model is refit on all available rows.

Train from backend/:  python -m services.ml_model
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from core.categories import MODEL_STATS
from core.config import settings
from core.db import init_db, set_meta
from data import repository as repo
from services.features import (baseline_prediction, model_feature_columns, player_features, team_factors,
                               team_rest)

log = logging.getLogger("courtvision.ml")
SPLIT_DATE = pd.Timestamp("2026-01-15")
MIN_TRAIN_ROWS = 5000
_model_lock = threading.Lock()
_loaded: dict | None = None


def build_frame(box: pd.DataFrame, games: pd.DataFrame, placeholders: pd.DataFrame | None = None,
                current_factors: bool = False) -> pd.DataFrame:
    """Player features + opponent factors + rest. Placeholder rows use the latest team factors."""
    feat = player_features(box, placeholders)
    asof, current = team_factors(box)
    asof = asof.rename(columns={"team_id": "opp_team_id"})
    real = feat[~feat["placeholder"]].merge(asof, on=["opp_team_id", "game_id"], how="left")
    ph = feat[feat["placeholder"]]
    if len(ph):
        ph = ph.merge(current.drop(columns="games").rename(columns={"team_id": "opp_team_id"}),
                      on="opp_team_id", how="left")
    feat = pd.concat([real, ph], ignore_index=True) if len(ph) else real
    rest = team_rest(games)
    feat = feat.merge(rest, on=["team_id", "game_id"], how="left")
    feat["rest"] = feat["rest"].fillna(2)
    opp_cols = [c for c in feat.columns if c.startswith("opp_") and c != "opp_team_id"]
    feat[opp_cols] = feat[opp_cols].fillna(1.0)
    return feat


def _naive(df: pd.DataFrame, stat: str) -> np.ndarray:
    cur = df[f"cur_{stat}"].to_numpy(dtype=float)
    return np.where(np.isnan(cur), df[f"prev_{stat}"].to_numpy(dtype=float), cur)


def _mae(pred: np.ndarray, actual: np.ndarray) -> float | None:
    mask = ~np.isnan(pred) & ~np.isnan(actual)
    return float(np.mean(np.abs(pred[mask] - actual[mask]))) if mask.any() else None


def _make_model(stat: str) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error" if stat == "min" else "poisson",
        max_iter=250, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=80,
        l2_regularization=1.0, random_state=7,
    )


def _sd_table(pred: np.ndarray, actual: np.ndarray, bins: int = 10) -> dict:
    """Residual standard deviation as a function of the predicted value (quantile bins)."""
    mask = ~np.isnan(pred) & ~np.isnan(actual)
    pred, actual = pred[mask], actual[mask]
    edges = np.unique(np.quantile(pred, np.linspace(0, 1, bins + 1)))
    centers, sds = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (pred >= lo) & (pred <= hi)
        if m.sum() >= 30:
            centers.append(float(pred[m].mean()))
            sds.append(float(np.std(actual[m] - pred[m])))
    return {"centers": centers, "sds": sds}


def train(save: bool = True) -> dict:
    box, games = repo.box_scores(), repo.games()
    df = build_frame(box, games)
    df = df[df["l5_min"].notna()].reset_index(drop=True)
    if len(df) < MIN_TRAIN_ROWS:
        raise RuntimeError(f"Not enough history to train ({len(df)} rows)")
    tr = df[(df["season"] <= 2026) & (df["date"] < SPLIT_DATE)]
    va = df[(df["season"] == 2026) & (df["date"] >= SPLIT_DATE)]
    te = df[df["season"] >= 2027]
    log.info("rows: train=%d valid=%d test=%d", len(tr), len(va), len(te))

    models, eval_models, metrics, sd_tables, use_ml = {}, {}, {}, {}, {}
    feature_cols: dict[str, list[str]] = {}
    preds_valid: dict[str, np.ndarray] = {}
    for stat in MODEL_STATS:
        # drop features with no observed values in training (e.g. no prior seasons available)
        cols = [c for c in model_feature_columns(stat) if tr[c].notna().any()]
        feature_cols[stat] = cols
        y_tr = tr[f"actual_{stat}"].to_numpy(dtype=float)
        model = _make_model(stat).fit(tr[cols], y_tr)
        eval_models[stat] = model
        entry = {}
        for name, part in (("validation", va), ("test", te)):
            if len(part) < 100:
                continue
            actual = part[f"actual_{stat}"].to_numpy(dtype=float)
            entry[name] = {
                "rows": int(len(part)),
                "mae_ml": _mae(np.clip(model.predict(part[cols]), 0, None), actual),
                "mae_baseline": _mae(baseline_prediction(part, stat), actual),
                "mae_season_avg": _mae(_naive(part, stat), actual),
                "mean_actual": float(np.nanmean(actual)),
            }
        v = entry["validation"]
        use_ml[stat] = bool(v["mae_ml"] < v["mae_baseline"])
        chosen = np.clip(model.predict(va[cols]), 0, None) if use_ml[stat] else baseline_prediction(va, stat)
        preds_valid[stat] = chosen
        sd_tables[stat] = _sd_table(chosen, va[f"actual_{stat}"].to_numpy(dtype=float))
        entry["method"] = "ml" if use_ml[stat] else "baseline"
        metrics[stat] = entry
        # Refit on every available row for production use.
        models[stat] = _make_model(stat).fit(df[cols], df[f"actual_{stat}"].to_numpy(dtype=float))
        log.info("%s: %s", stat, json.dumps(entry))

    # Shooting percentages: makes are either predicted directly or as projected attempts x the
    # player's season-blended percentage (stable, volume-aware). Validation picks per category.
    pct_method = {}
    for label, makes, att in (("fg_pct", "fgm", "fga"), ("ft_pct", "ftm", "fta")):
        a_m, a_a = va[f"actual_{makes}"].to_numpy(float), va[f"actual_{att}"].to_numpy(float)
        mask = a_a >= 1
        candidates = {
            "direct": preds_valid[makes],
            "attempts_x_pct": preds_valid[att] * blended_pct(va, makes, att),
        }
        scores = {}
        for name, pm in candidates.items():
            p_pct = pm / np.maximum(preds_valid[att], 1e-9)
            scores[name] = float(np.sum(np.abs(p_pct[mask] - a_m[mask] / a_a[mask]) * a_a[mask]) / np.sum(a_a[mask]))
        best = min(scores, key=scores.get)
        pct_method[makes] = best
        if best == "attempts_x_pct":
            preds_valid[makes] = candidates[best]
            metrics[makes]["method"] = f"{metrics[att]['method']} attempts x blended %"
            metrics[makes]["validation"]["mae_chosen"] = _mae(candidates[best], a_m)
            sd_tables[makes] = _sd_table(candidates[best], a_m)
        metrics[label] = {"method": best, "validation": {
            "rows": int(mask.sum()),
            **{f"attempt_weighted_mae_{k}": v for k, v in scores.items()},
            "attempt_weighted_mae": scores[best],
        }}

    bundle = {
        "models": models, "feature_cols": feature_cols, "use_ml": use_ml, "pct_method": pct_method, "sd_tables": sd_tables, "metrics": metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "rows": {"train": int(len(tr)), "validation": int(len(va)), "test": int(len(te)), "final_fit": int(len(df))},
        "split_date": SPLIT_DATE.date().isoformat(),
        "data_through": df["date"].max().date().isoformat(),
        "algorithm": "HistGradientBoostingRegressor (Poisson loss for counting stats)",
    }
    if save:
        joblib.dump(bundle, settings.model_path)
        set_meta("model_trained_at", bundle["trained_at"])
        global _loaded
        with _model_lock:
            _loaded = bundle
    return bundle


def load_model() -> dict | None:
    global _loaded
    with _model_lock:
        if _loaded is None and settings.model_path.exists():
            try:
                _loaded = joblib.load(settings.model_path)
            except Exception as exc:  # noqa: BLE001 - corrupt/incompatible file: fall back to baseline
                log.warning("could not load model: %s", exc)
                _loaded = None
        return _loaded


def blended_pct(feat: pd.DataFrame, makes: str, att: str) -> np.ndarray:
    """Season-blended shooting % (current season shrunk toward prior season), league-average fallback."""
    m = feat[f"blend_{makes}"].to_numpy(dtype=float)
    a = feat[f"blend_{att}"].to_numpy(dtype=float)
    league = LEAGUE_PCT[makes]
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(a > 0.05, m / a, league)
    return np.where(np.isfinite(pct), np.clip(pct, 0, 1), league)


LEAGUE_PCT = {"fgm": 0.47, "ftm": 0.78}


def predict(feat: pd.DataFrame, stat: str) -> tuple[np.ndarray, str]:
    """Per-row prediction for one stat and the method used ('ml' or 'baseline')."""
    bundle = load_model()
    if bundle and bundle["use_ml"].get(stat):
        cols = bundle.get("feature_cols", {}).get(stat) or model_feature_columns(stat)
        return np.clip(bundle["models"][stat].predict(feat[cols]), 0, None), "ml"
    return np.clip(baseline_prediction(feat, stat), 0, None), "baseline"


def predict_all(feat: pd.DataFrame) -> tuple[dict[str, np.ndarray], dict[str, str]]:
    """Predictions for every modelled stat, applying the validated shooting-% method."""
    preds, methods = {}, {}
    for stat in MODEL_STATS:
        preds[stat], methods[stat] = predict(feat, stat)
    bundle = load_model() or {}
    for makes, att in (("fgm", "fga"), ("ftm", "fta")):
        if bundle.get("pct_method", {}).get(makes, "attempts_x_pct") == "attempts_x_pct":
            preds[makes] = preds[att] * blended_pct(feat, makes, att)
            methods[makes] = f"{methods[att]} attempts x blended %"
    return preds, methods


def residual_sd(stat: str, pred: np.ndarray) -> np.ndarray:
    """Model-level residual SD for given predictions, interpolated from validation bins."""
    bundle = load_model()
    table = bundle["sd_tables"].get(stat) if bundle else None
    if not table or not table["centers"]:
        return np.sqrt(np.maximum(pred, 0.25)) * (1.0 if stat != "min" else 2.0)
    return np.interp(pred, table["centers"], table["sds"])


def summary() -> dict:
    bundle = load_model()
    if not bundle:
        return {"trained": False}
    return {"trained": True, **{k: v for k, v in bundle.items() if k not in {"models", "sd_tables", "feature_cols"}}}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    result = train()
    print(json.dumps({k: v for k, v in result.items() if k not in {"models", "sd_tables"}}, indent=2))
