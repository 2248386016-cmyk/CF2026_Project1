"""06 - 运行策略信号、交易模拟、绩效分析、验证和稳定性评估。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STEPS = [
    "01_build_strategy_signals.py",
    "02_run_portfolio_backtest.py",
    "03_analyze_backtest.py",
    "04_validate_backtest.py",
    "05_assess_strategy_stability.py",
]


def main() -> None:
    for filename in STEPS:
        print("\n" + "#" * 72)
        print(f"运行：{filename}")
        print("#" * 72)
        subprocess.run([sys.executable, str(SCRIPT_DIR / filename)], check=True)
    print("\n[PASS] 单因子和多因子正式回测全部完成。")


if __name__ == "__main__":
    main()
