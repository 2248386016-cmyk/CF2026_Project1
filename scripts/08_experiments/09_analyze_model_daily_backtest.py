"""Select on validation only and report the frozen execution-level test result."""
from __future__ import annotations
import json
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]

def metrics(frame: pd.DataFrame) -> dict:
    ret = frame["daily_return"].astype(float)
    nav = (1 + ret).cumprod()
    years = len(ret) / 242
    return {"total_return": nav.iloc[-1] - 1, "annualized_return": nav.iloc[-1] ** (1 / years) - 1,
            "annualized_volatility": ret.std(ddof=1) * np.sqrt(242),
            "max_drawdown": -(nav / nav.cummax() - 1).min(),
            "sharpe": ret.mean() / ret.std(ddof=1) * np.sqrt(242) if ret.std(ddof=1) else np.nan}

def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/model_baseline.yaml").read_text(encoding="utf-8"))
    con = duckdb.connect(cfg["run"]["source_database"], read_only=True)
    daily = con.execute("SELECT * FROM model_baseline_backtest_daily WHERE date >= DATE '2023-01-01'").fetchdf()
    con.close()
    daily["date"] = pd.to_datetime(daily["date"])
    index = pd.read_parquet(ROOT / "data/model_inputs" / cfg["run"]["run_id"] / "csi300_index_daily.parquet")
    index["date"] = pd.to_datetime(index["trade_date"])
    index = index.sort_values("date"); index["daily_return"] = index["close"].pct_change()
    rows = []
    periods = {"validation": ("2023-01-01", "2024-12-31"), "test": ("2025-01-01", "2025-12-31")}
    for period, (start, end) in periods.items():
        bench = index[index["date"].between(start, end)].dropna(subset=["daily_return"])
        b = metrics(bench); b.update({"period": period, "strategy": "csi300"}); rows.append(b)
        for strategy, frame in daily[daily["date"].between(start, end)].groupby("strategy"):
            value = metrics(frame); value.update({"period": period, "strategy": strategy}); rows.append(value)
    result = pd.DataFrame(rows)
    validation = result[result["period"] == "validation"].copy()
    benchmark = validation.loc[validation["strategy"] == "csi300", "annualized_return"].iloc[0]
    candidates = validation[validation["strategy"] != "csi300"].copy()
    candidates["validation_excess_annualized"] = candidates["annualized_return"] - benchmark
    selected = candidates.sort_values(["validation_excess_annualized", "max_drawdown"], ascending=[False, True]).iloc[0]["strategy"]
    result["selected_on_validation"] = result["strategy"].eq(selected)
    out = ROOT / "outputs/backtest" / cfg["run"]["run_id"]
    result.to_csv(out / "daily_execution_metrics.csv", index=False)
    summary = {"selected_strategy": selected, "selection_rule": "highest validation annualized excess return",
               "validation": result[(result.period == "validation") & result.strategy.isin([selected, "csi300"])].to_dict("records"),
               "test": result[(result.period == "test") & result.strategy.isin([selected, "csi300"])].to_dict("records")}
    (out / "daily_execution_selection.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
