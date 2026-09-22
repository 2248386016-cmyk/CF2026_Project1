"""验证实验控制条件并生成可直接用于报告的证据摘要。"""
from __future__ import annotations
import json,sys
from pathlib import Path
import duckdb
import pandas as pd
import yaml
PROJECT_ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(PROJECT_ROOT))
from project_config import BACKTEST_OUTPUT_DIR,DATABASE_DIR,print_section
OUTPUT_DIR=BACKTEST_OUTPUT_DIR/"portfolio_risk_extension"
CONFIG_PATH=PROJECT_ROOT/"config"/"experiments"/"portfolio_risk_extension.yaml"
def pct(value): return f"{value:.2%}"
def main():
    print_section("03 验证并报告组合与风险拓展")
    config=yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    con=duckdb.connect(str(DATABASE_DIR/"cf2026_project1.duckdb"),read_only=True)
    try:
        targets=con.execute("SELECT * FROM extension_risk_strategy_targets").fetchdf()
        daily=con.execute("SELECT * FROM extension_risk_backtest_daily").fetchdf()
        metrics=con.execute("SELECT * FROM extension_risk_backtest_metrics").fetchdf()
        diagnostics=con.execute("SELECT * FROM extension_risk_target_diagnostics").fetchdf()
    finally: con.close()
    asset_sets=targets.groupby(["rebalance_date","strategy"]).asset.apply(lambda x:tuple(sorted(x))).reset_index()
    mismatch=sum(int(frame.asset.nunique()!=1) for _,frame in asset_sets.groupby("rebalance_date"))
    sums=targets.groupby(["rebalance_date","strategy"]).target_weight.sum()
    capped=targets[targets.strategy.str.contains("cap_08")]
    checks=dict(strategy_count=int(targets.strategy.nunique()),rebalance_dates=int(targets.rebalance_date.nunique()),same_asset_selection_mismatch_dates=int(mismatch),duplicate_target_keys=int(targets.duplicated(["rebalance_date","strategy","asset"]).sum()),future_information_rows=int((pd.to_datetime(targets.formation_date)>=pd.to_datetime(targets.rebalance_date)).sum()),risk_history_after_formation_rows=int((pd.to_datetime(diagnostics.history_last_date)>pd.to_datetime(diagnostics.formation_date)).sum()),negative_target_weights=int((targets.target_weight < -1e-12).sum()),target_exposure_above_one=int((sums>1+1e-9).sum()),cap_target_violations=int((capped.target_weight>float(config["risk_model"]["weight_cap"])+1e-8).sum()),duplicate_daily_keys=int(daily.duplicated(["date","strategy"]).sum()),nonpositive_nav_rows=int((daily.nav<=0).sum()),date_count_min=int(daily.groupby("strategy").date.nunique().min()),date_count_max=int(daily.groupby("strategy").date.nunique().max()))
    bad=[k for k in ["same_asset_selection_mismatch_dates","duplicate_target_keys","future_information_rows","risk_history_after_formation_rows","negative_target_weights","target_exposure_above_one","cap_target_violations","duplicate_daily_keys","nonpositive_nav_rows"] if checks[k]!=0]
    if checks["date_count_min"]!=checks["date_count_max"]: bad.append("date_count")
    pd.DataFrame([checks]).to_csv(OUTPUT_DIR/"03_experiment_checks.csv",index=False,encoding="utf-8-sig")
    if bad: raise AssertionError(f"实验验证失败：{bad}")
    keyed=metrics.set_index("strategy"); base=keyed.loc["monthly_equal"]
    best_name=metrics.sort_values("annualized_sharpe",ascending=False).iloc[0].strategy; best=keyed.loc[best_name]
    runtime=json.loads((OUTPUT_DIR/"01_runtime.json").read_text(encoding="utf-8"))
    report=f'''# 组合与风险自主拓展：同信号下的风险配置比较

## 研究设计

- 样本：{config['fixed_conditions']['research_start']} 至 {config['fixed_conditions']['research_end']}，动态沪深主板资产池。
- 所有方案使用完全相同的月频三因子 Top 20 信号、复权价格、交易日、费率和交易约束。
- 唯一变化是组合层：等权、波动率目标、ERC风险平价、8%目标权重上限及其组合。
- 风险估计仅使用形成日及以前{config['risk_model']['lookback_trading_days']}个交易日，至少{config['risk_model']['minimum_observations']}个有效观测。
- 波动率目标不加杠杆，未投入部分作为零收益现金。

## 主要结果

- 等权月频：年化收益 {pct(base.annualized_return)}，年化波动 {pct(base.annualized_volatility)}，Sharpe {base.annualized_sharpe:.3f}，最大回撤 {pct(base.max_drawdown)}，成本 {base.total_transaction_cost:,.0f} 元。
- Sharpe最高方案：`{best_name}`；年化收益 {pct(best.annualized_return)}，年化波动 {pct(best.annualized_volatility)}，Sharpe {best.annualized_sharpe:.3f}，最大回撤 {pct(best.max_drawdown)}，成本 {best.total_transaction_cost:,.0f} 元。
- 完整指标、年度结果、训练/验证/测试分段及滚动稳定性见同目录CSV，不能只根据全样本Sharpe判断拓展成功。

## 解释边界

- 波动率目标同时改变股票总仓位和现金比例；收益变化应结合实际风险暴露解释。
- 风险平价改变Top 20内部权重，但不改变选股集合；差异来自风险配置、交易路径及成本。
- 8%是调仓目标权重上限。价格变动或交易受限时，实际权重仍可能暂时超过8%。
- 未建模冲击成本、滑点、整手约束、现金利息及风险模型参数误差。

## 复现信息

- 配置：`config/experiments/portfolio_risk_extension.yaml`
- 目标权重与风险预测：`01_target_weights.csv`、`01_target_diagnostics.csv`
- 口径检查：`03_experiment_checks.csv`
- 运行时间：{runtime['runtime_seconds']:.3f}秒；配置SHA-256：`{runtime['config_sha256']}`。
'''
    (OUTPUT_DIR/"03_report_evidence.md").write_text(report,encoding="utf-8")
    print(pd.DataFrame([checks]).to_string(index=False)); print(f"Sharpe最高方案：{best_name}"); print("[PASS] 同信号、无未来信息、权重和日期口径检查全部通过。")
if __name__=="__main__": main()
