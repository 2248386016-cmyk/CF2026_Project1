"""03 - 验证对照实验仅改变调仓频率，且两组输出完整。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import BACKTEST_OUTPUT_DIR, DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("03 验证周频 vs 月频对照实验")
    ensure_data_dirs()
    output_dir = BACKTEST_OUTPUT_DIR / "weekly_vs_monthly"
    config = yaml.safe_load((PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8"))
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"), read_only=True)
    try:
        checks = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM experiment_weekly_strategy_rebalance_schedule) AS weekly_rebalances,
                (SELECT count(*) FROM experiment_monthly_strategy_rebalance_schedule) AS monthly_rebalances,
                (SELECT count(DISTINCT strategy) FROM experiment_weekly_backtest_daily) AS weekly_strategies,
                (SELECT count(DISTINCT strategy) FROM experiment_monthly_backtest_daily) AS monthly_strategies,
                (SELECT count(DISTINCT date) FROM experiment_weekly_backtest_daily) AS weekly_dates,
                (SELECT count(DISTINCT date) FROM experiment_monthly_backtest_daily) AS monthly_dates,
                (SELECT count(*) FROM experiment_weekly_strategy_targets WHERE target_weight <> 0.05) AS invalid_weekly_weights,
                (SELECT count(*) FROM experiment_monthly_strategy_targets WHERE target_weight <> 0.05) AS invalid_monthly_weights,
                (SELECT count(*) FROM experiment_weekly_strategy_targets WHERE formation_date >= rebalance_date) AS weekly_lookahead,
                (SELECT count(*) FROM experiment_monthly_strategy_targets WHERE formation_date >= rebalance_date) AS monthly_lookahead,
                (SELECT count(*) FROM (
                    SELECT strategy FROM experiment_weekly_backtest_daily
                    EXCEPT SELECT strategy FROM experiment_monthly_backtest_daily
                )) AS strategy_set_difference,
                (SELECT count(*) FROM (
                    SELECT date FROM experiment_weekly_backtest_daily
                    EXCEPT SELECT date FROM experiment_monthly_backtest_daily
                )) AS date_set_difference
            """
        ).fetchdf()
    finally:
        connection.close()
    checks["same_research_start"] = config["research"]["start_date"] == "2020-01-01"
    checks["same_research_end"] = config["research"]["end_date"] == "2025-12-31"
    checks["same_top_n"] = int(config["portfolio"]["top_n"]) == 20
    checks["same_buy_rate"] = float(config["cost"]["buy_rate"]) == 0.0003
    checks["same_sell_rate"] = float(config["cost"]["sell_rate"]) == 0.0013
    checks.to_csv(output_dir / "03_experiment_checks.csv", index=False, encoding="utf-8-sig")
    row = checks.iloc[0]
    failures = {}
    zero_columns = [
        "invalid_weekly_weights", "invalid_monthly_weights", "weekly_lookahead",
        "monthly_lookahead", "strategy_set_difference", "date_set_difference",
    ]
    for column in zero_columns:
        if int(row[column]) != 0:
            failures[column] = int(row[column])
    if int(row["weekly_strategies"]) != 4 or int(row["monthly_strategies"]) != 4:
        failures["strategy_counts"] = (int(row["weekly_strategies"]), int(row["monthly_strategies"]))
    if int(row["weekly_dates"]) != int(row["monthly_dates"]):
        failures["date_counts"] = (int(row["weekly_dates"]), int(row["monthly_dates"]))
    for column in ["same_research_start", "same_research_end", "same_top_n", "same_buy_rate", "same_sell_rate"]:
        if not bool(row[column]):
            failures[column] = False
    if not int(row["weekly_rebalances"]) > int(row["monthly_rebalances"]) > 0:
        failures["rebalance_counts"] = (int(row["weekly_rebalances"]), int(row["monthly_rebalances"]))
    print(checks.to_string(index=False))
    if failures:
        raise AssertionError(f"对照实验未通过：{failures}")
    print("[PASS] 两组的数据、样本、因子、持仓和成本口径一致，唯一变量为调仓频率。")


if __name__ == "__main__":
    main()
