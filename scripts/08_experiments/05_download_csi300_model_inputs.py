"""Download small, cached Tushare inputs for the dynamic CSI 300 model baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import tushare as ts
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config/model_baseline.yaml"))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def request_with_retry(callable_, *, attempts: int = 5) -> pd.DataFrame:
    for attempt in range(attempts):
        try:
            return callable_()
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("请设置环境变量 TUSHARE_TOKEN；脚本不会把 Token 写入磁盘。")
    pro = ts.pro_api(token)
    cache = PROJECT_ROOT / "data/model_inputs" / config["run"]["run_id"]
    cache.mkdir(parents=True, exist_ok=True)

    membership_path = cache / "csi300_index_weight.parquet"
    if args.force or not membership_path.exists():
        frames: list[pd.DataFrame] = []
        months = pd.period_range(
            config["universe"]["history_start"], config["run"]["test_end"], freq="M"
        )
        for number, month in enumerate(months, 1):
            frame = request_with_retry(
                lambda m=month: pro.index_weight(
                    index_code=config["universe"]["index_code"],
                    start_date=m.start_time.strftime("%Y%m%d"),
                    end_date=m.end_time.strftime("%Y%m%d"),
                    fields="index_code,con_code,trade_date,weight",
                )
            )
            if not frame.empty:
                frames.append(frame)
            print(f"index_weight {number}/{len(months)} rows={len(frame)}")
            time.sleep(0.16)
        membership = pd.concat(frames, ignore_index=True).drop_duplicates(
            ["trade_date", "con_code"], keep="last"
        )
        membership["trade_date"] = pd.to_datetime(membership["trade_date"])
        membership.to_parquet(membership_path, index=False)
    else:
        membership = pd.read_parquet(membership_path)

    database = config["run"]["source_database"]
    connection = duckdb.connect(database, read_only=True)
    formation_dates = connection.execute(
        """
        WITH calendar AS (
            SELECT DISTINCT trade_date
            FROM daily_adjusted
            WHERE trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        )
        SELECT max(trade_date) AS formation_date
        FROM calendar
        GROUP BY year(trade_date), month(trade_date)
        ORDER BY formation_date
        """,
        [config["run"]["start_date"], config["run"]["test_end"]],
    ).fetchdf()["formation_date"]
    connection.close()

    daily_basic_path = cache / "daily_basic_month_end.parquet"
    if args.force or not daily_basic_path.exists():
        frames = []
        for number, value in enumerate(formation_dates, 1):
            trade_date = pd.Timestamp(value).strftime("%Y%m%d")
            frame = request_with_retry(
                lambda d=trade_date: pro.daily_basic(
                    trade_date=d,
                    fields=("ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,"
                            "pe_ttm,pb,total_mv,circ_mv"),
                )
            )
            frames.append(frame)
            print(f"daily_basic {number}/{len(formation_dates)} rows={len(frame)}")
            time.sleep(0.16)
        daily_basic = pd.concat(frames, ignore_index=True).drop_duplicates(
            ["trade_date", "ts_code"], keep="last"
        )
        daily_basic["trade_date"] = pd.to_datetime(daily_basic["trade_date"])
        daily_basic.to_parquet(daily_basic_path, index=False)

    financial_path = cache / "fina_indicator_history.parquet"
    if args.force or not financial_path.exists():
        assets = sorted(membership["con_code"].dropna().unique())
        frames = []
        for number, asset in enumerate(assets, 1):
            frame = request_with_retry(
                lambda a=asset: pro.fina_indicator(
                    ts_code=a,
                    start_date="20180101",
                    end_date=config["run"]["test_end"].replace("-", ""),
                    fields=("ts_code,ann_date,end_date,update_flag,roe,roa,"
                            "grossprofit_margin,debt_to_assets,q_sales_yoy,q_profit_yoy"),
                )
            )
            if not frame.empty:
                frames.append(frame)
            print(f"fina_indicator {number}/{len(assets)} rows={len(frame)}")
            time.sleep(0.16)
        financials = pd.concat(frames, ignore_index=True).drop_duplicates(
            ["ts_code", "ann_date", "end_date"], keep="last"
        )
        financials["ann_date"] = pd.to_datetime(financials["ann_date"])
        financials["end_date"] = pd.to_datetime(financials["end_date"])
        financials.to_parquet(financial_path, index=False)

    index_daily_path = cache / "csi300_index_daily.parquet"
    if args.force or not index_daily_path.exists():
        index_daily = request_with_retry(
            lambda: pro.index_daily(
                ts_code=config["universe"]["index_code"],
                start_date=config["run"]["start_date"].replace("-", ""),
                end_date="20260131",
                fields="ts_code,trade_date,close,pct_chg",
            )
        )
        index_daily["trade_date"] = pd.to_datetime(index_daily["trade_date"])
        index_daily.to_parquet(index_daily_path, index=False)

    manifest = []
    for path in [membership_path, daily_basic_path, financial_path, index_daily_path]:
        frame = pd.read_parquet(path)
        manifest.append(
            {"file": path.name, "rows": len(frame), "sha256": sha256(path)}
        )
    (cache / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
