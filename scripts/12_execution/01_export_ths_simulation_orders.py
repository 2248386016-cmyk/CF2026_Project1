"""Export auditable orders for manual confirmation in THS simulation trading."""
from __future__ import annotations
import argparse
from pathlib import Path
import duckdb, pandas as pd, yaml

ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser();p.add_argument('--capital',type=float,default=1_000_000);p.add_argument('--confirm-live',action='store_true');a=p.parse_args()
    if a.confirm_live: raise RuntimeError('项目不支持无人值守提交委托；请在同花顺客户端人工复核。')
    cfg=yaml.safe_load((ROOT/'config/model_baseline.yaml').read_text(encoding='utf-8'));con=duckdb.connect(cfg['run']['source_database'],read_only=True)
    date=con.execute('SELECT max(rebalance_date) FROM model_baseline_targets').fetchone()[0]
    frame=con.execute("SELECT asset,target_weight,score FROM model_baseline_targets WHERE rebalance_date=? AND strategy='lgb_defensive_top10' ORDER BY target_rank",[date]).fetchdf();con.close()
    frame['证券代码']=frame.asset.str[:6];frame['市场']=frame.asset.str[-2:];frame['方向']='买入';frame['目标权重']=frame.target_weight;frame['参考资金']=a.capital;frame['目标金额']=a.capital*frame.target_weight;frame['委托价格']='客户端复核';frame['委托数量']='客户端按整手计算';frame['信号日期']=str(date);frame['状态']='待人工确认'
    out=ROOT/'outputs/execution';out.mkdir(parents=True,exist_ok=True);path=out/f'ths_simulation_orders_{date}.csv';frame[['证券代码','市场','方向','目标权重','参考资金','目标金额','委托价格','委托数量','信号日期','状态']].to_csv(path,index=False,encoding='utf-8-sig');print(path)
if __name__=='__main__':main()
