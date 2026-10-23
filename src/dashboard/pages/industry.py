from __future__ import annotations

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
    format_int,
    format_pct,
    metric_row,
    section,
)

LINE_PALETTE = [
    "#3B82F6",
    "#E5484D",
    "#12A150",
    "#F59E0B",
    "#8B5CF6",
    "#0891B2",
    "#DB2777",
    "#65A30D",
    "#EA580C",
    "#4F46E5",
]


def render(meta: dict) -> None:
    st.header("🏭 行业分析")
    st.caption(
        "行业分类取自 stock_info 的证监会行业门类，"
        "行业收益率为区间内成分股等权平均的个股收益率。"
    )

    start_date, end_date = date_range_filter(meta, "industry")

    stock_count = db.load_industry_stock_count()
    returns = db.load_industry_returns(start_date, end_date)

    if stock_count.empty:
        empty_state("没有可用的行业分类数据。")
        return

    if returns.empty:
        empty_state(
            "所选日期范围内没有足够的有效行情记录来计算行业收益率，"
            "请扩大日期区间。"
        )
        return

    _render_metrics(returns)
    st.divider()

    _render_stock_count_chart(stock_count)
    _render_return_ranking(returns, start_date, end_date)
    _render_nav_comparison(start_date, end_date, returns)
    _render_detail_table(returns)


def _render_metrics(returns: pd.DataFrame) -> None:
    total_industries = len(returns)
    total_stocks = int(returns["stock_count"].sum())

    rising = int((returns["avg_return_pct"] > 0).sum())
    falling = int((returns["avg_return_pct"] < 0).sum())

    best = returns.iloc[0]
    worst = returns.iloc[-1]

    metric_row(
        [
            ("行业类别数", f"{total_industries} 个", None),
            ("覆盖股票数", f"{format_int(total_stocks)} 只", None),
            (
                "区间上涨行业",
                f"{rising} 个",
                f"区间平均收益率为正的行业数量，下跌 {falling} 个",
            ),
            (
                "行业涨跌比例",
                f"{rising}:{falling}",
                "上涨行业数 : 下跌行业数",
            ),
        ]
    )

    metric_row(
        [
            (
                "表现最强行业",
                str(best["industry_label"]),
                f"区间平均收益率 {best['avg_return_pct']:.2f}%",
            ),
            ("最强行业收益", format_pct(float(best["avg_return_pct"])), None),
            (
                "表现最弱行业",
                str(worst["industry_label"]),
                f"区间平均收益率 {worst['avg_return_pct']:.2f}%",
            ),
            ("最弱行业收益", format_pct(float(worst["avg_return_pct"])), None),
        ]
    )


def _render_stock_count_chart(stock_count: pd.DataFrame) -> None:
    section("🏢 行业股票数量分布", "按行业统计当前股票池中的成分股数量。")

    max_n = len(stock_count)
    default_n = min(15, max_n)

    top_n = st.slider(
        "显示股票数量最多的行业个数",
        min_value=1,
        max_value=max_n,
        value=default_n,
        step=1,
        key="industry_count_top_n",
    )

    selected = (
        stock_count.head(top_n).sort_values("stock_count", ascending=True)
    )

    figure = go.Figure(
        go.Bar(
            x=selected["stock_count"],
            y=selected["industry_label"],
            orientation="h",
            marker_color=ACCENT_COLOR,
            opacity=0.85,
            hovertemplate="%{y}<br>%{x} 只<extra></extra>",
        )
    )

    figure.update_xaxes(title_text="股票数量（只）")
    figure.update_yaxes(title_text="")
    apply_theme(
        figure,
        height=max(320, 26 * len(selected) + 120),
        legend=False,
    )

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("industry_count", top_n, len(stock_count)),
    )


def _render_return_ranking(
    returns: pd.DataFrame, start_date, end_date
) -> None:
    section(
        "🏆 行业区间收益率排名",
        "个股收益率 = 区间内首个有效交易日收盘价到最后一个有效交易日收盘价的变化，"
        "再对行业内成分股取等权平均。",
    )

    max_n = max(1, len(returns) // 2)
    default_n = min(10, max_n)

    top_n = st.slider(
        "分别显示最强与最弱的行业个数",
        min_value=1,
        max_value=max_n,
        value=default_n,
        step=1,
        key="industry_return_top_n",
    )

    ordered = returns.sort_values("avg_return_pct", ascending=False)

    if len(ordered) <= top_n * 2:
        selected = ordered
    else:
        selected = pd.concat(
            [ordered.head(top_n), ordered.tail(top_n)]
        ).drop_duplicates(subset=["industry_label"])

    selected = selected.sort_values("avg_return_pct", ascending=True)

    colors = [
        UP_COLOR if value > 0 else DOWN_COLOR
        for value in selected["avg_return_pct"]
    ]

    figure = go.Figure(
        go.Bar(
            x=selected["avg_return_pct"],
            y=selected["industry_label"],
            orientation="h",
            marker_color=colors,
            hovertemplate="%{y}<br>区间平均收益率 %{x:.2f}%<extra></extra>",
        )
    )

    figure.add_vline(x=0, line_dash="dot", line_color=NEUTRAL_COLOR)

    figure.update_xaxes(title_text="区间平均收益率（%）")
    figure.update_yaxes(title_text="")
    apply_theme(
        figure,
        height=max(340, 26 * len(selected) + 120),
        legend=False,
    )

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key(
            "industry_return_rank", top_n, start_date, end_date
        ),
    )

    st.caption("红色为上涨行业，绿色为下跌行业。")


def _render_nav_comparison(
    start_date, end_date, returns: pd.DataFrame
) -> None:
    section(
        "📈 行业累计净值对比",
        "以行业内成分股每日涨跌幅等权平均后逐日复利，起点归一为 1.00，"
        "属于每日再平衡的等权组合，不含交易成本。",
    )

    nav_matrix = db.load_industry_daily_nav(start_date, end_date)

    if nav_matrix.empty:
        empty_state("所选区间内没有足够的行业行情数据。")
        return

    available = [
        column
        for column in nav_matrix.columns
        if column in set(returns["industry_label"])
    ]

    if not available:
        empty_state("没有可对比的行业。")
        return

    default_selection = (
        returns.sort_values("stock_count", ascending=False)["industry_label"]
        .head(5)
        .tolist()
    )
    default_selection = [
        item for item in default_selection if item in available
    ]

    selected_industries = st.multiselect(
        "选择要对比的行业（最多 10 个）",
        options=available,
        default=default_selection,
        max_selections=10,
        key="industry_nav_selection",
    )

    if not selected_industries:
        st.info("请至少选择一个行业。")
        return

    figure = go.Figure()

    for index, industry in enumerate(selected_industries):
        series = nav_matrix[industry].dropna()
        if series.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                name=industry,
                mode="lines",
                line={
                    "color": LINE_PALETTE[index % len(LINE_PALETTE)],
                    "width": 2,
                },
                hovertemplate="%{x|%Y-%m-%d}<br>净值 %{y:.4f}<extra></extra>",
            )
        )

    figure.add_hline(
        y=1.0,
        line_dash="dot",
        line_color=NEUTRAL_COLOR,
    )

    figure.update_yaxes(title_text="净值")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=420)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key(
            "industry_nav",
            start_date,
            end_date,
            ",".join(sorted(selected_industries)),
        ),
    )


def _render_detail_table(returns: pd.DataFrame) -> None:
    section("📋 行业区间表现明细")

    display = returns.copy().rename(
        columns={
            "industry_label": "行业名称",
            "stock_count": "成分股数",
            "avg_return_pct": "区间平均收益率（%）",
            "median_return_pct": "区间收益率中位数（%）",
            "up_stock_count": "区间上涨股票数",
            "up_stock_ratio": "上涨股票占比（%）",
        }
    )

    display = display[
        [
            "行业名称",
            "成分股数",
            "区间平均收益率（%）",
            "区间收益率中位数（%）",
            "区间上涨股票数",
            "上涨股票占比（%）",
        ]
    ]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "成分股数": st.column_config.NumberColumn(format="%d"),
            "区间平均收益率（%）": st.column_config.NumberColumn(format="%.2f"),
            "区间收益率中位数（%）": st.column_config.NumberColumn(format="%.2f"),
            "区间上涨股票数": st.column_config.NumberColumn(format="%d"),
            "上涨股票占比（%）": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    download_button(
        display,
        "行业区间表现.csv",
        "⬇️ 下载明细 CSV",
        chart_key("industry_download", len(display)),
    )

    st.caption(
        "注意：行业分类使用当前时点的股票行业信息，不代表历史区间的真实行业构成；"
        "区间内停牌或缺少有效价格的交易日会被剔除，"
        "因此每只股票的收益率区间起点可能不同。"
        "行业名称前的字母数字（如 C39）为证监会行业代码，"
        "缺少行业信息的股票统一归入「未分类」。"
    )
