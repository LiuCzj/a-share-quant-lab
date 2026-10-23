import baostock as bs
import pandas as pd
from pathlib import Path


# ============================================================
# 第 1 步：确定项目目录和数据保存位置
# ============================================================

# 获取当前 Python 文件所在的目录，即 src 文件夹
current_dir = Path(__file__).resolve().parent

# 项目根目录是 src 的上一级目录
project_dir = current_dir.parent

# 下载的数据保存到项目根目录下的 data 文件夹
data_dir = project_dir / "data"

# 如果 data 文件夹不存在，就自动创建
data_dir.mkdir(parents=True, exist_ok=True)


# ============================================================
# 第 2 步：登录 BaoStock
# ============================================================

# BaoStock 提供免费的证券历史行情查询接口
# 登录成功后，才能调用行情查询功能
login_result = bs.login()

# 检查登录结果
if login_result.error_code != "0":
    raise RuntimeError(f"BaoStock 登录失败：{login_result.error_msg}")

print("BaoStock 登录成功！")


try:
    # ========================================================
    # 第 3 步：查询贵州茅台的历史日线行情
    # ========================================================

    # sh.600519 表示上海证券交易所的贵州茅台
    # frequency="d" 表示日线数据
    # adjustflag="2" 表示前复权数据
    # 前复权会根据后续分红、送转等因素调整历史价格
    result = bs.query_history_k_data_plus(
        "sh.600519",
        "date,code,open,high,low,close,preclose,volume,amount,"
        "adjustflag,turn,tradestatus,pctChg",
        start_date="2025-01-01",
        end_date="2025-03-31",
        frequency="d",
        adjustflag="2"
    )

    # 检查查询是否成功
    if result.error_code != "0":
        raise RuntimeError(f"行情查询失败：{result.error_msg}")

    # ========================================================
    # 第 4 步：逐行读取查询结果
    # ========================================================

    rows = []

    # BaoStock 返回的是一个结果集
    # next() 表示移动到下一条记录
    # get_row_data() 表示读取当前记录的各个字段
    while result.next():
        rows.append(result.get_row_data())

    # 将数据转换成 pandas DataFrame
    # 可以把 DataFrame 理解为一张带有行和列的表格
    df = pd.DataFrame(rows, columns=result.fields)

    # ========================================================
    # 第 5 步：检查数据是否为空
    # ========================================================

    if df.empty:
        print("没有获取到行情数据，请检查网络、查询参数或接口返回。")
    else:
        print("\n========== 数据预览 ==========")
        print(df.head(10).to_string(index=False))

        print("\n========== 数据基本信息 ==========")
        print("数据行数：", len(df))
        print("数据列数：", len(df.columns))
        print("字段名称：", df.columns.tolist())

        # ====================================================
        # 第 6 步：检查重复记录
        # ====================================================

        # 同一只股票的同一交易日，正常情况下只应有一条日线记录
        duplicate_count = df.duplicated(subset=["date", "code"]).sum()
        print("\n重复的股票-日期记录数：", duplicate_count)

        # ====================================================
        # 第 7 步：检查缺失值
        # ====================================================

        print("\n========== 各字段缺失值数量 ==========")
        print(df.isnull().sum())

        # ====================================================
        # 第 8 步：检查关键价格字段
        # ====================================================

        # 接口返回的数据通常是字符串
        # 转成数字后才能进行均值、最大值等数学计算
        price_columns = ["open", "high", "low", "close", "preclose"]

        for column in price_columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        print("\n========== 价格字段统计 ==========")
        print(df[price_columns].describe())

        # 检查价格是否为正数
        invalid_price_count = (df[price_columns] <= 0).any(axis=1).sum()
        print("\n存在非正价格的记录数：", invalid_price_count)

        # 检查最高价是否低于最低价
        invalid_high_low_count = (df["high"] < df["low"]).sum()
        print("最高价低于最低价的记录数：", invalid_high_low_count)

        # ====================================================
        # 第 9 步：保存原始查询结果
        # ====================================================

        # 建立英文字段名与中文字段名的对应关系
        column_mapping = {
            "date": "交易日期",
            "code": "股票代码",
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
        # 创建一份用于导出的数据，不修改前面用于检查的 df
        df_chinese = df.rename(columns=column_mapping)
        # 先保存接口返回的原始字段，便于后续复查
        # encoding="utf-8-sig" 便于使用 Excel 查看中文内容
        output_path = data_dir / "600519_daily_raw.csv"
        df_chinese.to_csv(output_path, index=False, encoding="utf-8-sig")

        print(f"\n数据已保存到：{output_path}")

finally:
    # 无论查询成功还是失败，都尝试退出 BaoStock 登录会话
    bs.logout()
    print("\nBaoStock 会话已退出。")
