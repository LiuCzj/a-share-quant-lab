from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

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
    format_int,
    format_pct,
    metric_row,
    section,
)


def render(meta: dict) -> None:
    st.header("📊 A 股市场总览")
    st.caption(
        "基于真实日线行情的全市场统计。所有指标仅统计正常交易状态"
        "（trade_status = 1）的记录。"
    )

    start_date, end_date = date_range_filter(meta, "market")
    daily = db.load_market_daily(start_date, end_date)

    if daily.empty:
        empty_state(
            "所选日期范围内没有任何交易日记录。"
            "请确认区间内包含交易日——周末与法定节假日没有行情数据。"
        )
        return

    _render_metrics(daily, start_date, end_date)
    st.divider()
    _render_amount_chart(daily, start_date, end_date)
    _render_breadth_chart(daily, start_date, end_date)
    _render_equity_curve(daily, start_date, end_date)
    _render_detail_table(daily)


def _render_metrics(daily: pd.DataFrame, start_date, end_date) -> None:
    total_amount = float(daily["amount_yi"].sum())
    average_amount = float(daily["amount_yi"].mean())
    trading_days = len(daily)

    nav = (1 + daily["avg_pct_change"] / 100).cumprod()
    interval_return = float(nav.iloc[-1] - 1) * 100

    latest = daily.iloc[-1]

    metric_row(
        [
            ("区间交易日", f"{trading_days} 天", None),
            (
                "区间日均成交额",
                format_amount_yi(average_amount),
                "区间内每日成交额的算术平均值",
            ),
            (
                "区间成交额合计",
                format_amount_yi(total_amount),
                "区间内所有正常交易记录的成交额之和",
            ),
            (
                "区间等权累计收益",
                format_pct(interval_return),
                "每日对全部可交易股票等权再平衡的组合收益，不含交易成本",
            ),
        ]
    )

    metric_row(
        [
            (
                "最近交易日",
                latest["trade_date"].strftime("%Y-%m-%d"),
                None,
            ),
            (
                "最近交易日平均涨跌幅",
                format_pct(float(latest["avg_pct_change"])),
                "该日全部可交易股票涨跌幅的算术平均值",
            ),
            (
                "最近交易日涨跌家数",
                f"{format_int(latest['up_count'])} / "
                f"{format_int(latest['down_count'])}",
                "上涨家数 / 下跌家数",
            ),
            (
                "区间平均上涨占比",
                f"{daily['up_ratio'].mean():.1f}%",
                "每个交易日上涨家数占可交易股票数的比例，再对交易日取平均",
            ),
        ]
    )


def _render_amount_chart(daily: pd.DataFrame, start_date, end_date) -> None:
    section("💰 每日市场成交额", "柱状为当日成交额，折线为 5 个交易日移动平均。")

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=daily["trade_date"],
            y=daily["amount_yi"],
            name="日成交额",
            marker_color="#BFDBFE",
            hovertemplate="%{x|%Y-%m-%d}<br>成交额 %{y:,.2f} 亿元<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=daily["trade_date"],
            y=daily["amount_ma5"],
            name="5 日均值",
            mode="lines",
            line={"color": ACCENT_COLOR, "width": 2.4},
            hovertemplate="%{x|%Y-%m-%d}<br>5 日均值 %{y:,.2f} 亿元<extra></extra>",
        )
    )

    figure.update_yaxes(title_text="成交额（亿元）")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=380)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("market_amount", start_date, end_date),
    )


def _render_breadth_chart(daily: pd.DataFrame, start_date, end_date) -> None:
    section(
        "📈 每日涨跌家数",
        "堆叠柱为上涨、下跌、平盘家数，折线为上涨家数占当日可交易股票的比例。",
    )

    figure = make_subplots(specs=[[{"secondary_y": True}]])

    figure.add_trace(
        go.Scatter(
            x=daily["trade_date"],
            y=daily["up_ratio"],
            name="上涨占比",
            mode="lines+markers",
            line={"color": "#B45309", "width": 2},
            marker={"size": 5},
            hovertemplate="%{x|%Y-%m-%d}<br>上涨占比 %{y:.2f}%<extra></extra>",
        ),
        secondary_y=True,
    )

    for column, label, color in (
        ("flat_count", "平盘", NEUTRAL_COLOR),
        ("down_count", "下跌", DOWN_COLOR),
        ("up_count", "上涨", UP_COLOR),
    ):
        figure.add_trace(
            go.Bar(
                x=daily["trade_date"],
                y=daily[column],
                name=label,
                marker_color=color,
                hovertemplate="%{x|%Y-%m-%d}<br>"
                + label
                + " %{y:,.0f} 只<extra></extra>",
            ),
            secondary_y=False,
        )

    figure.update_layout(barmode="stack")
    figure.update_yaxes(title_text="股票数量（只）", secondary_y=False)
    figure.update_yaxes(
        title_text="上涨占比（%）",
        secondary_y=True,
        range=[0, 100],
        showgrid=False,
    )
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=400)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("market_breadth", start_date, end_date),
    )


def _render_equity_curve(daily: pd.DataFrame, start_date, end_date) -> None:
    section(
        "📉 全市场等权累计净值",
        "以每个交易日全部可交易股票等权持有、每日再平衡的方式计算，"
        "起点归一为 1.00，不含交易成本。该曲线用于观察市场整体赚钱效应，"
        "不是任何指数。",
    )

    nav = (1 + daily["avg_pct_change"] / 100).cumprod()

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=daily["trade_date"],
            y=nav,
            name="等权净值",
            mode="lines",
            line={"color": ACCENT_COLOR, "width": 2.4},
            hovertemplate="%{x|%Y-%m-%d}<br>净值 %{y:.4f}<extra></extra>",
        )
    )
    figure.add_hline(
        y=1.0,
        line_dash="dot",
        line_color=NEUTRAL_COLOR,
        annotation_text="起点 1.00",
        annotation_position="bottom right",
    )

    figure.update_yaxes(title_text="净值")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=360, legend=False)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("market_nav", start_date, end_date),
    )


def _render_detail_table(daily: pd.DataFrame) -> None:
    section("📋 每日市场数据明细")

    display = daily.copy()
    display["trade_date"] = display["trade_date"].dt.strftime("%Y-%m-%d")

    display = display.rename(
        columns={
            "trade_date": "交易日期",
            "amount_yi": "成交额（亿元）",
            "amount_ma5": "成交额5日均值（亿元）",
            "up_count": "上涨家数",
            "down_count": "下跌家数",
            "flat_count": "平盘家数",
            "trading_count": "可交易股票数",
            "up_ratio": "上涨占比（%）",
            "avg_pct_change": "平均涨跌幅（%）",
        }
    )

    display = display[
        [
            "交易日期",
            "成交额（亿元）",
            "成交额5日均值（亿元）",
            "上涨家数",
            "下跌家数",
            "平盘家数",
            "可交易股票数",
            "上涨占比（%）",
            "平均涨跌幅（%）",
        ]
    ]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "成交额（亿元）": st.column_config.NumberColumn(format="%.2f"),
            "成交额5日均值（亿元）": st.column_config.NumberColumn(format="%.2f"),
            "上涨家数": st.column_config.NumberColumn(format="%d"),
            "下跌家数": st.column_config.NumberColumn(format="%d"),
            "平盘家数": st.column_config.NumberColumn(format="%d"),
            "可交易股票数": st.column_config.NumberColumn(format="%d"),
            "上涨占比（%）": st.column_config.NumberColumn(format="%.2f"),
            "平均涨跌幅（%）": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    download_button(
        display,
        "市场每日统计.csv",
        "⬇️ 下载明细 CSV",
        chart_key("market_download", len(display)),
    )

    st.caption(
        "口径说明：上涨 + 下跌 + 平盘 = 可交易股票数；"
        "停牌记录（trade_status = 0）不计入任何涨跌家数，也不计入成交额。"
    )
