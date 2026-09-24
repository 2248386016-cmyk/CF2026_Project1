"""Evaluate a transparent subset of official Qlib Alpha158 expressions."""
from __future__ import annotations
from pathlib import Path
import duckdb, numpy as np, pandas as pd, yaml
from qlib.contrib.data.loader import Alpha158DL
from scipy.stats import spearmanr

ROOT=Path(__file__).resolve().parents[2]

def main():
    cfg=yaml.safe_load((ROOT/'config/model_baseline.yaml').read_text(encoding='utf-8'))
    panel=pd.read_parquet(ROOT/'outputs/backtest'/cfg['run']['run_id']/'model_panel.parquet')[['date','asset','forward_return_20d']]
    assets=sorted(panel.asset.unique()); con=duckdb.connect(cfg['run']['source_database'],read_only=True)
    con.register('assets',pd.DataFrame({'asset':assets}))
    market=con.execute("""SELECT d.ts_code AS asset,d.trade_date AS date,d.open_adj AS open_px,d.high_adj AS high_px,d.low_adj AS low_px,d.close_adj AS close_px,d.vol AS volume,d.amount FROM daily_adjusted d JOIN assets a ON d.ts_code=a.asset WHERE d.trade_date>=DATE '2019-10-01' AND d.trade_date<=DATE '2025-12-31' ORDER BY asset,date""").fetchdf();con.close()
    market=market.rename(columns={'open_px':'open','high_px':'high','low_px':'low','close_px':'close'})
    market['date']=pd.to_datetime(market.date);g=market.groupby('asset',group_keys=False);eps=1e-12
    market['KMID']=(market.close-market.open)/market.open;market['KLEN']=(market.high-market.low)/market.open
    market['KSFT']=(2*market.close-market.high-market.low)/market.open
    for w in [5,10,20,60]:
        market[f'ROC{w}']=g.close.shift(w)/market.close
        market[f'MA{w}']=g.close.transform(lambda x:x.rolling(w).mean())/market.close
        market[f'STD{w}']=g.close.transform(lambda x:x.rolling(w).std())/market.close
    for w in [5,20,60]:
        lo=g.low.transform(lambda x:x.rolling(w).min());hi=g.high.transform(lambda x:x.rolling(w).max())
        market[f'RSV{w}']=(market.close-lo)/(hi-lo+eps)
    market['CORR20']=g.apply(lambda x:x.close.rolling(20).corr(np.log(x.volume+1)),include_groups=False).reset_index(level=0,drop=True).sort_index()
    up=(market.close>g.close.shift(1)).astype(float);market['CNTP20']=up.groupby(market.asset).transform(lambda x:x.rolling(20).mean())
    weighted=(market.close/g.close.shift(1)-1).abs()*market.volume
    market['WVMA20']=weighted.groupby(market.asset).transform(lambda x:x.rolling(20).std())/(weighted.groupby(market.asset).transform(lambda x:x.rolling(20).mean())+eps)
    features=['KMID','KLEN','KSFT','ROC5','ROC10','ROC20','ROC60','MA5','MA10','MA20','MA60','STD5','STD10','STD20','STD60','RSV5','RSV20','RSV60','CORR20','CNTP20','WVMA20']
    official=dict(zip(*reversed(Alpha158DL.get_feature_config())))
    joined=panel.merge(market[['date','asset',*features]],on=['date','asset'],how='left')
    rows=[]
    periods={'train':('2020-01-01','2022-12-31'),'validation':('2023-01-01','2024-12-31'),'test':('2025-01-01','2025-12-31')}
    for period,(start,end) in periods.items():
      sample=joined[joined.date.between(start,end)]
      for factor in features:
        daily=[]
        for _,frame in sample[['date',factor,'forward_return_20d']].dropna().groupby('date'):
          if len(frame)>=30: daily.append(spearmanr(frame[factor],frame.forward_return_20d).statistic)
        rows.append({'period':period,'factor':factor,'qlib_expression':official.get(factor,''),'mean_rank_ic':np.nanmean(daily),'ic_ir':np.nanmean(daily)/(np.nanstd(daily,ddof=1)+eps),'months':len(daily)})
    out=ROOT/'outputs/qlib';out.mkdir(parents=True,exist_ok=True);result=pd.DataFrame(rows);result.to_csv(out/'alpha158_subset_ic.csv',index=False)
    (out/'README.md').write_text('Qlib 0.9.7 Alpha158 透明子集，共21个OHLCV因子。公式名称来自官方 Alpha158DL；数值基于本项目复权行情重算，并按动态沪深300月末样本计算20日 RankIC。\n',encoding='utf-8')
    print(result.groupby('period').apply(lambda x:x.nlargest(5,'mean_rank_ic'),include_groups=False).to_string(index=False))
if __name__=='__main__':main()
