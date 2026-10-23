
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import os
import time

import baostock as bs
import pandas as pd


# ============================================================
# 第 1 步：项目配置
# ============================================================

project_root = Path(__file__).resolve().parent.parent
data_dir = project_root / "data"

universe_path = data_dir / "stock_universe_2025-01-02.csv"
parts_dir = data_dir / "market_daily_parts"

output_path = data_dir / "a_share_daily_2025q1.csv"
failure_path = data_dir / "market_daily_failures.csv"
invalid_path = data_dir / "market_daily_invalid_files.csv"

parts_dir.mkdir(parents=True, exist_ok=True)

start_date = "2025-01-01"
end_date = "2025-03-31"

# 先保持 4 个并发进程，避免无必要地增加接口压力
max_workers = 4

# 每只股票最多尝试 3 次
max_attempts = 3

fields = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg"
)

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
    "pctChg": "涨跌幅（%）",
}


# ============================================================
# 第 2 步：单个工作进程下载一批股票
# ============================================================

def download_batch(stock_codes, stock_names):
    """
    每个工作进程独立登录 BaoStock。
    每只股票单独保存 CSV，便于断点续传。
    """

    failures = []

    login_result = bs.login()

    if login_result.error_code != "0":
        reason = (
            f"登录失败：{login_result.error_code}，"
            f"{login_result.error_msg}"
        )

        return [
            {"股票代码": code, "错误原因": reason}
            for code in stock_codes
        ]

    try:
        for stock_code in stock_codes:
            part_path = parts_dir / (
                stock_code.replace(".", "_") + ".csv"
            )

            # 只有文件内容有效、股票代码正确时才跳过
            if part_path.exists() and part_path.stat().st_size > 0:
                try:
                    existing_df = pd.read_csv(
                        part_path,
                        encoding="utf-8-sig",
                        usecols=["code"],
                        dtype={"code": str},
                    )

                    existing_codes = (
                        existing_df["code"].astype(str).str.strip().unique()
                    )

                    if len(existing_codes) == 1 and existing_codes[0] == stock_code:
                        continue

                except Exception:
                    pass

            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    result = bs.query_history_k_data_plus(
                        code=stock_code,
                        fields=fields,
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="2",
                    )

                    if result.error_code != "0":
                        raise RuntimeError(
                            f"{result.error_code}: {result.error_msg}"
                        )

                    rows = []

                    while result.next():
                        rows.append(result.get_row_data())

                    if not rows:
                        raise RuntimeError("接口没有返回行情记录。")

                    stock_df = pd.DataFrame(
                        rows,
                        columns=result.fields,
                    )

                    # 检查接口返回的代码，防止错误数据被保存
                    returned_codes = (
                        stock_df["code"].astype(str).str.strip().unique()
                    )

                    if len(returned_codes) != 1 or returned_codes[0] != stock_code:
                        raise RuntimeError(
                            f"返回股票代码与请求不一致：{returned_codes}"
                        )

                    # 临时文件写完后再替换正式文件
                    temp_path = part_path.with_suffix(".tmp")

                    stock_df.to_csv(
                        temp_path,
                        index=False,
                        encoding="utf-8-sig",
                    )

                    temp_path.replace(part_path)

                    print(
                        f"[进程 {os.getpid()}] "
                        f"{stock_code}：{len(stock_df)} 条"
                    )

                    last_error = None
                    break

                except Exception as exc:
                    last_error = str(exc)

                    if attempt < max_attempts:
                        time.sleep(2 ** (attempt - 1))

            if last_error is not None:
                failures.append({
                    "股票代码": stock_code,
                    "错误原因": last_error,
                })

    finally:
        logout_result = bs.logout()

        if logout_result.error_code != "0":
            print(
                f"[进程 {os.getpid()}] "
                f"BaoStock 退出提示：{logout_result.error_msg}"
            )

    return failures


# ============================================================
# 第 3 步：读取并校验股票池
# ============================================================

def main():
    if not universe_path.exists():
        raise FileNotFoundError(
            f"没有找到股票池文件：{universe_path}"
        )

    universe_df = pd.read_csv(
        universe_path,
        encoding="utf-8-sig",
        dtype={"股票代码": str},
    )

    required_columns = {"股票代码", "股票名称"}

    if not required_columns.issubset(universe_df.columns):
        raise ValueError(
            f"股票池必须包含字段：{required_columns}"
        )

    universe_df = universe_df[["股票代码", "股票名称"]].copy()

    universe_df["股票代码"] = (
        universe_df["股票代码"].astype(str).str.strip()
    )

    universe_df["股票名称"] = (
        universe_df["股票名称"].astype(str).str.strip()
    )

    # 去掉空代码和空名称
    universe_df = universe_df[
        universe_df["股票代码"].ne("")
        & universe_df["股票名称"].ne("")
    ].copy()

    # 股票代码必须唯一
    if universe_df["股票代码"].duplicated().any():
        duplicates = universe_df.loc[
            universe_df["股票代码"].duplicated(False),
            "股票代码",
        ].tolist()

        raise ValueError(f"股票池中存在重复代码：{duplicates[:20]}")

    stock_names = dict(
        zip(universe_df["股票代码"], universe_df["股票名称"])
    )

    stock_codes = list(stock_names.keys())

    print(f"股票池总数：{len(stock_codes)}")

    # ========================================================
    # 第 4 步：检查已下载文件，确定待下载股票
    # ========================================================

    pending_codes = []

    for stock_code in stock_codes:
        part_path = parts_dir / (
            stock_code.replace(".", "_") + ".csv"
        )

        if not part_path.exists() or part_path.stat().st_size == 0:
            pending_codes.append(stock_code)
            continue

        try:
            existing_df = pd.read_csv(
                part_path,
                encoding="utf-8-sig",
                usecols=["code"],
                dtype={"code": str},
            )

            existing_codes = (
                existing_df["code"].astype(str).str.strip().unique()
            )

            # 文件中必须恰好只有请求的那只股票
            if len(existing_codes) != 1 or existing_codes[0] != stock_code:
                pending_codes.append(stock_code)

        except Exception:
            pending_codes.append(stock_code)

    print(f"已有有效文件：{len(stock_codes) - len(pending_codes)}")
    print(f"待下载股票数：{len(pending_codes)}")
    print(f"并发进程数：{max_workers}")

    # ========================================================
    # 第 5 步：并行下载
    # ========================================================

    start_time = time.perf_counter()
    failures = []

    # 轮流分配股票，尽量让每个进程承担相近的任务量
    batches = [
        pending_codes[i::max_workers]
        for i in range(max_workers)
    ]

    batches = [batch for batch in batches if batch]

    if batches:
        with ProcessPoolExecutor(
            max_workers=max_workers
        ) as executor:

            futures = [
                executor.submit(
                    download_batch,
                    batch,
                    stock_names,
                )
                for batch in batches
            ]

            for future in as_completed(futures):
                try:
                    failures.extend(future.result())
                except Exception as exc:
                    print(f"工作进程异常：{exc}")

    # ========================================================
    # 第 6 步：合并行情文件，并严格检查代码
    # ========================================================

    frames = []
    invalid_files = []
    valid_file_count = 0

    # 只遍历本次股票池中应该存在的文件
    for stock_code in stock_codes:
        part_path = parts_dir / (
            stock_code.replace(".", "_") + ".csv"
        )

        if not part_path.exists():
            invalid_files.append({
                "文件名": part_path.name,
                "问题": "文件不存在",
            })
            continue

        try:
            part_df = pd.read_csv(
                part_path,
                encoding="utf-8-sig",
                dtype={"code": str},
            )

            required_fields = {"date", "code", "close"}

            if not required_fields.issubset(part_df.columns):
                invalid_files.append({
                    "文件名": part_path.name,
                    "问题": "缺少必要字段",
                })
                continue

            part_df["code"] = part_df["code"].astype(str).str.strip()

            returned_codes = part_df["code"].unique()

            if len(returned_codes) != 1 or returned_codes[0] != stock_code:
                invalid_files.append({
                    "文件名": part_path.name,
                    "问题": (
                        f"代码不匹配，期望 {stock_code}，"
                        f"实际 {returned_codes[:5].tolist()}"
                    ),
                })
                continue

            if part_df.empty:
                invalid_files.append({
                    "文件名": part_path.name,
                    "问题": "文件没有行情记录",
                })
                continue

            part_df["stock_name"] = stock_names[stock_code]
            frames.append(part_df)
            valid_file_count += 1

        except Exception as exc:
            invalid_files.append({
                "文件名": part_path.name,
                "问题": str(exc),
            })

    if not frames:
        raise RuntimeError(
            "没有可合并的有效行情文件，请检查股票池和下载文件。"
        )

    all_df = pd.concat(frames, ignore_index=True)

    all_df = all_df.rename(columns=column_mapping)

    # 删除相同股票、相同日期的重复行情
    all_df = all_df.drop_duplicates(
        subset=["交易日期", "股票代码"],
        keep="last",
    )

    all_df = all_df.sort_values(
        ["交易日期", "股票代码"]
    ).reset_index(drop=True)

    all_df.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    # ========================================================
    # 第 7 步：保存失败清单和异常文件清单
    # ========================================================

    if failures:
        pd.DataFrame(failures).to_csv(
            failure_path,
            index=False,
            encoding="utf-8-sig",
        )
    elif failure_path.exists():
        failure_path.unlink()

    if invalid_files:
        pd.DataFrame(invalid_files).to_csv(
            invalid_path,
            index=False,
            encoding="utf-8-sig",
        )
    elif invalid_path.exists():
        invalid_path.unlink()

    elapsed = time.perf_counter() - start_time

    # ========================================================
    # 第 8 步：输出最终汇总
    # ========================================================

    print("\n========== 下载汇总 ==========")
    print(f"股票池总数：{len(stock_codes)}")
    print(f"有效行情文件数：{valid_file_count}")
    print(f"存在问题的文件数：{len(invalid_files)}")
    print(f"实际有行情记录的股票数：{all_df['股票代码'].nunique()}")
    print(f"行情总记录数：{len(all_df)}")
    print(
        f"行情日期范围：{all_df['交易日期'].min()} "
        f"至 {all_df['交易日期'].max()}"
    )
    print(f"本次下载失败股票数：{len(failures)}")
    print(f"本次耗时：{elapsed:.1f} 秒")
    print(f"合并文件：{output_path}")

    if failures:
        print(f"失败清单：{failure_path}")

    if invalid_files:
        print(f"异常文件清单：{invalid_path}")

    print("下载与合并任务结束。")


if __name__ == "__main__":
    # Windows 使用多进程时必须保留此入口保护
    main()
