"""比较风险拓展的收益、风险、成本、持仓行为与稳定性。"""
from __future__ import annotations
import sys
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
PROJECT_ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(PROJECT_ROOT))
from project_config import BACKTEST_OUTPUT_DIR,DATABASE_DIR,print_section
OUTPUT_DIR=BACKTEST_OUTPUT_DIR/"portfolio_risk_extension"

def rolling_stability(daily,windows=(63,121,242)):
    rows=[]
    for strategy,frame in daily.groupby("strategy"):
        values=frame.sort_values("date").daily_return.astype(float)
        for window in windows:
            rr=(1+values).rolling(window).apply(np.prod,raw=True)-1
            rv=values.rolling(window).std(ddof=1)*np.sqrt(242)
            rs=values.rolling(window).mean()/values.rolling(window).std(ddof=1)*np.sqrt(242)
            valid=rr.dropna()
            rows.append(dict(strategy=strategy,window_days=window,observations=len(valid),positive_return_ratio=float((valid>0).mean()),median_rolling_return=float(valid.median()),worst_rolling_return=float(valid.min()),median_rolling_volatility=float(rv.dropna().median()),positive_sharpe_ratio=float((rs.dropna()>0).mean())))
    return pd.DataFrame(rows)

def main():
    print_section("02 分析组合与风险拓展"); OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(DATABASE_DIR/"cf2026_project1.duckdb"),read_only=True)
    try:
        metrics=con.execute("SELECT * FROM extension_risk_backtest_metrics").fetchdf()
        daily=con.execute("SELECT * FROM extension_risk_backtest_daily ORDER BY strategy,date").fetchdf()
        yearly=con.execute("SELECT * FROM extension_risk_backtest_yearly_returns ORDER BY strategy,year").fetchdf()
        periods=con.execute("SELECT * FROM extension_risk_backtest_period_metrics ORDER BY strategy,sample_period").fetchdf()
        diagnostics=con.execute("SELECT * FROM extension_risk_target_diagnostics").fetchdf()
    finally: con.close()
    daily["cash_ratio"]=daily.cash/daily.nav
    cash=daily.groupby("strategy").agg(average_cash_ratio=("cash_ratio","mean"),maximum_cash_ratio=("cash_ratio","max")).reset_index()
    target=diagnostics.groupby("strategy").agg(average_target_equity_exposure=("target_equity_exposure","mean"),minimum_target_equity_exposure=("target_equity_exposure","min"),average_forecast_volatility=("forecast_annual_volatility","mean"),maximum_target_weight=("maximum_target_weight","max"),solver_success_rate=("erc_solver_success","mean")).reset_index()
    comparison=metrics.merge(cash,on="strategy",how="left").merge(target,on="strategy",how="left")
    base=comparison.loc[comparison.strategy=="monthly_equal"].iloc[0]
    for col in ["annualized_return","annualized_volatility","annualized_sharpe","max_drawdown","total_turnover","total_transaction_cost"]:
        comparison[f"change_vs_equal_{col}"]=comparison[col]-base[col]
    stability=rolling_stability(daily)
    ys=yearly.groupby("strategy").agg(positive_years=("return",lambda x:int((x>0).sum())),worst_year_return=("return","min"),median_year_return=("return","median")).reset_index()
    comparison=comparison.merge(ys,on="strategy",how="left")
    comparison.to_csv(OUTPUT_DIR/"02_strategy_comparison.csv",index=False,encoding="utf-8-sig")
    yearly.to_csv(OUTPUT_DIR/"02_yearly_returns.csv",index=False,encoding="utf-8-sig")
    periods.to_csv(OUTPUT_DIR/"02_period_metrics.csv",index=False,encoding="utf-8-sig")
    stability.to_csv(OUTPUT_DIR/"02_rolling_stability.csv",index=False,encoding="utf-8-sig")
    daily.to_csv(OUTPUT_DIR/"02_daily_nav.csv",index=False,encoding="utf-8-sig")
    display=comparison[["strategy","annualized_return","annualized_volatility","annualized_sharpe","max_drawdown","total_turnover","total_transaction_cost","average_cash_ratio","maximum_single_asset_weight","positive_years","worst_year_return"]].sort_values("annualized_sharpe",ascending=False)
    display.to_csv(OUTPUT_DIR/"02_key_results.csv",index=False,encoding="utf-8-sig")
    print(display.to_string(index=False)); print("[PASS] 风险、成本、持仓行为和稳定性比较已输出。")
if __name__=="__main__": main()
