
import baostock as bs
import pandas as pd
from pathlib import Path


# ============================================================
# 第 1 步：设置项目目录、日期范围和股票清单
# ============================================================

current_dir = Path(__file__).resolve().parent
project_dir = current_dir.parent
data_dir = project_dir / "data"
data_dir.mkdir(parents=True, exist_ok=True)

# 先用 2025 年第一季度验证批量获取流程
start_date = "2025-01-01"
end_date = "2025-03-31"

# 股票代码和名称建立对应关系，方便后续分析和展示
stock_list = [
    {"code": "sh.600519", "name": "贵州茅台"},
    {"code": "sh.601318", "name": "中国平安"},
    {"code": "sh.600036", "name": "招商银行"},
    {"code": "sh.600050", "name": "中国联通"},
    {"code": "sz.000002", "name": "万科A"},
]

# BaoStock 返回的行情字段
fields = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg"
)

# 保存所有股票的行情数据
all_data = []

# 记录获取失败的股票，方便后续排查
failed_stocks = []


# ============================================================
# 第 2 步：登录 BaoStock
# ============================================================

login_result = bs.login()

if login_result.error_code != "0":
    raise RuntimeError(f"BaoStock 登录失败：{login_result.error_msg}")

print("BaoStock 登录成功！")


try:
    # ========================================================
    # 第 3 步：逐只获取股票行情
    # ========================================================

    for stock in stock_list:
        stock_code = stock["code"]
        stock_name = stock["name"]

        print(f"\n正在获取：{stock_name}（{stock_code}）")

        result = bs.query_history_k_data_plus(
            stock_code,
            fields,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"
        )

        # 如果某只股票查询失败，记录下来，继续处理其他股票
        if result.error_code != "0":
            print(f"获取失败：{result.error_msg}")
            failed_stocks.append({
                "code": stock_code,
                "name": stock_name,
                "error": result.error_msg
            })
            continue

        # 逐行读取这只股票的查询结果
        rows = []

        while result.next():
            rows.append(result.get_row_data())

        # 转换为 DataFrame，也就是表格形式的数据
        stock_df = pd.DataFrame(rows, columns=result.fields)

        if stock_df.empty:
            print("没有获取到数据。")
            failed_stocks.append({
                "code": stock_code,
                "name": stock_name,
                "error": "查询结果为空"
            })
            continue

        # 添加股票名称，方便阅读和分组统计
        stock_df["stock_name"] = stock_name

        # 将这只股票的数据放进总列表
        all_data.append(stock_df)

        print(f"获取成功，共 {len(stock_df)} 条记录。")

finally:
    # 无论是否出现异常，都退出 BaoStock 会话
    bs.logout()
    print("\nBaoStock 会话已退出。")


# ============================================================
# 第 4 步：合并所有股票的数据
# ============================================================

if not all_data:
    raise RuntimeError("所有股票都没有获取到数据，请检查网络或接口返回。")

# 将多张股票行情表按行合并
df = pd.concat(all_data, ignore_index=True)

print("\n========== 合并结果 ==========")
print("总记录数：", len(df))
print("股票数量：", df["code"].nunique())
print("股票清单：")
print(df[["code", "stock_name"]].drop_duplicates().to_string(index=False))


# ============================================================
# 第 5 步：检查重复记录
# ============================================================

# 同一只股票在同一交易日，正常情况下只应有一条日线记录
duplicate_count = df.duplicated(subset=["date", "code"]).sum()

print("\n========== 重复记录检查 ==========")
print("重复的股票-日期记录数：", duplicate_count)


# ============================================================
# 第 6 步：检查缺失值并转换数值字段
# ============================================================

# 这些字段应该是数值，不能一直以字符串形式保存
numeric_columns = [
    "open", "high", "low", "close", "preclose",
    "volume", "amount", "turn", "tradestatus", "pctChg"
]

for column in numeric_columns:
    # 无法转换为数字的内容会变成 NaN，方便检查异常数据
    df[column] = pd.to_numeric(df[column], errors="coerce")

print("\n========== 缺失值检查 ==========")
print(df.isnull().sum().to_string())


# ============================================================
# 第 7 步：检查价格逻辑
# ============================================================

price_columns = ["open", "high", "low", "close", "preclose"]

# 检查价格是否存在非正数
invalid_price_count = (df[price_columns] <= 0).any(axis=1).sum()

# 检查最高价是否低于最低价
invalid_high_low_count = (df["high"] < df["low"]).sum()

# 检查开盘价、收盘价是否超出当日最高价和最低价
invalid_range_count = (
    (df["open"] > df["high"])
    | (df["open"] < df["low"])
    | (df["close"] > df["high"])
    | (df["close"] < df["low"])
).sum()

print("\n========== 价格逻辑检查 ==========")
print("存在非正价格的记录数：", invalid_price_count)
print("最高价低于最低价的记录数：", invalid_high_low_count)
print("开盘价或收盘价超出当日价格范围的记录数：", invalid_range_count)


# ============================================================
# 第 8 步：按股票统计数据量
# ============================================================

print("\n========== 每只股票的数据量 ==========")

stock_counts = (
    df.groupby(["code", "stock_name"])
    .size()
    .reset_index(name="记录数")
)

print(stock_counts.to_string(index=False))


# ============================================================
# 第 9 步：将字段名转换为中文
# ============================================================

column_mapping = {
    "date": "交易日期",
    "code": "股票代码",
    "stock_name": "股票名称",
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "preclose": "前收盘价",
    "volume": "成交量",
    "amount": "成交额",
    "adjustflag": "复权类型",
    "turn": "换手率",
    "tradestatus": "交易状态",
    "pctChg": "涨跌幅（%）"
}

df_chinese = df.rename(columns=column_mapping)

# 按股票代码、交易日期排序，方便后续查看和分析
df_chinese = df_chinese.sort_values(
    by=["股票代码", "交易日期"]
).reset_index(drop=True)


# ============================================================
# 第 10 步：保存合并后的数据
# ============================================================

output_path = data_dir / "a_share_daily_2025q1.csv"

df_chinese.to_csv(
    output_path,
    index=False,
    encoding="utf-8-sig"
)

print("\n========== 最终结果 ==========")
print("最终记录数：", len(df_chinese))
print("最终字段：", df_chinese.columns.tolist())
print("\n数据预览：")
print(df_chinese.head(10).to_string(index=False))
print(f"\n数据已保存到：{output_path}")


# ============================================================
# 第 11 步：报告获取失败的股票
# ============================================================

if failed_stocks:
    print("\n========== 获取失败的股票 ==========")

    for stock in failed_stocks:
        print(
            f"{stock['name']}（{stock['code']}）："
            f"{stock['error']}"
        )
else:
    print("\n所有股票均已成功获取。")
