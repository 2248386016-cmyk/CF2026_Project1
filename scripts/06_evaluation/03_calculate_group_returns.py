"""03 - 计算五分组未来收益、高低组价差和单调性。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, EVALUATION_OUTPUT_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("03 计算五分组收益")
    ensure_data_dirs()
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        connection.execute(
            """
            CREATE OR REPLACE TABLE daily_factor_group_returns AS
            WITH labels AS (
                SELECT date, asset, 1 AS horizon, forward_return_1d AS future_return
                FROM forward_returns WHERE forward_return_1d IS NOT NULL
                UNION ALL
                SELECT date, asset, 5, forward_return_5d
                FROM forward_returns WHERE forward_return_5d IS NOT NULL
                UNION ALL
                SELECT date, asset, 20, forward_return_20d
                FROM forward_returns WHERE forward_return_20d IS NOT NULL
            ),
            assigned AS (
                SELECT f.date, f.asset, f.factor, l.horizon, l.future_return,
                       least(5, floor(f.rank_pct * 5)::INTEGER + 1) AS factor_group
                FROM factor_values_processed_detail f
                JOIN labels l USING (date, asset)
            )
            SELECT date, factor, horizon, factor_group,
                   count(*) AS assets,
                   avg(future_return) AS group_return
            FROM assigned
            GROUP BY date, factor, horizon, factor_group
            ORDER BY date, factor, horizon, factor_group;

            CREATE OR REPLACE TABLE daily_factor_spreads AS
            SELECT date, factor, horizon,
                   max(group_return) FILTER (WHERE factor_group = 5)
                     - max(group_return) FILTER (WHERE factor_group = 1) AS high_minus_low,
                   corr(factor_group, group_return) AS group_monotonicity,
                   sum(assets) AS sample_size
            FROM daily_factor_group_returns
            GROUP BY date, factor, horizon
            HAVING count(DISTINCT factor_group) = 5
            ORDER BY date, factor, horizon;

            CREATE OR REPLACE TABLE factor_group_summary AS
            WITH split_groups AS (
                SELECT *, CASE
                    WHEN date <= DATE '2023-12-31' THEN 'train_2020_2023'
                    WHEN date <= DATE '2024-12-31' THEN 'validation_2024'
                    ELSE 'test_2025' END AS sample_period
                FROM daily_factor_group_returns
            )
            SELECT factor, horizon, sample_period, factor_group,
                   count(*) AS dates,
                   avg(assets) AS average_assets,
                   avg(group_return) AS mean_group_return,
                   stddev_samp(group_return) AS std_group_return
            FROM split_groups
            GROUP BY factor, horizon, sample_period, factor_group
            ORDER BY factor, horizon, sample_period, factor_group;

            CREATE OR REPLACE TABLE factor_spread_summary AS
            WITH split_spreads AS (
                SELECT *, CASE
                    WHEN date <= DATE '2023-12-31' THEN 'train_2020_2023'
                    WHEN date <= DATE '2024-12-31' THEN 'validation_2024'
                    ELSE 'test_2025' END AS sample_period
                FROM daily_factor_spreads
            )
            SELECT factor, horizon, sample_period,
                   count(*) AS dates,
                   avg(high_minus_low) AS mean_high_minus_low,
                   stddev_samp(high_minus_low) AS std_high_minus_low,
                   avg(high_minus_low) / NULLIF(stddev_samp(high_minus_low), 0)
                       AS spread_ir,
                   avg(high_minus_low) /
                       NULLIF(stddev_samp(high_minus_low) / sqrt(count(*)), 0)
                       AS spread_t_stat,
                   avg(CASE WHEN high_minus_low > 0 THEN 1.0 ELSE 0.0 END)
                       AS positive_spread_ratio,
                   avg(group_monotonicity) AS average_group_monotonicity
            FROM split_spreads
            GROUP BY factor, horizon, sample_period
            ORDER BY factor, horizon, sample_period;
            """
        )
        groups = connection.execute("SELECT * FROM factor_group_summary").fetchdf()
        spreads = connection.execute("SELECT * FROM factor_spread_summary").fetchdf()
        groups.to_csv(EVALUATION_OUTPUT_DIR / "03_group_return_summary.csv", index=False, encoding="utf-8-sig")
        spreads.to_csv(EVALUATION_OUTPUT_DIR / "03_spread_summary.csv", index=False, encoding="utf-8-sig")
        print(spreads.to_string(index=False))
        print("[PASS] 五分组收益和高低组价差已计算。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
