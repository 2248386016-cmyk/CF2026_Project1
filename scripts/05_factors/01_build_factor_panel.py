"""01 - 建立不跨过停牌、ST和缺失行情的日频因子基础面板。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("01 建立因子基础面板")
    ensure_data_dirs()
    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        required = {"research_universe_daily", "daily_adjusted"}
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        missing = required - existing
        if missing:
            raise RuntimeError(
                f"缺少数据库表 {sorted(missing)}，请先运行动态资产池流水线。"
            )

        connection.execute(
            """
            CREATE OR REPLACE TABLE factor_panel AS
            WITH base AS (
                SELECT
                    u.trade_date AS date,
                    u.ts_code AS asset,
                    u.is_in_universe,
                    u.is_st,
                    u.is_known_suspended,
                    u.has_valid_market_data,
                    d.open_adj,
                    d.high_adj,
                    d.low_adj,
                    d.close_adj,
                    d.amount,
                    CASE
                        WHEN u.is_in_universe AND u.has_valid_market_data
                            THEN d.close_adj
                    END AS eligible_close,
                    CASE
                        WHEN u.is_in_universe AND u.has_valid_market_data
                            THEN d.open_adj
                    END AS eligible_open,
                    CASE
                        WHEN u.is_in_universe AND u.has_valid_market_data
                             AND d.amount > 0 THEN d.amount
                    END AS eligible_amount
                FROM research_universe_daily u
                LEFT JOIN daily_adjusted d
                  ON u.trade_date = d.trade_date AND u.ts_code = d.ts_code
            ),
            lagged AS (
                SELECT *,
                    lag(eligible_close, 1) OVER (
                        PARTITION BY asset ORDER BY date
                    ) AS previous_eligible_close
                FROM base
            )
            SELECT *,
                CASE
                    WHEN eligible_close IS NOT NULL
                     AND previous_eligible_close IS NOT NULL
                    THEN eligible_close / previous_eligible_close - 1
                END AS daily_return,
                CASE
                    WHEN eligible_open IS NOT NULL
                     AND previous_eligible_close IS NOT NULL
                    THEN ln(eligible_open / previous_eligible_close)
                END AS overnight_log_return
            FROM lagged
            ORDER BY asset, date;

            CREATE INDEX IF NOT EXISTS idx_factor_panel_asset_date
            ON factor_panel(asset, date);
            CREATE INDEX IF NOT EXISTS idx_factor_panel_date_asset
            ON factor_panel(date, asset);
            """
        )
        summary = connection.execute(
            """
            SELECT count(*) AS rows,
                   count(DISTINCT asset) AS assets,
                   min(date) AS first_date,
                   max(date) AS last_date,
                   count(*) FILTER (WHERE daily_return IS NOT NULL) AS valid_returns,
                   count(*) FILTER (WHERE overnight_log_return IS NOT NULL) AS valid_overnights
            FROM factor_panel
            """
        ).fetchdf()
        print(summary.to_string(index=False))
        print("[PASS] factor_panel 已建立。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
