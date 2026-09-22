"""04 - 验证清洗表并输出清洗前后数量、覆盖率和市场分布报告。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATABASE_DIR,
    PROCESSING_OUTPUT_DIR,
    ensure_data_dirs,
    print_section,
)


def main() -> None:
    print_section("04 验证清洗后数据")
    ensure_data_dirs()
    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        if "market_data_clean" not in tables:
            raise RuntimeError("缺少 market_data_clean，请先运行 03_clean_market_data.py。")

        summary = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM daily_adjusted) AS input_rows,
                count(*) AS clean_rows,
                min(trade_date) AS first_date,
                max(trade_date) AS last_date,
                count(DISTINCT trade_date) AS trading_days,
                count(DISTINCT ts_code) AS distinct_stocks,
                round(
                    100.0 * count(*)
                    / NULLIF((SELECT count(*) FROM market_data_enriched
                              WHERE has_stock_metadata AND is_research_universe
                                AND is_listed_on_date), 0),
                    4
                ) AS clean_retention_pct,
                count(*) FILTER (WHERE is_suspended) AS suspended_records,
                count(*) FILTER (WHERE has_zero_volume) AS zero_volume_records,
                count(*) FILTER (WHERE is_open_at_up_limit) AS open_at_up_limit,
                count(*) FILTER (WHERE is_open_at_down_limit) AS open_at_down_limit,
                count(*) FILTER (WHERE can_trade_at_open) AS tradable_at_open_records,
                count(*) FILTER (WHERE st_data_available) AS rows_with_st_dataset_available
            FROM market_data_clean
            """
        ).fetchdf()

        checks = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM (
                    SELECT trade_date, ts_code FROM market_data_clean
                    GROUP BY trade_date, ts_code HAVING count(*) > 1
                )) AS duplicate_keys,
                count(*) FILTER (
                    WHERE has_invalid_raw_price OR has_invalid_adjusted_price
                       OR has_invalid_adj_factor OR has_invalid_volume OR has_invalid_amount
                ) AS remaining_invalid_rows,
                count(*) FILTER (WHERE NOT has_stock_metadata) AS missing_metadata,
                count(*) FILTER (WHERE NOT is_listed_on_date) AS outside_listing_period,
                count(*) FILTER (WHERE NOT is_research_universe) AS outside_research_universe,
                count(*) FILTER (WHERE is_st) AS remaining_st_rows,
                count(*) FILTER (
                    WHERE ts_code IS NULL OR trade_date IS NULL OR exchange IS NULL OR market IS NULL
                ) AS missing_required_identifiers
            FROM market_data_clean
            """
        ).fetchdf()

        daily = connection.execute(
            """
            SELECT
                trade_date,
                count(*) AS clean_rows,
                count(*) FILTER (WHERE exchange IN ('SSE', 'SZSE')) AS sh_sz_rows,
                count(*) FILTER (WHERE market = '主板') AS main_board_rows,
                count(*) FILTER (WHERE market = '创业板') AS gem_rows,
                count(*) FILTER (WHERE market = '科创板') AS star_rows,
                count(*) FILTER (WHERE is_suspended) AS suspended_rows,
                count(*) FILTER (WHERE can_trade_at_open) AS tradable_at_open_rows
            FROM market_data_clean
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).fetchdf()

        yearly = connection.execute(
            """
            SELECT
                year(trade_date) AS year,
                market,
                count(DISTINCT ts_code) AS distinct_stocks,
                count(*) AS observations
            FROM market_data_clean
            GROUP BY year(trade_date), market
            ORDER BY year, market
            """
        ).fetchdf()

        summary.to_csv(
            PROCESSING_OUTPUT_DIR / "04_cleaning_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        checks.to_csv(
            PROCESSING_OUTPUT_DIR / "04_cleaning_checks.csv",
            index=False,
            encoding="utf-8-sig",
        )
        daily.to_csv(
            PROCESSING_OUTPUT_DIR / "04_daily_clean_coverage.csv",
            index=False,
            encoding="utf-8-sig",
        )
        yearly.to_csv(
            PROCESSING_OUTPUT_DIR / "04_yearly_market_distribution.csv",
            index=False,
            encoding="utf-8-sig",
        )

        print("清洗汇总：")
        print(summary.to_string(index=False))
        print("\n关键检查：")
        print(checks.to_string(index=False))

        critical_columns = [
            "duplicate_keys",
            "remaining_invalid_rows",
            "missing_metadata",
            "outside_listing_period",
            "outside_research_universe",
            "remaining_st_rows",
            "missing_required_identifiers",
        ]
        failures = {
            column: int(checks.iloc[0][column])
            for column in critical_columns
            if int(checks.iloc[0][column]) != 0
        }
        if failures:
            raise AssertionError(f"清洗后数据未通过关键检查：{failures}")

        if int(summary.iloc[0]["clean_rows"]) == 0:
            raise AssertionError("清洗后数据为空。")

        print(f"\n质量报告目录：{PROCESSING_OUTPUT_DIR}")
        if int(summary.iloc[0]["rows_with_st_dataset_available"]) == 0:
            raise AssertionError("沪深主板历史 ST 数据未接入，不能验证 ST 排除结果。")
        print("[PASS] 清洗后数据全部关键检查通过。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
