"""07 - 批量下载与研究期有交集的沪深主板股票历史名称。"""

from __future__ import annotations

import sys
import time
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
    MANIFEST_DIR,
    NAMECHANGE_DIR,
    REFERENCE_DIR,
    ensure_data_dirs,
    get_tushare_client,
    print_section,
)


RESEARCH_START = pd.Timestamp("2020-01-01")
RESEARCH_END = pd.Timestamp("2025-12-31")
FIELDS = "ts_code,name,start_date,end_date,ann_date,change_reason"
EMPTY_COLUMNS = [
    "ts_code",
    "name",
    "start_date",
    "end_date",
    "ann_date",
    "change_reason",
]

# Tushare 各接口的限频可能不同。加上公共函数中的等待后，
# 使 namechange 请求间隔不低于约 0.35 秒。
EXTRA_INTERVAL_SECONDS = 0.20


def filename_for_code(ts_code: str) -> str:
    """把 000001.SZ 转换成适合作为文件名的 000001_SZ.parquet。"""
    return f"{ts_code.replace('.', '_')}.parquet"


def load_mainboard_codes() -> list[str]:
    """读取与正式研究期有交集的上交所、深交所主板股票。"""
    stock_path = REFERENCE_DIR / "stock_basic.parquet"
    if not stock_path.exists():
        raise FileNotFoundError(
            f"缺少股票基础信息：{stock_path}。"
            "请先运行 scripts/02_download/01_download_reference_data.py。"
        )

    stocks = pd.read_parquet(stock_path, engine="pyarrow")
    required = {
        "ts_code",
        "exchange",
        "market",
        "list_date",
        "delist_date",
    }
    missing = required - set(stocks.columns)
    if missing:
        raise AssertionError(f"stock_basic 缺少字段：{sorted(missing)}")

    stocks["list_date_parsed"] = pd.to_datetime(
        stocks["list_date"], format="%Y%m%d", errors="coerce"
    )
    stocks["delist_date_parsed"] = pd.to_datetime(
        stocks["delist_date"], format="%Y%m%d", errors="coerce"
    )

    is_mainboard = (
        stocks["exchange"].isin(["SSE", "SZSE"])
        & stocks["market"].eq("主板")
    )
    overlaps_research_period = (
        stocks["list_date_parsed"].notna()
        & stocks["list_date_parsed"].le(RESEARCH_END)
        & (
            stocks["delist_date_parsed"].isna()
            | stocks["delist_date_parsed"].ge(RESEARCH_START)
        )
    )

    codes = (
        stocks.loc[is_mainboard & overlaps_research_period, "ts_code"]
        .dropna()
        .astype(str)
        .str.strip()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    if not codes:
        raise AssertionError("沪深主板候选股票代码为空。")
    return codes


def normalize_result(data: pd.DataFrame, requested_code: str) -> pd.DataFrame:
    """统一字段并验证接口没有返回其他股票的数据。"""
    if data.empty:
        return pd.DataFrame(columns=EMPTY_COLUMNS)

    missing = set(EMPTY_COLUMNS) - set(data.columns)
    if missing:
        raise AssertionError(f"{requested_code} 返回结果缺少字段：{sorted(missing)}")

    data = data[EMPTY_COLUMNS].copy()
    data["ts_code"] = data["ts_code"].astype(str).str.strip()
    unexpected = sorted(set(data["ts_code"]) - {requested_code})
    if unexpected:
        raise AssertionError(
            f"请求 {requested_code}，但接口返回其他代码：{unexpected[:10]}"
        )

    for column in ["start_date", "end_date", "ann_date"]:
        # 原始层仍保存 YYYYMMDD 字符串；这里只清除显式的 nan/None 文本。
        data[column] = data[column].where(data[column].notna(), None)

    data = data.drop_duplicates(
        subset=["ts_code", "name", "start_date", "end_date"],
        keep="last",
    )
    return data.sort_values(["ts_code", "start_date"], na_position="last").reset_index(drop=True)


def main() -> None:
    print_section("07 批量下载沪深主板历史名称")
    ensure_data_dirs()
    pro = get_tushare_client()
    codes = load_mainboard_codes()
    event_log = MANIFEST_DIR / "07_namechange_download_events.jsonl"
    summary_path = MANIFEST_DIR / "07_namechange_download_summary.csv"

    print(f"候选股票数：{len(codes)}")
    print("下载支持断点续传；已经通过回读检查的文件会自动跳过。")

    summary_rows: list[dict] = []
    failures: list[tuple[str, str]] = []

    for index, ts_code in enumerate(codes, start=1):
        destination = NAMECHANGE_DIR / filename_for_code(ts_code)

        if parquet_is_valid(destination):
            existing = pd.read_parquet(destination, engine="pyarrow")
            summary_rows.append(
                {
                    "ts_code": ts_code,
                    "status": "existing",
                    "rows": len(existing),
                    "file": destination.name,
                    "error": "",
                }
            )
            if index % 100 == 0 or index == len(codes):
                print(f"[{index}/{len(codes)}] 已完成文件检查")
            continue

        try:
            data = call_with_retry(
                f"namechange {ts_code}",
                lambda ts_code=ts_code: pro.namechange(
                    ts_code=ts_code,
                    fields=FIELDS,
                ),
            )
            time.sleep(EXTRA_INTERVAL_SECONDS)
            data = normalize_result(data, ts_code)
            save_parquet_atomic(data, destination)

            status = "empty" if data.empty else "success"
            record = {
                "ts_code": ts_code,
                "status": status,
                "rows": len(data),
                "file": destination.name,
                "sha256": sha256_file(destination),
                "error": "",
            }
            summary_rows.append(record)
            append_jsonl(event_log, record)

            if index % 25 == 0 or index == len(codes):
                print(
                    f"[{index}/{len(codes)}] {ts_code} 完成，"
                    f"本股票历史名称记录数：{len(data)}"
                )
        except Exception as exc:
            message = str(exc)
            failures.append((ts_code, message))
            record = {
                "ts_code": ts_code,
                "status": "failed",
                "rows": None,
                "file": destination.name,
                "error": message,
            }
            summary_rows.append(record)
            append_jsonl(event_log, record)
            print(f"[FAILED] {ts_code}: {message}", file=sys.stderr)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    success_count = int(summary["status"].isin(["success", "existing"]).sum())
    empty_count = int(summary["status"].eq("empty").sum())
    failed_count = int(summary["status"].eq("failed").sum())

    print(f"\n结束时间：{datetime.now().isoformat(timespec='seconds')}")
    print(f"候选股票：{len(codes)}")
    print(f"有历史名称或已存在：{success_count}")
    print(f"接口返回空结果：{empty_count}")
    print(f"失败股票：{failed_count}")
    print(f"汇总文件：{summary_path}")

    if failures:
        print("以下为前20个失败记录；重新运行会只补失败文件：")
        for ts_code, message in failures[:20]:
            print(f"- {ts_code}: {message}")
        raise SystemExit(1)

    print("[PASS] 沪深主板股票历史名称批量下载完成。")


if __name__ == "__main__":
    main()
