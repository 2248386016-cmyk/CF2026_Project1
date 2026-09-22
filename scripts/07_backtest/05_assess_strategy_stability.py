"""05 - 生成年度、分期和滚动窗口稳定性报告。"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import BACKTEST_OUTPUT_DIR, DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("05 评估策略稳定性")
    ensure_data_dirs()
    config = yaml.safe_load((PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8"))
    annual_days = int(config["performance"]["annual_trading_days"])
    windows = [int(value) for value in config["performance"]["rolling_windows"]]
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        daily = connection.execute(
            "SELECT * FROM backtest_daily WHERE strategy='multi_equal_3' ORDER BY date"
        ).fetchdf()
        yearly = connection.execute(
            "SELECT * FROM backtest_yearly_returns WHERE strategy='multi_equal_3' ORDER BY year"
        ).fetchdf()
        periods = connection.execute(
            "SELECT * FROM backtest_period_metrics WHERE strategy='multi_equal_3' ORDER BY sample_period"
        ).fetchdf()
        rolling_frames: list[pd.DataFrame] = []
        returns = daily["daily_return"].astype(float)
        for window in windows:
            rolling_return = (1.0 + returns).rolling(window).apply(np.prod, raw=True) - 1.0
            rolling_vol = returns.rolling(window).std(ddof=1) * np.sqrt(annual_days)
            rolling_sharpe = (
                returns.rolling(window).mean()
                / returns.rolling(window).std(ddof=1)
                * np.sqrt(annual_days)
            )
            rolling_frames.append(pd.DataFrame({
                "date": daily["date"], "window_days": window,
                "rolling_return": rolling_return,
                "rolling_annualized_volatility": rolling_vol,
                "rolling_sharpe": rolling_sharpe,
            }).dropna())
        rolling = pd.concat(rolling_frames, ignore_index=True)
        stability_rows: list[dict] = []
        for window, frame in rolling.groupby("window_days"):
            stability_rows.append({
                "window_days": int(window), "observations": len(frame),
                "positive_return_ratio": (frame["rolling_return"] > 0).mean(),
                "positive_sharpe_ratio": (frame["rolling_sharpe"] > 0).mean(),
                "median_rolling_return": frame["rolling_return"].median(),
                "worst_rolling_return": frame["rolling_return"].min(),
                "best_rolling_return": frame["rolling_return"].max(),
                "median_rolling_sharpe": frame["rolling_sharpe"].median(),
                "worst_rolling_sharpe": frame["rolling_sharpe"].min(),
            })
        stability = pd.DataFrame(stability_rows)
        annual_summary = pd.DataFrame([{
            "positive_years": int((yearly["return"] > 0).sum()),
            "total_years": len(yearly),
            "positive_year_ratio": float((yearly["return"] > 0).mean()),
            "average_year_return": float(yearly["return"].mean()),
            "year_return_std": float(yearly["return"].std(ddof=1)),
            "worst_year": int(yearly.loc[yearly["return"].idxmin(), "year"]),
            "worst_year_return": float(yearly["return"].min()),
            "best_year": int(yearly.loc[yearly["return"].idxmax(), "year"]),
            "best_year_return": float(yearly["return"].max()),
        }])
        rolling.to_csv(BACKTEST_OUTPUT_DIR / "05_multi_factor_rolling_metrics.csv", index=False, encoding="utf-8-sig")
        stability.to_csv(BACKTEST_OUTPUT_DIR / "05_multi_factor_stability_summary.csv", index=False, encoding="utf-8-sig")
        annual_summary.to_csv(BACKTEST_OUTPUT_DIR / "05_multi_factor_annual_stability.csv", index=False, encoding="utf-8-sig")
        print("年度收益：")
        print(yearly.to_string(index=False))
        print("\n研究/验证/测试分期：")
        print(periods.to_string(index=False))
        print("\n滚动稳定性：")
        print(stability.to_string(index=False))
        print("[PASS] 三因子策略稳定性报告已生成。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
