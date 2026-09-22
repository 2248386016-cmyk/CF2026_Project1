"""04 - 验证因子输出，并计算逻辑重复程度所需的相关性与高分组重合率。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATABASE_DIR,
    FACTOR_OUTPUT_DIR,
    ensure_data_dirs,
    print_section,
)


def main() -> None:
    print_section("04 验证和比较因子")
    ensure_data_dirs()
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "factor_config.yaml").read_text(encoding="utf-8")
    )
    minimum_assets = int(config["diagnostics"]["minimum_daily_assets"])
    high_quantile = float(config["diagnostics"]["high_group_quantile"])

    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        checks = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM (
                    SELECT date, asset, factor FROM factor_values_raw
                    GROUP BY date, asset, factor HAVING count(*) > 1
                )) AS duplicate_raw_keys,
                (SELECT count(*) FROM factor_values_raw
                 WHERE value IS NULL OR NOT isfinite(value)) AS invalid_raw_values,
                (SELECT count(*) FROM factor_values_processed_detail
                 WHERE zscore_value IS NULL OR NOT isfinite(zscore_value)) AS invalid_zscores,
                (SELECT count(*) FROM factor_values_processed_detail
                 WHERE rank_pct < 0 OR rank_pct > 1) AS invalid_ranks
            """
        ).fetchdf()

        coverage = connection.execute(
            """
            WITH theoretical AS (
                SELECT trade_date AS date, count(*) AS universe_assets
                FROM research_universe_daily
                WHERE is_in_universe
                  AND trade_date BETWEEN DATE '2020-01-01' AND DATE '2025-12-31'
                GROUP BY trade_date
            ), factor_daily AS (
                SELECT date, factor, count(*) AS valid_assets
                FROM factor_values_raw GROUP BY date, factor
            )
            SELECT f.factor,
                   min(f.date) AS first_date,
                   max(f.date) AS last_date,
                   count(*) AS dates,
                   min(f.valid_assets) AS min_daily_assets,
                   round(avg(f.valid_assets), 2) AS average_daily_assets,
                   round(100.0 * sum(f.valid_assets) / sum(t.universe_assets), 4)
                       AS average_coverage_pct
            FROM factor_daily f JOIN theoretical t USING (date)
            GROUP BY f.factor ORDER BY f.factor
            """
        ).fetchdf()

        descriptive = connection.execute(
            """
            SELECT factor, count(*) AS observations,
                   avg(raw_value) AS mean,
                   stddev_samp(raw_value) AS std,
                   min(raw_value) AS min,
                   quantile_cont(raw_value, 0.01) AS p01,
                   quantile_cont(raw_value, 0.50) AS median,
                   quantile_cont(raw_value, 0.99) AS p99,
                   max(raw_value) AS max
            FROM factor_values_processed_detail
            GROUP BY factor ORDER BY factor
            """
        ).fetchdf()

        pair_summary = connection.execute(
            f"""
            WITH daily_pairs AS (
                SELECT a.date,
                       a.factor AS factor_a,
                       b.factor AS factor_b,
                       corr(a.rank_pct, b.rank_pct) AS rank_correlation,
                       count(*) FILTER (
                           WHERE a.rank_pct >= {high_quantile}
                             AND b.rank_pct >= {high_quantile}
                       ) AS both_high,
                       count(*) FILTER (
                           WHERE a.rank_pct >= {high_quantile}
                              OR b.rank_pct >= {high_quantile}
                       ) AS either_high,
                       count(*) AS common_assets
                FROM factor_values_processed_detail a
                JOIN factor_values_processed_detail b
                  ON a.date = b.date AND a.asset = b.asset AND a.factor < b.factor
                GROUP BY a.date, a.factor, b.factor
                HAVING count(*) >= {minimum_assets}
            )
            SELECT factor_a, factor_b,
                   count(*) AS common_dates,
                   avg(common_assets) AS average_common_assets,
                   avg(rank_correlation) AS average_rank_correlation,
                   median(rank_correlation) AS median_rank_correlation,
                   avg(both_high * 1.0 / NULLIF(either_high, 0))
                       AS average_high_group_jaccard
            FROM daily_pairs
            GROUP BY factor_a, factor_b
            ORDER BY factor_a, factor_b
            """
        ).fetchdf()

        cards = yaml.safe_load(
            (PROJECT_ROOT / "config" / "factor_cards.yaml").read_text(encoding="utf-8")
        )["factors"]
        card_rows = [dict(factor=name, **values) for name, values in cards.items()]
        import pandas as pd

        cards_frame = pd.DataFrame(card_rows)
        if "fields" in cards_frame.columns:
            cards_frame["fields"] = cards_frame["fields"].apply(
                lambda value: ", ".join(value) if isinstance(value, list) else value
            )

        checks.to_csv(FACTOR_OUTPUT_DIR / "04_factor_checks.csv", index=False, encoding="utf-8-sig")
        coverage.to_csv(FACTOR_OUTPUT_DIR / "04_factor_coverage.csv", index=False, encoding="utf-8-sig")
        descriptive.to_csv(FACTOR_OUTPUT_DIR / "04_factor_descriptive_statistics.csv", index=False, encoding="utf-8-sig")
        pair_summary.to_csv(FACTOR_OUTPUT_DIR / "04_factor_pair_comparison.csv", index=False, encoding="utf-8-sig")
        cards_frame.to_csv(FACTOR_OUTPUT_DIR / "04_factor_cards.csv", index=False, encoding="utf-8-sig")

        print("关键检查：")
        print(checks.to_string(index=False))
        print("\n因子覆盖率：")
        print(coverage.to_string(index=False))
        print("\n因子对比：")
        print(pair_summary.to_string(index=False))

        failures = {
            column: int(checks.iloc[0][column])
            for column in checks.columns
            if int(checks.iloc[0][column]) != 0
        }
        if failures:
            raise AssertionError(f"因子输出未通过关键检查：{failures}")
        if (coverage["min_daily_assets"] < minimum_assets).any():
            bad = coverage.loc[coverage["min_daily_assets"] < minimum_assets, "factor"].tolist()
            raise AssertionError(f"以下因子的最小每日样本数不足：{bad}")
        print(f"\n报告目录：{FACTOR_OUTPUT_DIR}")
        print("[PASS] 因子唯一性、覆盖率、分布和逻辑重复度验证完成。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
