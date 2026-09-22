"""10 - 验证核心全市场原始文件是否完整并生成按日质量报告。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    ADJ_FACTOR_DIR,
    DAILY_DIR,
    MANIFEST_DIR,
    REFERENCE_DIR,
    ensure_data_dirs,
    print_section,
)


def open_dates() -> list[str]:
    calendar = pd.read_parquet(REFERENCE_DIR / "trade_calendar.parquet")
    values = calendar.loc[calendar["is_open"].eq(1), "cal_date"].astype(str)
    return sorted(values.str.replace("-", "", regex=False).tolist())


def main() -> None:
    print_section("10 验证核心原始下载")
    ensure_data_dirs()
    dates = open_dates()
    rows = []
    errors = []

    for index, trade_date in enumerate(dates, start=1):
        daily_path = DAILY_DIR / f"{trade_date}.parquet"
        adj_path = ADJ_FACTOR_DIR / f"{trade_date}.parquet"
        record = {"trade_date": trade_date}

        if not daily_path.exists() or not adj_path.exists():
            missing = []
            if not daily_path.exists():
                missing.append("daily")
            if not adj_path.exists():
                missing.append("adj_factor")
            message = f"缺少文件：{','.join(missing)}"
            record.update({"status": "failed", "error": message})
            rows.append(record)
            errors.append((trade_date, message))
            continue

        try:
            daily = pd.read_parquet(daily_path)
            adj = pd.read_parquet(adj_path)
            daily_duplicates = int(daily.duplicated(["trade_date", "ts_code"]).sum())
            adj_duplicates = int(adj.duplicated(["trade_date", "ts_code"]).sum())
            invalid_prices = int(
                (daily[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
            )
            invalid_volume = int((daily["vol"] < 0).sum())
            invalid_adj = int((adj["adj_factor"] <= 0).sum())

            coverage = daily[["trade_date", "ts_code"]].merge(
                adj[["trade_date", "ts_code"]],
                on=["trade_date", "ts_code"],
                how="left",
                indicator=True,
            )
            missing_adj_for_daily = int(coverage["_merge"].ne("both").sum())

            metrics = {
                "daily_rows": len(daily),
                "adj_rows": len(adj),
                "daily_duplicates": daily_duplicates,
                "adj_duplicates": adj_duplicates,
                "invalid_prices": invalid_prices,
                "negative_volume": invalid_volume,
                "invalid_adj_factor": invalid_adj,
                "missing_adj_for_daily": missing_adj_for_daily,
            }
            failed_metrics = {key: value for key, value in metrics.items() if key not in {"daily_rows", "adj_rows"} and value}
            status = "failed" if failed_metrics else "passed"
            record.update(metrics)
            record["status"] = status
            record["error"] = str(failed_metrics) if failed_metrics else ""
            if failed_metrics:
                errors.append((trade_date, str(failed_metrics)))
            rows.append(record)
            if index % 100 == 0 or index == len(dates):
                print(f"已检查 {index}/{len(dates)} 个交易日")
        except Exception as exc:
            record.update({"status": "failed", "error": str(exc)})
            rows.append(record)
            errors.append((trade_date, str(exc)))

    report = pd.DataFrame(rows)
    report_path = MANIFEST_DIR / "10_core_data_quality_report.csv"
    report.to_csv(report_path, index=False, encoding="utf-8-sig")

    print(f"质量报告：{report_path}")
    print(f"预期交易日：{len(dates)}")
    print(f"通过日期：{int(report['status'].eq('passed').sum())}")
    print(f"失败日期：{len(errors)}")
    if errors:
        for trade_date, message in errors[:30]:
            print(f"- {trade_date}: {message}")
        raise SystemExit(1)
    print("[PASS] 核心原始行情完整性和基础质量检查通过。")


if __name__ == "__main__":
    main()
