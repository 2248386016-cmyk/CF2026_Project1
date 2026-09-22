"""01 - 构建从 T+1 开始的1/5/20日未来收益标签。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("01 构建未来收益标签")
    ensure_data_dirs()
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        connection.execute(
            """
            CREATE OR REPLACE TABLE forward_returns AS
            WITH base AS (
                SELECT
                    p.date,
                    p.asset,
                    p.eligible_close,
                    p.is_in_universe,
                    p.has_valid_market_data,
                    (
                        p.is_in_universe
                        AND p.has_valid_market_data
                        AND NOT COALESCE(m.is_suspended, FALSE)
                        AND NOT COALESCE(m.has_zero_volume, FALSE)
                        AND NOT COALESCE(m.is_open_at_up_limit, FALSE)
                        AND NOT COALESCE(m.is_open_at_down_limit, FALSE)
                    ) AS can_enter_at_open
                FROM factor_panel p
                LEFT JOIN market_data_enriched m
                  ON p.date = m.trade_date AND p.asset = m.ts_code
            ),
            future AS (
                SELECT *,
                    lead(date, 1) OVER w AS entry_date,
                    lead(eligible_close, 1) OVER w AS entry_close,
                    lead(can_enter_at_open, 1) OVER w AS entry_is_tradable,
                    lead(date, 2) OVER w AS exit_date_1d,
                    lead(eligible_close, 2) OVER w AS exit_close_1d,
                    lead(date, 6) OVER w AS exit_date_5d,
                    lead(eligible_close, 6) OVER w AS exit_close_5d,
                    lead(date, 21) OVER w AS exit_date_20d,
                    lead(eligible_close, 21) OVER w AS exit_close_20d,
                    count(eligible_close) OVER (
                        PARTITION BY asset ORDER BY date
                        ROWS BETWEEN 1 FOLLOWING AND 2 FOLLOWING
                    ) AS valid_prices_1d,
                    count(eligible_close) OVER (
                        PARTITION BY asset ORDER BY date
                        ROWS BETWEEN 1 FOLLOWING AND 6 FOLLOWING
                    ) AS valid_prices_5d,
                    count(eligible_close) OVER (
                        PARTITION BY asset ORDER BY date
                        ROWS BETWEEN 1 FOLLOWING AND 21 FOLLOWING
                    ) AS valid_prices_20d
                FROM base
                WINDOW w AS (PARTITION BY asset ORDER BY date)
            )
            SELECT
                date,
                asset,
                entry_date,
                exit_date_1d,
                exit_date_5d,
                exit_date_20d,
                CASE WHEN entry_is_tradable AND valid_prices_1d = 2
                     THEN exit_close_1d / entry_close - 1 END AS forward_return_1d,
                CASE WHEN entry_is_tradable AND valid_prices_5d = 6
                     THEN exit_close_5d / entry_close - 1 END AS forward_return_5d,
                CASE WHEN entry_is_tradable AND valid_prices_20d = 21
                     THEN exit_close_20d / entry_close - 1 END AS forward_return_20d,
                entry_is_tradable,
                valid_prices_1d,
                valid_prices_5d,
                valid_prices_20d
            FROM future
            WHERE date BETWEEN DATE '2020-01-01' AND DATE '2025-12-31'
            ORDER BY date, asset;

            CREATE INDEX IF NOT EXISTS idx_forward_return_key
            ON forward_returns(date, asset);
            """
        )
        summary = connection.execute(
            """
            SELECT count(*) AS rows,
                   count(*) FILTER (WHERE forward_return_1d IS NOT NULL) AS labels_1d,
                   count(*) FILTER (WHERE forward_return_5d IS NOT NULL) AS labels_5d,
                   count(*) FILTER (WHERE forward_return_20d IS NOT NULL) AS labels_20d,
                   min(date) AS first_formation_date,
                   max(date) AS last_formation_date
            FROM forward_returns
            """
        ).fetchdf()
        print(summary.to_string(index=False))
        print("口径：T日收盘后形成因子，标签从T+1收盘开始，不跨过ST、停牌或缺失行情。")
        print("[PASS] forward_returns 已建立。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
