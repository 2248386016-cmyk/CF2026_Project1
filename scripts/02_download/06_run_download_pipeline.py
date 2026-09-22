"""12 - 顺序运行参考数据、核心下载、验证与建库；可选约束数据需单独运行09。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_download_reference_data.py",
    "02_download_core_market_data.py",
    "04_validate_raw_downloads.py",
    "05_build_research_database.py",
]


def main() -> None:
    for step in STEPS:
        print(f"\n{'#' * 72}\n运行：{step}\n{'#' * 72}")
        result = subprocess.run([sys.executable, str(SCRIPT_DIR / step)], cwd=SCRIPT_DIR)
        if result.returncode != 0:
            print(f"流水线停止：{step} 退出码 {result.returncode}")
            raise SystemExit(result.returncode)
    print("\n[PASS] 核心数据下载、验证和建库流水线全部完成。")


if __name__ == "__main__":
    main()
