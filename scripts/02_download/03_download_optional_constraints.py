"""09 - 可选下载 ST、停牌及涨跌停数据；相关接口可能要求更高积分。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from download_utils import append_jsonl, call_with_retry, parquet_is_valid, save_parquet_atomic
from project_config import (
    MANIFEST_DIR,
    REFERENCE_DIR,
    STOCK_ST_DIR,
    STK_LIMIT_DIR,
    SUSPEND_DIR,
    ensure_data_dirs,
    get_tushare_client,
    print_section,
)


DATASETS = {
    "stock_st": {
        "directory": STOCK_ST_DIR,
        "fields": "ts_code,name,trade_date,type,type_name",
        "empty_columns": ["ts_code", "name", "trade_date", "type", "type_name"],
    },
    "suspend": {
        "directory": SUSPEND_DIR,
        "fields": "ts_code,trade_date,suspend_timing,suspend_type",
        "empty_columns": ["ts_code", "trade_date", "suspend_timing", "suspend_type"],
    },
    "stk_limit": {
        "directory": STK_LIMIT_DIR,
        "fields": "trade_date,ts_code,pre_close,up_limit,down_limit,asset_type,exchange",
        "empty_columns": [
            "trade_date", "ts_code", "pre_close", "up_limit", "down_limit",
            "asset_type", "exchange",
        ],
    },
}


def load_open_dates() -> list[str]:
    path = REFERENCE_DIR / "trade_calendar.parquet"
    if not path.exists():
        raise FileNotFoundError("缺少交易日历，请先运行 07_download_reference_data.py。")
    calendar = pd.read_parquet(path)
    values = calendar.loc[calendar["is_open"].eq(1), "cal_date"].astype(str)
    return sorted(values.str.replace("-", "", regex=False).tolist())


def fetch(pro, dataset: str, trade_date: str, fields: str) -> pd.DataFrame:
    if dataset == "stock_st":
        return pro.stock_st(trade_date=trade_date, fields=fields)
    if dataset == "suspend":
        return pro.suspend_d(trade_date=trade_date, suspend_type="S", fields=fields)
    if dataset == "stk_limit":
        return pro.stk_limit(trade_date=trade_date, fields=fields)
    raise ValueError(dataset)


def main() -> None:
    print_section("09 下载可选交易约束数据")
    ensure_data_dirs()
    pro = get_tushare_client()
    dates = load_open_dates()
    event_log = MANIFEST_DIR / "09_optional_download_events.jsonl"

    print("接口可能因积分不足失败。已完成的数据会保留，再次运行可断点续传。")
    unavailable = set()
    failures = []

    for dataset, config in DATASETS.items():
        print(f"\n开始数据集：{dataset}")
        for index, trade_date in enumerate(dates, start=1):
            if dataset in unavailable:
                break
            destination = config["directory"] / f"{trade_date}.parquet"
            if parquet_is_valid(destination, trade_date):
                continue
            try:
                frame = call_with_retry(
                    f"{dataset} {trade_date}",
                    lambda dataset=dataset, trade_date=trade_date, fields=config["fields"]: fetch(
                        pro, dataset, trade_date, fields
                    ),
                )
                if frame.empty:
                    frame = pd.DataFrame(columns=config["empty_columns"])
                if "trade_date" in frame.columns and not frame.empty:
                    if frame.duplicated(["trade_date", "ts_code"]).any():
                        raise AssertionError(f"{dataset} {trade_date} 存在重复键。")
                save_parquet_atomic(frame, destination)
                append_jsonl(
                    event_log,
                    {
                        "dataset": dataset,
                        "trade_date": trade_date,
                        "status": "success",
                        "rows": len(frame),
                    },
                )
                print(f"[{index}/{len(dates)}] {dataset} {trade_date}: {len(frame)} 行")
            except Exception as exc:
                message = str(exc)
                append_jsonl(
                    event_log,
                    {
                        "dataset": dataset,
                        "trade_date": trade_date,
                        "status": "failed",
                        "error": message,
                    },
                )
                # 权限/积分问题通常会在第一个日期持续失败，不继续浪费请求。
                if any(word in message.lower() for word in ["权限", "积分", "permission", "privilege"]):
                    unavailable.add(dataset)
                    print(f"[SKIP] {dataset} 当前权限不可用：{message}", file=sys.stderr)
                    break
                failures.append((dataset, trade_date, message))
                print(f"[FAILED] {dataset} {trade_date}: {message}", file=sys.stderr)

    print("\n可选数据下载结果：")
    for dataset in DATASETS:
        status = "权限不足/不可用" if dataset in unavailable else "已完成或可续传"
        print(f"- {dataset}: {status}")
    if failures:
        print(f"其他失败记录：{len(failures)}；再次运行会补下载。")
        raise SystemExit(1)
    print("[PASS] 可用权限范围内的交易约束数据下载完成。")


if __name__ == "__main__":
    main()
