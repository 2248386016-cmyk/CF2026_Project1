"""02 - 在停牌、涨跌停和交易费约束下运行单因子及多因子组合回测。"""

from __future__ import annotations

import math
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import DATABASE_DIR, ensure_data_dirs, print_section


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets-table", default="strategy_targets")
    parser.add_argument("--output-prefix", default="")
    parser.add_argument("--database", default=str(DATABASE_DIR / "cf2026_project1.duckdb"))
    return parser.parse_args()


def main() -> None:
    print_section("02 运行正式组合回测")
    ensure_data_dirs()
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "backtest_config.yaml").read_text(encoding="utf-8")
    )
    initial_capital = float(config["portfolio"]["initial_capital"])
    buy_rate = float(config["cost"]["buy_rate"])
    sell_rate = float(config["cost"]["sell_rate"])
    delist_recovery_rate = float(config["cost"]["delist_recovery_rate"])
    start_date = config["research"]["start_date"]
    end_date = config["research"]["end_date"]

    cli = parse_args()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cli.targets_table):
        raise ValueError("targets-table 不是安全的 SQL 标识符")
    if not re.fullmatch(r"[A-Za-z0-9_]*", cli.output_prefix):
        raise ValueError("output-prefix 不是安全的 SQL 标识符前缀")
    connection = duckdb.connect(cli.database)
    try:
        dates = [row[0] for row in connection.execute(
            """
            SELECT DISTINCT date FROM factor_panel
            WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            ORDER BY date
            """, [start_date, end_date]
        ).fetchall()]
        strategies = [row[0] for row in connection.execute(
            f"SELECT DISTINCT strategy FROM {cli.targets_table} ORDER BY strategy"
        ).fetchall()]
        delist_dates = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT ts_code, delist_date FROM stock_basic_standardized WHERE delist_date IS NOT NULL"
            ).fetchall()
        }
        target_rows = connection.execute(f"SELECT * FROM {cli.targets_table}").fetchdf()
        targets: dict[tuple[object, str], dict[str, float]] = {}
        for (date, strategy), frame in target_rows.groupby(["rebalance_date", "strategy"]):
            normalized_date = pd.Timestamp(date).date()
            targets[(normalized_date, strategy)] = dict(zip(frame["asset"], frame["target_weight"]))

        cash = {strategy: initial_capital for strategy in strategies}
        holdings: dict[str, dict[str, float]] = {strategy: {} for strategy in strategies}
        last_prices: dict[str, float] = {}
        previous_nav = {strategy: initial_capital for strategy in strategies}
        nav_records: list[dict] = []
        trade_records: list[dict] = []
        position_records: list[dict] = []

        for date in dates:
            market = connection.execute(
                """
                SELECT ts_code AS asset, open_adj, close_adj,
                       COALESCE(is_suspended, FALSE) AS is_suspended,
                       COALESCE(has_zero_volume, FALSE) AS has_zero_volume,
                       COALESCE(is_open_at_up_limit, FALSE) AS is_open_at_up_limit,
                       COALESCE(is_open_at_down_limit, FALSE) AS is_open_at_down_limit
                FROM market_data_enriched
                WHERE trade_date = ?
                  AND exchange IN ('SSE', 'SZSE')
                """,
                [date],
            ).fetchdf()
            market_map = market.set_index("asset").to_dict("index") if not market.empty else {}
            old_last_prices = last_prices.copy()
            for row in market.itertuples(index=False):
                if row.close_adj is not None and math.isfinite(float(row.close_adj)) and row.close_adj > 0:
                    last_prices[row.asset] = float(row.close_adj)

            for strategy in strategies:
                day_buy = day_sell = day_cost = 0.0
                day_writeoff = 0.0
                blocked_buys = blocked_sells = 0
                is_rebalance = (date, strategy) in targets

                # 若股票已退市且此前因限制无法卖出，不得继续用最后价格虚增净值。
                for asset in list(holdings[strategy]):
                    delist_date = delist_dates.get(asset)
                    if delist_date is None or date <= delist_date:
                        continue
                    units = holdings[strategy].pop(asset)
                    reference_price = old_last_prices.get(asset) or last_prices.get(asset) or 0.0
                    stale_value = units * reference_price
                    recovery = stale_value * delist_recovery_rate
                    cash[strategy] += recovery
                    day_writeoff += stale_value - recovery
                    trade_records.append({
                        "date": date, "strategy": strategy, "asset": asset,
                        "side": "DELIST_WRITE_OFF", "price": reference_price,
                        "units": units, "gross_amount": recovery,
                        "cost": 0.0, "blocked": False,
                    })

                def open_price(asset: str) -> float | None:
                    row = market_map.get(asset)
                    if row and row["open_adj"] is not None and row["open_adj"] > 0:
                        return float(row["open_adj"])
                    return old_last_prices.get(asset) or last_prices.get(asset)

                pre_trade_nav = cash[strategy]
                for asset, units in holdings[strategy].items():
                    price = open_price(asset)
                    if price is not None:
                        pre_trade_nav += units * price

                if is_rebalance:
                    desired_weights = targets[(date, strategy)]

                    # 先卖出；跌停、停牌或无开盘价时保留持仓。
                    for asset in list(holdings[strategy]):
                        units = holdings[strategy][asset]
                        price = open_price(asset)
                        current_value = units * price if price is not None else 0.0
                        desired_value = pre_trade_nav * desired_weights.get(asset, 0.0)
                        sell_value = max(0.0, current_value - desired_value)
                        if sell_value <= 1e-10:
                            continue
                        row = market_map.get(asset)
                        can_sell = bool(
                            row and row["open_adj"] is not None and row["open_adj"] > 0
                            and not row["is_suspended"] and not row["has_zero_volume"]
                            and not row["is_open_at_down_limit"]
                        )
                        if not can_sell:
                            blocked_sells += 1
                            continue
                        sell_units = min(units, sell_value / float(row["open_adj"]))
                        gross = sell_units * float(row["open_adj"])
                        cost = gross * sell_rate
                        holdings[strategy][asset] -= sell_units
                        if holdings[strategy][asset] <= 1e-12:
                            del holdings[strategy][asset]
                        cash[strategy] += gross - cost
                        day_sell += gross
                        day_cost += cost
                        trade_records.append({
                            "date": date, "strategy": strategy, "asset": asset,
                            "side": "SELL", "price": float(row["open_adj"]),
                            "units": sell_units, "gross_amount": gross,
                            "cost": cost, "blocked": False,
                        })

                    # 再买入；涨停、停牌或无开盘价时不成交。
                    needs: list[tuple[str, float, float]] = []
                    for asset, weight in desired_weights.items():
                        row = market_map.get(asset)
                        can_buy = bool(
                            row and row["open_adj"] is not None and row["open_adj"] > 0
                            and not row["is_suspended"] and not row["has_zero_volume"]
                            and not row["is_open_at_up_limit"]
                        )
                        if not can_buy:
                            blocked_buys += 1
                            continue
                        price = float(row["open_adj"])
                        current_value = holdings[strategy].get(asset, 0.0) * price
                        need = max(0.0, pre_trade_nav * weight - current_value)
                        if need > 1e-10:
                            needs.append((asset, price, need))
                    total_need = sum(item[2] for item in needs)
                    scale = min(1.0, cash[strategy] / ((1.0 + buy_rate) * total_need)) if total_need > 0 else 0.0
                    for asset, price, need in needs:
                        gross = need * scale
                        units = gross / price
                        cost = gross * buy_rate
                        holdings[strategy][asset] = holdings[strategy].get(asset, 0.0) + units
                        cash[strategy] -= gross + cost
                        day_buy += gross
                        day_cost += cost
                        trade_records.append({
                            "date": date, "strategy": strategy, "asset": asset,
                            "side": "BUY", "price": price, "units": units,
                            "gross_amount": gross, "cost": cost, "blocked": False,
                        })

                close_nav = cash[strategy]
                values: dict[str, float] = {}
                for asset, units in holdings[strategy].items():
                    price = last_prices.get(asset) or old_last_prices.get(asset)
                    if price is not None:
                        values[asset] = units * price
                        close_nav += values[asset]

                daily_return = close_nav / previous_nav[strategy] - 1 if previous_nav[strategy] > 0 else 0.0
                turnover = (day_buy + day_sell) / pre_trade_nav if pre_trade_nav > 0 else 0.0
                nav_records.append({
                    "date": date, "strategy": strategy, "nav": close_nav,
                    "daily_return": daily_return, "cash": cash[strategy],
                    "holdings_count": len(holdings[strategy]),
                    "is_rebalance": is_rebalance, "buy_amount": day_buy,
                    "sell_amount": day_sell, "turnover": turnover,
                    "transaction_cost": day_cost,
                    "delist_writeoff": day_writeoff,
                    "blocked_buys": blocked_buys, "blocked_sells": blocked_sells,
                })
                for asset, value in values.items():
                    position_records.append({
                        "date": date, "strategy": strategy, "asset": asset,
                        "units": holdings[strategy][asset],
                        "close_price": last_prices.get(asset) or old_last_prices.get(asset),
                        "market_value": value,
                        "weight": value / close_nav if close_nav > 0 else 0.0,
                    })
                previous_nav[strategy] = close_nav

        nav_frame = pd.DataFrame(nav_records)
        trades_frame = pd.DataFrame(trade_records)
        positions_frame = pd.DataFrame(position_records)
        if trades_frame.empty:
            raise AssertionError("回测未产生任何交易，请检查调仓日与目标持仓日期类型。")
        if positions_frame.empty:
            raise AssertionError("回测未产生任何持仓。")
        nav_frame = nav_frame.sort_values(["strategy", "date"])
        nav_frame["cumulative_transaction_cost"] = nav_frame.groupby("strategy")["transaction_cost"].cumsum()
        nav_frame["cumulative_turnover"] = nav_frame.groupby("strategy")["turnover"].cumsum()
        for name, frame in [
            (f"{cli.output_prefix}backtest_daily", nav_frame),
            (f"{cli.output_prefix}backtest_trades", trades_frame),
            (f"{cli.output_prefix}backtest_positions", positions_frame),
        ]:
            connection.register("temporary_frame", frame)
            connection.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM temporary_frame")
            connection.unregister("temporary_frame")
        print(nav_frame.groupby("strategy").agg(
            first_date=("date", "min"), last_date=("date", "max"),
            final_nav=("nav", "last"), total_cost=("transaction_cost", "sum"),
            total_turnover=("turnover", "sum"), blocked_buys=("blocked_buys", "sum"),
            blocked_sells=("blocked_sells", "sum"), delist_writeoff=("delist_writeoff", "sum"),
        ).to_string())
        print("[PASS] 每日净值、持仓和成交记录已生成。")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
