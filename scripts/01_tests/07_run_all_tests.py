"""06 - 按编号依次执行全部 Tushare 测试脚本。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent

TEST_SCRIPTS = [
    "01_test_token_connection.py",
    "02_test_daily_data.py",
    "03_test_adjustment_factor.py",
    "04_test_trade_calendar.py",
    "05_test_stock_universe.py",
    "06_test_namechange_access.py",
]


def main() -> None:
    failures = []

    for script_name in TEST_SCRIPTS:
        script_path = SCRIPT_DIR / script_name
        print(f"\n{'#' * 70}")
        print(f"开始运行：{script_name}")
        print(f"{'#' * 70}")

        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=SCRIPT_DIR,
            check=False,
        )

        if completed.returncode != 0:
            failures.append((script_name, completed.returncode))

    print(f"\n{'=' * 70}")
    if failures:
        print("部分测试未通过：")
        for script_name, return_code in failures:
            print(f"- {script_name}: 退出码 {return_code}")
        raise SystemExit(1)

    print("[PASS] 全部 Tushare 基础测试通过。")


if __name__ == "__main__":
    main()
