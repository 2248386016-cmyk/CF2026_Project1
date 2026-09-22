"""03 - 依次构建并验证沪深主板动态资产池。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_build_dynamic_universe.py",
    "02_validate_universe_coverage.py",
]


def main() -> None:
    for filename in STEPS:
        script = SCRIPT_DIR / filename
        print("\n" + "#" * 72)
        print(f"运行：{filename}")
        print("#" * 72)
        subprocess.run([sys.executable, str(script)], check=True)
    print("\n[PASS] 动态资产池构建与覆盖率验证全部完成。")


if __name__ == "__main__":
    main()
