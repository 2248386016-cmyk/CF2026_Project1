"""02 - 按因子卡计算7个原始候选因子并输出统一长表。"""

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
    print_section("02 计算原始因子")
    ensure_data_dirs()
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "factor_config.yaml").read_text(encoding="utf-8")
    )
    start_date = config["research"]["start_date"]
    end_date = config["research"]["end_date"]
    enabled = {item["name"] for item in config["factors"] if item.get("enabled", True)}

    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE factor_values_raw AS
            WITH features AS (
                SELECT *,
                    lag(eligible_close, 5) OVER w AS close_lag_5,
                    lag(eligible_close, 20) OVER w AS close_lag_20,
                    lag(eligible_close, 60) OVER w AS close_lag_60,
                    count(eligible_close) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
                    ) AS close_count_6,
                    count(eligible_close) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
                    ) AS close_count_21,
                    count(eligible_close) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 60 PRECEDING AND CURRENT ROW
                    ) AS close_count_61,
                    count(daily_return) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS return_count_20,
                    stddev_samp(daily_return) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS return_std_20,
                    count(overnight_log_return) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS overnight_count_5,
                    sum(overnight_log_return) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS overnight_sum_5,
                    count(CASE WHEN daily_return IS NOT NULL AND eligible_amount > 0 THEN 1 END) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS amihud_count_20,
                    avg(CASE WHEN daily_return IS NOT NULL AND eligible_amount > 0
                             THEN abs(daily_return) / eligible_amount END) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS amihud_mean_20,
                    count(eligible_amount) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS amount_count_20,
                    avg(eligible_amount) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                    ) AS amount_mean_5,
                    avg(eligible_amount) OVER (
                        PARTITION BY asset ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) AS amount_mean_20
                FROM factor_panel
                WINDOW w AS (PARTITION BY asset ORDER BY date)
            ),
            wide AS (
                SELECT date, asset,
                    CASE WHEN is_in_universe AND close_count_21 = 21
                         THEN eligible_close / close_lag_20 - 1 END AS momentum_20,
                    CASE WHEN is_in_universe AND close_count_6 = 6
                         THEN -(eligible_close / close_lag_5 - 1) END AS reversal_5,
                    CASE WHEN is_in_universe AND return_count_20 = 20
                         THEN -return_std_20 END AS low_volatility_20,
                    CASE WHEN is_in_universe AND close_count_61 = 61
                         THEN close_lag_5 / close_lag_60 - 1 END AS momentum_60_skip_5,
                    CASE WHEN is_in_universe AND overnight_count_5 = 5
                         THEN -overnight_sum_5 END AS overnight_reversal_5,
                    CASE WHEN is_in_universe AND amihud_count_20 = 20
                                   AND amihud_mean_20 > 0
                         THEN ln(amihud_mean_20) END AS amihud_illiquidity_20,
                    CASE WHEN is_in_universe AND amount_count_20 = 20
                                   AND amount_mean_5 > 0 AND amount_mean_20 > 0
                         THEN ln(amount_mean_5 / amount_mean_20) END AS amount_change_5_20
                FROM features
                WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            ),
            long_values AS (
                SELECT date, asset, 'momentum_20' AS factor, momentum_20 AS value FROM wide
                UNION ALL SELECT date, asset, 'reversal_5', reversal_5 FROM wide
                UNION ALL SELECT date, asset, 'low_volatility_20', low_volatility_20 FROM wide
                UNION ALL SELECT date, asset, 'momentum_60_skip_5', momentum_60_skip_5 FROM wide
                UNION ALL SELECT date, asset, 'overnight_reversal_5', overnight_reversal_5 FROM wide
                UNION ALL SELECT date, asset, 'amihud_illiquidity_20', amihud_illiquidity_20 FROM wide
                UNION ALL SELECT date, asset, 'amount_change_5_20', amount_change_5_20 FROM wide
            )
            SELECT date, asset, factor, value
            FROM long_values
            WHERE value IS NOT NULL AND isfinite(value)
            ORDER BY date, asset, factor;

            CREATE INDEX IF NOT EXISTS idx_factor_raw_key
            ON factor_values_raw(date, asset, factor);
            """
        )
        available = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT factor FROM factor_values_raw"
            ).fetchall()
        }
        missing_factors = enabled - available
        if missing_factors:
            raise AssertionError(f"已启用因子无有效输出：{sorted(missing_factors)}")
        summary = connection.execute(
            """
            SELECT factor, count(*) AS observations,
                   count(DISTINCT date) AS dates,
                   count(DISTINCT asset) AS assets,
                   min(date) AS first_date, max(date) AS last_date
            FROM factor_values_raw GROUP BY factor ORDER BY factor
            """
        ).fetchdf()
        print(summary.to_string(index=False))
        print("[PASS] factor_values_raw 统一长表已建立。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
