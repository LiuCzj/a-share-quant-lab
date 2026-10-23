from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import db
from ..ui import (
    ACCENT_COLOR,
    DOWN_COLOR,
    NEUTRAL_COLOR,
    UP_COLOR,
    apply_theme,
    chart_key,
    date_range_filter,
    download_button,
    empty_state,
    format_amount_yi,
    format_pct,
    format_price,
    metric_row,
    section,
)

TRADING_DAYS_PER_YEAR = 252


def render(meta: dict) -> None:
    st.header("🔍 个股分析")
    st.caption(
        "查看单只股票的前复权历史行情、价格走势、成交量与区间风险收益特征。"
    )

    start_date, end_date = date_range_filter(meta, "stock")

    stock_list = db.load_stock_list()
    if stock_list.empty:
        empty_state("股票基础信息表 stock_info 中没有数据。")
        return

    selected_stock = _render_stock_selector(stock_list)
    if selected_stock is None:
        return

    history = db.load_stock_daily(
        selected_stock["stock_code"], start_date, end_date
    )

    if history.empty:
        empty_state("所选日期范围内没有该股票的行情记录。")
        return

    st.subheader(
        f"{selected_stock['stock_name']}　"
        f"{selected_stock['stock_code']}"
    )
    st.caption(
        f"所属行业：{selected_stock['industry_label']}　|　"
        f"交易所：{selected_stock['exchange_name']}　|　"
        f"数据区间：{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d}"
    )

    valid = history[
        history["is_tradable"]
        & history["close_price"].notna()
        & history["close_price"].gt(0)
    ].copy()

    suspended_days = int((~history["is_tradable"]).sum())

    if len(valid) < 2:
        empty_state(
            "所选区间内该股票的正常交易记录不足 2 个交易日，"
            "无法计算区间指标。"
        )
        if suspended_days:
            st.caption(f"区间内有 {suspended_days} 个交易日处于停牌状态。")
        return

    _render_metrics(valid)
    _render_anomaly_warning(valid, suspended_days)

    st.divider()
    _render_candlestick(valid, selected_stock, start_date, end_date)
    _render_volume(valid, start_date, end_date)
    _render_return_distribution(valid, start_date, end_date)
    _render_detail_table(valid, selected_stock)


def _render_stock_selector(stock_list: pd.DataFrame) -> pd.Series | None:
    st.markdown("##### 🔎 股票筛选")
    columns = st.columns([1, 3])

    exchange_options = ["全部"] + sorted(
        stock_list["exchange_name"].dropna().unique().tolist()
    )
    exchange = columns[0].selectbox(
        "交易所",
        options=exchange_options,
        index=0,
        key="stock_exchange",
    )

    pool = stock_list
    if exchange != "全部":
        pool = pool[pool["exchange_name"] == exchange]

    if pool.empty:
        columns[1].warning("该交易所下没有股票数据。")
        return None

    selected_label = columns[1].selectbox(
        "搜索并选择股票",
        options=pool["display_name"].tolist(),
        index=0,
        key="stock_selected",
        help="点击后直接输入股票代码或名称片段，列表会自动过滤。",
    )

    return pool.loc[pool["display_name"] == selected_label].iloc[0]


def _render_metrics(valid: pd.DataFrame) -> None:
    first_close = float(valid["close_price"].iloc[0])
    last_close = float(valid["close_price"].iloc[-1])

    interval_return = (last_close / first_close - 1) * 100

    nav = valid["close_price"] / first_close
    drawdown = nav / nav.cummax() - 1
    max_drawdown = float(drawdown.min()) * 100

    daily_return = valid["close_price"].pct_change(fill_method=None).dropna()
    volatility = (
        float(daily_return.std(ddof=1)) * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
        if len(daily_return) > 1
        else float("nan")
    )

    total_amount = float(valid["amount"].sum()) / 1e8
    average_turnover = float(valid["turnover_rate"].mean())

    metric_row(
        [
            ("最新收盘价", format_price(last_close), "前复权收盘价"),
            (
                "区间涨跌幅",
                format_pct(interval_return),
                "按区间内首个与最后一个有效交易日的前复权收盘价计算",
            ),
            (
                "区间最大回撤",
                format_pct(max_drawdown),
                "区间内净值相对历史高点的最大跌幅",
            ),
            (
                "年化波动率",
                f"{volatility:.2f}%" if not np.isnan(volatility) else "—",
                "日收益率标准差 × √252，按区间内交易日计算",
            ),
        ]
    )

    metric_row(
        [
            ("区间成交额", format_amount_yi(total_amount), None),
            (
                "日均换手率",
                f"{average_turnover:.3f}%",
                "区间内各交易日换手率的算术平均值",
            ),
            ("区间最高收盘价", format_price(float(valid["close_price"].max())), None),
            ("区间最低收盘价", format_price(float(valid["close_price"].min())), None),
        ]
    )

    st.caption(
        f"首个有效交易日：{valid['trade_date'].iloc[0]:%Y-%m-%d}；"
        f"最后一个有效交易日：{valid['trade_date'].iloc[-1]:%Y-%m-%d}；"
        f"有效交易日数：{len(valid)} 天。"
    )


def _render_anomaly_warning(valid: pd.DataFrame, suspended_days: int) -> None:
    messages: list[str] = []

    if suspended_days:
        messages.append(
            f"区间内有 {suspended_days} 个交易日处于停牌状态"
            "（trade_status = 0），已从走势图和全部统计指标中剔除。"
        )

    extreme = valid[valid["pct_change"].abs() > 21]
    if not extreme.empty:
        sample = extreme.iloc[0]
        messages.append(
            f"区间内存在 {len(extreme)} 个单日涨跌幅绝对值超过 21% 的交易日"
            f"（例如 {sample['trade_date']:%Y-%m-%d} 为 "
            f"{sample['pct_change']:.2f}%）。A 股常规涨跌停限制为 ±10% "
            "（科创板、创业板为 ±20%），此类记录通常来自退市整理期或"
            "复权处理，使用前请人工确认。"
        )

    for message in messages:
        st.warning(message)

    st.info(
        "价格口径：数据库中的行情为前复权（adjust_flag = 2）。"
        "区间涨跌幅不扣除交易费用，也不等同于实际投资收益。"
    )


def _render_candlestick(
    valid: pd.DataFrame,
    selected_stock: pd.Series,
    start_date,
    end_date,
) -> None:
    section(
        "🕯️ 价格走势",
        "蜡烛图为前复权开高低收，叠加 5 / 10 / 20 日简单移动平均线。",
    )

    figure = go.Figure()

    figure.add_trace(
        go.Candlestick(
            x=valid["trade_date"],
            open=valid["open_price"],
            high=valid["high_price"],
            low=valid["low_price"],
            close=valid["close_price"],
            name="K 线",
            increasing_line_color=UP_COLOR,
            increasing_fillcolor=UP_COLOR,
            decreasing_line_color=DOWN_COLOR,
            decreasing_fillcolor=DOWN_COLOR,
        )
    )

    for window, color in ((5, "#F59E0B"), (10, "#3B82F6"), (20, "#8B5CF6")):
        figure.add_trace(
            go.Scatter(
                x=valid["trade_date"],
                y=valid["close_price"].rolling(window, min_periods=window).mean(),
                name=f"MA{window}",
                mode="lines",
                line={"color": color, "width": 1.5},
                hovertemplate="%{x|%Y-%m-%d}<br>MA"
                + str(window)
                + " %{y:.2f}<extra></extra>",
            )
        )

    figure.update_layout(xaxis_rangeslider_visible=False)
    figure.update_yaxes(title_text="价格（元）")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=480)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("stock_candle"),
    )


def _render_volume(valid: pd.DataFrame, start_date, end_date) -> None:
    section("📊 成交量", "柱状为每日成交量，颜色区分当日涨跌。")

    colors = np.where(
        valid["close_price"] >= valid["open_price"], UP_COLOR, DOWN_COLOR
    )

    figure = go.Figure(
        go.Bar(
            x=valid["trade_date"],
            y=valid["volume"],
            marker_color=colors,
            name="成交量",
            hovertemplate="%{x|%Y-%m-%d}<br>成交量 %{y:,.0f} 股<extra></extra>",
        )
    )

    figure.update_yaxes(title_text="成交量（股）")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=300, legend=False)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("stock_volume"),
    )


def _render_return_distribution(valid: pd.DataFrame, start_date, end_date) -> None:
    section("📐 日涨跌幅分布", "统计区间内每个交易日涨跌幅的分布情况。")

    returns = valid["pct_change"].dropna()

    if returns.empty:
        empty_state("区间内没有可用的涨跌幅数据。")
        return

    figure = go.Figure(
        go.Histogram(
            x=returns,
            nbinsx=min(30, max(8, int(np.sqrt(len(returns)) * 2))),
            marker_color=ACCENT_COLOR,
            opacity=0.85,
            hovertemplate="涨跌幅 %{x:.2f}%<br>交易日数 %{y}<extra></extra>",
        )
    )

    figure.add_vline(
        x=0,
        line_dash="dot",
        line_color=NEUTRAL_COLOR,
        annotation_text="0%",
        annotation_position="top",
    )

    figure.update_xaxes(title_text="日涨跌幅（%）")
    figure.update_yaxes(title_text="交易日数")
    apply_theme(figure, height=300, legend=False)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("stock_return_dist"),
    )


def _render_detail_table(valid: pd.DataFrame, selected_stock: pd.Series) -> None:
    section("📋 历史行情明细")

    display = valid.copy()
    display["trade_date"] = display["trade_date"].dt.strftime("%Y-%m-%d")

    display = display.rename(
        columns={
            "trade_date": "交易日期",
            "open_price": "开盘价",
            "high_price": "最高价",
            "low_price": "最低价",
            "close_price": "收盘价",
            "preclose_price": "前收盘价",
            "volume": "成交量（股）",
            "amount": "成交额（元）",
            "turnover_rate": "换手率（%）",
            "pct_change": "涨跌幅（%）",
        }
    )

    display = display[
        [
            "交易日期",
            "开盘价",
            "最高价",
            "最低价",
            "收盘价",
            "前收盘价",
            "涨跌幅（%）",
            "成交量（股）",
            "成交额（元）",
            "换手率（%）",
        ]
    ]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "开盘价": st.column_config.NumberColumn(format="%.4f"),
            "最高价": st.column_config.NumberColumn(format="%.4f"),
            "最低价": st.column_config.NumberColumn(format="%.4f"),
            "收盘价": st.column_config.NumberColumn(format="%.4f"),
            "前收盘价": st.column_config.NumberColumn(format="%.4f"),
            "涨跌幅（%）": st.column_config.NumberColumn(format="%.2f"),
            "成交量（股）": st.column_config.NumberColumn(format="%d"),
            "成交额（元）": st.column_config.NumberColumn(format="%d"),
            "换手率（%）": st.column_config.NumberColumn(format="%.4f"),
        },
    )

    download_button(
        display,
        f"{selected_stock['stock_code']}_历史行情.csv",
        "⬇️ 下载明细 CSV",
        chart_key("stock_download"),
    )
