"""Build isolated candidate target weights for execution-level model backtests."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def pct_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average")


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/model_baseline.yaml").read_text(encoding="utf-8"))
    path = ROOT / "outputs/backtest" / cfg["run"]["run_id"] / "predictions.csv"
    predictions = pd.read_csv(path, parse_dates=["date"])
    wide = predictions.pivot_table(index=["date", "asset"], columns="model", values="prediction").reset_index()
    features = predictions[predictions["model"] == "lightgbm"][
        ["date", "asset", "low_volatility_20", "momentum_60_skip_5", "quality_roe"]
    ]
    panel = wide.merge(features, on=["date", "asset"], how="left")
    for column in ["lightgbm", "ridge", "low_volatility_20", "momentum_60_skip_5", "quality_roe"]:
        panel[column + "_rank"] = panel.groupby("date")[column].transform(pct_rank)
    scores = {
        "lgb": panel["lightgbm_rank"],
        "ridge": panel["ridge_rank"],
        "ensemble": .65 * panel["lightgbm_rank"] + .35 * panel["ridge_rank"],
        "lgb_defensive": .75 * panel["lightgbm_rank"] + .25 * panel["low_volatility_20_rank"],
        "lgb_mom_quality": .70 * panel["lightgbm_rank"] + .15 * panel["momentum_60_skip_5_rank"] + .15 * panel["quality_roe_rank"],
    }
    connection = duckdb.connect(cfg["run"]["source_database"])
    calendar = [r[0] for r in connection.execute("SELECT DISTINCT date FROM factor_panel ORDER BY date").fetchall()]
    next_date = {pd.Timestamp(calendar[i]): calendar[i + 1] for i in range(len(calendar) - 1)}
    rows = []
    for name, score in scores.items():
        panel["score"] = score
        for top_n in [10, 20, 30, 50]:
            ranked = panel.sort_values(["date", "score", "asset"], ascending=[True, False, True]).copy()
            ranked["target_rank"] = ranked.groupby("date").cumcount() + 1
            selected = ranked[ranked["target_rank"] <= top_n]
            for row in selected.itertuples(index=False):
                rebalance = next_date.get(row.date)
                if rebalance is not None:
                    rows.append({"rebalance_date": rebalance, "formation_date": row.date.date(),
                                 "strategy": f"{name}_top{top_n}", "asset": row.asset,
                                 "score": row.score, "target_rank": row.target_rank,
                                 "target_weight": 1.0 / top_n})
    targets = pd.DataFrame(rows)
    connection.register("candidate_targets", targets)
    connection.execute("CREATE OR REPLACE TABLE model_baseline_targets AS SELECT * FROM candidate_targets")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_model_baseline_targets ON model_baseline_targets(rebalance_date,strategy,asset)")
    connection.close()
    print(targets.groupby("strategy").agg(rebalances=("rebalance_date", "nunique"), rows=("asset", "size")).to_string())


if __name__ == "__main__":
    main()
