"""CF2026 Project 1 的公共配置与辅助函数。"""

from __future__ import annotations

import os
from pathlib import Path

import tushare as ts


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "test_results"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REFERENCE_DIR = RAW_DIR / "reference"
DAILY_DIR = RAW_DIR / "daily"
ADJ_FACTOR_DIR = RAW_DIR / "adj_factor"
STOCK_ST_DIR = RAW_DIR / "stock_st"
SUSPEND_DIR = RAW_DIR / "suspend"
STK_LIMIT_DIR = RAW_DIR / "stk_limit"
NAMECHANGE_DIR = RAW_DIR / "namechange_mainboard"
MANIFEST_DIR = RAW_DIR / "manifests"
DATABASE_DIR = DATA_DIR / "database"
PROCESSED_DIR = DATA_DIR / "processed"
LOG_DIR = PROJECT_ROOT / "logs"
PROCESSING_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "processing"
UNIVERSE_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "universe"
FACTOR_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "factors"
EVALUATION_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "evaluation"
BACKTEST_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "backtest"
DATA_AUDIT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "data_audit"

# 正式评价期不变；下载期增加前后缓冲区，用于滚动因子和未来收益标签。
DOWNLOAD_START_DATE = "20191001"
DOWNLOAD_END_DATE = "20260131"

# 下载控制。REQUEST_INTERVAL_SECONDS=0.15 相当于理论上每分钟不超过400次。
REQUEST_INTERVAL_SECONDS = 0.15
MAX_RETRIES = 5
RETRY_BASE_SECONDS = 2.0

PROJECT_START_DATE = "20200101"
PROJECT_END_DATE = "20251231"

# 单股票快速测试区间。使用完整 2020 年，便于观察复权因子变化。
TEST_START_DATE = "20200101"
TEST_END_DATE = "20201231"
TEST_TS_CODE = "000001.SZ"


def ensure_output_dir() -> Path:
    """创建并返回测试输出目录。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def ensure_data_dirs() -> None:
    """创建下载、日志和数据库目录。"""
    for path in [
        REFERENCE_DIR,
        DAILY_DIR,
        ADJ_FACTOR_DIR,
        STOCK_ST_DIR,
        SUSPEND_DIR,
        STK_LIMIT_DIR,
        NAMECHANGE_DIR,
        MANIFEST_DIR,
        DATABASE_DIR,
        PROCESSED_DIR,
        LOG_DIR,
        PROCESSING_OUTPUT_DIR,
        UNIVERSE_OUTPUT_DIR,
        FACTOR_OUTPUT_DIR,
        EVALUATION_OUTPUT_DIR,
        BACKTEST_OUTPUT_DIR,
        DATA_AUDIT_OUTPUT_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def get_tushare_client():
    """从环境变量读取 Token 并创建 Tushare Pro 客户端。"""
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "未读取到环境变量 TUSHARE_TOKEN。请在 PyCharm 的运行配置中添加它。"
        )
    return ts.pro_api(token)


def print_section(title: str) -> None:
    """打印统一格式的小节标题。"""
    print(f"\n{'=' * 12} {title} {'=' * 12}")
