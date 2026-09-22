"""08 - 按交易日下载全市场 daily 和 adj_factor，支持断点续传。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from download_utils import (
    append_jsonl,
    call_with_retry,
    parquet_is_valid,
    save_parquet_atomic,
    sha256_file,
)
from project_config import (
    ADJ_FACTOR_DIR,
    DAILY_DIR,
    MANIFEST_DIR,
    REFERENCE_DIR,
    ensure_data_dirs,
    get_tushare_client,
    print_section,
)


DAILY_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,"
    "change,pct_chg,vol,amount"
)
ADJ_FIELDS = "ts_code,trade_date,adj_factor"


def load_open_dates() -> list[str]:
    path = REFERENCE_DIR / "trade_calendar.parquet"
    if not path.exists():
        raise FileNotFoundError("缺少交易日历，请先运行 07_download_reference_data.py。")
    calendar = pd.read_parquet(path)
    dates = calendar.loc[calendar["is_open"].eq(1), "cal_date"].astype(str)
    return sorted(dates.str.replace("-", "", regex=False).tolist())


def main() -> None:
    print_section("08 下载核心全市场行情")
    ensure_data_dirs()
    pro = get_tushare_client()
    trade_dates = load_open_dates()
    event_log = MANIFEST_DIR / "08_core_download_events.jsonl"

    print(f"待覆盖交易日：{len(trade_dates)}")
    print("可以随时停止；再次运行会跳过已验证的文件。")

    failures = []
    for index, trade_date in enumerate(trade_dates, start=1):
        daily_path = DAILY_DIR / f"{trade_date}.parquet"
        adj_path = ADJ_FACTOR_DIR / f"{trade_date}.parquet"
        daily_ok = parquet_is_valid(daily_path, trade_date)
        adj_ok = parquet_is_valid(adj_path, trade_date)

        if daily_ok and adj_ok:
            print(f"[{index}/{len(trade_dates)}] {trade_date} 已存在，跳过。")
            continue

        try:
            if not daily_ok:
                daily = call_with_retry(
                    f"daily {trade_date}",
                    lambda: pro.daily(trade_date=trade_date, fields=DAILY_FIELDS),
                )
                if daily.empty:
                    raise AssertionError(f"{trade_date} 是交易日，但 daily 返回空数据。")
                if len(daily) >= 6000:
                    raise AssertionError(
                        f"{trade_date} daily 返回 {len(daily)} 行，可能触及6000行上限。"
                    )
                if daily.duplicated(["trade_date", "ts_code"]).any():
                    raise AssertionError(f"{trade_date} daily 存在重复键。")
                save_parquet_atomic(daily, daily_path)
            else:
                daily = pd.read_parquet(daily_path)

            if not adj_ok:
                adj = call_with_retry(
                    f"adj_factor {trade_date}",
                    lambda: pro.adj_factor(trade_date=trade_date, fields=ADJ_FIELDS),
                )
                if adj.empty:
                    raise AssertionError(f"{trade_date} 是交易日，但 adj_factor 返回空数据。")
                if adj.duplicated(["trade_date", "ts_code"]).any():
                    raise AssertionError(f"{trade_date} adj_factor 存在重复键。")
                save_parquet_atomic(adj, adj_path)
            else:
                adj = pd.read_parquet(adj_path)

            append_jsonl(
                event_log,
                {
                    "trade_date": trade_date,
                    "status": "success",
                    "daily_rows": len(daily),
                    "adj_factor_rows": len(adj),
                    "daily_sha256": sha256_file(daily_path),
                    "adj_factor_sha256": sha256_file(adj_path),
                },
            )
            print(
                f"[{index}/{len(trade_dates)}] {trade_date} 完成："
                f"daily={len(daily)}, adj_factor={len(adj)}"
            )
        except Exception as exc:
            failures.append((trade_date, str(exc)))
            append_jsonl(
                event_log,
                {"trade_date": trade_date, "status": "failed", "error": str(exc)},
            )
            print(f"[FAILED] {trade_date}: {exc}", file=sys.stderr)

    print(f"\n结束时间：{datetime.now().isoformat(timespec='seconds')}")
    if failures:
        print(f"失败日期数量：{len(failures)}。再次运行脚本会自动补下载。")
        for trade_date, message in failures[:20]:
            print(f"- {trade_date}: {message}")
        raise SystemExit(1)

    print("[PASS] 所有交易日的 daily 和 adj_factor 下载完成。")


if __name__ == "__main__":
    main()
