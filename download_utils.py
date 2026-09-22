"""数据下载阶段共用的重试、原子写入和日志函数。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from project_config import MAX_RETRIES, REQUEST_INTERVAL_SECONDS, RETRY_BASE_SECONDS


def call_with_retry(description: str, function: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    """调用 Tushare 接口；失败时指数退避重试。"""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = function()
            time.sleep(REQUEST_INTERVAL_SECONDS)
            return result
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            # 权限或积分不足属于永久错误，等待和重试不会改变结果。
            permanent_error_words = [
                "没有接口",
                "没有权限",
                "权限不足",
                "积分不足",
                "permission denied",
                "no permission",
                "privilege",
            ]
            if any(word in message for word in permanent_error_words):
                raise RuntimeError(f"{description} 永久权限错误：{exc}") from exc
            if attempt == MAX_RETRIES:
                break
            wait_seconds = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            print(
                f"[RETRY] {description} 第 {attempt} 次失败：{exc}；"
                f"{wait_seconds:.1f} 秒后重试。"
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"{description} 连续 {MAX_RETRIES} 次失败：{last_error}") from last_error


def save_parquet_atomic(data: pd.DataFrame, destination: Path) -> None:
    """先写临时文件并回读，成功后原子替换正式文件。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    data.to_parquet(temporary, index=False, engine="pyarrow")
    check = pd.read_parquet(temporary, engine="pyarrow")
    if len(check) != len(data):
        temporary.unlink(missing_ok=True)
        raise IOError(
            f"Parquet 回读行数不一致：写入 {len(data)}，回读 {len(check)}"
        )
    os.replace(temporary, destination)


def parquet_is_valid(path: Path, expected_trade_date: str | None = None) -> bool:
    """检查已存在的 Parquet 是否可读取且日期符合预期。"""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        frame = pd.read_parquet(path, engine="pyarrow")
    except Exception:
        return False
    if expected_trade_date and not frame.empty and "trade_date" in frame.columns:
        values = frame["trade_date"].astype(str).str.replace("-", "", regex=False).unique()
        return len(values) == 1 and values[0] == expected_trade_date
    return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def append_jsonl(path: Path, record: dict) -> None:
    """以 JSON Lines 追加下载事件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("recorded_at", datetime.now().isoformat(timespec="seconds"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
