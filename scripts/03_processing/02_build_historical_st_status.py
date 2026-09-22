"""02 - 导入历史名称并构造沪深主板每日 ST 状态。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATABASE_DIR,
    NAMECHANGE_DIR,
    PROCESSING_OUTPUT_DIR,
    ensure_data_dirs,
    print_section,
)


def sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def main() -> None:
    print_section("02 构造历史 ST 状态")
    ensure_data_dirs()

    files = sorted(NAMECHANGE_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"没有历史名称文件：{NAMECHANGE_DIR}。"
            "请先运行 scripts/02_download/07_download_mainboard_namechange.py。"
        )

    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    if not database_path.exists():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE namechange_history AS
            SELECT DISTINCT
                TRIM(ts_code) AS ts_code,
                TRIM(name) AS name,
                TRY_STRPTIME(NULLIF(TRIM(CAST(start_date AS VARCHAR)), ''), '%Y%m%d')::DATE AS start_date,
                TRY_STRPTIME(NULLIF(TRIM(CAST(end_date AS VARCHAR)), ''), '%Y%m%d')::DATE AS end_date,
                TRY_STRPTIME(NULLIF(TRIM(CAST(ann_date AS VARCHAR)), ''), '%Y%m%d')::DATE AS ann_date,
                change_reason,
                REGEXP_MATCHES(UPPER(TRIM(name)), '^(S\\*?ST|\\*?ST)') AS is_st_name
            FROM read_parquet('{sql_path(NAMECHANGE_DIR / '*.parquet')}', union_by_name=true)
            WHERE ts_code IS NOT NULL AND name IS NOT NULL;
            """
        )

        invalid_intervals = connection.execute(
            """
            SELECT count(*)
            FROM namechange_history
            WHERE start_date IS NULL
               OR (end_date IS NOT NULL AND end_date < start_date)
            """
        ).fetchone()[0]
        if invalid_intervals:
            raise AssertionError(f"历史名称存在 {invalid_intervals} 条非法日期区间。")

        # 只为实际存在行情的日期生成 ST 状态，避免构造股票×全部日历的巨大笛卡尔积。
        connection.execute(
            """
            CREATE OR REPLACE TABLE stock_st_daily AS
            SELECT DISTINCT
                d.ts_code,
                d.trade_date,
                n.name,
                'NAMECHANGE' AS type,
                '由历史名称区间识别' AS type_name
            FROM daily_adjusted d
            INNER JOIN namechange_history n
                ON d.ts_code = n.ts_code
               AND d.trade_date >= n.start_date
               AND d.trade_date <= COALESCE(n.end_date, DATE '9999-12-31')
            WHERE n.is_st_name;

            CREATE INDEX IF NOT EXISTS idx_namechange_code_dates
            ON namechange_history(ts_code, start_date, end_date);
            CREATE INDEX IF NOT EXISTS idx_st_date_code
            ON stock_st_daily(trade_date, ts_code);
            """
        )

        duplicate_st_keys = connection.execute(
            """
            SELECT count(*) FROM (
                SELECT trade_date, ts_code
                FROM stock_st_daily
                GROUP BY trade_date, ts_code
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        if duplicate_st_keys:
            raise AssertionError(f"stock_st_daily 存在 {duplicate_st_keys} 个重复键。")

        summary = connection.execute(
            """
            SELECT
                count(*) AS namechange_rows,
                count(DISTINCT ts_code) AS stocks_with_name_history,
                count(*) FILTER (WHERE is_st_name) AS st_name_intervals,
                count(DISTINCT ts_code) FILTER (WHERE is_st_name) AS stocks_ever_st,
                (SELECT count(*) FROM stock_st_daily) AS daily_st_rows,
                (SELECT count(DISTINCT ts_code) FROM stock_st_daily) AS daily_st_stocks,
                (SELECT min(trade_date) FROM stock_st_daily) AS first_st_date,
                (SELECT max(trade_date) FROM stock_st_daily) AS last_st_date
            FROM namechange_history
            """
        ).fetchdf()

        intervals = connection.execute(
            """
            SELECT ts_code, name, start_date, end_date, ann_date, change_reason
            FROM namechange_history
            WHERE is_st_name
            ORDER BY ts_code, start_date
            """
        ).fetchdf()

        summary.to_csv(
            PROCESSING_OUTPUT_DIR / "02_historical_st_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        intervals.to_csv(
            PROCESSING_OUTPUT_DIR / "02_historical_st_intervals.csv",
            index=False,
            encoding="utf-8-sig",
        )

        print(f"历史名称文件数：{len(files)}")
        print(summary.to_string(index=False))
        print(f"ST 区间报告：{PROCESSING_OUTPUT_DIR / '02_historical_st_intervals.csv'}")
        print("[PASS] 历史名称已导入，stock_st_daily 已构造。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
