"""05 - 顺序运行约束入库、历史 ST 构造、清洗和验证。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_import_optional_data.py",
    "02_build_historical_st_status.py",
    "03_clean_market_data.py",
    "04_validate_clean_data.py",
    "06_generate_data_audit_package.py",
]


def main() -> None:
    for step in STEPS:
        print(f"\n{'#' * 72}\n运行：{step}\n{'#' * 72}")
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / step)],
            cwd=SCRIPT_DIR,
            check=False,
        )
        if result.returncode != 0:
            print(f"处理流水线停止：{step} 退出码 {result.returncode}")
            raise SystemExit(result.returncode)
    print("\n[PASS] 可选数据入库、数据清洗与验证全部完成。")


if __name__ == "__main__":
    main()
