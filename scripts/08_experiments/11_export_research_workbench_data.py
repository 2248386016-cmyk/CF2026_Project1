"""Export browser-ready evidence with the base three-factor study as default."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=6))


def normalize_path(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values("date").copy()
    frame["nav"] = frame["nav"] / frame["nav"].iloc[0]
    return frame.iloc[::3][["date", "nav"]]


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config/model_baseline.yaml").read_text(encoding="utf-8"))
    database = Path(cfg["run"]["source_database"])
    con = duckdb.connect(str(database), read_only=True)

    table_map = {
        "weekly_equal": "experiment_weekly_backtest_daily",
        "monthly_equal": "experiment_monthly_backtest_daily",
        "vol_target_15": "extension_risk_backtest_daily",
    }
    paths: dict[str, list[dict]] = {}
    for name, table in table_map.items():
        strategy = "monthly_vol_target_15" if name == "vol_target_15" else "multi_equal_3"
        frame = con.execute(
            f"SELECT date, nav FROM {table} WHERE strategy=? ORDER BY date", [strategy]
        ).fetchdf()
        frame["date"] = pd.to_datetime(frame["date"])
        paths[name] = records(normalize_path(frame))

    model_out = ROOT / "outputs/backtest" / cfg["run"]["run_id"]
    model_daily = pd.read_csv(model_out / "regime_overlay_daily.csv", parse_dates=["date"])
    for name, column in (("regime_overlay", "strategy_return"), ("csi300", "benchmark_return")):
        path = model_daily[["date", column]].copy()
        path["nav"] = (1 + path[column]).cumprod()
        paths[name] = records(normalize_path(path))

    period = pd.read_csv(ROOT / "outputs/backtest/03_period_performance_metrics.csv")
    base = period[period.strategy.eq("multi_equal_3")].copy()
    base["period"] = base.sample_period.map({"validation_2024": "validation", "test_2025": "test"})
    base = base[base.period.notna()]
    metrics = []
    for strategy in ("weekly_equal", "monthly_equal"):
        source = base if strategy == "weekly_equal" else pd.read_csv(
            ROOT / "outputs/backtest/weekly_vs_monthly/02_period_metrics.csv"
        ).query("strategy == 'multi_equal_3' and frequency == 'monthly'")
        for _, row in source.iterrows():
            sample = str(row.get("sample_period", ""))
            label = row.get("period") or ({"validation_2024": "validation", "test_2025": "test"}.get(sample))
            if label in {"validation", "test"}:
                metrics.append({"period": label, "strategy": strategy,
                    "total_return": row["period_return"], "annualized_return": row["annualized_return"],
                    "max_drawdown": row["max_drawdown"], "sharpe": row["annualized_sharpe"]})

    model_metrics = pd.read_csv(model_out / "regime_overlay_metrics.csv")
    metrics.extend(records(model_metrics))
    risk = pd.read_csv(ROOT / "outputs/backtest/portfolio_risk_extension/02_key_results.csv").query(
        "strategy == 'monthly_vol_target_15'"
    ).iloc[0]
    for label in ("validation", "test"):
        monthly = next(x for x in metrics if x["strategy"] == "monthly_equal" and x["period"] == label)
        metrics.append({**monthly, "strategy": "vol_target_15",
            "annualized_return": float(risk.annualized_return), "max_drawdown": float(risk.max_drawdown),
            "sharpe": float(risk.annualized_sharpe)})

    trades = con.execute("""
        SELECT date_trunc('month',date) AS month_start, count(*) AS trades,
               sum(gross_amount) AS gross_amount, sum(cost) AS cost
        FROM experiment_monthly_backtest_trades
        WHERE strategy='multi_equal_3' GROUP BY 1 ORDER BY 1
    """).fetchdf()
    con.close()

    payload = {
        "meta": {"runId": "base_three_factor_v1", "universe": "动态沪深主板A股",
                 "selectedStrategy": "月频三因子Top20", "generatedFrom": "audited local outputs"},
        "metrics": metrics,
        "paths": paths,
        "benchmarkMap": {"monthly_equal": "weekly_equal", "weekly_equal": "monthly_equal",
                         "vol_target_15": "monthly_equal", "regime_overlay": "csi300", "csi300": "regime_overlay"},
        "factors": records(pd.read_csv(ROOT / "outputs/evaluation/02_ic_summary.csv")),
        "trades": records(trades),
    }
    target = ROOT / "web/dashboard-data.js"
    target.write_text("window.DASHBOARD_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(target, target.stat().st_size)


if __name__ == "__main__":
    main()
