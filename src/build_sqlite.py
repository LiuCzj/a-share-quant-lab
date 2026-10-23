from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_CSV = DATA_DIR / "a_share_daily_2025q1.csv"
INFO_CSV = DATA_DIR / "stock_info.csv"
DB_PATH = DATA_DIR / "market.db"
ARCHIVE_PATH = DATA_DIR / "market.db.gz"

DAILY_COLUMN_MAPPING = {
    "交易日期": "trade_date",
    "股票代码": "stock_code",
    "股票名称": "stock_name",
    "开盘价": "open_price",
    "最高价": "high_price",
    "最低价": "low_price",
    "收盘价": "close_price",
    "前收盘价": "preclose_price",
    "成交量": "volume",
    "成交额": "amount",
    "复权类型": "adjust_flag",
    "换手率": "turnover_rate",
    "交易状态": "trade_status",
    "涨跌幅（%）": "pct_change",
}

INFO_COLUMN_MAPPING = {
    "股票代码": "stock_code",
    "股票名称": "stock_name",
    "上市日期": "list_date",
    "所属行业": "industry_name",
}

PRICE_COLUMNS = ["open_price", "high_price", "low_price", "close_price"]
MARKET_COLUMNS = [
    "preclose_price",
    "volume",
    "amount",
    "turnover_rate",
    "pct_change",
]
TEXT_COLUMNS = ["stock_name", "adjust_flag", "trade_status"]


def _exchange_name(stock_code: object) -> str | None:
    if not isinstance(stock_code, str):
        return None
    if stock_code.startswith("sh."):
        return "上海证券交易所"
    if stock_code.startswith("sz."):
        return "深圳证券交易所"
    return None


def load_daily() -> pd.DataFrame:
    frame = pd.read_csv(
        DAILY_CSV, encoding="utf-8-sig", dtype={"股票代码": "string"}
    )

    missing = set(DAILY_COLUMN_MAPPING) - set(frame.columns)
    if missing:
        raise ValueError(f"行情 CSV 缺少字段：{sorted(missing)}")

    frame = frame.rename(columns=DAILY_COLUMN_MAPPING)
    frame = frame[list(DAILY_COLUMN_MAPPING.values())]

    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.strftime("%Y-%m-%d")
    frame["stock_code"] = frame["stock_code"].astype("string").str.strip()

    for column in TEXT_COLUMNS:
        frame[column] = frame[column].astype("string").str.strip()

    for column in PRICE_COLUMNS + MARKET_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(
            "float64"
        )

    if frame[["trade_date", "stock_code", "stock_name", "trade_status"]].isna().any().any():
        raise ValueError("日期、股票代码、股票名称或交易状态存在缺失。")

    unknown_status = ~frame["trade_status"].isin(["0", "1"])
    if unknown_status.any():
        values = frame.loc[unknown_status, "trade_status"].unique().tolist()
        raise ValueError(f"发现未识别的交易状态：{values}")

    duplicated = frame.duplicated(subset=["trade_date", "stock_code"]).sum()
    if duplicated:
        raise ValueError(f"发现 {duplicated} 条重复主键。")

    tradable = frame["trade_status"].eq("1")
    if frame.loc[tradable, PRICE_COLUMNS].isna().any().any():
        raise ValueError("正常交易记录存在缺失的开盘价/最高价/最低价/收盘价。")

    for column in PRICE_COLUMNS:
        values = frame[column].dropna()
        if (values <= 0).any():
            raise ValueError(f"字段 {column} 存在小于或等于 0 的价格。")

    return frame


def load_info() -> pd.DataFrame:
    frame = pd.read_csv(INFO_CSV, encoding="utf-8-sig", dtype=str)

    missing = set(INFO_COLUMN_MAPPING) - set(frame.columns)
    if missing:
        raise ValueError(f"基础信息 CSV 缺少字段：{sorted(missing)}")

    frame = frame.rename(columns=INFO_COLUMN_MAPPING)
    frame = frame[list(INFO_COLUMN_MAPPING.values())].copy()

    for column in ("stock_code", "stock_name", "industry_name"):
        frame[column] = frame[column].astype("string").str.strip()
        frame[column] = frame[column].replace("", pd.NA)

    frame["list_date"] = pd.to_datetime(
        frame["list_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    if frame["stock_code"].isna().any():
        raise ValueError("股票代码存在缺失值。")

    if frame["stock_code"].duplicated().any():
        raise ValueError("股票代码存在重复值。")

    frame["stock_name"] = frame["stock_name"].fillna("未知名称")
    frame["exchange_name"] = frame["stock_code"].map(_exchange_name)

    return frame.astype(object).where(pd.notna(frame), None)


def write_database(daily: pd.DataFrame, info: pd.DataFrame) -> None:
    temp_path = DB_PATH.with_suffix(".db.tmp")
    if temp_path.exists():
        temp_path.unlink()

    connection = sqlite3.connect(temp_path)
    try:
        daily.to_sql("stock_daily", connection, index=False, chunksize=20000)
        info.to_sql("stock_info", connection, index=False, chunksize=2000)

        cursor = connection.cursor()
        cursor.execute(
            "create index idx_daily_code_date "
            "on stock_daily (stock_code, trade_date)"
        )
        cursor.execute("create index idx_daily_date on stock_daily (trade_date)")
        cursor.execute("create index idx_info_code on stock_info (stock_code)")
        connection.commit()
        cursor.execute("vacuum")
        connection.commit()
        cursor.close()
    finally:
        connection.close()

    os.replace(temp_path, DB_PATH)


def verify() -> None:
    connection = sqlite3.connect(DB_PATH)
    try:
        summary = connection.execute(
            """
            select
                count(*) as record_count,
                count(distinct stock_code) as stock_count,
                count(distinct trade_date) as trading_days,
                min(trade_date) as min_date,
                max(trade_date) as max_date,
                sum(case when trade_status = '1' then 1 else 0 end) as normal_count,
                sum(case when trade_status = '1' then 0 else 1 end) as suspended_count
            from stock_daily
            """
        ).fetchone()

        info_count = connection.execute(
            "select count(*) from stock_info"
        ).fetchone()[0]

        orphan = connection.execute(
            """
            select count(distinct d.stock_code)
            from stock_daily d
            left join stock_info i on i.stock_code = d.stock_code
            where i.stock_code is null
            """
        ).fetchone()[0]

        window_rows = connection.execute(
            """
            select count(*) from (
                select row_number() over (
                    partition by stock_code order by trade_date
                ) as rn
                from stock_daily
                where trade_date between '2025-01-02' and '2025-03-31'
                  and trade_status = '1'
                  and close_price > 0
            )
            """
        ).fetchone()[0]
    finally:
        connection.close()

    size_mb = DB_PATH.stat().st_size / 1024 / 1024

    print("========== SQLite 构建结果 ==========")
    print(f"文件路径：{DB_PATH}")
    print(f"文件大小：{size_mb:.1f} MB")
    print(f"行情记录：{summary[0]:,} 条")
    print(f"股票数量：{summary[1]:,} 只")
    print(f"交易日数：{summary[2]} 天")
    print(f"数据区间：{summary[3]} 至 {summary[4]}")
    print(f"正常交易：{summary[5]:,} 条　停牌：{summary[6]:,} 条")
    print(f"基础信息：{info_count:,} 行")
    print(f"行情中缺基础信息的股票：{orphan:,} 只")
    print(f"窗口函数可用性：返回 {window_rows:,} 行")

    if summary[0] == 0:
        raise RuntimeError("stock_daily 为空，构建失败。")


def write_archive() -> None:
    temp_path = ARCHIVE_PATH.parent / (ARCHIVE_PATH.name + ".tmp")

    with open(DB_PATH, "rb") as source, gzip.open(
        temp_path, "wb", compresslevel=6
    ) as sink:
        shutil.copyfileobj(source, sink, 1024 * 1024)

    os.replace(temp_path, ARCHIVE_PATH)


def main() -> None:
    daily = load_daily()
    info = load_info()

    print(f"行情源文件：{DAILY_CSV}（{len(daily):,} 行）")
    print(f"基础信息源文件：{INFO_CSV}（{len(info):,} 行）")

    write_database(daily, info)
    verify()
    write_archive()

    print(f"部署用压缩包：{ARCHIVE_PATH}")
    print(f"压缩包大小：{ARCHIVE_PATH.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
