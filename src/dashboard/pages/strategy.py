from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .. import backtest, db
from ..ui import (
    ACCENT_COLOR,
    BENCHMARK_COLOR,
    DOWN_COLOR,
    NEUTRAL_COLOR,
    UP_COLOR,
    apply_theme,
    chart_key,
    date_range_filter,
    download_button,
    empty_state,
    metric_row,
    section,
)


def render(meta: dict) -> None:
    st.header("🧪 量化策略研究")
    st.caption(
        "在真实行情上执行可复现的策略回测，包含交易成本、次日开盘成交、"
        "基准对照与风险指标。"
    )

    start_date, end_date = date_range_filter(meta, "strategy")

    settings = _render_parameters(meta)
    if settings is None:
        return

    open_matrix, close_matrix = db.load_price_matrices(start_date, end_date)

    if close_matrix.empty or len(close_matrix) < 3:
        empty_state("所选区间内的可交易数据不足，无法回测。")
        return

    _render_sample_warning(close_matrix, start_date, end_date)

    weights, description = _build_weights(settings, close_matrix)

    if weights is None:
        return

    cost_model = backtest.CostModel(
        commission=settings["commission"],
        stamp_tax=settings["stamp_tax"],
        slippage=settings["slippage"],
    )

    try:
        result = backtest.run_backtest(
            open_matrix, close_matrix, weights, cost_model
        )
    except ValueError as error:
        st.error(f"回测执行失败：{error}")
        return

    st.caption(description)

    _render_metrics(result)
    st.divider()
    _render_equity_curve(result)
    _render_drawdown(result)
    _render_exposure(result)
    _render_trades(result)


def _render_parameters(meta: dict) -> dict | None:
    with st.container(border=True):
        st.markdown("**⚙️ 策略参数**")

        strategy_name = st.radio(
            "策略类型",
            options=["横截面动量轮动", "双均线择时"],
            horizontal=True,
            key="strategy_type",
        )

        settings: dict = {"strategy": strategy_name}

        if strategy_name == "横截面动量轮动":
            columns = st.columns(3)
            settings["lookback"] = columns[0].slider(
                "动量回看窗口（交易日）",
                min_value=5,
                max_value=60,
                value=20,
                step=1,
                key="momentum_lookback",
                help="以过去 N 个交易日的累计涨幅作为动量因子。",
            )
            settings["top_n"] = columns[1].slider(
                "持仓股票数",
                min_value=3,
                max_value=50,
                value=10,
                step=1,
                key="momentum_top_n",
            )
            settings["rebalance_days"] = columns[2].slider(
                "调仓间隔（交易日）",
                min_value=1,
                max_value=20,
                value=5,
                step=1,
                key="momentum_rebalance",
            )
        else:
            stock_list = db.load_stock_list()
            if stock_list.empty:
                st.warning("股票基础信息为空，无法选择标的。")
                return None

            columns = st.columns([1, 2, 1, 1])

            exchange_options = ["全部"] + sorted(
                stock_list["exchange_name"].dropna().unique().tolist()
            )
            exchange = columns[0].selectbox(
                "交易所",
                options=exchange_options,
                index=0,
                key="ma_exchange",
            )

            pool = stock_list
            if exchange != "全部":
                pool = pool[pool["exchange_name"] == exchange]

            if pool.empty:
                columns[1].warning("该交易所下没有股票数据。")
                return None

            selected_label = columns[1].selectbox(
                "搜索并选择标的",
                options=pool["display_name"].tolist(),
                index=0,
                key="ma_stock",
                help="点击后直接输入股票代码或名称片段，列表会自动过滤。",
            )

            selected_row = pool.loc[
                pool["display_name"] == selected_label
            ].iloc[0]

            fast_window = columns[2].slider(
                "快线窗口",
                min_value=3,
                max_value=30,
                value=5,
                step=1,
                key="ma_fast",
            )
            slow_window = columns[3].slider(
                "慢线窗口",
                min_value=10,
                max_value=120,
                value=20,
                step=1,
                key="ma_slow",
            )

            if fast_window >= slow_window:
                st.error("快线窗口必须小于慢线窗口。")
                return None

            settings["stock_code"] = selected_row["stock_code"]
            settings["stock_label"] = selected_label
            settings["fast_window"] = fast_window
            settings["slow_window"] = slow_window

        st.divider()
        st.markdown("**💰 交易成本**")

        cost_columns = st.columns(3)

        settings["commission"] = (
            cost_columns[0].number_input(
                "佣金（‰，双向）",
                min_value=0.0,
                max_value=5.0,
                value=0.3,
                step=0.1,
                format="%.2f",
                key="cost_commission",
            )
            / 1000
        )
        settings["stamp_tax"] = (
            cost_columns[1].number_input(
                "印花税（‰，仅卖出）",
                min_value=0.0,
                max_value=5.0,
                value=0.5,
                step=0.1,
                format="%.2f",
                key="cost_stamp_tax",
            )
            / 1000
        )
        settings["slippage"] = (
            cost_columns[2].number_input(
                "滑点（‰，双向）",
                min_value=0.0,
                max_value=10.0,
                value=1.0,
                step=0.1,
                format="%.2f",
                key="cost_slippage",
            )
            / 1000
        )

    return settings


def _render_sample_warning(
    close_matrix: pd.DataFrame, start_date, end_date
) -> None:
    st.warning(
        f"⚠️ 回测区间仅有 **{len(close_matrix)} 个交易日**"
        f"（{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d}）。"
        "样本期极短，年化收益率、夏普比率等指标会被显著放大，"
        "任何收益结论都不具备统计意义。"
        "本页面的作用是验证回测链路与指标计算是否正确，"
        "不能作为策略有效性的证据。"
    )


def _build_weights(settings: dict, close_matrix: pd.DataFrame):
    strategy_name = settings["strategy"]

    if strategy_name == "横截面动量轮动":
        lookback = settings["lookback"]

        if len(close_matrix) <= lookback + 1:
            st.error(
                f"回测区间只有 {len(close_matrix)} 个交易日，"
                f"不足以支撑 {lookback} 日的动量回看窗口。"
                "请缩短回看窗口或扩大日期区间。"
            )
            return None, ""

        weights = backtest.momentum_rebalance_weights(
            close_matrix,
            lookback=lookback,
            top_n=settings["top_n"],
            rebalance_days=settings["rebalance_days"],
        )

        description = (
            f"策略规则：每 {settings['rebalance_days']} 个交易日，"
            f"按过去 {lookback} 个交易日累计涨幅排序，"
            f"买入涨幅最高的 {settings['top_n']} 只股票并等权持有，"
            "信号于调仓日收盘产生，次日开盘执行。"
        )
    else:
        stock_code = settings["stock_code"]
        label = settings["stock_label"]

        if stock_code not in close_matrix.columns:
            st.error(f"{label} 在所选区间内没有可交易记录，无法回测。")
            return None, ""

        weights = backtest.ma_crossover_rebalance_weights(
            close_matrix,
            stock_code,
            fast_window=settings["fast_window"],
            slow_window=settings["slow_window"],
        )

        description = (
            f"策略规则：{label} 的 "
            f"MA{settings['fast_window']} 上穿 "
            f"MA{settings['slow_window']} 时满仓持有，"
            "下穿时清仓转为现金，信号于收盘产生，次日开盘执行。"
        )

    if not weights:
        st.warning(
            "当前参数在所选区间内没有产生任何调仓信号，"
            "请调整参数或扩大日期区间。"
        )
        return None, ""

    return weights, description


def _format_value(value: float, as_percent: bool) -> str:
    if value is None or pd.isna(value):
        return "—"
    if as_percent:
        return f"{value * 100:+.2f}%"
    return f"{value:.2f}"


def _render_metrics(result: backtest.BacktestResult) -> None:
    strategy = result.stats
    benchmark = result.benchmark_stats

    pairs = [
        ("累计收益率", "total_return", True),
        ("年化收益率", "annual_return", True),
        ("最大回撤", "max_drawdown", True),
        ("夏普比率", "sharpe", False),
    ]

    columns = st.columns(len(pairs))
    for column, (label, key, as_percent) in zip(columns, pairs):
        column.metric(label, _format_value(strategy[key], as_percent))
        column.caption(f"基准：{_format_value(benchmark[key], as_percent)}")

    total_cost = float(result.costs.sum())

    metric_row(
        [
            (
                "年化波动率",
                f"{strategy['volatility'] * 100:.2f}%"
                if not pd.isna(strategy["volatility"])
                else "—",
                f"基准：{benchmark['volatility'] * 100:.2f}%",
            ),
            (
                "日胜率",
                f"{strategy['win_rate'] * 100:.2f}%"
                if not pd.isna(strategy["win_rate"])
                else "—",
                "剔除空仓日后的日收益为正比例",
            ),
            (
                "平均仓位",
                f"{result.exposure.mean() * 100:.2f}%",
                "持仓市值占组合净值的平均比例，剩余为现金；"
                "动量策略包含信号预热期的空仓日，因此会低于满仓",
            ),
            (
                "累计交易成本",
                f"{total_cost * 100:.2f}%",
                "按每次调仓的换手权重与费率逐笔计提，直接从组合净值中扣除",
            ),
        ]
    )

    st.caption(
        f"回测交易日 {strategy['days']} 天；"
        f"调仓次数 {len(result.rebalance_dates)} 次；"
        f"成交笔数 {len(result.trades)} 笔；"
        f"基准为每日等权持有全部可交易股票、不含交易成本。"
    )


def _render_equity_curve(result: backtest.BacktestResult) -> None:
    section(
        "📈 策略净值与基准对比",
        "策略净值已扣除佣金、印花税与滑点；基准为全市场等权组合，不含成本。",
    )

    figure = go.Figure()

    figure.add_trace(
        go.Scatter(
            x=result.net_value.index,
            y=result.net_value,
            name="策略净值",
            mode="lines",
            line={"color": ACCENT_COLOR, "width": 2.6},
            hovertemplate="%{x|%Y-%m-%d}<br>策略 %{y:.4f}<extra></extra>",
        )
    )

    figure.add_trace(
        go.Scatter(
            x=result.benchmark_value.index,
            y=result.benchmark_value,
            name="等权基准",
            mode="lines",
            line={"color": BENCHMARK_COLOR, "width": 1.8, "dash": "dash"},
            hovertemplate="%{x|%Y-%m-%d}<br>基准 %{y:.4f}<extra></extra>",
        )
    )

    figure.add_hline(y=1.0, line_dash="dot", line_color=NEUTRAL_COLOR)

    figure.update_yaxes(title_text="净值")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=420)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("strategy_nav"),
    )


def _render_drawdown(result: backtest.BacktestResult) -> None:
    section("📉 回撤曲线", "净值相对历史最高点的回撤幅度。")

    figure = go.Figure()

    figure.add_trace(
        go.Scatter(
            x=result.drawdown.index,
            y=result.drawdown * 100,
            name="策略回撤",
            mode="lines",
            line={"color": DOWN_COLOR, "width": 2},
            fill="tozeroy",
            fillcolor="rgba(18,161,80,0.12)",
            hovertemplate="%{x|%Y-%m-%d}<br>策略回撤 %{y:.2f}%<extra></extra>",
        )
    )

    figure.add_trace(
        go.Scatter(
            x=result.benchmark_drawdown.index,
            y=result.benchmark_drawdown * 100,
            name="基准回撤",
            mode="lines",
            line={"color": BENCHMARK_COLOR, "width": 1.6, "dash": "dash"},
            hovertemplate="%{x|%Y-%m-%d}<br>基准回撤 %{y:.2f}%<extra></extra>",
        )
    )

    figure.update_yaxes(title_text="回撤（%）")
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=320)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("strategy_drawdown"),
    )


def _render_exposure(result: backtest.BacktestResult) -> None:
    section(
        "🎯 持仓数量与仓位",
        "柱状为当日持仓股票数，折线为持仓市值占组合净值的比例。",
    )

    figure = make_subplots(specs=[[{"secondary_y": True}]])

    figure.add_trace(
        go.Bar(
            x=result.holding_count.index,
            y=result.holding_count.values,
            name="持仓股票数",
            marker_color="#BFDBFE",
            hovertemplate="%{x|%Y-%m-%d}<br>持仓 %{y} 只<extra></extra>",
        ),
        secondary_y=False,
    )

    figure.add_trace(
        go.Scatter(
            x=result.exposure.index,
            y=result.exposure.values * 100,
            name="仓位",
            mode="lines",
            line={"color": UP_COLOR, "width": 2},
            hovertemplate="%{x|%Y-%m-%d}<br>仓位 %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )

    figure.update_yaxes(title_text="持仓股票数（只）", secondary_y=False)
    figure.update_yaxes(
        title_text="仓位（%）",
        secondary_y=True,
        range=[0, 105],
        showgrid=False,
    )
    figure.update_xaxes(title_text="交易日期")
    apply_theme(figure, height=300)

    st.plotly_chart(
        figure,
        width="stretch",
        key=chart_key("strategy_exposure"),
    )


def _render_trades(result: backtest.BacktestResult) -> None:
    section("📋 成交明细", "每一笔调仓的股票、方向、权重变化与执行价。")

    if result.trades.empty:
        empty_state("回测期间没有产生任何成交。")
        return

    display = result.trades.copy()
    display["执行日期"] = pd.to_datetime(display["执行日期"]).dt.strftime(
        "%Y-%m-%d"
    )
    display["权重变化"] = (display["权重变化"] * 100).round(4)

    display = display.rename(columns={"权重变化": "权重变化（%）"})

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "权重变化（%）": st.column_config.NumberColumn(format="%.4f"),
            "执行价": st.column_config.NumberColumn(format="%.4f"),
        },
    )

    download_button(
        display,
        "策略成交明细.csv",
        "⬇️ 下载成交明细 CSV",
        chart_key("strategy_trades"),
    )

    with st.expander("回测方法与已知限制", expanded=False):
        st.markdown(
            """
**成交时点**

- 调仓信号在决策日收盘后使用当日及历史数据计算，不存在未来函数。
- 成交发生在下一个交易日的开盘价，组合收益拆分为隔夜跳空与日内两段。
- 停牌标的无法建仓，其目标权重自动转为现金；已持仓标的停牌时无法卖出，权重保持不变。

**成本假设**

- 佣金双向计提，印花税仅在卖出时计提，滑点双向计提，费率可在上方调整。
- 成本按每次调仓的权重变化直接扣减组合净值。

**已知限制**

- 样本区间只有一个季度，年化指标被放大，结论不具备统计意义。
- 股票池取自 2025-01-02 的股票列表，存在幸存者偏差。
- 未考虑涨跌停无法成交、停牌复牌跳空、分红送转的现金处理。
- 行业分类为当前时点分类，非历史分类。
- 基准为每日等权全市场组合，不含交易成本，也不等同于任何公开指数。
            """
        )
