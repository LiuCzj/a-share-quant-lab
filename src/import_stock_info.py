from getpass import getpass
from pathlib import Path

import pandas as pd
from sqlalchemy import URL, create_engine, text


# 第 1 步：确定项目目录和 CSV 文件
project_root = Path(__file__).resolve().parent.parent
csv_path = project_root / "data" / "stock_info.csv"

if not csv_path.exists():
    raise FileNotFoundError(f"没有找到股票基础信息文件：{csv_path}")


# 第 2 步：读取 CSV
df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)

print(f"CSV 文件：{csv_path}")
print(f"CSV 原始记录数：{len(df):,}")


# 第 3 步：将中文列名映射为数据库英文列名
column_mapping = {
    "股票代码": "stock_code",
    "股票名称": "stock_name",
    "上市日期": "list_date",
    "所属行业": "industry_name",
}

required_columns = list(column_mapping.keys())
missing_columns = [col for col in required_columns if col not in df.columns]

if missing_columns:
    raise ValueError(f"CSV 缺少必需字段：{missing_columns}")

df = df[required_columns].rename(columns=column_mapping).copy()


# 第 4 步：清理字段和数据类型
for col in ["stock_code", "stock_name", "industry_name"]:
    df[col] = df[col].astype("string").str.strip()
    df[col] = df[col].replace("", pd.NA)

# 将非法或空白的上市日期转换成缺失值
df["list_date"] = pd.to_datetime(
    df["list_date"], errors="coerce"
).dt.date

# 根据股票代码识别交易所
def get_exchange_name(stock_code):
    """根据股票代码前缀识别交易所。"""
    if not isinstance(stock_code, str):
        return None
    if stock_code.startswith("sh."):
        return "上海证券交易所"
    if stock_code.startswith("sz."):
        return "深圳证券交易所"
    return None


df["exchange_name"] = df["stock_code"].apply(get_exchange_name)


# 第 5 步：检查数据
if df.empty:
    raise ValueError("CSV 中没有可导入的数据。")

if df["stock_code"].isna().any():
    raise ValueError("股票代码存在缺失值，已停止导入。")

if df["stock_code"].duplicated().any():
    duplicates = df.loc[
        df["stock_code"].duplicated(keep=False), "stock_code"
    ].tolist()
    raise ValueError(f"发现重复股票代码，已停止导入：{duplicates[:20]}")

# 名称缺失时使用明确的占位标记，避免把缺失值误当作真实名称
df["stock_name"] = df["stock_name"].fillna("未知名称")

# 将 pandas 的缺失值转换为 Python None，便于写入 MySQL NULL
df = df.astype(object).where(pd.notna(df), None)

print("\n========== 导入前数据检查 ==========")
print(f"准备导入的股票数量：{len(df):,}")
print(f"未知名称数量：{(df['stock_name'] == '未知名称').sum():,}")
print(f"上市日期缺失数量：{df['list_date'].isna().sum():,}")
print(f"所属行业缺失数量：{df['industry_name'].isna().sum():,}")


# 第 6 步：连接 MySQL
username = input("请输入 MySQL 用户名：").strip()
password = getpass("请输入 MySQL 密码：")

db_url = URL.create(
    drivername="mysql+pymysql",
    username=username,
    password=password,
    host="localhost",
    port=3306,
    database="a_share_research",
    query={"charset": "utf8mb4"},
)

engine = create_engine(db_url, pool_pre_ping=True)


# 第 7 步：插入新记录；已有记录只用有效的新值更新
# 如果 CSV 的字段为空，则保留数据库原有值。
# “未知名称”不会覆盖数据库中已有的真实股票名称。
upsert_sql = text("""
    insert into stock_info (
        stock_code,
        stock_name,
        exchange_name,
        list_date,
        industry_name
    )
    values (
        :stock_code,
        :stock_name,
        :exchange_name,
        :list_date,
        :industry_name
    )
    on duplicate key update
        stock_name = case
            when values(stock_name) is not null
                 and values(stock_name) <> '未知名称'
            then values(stock_name)
            else stock_info.stock_name
        end,
        exchange_name = coalesce(
            values(exchange_name), stock_info.exchange_name
        ),
        list_date = coalesce(
            values(list_date), stock_info.list_date
        ),
        industry_name = coalesce(
            values(industry_name), stock_info.industry_name
        )
""")


try:
    with engine.begin() as conn:
        # 确认目标数据库，避免误写入其他数据库
        current_db = conn.execute(
            text("select database()")
        ).scalar_one()

        if current_db != "a_share_research":
            raise RuntimeError(f"当前数据库不正确：{current_db}")

        # 批量写入。发生异常时，事务会自动回滚。
        records = df.to_dict(orient="records")
        conn.execute(upsert_sql, records)

        # 第 8 步：查询数据库中的最终记录数量和字段覆盖情况
        summary_sql = text("""
            select
                count(*) as total_rows,
                count(distinct stock_code) as unique_stocks,
                sum(stock_name is null or stock_name = '' or stock_name = '未知名称') as unknown_names,
                sum(list_date is null) as missing_list_dates,
                sum(industry_name is null or industry_name = '') as missing_industries
            from stock_info
        """)

        summary = conn.execute(summary_sql).mappings().one()

        # 检查本次 CSV 中的股票是否都已存在于数据库
        coverage_sql = text("""
            select count(distinct stock_code)
            from stock_info
            where stock_code in :stock_codes
        """).bindparams()

        # 分批核对，避免一次性传入过多参数
        imported_codes = set()

        for start in range(0, len(df), 500):
            batch_codes = df["stock_code"].iloc[start:start + 500].tolist()
            placeholders = ", ".join(
                f":code_{i}" for i in range(len(batch_codes))
            )
            check_sql = text(
                f"select stock_code from stock_info "
                f"where stock_code in ({placeholders})"
            )
            params = {
                f"code_{i}": code
                for i, code in enumerate(batch_codes)
            }
            rows = conn.execute(check_sql, params).fetchall()
            imported_codes.update(row[0] for row in rows)

        missing_codes = sorted(set(df["stock_code"]) - imported_codes)

        if missing_codes:
            raise RuntimeError(
                f"有 {len(missing_codes)} 只股票未能在数据库中找到，"
                f"示例：{missing_codes[:10]}"
            )

    # 事务成功提交后输出结果
    print("\n========== MySQL 导入验收 ==========")
    print(f"目标数据库：{current_db}")
    print(f"本次 CSV 股票数：{len(df):,}")
    print(f"成功核对的股票数：{len(imported_codes):,}")
    print(f"未找到的股票数：{len(missing_codes):,}")
    print(f"数据库股票基础信息总行数：{summary['total_rows']:,}")
    print(f"数据库股票代码去重数：{summary['unique_stocks']:,}")
    print(f"数据库未知名称数量：{summary['unknown_names']:,}")
    print(f"数据库上市日期缺失数量：{summary['missing_list_dates']:,}")
    print(f"数据库所属行业缺失数量：{summary['missing_industries']:,}")

    if len(imported_codes) == len(df):
        print("\n验收通过：本次 CSV 中的股票代码均已存在于数据库。")

finally:
    engine.dispose()
