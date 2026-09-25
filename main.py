"""CF2026 Project 1 unified command-line entry point."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "validate": ["scripts/01_tests/07_run_all_tests.py"],
    "core": [
        "scripts/03_processing/05_run_processing_pipeline.py",
        "scripts/04_universe/03_run_universe_pipeline.py",
        "scripts/05_factors/05_run_factor_pipeline.py",
        "scripts/06_evaluation/06_run_evaluation_pipeline.py",
        "scripts/07_backtest/06_run_backtest_pipeline.py",
    ],
    "experiments": [
        "scripts/08_experiments/04_run_weekly_vs_monthly_experiment.py",
        "scripts/09_extensions/04_run_portfolio_risk_extension.py",
        "scripts/08_experiments/07_validate_ridge_lightgbm_baseline.py",
        "scripts/08_experiments/11_export_research_workbench_data.py",
    ],
    "report": ["scripts/11_report/02_build_latex_report.py"],
    "reproduce": ["scripts/10_reproducibility/04_run_final_reproduction_package.py"],
}


def run_steps(groups: list[str]) -> None:
    for group in groups:
        for relative in COMMANDS[group]:
            print(f"\n[CF2026] {group}: {relative}", flush=True)
            subprocess.run([sys.executable, str(ROOT / relative)], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="CF2026量化研究平台统一入口")
    parser.add_argument(
        "command",
        choices=["validate", "core", "experiments", "report", "reproduce", "all"],
        help="all从冻结数据快照重建核心研究、实验、报告和复现证据",
    )
    args = parser.parse_args()
    groups = (["validate", "core", "experiments", "report", "reproduce"]
              if args.command == "all" else [args.command])
    run_steps(groups)
    print("\n[PASS] requested workflow completed.")


if __name__ == "__main__":
    main()
