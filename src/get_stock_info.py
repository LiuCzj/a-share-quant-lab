from pathlib import Path

import baostock as bs
import pandas as pd


# 第 1 步：确定项目目录和全市场行情文件
project_root = Path(__file__).resolve().parent.parent
data_dir = project_root / "data"
daily_path = data_dir / "a_share_daily_2025q1.csv"
output_path = data_dir / "stock_info.csv"

if not daily_path.exists():
    raise FileNotFoundError(f"没有找到全市场行情文件：{daily_path}")


# 第 2 步：从行情文件中提取完整股票代码清单
daily_df = pd.read_csv(daily_path, encoding="utf-8-sig", dtype=str)

# 兼容项目 CSV 中可能出现的中英文列名
code_column = next(
    (col for col in ["股票代码", "code", "stock_code"] if col in daily_df.columns),
    None,
)

if code_column is None:
    raise ValueError(f"行情 CSV 中找不到股票代码列，实际列名：{daily_df.columns.tolist()}")

target_df = daily_df[[code_column]].rename(columns={code_column: "code"}).copy()
target_df["code"] = target_df["code"].astype("string").str.strip()
target_df = target_df.dropna(subset=["code"]).drop_duplicates(subset=["code"])

# 如果行情 CSV 中有股票名称，保留它作为基础资料缺失时的备用来源
name_column = next(
    (col for col in ["股票名称", "code_name", "stock_name"] if col in daily_df.columns),
    None,
)

if name_column:
    name_df = daily_df[[code_column, name_column]].rename(
        columns={code_column: "code", name_column: "fallback_name"}
    ).copy()
    name_df["code"] = name_df["code"].astype("string").str.strip()
    name_df["fallback_name"] = name_df["fallback_name"].astype("string").str.strip()
    name_df = name_df.drop_duplicates(subset=["code"], keep="first")
    target_df = target_df.merge(name_df, on="code", how="left", validate="one_to_one")
else:
    target_df["fallback_name"] = pd.NA

target_codes = set(target_df["code"])

print(f"行情文件涉及的股票数量：{len(target_codes):,}")


# 第 3 步：定义 BaoStock 结果转换函数
def get_result_dataframe(result, query_name):
    """将 BaoStock 查询结果转换成 DataFrame，并检查接口是否报错。"""
    if result.error_code != "0":
        raise RuntimeError(
            f"{query_name}失败：{result.error_code}，{result.error_msg}"
        )

    rows = []

    while result.next():
        rows.append(result.get_row_data())

    return pd.DataFrame(rows, columns=result.fields)


# 第 4 步：登录 BaoStock
login_result = bs.login()

if login_result.error_code != "0":
    raise RuntimeError(
        f"BaoStock 登录失败：{login_result.error_code}，"
        f"{login_result.error_msg}"
    )

try:
    # 第 5 步：一次性获取全部证券基础资料
    print("\n正在获取全部证券基础资料……")
    basic_result = bs.query_stock_basic()
    basic_df = get_result_dataframe(basic_result, "查询证券基础资料")

    if basic_df.empty:
        raise RuntimeError("BaoStock 没有返回任何证券基础资料。")

    # 只保留行情文件中涉及的股票
    basic_df = basic_df[basic_df["code"].isin(target_codes)].copy()
    basic_df = basic_df.drop_duplicates(subset=["code"], keep="last")

    print(f"匹配到基础资料的股票数量：{basic_df['code'].nunique():,}")

    # 第 6 步：一次性获取全部行业分类
    print("\n正在获取行业分类……")
    industry_result = bs.query_stock_industry()
    industry_df = get_result_dataframe(industry_result, "查询行业分类")

    if industry_df.empty:
        print("警告：行业接口没有返回数据，所属行业将保留为空。")
        industry_df = pd.DataFrame(
            columns=["code", "industry", "industryClassification"]
        )
    else:
        industry_df = industry_df[industry_df["code"].isin(target_codes)].copy()
        industry_df = industry_df.drop_duplicates(subset=["code"], keep="last")

    print(f"匹配到行业信息的股票数量：{industry_df['code'].nunique():,}")

    # 第 7 步：以行情股票清单为主表，左连接基础资料和行业资料
    stock_info_df = target_df.merge(
        basic_df[["code", "code_name", "ipoDate", "outDate", "type", "status"]],
        on="code",
        how="left",
        validate="one_to_one",
    )

    stock_info_df = stock_info_df.merge(
        industry_df[["code", "industry", "industryClassification"]],
        on="code",
        how="left",
        validate="one_to_one",
    )

    # 第 8 步：清理名称，优先使用基础资料，其次使用行情文件中的名称
    stock_info_df["code_name"] = (
        stock_info_df["code_name"].astype("string").str.strip()
    )
    stock_info_df["fallback_name"] = (
        stock_info_df["fallback_name"].astype("string").str.strip()
    )

    stock_info_df["code_name"] = stock_info_df["code_name"].replace("", pd.NA)
    stock_info_df["fallback_name"] = stock_info_df["fallback_name"].replace("", pd.NA)

    stock_info_df["code_name"] = stock_info_df["code_name"].fillna(
        stock_info_df["fallback_name"]
    )

    # 明确标识无法获取名称的记录，不伪造股票名称
    missing_name_count = stock_info_df["code_name"].isna().sum()
    stock_info_df["code_name"] = stock_info_df["code_name"].fillna("未知名称")

    # 第 9 步：转换为便于阅读的中文列名
    stock_info_df = stock_info_df.rename(
        columns={
            "code": "股票代码",
            "code_name": "股票名称",
            "ipoDate": "上市日期",
            "outDate": "退市日期",
            "type": "证券类型代码",
            "status": "上市状态代码",
            "industry": "所属行业",
            "industryClassification": "行业分类标准",
        }
    )

    # 第 10 步：检查结果，保证每个行情股票代码都保留
    if stock_info_df["股票代码"].duplicated().any():
        raise ValueError("结果中存在重复股票代码，请检查接口数据。")

    if len(stock_info_df) != len(target_codes):
        raise RuntimeError(
            f"股票代码覆盖数量异常：目标 {len(target_codes)}，"
            f"结果 {len(stock_info_df)}"
        )

    # 统计时将空字符串也视为缺失
    for col in ["所属行业", "行业分类标准", "上市日期"]:
        stock_info_df[col] = stock_info_df[col].replace("", pd.NA)

    # 第 11 步：保存 CSV
    stock_info_df.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    # 第 12 步：输出覆盖率和缺失统计
    print("\n========== 股票基础信息获取汇总 ==========")
    print(f"目标股票数量：{len(target_codes):,}")
    print(f"输出记录数量：{len(stock_info_df):,}")
    print(f"缺失股票名称数量：{missing_name_count:,}")
    print(f"缺失上市日期数量：{stock_info_df['上市日期'].isna().sum():,}")
    print(f"缺失所属行业数量：{stock_info_df['所属行业'].isna().sum():,}")
    print(f"缺失行业分类标准数量：{stock_info_df['行业分类标准'].isna().sum():,}")
    print(f"\nCSV 已保存到：{output_path}")

    print("\n前 10 条记录：")
    print(stock_info_df.head(10).to_string(index=False))

finally:
    # 查询成功或失败，都尝试退出 BaoStock
    bs.logout()
