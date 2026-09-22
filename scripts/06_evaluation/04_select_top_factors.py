"""04 - 仅用研究期和验证期指标，从不同逻辑家族选出3个因子。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, EVALUATION_OUTPUT_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("04 择优选取3个因子")
    ensure_data_dirs()
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "factor_config.yaml").read_text(encoding="utf-8")
    )
    horizon = int(config["evaluation"]["primary_selection_horizon"])
    threshold = float(config["diagnostics"]["high_correlation_threshold"])
    family_map = {item["name"]: item["family"] for item in config["factors"]}

    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        ic = connection.execute(
            "SELECT * FROM factor_ic_summary WHERE horizon = ?", [horizon]
        ).fetchdf()
        spread = connection.execute(
            "SELECT * FROM factor_spread_summary WHERE horizon = ?", [horizon]
        ).fetchdf()
        corr = connection.execute(
            """
            WITH pairs AS (
                SELECT a.date, a.factor AS factor_a, b.factor AS factor_b,
                       corr(a.rank_pct, b.rank_pct) AS rank_corr
                FROM factor_values_processed_detail a
                JOIN factor_values_processed_detail b
                  ON a.date=b.date AND a.asset=b.asset AND a.factor<b.factor
                WHERE a.date <= DATE '2024-12-31'
                GROUP BY a.date, a.factor, b.factor
                HAVING count(*) >= 30
            )
            SELECT factor_a, factor_b, avg(rank_corr) AS rank_correlation
            FROM pairs GROUP BY factor_a, factor_b
            """
        ).fetchdf()

        def pivot_metric(frame: pd.DataFrame, value: str, prefix: str) -> pd.DataFrame:
            result = frame.pivot(index="factor", columns="sample_period", values=value)
            return result.rename(columns={
                "train_2020_2023": f"train_{prefix}",
                "validation_2024": f"validation_{prefix}",
                "test_2025": f"test_{prefix}",
            })

        ranking = pivot_metric(ic, "mean_rank_ic", "rank_ic")
        ranking = ranking.join(pivot_metric(ic, "rank_ic_ir", "rank_ic_ir"))
        ranking = ranking.join(pivot_metric(spread, "mean_high_minus_low", "spread"))
        ranking = ranking.join(pivot_metric(spread, "average_group_monotonicity", "monotonicity"))
        ranking = ranking.reset_index()
        ranking["family"] = ranking["factor"].map(family_map)

        selection_metrics = [
            "train_rank_ic",
            "validation_rank_ic",
            "train_spread",
            "validation_spread",
        ]
        for column in selection_metrics:
            ranking[f"rank_{column}"] = ranking[column].rank(pct=True, method="average")
        ranking["base_score"] = ranking[[f"rank_{c}" for c in selection_metrics]].mean(axis=1)
        ranking["direction_consistent"] = (
            (ranking["train_rank_ic"] > 0)
            & (ranking["validation_rank_ic"] > 0)
            & (ranking["train_spread"] > 0)
            & (ranking["validation_spread"] > 0)
        )
        ranking["selection_score"] = ranking["base_score"] - (~ranking["direction_consistent"]).astype(float) * 0.50
        ranking = ranking.sort_values("selection_score", ascending=False).reset_index(drop=True)

        corr_lookup: dict[tuple[str, str], float] = {}
        for row in corr.itertuples(index=False):
            corr_lookup[tuple(sorted((row.factor_a, row.factor_b)))] = float(row.rank_correlation)

        selected: list[str] = []
        selected_families: set[str] = set()
        reasons: list[str] = []
        for row in ranking.itertuples(index=False):
            if row.family in selected_families:
                continue
            if any(abs(corr_lookup.get(tuple(sorted((row.factor, other))), 0.0)) >= threshold for other in selected):
                continue
            selected.append(row.factor)
            selected_families.add(row.family)
            reasons.append(
                "研究/验证Rank IC、五分组价差综合排名；"
                f"逻辑家族={row.family}"
            )
            if len(selected) == 3:
                break

        if len(selected) != 3:
            raise AssertionError(f"无法在家族和相关性约束下选出3个因子：{selected}")

        ranking["selected"] = ranking["factor"].isin(selected)
        ranking["selection_used_test_data"] = False
        selected_frame = pd.DataFrame({
            "selection_order": range(1, 4),
            "factor": selected,
            "family": [family_map[name] for name in selected],
            "reason": reasons,
        })

        connection.register("ranking_frame", ranking)
        connection.register("selected_frame", selected_frame)
        connection.execute("CREATE OR REPLACE TABLE factor_selection_ranking AS SELECT * FROM ranking_frame")
        connection.execute("CREATE OR REPLACE TABLE selected_factors AS SELECT * FROM selected_frame")
        connection.unregister("ranking_frame")
        connection.unregister("selected_frame")

        ranking.to_csv(EVALUATION_OUTPUT_DIR / "04_factor_selection_ranking.csv", index=False, encoding="utf-8-sig")
        selected_frame.to_csv(EVALUATION_OUTPUT_DIR / "04_selected_factors.csv", index=False, encoding="utf-8-sig")

        test_report = ranking.loc[ranking["selected"], [
            "factor", "family", "test_rank_ic", "test_rank_ic_ir", "test_spread", "test_monotonicity"
        ]].copy()
        test_report.to_csv(EVALUATION_OUTPUT_DIR / "04_selected_factors_test_2025.csv", index=False, encoding="utf-8-sig")

        print("候选因子排名（选择不使用2025数据）：")
        print(ranking[["factor", "family", "train_rank_ic", "validation_rank_ic",
                       "train_spread", "validation_spread", "direction_consistent",
                       "selection_score", "selected"]].to_string(index=False))
        print("\n最终选中：")
        print(selected_frame.to_string(index=False))
        print("\n2025样本外结果（未参与选择）：")
        print(test_report.to_string(index=False))
        print("[PASS] 已在不使用2025测试数据的前提下选出3个因子。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
