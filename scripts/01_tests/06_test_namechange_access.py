"""06 - 测试 Tushare namechange（股票曾用名）接口权限与字段。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_config import ensure_output_dir, get_tushare_client, print_section


TEST_TS_CODE = "000001.SZ"
EXPECTED_COLUMNS = {
    "ts_code",
    "name",
    "start_date",
    "end_date",
    "ann_date",
    "change_reason",
}


def main() -> None:
    print_section("06 namechange 权限测试")
    pro = get_tushare_client()
    output_dir = ensure_output_dir()

    try:
        data = pro.namechange(
            ts_code=TEST_TS_CODE,
            fields="ts_code,name,start_date,end_date,ann_date,change_reason",
        )
    except Exception as exc:
        message = str(exc)
        permission_words = ["没有接口", "没有权限", "权限不足", "积分不足"]
        if any(word in message for word in permission_words):
            print(f"[NO ACCESS] namechange 接口无权限：{message}")
            raise SystemExit(2) from exc
        print(f"[FAILED] namechange 调用失败：{message}")
        raise

    missing_columns = EXPECTED_COLUMNS - set(data.columns)
    if missing_columns:
        raise AssertionError(f"namechange 结果缺少字段：{sorted(missing_columns)}")

    if data.empty:
        print(
            f"[WARNING] 接口调用成功，但 {TEST_TS_CODE} 返回空数据。"
            "这能说明接口可调用，但还不能证明历史名称覆盖完整。"
        )
        return

    for column in ["start_date", "end_date", "ann_date"]:
        data[column] = pd.to_datetime(
            data[column],
            format="%Y%m%d",
            errors="coerce",
        )

    data = data.sort_values(
        ["ts_code", "start_date"],
        na_position="last",
    ).reset_index(drop=True)

    # 这里只识别样本返回值，不把测试结果当作完整 ST 历史。
    data["name_contains_st"] = data["name"].astype(str).str.upper().str.contains(
        "ST", regex=False, na=False
    )

    output_file = output_dir / "06_namechange_000001_sz_sample.csv"
    data.to_csv(output_file, index=False, encoding="utf-8-sig")

    print(f"测试股票：{TEST_TS_CODE}")
    print(f"返回记录数：{len(data)}")
    print(f"名称含 ST 的样本记录数：{int(data['name_contains_st'].sum())}")
    print("\n返回数据：")
    print(data.to_string(index=False))
    print(f"\n样本输出：{output_file}")
    print("[PASS] namechange 接口可访问，字段检查通过。")
    print(
        "[NEXT] 下一步可按全部研究股票下载历史名称，"
        "再用名称生效起止日期构造每日 ST 状态。"
    )


if __name__ == "__main__":
    main()
