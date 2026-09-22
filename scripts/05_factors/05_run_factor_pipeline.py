"""05 - 依次构建、预处理并验证候选因子。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_build_factor_panel.py",
    "02_calculate_raw_factors.py",
    "03_preprocess_factors.py",
    "04_validate_and_compare_factors.py",
]


def main() -> None:
    for filename in STEPS:
        print("\n" + "#" * 72)
        print(f"运行：{filename}")
        print("#" * 72)
        subprocess.run([sys.executable, str(SCRIPT_DIR / filename)], check=True)
    print("\n[PASS] 因子构建、预处理和验证全部完成。")


if __name__ == "__main__":
    main()
