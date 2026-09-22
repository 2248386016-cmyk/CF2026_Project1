"""03 - 计算收益、波动率、Sharpe、回撤、换手和成本指标。"""

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
    print_section("03 分析回测绩效")
    ensure_data_dirs()
    config = yaml.safe_load((PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8"))
    annual_days = int(config["performance"]["annual_trading_days"])
    risk_free = float(config["performance"]["annual_risk_free_rate"])
    initial_capital = float(config["portfolio"]["initial_capital"])

    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"))
    try:
        daily = connection.execute("SELECT * FROM backtest_daily ORDER BY strategy, date").fetchdf()
        trade_stats = connection.execute(
            """
            SELECT strategy,
                   count(*) FILTER (WHERE side IN ('BUY', 'SELL')) AS trade_count,
                   count(*) FILTER (WHERE side = 'BUY') AS buy_trade_count,
                   count(*) FILTER (WHERE side = 'SELL') AS sell_trade_count,
                   count(*) FILTER (WHERE side = 'DELIST_WRITE_OFF') AS delist_writeoff_events
            FROM backtest_trades GROUP BY strategy
            """
        ).fetchdf().set_index("strategy")
        position_stats = connection.execute(
            """
            SELECT strategy, max(weight) AS maximum_single_asset_weight,
                   avg(daily_holdings) AS average_holdings_count
            FROM (
                SELECT date, strategy, max(weight) AS weight,
                       count(*) AS daily_holdings
                FROM backtest_positions GROUP BY date, strategy
            )
            GROUP BY strategy
            """
        ).fetchdf().set_index("strategy")
        metrics: list[dict] = []
        drawdowns: list[pd.DataFrame] = []
        yearly_rows: list[dict] = []
        period_rows: list[dict] = []
        for strategy, frame in daily.groupby("strategy", sort=True):
            frame = frame.sort_values("date").copy()
            returns = frame["daily_return"].astype(float)
            nav = frame["nav"].astype(float)
            running_high = nav.cummax()
            drawdown = 1.0 - nav / running_high
            frame["drawdown"] = drawdown
            drawdowns.append(frame[["date", "strategy", "drawdown"]])
            n = len(frame)
            total_return = nav.iloc[-1] / initial_capital - 1
            annual_return = (nav.iloc[-1] / initial_capital) ** (annual_days / n) - 1
            annual_vol = returns.std(ddof=1) * np.sqrt(annual_days)
            daily_rf = (1 + risk_free) ** (1 / annual_days) - 1
            excess = returns - daily_rf
            sharpe = np.sqrt(annual_days) * excess.mean() / excess.std(ddof=1) if excess.std(ddof=1) > 0 else np.nan
            metrics.append({
                "strategy": strategy, "start_date": frame["date"].min(),
                "end_date": frame["date"].max(), "trading_days": n,
                "final_nav": nav.iloc[-1], "total_return": total_return,
                "annualized_return": annual_return, "annualized_volatility": annual_vol,
                "annualized_sharpe": sharpe, "max_drawdown": drawdown.max(),
                "total_turnover": frame["turnover"].sum(),
                "average_rebalance_turnover": frame.loc[frame["is_rebalance"], "turnover"].mean(),
                "total_transaction_cost": frame["transaction_cost"].sum(),
                "total_delist_writeoff": frame["delist_writeoff"].sum(),
                "cost_as_initial_capital": frame["transaction_cost"].sum() / initial_capital,
                "blocked_buys": int(frame["blocked_buys"].sum()),
                "blocked_sells": int(frame["blocked_sells"].sum()),
                "trade_count": int(trade_stats.loc[strategy, "trade_count"]),
                "buy_trade_count": int(trade_stats.loc[strategy, "buy_trade_count"]),
                "sell_trade_count": int(trade_stats.loc[strategy, "sell_trade_count"]),
                "delist_writeoff_events": int(trade_stats.loc[strategy, "delist_writeoff_events"]),
                "maximum_single_asset_weight": float(position_stats.loc[strategy, "maximum_single_asset_weight"]),
                "average_holdings_count": float(position_stats.loc[strategy, "average_holdings_count"]),
            })
            frame["year"] = pd.to_datetime(frame["date"]).dt.year
            for year, year_frame in frame.groupby("year"):
                year_return = (1 + year_frame["daily_return"]).prod() - 1
                yearly_rows.append({"strategy": strategy, "year": int(year), "return": year_return})
            periods = {
                "train_2020_2023": ("2020-01-01", "2023-12-31"),
                "validation_2024": ("2024-01-01", "2024-12-31"),
                "test_2025": ("2025-01-01", "2025-12-31"),
            }
            date_series = pd.to_datetime(frame["date"])
            for period, (start, end) in periods.items():
                part = frame.loc[(date_series >= start) & (date_series <= end)].copy()
                part_returns = part["daily_return"].astype(float)
                if part.empty:
                    continue
                cumulative = (1.0 + part_returns).prod() - 1.0
                p_vol = part_returns.std(ddof=1) * np.sqrt(annual_days)
                p_excess = part_returns - daily_rf
                p_sharpe = (
                    np.sqrt(annual_days) * p_excess.mean() / p_excess.std(ddof=1)
                    if p_excess.std(ddof=1) > 0 else np.nan
                )
                period_nav = (1.0 + part_returns).cumprod()
                p_drawdown = 1.0 - period_nav / period_nav.cummax()
                period_rows.append({
                    "strategy": strategy, "sample_period": period,
                    "start_date": part["date"].min(), "end_date": part["date"].max(),
                    "trading_days": len(part), "period_return": cumulative,
                    "annualized_return": (1.0 + cumulative) ** (annual_days / len(part)) - 1.0,
                    "annualized_volatility": p_vol, "annualized_sharpe": p_sharpe,
                    "max_drawdown": p_drawdown.max(),
                    "total_turnover": part["turnover"].sum(),
                    "transaction_cost": part["transaction_cost"].sum(),
                    "delist_writeoff": part["delist_writeoff"].sum(),
                })

        metrics_frame = pd.DataFrame(metrics).sort_values("annualized_sharpe", ascending=False)
        drawdown_frame = pd.concat(drawdowns, ignore_index=True)
        yearly_frame = pd.DataFrame(yearly_rows)
        period_frame = pd.DataFrame(period_rows)
        for name, frame in [
            ("backtest_metrics", metrics_frame),
            ("backtest_drawdowns", drawdown_frame),
            ("backtest_yearly_returns", yearly_frame),
            ("backtest_period_metrics", period_frame),
        ]:
            connection.register("temporary_frame", frame)
            connection.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM temporary_frame")
            connection.unregister("temporary_frame")

        daily.to_csv(BACKTEST_OUTPUT_DIR / "03_daily_nav.csv", index=False, encoding="utf-8-sig")
        metrics_frame.to_csv(BACKTEST_OUTPUT_DIR / "03_performance_metrics.csv", index=False, encoding="utf-8-sig")
        yearly_frame.to_csv(BACKTEST_OUTPUT_DIR / "03_yearly_returns.csv", index=False, encoding="utf-8-sig")
        period_frame.to_csv(BACKTEST_OUTPUT_DIR / "03_period_performance_metrics.csv", index=False, encoding="utf-8-sig")
        connection.execute("SELECT * FROM backtest_trades ORDER BY date, strategy, asset").fetchdf().to_csv(
            BACKTEST_OUTPUT_DIR / "03_trade_log.csv", index=False, encoding="utf-8-sig"
        )
        print(metrics_frame.to_string(index=False))
        print("\n分阶段绩效：")
        print(period_frame.to_string(index=False))
        print("[PASS] 绩效、回撤、换手和成本报告已生成。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
