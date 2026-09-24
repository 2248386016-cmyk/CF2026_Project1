"""固定月频三因子选股，运行波动率目标、权重上限和ERC风险平价拓展。"""
from __future__ import annotations
import hashlib, json, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from project_config import BACKTEST_OUTPUT_DIR, DATABASE_DIR, print_section

BACKTEST_DIR = PROJECT_ROOT / "scripts" / "07_backtest"
OUTPUT_DIR = BACKTEST_OUTPUT_DIR / "portfolio_risk_extension"
CONFIG_PATH = PROJECT_ROOT / "config" / "experiments" / "portfolio_risk_extension.yaml"
RESULT_TABLES = ["strategy_rebalance_schedule", "strategy_targets", "backtest_daily",
                 "backtest_trades", "backtest_positions", "backtest_metrics",
                 "backtest_drawdowns", "backtest_yearly_returns", "backtest_period_metrics"]

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()

def erc_weights(covariance, cap, minimum):
    n = covariance.shape[0]
    initial = np.repeat(1.0 / n, n)
    upper = 1.0 if cap is None else cap
    def objective(weights):
        marginal = covariance @ weights
        contribution = weights * marginal
        variance = float(weights @ marginal)
        return float(np.sum((contribution - variance / n) ** 2) / max(variance ** 2, 1e-20))
    result = minimize(objective, initial, method="SLSQP", bounds=[(minimum, upper)] * n,
                      constraints={"type": "eq", "fun": lambda w: w.sum() - 1.0},
                      options={"maxiter": 1000, "ftol": 1e-12})
    if result.success and np.all(np.isfinite(result.x)):
        weights = np.maximum(result.x, 0.0)
        return weights / weights.sum(), True
    inverse_vol = 1.0 / np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    weights = inverse_vol / inverse_vol.sum()
    if cap is not None:
        for _ in range(n + 2):
            excess = np.maximum(weights - cap, 0.0).sum()
            weights = np.minimum(weights, cap)
            eligible = weights < cap - 1e-12
            if excess <= 1e-12 or not eligible.any(): break
            weights[eligible] += excess * weights[eligible] / weights[eligible].sum()
    return weights / weights.sum(), False

def rc_error(weights, covariance):
    contribution = weights * (covariance @ weights)
    if contribution.sum() <= 0: return np.nan
    return float(np.max(np.abs(contribution / contribution.sum() - 1 / len(weights))))

def main():
    print_section("01 运行组合与风险拓展")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    risk = config["risk_model"]
    lookback, min_obs = int(risk["lookback_trading_days"]), int(risk["minimum_observations"])
    annual_days, shrinkage = int(risk["annual_trading_days"]), float(risk["covariance_shrinkage"])
    ridge, min_weight = float(risk["covariance_ridge"]), float(risk["erc_minimum_weight"])
    cap, leverage_cap = float(risk["weight_cap"]), float(risk["leverage_cap"])
    vol_targets = [float(x) for x in risk["volatility_targets"]]
    db = DATABASE_DIR / "cf2026_project1.duckdb"
    started, clock = datetime.now(), time.perf_counter()
    config_hash = sha256(CONFIG_PATH)
    run_id = f"portfolio_risk_{started:%Y%m%dT%H%M%S}_{config_hash[:8]}"
    run_output_dir = BACKTEST_OUTPUT_DIR / "runs" / run_id
    run_output_dir.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect(str(db))
    try:
        exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='experiment_monthly_strategy_targets'").fetchone()[0]
        if not exists: raise RuntimeError("请先运行 scripts/08_experiments/04_run_weekly_vs_monthly_experiment.py")
        base = con.execute("SELECT rebalance_date,formation_date,asset,score,target_rank FROM experiment_monthly_strategy_targets WHERE strategy='multi_equal_3' ORDER BY rebalance_date,target_rank").fetchdf()
        prices = con.execute("SELECT trade_date date,ts_code asset,close_adj FROM market_data_enriched WHERE trade_date BETWEEN DATE '2019-10-01' AND DATE '2025-12-31' AND exchange IN ('SSE','SZSE') AND market='主板' AND close_adj>0 ORDER BY asset,date").fetchdf()
        prices["date"] = pd.to_datetime(prices["date"])
        returns = prices.pivot(index="date", columns="asset", values="close_adj").pct_change(fill_method=None)
        rows, diags = [], []
        for rebalance, group in base.groupby("rebalance_date", sort=True):
            group = group.sort_values("target_rank")
            assets = group.asset.tolist(); formation = pd.Timestamp(group.formation_date.iloc[0])
            history = returns.loc[returns.index <= formation, assets].tail(lookback)
            complete = [a for a in assets if history[a].notna().sum() >= min_obs]
            fallback = [a for a in assets if a not in complete]
            usable = history[complete]
            covariance = usable.cov(min_periods=min_obs).to_numpy(float) * annual_days
            covariance = (1-shrinkage)*covariance + shrinkage*np.diag(np.diag(covariance)) + np.eye(len(complete))*ridge
            equal = np.repeat(1/len(assets), len(assets))
            valid = len(complete) >= 2 and np.all(np.isfinite(covariance))
            if valid:
                erc, ok_erc = erc_weights(covariance, None, min_weight)
                capped, ok_cap = erc_weights(covariance, cap, min_weight)
            else:
                erc = capped = np.repeat(1/max(len(complete),1), max(len(complete),1)); ok_erc = ok_cap = False
            def expand(core):
                mass = len(fallback)/len(assets)
                mapping = dict(zip(complete, core*(1-mass)))
                mapping.update({a:1/len(assets) for a in fallback})
                return np.array([mapping[a] for a in assets])
            erc_all, capped_all = expand(erc), expand(capped)
            def forecast(weights_all):
                core = np.array([weights_all[assets.index(a)] for a in complete])
                return float(np.sqrt(max(core @ covariance @ core, 0))) if valid else np.nan
            f_equal, f_erc, f_cap = forecast(equal), forecast(erc_all), forecast(capped_all)
            schemes = {"monthly_equal":(equal,1.0,f_equal,False,np.nan),
                       "monthly_risk_parity":(erc_all,1.0,f_erc,ok_erc,rc_error(erc,covariance) if valid else np.nan),
                       "monthly_risk_parity_cap_08":(capped_all,1.0,f_cap,ok_cap,rc_error(capped,covariance) if valid else np.nan)}
            for target in vol_targets:
                scale = min(leverage_cap,target/f_equal) if np.isfinite(f_equal) and f_equal>0 else 1.0
                schemes[f"monthly_vol_target_{int(target*100):02d}"]=(equal,scale,f_equal,False,np.nan)
            scale = min(leverage_cap,.15/f_cap) if np.isfinite(f_cap) and f_cap>0 else 1.0
            schemes["monthly_risk_parity_cap_08_vol_15"]=(capped_all,scale,f_cap,ok_cap,rc_error(capped,covariance) if valid else np.nan)
            for strategy,(base_w,scale,fvol,solver_ok,rcerr) in schemes.items():
                weights=base_w*scale
                for record,weight in zip(group.itertuples(index=False),weights):
                    rows.append(dict(rebalance_date=record.rebalance_date,formation_date=record.formation_date,strategy=strategy,asset=record.asset,score=record.score,target_rank=record.target_rank,target_weight=float(weight)))
                diags.append(dict(rebalance_date=rebalance,formation_date=group.formation_date.iloc[0],strategy=strategy,selected_assets=len(assets),assets_with_sufficient_history=len(complete),forecast_annual_volatility=fvol,target_equity_exposure=float(weights.sum()),target_cash_weight=float(1-weights.sum()),maximum_target_weight=float(weights.max()),erc_solver_success=solver_ok,erc_max_risk_contribution_error=rcerr,history_last_date=history.index.max()))
        targets, diagnostics = pd.DataFrame(rows), pd.DataFrame(diags)
        schedule = base[["rebalance_date","formation_date"]].drop_duplicates().copy()
        rd = pd.to_datetime(schedule.rebalance_date); schedule["period_id"] = rd.dt.year*100+rd.dt.month
        for name,frame in [("strategy_targets",targets),("strategy_rebalance_schedule",schedule),("portfolio_risk_target_diagnostics",diagnostics)]:
            con.register("frame",frame); con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM frame"); con.unregister("frame")
    finally: con.close()
    for script in ["02_run_portfolio_backtest.py","03_analyze_backtest.py"]:
        subprocess.run([sys.executable,str(BACKTEST_DIR/script)],check=True)
    con=duckdb.connect(str(db))
    try:
        for table in RESULT_TABLES: con.execute(f"CREATE OR REPLACE TABLE extension_risk_{table} AS SELECT * FROM {table}")
        con.execute("CREATE OR REPLACE TABLE extension_risk_target_diagnostics AS SELECT * FROM portfolio_risk_target_diagnostics")
        con.execute("""
            CREATE TABLE IF NOT EXISTS research_run_registry (
                run_id VARCHAR PRIMARY KEY,
                experiment VARCHAR NOT NULL,
                started_at TIMESTAMP NOT NULL,
                config_sha256 VARCHAR NOT NULL,
                output_directory VARCHAR NOT NULL
            )
        """)
        con.execute(
            "INSERT INTO research_run_registry VALUES (?, ?, ?, ?, ?)",
            [run_id, "portfolio_risk_extension", started, config_hash, str(run_output_dir)],
        )
        for table in RESULT_TABLES:
            run_table = f"research_run_{table}"
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {run_table} AS "
                f"SELECT CAST(NULL AS VARCHAR) AS run_id, * FROM {table} WHERE FALSE"
            )
            con.execute(f"INSERT INTO {run_table} SELECT ?, * FROM {table}", [run_id])
        for table in RESULT_TABLES: con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM experiment_weekly_{table}")
    finally: con.close()
    # 先冻结本次扩展生成的文件，再恢复基准 CSV，避免实验覆盖正式结果。
    for artifact in sorted(BACKTEST_OUTPUT_DIR.glob("03_*.csv")):
        shutil.copy2(artifact, run_output_dir / artifact.name)
    for script in ["03_analyze_backtest.py", "04_validate_backtest.py"]:
        subprocess.run([sys.executable, str(BACKTEST_DIR / script)], check=True)
    diagnostics.to_csv(OUTPUT_DIR/"01_target_diagnostics.csv",index=False,encoding="utf-8-sig")
    targets.to_csv(OUTPUT_DIR/"01_target_weights.csv",index=False,encoding="utf-8-sig")
    runtime=dict(run_id=run_id,experiment="portfolio_risk_extension",started_at=started.isoformat(timespec="seconds"),finished_at=datetime.now().isoformat(timespec="seconds"),runtime_seconds=round(time.perf_counter()-clock,3),python_executable=sys.executable,database=str(db),config=str(CONFIG_PATH),config_sha256=config_hash,run_output_directory=str(run_output_dir),standard_weekly_tables_restored=True,standard_weekly_csv_restored=True)
    (OUTPUT_DIR/"01_runtime.json").write_text(json.dumps(runtime,ensure_ascii=False,indent=2),encoding="utf-8")
    (run_output_dir/"run_manifest.json").write_text(json.dumps(runtime,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"生成策略数：{targets.strategy.nunique()}；调仓日数：{targets.rebalance_date.nunique()}")
    print("[PASS] 风险拓展已运行并冻结，正式周频表已恢复。")
if __name__=="__main__": main()
