"""02 - 汇总周频/月频收益、风险、成本、持仓行为并生成报告证据包。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import BACKTEST_OUTPUT_DIR, DATABASE_DIR, ensure_data_dirs, print_section


def main() -> None:
    print_section("02 比较周频与月频")
    ensure_data_dirs()
    output_dir = BACKTEST_OUTPUT_DIR / "weekly_vs_monthly"
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(DATABASE_DIR / "cf2026_project1.duckdb"), read_only=True)
    try:
        metrics = connection.execute(
            """
            SELECT 'weekly' AS frequency, * FROM experiment_weekly_backtest_metrics
            UNION ALL
            SELECT 'monthly', * FROM experiment_monthly_backtest_metrics
            ORDER BY strategy, frequency
            """
        ).fetchdf()
        periods = connection.execute(
            """
            SELECT 'weekly' AS frequency, * FROM experiment_weekly_backtest_period_metrics
            UNION ALL
            SELECT 'monthly', * FROM experiment_monthly_backtest_period_metrics
            ORDER BY strategy, sample_period, frequency
            """
        ).fetchdf()
        yearly = connection.execute(
            """
            SELECT 'weekly' AS frequency, * FROM experiment_weekly_backtest_yearly_returns
            UNION ALL
            SELECT 'monthly', * FROM experiment_monthly_backtest_yearly_returns
            ORDER BY strategy, year, frequency
            """
        ).fetchdf()
        rebalances = connection.execute(
            """
            SELECT 'weekly' AS frequency, count(*) AS rebalance_dates
            FROM experiment_weekly_strategy_rebalance_schedule
            UNION ALL
            SELECT 'monthly', count(*) FROM experiment_monthly_strategy_rebalance_schedule
            """
        ).fetchdf()
        selected_diagnostics = connection.execute(
            """
            SELECT i.factor, i.horizon, i.sample_period,
                   i.mean_rank_ic, i.rank_ic_ir,
                   s.mean_high_minus_low, s.average_group_monotonicity
            FROM factor_ic_summary i
            JOIN factor_spread_summary s
              USING (factor, horizon, sample_period)
            WHERE i.factor IN (SELECT factor FROM selected_factors) AND i.horizon=5
            ORDER BY i.factor, i.sample_period
            """
        ).fetchdf()
        data_evidence = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM daily_adjusted) AS adjusted_market_rows,
                (SELECT count(*) FROM market_data_clean) AS clean_rows,
                (SELECT count(*) FROM research_universe_daily) AS universe_rows,
                (SELECT count(*) FROM factor_values_raw) AS raw_factor_rows,
                (SELECT min(trade_date) FROM research_universe_daily) AS buffer_first_date,
                (SELECT max(trade_date) FROM research_universe_daily) AS buffer_last_date,
                (SELECT count(DISTINCT ts_code) FROM research_universe_daily) AS universe_stocks
            """
        ).fetchdf()
    finally:
        connection.close()

    metrics.to_csv(output_dir / "02_strategy_metrics.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(output_dir / "02_period_metrics.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(output_dir / "02_yearly_returns.csv", index=False, encoding="utf-8-sig")
    rebalances.to_csv(output_dir / "02_rebalance_counts.csv", index=False, encoding="utf-8-sig")
    selected_diagnostics.to_csv(output_dir / "02_selected_factor_diagnostics.csv", index=False, encoding="utf-8-sig")
    data_evidence.to_csv(output_dir / "02_data_and_sample_evidence.csv", index=False, encoding="utf-8-sig")

    multi = metrics.loc[metrics["strategy"] == "multi_equal_3"].set_index("frequency")
    comparison_columns = [
        "total_return", "annualized_return", "annualized_volatility", "annualized_sharpe",
        "max_drawdown", "total_turnover", "total_transaction_cost", "total_delist_writeoff",
        "trade_count", "maximum_single_asset_weight", "average_holdings_count",
        "blocked_buys", "blocked_sells",
    ]
    comparison = pd.DataFrame({
        "metric": comparison_columns,
        "weekly": [multi.loc["weekly", c] for c in comparison_columns],
        "monthly": [multi.loc["monthly", c] for c in comparison_columns],
    })
    comparison["monthly_minus_weekly"] = comparison["monthly"] - comparison["weekly"]
    comparison["monthly_over_weekly"] = comparison["monthly"] / comparison["weekly"].replace(0, pd.NA)
    comparison.to_csv(output_dir / "02_multi_factor_comparison.csv", index=False, encoding="utf-8-sig")

    config = yaml.safe_load((PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8"))
    audit_env_path = PROJECT_ROOT / "outputs" / "data_audit" / "06_environment_snapshot.json"
    audit_env = json.loads(audit_env_path.read_text(encoding="utf-8")) if audit_env_path.exists() else {}
    weekly = multi.loc["weekly"]
    monthly = multi.loc["monthly"]
    explanation = (
        f"# 周频 vs 月频对照实验证据\n\n"
        f"## 数据与假设\n\n"
        f"- 两组共用数据库、动态沪深主板资产池和复权口径。\n"
        f"- 样本区间：{config['research']['start_date']} 至 {config['research']['end_date']}。\n"
        f"- 两组均为前{config['portfolio']['top_n']}名等权，买入费率{config['cost']['buy_rate']:.4%}，卖出费率{config['cost']['sell_rate']:.4%}。\n"
        f"- 唯一改变：每周首个交易日 vs 每月首个交易日调仓。\n"
        f"- 原始数据快照文件数：{audit_env.get('raw_file_count', 'NA')}；快照清单SHA-256：{audit_env.get('manifest_sha256', 'NA')}。\n"
        f"- 未建模：冲击成本、滑点、整手约束、行业/市值中性化；退市无法卖出按零回收率核销。\n\n"
        f"## 三因子与回测\n\n"
        f"- 因子：20日低波动、5日反转、20日Amihud非流动性。\n"
        f"- 周频：年化收益 {weekly['annualized_return']:.2%}，Sharpe {weekly['annualized_sharpe']:.3f}，最大回撤 {weekly['max_drawdown']:.2%}，成本 {weekly['total_transaction_cost']:,.0f}元。\n"
        f"- 月频：年化收益 {monthly['annualized_return']:.2%}，Sharpe {monthly['annualized_sharpe']:.3f}，最大回撤 {monthly['max_drawdown']:.2%}，成本 {monthly['total_transaction_cost']:,.0f}元。\n\n"
        f"## 对照与解释\n\n"
        f"- 换手变化：{weekly['total_turnover']:.2f} → {monthly['total_turnover']:.2f}。\n"
        f"- 交易次数：{int(weekly['trade_count'])} → {int(monthly['trade_count'])}。\n"
        f"- 平均实际持仓：{weekly['average_holdings_count']:.2f} → {monthly['average_holdings_count']:.2f}。\n"
        f"- 最大单股权重：{weekly['maximum_single_asset_weight']:.2%} → {monthly['maximum_single_asset_weight']:.2%}。\n"
        f"- 只有调仓频率变化，因此收益、风险和成本差异可主要归因于信号更新速度与换手的变化。\n\n"
        f"## 复现信息\n\n"
        f"- 数据快照：`outputs/data_audit/06_raw_snapshot_manifest_sha256.csv`\n"
        f"- 代码/配置校验：`outputs/backtest/weekly_vs_monthly/01_code_and_config_sha256.csv`\n"
        f"- 配置：`config/backtest_config.yaml` 与 `config/experiments/weekly_vs_monthly.yaml`\n"
        f"- 运行时间与配置哈希：`01_runtime_and_reproduction.json`\n"
        f"- 检查输出：`03_experiment_checks.csv`\n"
    )
    (output_dir / "02_report_evidence.md").write_text(explanation, encoding="utf-8")
    print(comparison.to_string(index=False))
    print(f"证据包目录：{output_dir}")
    print("[PASS] 对照比较和报告证据已生成。")


if __name__ == "__main__":
    main()
