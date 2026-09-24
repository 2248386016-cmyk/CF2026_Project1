"""Point-in-time Ridge/LightGBM baseline on the dynamic CSI 300 universe."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TECHNICAL_FACTORS = [
    "momentum_20", "reversal_5", "low_volatility_20",
    "momentum_60_skip_5", "overnight_reversal_5",
    "amihud_illiquidity_20", "amount_change_5_20",
]
FEATURES = TECHNICAL_FACTORS + ["earnings_yield", "book_to_price", "quality_roe"]


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config/model_baseline.yaml"))
    return parser.parse_args()


def latest_membership(membership: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    membership = membership.copy()
    membership["trade_date"] = pd.to_datetime(membership["trade_date"])
    snapshots = sorted(membership["trade_date"].unique())
    rows = []
    for date in dates:
        eligible = [value for value in snapshots if value <= date.to_datetime64()]
        if not eligible:
            continue
        snapshot = max(eligible)
        frame = membership[membership["trade_date"] == snapshot].copy()
        frame["date"] = date
        frame["asset"] = frame["con_code"]
        frame["membership_snapshot_date"] = pd.Timestamp(snapshot)
        rows.append(frame[["date", "asset", "weight", "membership_snapshot_date"]])
    return pd.concat(rows, ignore_index=True)


def merge_financials(panel: pd.DataFrame, financials: pd.DataFrame) -> pd.DataFrame:
    left = panel.sort_values(["date", "asset"]).copy()
    right = financials.rename(columns={"ts_code": "asset"}).copy()
    right["ann_date"] = pd.to_datetime(right["ann_date"])
    right = right.sort_values(["ann_date", "asset"]).drop_duplicates(
        ["asset", "ann_date"], keep="last"
    )
    return pd.merge_asof(
        left, right[["asset", "ann_date", "end_date", "roe"]],
        left_on="date", right_on="ann_date", by="asset",
        direction="backward", allow_exact_matches=True,
    )


def residualize(group: pd.DataFrame, column: str) -> pd.Series:
    values = group[column].replace([np.inf, -np.inf], np.nan)
    values = values.fillna(values.median())
    lo, hi = values.quantile([0.01, 0.99])
    values = values.clip(lo, hi)
    industries = pd.get_dummies(group["industry"].fillna("UNKNOWN"), drop_first=True, dtype=float)
    design = pd.concat(
        [pd.Series(1.0, index=group.index, name="const"), group["log_mv"], industries.set_index(group.index)],
        axis=1,
    ).astype(float)
    coefficients = np.linalg.lstsq(design.to_numpy(), values.to_numpy(), rcond=None)[0]
    residual = values.to_numpy() - design.to_numpy() @ coefficients
    std = np.std(residual, ddof=1)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=group.index)
    return pd.Series((residual - np.mean(residual)) / std, index=group.index)


def prepare_panel(config: dict) -> pd.DataFrame:
    cache = PROJECT_ROOT / "data/model_inputs" / config["run"]["run_id"]
    membership = pd.read_parquet(cache / "csi300_index_weight.parquet")
    basic = pd.read_parquet(cache / "daily_basic_month_end.parquet").rename(
        columns={"ts_code": "asset", "trade_date": "date"}
    )
    basic["date"] = pd.to_datetime(basic["date"])
    financials = pd.read_parquet(cache / "fina_indicator_history.parquet")
    connection = duckdb.connect(config["run"]["source_database"], read_only=True)
    technical = connection.execute(
        """
        WITH month_ends AS (
          SELECT max(date) AS date FROM factor_values_processed_detail
          WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          GROUP BY year(date), month(date)
        )
        SELECT f.date, f.asset, f.factor, f.zscore_value
        FROM factor_values_processed_detail f JOIN month_ends m USING(date)
        WHERE f.factor IN ({})
        """.format(",".join(["?"] * len(TECHNICAL_FACTORS))),
        [config["run"]["start_date"], config["run"]["test_end"], *TECHNICAL_FACTORS],
    ).fetchdf()
    labels = connection.execute(
        "SELECT date, asset, exit_date_20d, forward_return_20d FROM forward_returns"
    ).fetchdf()
    industries = connection.execute(
        "SELECT ts_code AS asset, industry FROM stock_basic"
    ).fetchdf().drop_duplicates("asset")
    connection.close()
    technical["date"] = pd.to_datetime(technical["date"])
    labels["date"] = pd.to_datetime(labels["date"])
    labels["exit_date_20d"] = pd.to_datetime(labels["exit_date_20d"])
    wide = technical.pivot(index=["date", "asset"], columns="factor", values="zscore_value").reset_index()
    members = latest_membership(membership, sorted(wide["date"].unique()))
    panel = members.merge(wide, on=["date", "asset"], how="inner")
    panel = panel.merge(basic, on=["date", "asset"], how="left").merge(industries, on="asset", how="left")
    panel = merge_financials(panel, financials)
    panel["earnings_yield"] = np.where(panel["pe_ttm"] > 0, 1.0 / panel["pe_ttm"], np.nan)
    panel["book_to_price"] = np.where(panel["pb"] > 0, 1.0 / panel["pb"], np.nan)
    panel["quality_roe"] = panel["roe"]
    panel["log_mv"] = np.log(panel["total_mv"].where(panel["total_mv"] > 0))
    panel = panel.merge(labels, on=["date", "asset"], how="left")
    for feature in FEATURES:
        panel[feature] = panel.groupby("date", group_keys=False).apply(
            lambda frame, name=feature: residualize(frame, name), include_groups=False
        ).reset_index(level=0, drop=True).sort_index()
    panel["target"] = panel["forward_return_20d"] - panel.groupby("date")["forward_return_20d"].transform("mean")
    panel["financial_lag_days"] = (panel["date"] - panel["ann_date"]).dt.days
    return panel.sort_values(["date", "asset"]).reset_index(drop=True)


def model_factory(name: str, params: dict):
    if name == "ridge":
        return Ridge(alpha=params["alpha"])
    return lgb.LGBMRegressor(
        **params, random_state=2026, objective="regression", verbosity=-1,
        n_jobs=-1, subsample=0.8, colsample_bytree=0.8,
    )


def expanding_predictions(panel: pd.DataFrame, model_name: str, params: dict,
                          start: str, end: str) -> pd.DataFrame:
    output = []
    for prediction_date in sorted(panel.loc[panel["date"].between(start, end), "date"].unique()):
        train = panel[
            (panel["exit_date_20d"] < pd.Timestamp(prediction_date))
            & panel["target"].notna()
        ].dropna(subset=FEATURES)
        score = panel[panel["date"] == prediction_date].dropna(subset=FEATURES).copy()
        if train.empty or score.empty:
            continue
        scaler = StandardScaler().fit(train[FEATURES])
        train_x = scaler.transform(train[FEATURES])
        score_x = scaler.transform(score[FEATURES])
        model = model_factory(model_name, params)
        model.fit(train_x, train["target"])
        score["prediction"] = model.predict(score_x)
        score["model"] = model_name
        output.append(score)
    return pd.concat(output, ignore_index=True)


def mean_rank_ic(predictions: pd.DataFrame) -> float:
    values = []
    for _, group in predictions.dropna(subset=["target"]).groupby("date"):
        value = spearmanr(group["prediction"], group["target"]).statistic
        if np.isfinite(value):
            values.append(value)
    return float(np.mean(values)) if values else float("nan")


def simulate(predictions: pd.DataFrame, config: dict, period: str) -> tuple[pd.DataFrame, dict]:
    buy_rate = config["cost"]["buy_rate"]
    sell_rate = config["cost"]["sell_rate"]
    top_n = config["portfolio"]["top_n"]
    previous: dict[str, float] = {}
    nav = 1.0
    rows = []
    for date, group in predictions.groupby("date"):
        selected = group.nlargest(top_n, "prediction").dropna(subset=["forward_return_20d"])
        if selected.empty:
            continue
        weights = {asset: 1.0 / len(selected) for asset in selected["asset"]}
        buys = sum(max(weights.get(a, 0) - previous.get(a, 0), 0) for a in set(weights) | set(previous))
        sells = sum(max(previous.get(a, 0) - weights.get(a, 0), 0) for a in set(weights) | set(previous))
        gross = float(selected["forward_return_20d"].mean())
        cost = buys * buy_rate + sells * sell_rate
        net = gross - cost
        nav *= 1 + net
        rows.append({"date": date, "period": period, "model": selected["model"].iloc[0],
                     "gross_return": gross, "turnover_buy": buys, "turnover_sell": sells,
                     "cost_return": cost, "net_return": net, "nav": nav,
                     "holdings": len(selected)})
        previous = weights
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {}
    years = max((frame["date"].max() - frame["date"].min()).days / 365.25, 1 / 12)
    drawdown = frame["nav"] / frame["nav"].cummax() - 1
    metrics = {
        "period": period, "model": frame["model"].iloc[0], "months": len(frame),
        "total_return": frame["nav"].iloc[-1] - 1,
        "annualized_return": frame["nav"].iloc[-1] ** (1 / years) - 1,
        "max_drawdown": float(-drawdown.min()),
        "annualized_volatility": float(frame["net_return"].std(ddof=1) * math.sqrt(12)),
        "average_monthly_turnover": float((frame["turnover_buy"] + frame["turnover_sell"]).mean()),
        "total_cost_return": float(frame["cost_return"].sum()),
    }
    return frame, metrics


def benchmark_metrics(config: dict, dates: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    cache = PROJECT_ROOT / "data/model_inputs" / config["run"]["run_id"]
    index_daily = pd.read_parquet(cache / "csi300_index_daily.parquet").sort_values("trade_date")
    index_daily["trade_date"] = pd.to_datetime(index_daily["trade_date"])
    index_daily["benchmark_return"] = index_daily["close"].shift(-21) / index_daily["close"].shift(-1) - 1
    lookup = index_daily.set_index("trade_date")["benchmark_return"]
    output, summaries = [], []
    for period, group in dates.groupby("period"):
        frame = group[["date"]].drop_duplicates().sort_values("date").copy()
        frame["period"] = period
        frame["model"] = "csi300_benchmark"
        frame["net_return"] = frame["date"].map(lookup)
        frame = frame.dropna(subset=["net_return"])
        frame["nav"] = (1 + frame["net_return"]).cumprod()
        output.append(frame)
        years = max((frame["date"].max() - frame["date"].min()).days / 365.25, 1 / 12)
        drawdown = frame["nav"] / frame["nav"].cummax() - 1
        summaries.append({
            "period": period, "model": "csi300_benchmark", "months": len(frame),
            "total_return": frame["nav"].iloc[-1] - 1,
            "annualized_return": frame["nav"].iloc[-1] ** (1 / years) - 1,
            "max_drawdown": float(-drawdown.min()),
            "annualized_volatility": float(frame["net_return"].std(ddof=1) * math.sqrt(12)),
            "average_monthly_turnover": 0.0, "total_cost_return": 0.0,
            "rank_ic": np.nan, "params": "{}",
        })
    return pd.concat(output, ignore_index=True), summaries


def main() -> None:
    config = yaml.safe_load(Path(args().config).read_text(encoding="utf-8"))
    output = PROJECT_ROOT / "outputs/backtest" / config["run"]["run_id"]
    output.mkdir(parents=True, exist_ok=True)
    panel = prepare_panel(config)
    if (panel["financial_lag_days"].dropna() < 0).any():
        raise AssertionError("检测到财务公告日未来数据泄漏")
    panel.to_parquet(output / "model_panel.parquet", index=False)

    candidates = [("ridge", {"alpha": value}) for value in config["model"]["ridge_alphas"]]
    candidates += [("lightgbm", value) for value in config["model"]["lightgbm_candidates"]]
    selection_rows, validation_predictions = [], {}
    for model_name, params in candidates:
        prediction = expanding_predictions(
            panel, model_name, params,
            str(pd.Timestamp(config["run"]["train_end"]) + pd.Timedelta(days=1))[:10],
            config["run"]["validation_end"],
        )
        ic = mean_rank_ic(prediction)
        key = f"{model_name}:{json.dumps(params, sort_keys=True)}"
        validation_predictions[key] = prediction
        selection_rows.append({"model": model_name, "params": json.dumps(params, sort_keys=True),
                               "validation_rank_ic": ic})
    selection = pd.DataFrame(selection_rows)
    selection.to_csv(output / "model_selection.csv", index=False)
    best = selection.sort_values("validation_rank_ic", ascending=False).groupby("model").head(1)

    all_predictions, all_nav, metrics = [], [], []
    for row in best.itertuples(index=False):
        params = json.loads(row.params)
        key = f"{row.model}:{json.dumps(params, sort_keys=True)}"
        validation = validation_predictions[key]
        test = expanding_predictions(
            panel, row.model, params,
            str(pd.Timestamp(config["run"]["validation_end"]) + pd.Timedelta(days=1))[:10],
            config["run"]["test_end"],
        )
        validation["period"] = "validation"
        test["period"] = "test"
        all_predictions.extend([validation, test])
        for name, frame in [("validation", validation), ("test", test)]:
            nav, summary = simulate(frame, config, name)
            all_nav.append(nav)
            summary["rank_ic"] = mean_rank_ic(frame)
            summary["params"] = row.params
            metrics.append(summary)
    prediction_frame = pd.concat(all_predictions, ignore_index=True)
    benchmark_nav, benchmark_summaries = benchmark_metrics(
        config, prediction_frame[["date", "period"]]
    )
    all_nav.append(benchmark_nav)
    metrics.extend(benchmark_summaries)
    prediction_frame.to_csv(output / "predictions.csv", index=False)
    pd.concat(all_nav).to_csv(output / "monthly_nav.csv", index=False)
    pd.DataFrame(metrics).to_csv(output / "performance_metrics.csv", index=False)
    audit = {
        "run_id": config["run"]["run_id"], "rows": len(panel),
        "dates": int(panel["date"].nunique()), "assets": int(panel["asset"].nunique()),
        "features": FEATURES, "negative_financial_lags": int((panel["financial_lag_days"] < 0).sum()),
        "membership_snapshot_after_signal": int((panel["membership_snapshot_date"] > panel["date"]).sum()),
    }
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(pd.DataFrame(metrics).to_string(index=False))
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
