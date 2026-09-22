"""从清洗后的数据库导出无需Token即可检查的固定小样本。"""
from __future__ import annotations
import hashlib,sys
from pathlib import Path
import duckdb
import pandas as pd
PROJECT_ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(PROJECT_ROOT))
from project_config import DATABASE_DIR,print_section
OUTPUT_DIR=PROJECT_ROOT/"outputs"/"reproducibility"/"shareable_sample"
START,END="2025-01-02","2025-03-31"; ASSET_COUNT=10
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    return h.hexdigest()
def main():
    print_section("02 生成可分享小样本"); OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(DATABASE_DIR/"cf2026_project1.duckdb"),read_only=True)
    try:
        assets=[r[0] for r in con.execute(f"SELECT ts_code FROM market_data_clean WHERE trade_date BETWEEN DATE '{START}' AND DATE '{END}' GROUP BY ts_code ORDER BY count(*) DESC,ts_code LIMIT {ASSET_COUNT}").fetchall()]
        placeholders=",".join("?" for _ in assets)
        queries={
            "sample_raw_daily.csv":f"SELECT * FROM daily_raw WHERE ts_code IN ({placeholders}) AND strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')::DATE BETWEEN DATE '{START}' AND DATE '{END}' ORDER BY strptime(CAST(trade_date AS VARCHAR), '%Y%m%d')::DATE,ts_code",
            "sample_clean_market.csv":f"SELECT * FROM market_data_clean WHERE ts_code IN ({placeholders}) AND trade_date BETWEEN DATE '{START}' AND DATE '{END}' ORDER BY trade_date,ts_code",
            "sample_universe.csv":f"SELECT * FROM research_universe_daily WHERE ts_code IN ({placeholders}) AND trade_date BETWEEN DATE '{START}' AND DATE '{END}' ORDER BY trade_date,ts_code",
            "sample_factor_values.csv":f"SELECT date,asset,factor,raw_value,winsorized_value,zscore_value,rank_pct,cross_section_assets FROM factor_values_processed_detail WHERE asset IN ({placeholders}) AND date BETWEEN DATE '{START}' AND DATE '{END}' ORDER BY date,asset,factor",
            "sample_forward_returns.csv":f"SELECT * FROM forward_returns WHERE asset IN ({placeholders}) AND date BETWEEN DATE '{START}' AND DATE '{END}' ORDER BY date,asset",
        }
        records=[]
        for filename,query in queries.items():
            frame=con.execute(query,assets).fetchdf(); path=OUTPUT_DIR/filename
            frame.to_csv(path,index=False,encoding="utf-8-sig")
            records.append(dict(filename=filename,rows=len(frame),columns=len(frame.columns),sha256=digest(path)))
    finally: con.close()
    pd.DataFrame(records).to_csv(OUTPUT_DIR/"sample_manifest_sha256.csv",index=False,encoding="utf-8-sig")
    (OUTPUT_DIR/"README_sample.md").write_text(f"""# 可分享离线小样本\n\n- 固定区间：{START} 至 {END}\n- 固定资产数：{ASSET_COUNT}\n- 资产：{', '.join(assets)}\n- 来源：正式数据库导出的原始行情、清洗行情、动态资产池、因子值和未来收益标签。\n- 用途：无需Tushare Token即可检查字段、唯一键、清洗口径、因子长表和标签结构。\n- 限制：这是教学复现小样本，不用于代表全样本绩效，也不能复现完整策略净值。\n- 完整数据获取方式见项目README；每个文件的行数和SHA-256见sample_manifest_sha256.csv。\n\n快速读取：\n```python\nimport pandas as pd\nmarket = pd.read_csv('sample_clean_market.csv', parse_dates=['trade_date'])\nfactors = pd.read_csv('sample_factor_values.csv', parse_dates=['date'])\nassert market.duplicated(['trade_date', 'ts_code']).sum() == 0\nassert factors.duplicated(['date', 'asset', 'factor']).sum() == 0\n```\n""",encoding="utf-8")
    print(pd.DataFrame(records).to_string(index=False)); print("[PASS] 离线可分享小样本已生成。")
if __name__=="__main__": main()
