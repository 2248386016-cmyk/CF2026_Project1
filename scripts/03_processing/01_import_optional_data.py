"""01 - 将停牌、涨跌停和可用的 ST 文件导入现有 DuckDB。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATABASE_DIR,
    STOCK_ST_DIR,
    STK_LIMIT_DIR,
    SUSPEND_DIR,
    ensure_data_dirs,
    print_section,
)


def sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def require_files(directory: Path, dataset: str) -> list[Path]:
    files = sorted(directory.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"{dataset} 没有 Parquet 文件：{directory}。"
            "请先运行 scripts/02_download/03_download_optional_constraints.py。"
        )
    return files


def main() -> None:
    print_section("01 导入可选交易约束数据")
    ensure_data_dirs()

    suspend_files = require_files(SUSPEND_DIR, "suspend")
    limit_files = require_files(STK_LIMIT_DIR, "stk_limit")
    st_files = sorted(STOCK_ST_DIR.glob("*.parquet"))

    database_path = DATABASE_DIR / "cf2026_project1.duckdb"
    if not database_path.exists():
        raise FileNotFoundError(f"核心数据库不存在：{database_path}")

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE suspend_daily AS
            SELECT DISTINCT
                TRIM(ts_code) AS ts_code,
                TRY_STRPTIME(CAST(trade_date AS VARCHAR), '%Y%m%d')::DATE AS trade_date,
                suspend_timing,
                suspend_type
            FROM read_parquet('{sql_path(SUSPEND_DIR / '*.parquet')}', union_by_name=true)
            WHERE ts_code IS NOT NULL AND trade_date IS NOT NULL;

            CREATE OR REPLACE TABLE stk_limit_daily AS
            SELECT DISTINCT
                TRIM(ts_code) AS ts_code,
                TRY_STRPTIME(CAST(trade_date AS VARCHAR), '%Y%m%d')::DATE AS trade_date,
                pre_close AS limit_pre_close,
                up_limit,
                down_limit,
                asset_type,
                exchange AS limit_exchange
            FROM read_parquet('{sql_path(STK_LIMIT_DIR / '*.parquet')}', union_by_name=true)
            WHERE ts_code IS NOT NULL AND trade_date IS NOT NULL;
            """
        )

        if st_files:
            connection.execute(
                f"""
                CREATE OR REPLACE TABLE stock_st_daily AS
                SELECT DISTINCT
                    TRIM(ts_code) AS ts_code,
                    TRY_STRPTIME(CAST(trade_date AS VARCHAR), '%Y%m%d')::DATE AS trade_date,
                    name,
                    type,
                    type_name
                FROM read_parquet('{sql_path(STOCK_ST_DIR / '*.parquet')}', union_by_name=true)
                WHERE ts_code IS NOT NULL AND trade_date IS NOT NULL;
                """
            )
            st_available = True
        else:
            connection.execute(
                """
                CREATE OR REPLACE TABLE stock_st_daily (
                    ts_code VARCHAR,
                    trade_date DATE,
                    name VARCHAR,
                    type VARCHAR,
                    type_name VARCHAR
                );
                """
            )
            st_available = False

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_suspend_date_code ON suspend_daily(trade_date, ts_code)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_limit_date_code ON stk_limit_daily(trade_date, ts_code)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_st_date_code ON stock_st_daily(trade_date, ts_code)"
        )

        counts = connection.execute(
            """
            SELECT 'suspend_daily' AS table_name, count(*) AS rows FROM suspend_daily
            UNION ALL SELECT 'stk_limit_daily', count(*) FROM stk_limit_daily
            UNION ALL SELECT 'stock_st_daily', count(*) FROM stock_st_daily
            """
        ).fetchdf()

        duplicate_counts = connection.execute(
            """
            SELECT 'suspend_daily' AS table_name, count(*) AS duplicate_keys
            FROM (
                SELECT trade_date, ts_code FROM suspend_daily
                GROUP BY trade_date, ts_code HAVING count(*) > 1
            )
            UNION ALL
            SELECT 'stk_limit_daily', count(*)
            FROM (
                SELECT trade_date, ts_code FROM stk_limit_daily
                GROUP BY trade_date, ts_code HAVING count(*) > 1
            )
            UNION ALL
            SELECT 'stock_st_daily', count(*)
            FROM (
                SELECT trade_date, ts_code FROM stock_st_daily
                GROUP BY trade_date, ts_code HAVING count(*) > 1
            )
            """
        ).fetchdf()

        if int(duplicate_counts["duplicate_keys"].sum()) != 0:
            raise AssertionError(f"可选数据存在重复键：\n{duplicate_counts}")

        print(f"停牌文件数：{len(suspend_files)}")
        print(f"涨跌停文件数：{len(limit_files)}")
        print(f"ST 数据可用：{st_available}")
        print(counts.to_string(index=False))
        if not st_available:
            print("[NOTICE] 官方 stock_st 无权限；已建立空表，后续不会假装已排除 ST。")
        print("[PASS] 可选交易约束数据已导入 DuckDB。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
