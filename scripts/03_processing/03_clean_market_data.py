"""03 - 标准化字段、添加质量与交易状态标记，并建立清洗行情表。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("03 清洗和标准化市场数据")
    ensure_data_dirs()
    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    connection = duckdb.connect(str(database_path))
    try:
        required_tables = {
            "daily_adjusted",
            "stock_basic",
            "suspend_daily",
            "stk_limit_daily",
            "stock_st_daily",
        }
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        missing = required_tables - existing
        if missing:
            raise RuntimeError(
                f"缺少数据库表 {sorted(missing)}。请先运行 01_import_optional_data.py。"
            )

        connection.execute(
            """
            CREATE OR REPLACE VIEW stock_basic_standardized AS
            SELECT
                TRIM(ts_code) AS ts_code,
                symbol,
                name,
                area,
                industry,
                market,
                exchange,
                list_status,
                TRY_STRPTIME(NULLIF(TRIM(CAST(list_date AS VARCHAR)), ''), '%Y%m%d')::DATE AS list_date,
                TRY_STRPTIME(NULLIF(TRIM(CAST(delist_date AS VARCHAR)), ''), '%Y%m%d')::DATE AS delist_date
            FROM stock_basic;

            CREATE OR REPLACE VIEW market_data_enriched AS
            SELECT
                TRIM(d.ts_code) AS ts_code,
                d.trade_date,
                s.symbol,
                s.name,
                s.area,
                s.industry,
                s.market,
                s.exchange,
                s.list_status,
                s.list_date,
                s.delist_date,
                d.open,
                d.high,
                d.low,
                d.close,
                d.pre_close,
                d.change,
                d.pct_chg,
                d.vol,
                d.amount,
                d.adj_factor,
                d.reference_factor,
                d.open_adj,
                d.high_adj,
                d.low_adj,
                d.close_adj,
                l.limit_pre_close,
                l.up_limit,
                l.down_limit,
                COALESCE(p.is_suspended, FALSE) AS is_suspended,
                COALESCE(st.is_st, FALSE) AS is_st,
                (
                    s.exchange IN ('SSE', 'SZSE')
                    AND s.market = '主板'
                ) AS is_research_universe,
                (
                    s.exchange IN ('SSE', 'SZSE')
                    AND s.market = '主板'
                    AND EXISTS (SELECT 1 FROM stock_st_daily LIMIT 1)
                ) AS st_data_available,
                s.ts_code IS NOT NULL AS has_stock_metadata,
                (
                    s.list_date IS NOT NULL
                    AND d.trade_date >= s.list_date
                    AND (s.delist_date IS NULL OR d.trade_date <= s.delist_date)
                ) AS is_listed_on_date,
                (
                    d.open IS NULL OR d.high IS NULL OR d.low IS NULL OR d.close IS NULL
                    OR d.open <= 0 OR d.high <= 0 OR d.low <= 0 OR d.close <= 0
                    OR d.high < GREATEST(d.open, d.close, d.low)
                    OR d.low > LEAST(d.open, d.close, d.high)
                ) AS has_invalid_raw_price,
                (
                    d.open_adj IS NULL OR d.high_adj IS NULL OR d.low_adj IS NULL OR d.close_adj IS NULL
                    OR d.open_adj <= 0 OR d.high_adj <= 0 OR d.low_adj <= 0 OR d.close_adj <= 0
                    OR d.high_adj < GREATEST(d.open_adj, d.close_adj, d.low_adj)
                    OR d.low_adj > LEAST(d.open_adj, d.close_adj, d.high_adj)
                ) AS has_invalid_adjusted_price,
                (d.adj_factor IS NULL OR d.adj_factor <= 0) AS has_invalid_adj_factor,
                (d.vol IS NULL OR d.vol < 0) AS has_invalid_volume,
                (d.amount IS NULL OR d.amount < 0) AS has_invalid_amount,
                (d.vol = 0) AS has_zero_volume,
                (
                    l.up_limit IS NOT NULL
                    AND ABS(d.open - l.up_limit) <= GREATEST(0.001, ABS(l.up_limit) * 0.000001)
                ) AS is_open_at_up_limit,
                (
                    l.down_limit IS NOT NULL
                    AND ABS(d.open - l.down_limit) <= GREATEST(0.001, ABS(l.down_limit) * 0.000001)
                ) AS is_open_at_down_limit,
                (
                    l.up_limit IS NOT NULL
                    AND ABS(d.close - l.up_limit) <= GREATEST(0.001, ABS(l.up_limit) * 0.000001)
                ) AS is_close_at_up_limit,
                (
                    l.down_limit IS NOT NULL
                    AND ABS(d.close - l.down_limit) <= GREATEST(0.001, ABS(l.down_limit) * 0.000001)
                ) AS is_close_at_down_limit
            FROM daily_adjusted d
            LEFT JOIN stock_basic_standardized s USING (ts_code)
            LEFT JOIN (
                SELECT trade_date, ts_code, TRUE AS is_suspended
                FROM suspend_daily
                WHERE suspend_type = 'S'
                GROUP BY trade_date, ts_code
            ) p USING (trade_date, ts_code)
            LEFT JOIN stk_limit_daily l USING (trade_date, ts_code)
            LEFT JOIN (
                SELECT trade_date, ts_code, TRUE AS is_st
                FROM stock_st_daily
                GROUP BY trade_date, ts_code
            ) st USING (trade_date, ts_code);
            """
        )

        connection.execute(
            """
            CREATE OR REPLACE TABLE market_data_clean AS
            SELECT *,
                (
                    NOT is_suspended
                    AND NOT has_zero_volume
                    AND NOT is_open_at_up_limit
                    AND NOT is_open_at_down_limit
                ) AS can_trade_at_open
            FROM market_data_enriched
            WHERE
                has_stock_metadata
                AND is_research_universe
                AND is_listed_on_date
                AND NOT has_invalid_raw_price
                AND NOT has_invalid_adjusted_price
                AND NOT has_invalid_adj_factor
                AND NOT has_invalid_volume
                AND NOT has_invalid_amount
                AND NOT is_st;

            CREATE INDEX IF NOT EXISTS idx_clean_date_code
            ON market_data_clean(trade_date, ts_code);
            CREATE INDEX IF NOT EXISTS idx_clean_code_date
            ON market_data_clean(ts_code, trade_date);
            """
        )

        audit = connection.execute(
            """
            SELECT
                count(*) AS raw_rows,
                count(*) FILTER (WHERE NOT has_stock_metadata) AS missing_stock_metadata,
                count(*) FILTER (WHERE has_stock_metadata AND NOT is_research_universe) AS outside_research_universe,
                count(*) FILTER (WHERE has_stock_metadata AND NOT is_listed_on_date) AS outside_listing_period,
                count(*) FILTER (WHERE has_invalid_raw_price) AS invalid_raw_price,
                count(*) FILTER (WHERE has_invalid_adjusted_price) AS invalid_adjusted_price,
                count(*) FILTER (WHERE has_invalid_adj_factor) AS invalid_adj_factor,
                count(*) FILTER (WHERE has_invalid_volume) AS invalid_volume,
                count(*) FILTER (WHERE has_invalid_amount) AS invalid_amount,
                count(*) FILTER (WHERE is_st) AS historical_st_records,
                count(*) FILTER (WHERE is_suspended) AS suspended_records,
                count(*) FILTER (WHERE has_zero_volume) AS zero_volume_records,
                count(*) FILTER (WHERE is_open_at_up_limit) AS open_at_up_limit,
                count(*) FILTER (WHERE is_open_at_down_limit) AS open_at_down_limit
            FROM market_data_enriched
            """
        ).fetchdf()
        clean_rows = connection.execute("SELECT count(*) FROM market_data_clean").fetchone()[0]

        print(audit.to_string(index=False))
        print(f"clean_rows: {clean_rows}")
        print("说明：停牌、零成交量和开盘涨跌停记录被保留并标记，不在清洗阶段删除。")
        print("说明：最终研究范围限定为上交所和深交所主板，排除创业板、科创板和北交所。")
        print("说明：历史名称处于 ST 区间的记录已从 market_data_clean 排除。")
        print("[PASS] market_data_clean 已重新建立。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
