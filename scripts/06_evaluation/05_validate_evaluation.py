"""05 - 验证标签、IC、分组和最终选择输出。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, EVALUATION_OUTPUT_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("05 验证因子评价输出")
    ensure_data_dirs()
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        checks = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM (
                    SELECT date, asset FROM forward_returns
                    GROUP BY date, asset HAVING count(*) > 1
                )) AS duplicate_label_keys,
                (SELECT count(*) FROM (
                    SELECT date, factor, horizon FROM daily_factor_ic
                    GROUP BY date, factor, horizon HAVING count(*) > 1
                )) AS duplicate_ic_keys,
                (SELECT count(*) FROM (
                    SELECT date, factor, horizon, factor_group
                    FROM daily_factor_group_returns
                    GROUP BY date, factor, horizon, factor_group HAVING count(*) > 1
                )) AS duplicate_group_keys,
                (SELECT count(*) FROM selected_factors) AS selected_factor_count,
                (SELECT count(DISTINCT family) FROM selected_factors) AS selected_family_count,
                (SELECT count(*) FROM factor_selection_ranking
                 WHERE selection_used_test_data) AS selections_using_test_data,
                (SELECT count(*) FROM forward_returns
                 WHERE entry_date <= date) AS invalid_entry_dates,
                (SELECT count(*) FROM forward_returns
                 WHERE forward_return_1d IS NOT NULL AND exit_date_1d <= entry_date) AS invalid_exit_dates
            """
        ).fetchdf()
        checks.to_csv(EVALUATION_OUTPUT_DIR / "05_evaluation_checks.csv", index=False, encoding="utf-8-sig")
        print(checks.to_string(index=False))

        zero_required = [
            "duplicate_label_keys", "duplicate_ic_keys", "duplicate_group_keys",
            "selections_using_test_data", "invalid_entry_dates", "invalid_exit_dates",
        ]
        failures = {c: int(checks.iloc[0][c]) for c in zero_required if int(checks.iloc[0][c]) != 0}
        if int(checks.iloc[0]["selected_factor_count"]) != 3:
            failures["selected_factor_count"] = int(checks.iloc[0]["selected_factor_count"])
        if int(checks.iloc[0]["selected_family_count"]) != 3:
            failures["selected_family_count"] = int(checks.iloc[0]["selected_family_count"])
        if failures:
            raise AssertionError(f"因子评价输出未通过检查：{failures}")
        print(f"报告目录：{EVALUATION_OUTPUT_DIR}")
        print("[PASS] 标签、IC、分组与选择输出全部通过验证。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
