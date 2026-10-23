from __future__ import annotations

import gzip
import os
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)

CACHE_TTL = 1800
SQLITE_PATH = PROJECT_ROOT / "data" / "market.db"
SQLITE_ARCHIVE_PATH = PROJECT_ROOT / "data" / "market.db.gz"
UNKNOWN_INDUSTRY = "未分类"
TRADABLE_STATUS = "1"

_INDUSTRY_PATTERN = re.compile(r"^([A-Za-z]\d{2})\s*(.+)$")


class DataUnavailableError(RuntimeError):
    pass


def _as_int(value: object) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


def split_industry_name(raw: object) -> tuple[str, str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "", UNKNOWN_INDUSTRY

    text_value = str(raw).strip()
    if not text_value:
        return "", UNKNOWN_INDUSTRY

    matched = _INDUSTRY_PATTERN.match(text_value)
    if matched:
        return matched.group(1), matched.group(2).strip()

    return "", text_value


def _backend() -> str:
    explicit = os.getenv("DB_BACKEND", "").strip().lower()
    if explicit in {"sqlite", "mysql"}:
        return explicit
    if os.getenv("DATABASE_URL", "").strip():
        return "mysql"
    if os.getenv("DB_HOST", "").strip() and os.getenv("DB_USER", "").strip():
        return "mysql"
    return "sqlite"


@st.cache_resource(show_spinner=False)
def _materialize_sqlite(archive: Path) -> Path:
    candidates = (
        archive.with_name("market.db"),
        Path(tempfile.gettempdir()) / "a_share_market.db",
    )

    for target in candidates:
        try:
            if not target.exists():
                with gzip.open(archive, "rb") as source, open(
                    target, "wb"
                ) as sink:
                    shutil.copyfileobj(source, sink, 1024 * 1024)
            return target
        except OSError:
            continue

    raise DataUnavailableError(f"无法解压 SQLite 数据文件：{archive}")


def _sqlite_source() -> Path:
    configured = os.getenv("SQLITE_PATH", "").strip()

    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if not path.exists():
            raise DataUnavailableError(f"SQLITE_PATH 指向的文件不存在：{path}")
        return path

    if SQLITE_PATH.exists():
        return SQLITE_PATH

    if SQLITE_ARCHIVE_PATH.exists():
        return _materialize_sqlite(SQLITE_ARCHIVE_PATH)

    raise DataUnavailableError(
        "未找到 SQLite 数据文件。请运行 src/build_sqlite.py 生成 "
        "data/market.db，或配置 DATABASE_URL 连接 MySQL。"
    )


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    if _backend() == "mysql":
        database_url = os.getenv("DATABASE_URL", "").strip()

        if not database_url:
            database_url = URL.create(
                drivername="mysql+pymysql",
                username=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "3306")),
                database=os.getenv("DB_NAME", "a_share_research"),
                query={"charset": "utf8mb4"},
            )

        return create_engine(
            database_url, pool_pre_ping=True, pool_recycle=1800
        )

    return create_engine(
        f"sqlite:///{_sqlite_source().as_posix()}",
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )


def _query_params(**values: object) -> dict:
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in values.items()
    }


def check_connection() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("select 1"))


@st.cache_data(ttl=CACHE_TTL, max_entries=8, show_spinner=False)
def load_meta() -> dict:
    sql = text("""
        select
            min(trade_date) as min_date,
            max(trade_date) as max_date,
            count(*) as record_count,
            count(distinct stock_code) as stock_count,
            count(distinct trade_date) as trading_days,
            sum(case when trade_status = '1' then 1 else 0 end) as normal_count,
            sum(case when trade_status = '1' then 0 else 1 end) as suspended_count
        from stock_daily
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(sql, conn)

    if frame.empty or pd.isna(frame.loc[0, "min_date"]):
        raise DataUnavailableError("stock_daily 表为空，请先导入行情数据。")

    row = frame.iloc[0]

    return {
        "min_date": pd.to_datetime(row["min_date"]).date(),
        "max_date": pd.to_datetime(row["max_date"]).date(),
        "record_count": _as_int(row["record_count"]),
        "stock_count": _as_int(row["stock_count"]),
        "trading_days": _as_int(row["trading_days"]),
        "normal_count": _as_int(row["normal_count"]),
        "suspended_count": _as_int(row["suspended_count"]),
    }


@st.cache_data(ttl=CACHE_TTL, max_entries=8, show_spinner=False)
def load_trading_dates() -> list:
    sql = text("""
        select distinct trade_date
        from stock_daily
        order by trade_date
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(sql, conn)

    if frame.empty:
        return []

    return [pd.to_datetime(value).date() for value in frame["trade_date"]]


@st.cache_data(ttl=CACHE_TTL, max_entries=32, show_spinner=False)
def load_market_daily(start_date, end_date) -> pd.DataFrame:
    sql = text("""
        select
            trade_date,
            sum(case when trade_status = '1' then amount else 0 end)
                / 100000000.0 as amount_yi,
            sum(case when trade_status = '1' and pct_change > 0 then 1 else 0 end)
                as up_count,
            sum(case when trade_status = '1' and pct_change < 0 then 1 else 0 end)
                as down_count,
            sum(case when trade_status = '1' and pct_change = 0 then 1 else 0 end)
                as flat_count,
            sum(case when trade_status = '1' then 1 else 0 end)
                as trading_count,
            avg(case when trade_status = '1' then pct_change end)
                as avg_pct_change
        from stock_daily
        where trade_date between :start_date and :end_date
        group by trade_date
        order by trade_date
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(
            sql,
            conn,
            params=_query_params(start_date=start_date, end_date=end_date),
        )

    if frame.empty:
        return frame

    frame["trade_date"] = pd.to_datetime(frame["trade_date"])

    numeric_columns = [
        "amount_yi",
        "up_count",
        "down_count",
        "flat_count",
        "trading_count",
        "avg_pct_change",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame[numeric_columns] = frame[numeric_columns].fillna(0.0)

    frame["up_ratio"] = (
        frame["up_count"]
        .div(frame["trading_count"].replace(0, pd.NA))
        .mul(100)
        .fillna(0.0)
    )
    frame["amount_ma5"] = frame["amount_yi"].rolling(5, min_periods=1).mean()

    return frame


@st.cache_data(ttl=CACHE_TTL, max_entries=8, show_spinner=False)
def load_stock_list() -> pd.DataFrame:
    sql = text("""
        select
            stock_code,
            stock_name,
            exchange_name,
            industry_name
        from stock_info
        order by stock_code
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(sql, conn)

    if frame.empty:
        return frame

    frame["stock_code"] = frame["stock_code"].astype(str).str.strip()
    frame["stock_name"] = (
        frame["stock_name"].fillna("未知名称").astype(str).str.strip()
    )
    frame["exchange_name"] = (
        frame["exchange_name"].fillna("未知交易所").astype(str).str.strip()
    )

    cleaned = frame["industry_name"].map(split_industry_name)
    frame["industry_code"] = [item[0] for item in cleaned]
    frame["industry_label"] = [item[1] for item in cleaned]

    frame["display_name"] = (
        frame["stock_name"] + "（" + frame["stock_code"] + "）"
    )

    return frame


@st.cache_data(ttl=CACHE_TTL, max_entries=64, show_spinner=False)
def load_stock_daily(stock_code: str, start_date, end_date) -> pd.DataFrame:
    sql = text("""
        select
            trade_date,
            open_price,
            high_price,
            low_price,
            close_price,
            preclose_price,
            volume,
            amount,
            turnover_rate,
            pct_change,
            trade_status
        from stock_daily
        where stock_code = :stock_code
          and trade_date between :start_date and :end_date
        order by trade_date
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(
            sql,
            conn,
            params=_query_params(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
            ),
        )

    if frame.empty:
        return frame

    frame["trade_date"] = pd.to_datetime(frame["trade_date"])

    numeric_columns = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "preclose_price",
        "volume",
        "amount",
        "turnover_rate",
        "pct_change",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["is_tradable"] = (
        frame["trade_status"].astype(str).str.strip().eq(TRADABLE_STATUS)
    )

    return frame


@st.cache_data(ttl=CACHE_TTL, max_entries=8, show_spinner=False)
def load_industry_stock_count() -> pd.DataFrame:
    stocks = load_stock_list()
    if stocks.empty:
        return pd.DataFrame(columns=["industry_label", "stock_count"])

    return (
        stocks.groupby("industry_label", as_index=False)
        .agg(stock_count=("stock_code", "nunique"))
        .sort_values("stock_count", ascending=False)
        .reset_index(drop=True)
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=16, show_spinner=False)
def load_industry_returns(start_date, end_date) -> pd.DataFrame:
    sql = text("""
        select
            b.stock_code,
            i.industry_name,
            max(case when d.trade_date = b.first_date then d.close_price end)
                as first_close,
            max(case when d.trade_date = b.last_date then d.close_price end)
                as last_close
        from (
            select
                stock_code,
                min(trade_date) as first_date,
                max(trade_date) as last_date
            from stock_daily
            where trade_date between :start_date and :end_date
              and trade_status = '1'
              and close_price > 0
            group by stock_code
        ) b
        inner join stock_daily d
                on d.stock_code = b.stock_code
               and d.trade_date in (b.first_date, b.last_date)
        inner join stock_info i on i.stock_code = b.stock_code
        group by b.stock_code, i.industry_name
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(
            sql,
            conn,
            params=_query_params(start_date=start_date, end_date=end_date),
        )

    columns = [
        "industry_label",
        "stock_count",
        "avg_return_pct",
        "median_return_pct",
        "up_stock_count",
        "up_stock_ratio",
    ]

    if frame.empty:
        return pd.DataFrame(columns=columns)

    for column in ("first_close", "last_close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame[
        frame["first_close"].gt(0) & frame["last_close"].notna()
    ].copy()

    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame["return_pct"] = (
        frame["last_close"] / frame["first_close"] - 1
    ) * 100
    frame["industry_label"] = [
        split_industry_name(value)[1] for value in frame["industry_name"]
    ]

    grouped = (
        frame.groupby("industry_label", as_index=False)
        .agg(
            stock_count=("stock_code", "nunique"),
            avg_return_pct=("return_pct", "mean"),
            median_return_pct=("return_pct", "median"),
            up_stock_count=("return_pct", lambda values: int((values > 0).sum())),
        )
        .sort_values("avg_return_pct", ascending=False)
        .reset_index(drop=True)
    )

    grouped["up_stock_ratio"] = (
        grouped["up_stock_count"]
        .div(grouped["stock_count"].replace(0, pd.NA))
        .mul(100)
        .fillna(0.0)
    )

    return grouped


@st.cache_data(ttl=CACHE_TTL, max_entries=16, show_spinner=False)
def load_industry_daily_nav(start_date, end_date) -> pd.DataFrame:
    sql = text("""
        select
            d.trade_date,
            i.industry_name,
            avg(d.pct_change) as avg_pct_change
        from stock_daily d
        inner join stock_info i on i.stock_code = d.stock_code
        where d.trade_date between :start_date and :end_date
          and d.trade_status = '1'
          and d.pct_change is not null
        group by d.trade_date, i.industry_name
        order by d.trade_date
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(
            sql,
            conn,
            params=_query_params(start_date=start_date, end_date=end_date),
        )

    if frame.empty:
        return pd.DataFrame()

    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["avg_pct_change"] = pd.to_numeric(
        frame["avg_pct_change"], errors="coerce"
    )
    frame["industry_label"] = [
        split_industry_name(value)[1] for value in frame["industry_name"]
    ]

    daily = (
        frame.pivot_table(
            index="trade_date",
            columns="industry_label",
            values="avg_pct_change",
            aggfunc="mean",
        )
        .sort_index()
    )

    return (1 + daily.div(100)).cumprod()


@st.cache_data(ttl=CACHE_TTL, max_entries=4, show_spinner=False)
def load_price_matrices(
    start_date, end_date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sql = text("""
        select
            trade_date,
            stock_code,
            open_price,
            close_price
        from stock_daily
        where trade_date between :start_date and :end_date
          and trade_status = '1'
          and open_price > 0
          and close_price > 0
    """)

    with get_engine().connect() as conn:
        frame = pd.read_sql_query(
            sql,
            conn,
            params=_query_params(start_date=start_date, end_date=end_date),
        )

    if frame.empty:
        return pd.DataFrame(), pd.DataFrame()

    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["stock_code"] = frame["stock_code"].astype(str).str.strip()

    for column in ("open_price", "close_price"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    open_matrix = (
        frame.pivot(
            index="trade_date", columns="stock_code", values="open_price"
        )
        .sort_index()
        .where(lambda matrix: matrix > 0)
    )

    close_matrix = (
        frame.pivot(
            index="trade_date", columns="stock_code", values="close_price"
        )
        .sort_index()
        .where(lambda matrix: matrix > 0)
    )

    common_codes = open_matrix.columns.intersection(close_matrix.columns)

    return open_matrix[common_codes], close_matrix[common_codes]
