"""02 - 计算每日 IC、Rank IC 及研究/验证/测试分期汇总。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, EVALUATION_OUTPUT_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("02 计算 IC 和 Rank IC")
    ensure_data_dirs()
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        connection.execute(
            """
            CREATE OR REPLACE TABLE daily_factor_ic AS
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
            joined AS (
                SELECT f.date, f.asset, f.factor, l.horizon,
                       f.winsorized_value AS factor_value,
                       f.rank_pct AS factor_rank,
                       l.future_return,
                       percent_rank() OVER (
                           PARTITION BY f.date, f.factor, l.horizon
                           ORDER BY l.future_return
                       ) AS return_rank
                FROM factor_values_processed_detail f
                JOIN labels l USING (date, asset)
            )
            SELECT date, factor, horizon,
                   count(*) AS sample_size,
                   corr(factor_value, future_return) AS ic,
                   corr(factor_rank, return_rank) AS rank_ic
            FROM joined
            GROUP BY date, factor, horizon
            HAVING count(*) >= 30
            ORDER BY date, factor, horizon;

            CREATE OR REPLACE TABLE factor_ic_summary AS
            WITH split_data AS (
                SELECT *,
                    CASE
                        WHEN date <= DATE '2023-12-31' THEN 'train_2020_2023'
                        WHEN date <= DATE '2024-12-31' THEN 'validation_2024'
                        ELSE 'test_2025'
                    END AS sample_period
                FROM daily_factor_ic
            )
            SELECT factor, horizon, sample_period,
                   count(*) AS dates,
                   avg(sample_size) AS average_sample_size,
                   avg(ic) AS mean_ic,
                   stddev_samp(ic) AS std_ic,
                   avg(ic) / NULLIF(stddev_samp(ic), 0) AS ic_ir,
                   avg(ic) / NULLIF(stddev_samp(ic) / sqrt(count(*)), 0) AS ic_t_stat,
                   avg(CASE WHEN ic > 0 THEN 1.0 ELSE 0.0 END) AS positive_ic_ratio,
                   avg(rank_ic) AS mean_rank_ic,
                   stddev_samp(rank_ic) AS std_rank_ic,
                   avg(rank_ic) / NULLIF(stddev_samp(rank_ic), 0) AS rank_ic_ir,
                   avg(rank_ic) / NULLIF(stddev_samp(rank_ic) / sqrt(count(*)), 0)
                       AS rank_ic_t_stat,
                   avg(CASE WHEN rank_ic > 0 THEN 1.0 ELSE 0.0 END)
                       AS positive_rank_ic_ratio
            FROM split_data
            GROUP BY factor, horizon, sample_period
            ORDER BY factor, horizon, sample_period;
            """
        )
        daily = connection.execute("SELECT * FROM daily_factor_ic").fetchdf()
        summary = connection.execute("SELECT * FROM factor_ic_summary").fetchdf()
        daily.to_csv(EVALUATION_OUTPUT_DIR / "02_daily_ic.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(EVALUATION_OUTPUT_DIR / "02_ic_summary.csv", index=False, encoding="utf-8-sig")
        print(summary.to_string(index=False))
        print("[PASS] IC 和 Rank IC 已计算。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
