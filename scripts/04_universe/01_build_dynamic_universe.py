"""01 - 按交易日、上市区间和历史 ST 状态构建沪深主板动态资产池。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATABASE_DIR,
    DOWNLOAD_END_DATE,
    DOWNLOAD_START_DATE,
    ensure_data_dirs,
    print_section,
)


def main() -> None:
    print_section("01 构建沪深主板动态资产池")
    ensure_data_dirs()
    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    start_date = f"{DOWNLOAD_START_DATE[:4]}-{DOWNLOAD_START_DATE[4:6]}-{DOWNLOAD_START_DATE[6:]}"
    end_date = f"{DOWNLOAD_END_DATE[:4]}-{DOWNLOAD_END_DATE[4:6]}-{DOWNLOAD_END_DATE[6:]}"

    connection = duckdb.connect(str(database_path))
    try:
        required = {
            "trade_calendar",
            "stock_basic_standardized",
            "stock_st_daily",
            "daily_adjusted",
            "suspend_daily",
        }
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        missing = required - existing
        if missing:
            raise RuntimeError(
                f"缺少数据库表 {sorted(missing)}，请先运行 03_processing/05_run_processing_pipeline.py。"
            )

        connection.execute(
            f"""
            CREATE OR REPLACE TABLE research_universe_daily AS
            WITH open_dates AS (
                SELECT DISTINCT TRY_STRPTIME(cal_date, '%Y%m%d')::DATE AS trade_date
                FROM trade_calendar
                WHERE is_open = 1
                  AND TRY_STRPTIME(cal_date, '%Y%m%d')::DATE
                      BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            ),
            mainboard_stocks AS (
                SELECT DISTINCT
                    ts_code, symbol, name, exchange, market, list_status,
                    list_date, delist_date
                FROM stock_basic_standardized
                WHERE exchange IN ('SSE', 'SZSE')
                  AND market = '主板'
                  AND list_date IS NOT NULL
                  -- 显式排除深市 200xxx 和沪市 900xxx B 股代码。
                  AND NOT REGEXP_MATCHES(COALESCE(symbol, ''), '^(200|900)')
            ),
            listed_panel AS (
                SELECT d.trade_date, s.*
                FROM open_dates d
                JOIN mainboard_stocks s
                  ON d.trade_date >= s.list_date
                 AND (s.delist_date IS NULL OR d.trade_date <= s.delist_date)
            ),
            prices AS (
                SELECT
                    trade_date,
                    ts_code,
                    TRUE AS has_market_data,
                    BOOL_AND(
                        open > 0 AND high > 0 AND low > 0 AND close > 0
                        AND open_adj > 0 AND high_adj > 0
                        AND low_adj > 0 AND close_adj > 0
                        AND adj_factor > 0 AND vol >= 0 AND amount >= 0
                    ) AS has_valid_market_data
                FROM daily_adjusted
                GROUP BY trade_date, ts_code
            ),
            suspensions AS (
                SELECT trade_date, ts_code, TRUE AS is_known_suspended
                FROM suspend_daily
                WHERE suspend_type = 'S'
                GROUP BY trade_date, ts_code
            ),
            st_status AS (
                SELECT trade_date, ts_code, TRUE AS is_st
                FROM stock_st_daily
                GROUP BY trade_date, ts_code
            )
            SELECT
                p.trade_date,
                p.ts_code,
                p.symbol,
                p.name,
                p.exchange,
                p.market,
                p.list_status,
                p.list_date,
                p.delist_date,
                TRUE AS is_listed_on_date,
                TRUE AS is_mainboard_a_share,
                COALESCE(st.is_st, FALSE) AS is_st,
                NOT COALESCE(st.is_st, FALSE) AS is_in_universe,
                COALESCE(px.has_market_data, FALSE) AS has_market_data,
                COALESCE(px.has_valid_market_data, FALSE) AS has_valid_market_data,
                COALESCE(su.is_known_suspended, FALSE) AS is_known_suspended,
                CASE
                    WHEN COALESCE(st.is_st, FALSE) THEN 'historical_st'
                    ELSE NULL
                END AS exclusion_reason,
                CASE
                    WHEN COALESCE(st.is_st, FALSE) THEN 'excluded_st'
                    WHEN COALESCE(px.has_valid_market_data, FALSE) THEN 'covered'
                    WHEN COALESCE(su.is_known_suspended, FALSE) THEN 'missing_known_suspension'
                    WHEN NOT COALESCE(px.has_market_data, FALSE) THEN 'missing_unexplained'
                    ELSE 'invalid_market_data'
                END AS coverage_status
            FROM listed_panel p
            LEFT JOIN prices px USING (trade_date, ts_code)
            LEFT JOIN suspensions su USING (trade_date, ts_code)
            LEFT JOIN st_status st USING (trade_date, ts_code);

            CREATE OR REPLACE VIEW research_universe_members AS
            SELECT *
            FROM research_universe_daily
            WHERE is_in_universe;

            CREATE INDEX IF NOT EXISTS idx_universe_date_code
            ON research_universe_daily(trade_date, ts_code);
            CREATE INDEX IF NOT EXISTS idx_universe_code_date
            ON research_universe_daily(ts_code, trade_date);
            """
        )

        result = connection.execute(
            """
            SELECT
                min(trade_date) AS first_date,
                max(trade_date) AS last_date,
                count(DISTINCT trade_date) AS trading_days,
                count(DISTINCT ts_code) AS stocks_ever_listed,
                count(*) AS listed_stock_days,
                count(*) FILTER (WHERE is_st) AS excluded_st_days,
                count(*) FILTER (WHERE is_in_universe) AS universe_stock_days,
                count(*) FILTER (WHERE is_in_universe AND has_valid_market_data)
                    AS covered_stock_days
            FROM research_universe_daily
            """
        ).fetchdf()
        print(result.to_string(index=False))
        print("[PASS] research_universe_daily 和 research_universe_members 已建立。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
