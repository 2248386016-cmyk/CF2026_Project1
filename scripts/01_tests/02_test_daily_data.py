"""02 - 检查单只股票未复权日线行情的字段和基础质量。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    TEST_END_DATE,
    TEST_START_DATE,
    TEST_TS_CODE,
    ensure_output_dir,
    get_tushare_client,
    print_section,
)


def main() -> None:
    print_section("02 单股票日线质量测试")
    pro = get_tushare_client()
    output_dir = ensure_output_dir()

    data = pro.daily(
        ts_code=TEST_TS_CODE,
        start_date=TEST_START_DATE,
        end_date=TEST_END_DATE,
        fields=(
            "ts_code,trade_date,open,high,low,close,pre_close,"
            "change,pct_chg,vol,amount"
        ),
    )

    if data.empty:
        raise AssertionError("日线行情为空。")

    data["trade_date"] = pd.to_datetime(data["trade_date"], format="%Y%m%d")
    data = data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    report = {
        "rows": len(data),
        "duplicate_keys": int(data.duplicated(["trade_date", "ts_code"]).sum()),
        "missing_values": int(data.isna().sum().sum()),
        "nonpositive_prices": int(
            (data[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
        ),
        "negative_volume": int((data["vol"] < 0).sum()),
        "negative_amount": int((data["amount"] < 0).sum()),
        "invalid_high": int(
            (data["high"] < data[["open", "close", "low"]].max(axis=1)).sum()
        ),
        "invalid_low": int(
            (data["low"] > data[["open", "close", "high"]].min(axis=1)).sum()
        ),
    }

    print(f"股票代码：{TEST_TS_CODE}")
    print(f"日期范围：{data['trade_date'].min().date()} 至 {data['trade_date'].max().date()}")
    for key, value in report.items():
        print(f"{key}: {value}")

    critical = [
        "duplicate_keys", "nonpositive_prices", "negative_volume",
        "negative_amount", "invalid_high", "invalid_low",
    ]
    failures = {key: report[key] for key in critical if report[key] != 0}
    if failures:
        raise AssertionError(f"发现关键行情质量问题：{failures}")

    output_file = output_dir / "02_daily_000001_sz_2020.csv"
    data.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"输出文件：{output_file}")
    print("[PASS] 单股票日线行情基础质量检查通过。")


if __name__ == "__main__":
    main()
