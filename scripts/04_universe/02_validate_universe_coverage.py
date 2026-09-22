"""02 - 验证动态资产池唯一性、入池口径和行情覆盖率。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATABASE_DIR,
    PROJECT_END_DATE,
    PROJECT_START_DATE,
    UNIVERSE_OUTPUT_DIR,
    ensure_data_dirs,
    print_section,
)


def main() -> None:
    print_section("02 验证动态资产池及覆盖率")
    ensure_data_dirs()
    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    start_date = f"{PROJECT_START_DATE[:4]}-{PROJECT_START_DATE[4:6]}-{PROJECT_START_DATE[6:]}"
    end_date = f"{PROJECT_END_DATE[:4]}-{PROJECT_END_DATE[4:6]}-{PROJECT_END_DATE[6:]}"

    connection = duckdb.connect(str(database_path))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        if "research_universe_daily" not in tables:
            raise RuntimeError(
                "缺少 research_universe_daily，请先运行 01_build_dynamic_universe.py。"
            )

        checks = connection.execute(
            f"""
            SELECT
                (SELECT count(*) FROM (
                    SELECT trade_date, ts_code
                    FROM research_universe_daily
                    GROUP BY trade_date, ts_code
                    HAVING count(*) > 1
                )) AS duplicate_keys,
                count(*) FILTER (
                    WHERE exchange NOT IN ('SSE', 'SZSE') OR market <> '主板'
                ) AS outside_mainboard,
                count(*) FILTER (
                    WHERE trade_date < list_date
                       OR (delist_date IS NOT NULL AND trade_date > delist_date)
                ) AS outside_listing_period,
                count(*) FILTER (WHERE is_in_universe AND is_st) AS included_st_rows,
                count(*) FILTER (
                    WHERE is_in_universe AND coverage_status = 'excluded_st'
                ) AS inconsistent_status,
                count(*) FILTER (
                    WHERE trade_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
                      AND is_in_universe AND NOT has_valid_market_data
                      AND NOT is_known_suspended
                ) AS unexplained_or_invalid_missing_rows
            FROM research_universe_daily
            """
        ).fetchdf()

        daily = connection.execute(
            f"""
            SELECT
                trade_date,
                count(*) AS listed_mainboard_stocks,
                count(*) FILTER (WHERE is_st) AS excluded_st_stocks,
                count(*) FILTER (WHERE is_in_universe) AS theoretical_universe_stocks,
                count(*) FILTER (
                    WHERE is_in_universe AND has_valid_market_data
                ) AS covered_stocks,
                count(*) FILTER (
                    WHERE is_in_universe AND NOT has_valid_market_data
                      AND is_known_suspended
                ) AS missing_known_suspension,
                count(*) FILTER (
                    WHERE is_in_universe AND NOT has_valid_market_data
                      AND NOT is_known_suspended
                ) AS missing_unexplained_or_invalid,
                round(
                    100.0 * count(*) FILTER (
                        WHERE is_in_universe AND has_valid_market_data
                    ) / NULLIF(count(*) FILTER (WHERE is_in_universe), 0),
                    4
                ) AS coverage_pct
            FROM research_universe_daily
            WHERE trade_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ).fetchdf()

        yearly = connection.execute(
            f"""
            SELECT
                year(trade_date) AS year,
                count(DISTINCT trade_date) AS trading_days,
                count(DISTINCT ts_code) FILTER (WHERE is_in_universe)
                    AS distinct_universe_stocks,
                count(*) FILTER (WHERE is_in_universe) AS theoretical_stock_days,
                count(*) FILTER (
                    WHERE is_in_universe AND has_valid_market_data
                ) AS covered_stock_days,
                count(*) FILTER (
                    WHERE is_in_universe AND NOT has_valid_market_data
                      AND is_known_suspended
                ) AS missing_known_suspension,
                count(*) FILTER (
                    WHERE is_in_universe AND NOT has_valid_market_data
                      AND NOT is_known_suspended
                ) AS missing_unexplained_or_invalid,
                round(
                    100.0 * count(*) FILTER (
                        WHERE is_in_universe AND has_valid_market_data
                    ) / NULLIF(count(*) FILTER (WHERE is_in_universe), 0),
                    4
                ) AS coverage_pct
            FROM research_universe_daily
            WHERE trade_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            GROUP BY year(trade_date)
            ORDER BY year
            """
        ).fetchdf()

        missing_detail = connection.execute(
            f"""
            SELECT
                trade_date, ts_code, name, exchange, market,
                is_known_suspended, has_market_data,
                has_valid_market_data, coverage_status
            FROM research_universe_daily
            WHERE trade_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
              AND is_in_universe
              AND NOT has_valid_market_data
            ORDER BY trade_date, ts_code
            """
        ).fetchdf()

        checks.to_csv(
            UNIVERSE_OUTPUT_DIR / "02_universe_checks.csv",
            index=False,
            encoding="utf-8-sig",
        )
        daily.to_csv(
            UNIVERSE_OUTPUT_DIR / "02_daily_universe_coverage.csv",
            index=False,
            encoding="utf-8-sig",
        )
        yearly.to_csv(
            UNIVERSE_OUTPUT_DIR / "02_yearly_universe_coverage.csv",
            index=False,
            encoding="utf-8-sig",
        )
        missing_detail.to_csv(
            UNIVERSE_OUTPUT_DIR / "02_missing_market_data_detail.csv",
            index=False,
            encoding="utf-8-sig",
        )

        print("关键检查：")
        print(checks.to_string(index=False))
        print("\n年度覆盖率：")
        print(yearly.to_string(index=False))

        critical = [
            "duplicate_keys",
            "outside_mainboard",
            "outside_listing_period",
            "included_st_rows",
            "inconsistent_status",
        ]
        failures = {
            column: int(checks.iloc[0][column])
            for column in critical
            if int(checks.iloc[0][column]) != 0
        }
        if failures:
            raise AssertionError(f"动态资产池未通过关键检查：{failures}")
        if daily.empty or (daily["theoretical_universe_stocks"] <= 0).any():
            raise AssertionError("研究期内存在空资产池日期。")
        if ((daily["coverage_pct"] < 0) | (daily["coverage_pct"] > 100)).any():
            raise AssertionError("覆盖率不在 0%-100% 范围内。")

        print(f"\n报告目录：{UNIVERSE_OUTPUT_DIR}")
        print("[PASS] 动态资产池口径和覆盖率验证完成。")
        if int(checks.iloc[0]["unexplained_or_invalid_missing_rows"]) > 0:
            print("[NOTICE] 存在非已知停牌的缺失/无效行情，请查看明细报告，不会静默删除。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
