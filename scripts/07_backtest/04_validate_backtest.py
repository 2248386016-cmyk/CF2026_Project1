"""04 - 验证回测时点、资金、交易费和输出唯一性。"""

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
    print_section("04 验证回测结果")
    ensure_data_dirs()
    config = yaml.safe_load((PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8"))
    tolerance = float(config["performance"]["reconciliation_tolerance"])
    initial_capital = float(config["portfolio"]["initial_capital"])
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        checks = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM (
                    SELECT date, strategy FROM backtest_daily
                    GROUP BY date, strategy HAVING count(*) > 1
                )) AS duplicate_daily_keys,
                (SELECT count(*) FROM backtest_daily WHERE nav <= 0) AS nonpositive_nav_rows,
                (SELECT count(*) FROM backtest_daily WHERE cash < -0.01) AS negative_cash_rows,
                (SELECT count(*) FROM backtest_daily
                 WHERE transaction_cost < 0 OR turnover < 0) AS invalid_cost_or_turnover,
                (SELECT count(*) FROM backtest_trades
                 WHERE units <= 0 OR cost < 0
                    OR (side IN ('BUY', 'SELL') AND gross_amount <= 0)) AS invalid_trades,
                (SELECT count(*) FROM strategy_targets
                 WHERE formation_date >= rebalance_date) AS lookahead_target_rows,
                (SELECT count(DISTINCT strategy) FROM backtest_daily) AS strategy_count,
                (SELECT count(*) FROM backtest_metrics) AS metric_strategy_count
            """
        ).fetchdf()
        daily = connection.execute("SELECT * FROM backtest_daily ORDER BY strategy, date").fetchdf()
        metrics = connection.execute("SELECT * FROM backtest_metrics").fetchdf().set_index("strategy")
        reconciliation_rows: list[dict] = []
        for strategy, frame in daily.groupby("strategy", sort=True):
            frame = frame.sort_values("date").copy()
            expected = frame["nav"].astype(float).pct_change().fillna(frame["nav"].iloc[0] / initial_capital - 1.0)
            max_daily_error = (expected - frame["daily_return"].astype(float)).abs().max()
            compounded_return = (1.0 + frame["daily_return"].astype(float)).prod() - 1.0
            nav_return = frame["nav"].iloc[-1] / initial_capital - 1.0
            daily_cost_sum = frame["transaction_cost"].sum()
            metric_cost = float(metrics.loc[strategy, "total_transaction_cost"])
            cumulative_cost = float(frame["cumulative_transaction_cost"].iloc[-1])
            reconciliation_rows.append({
                "strategy": strategy,
                "max_daily_return_nav_error": max_daily_error,
                "compounded_return": compounded_return,
                "nav_based_return": nav_return,
                "cumulative_return_error": abs(compounded_return - nav_return),
                "daily_cost_sum": daily_cost_sum,
                "metric_cost": metric_cost,
                "ending_cumulative_cost": cumulative_cost,
                "cost_reconciliation_error": max(
                    abs(daily_cost_sum - metric_cost), abs(daily_cost_sum - cumulative_cost)
                ),
            })
        reconciliation = pd.DataFrame(reconciliation_rows)
        reconciliation.to_csv(
            BACKTEST_OUTPUT_DIR / "04_backtest_reconciliation.csv",
            index=False, encoding="utf-8-sig"
        )
        checks.to_csv(BACKTEST_OUTPUT_DIR / "04_backtest_checks.csv", index=False, encoding="utf-8-sig")
        print(checks.to_string(index=False))
        required_zero = [
            "duplicate_daily_keys", "nonpositive_nav_rows", "negative_cash_rows",
            "invalid_cost_or_turnover", "invalid_trades", "lookahead_target_rows",
        ]
        failures = {c: int(checks.iloc[0][c]) for c in required_zero if int(checks.iloc[0][c]) != 0}
        if int(checks.iloc[0]["strategy_count"]) != 4:
            failures["strategy_count"] = int(checks.iloc[0]["strategy_count"])
        if int(checks.iloc[0]["metric_strategy_count"]) != 4:
            failures["metric_strategy_count"] = int(checks.iloc[0]["metric_strategy_count"])
        if failures:
            raise AssertionError(f"回测未通过关键检查：{failures}")
        numeric_columns = [
            "max_daily_return_nav_error", "cumulative_return_error", "cost_reconciliation_error"
        ]
        if (reconciliation[numeric_columns] > tolerance).any().any():
            raise AssertionError(
                f"净值/收益/成本对账误差超过容差 {tolerance}\n"
                + reconciliation.to_string(index=False)
            )
        print("\n独立对账：")
        print(reconciliation.to_string(index=False))
        print(f"报告目录：{BACKTEST_OUTPUT_DIR}")
        print("[PASS] 回测时点、资金、费用和唯一性检查全部通过。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
