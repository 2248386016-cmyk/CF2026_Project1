"""按相同成交数量与路径加回费用，生成毛收益/净收益归因。"""
from __future__ import annotations
import sys
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import yaml
PROJECT_ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(PROJECT_ROOT))
from project_config import BACKTEST_OUTPUT_DIR,DATABASE_DIR,print_section
OUTPUT_DIR=BACKTEST_OUTPUT_DIR/"gross_net"
SOURCES={"weekly":"experiment_weekly_backtest_daily","monthly":"experiment_monthly_backtest_daily","risk_extension":"extension_risk_backtest_daily"}

def main():
    print_section("01 同成交路径毛收益与净收益")
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    config=yaml.safe_load((PROJECT_ROOT/"config"/"backtest_config.yaml").read_text(encoding="utf-8"))
    initial=float(config["portfolio"]["initial_capital"]); annual_days=int(config["performance"]["annual_trading_days"])
    con=duckdb.connect(str(DATABASE_DIR/"cf2026_project1.duckdb"))
    paths=[]; summary=[]
    try:
        for experiment,table in SOURCES.items():
            frame=con.execute(f"SELECT * FROM {table} ORDER BY strategy,date").fetchdf()
            for strategy,part in frame.groupby("strategy",sort=True):
                part=part.sort_values("date").copy()
                part["experiment"]=experiment
                # 相同成交路径口径：不改变成交股数，仅将已支付费用作为未投资现金加回。
                part["gross_nav_same_path"]=part["nav"]+part["cumulative_transaction_cost"]
                part["gross_daily_return_same_path"]=part["gross_nav_same_path"].pct_change()
                first=part.index[0]
                part.loc[first,"gross_daily_return_same_path"]=part.loc[first,"gross_nav_same_path"]/initial-1
                net_final=float(part.nav.iloc[-1]); gross_final=float(part.gross_nav_same_path.iloc[-1])
                n=len(part); gross_returns=part.gross_daily_return_same_path.astype(float)
                gross_vol=float(gross_returns.std(ddof=1)*np.sqrt(annual_days))
                gross_sharpe=float(gross_returns.mean()/gross_returns.std(ddof=1)*np.sqrt(annual_days)) if gross_returns.std(ddof=1)>0 else np.nan
                summary.append(dict(experiment=experiment,strategy=strategy,start_date=part.date.min(),end_date=part.date.max(),trading_days=n,net_final_nav=net_final,gross_final_nav_same_path=gross_final,net_total_return=net_final/initial-1,gross_total_return_same_path=gross_final/initial-1,cost_drag_return=(gross_final-net_final)/initial,total_transaction_cost=float(part.transaction_cost.sum()),gross_annualized_return_same_path=(gross_final/initial)**(annual_days/n)-1,gross_annualized_volatility_same_path=gross_vol,gross_annualized_sharpe_same_path=gross_sharpe,method="same executed quantities; fees added back as non-invested cash"))
                paths.append(part[["date","experiment","strategy","nav","gross_nav_same_path","daily_return","gross_daily_return_same_path","transaction_cost","cumulative_transaction_cost"]])
        path_frame=pd.concat(paths,ignore_index=True); summary_frame=pd.DataFrame(summary)
        con.register("gross_net_paths",path_frame); con.execute("CREATE OR REPLACE TABLE gross_net_same_path_daily AS SELECT * FROM gross_net_paths"); con.unregister("gross_net_paths")
        con.register("gross_net_summary",summary_frame); con.execute("CREATE OR REPLACE TABLE gross_net_same_path_summary AS SELECT * FROM gross_net_summary"); con.unregister("gross_net_summary")
    finally: con.close()
    path_frame.to_csv(OUTPUT_DIR/"01_gross_net_daily_same_path.csv",index=False,encoding="utf-8-sig")
    summary_frame.to_csv(OUTPUT_DIR/"01_gross_net_summary_same_path.csv",index=False,encoding="utf-8-sig")
    (OUTPUT_DIR/"01_methodology.md").write_text("""# 毛收益与净收益口径\n\n采用同成交路径会计归因：沿用净回测实际成交日期、价格和数量，不重新下单；每日毛净值等于净值加累计已付交易费用。加回费用作为未投资现金，不参与后续交易或复利。这样差异只来自显式交易费，避免分别重跑造成持仓路径变化。结果未包含冲击成本、滑点和现金利息。\n""",encoding="utf-8")
    error=(summary_frame.cost_drag_return-summary_frame.total_transaction_cost/initial).abs().max()
    if error>1e-10: raise AssertionError(f"费用归因对账失败：{error}")
    print(summary_frame[["experiment","strategy","gross_total_return_same_path","net_total_return","cost_drag_return","total_transaction_cost"]].to_string(index=False))
    print("[PASS] 同成交路径毛净收益及费用归因已完成。")
if __name__=="__main__": main()
