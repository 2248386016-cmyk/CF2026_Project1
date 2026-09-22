"""03 - 对每日每因子做1%/99%缩尾、Z-score和百分位排名。"""

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
    print_section("03 因子预处理")
    ensure_data_dirs()
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "factor_config.yaml").read_text(encoding="utf-8")
    )
    lower = float(config["preprocess"]["winsorize"]["lower_quantile"])
    upper = float(config["preprocess"]["winsorize"]["upper_quantile"])

    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE factor_values_processed_detail AS
            WITH bounds AS (
                SELECT date, factor,
                       quantile_cont(value, {lower}) AS lower_bound,
                       quantile_cont(value, {upper}) AS upper_bound
                FROM factor_values_raw
                GROUP BY date, factor
            ),
            winsorized AS (
                SELECT r.date, r.asset, r.factor, r.value AS raw_value,
                       greatest(b.lower_bound, least(r.value, b.upper_bound))
                           AS winsorized_value
                FROM factor_values_raw r
                JOIN bounds b USING (date, factor)
            ),
            standardized AS (
                SELECT *,
                       avg(winsorized_value) OVER (PARTITION BY date, factor) AS cross_mean,
                       stddev_samp(winsorized_value) OVER (PARTITION BY date, factor) AS cross_std,
                       percent_rank() OVER (
                           PARTITION BY date, factor ORDER BY winsorized_value
                       ) AS rank_pct,
                       count(*) OVER (PARTITION BY date, factor) AS cross_section_assets
                FROM winsorized
            )
            SELECT date, asset, factor, raw_value, winsorized_value,
                   CASE WHEN cross_std > 0
                        THEN (winsorized_value - cross_mean) / cross_std END AS zscore_value,
                   rank_pct,
                   cross_section_assets
            FROM standardized
            ORDER BY date, asset, factor;

            CREATE OR REPLACE VIEW factor_values AS
            SELECT date, asset, factor, zscore_value AS value
            FROM factor_values_processed_detail
            WHERE zscore_value IS NOT NULL;

            CREATE OR REPLACE VIEW factor_ranks AS
            SELECT date, asset, factor, rank_pct AS value
            FROM factor_values_processed_detail
            WHERE rank_pct IS NOT NULL;
            """
        )
        summary = connection.execute(
            """
            SELECT factor, count(*) AS observations,
                   round(avg(zscore_value), 6) AS average_zscore,
                   round(stddev_samp(zscore_value), 6) AS zscore_std,
                   min(rank_pct) AS min_rank, max(rank_pct) AS max_rank
            FROM factor_values_processed_detail
            GROUP BY factor ORDER BY factor
            """
        ).fetchdf()
        print(summary.to_string(index=False))
        print("[PASS] 原始值、缩尾值、Z-score和排名已保存。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
