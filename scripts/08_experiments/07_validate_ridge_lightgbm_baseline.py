"""Validate point-in-time constraints and output completeness for the model baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    config = yaml.safe_load((PROJECT_ROOT / "config/model_baseline.yaml").read_text(encoding="utf-8"))
    output = PROJECT_ROOT / "outputs/backtest" / config["run"]["run_id"]
    panel = pd.read_parquet(output / "model_panel.parquet")
    predictions = pd.read_csv(output / "predictions.csv", parse_dates=["date", "ann_date", "exit_date_20d"])
    metrics = pd.read_csv(output / "performance_metrics.csv")
    overlay = pd.read_csv(output / "regime_overlay_daily.csv", parse_dates=["date"])
    overlay_metrics = pd.read_csv(output / "regime_overlay_metrics.csv")
    checks = {
        "unique_panel_key": not panel.duplicated(["date", "asset"]).any(),
        "financial_announced_by_signal": bool((panel["ann_date"].dropna() <= panel.loc[panel["ann_date"].notna(), "date"]).all()),
        "membership_known_by_signal": bool((panel["membership_snapshot_date"] <= panel["date"]).all()),
        "test_starts_2025": bool((predictions.loc[predictions["period"] == "test", "date"] >= pd.Timestamp("2025-01-01")).all()),
        "two_models_present": set(predictions["model"]) == {"ridge", "lightgbm"},
        "benchmark_present": "csi300_benchmark" in set(metrics["model"]),
        "finite_nav": bool(pd.to_numeric(pd.read_csv(output / "monthly_nav.csv")["nav"], errors="coerce").notna().all()),
        "overlay_one_row_per_day": not overlay.duplicated("date").any(),
        "overlay_monthly_frozen_weight": bool(
            (overlay.groupby(overlay["date"].dt.to_period("M"))["active_weight"].nunique() <= 1).all()
        ),
        "overlay_weight_is_binary": set(overlay["active_weight"].dropna().unique()).issubset({0.0, 1.0}),
        "validation_beats_benchmark": bool(
            overlay_metrics.query("period == 'validation' and strategy == 'regime_overlay'")["annualized_return"].iloc[0]
            > overlay_metrics.query("period == 'validation' and strategy == 'csi300'")["annualized_return"].iloc[0]
        ),
        "frozen_test_beats_benchmark": bool(
            overlay_metrics.query("period == 'test' and strategy == 'regime_overlay'")["annualized_return"].iloc[0]
            > overlay_metrics.query("period == 'test' and strategy == 'csi300'")["annualized_return"].iloc[0]
        ),
    }
    frame = pd.DataFrame([{"check": key, "passed": value} for key, value in checks.items()])
    frame.to_csv(output / "validation_checks.csv", index=False)
    print(frame.to_string(index=False))
    if not all(checks.values()):
        raise AssertionError("模型基准校验失败")
    (output / "validation_summary.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
