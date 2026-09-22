"""07 - 下载扩展区间交易日历和所有上市状态的股票基础信息。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from download_utils import call_with_retry, save_parquet_atomic, sha256_file
from project_config import (
    DOWNLOAD_END_DATE,
    DOWNLOAD_START_DATE,
    REFERENCE_DIR,
    ensure_data_dirs,
    get_tushare_client,
    print_section,
)


def main() -> None:
    print_section("07 下载参考数据")
    ensure_data_dirs()
    pro = get_tushare_client()

    calendar = call_with_retry(
        "下载交易日历",
        lambda: pro.trade_cal(
            exchange="SSE",
            start_date=DOWNLOAD_START_DATE,
            end_date=DOWNLOAD_END_DATE,
            fields="exchange,cal_date,is_open,pretrade_date",
        ),
    )
    if calendar.empty:
        raise AssertionError("交易日历为空。")
    calendar = calendar.sort_values("cal_date").reset_index(drop=True)

    stock_frames = []
    for status in ["L", "D", "P"]:
        frame = call_with_retry(
            f"下载 stock_basic 状态 {status}",
            lambda status=status: pro.stock_basic(
                exchange="",
                list_status=status,
                fields=(
                    "ts_code,symbol,name,area,industry,market,exchange,"
                    "list_status,list_date,delist_date"
                ),
            ),
        )
        if not frame.empty:
            frame["requested_status"] = status
            stock_frames.append(frame)
        print(f"stock_basic 状态 {status}: {len(frame)} 行")

    if not stock_frames:
        raise AssertionError("股票基础信息为空。")
    stocks = pd.concat(stock_frames, ignore_index=True)
    stocks = stocks.drop_duplicates("ts_code").sort_values("ts_code").reset_index(drop=True)

    calendar_path = REFERENCE_DIR / "trade_calendar.parquet"
    stocks_path = REFERENCE_DIR / "stock_basic.parquet"
    save_parquet_atomic(calendar, calendar_path)
    save_parquet_atomic(stocks, stocks_path)

    open_days = int(calendar["is_open"].eq(1).sum())
    print(f"交易日历：{len(calendar)} 个自然日，{open_days} 个交易日")
    print(f"股票基础信息：{len(stocks)} 只")
    print(f"交易日历 SHA-256：{sha256_file(calendar_path)}")
    print(f"股票名单 SHA-256：{sha256_file(stocks_path)}")
    print("[PASS] 参考数据下载完成。")


if __name__ == "__main__":
    main()
