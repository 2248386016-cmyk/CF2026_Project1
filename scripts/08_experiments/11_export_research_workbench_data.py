"""Export compact, browser-ready evidence from audited experiment outputs."""
from __future__ import annotations
import json
from pathlib import Path
import duckdb, pandas as pd, yaml

ROOT=Path(__file__).resolve().parents[2]

def records(frame):
    return json.loads(frame.to_json(orient="records",date_format="iso",double_precision=6))

def main():
    cfg=yaml.safe_load((ROOT/'config/model_baseline.yaml').read_text(encoding='utf-8'))
    out=ROOT/'outputs/backtest'/cfg['run']['run_id']
    daily=pd.read_csv(out/'regime_overlay_daily.csv',parse_dates=['date'])
    daily['strategy_nav']=(1+daily.strategy_return).cumprod();daily['benchmark_nav']=(1+daily.benchmark_return).cumprod()
    daily['strategy_drawdown']=daily.strategy_nav/daily.strategy_nav.cummax()-1
    daily['benchmark_drawdown']=daily.benchmark_nav/daily.benchmark_nav.cummax()-1
    daily=daily.iloc[::3].copy()
    metrics=pd.read_csv(out/'regime_overlay_metrics.csv')
    factor=pd.read_csv(ROOT/'outputs/evaluation/02_ic_summary.csv')
    con=duckdb.connect(cfg['run']['source_database'],read_only=True)
    trades=con.execute("""SELECT date_trunc('month',date) AS month_start,count(*) AS trades,sum(gross_amount) AS gross_amount,sum(cost) AS cost FROM model_baseline_backtest_trades WHERE strategy='lgb_defensive_top10' GROUP BY 1 ORDER BY 1""").fetchdf();con.close()
    payload={'meta':{'runId':cfg['run']['run_id'],'universe':'动态沪深300','selectedStrategy':'126日相对强弱状态切换 + 防御型 LightGBM Top10','generatedFrom':'audited local outputs'},
      'metrics':records(metrics),'nav':records(daily[['date','strategy_nav','benchmark_nav','strategy_drawdown','benchmark_drawdown','active_weight']]),
      'factors':records(factor),'trades':records(trades)}
    target=ROOT/'web/dashboard-data.js';target.write_text('window.DASHBOARD_DATA='+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    print(target, target.stat().st_size)
if __name__=='__main__':main()
