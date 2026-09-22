"""03 - 合并复权因子、计算固定参考日调整价格并进行质量检查。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import (
    TEST_END_DATE,
    TEST_START_DATE,
    TEST_TS_CODE,
    ensure_output_dir,
    get_tushare_client,
    print_section,
)


def main() -> None:
    print_section("03 复权因子测试")
    pro = get_tushare_client()
    output_dir = ensure_output_dir()

    daily = pro.daily(
        ts_code=TEST_TS_CODE,
        start_date=TEST_START_DATE,
        end_date=TEST_END_DATE,
        fields=(
            "ts_code,trade_date,open,high,low,close,pre_close,"
            "change,pct_chg,vol,amount"
        ),
    )
    adj = pro.adj_factor(
        ts_code=TEST_TS_CODE,
        start_date=TEST_START_DATE,
        end_date=TEST_END_DATE,
    )

    if daily.empty or adj.empty:
        raise AssertionError("日线行情或复权因子为空。")

    for frame in (daily, adj):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")

    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    adj = adj.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    data = daily.merge(
        adj,
        on=["ts_code", "trade_date"],
        how="left",
        validate="one_to_one",
    )

    missing_adj = int(data["adj_factor"].isna().sum())
    if missing_adj:
        raise AssertionError(f"存在 {missing_adj} 行缺失复权因子。")

    reference_date = data["trade_date"].max()
    reference_factor = data.loc[
        data["trade_date"].eq(reference_date), "adj_factor"
    ].iloc[0]

    for column in ["open", "high", "low", "close"]:
        data[f"{column}_adj"] = (
            data[column] * data["adj_factor"] / reference_factor
        )

    previous_factor = data["adj_factor"].shift(1)
    data["adj_factor_changed"] = (
        data["adj_factor"].ne(previous_factor) & previous_factor.notna()
    )

    changes = data.loc[
        data["adj_factor_changed"],
        ["trade_date", "close", "adj_factor", "close_adj"],
    ]

    reference_close = data.loc[
        data["trade_date"].eq(reference_date), ["close", "close_adj"]
    ].iloc[0]
    if abs(reference_close["close"] - reference_close["close_adj"]) > 1e-10:
        raise AssertionError("参考日的原始收盘价与调整收盘价不一致。")

    print(f"日线行数：{len(daily)}")
    print(f"复权因子行数：{len(adj)}")
    print(f"参考日期：{reference_date.date()}")
    print(f"参考日复权因子：{reference_factor}")
    print(f"复权因子实际变化次数：{len(changes)}")
    print("\n复权因子变化记录：")
    print(changes.to_string(index=False) if not changes.empty else "无变化")

    output_file = output_dir / "03_adjusted_000001_sz_2020.csv"
    data.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"输出文件：{output_file}")
    print("[PASS] 复权因子合并和调整价格计算通过。")


if __name__ == "__main__":
    main()
