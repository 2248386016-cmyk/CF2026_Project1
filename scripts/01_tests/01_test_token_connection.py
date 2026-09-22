"""01 - 验证 Tushare Token 与最基础接口是否可用。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import get_tushare_client, print_section


def main() -> None:
    print_section("01 Token 连通性测试")
    pro = get_tushare_client()

    result = pro.daily(
        ts_code="000001.SZ",
        start_date="20200101",
        end_date="20200131",
        fields="ts_code,trade_date,open,high,low,close,vol,amount",
    )

    if result.empty:
        raise AssertionError("Token 调用成功，但日线接口返回空数据。")

    required = {
        "ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"
    }
    missing = required - set(result.columns)
    if missing:
        raise AssertionError(f"日线结果缺少字段：{sorted(missing)}")

    print(result.head())
    print(f"返回行数：{len(result)}")
    print("[PASS] 环境变量、Token 和 daily 接口均正常。")


if __name__ == "__main__":
    main()
