"""06 - 生成数据字典、原始快照校验清单、环境快照和清洗对账表。"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    DATA_AUDIT_OUTPUT_DIR,
    DATABASE_DIR,
    RAW_DIR,
    ensure_data_dirs,
    print_section,
)


DATA_DICTIONARY = [
    ("daily_raw", "ts_code", "Tushare股票代码", "无", "日频"),
    ("daily_raw", "trade_date", "交易日", "YYYY-MM-DD", "日频"),
    ("daily_raw", "open/high/low/close", "未复权OHLC价格", "元/股", "日频"),
    ("daily_raw", "pre_close", "昨日收盘价", "元/股", "日频"),
    ("daily_raw", "vol", "成交量（Tushare daily口径）", "手，1手=100股", "日频"),
    ("daily_raw", "amount", "成交额（Tushare daily口径）", "千元", "日频"),
    ("adj_factor", "adj_factor", "复权因子", "无", "日频"),
    ("daily_adjusted", "reference_factor", "固定参考日复权因子", "无", "日频"),
    ("daily_adjusted", "open_adj/high_adj/low_adj/close_adj", "固定参考日的后复权OHLC", "元/股等价口径", "日频"),
    ("stock_basic", "list_date/delist_date", "上市/退市日期", "YYYY-MM-DD", "事件"),
    ("stock_st_daily", "is_st", "历史名称区间生成的每日ST标记", "布尔", "日频"),
    ("suspend_daily", "suspend_type", "停复牌类型，S表示停牌", "类别", "日频"),
    ("stk_limit_daily", "up_limit/down_limit", "当日涨跌停价", "元/股", "日频"),
    ("research_universe_daily", "is_in_universe", "当日是否进入沪深主板研究池", "布尔", "日频"),
    ("factor_values_raw", "date+asset+factor", "因子长表唯一键", "无", "日频"),
    ("backtest_daily", "nav/daily_return", "扣费后净值和日收益", "货币/比率", "日频"),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def main() -> None:
    print_section("06 生成数据审计包")
    ensure_data_dirs()
    DATA_AUDIT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dictionary_path = DATA_AUDIT_OUTPUT_DIR / "06_data_dictionary.csv"
    with dictionary_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["table", "field", "meaning", "unit", "frequency"])
        writer.writerows(DATA_DICTIONARY)

    raw_files = sorted(
        path for path in RAW_DIR.rglob("*")
        if path.is_file() and "manifests" not in path.relative_to(RAW_DIR).parts
    )
    manifest_path = DATA_AUDIT_OUTPUT_DIR / "06_raw_snapshot_manifest_sha256.csv"
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["relative_path", "dataset", "size_bytes", "modified_time", "sha256"])
        for index, path in enumerate(raw_files, start=1):
            stat = path.stat()
            relative = path.relative_to(PROJECT_ROOT)
            dataset = path.relative_to(RAW_DIR).parts[0]
            writer.writerow([
                relative.as_posix(), dataset, stat.st_size,
                datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                sha256_file(path),
            ])
            if index % 1000 == 0:
                print(f"已校验 {index}/{len(raw_files)} 个原始文件")

    environment = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: package_version(name)
            for name in ["pandas", "duckdb", "pyarrow", "tushare", "PyYAML"]
        },
        "raw_file_count": len(raw_files),
        "manifest_sha256": sha256_file(manifest_path),
        "factor_config_sha256": sha256_file(PROJECT_ROOT / "config" / "factor_config.yaml"),
        "backtest_config_sha256": sha256_file(PROJECT_ROOT / "config" / "backtest_config.yaml"),
    }
    (DATA_AUDIT_OUTPUT_DIR / "06_environment_snapshot.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"), read_only=True)
    try:
        reconciliation = connection.execute(
            """
            WITH classified AS (
                SELECT CASE
                    WHEN NOT has_stock_metadata THEN '01_missing_stock_metadata'
                    WHEN NOT is_research_universe THEN '02_outside_research_universe'
                    WHEN NOT is_listed_on_date THEN '03_outside_listing_period'
                    WHEN has_invalid_raw_price THEN '04_invalid_raw_price'
                    WHEN has_invalid_adjusted_price THEN '05_invalid_adjusted_price'
                    WHEN has_invalid_adj_factor THEN '06_invalid_adj_factor'
                    WHEN has_invalid_volume THEN '07_invalid_volume'
                    WHEN has_invalid_amount THEN '08_invalid_amount'
                    WHEN is_st THEN '09_historical_st'
                    ELSE '10_retained_in_market_data_clean'
                END AS exclusive_result
                FROM market_data_enriched
            )
            SELECT exclusive_result, count(*) AS rows
            FROM classified GROUP BY exclusive_result ORDER BY exclusive_result
            """
        ).fetchdf()
        totals = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM market_data_enriched) AS input_rows,
                (SELECT count(*) FROM market_data_clean) AS clean_rows,
                (SELECT count(*) FROM research_universe_daily) AS universe_rows,
                (SELECT count(*) FROM factor_values_raw) AS raw_factor_rows
            """
        ).fetchdf()
    finally:
        connection.close()
    reconciliation.to_csv(
        DATA_AUDIT_OUTPUT_DIR / "06_cleaning_exclusive_reconciliation.csv",
        index=False, encoding="utf-8-sig"
    )
    totals.to_csv(
        DATA_AUDIT_OUTPUT_DIR / "06_pipeline_row_counts.csv",
        index=False, encoding="utf-8-sig"
    )
    if int(reconciliation["rows"].sum()) != int(totals.iloc[0]["input_rows"]):
        raise AssertionError("互斥清洗分类与输入行数无法对账。")
    retained = reconciliation.loc[
        reconciliation["exclusive_result"] == "10_retained_in_market_data_clean", "rows"
    ]
    if retained.empty or int(retained.iloc[0]) != int(totals.iloc[0]["clean_rows"]):
        raise AssertionError("保留行数与 market_data_clean 无法对账。")
    print(f"原始快照文件数：{len(raw_files)}")
    print(reconciliation.to_string(index=False))
    print(f"审计包目录：{DATA_AUDIT_OUTPUT_DIR}")
    print("[PASS] 数据字典、SHA-256快照、环境快照和清洗对账已生成。")


if __name__ == "__main__":
    main()
