import getpass
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL


# ============================================================
# 1. 读取全市场行情数据
# ============================================================

project_dir = Path(__file__).resolve().parent.parent
csv_path = project_dir / "data" / "a_share_daily_2025q1.csv"

if not csv_path.exists():
    raise FileNotFoundError(f"找不到行情文件：{csv_path}")

df = pd.read_csv(
    csv_path,
    encoding="utf-8-sig",
    dtype={"股票代码": "string"}
)

if df.empty:
    raise ValueError("CSV 没有数据，停止导入。")

print(f"行情文件：{csv_path}")
print(f"CSV 记录数：{len(df):,}")


# ============================================================
# 2. 转换字段名称和数据类型
# ============================================================

column_mapping = {
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
    "涨跌幅（%）": "pct_change"
}

missing_columns = set(column_mapping) - set(df.columns)

if missing_columns:
    raise ValueError(f"CSV 缺少字段：{sorted(missing_columns)}")

df = df.rename(columns=column_mapping)
df = df[list(column_mapping.values())]

df["trade_date"] = pd.to_datetime(
    df["trade_date"], errors="raise"
).dt.date

df["stock_code"] = df["stock_code"].str.strip()

for column in ["stock_name", "adjust_flag", "trade_status"]:
    df[column] = df[column].astype("string").str.strip()

numeric_columns = [
    "open_price", "high_price", "low_price",
    "close_price", "preclose_price", "volume",
    "amount", "turnover_rate", "pct_change"
]

for column in numeric_columns:
    df[column] = pd.to_numeric(df[column], errors="raise")


# ============================================================
# 3. 统一进行数据质量检查
# ============================================================

# 这些字段不能缺失
required_columns = [
    "trade_date", "stock_code", "stock_name", "trade_status"
]

if df[required_columns].isna().any().any():
    raise ValueError("日期、股票代码、股票名称或交易状态缺失。")

for column in required_columns:
    if df[column].astype("string").str.strip().eq("").any():
        raise ValueError(f"字段 {column} 存在空字符串。")

# 当前数据源的交易状态约定：1 表示交易，0 表示停牌
unknown_status = ~df["trade_status"].isin(["0", "1"])

if unknown_status.any():
    values = df.loc[unknown_status, "trade_status"].unique().tolist()
    raise ValueError(f"发现未识别的交易状态：{values}")

# 同一股票在同一个交易日只能有一条记录
duplicate_count = df.duplicated(
    subset=["trade_date", "stock_code"]
).sum()

if duplicate_count:
    raise ValueError(f"发现 {duplicate_count} 条重复主键，停止导入。")

price_columns = [
    "open_price", "high_price", "low_price", "close_price"
]

# 正常交易记录必须有完整的 OHLC 价格
# OHLC 即开盘价、最高价、最低价、收盘价
normal_trade = df["trade_status"].eq("1")
missing_ohlc = df[price_columns].isna().any(axis=1)

if (normal_trade & missing_ohlc).any():
    count = int((normal_trade & missing_ohlc).sum())
    raise ValueError(f"发现 {count} 条正常交易记录缺少价格。")

# 正常交易记录的行情指标不应缺失
market_columns = [
    "preclose_price", "volume", "amount",
    "turnover_rate", "pct_change"
]

missing_market_data = df[market_columns].isna().any(axis=1)

if (normal_trade & missing_market_data).any():
    count = int((normal_trade & missing_market_data).sum())
    raise ValueError(f"发现 {count} 条正常交易记录缺少行情指标。")

# 停牌记录允许部分行情字段为空，不填 0，也不删除记录
suspended = df["trade_status"].eq("0")
suspended_missing = suspended & (
    df[price_columns + market_columns].isna().any(axis=1)
)

print("\n========== 数据质量检查 ==========")
print(f"总记录数：{len(df):,}")
print(f"股票数量：{df['stock_code'].nunique():,}")
print(f"正常交易记录：{normal_trade.sum():,}")
print(f"停牌记录：{suspended.sum():,}")
print(f"存在行情字段缺失的停牌记录：{suspended_missing.sum():,}")
print(f"重复主键：{duplicate_count}")

# 对所有非空价格检查正数
for column in price_columns + ["preclose_price"]:
    values = df[column].dropna()
    if (values <= 0).any():
        raise ValueError(f"字段 {column} 存在小于或等于 0 的价格。")

# 检查最高价、最低价和开盘价、收盘价之间的关系
complete_ohlc = df[price_columns].notna().all(axis=1)
price_df = df.loc[complete_ohlc]

invalid_prices = (
    (price_df["high_price"] < price_df["low_price"])
    | (price_df["high_price"] < price_df["open_price"])
    | (price_df["high_price"] < price_df["close_price"])
    | (price_df["low_price"] > price_df["open_price"])
    | (price_df["low_price"] > price_df["close_price"])
)

if invalid_prices.any():
    raise ValueError(f"发现 {invalid_prices.sum()} 条价格关系异常记录。")

for column in ["volume", "amount"]:
    if (df[column].dropna() < 0).any():
        raise ValueError(f"字段 {column} 存在负数。")

start_date = df["trade_date"].min()
end_date = df["trade_date"].max()
stock_codes = df["stock_code"].unique().tolist()

print(f"日期范围：{start_date} 至 {end_date}")
print("基础质量检查通过，准备连接数据库。")


# ============================================================
# 4. 连接 MySQL
# ============================================================

db_user = input("请输入 MySQL 用户名：").strip()
db_password = getpass.getpass("请输入 MySQL 密码：")

db_url = URL.create(
    drivername="mysql+pymysql",
    username=db_user,
    password=db_password,
    host="localhost",
    port=3306,
    database="a_share_research",
    query={"charset": "utf8mb4"}
)

engine = create_engine(db_url, pool_pre_ping=True)


# ============================================================
# 5. 删除本次范围内的旧数据，分批写入并验证
# ============================================================

try:
    with engine.begin() as conn:

        database_name = conn.execute(
            text("select database()")
        ).scalar_one()

        if database_name != "a_share_research":
            raise RuntimeError(f"连接到了错误的数据库：{database_name}")

        # 只删除本次 CSV 涉及的股票及日期范围内的旧数据。
        # 其他股票、其他日期的数据不会被删除。
        delete_sql = text("""
            delete from stock_daily
            where trade_date between :start_date and :end_date
              and stock_code in :stock_codes
        """).bindparams(
            bindparam("stock_codes", expanding=True)
        )

        deleted = conn.execute(
            delete_sql,
            {
                "start_date": start_date,
                "end_date": end_date,
                "stock_codes": stock_codes
            }
        ).rowcount

        print(f"\n已删除旧记录：{deleted:,} 条")

        # 分批写入，避免一次性发送过大的 SQL 语句。
        # 缺失值保留为空，不会主动填充为 0。
        df.to_sql(
            name="stock_daily",
            con=conn,
            if_exists="append",
            index=False,
            chunksize=500,
            method="multi"
        )

        # 只核对本次股票及日期范围内的记录
        verify_sql = text("""
            select
                count(*) as total_count,
                count(distinct stock_code) as stock_count,
                min(trade_date) as min_date,
                max(trade_date) as max_date
            from stock_daily
            where trade_date between :start_date and :end_date
              and stock_code in :stock_codes
        """).bindparams(
            bindparam("stock_codes", expanding=True)
        )

        result = conn.execute(
            verify_sql,
            {
                "start_date": start_date,
                "end_date": end_date,
                "stock_codes": stock_codes
            }
        ).mappings().one()

        database_count = result["total_count"]
        database_stock_count = result["stock_count"]

        if database_count != len(df):
            raise RuntimeError(
                f"记录数不一致：CSV {len(df):,} 条，"
                f"数据库 {database_count:,} 条，事务将回滚。"
            )

        if database_stock_count != len(stock_codes):
            raise RuntimeError(
                f"股票数量不一致：CSV {len(stock_codes):,} 只，"
                f"数据库 {database_stock_count:,} 只，事务将回滚。"
            )

        print("\n========== 入库验证通过 ==========")
        print(f"CSV 记录数：{len(df):,}")
        print(f"数据库记录数：{database_count:,}")
        print(f"股票数量：{database_stock_count:,}")
        print(f"最早日期：{result['min_date']}")
        print(f"最晚日期：{result['max_date']}")

    print("\n事务已提交，全市场行情数据入库成功。")

finally:
    engine.dispose()
    print("数据库连接资源已释放。")
