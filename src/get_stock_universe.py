from pathlib import Path

import baostock as bs
import pandas as pd


# 第 1 步：设置输出路径
project_root = Path(__file__).resolve().parent.parent
data_dir = project_root / "data"
data_dir.mkdir(parents=True, exist_ok=True)

output_path = data_dir / "stock_universe_2025-01-02.csv"


# 第 2 步：定义查询结果转换函数
def get_result_dataframe(result):
    """将 BaoStock 查询结果转换为 pandas DataFrame。"""

    if result.error_code != "0":
        raise RuntimeError(
            f"BaoStock 查询失败：{result.error_code}，{result.error_msg}"
        )

    rows = []

    while result.next():
        rows.append(result.get_row_data())

    return pd.DataFrame(rows, columns=result.fields)


# 第 3 步：登录 BaoStock
login_result = bs.login()

if login_result.error_code != "0":
    raise RuntimeError(
        f"BaoStock 登录失败：{login_result.error_code}，"
        f"{login_result.error_msg}"
    )

try:
    # 获取 2025 年 1 月 2 日的股票列表
    result = bs.query_all_stock(day="2025-01-02")
    stock_df = get_result_dataframe(result)

    if stock_df.empty:
        raise RuntimeError("没有获取到股票列表。")

    # 只保留沪深 A 股代码：
    # sh.6 开头：上海证券交易所 A 股
    # sz.0、sz.3 开头：深圳证券交易所 A 股
    stock_df = stock_df[
    stock_df["code"].str.match(
        r"^(sh\.(600|601|603|605|688|689)|sz\.(000|001|002|003|300|301))\d{3}$"
    )
].copy()

    # 删除重复股票代码
    stock_df = stock_df.drop_duplicates(subset=["code"])

    # 转换为便于查看的中文字段
    stock_df = stock_df.rename(
        columns={
            "code": "股票代码",
            "code_name": "股票名称",
            "tradeStatus": "当日交易状态代码",
        }
    )

    # 按股票代码排序，方便检查
    stock_df = stock_df.sort_values("股票代码").reset_index(drop=True)

    # 检查关键字段
    if stock_df["股票代码"].isna().any():
        raise ValueError("股票代码存在缺失值。")

    if stock_df["股票名称"].isna().any():
        raise ValueError("股票名称存在缺失值。")

    if stock_df["股票代码"].duplicated().any():
        raise ValueError("股票代码仍然存在重复。")

    # 保存股票池
    stock_df.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    print("股票池获取成功。")
    print(f"股票数量：{len(stock_df)}")
    print("\n前 10 条记录：")
    print(stock_df.head(10).to_string(index=False))
    print(f"\nCSV 保存位置：{output_path}")

finally:
    bs.logout()
