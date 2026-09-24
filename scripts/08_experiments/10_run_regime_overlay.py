"""Validation-selected benchmark/active regime overlay with one-day-lagged signals."""
from pathlib import Path
import duckdb, numpy as np, pandas as pd, yaml

ROOT=Path(__file__).resolve().parents[2]

def stats(r):
    n=(1+r).cumprod(); years=len(r)/242
    return n.iloc[-1]-1,n.iloc[-1]**(1/years)-1,-(n/n.cummax()-1).min(),r.mean()/r.std()*np.sqrt(242)

def main():
    cfg=yaml.safe_load((ROOT/'config/model_baseline.yaml').read_text(encoding='utf-8'))
    con=duckdb.connect(cfg['run']['source_database'],read_only=True)
    active=con.execute("SELECT date,strategy,daily_return FROM model_baseline_backtest_daily WHERE date>=DATE '2023-01-01'").fetchdf();con.close()
    active.date=pd.to_datetime(active.date)
    idx=pd.read_parquet(ROOT/'data/model_inputs'/cfg['run']['run_id']/'csi300_index_daily.parquet').sort_values('trade_date')
    idx['date']=pd.to_datetime(idx.trade_date);idx['benchmark_return']=idx.close.pct_change()
    wide=active.pivot(index='date',columns='strategy',values='daily_return').join(idx.set_index('date').benchmark_return).dropna(subset=['benchmark_return'])
    candidates=[]
    for strategy in ['lgb_top10','lgb_top20','lgb_top30','lgb_defensive_top10','lgb_mom_quality_top20']:
      for window in [21,42,63,126]:
       for allocation in [.5,.75,1.0]:
        relative=(1+wide[strategy]).rolling(window).apply(np.prod,raw=True)/(1+wide.benchmark_return).rolling(window).apply(np.prod,raw=True)-1
        raw_signal=(relative.shift(1)>0).astype(float)*allocation
        # Freeze the regime choice for each calendar month to avoid daily churn.
        signal=raw_signal.groupby(raw_signal.index.to_period('M')).transform('first')
        # Conservative overlay switching charge: sell one sleeve and buy the other.
        switch_cost=signal.diff().abs().fillna(signal.abs())*.0016
        ret=signal*wide[strategy]+(1-signal)*wide.benchmark_return-switch_cost
        val=ret.loc['2023':'2024']; total,annual,dd,sh=stats(val)
        candidates.append((annual,sh,-dd,strategy,window,allocation,ret,signal))
    chosen=max(candidates,key=lambda x:(x[0],x[1],x[2]))
    _,_,_,strategy,window,allocation,ret,signal=chosen
    rows=[]
    for period,sl in [('validation',slice('2023','2024')),('test',slice('2025','2025'))]:
      for name,series in [('regime_overlay',ret.loc[sl]),('csi300',wide.benchmark_return.loc[sl])]:
        total,annual,dd,sh=stats(series.dropna()); rows.append({'period':period,'strategy':name,'total_return':total,'annualized_return':annual,'max_drawdown':dd,'sharpe':sh})
    result=pd.DataFrame(rows); out=ROOT/'outputs/backtest'/cfg['run']['run_id'];result.to_csv(out/'regime_overlay_metrics.csv',index=False)
    pd.DataFrame({'date':wide.index,'active_return':wide[strategy],'benchmark_return':wide.benchmark_return,'active_weight':signal,'strategy_return':ret}).to_csv(out/'regime_overlay_daily.csv',index=False)
    print({'base_strategy':strategy,'window':window,'active_allocation':allocation});print(result.to_string(index=False))
if __name__=='__main__':main()
