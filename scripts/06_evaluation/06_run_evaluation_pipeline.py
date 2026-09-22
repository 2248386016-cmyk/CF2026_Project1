"""06 - 运行未来收益、IC、五分组和因子择优全流程。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_build_forward_returns.py",
    "02_calculate_ic.py",
    "03_calculate_group_returns.py",
    "04_select_top_factors.py",
    "05_validate_evaluation.py",
]


def main() -> None:
    for filename in STEPS:
        print("\n" + "#" * 72)
        print(f"运行：{filename}")
        print("#" * 72)
        subprocess.run([sys.executable, str(SCRIPT_DIR / filename)], check=True)
    print("\n[PASS] 因子评价与择优全流程完成。")


if __name__ == "__main__":
    main()
