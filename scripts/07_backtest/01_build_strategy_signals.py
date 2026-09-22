"""01 - 为3个单因子和1个等权多因子策略构建每周目标持仓。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("01 构建策略信号与每周目标持仓")
    ensure_data_dirs()
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8")
    )
    top_n = int(config["portfolio"]["top_n"])
    start_date = config["research"]["start_date"]
    end_date = config["research"]["end_date"]
    frequency = config["portfolio"]["rebalance_frequency"]
    if config["portfolio"]["weighting"] != "equal_weight":
        raise ValueError("当前实现仅支持 equal_weight。")
    if frequency == "weekly":
        period_expression = "yearweek(date)"
    elif frequency == "monthly":
        period_expression = "year(date) * 100 + month(date)"
    else:
        raise ValueError(f"不支持的调仓频率：{frequency}")
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        selected = [row[0] for row in connection.execute(
            "SELECT factor FROM selected_factors ORDER BY selection_order"
        ).fetchall()]
        if len(selected) != 3:
            raise AssertionError(f"需要3个已选因子，当前为：{selected}")

        placeholders = ", ".join("?" for _ in selected)
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE strategy_signal_scores AS
            WITH selected_values AS (
                SELECT date, asset, factor, zscore_value
                FROM factor_values_processed_detail
                WHERE factor IN ({placeholders})
                  AND date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            ),
            single_signals AS (
                SELECT date, asset,
                       'single_' || factor AS strategy,
                       zscore_value AS score
                FROM selected_values
            ),
            composite AS (
                SELECT date, asset, 'multi_equal_3' AS strategy,
                       avg(zscore_value) AS score
                FROM selected_values
                GROUP BY date, asset
                HAVING count(DISTINCT factor) = 3
            )
            SELECT * FROM single_signals
            UNION ALL SELECT * FROM composite;
            """,
            selected,
        )

        connection.execute(
            f"""
            CREATE OR REPLACE TABLE strategy_rebalance_schedule AS
            WITH dates AS (
                SELECT DISTINCT date
                FROM factor_panel
                WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            ), ordered AS (
                SELECT date,
                       lag(date) OVER (ORDER BY date) AS formation_date,
                       {period_expression} AS period_id,
                       row_number() OVER (
                           PARTITION BY {period_expression} ORDER BY date
                       ) AS day_in_period
                FROM dates
            )
            SELECT date AS rebalance_date, formation_date, period_id
            FROM ordered
            WHERE day_in_period = 1 AND formation_date IS NOT NULL
            ORDER BY rebalance_date;

            CREATE OR REPLACE TABLE strategy_targets AS
            WITH ranked AS (
                SELECT r.rebalance_date, r.formation_date,
                       s.strategy, s.asset, s.score,
                       row_number() OVER (
                           PARTITION BY r.rebalance_date, s.strategy
                           ORDER BY s.score DESC, s.asset
                       ) AS target_rank
                FROM strategy_rebalance_schedule r
                JOIN strategy_signal_scores s
                  ON r.formation_date = s.date
            )
            SELECT rebalance_date, formation_date, strategy, asset, score,
                   target_rank, 1.0 / {top_n} AS target_weight
            FROM ranked
            WHERE target_rank <= {top_n}
            ORDER BY rebalance_date, strategy, target_rank;

            CREATE INDEX IF NOT EXISTS idx_strategy_targets
            ON strategy_targets(rebalance_date, strategy, asset);
            """
        )
        summary = connection.execute(
            """
            SELECT strategy, count(DISTINCT rebalance_date) AS rebalances,
                   count(*) AS target_rows,
                   min(rebalance_date) AS first_rebalance,
                   max(rebalance_date) AS last_rebalance,
                   min(target_count) AS minimum_target_count,
                   max(target_count) AS maximum_target_count
            FROM (
                SELECT *, count(*) OVER (
                    PARTITION BY rebalance_date, strategy
                ) AS target_count
                FROM strategy_targets
            )
            GROUP BY strategy ORDER BY strategy
            """
        ).fetchdf()
        print(summary.to_string(index=False))
        print("[PASS] strategy_targets 已建立，信号使用前一交易日收盘后数据。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
