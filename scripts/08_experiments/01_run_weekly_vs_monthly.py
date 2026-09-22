"""01 - 使用相同数据、样本、因子、持仓与成本口径运行周频/月频对照。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import BACKTEST_OUTPUT_DIR, DATABASE_DIR, ensure_data_dirs, print_section

BACKTEST_DIR = PROJECT_ROOT / "scripts" / "07_backtest"
TABLES = [
    "strategy_rebalance_schedule", "strategy_targets", "backtest_daily",
    "backtest_trades", "backtest_positions", "backtest_metrics",
    "backtest_drawdowns", "backtest_yearly_returns", "backtest_period_metrics",
]


def run_script(filename: str) -> None:
    subprocess.run([sys.executable, str(BACKTEST_DIR / filename)], check=True)


def copy_tables(prefix: str) -> None:
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        for table in TABLES:
            connection.execute(
                f"CREATE OR REPLACE TABLE experiment_{prefix}_{table} AS SELECT * FROM {table}"
            )
    finally:
        connection.close()


def restore_weekly_tables() -> None:
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        for table in TABLES:
            connection.execute(
                f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM experiment_weekly_{table}"
            )
    finally:
        connection.close()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    print_section("01 运行周频 vs 月频对照实验")
    ensure_data_dirs()
    output_dir = BACKTEST_OUTPUT_DIR / "weekly_vs_monthly"
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = PROJECT_ROOT / "config" / "backtest_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["portfolio"]["rebalance_frequency"] != "weekly":
        raise AssertionError("基准 backtest_config.yaml 必须保持 weekly，实验脚本在数据库内单独构造月频调仓。")

    started_at = datetime.now()
    started_clock = time.perf_counter()

    # 重新运行周频基准，然后冻结数据库表。
    for filename in [
        "01_build_strategy_signals.py", "02_run_portfolio_backtest.py",
        "03_analyze_backtest.py", "04_validate_backtest.py",
    ]:
        run_script(filename)
    copy_tables("weekly")

    # 只将调仓时点改为每月第一个交易日，其他口径不变。
    top_n = int(config["portfolio"]["top_n"])
    start_date = config["research"]["start_date"]
    end_date = config["research"]["end_date"]
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE strategy_rebalance_schedule AS
            WITH dates AS (
                SELECT DISTINCT date FROM factor_panel
                WHERE date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
            ), ordered AS (
                SELECT date, lag(date) OVER (ORDER BY date) AS formation_date,
                       year(date) * 100 + month(date) AS period_id,
                       row_number() OVER (
                           PARTITION BY year(date), month(date) ORDER BY date
                       ) AS day_in_period
                FROM dates
            )
            SELECT date AS rebalance_date, formation_date, period_id
            FROM ordered
            WHERE day_in_period=1 AND formation_date IS NOT NULL
            ORDER BY rebalance_date;

            CREATE OR REPLACE TABLE strategy_targets AS
            WITH ranked AS (
                SELECT r.rebalance_date, r.formation_date,
                       s.strategy, s.asset, s.score,
                       row_number() OVER (
                           PARTITION BY r.rebalance_date, s.strategy
                           ORDER BY s.score DESC, s.asset
                       ) AS target_rank
                FROM strategy_rebalance_schedule r
                JOIN strategy_signal_scores s ON r.formation_date=s.date
            )
            SELECT rebalance_date, formation_date, strategy, asset, score,
                   target_rank, 1.0/{top_n} AS target_weight
            FROM ranked WHERE target_rank <= {top_n}
            ORDER BY rebalance_date, strategy, target_rank;
            """
        )
    finally:
        connection.close()

    run_script("02_run_portfolio_backtest.py")
    run_script("03_analyze_backtest.py")
    copy_tables("monthly")

    # 恢复周频主表和标准输出，对照表保留在 experiment_* 中。
    restore_weekly_tables()
    run_script("03_analyze_backtest.py")
    run_script("04_validate_backtest.py")
    run_script("05_assess_strategy_stability.py")

    code_manifest = []
    for path in sorted(list((PROJECT_ROOT / "scripts").rglob("*.py")) + list((PROJECT_ROOT / "config").rglob("*.yaml"))):
        code_manifest.append({
            "relative_path": path.relative_to(PROJECT_ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    import pandas as pd
    pd.DataFrame(code_manifest).to_csv(
        output_dir / "01_code_and_config_sha256.csv", index=False, encoding="utf-8-sig"
    )

    finished_at = datetime.now()
    runtime = {
        "experiment": "weekly_vs_monthly",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "runtime_seconds": round(time.perf_counter() - started_clock, 3),
        "python_executable": sys.executable,
        "database": str(DATABASE_DIR / "cf2026_project1.duckdb"),
        "backtest_config": str(config_path),
        "backtest_config_sha256": sha256(config_path),
        "experiment_config_sha256": sha256(PROJECT_ROOT / "config" / "experiments" / "weekly_vs_monthly.yaml"),
        "data_snapshot_environment": str(PROJECT_ROOT / "outputs" / "data_audit" / "06_environment_snapshot.json"),
        "weekly_tables_restored_after_experiment": True,
    }
    (output_dir / "01_runtime_and_reproduction.json").write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"实验运行时间：{runtime['runtime_seconds']} 秒")
    print("[PASS] 周频和月频结果已分别冻结，周频主表已恢复。")


if __name__ == "__main__":
    main()
