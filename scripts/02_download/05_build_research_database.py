"""11 - 将验证后的 Parquet 原始数据导入单文件 DuckDB 研究数据库。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    ADJ_FACTOR_DIR,
    DAILY_DIR,
    DATABASE_DIR,
    REFERENCE_DIR,
    ensure_data_dirs,
    print_section,
)


def sql_path(path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def main() -> None:
    print_section("11 建立 DuckDB 研究数据库")
    ensure_data_dirs()

    if not list(DAILY_DIR.glob("*.parquet")) or not list(ADJ_FACTOR_DIR.glob("*.parquet")):
        raise FileNotFoundError("核心行情文件不存在，请先运行 08 和 10。")

    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE trade_calendar AS
            SELECT * FROM read_parquet('{sql_path(REFERENCE_DIR / 'trade_calendar.parquet')}');

            CREATE OR REPLACE TABLE stock_basic AS
            SELECT * FROM read_parquet('{sql_path(REFERENCE_DIR / 'stock_basic.parquet')}');

            CREATE OR REPLACE TABLE daily_raw AS
            SELECT * FROM read_parquet('{sql_path(DAILY_DIR / '*.parquet')}', union_by_name=true);

            CREATE OR REPLACE TABLE adj_factor AS
            SELECT * FROM read_parquet('{sql_path(ADJ_FACTOR_DIR / '*.parquet')}', union_by_name=true);
            """
        )

        connection.execute(
            """
            CREATE OR REPLACE TABLE daily_adjusted AS
            WITH factor_reference AS (
                SELECT ts_code, arg_max(adj_factor, trade_date) AS reference_factor
                FROM adj_factor
                GROUP BY ts_code
            )
            SELECT
                d.ts_code,
                strptime(CAST(d.trade_date AS VARCHAR), '%Y%m%d')::DATE AS trade_date,
                d.open,
                d.high,
                d.low,
                d.close,
                d.pre_close,
                d.change,
                d.pct_chg,
                d.vol,
                d.amount,
                a.adj_factor,
                r.reference_factor,
                d.open  * a.adj_factor / r.reference_factor AS open_adj,
                d.high  * a.adj_factor / r.reference_factor AS high_adj,
                d.low   * a.adj_factor / r.reference_factor AS low_adj,
                d.close * a.adj_factor / r.reference_factor AS close_adj
            FROM daily_raw d
            INNER JOIN adj_factor a USING (ts_code, trade_date)
            INNER JOIN factor_reference r USING (ts_code);
            """
        )

        connection.execute("CREATE INDEX IF NOT EXISTS idx_daily_adjusted_date_code ON daily_adjusted(trade_date, ts_code)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_stock_basic_code ON stock_basic(ts_code)")

        counts = connection.execute(
            """
            SELECT 'daily_raw' AS table_name, count(*) AS rows FROM daily_raw
            UNION ALL SELECT 'adj_factor', count(*) FROM adj_factor
            UNION ALL SELECT 'daily_adjusted', count(*) FROM daily_adjusted
            UNION ALL SELECT 'stock_basic', count(*) FROM stock_basic
            UNION ALL SELECT 'trade_calendar', count(*) FROM trade_calendar
            """
        ).fetchdf()
        duplicate_count = connection.execute(
            """
            SELECT count(*) FROM (
                SELECT trade_date, ts_code, count(*) AS n
                FROM daily_adjusted
                GROUP BY trade_date, ts_code
                HAVING n > 1
            )
            """
        ).fetchone()[0]
        if duplicate_count:
            raise AssertionError(f"daily_adjusted 存在 {duplicate_count} 个重复键。")

        print(counts.to_string(index=False))
        print(f"数据库文件：{database_path}")
        print("[PASS] DuckDB 研究数据库建立完成。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
