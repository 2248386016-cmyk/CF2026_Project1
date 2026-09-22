"""04 - 获取并验证 2020-2025 年 A 股交易日历。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    PROJECT_END_DATE,
    PROJECT_START_DATE,
    ensure_output_dir,
    get_tushare_client,
    print_section,
)


def main() -> None:
    print_section("04 交易日历测试")
    pro = get_tushare_client()
    output_dir = ensure_output_dir()

    calendar = pro.trade_cal(
        exchange="SSE",
        start_date=PROJECT_START_DATE,
        end_date=PROJECT_END_DATE,
        fields="exchange,cal_date,is_open,pretrade_date",
    )
    if calendar.empty:
        raise AssertionError("交易日历为空。")

    calendar["cal_date"] = pd.to_datetime(calendar["cal_date"], format="%Y%m%d")
    calendar = calendar.sort_values("cal_date").reset_index(drop=True)
    open_days = calendar.loc[calendar["is_open"].eq(1)].copy()

    annual_counts = open_days.groupby(open_days["cal_date"].dt.year).size()
    expected_years = set(range(2020, 2026))
    actual_years = set(annual_counts.index.tolist())
    if actual_years != expected_years:
        raise AssertionError(
            f"交易日历年份不完整，期望 {sorted(expected_years)}，实际 {sorted(actual_years)}"
        )

    unreasonable = annual_counts[(annual_counts < 220) | (annual_counts > 260)]
    if not unreasonable.empty:
        raise AssertionError(f"部分年度交易日数量异常：\n{unreasonable}")

    print(f"日历总行数：{len(calendar)}")
    print(f"有效交易日数：{len(open_days)}")
    print(f"第一个交易日：{open_days['cal_date'].min().date()}")
    print(f"最后一个交易日：{open_days['cal_date'].max().date()}")
    print("\n每年交易日数量：")
    print(annual_counts.to_string())

    output_file = output_dir / "04_trade_calendar_2020_2025.csv"
    calendar.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"输出文件：{output_file}")
    print("[PASS] 2020-2025 年交易日历检查通过。")


if __name__ == "__main__":
    main()
