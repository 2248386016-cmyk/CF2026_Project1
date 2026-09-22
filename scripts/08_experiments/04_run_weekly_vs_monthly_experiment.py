"""04 - 运行周频 vs 月频对照实验、比较与验证。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_run_weekly_vs_monthly.py",
    "02_compare_weekly_vs_monthly.py",
    "03_validate_weekly_vs_monthly.py",
]


def main() -> None:
    for filename in STEPS:
        print("\n" + "#" * 72)
        print(f"运行：{filename}")
        print("#" * 72)
        subprocess.run([sys.executable, str(SCRIPT_DIR / filename)], check=True)
    print("\n[PASS] 周频 vs 月频对照实验完成。")


if __name__ == "__main__":
    main()
