"""05 - 获取股票基础名单并构造与研究期有交集的候选股票池。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import ensure_output_dir, get_tushare_client, print_section


RESEARCH_START = pd.Timestamp("2020-01-01")
RESEARCH_END = pd.Timestamp("2025-12-31")


def main() -> None:
    print_section("05 股票基础名单测试")
    pro = get_tushare_client()
    output_dir = ensure_output_dir()

    frames = []
    errors = []

    for status in ["L", "D", "P"]:
        try:
            frame = pro.stock_basic(
                exchange="",
                list_status=status,
                fields=(
                    "ts_code,symbol,name,area,industry,market,exchange,"
                    "list_status,list_date,delist_date"
                ),
            )
            if not frame.empty:
                frame["requested_status"] = status
                frames.append(frame)
                print(f"状态 {status}：获取 {len(frame)} 行")
            else:
                print(f"状态 {status}：返回 0 行")
        except Exception as exc:  # 保留其他状态的数据，同时清楚报告权限问题
            errors.append((status, str(exc)))
            print(f"状态 {status}：调用失败 - {exc}")

    if not frames:
        raise AssertionError("所有 stock_basic 调用均未返回数据。")

    stocks = pd.concat(frames, ignore_index=True)
    stocks = stocks.drop_duplicates(subset=["ts_code"], keep="first")

    for column in ["list_date", "delist_date"]:
        stocks[column] = pd.to_datetime(
            stocks[column], format="%Y%m%d", errors="coerce"
        )

    stocks = stocks.sort_values(["list_date", "ts_code"]).reset_index(drop=True)

    overlaps_period = (
        stocks["list_date"].notna()
        & stocks["list_date"].le(RESEARCH_END)
        & (stocks["delist_date"].isna() | stocks["delist_date"].ge(RESEARCH_START))
    )
    research_stocks = stocks.loc[overlaps_period].copy()

    duplicate_codes = int(research_stocks["ts_code"].duplicated().sum())
    missing_list_dates = int(research_stocks["list_date"].isna().sum())
    if duplicate_codes:
        raise AssertionError(f"研究股票池存在 {duplicate_codes} 个重复代码。")
    if research_stocks.empty:
        raise AssertionError("与研究期有交集的股票池为空。")

    print(f"\n去重后股票总数：{len(stocks)}")
    print(f"与 2020-2025 研究期有交集的股票数：{len(research_stocks)}")
    print(f"重复股票代码数：{duplicate_codes}")
    print(f"缺失上市日期数：{missing_list_dates}")
    print("\n交易所分布：")
    print(research_stocks["exchange"].value_counts(dropna=False).to_string())
    print("\n市场类型分布：")
    print(research_stocks["market"].value_counts(dropna=False).to_string())

    all_file = output_dir / "05_stock_basic_all_status.csv"
    research_file = output_dir / "05_research_stock_candidates_2020_2025.csv"
    stocks.to_csv(all_file, index=False, encoding="utf-8-sig")
    research_stocks.to_csv(research_file, index=False, encoding="utf-8-sig")

    print(f"\n全部名单：{all_file}")
    print(f"研究期候选名单：{research_file}")
    if errors:
        print("\n以下状态调用失败，但其余结果已保存：")
        for status, message in errors:
            print(f"- {status}: {message}")
    print("[PASS] 股票基础名单与研究期候选池检查通过。")


if __name__ == "__main__":
    main()
