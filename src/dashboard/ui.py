from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import db

UP_COLOR = "#E5484D"
DOWN_COLOR = "#12A150"
NEUTRAL_COLOR = "#8B949E"
ACCENT_COLOR = "#3B82F6"
BENCHMARK_COLOR = "#8B5CF6"

FONT_FAMILY = (
    "Microsoft YaHei, PingFang SC, Hiragino Sans GB, "
    "Source Han Sans SC, sans-serif"
)


def chart_key(prefix: str, *_ignored: object) -> str:
    # 组件 key 必须跨 rerun 保持稳定：key 变化会让 Streamlit 卸载并重新挂载
    # 组件，plotly 实例可能不再接收新的 figure，表现为筛选后图表不更新。
    return f"chart_{prefix}"


def apply_theme(fig: go.Figure, height: int = 420, legend: bool = True) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 12, "r": 12, "t": 56, "b": 12},
        font={"family": FONT_FAMILY, "size": 13, "color": "#1F2328"},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": 12}},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=legend,
    )

    if legend:
        fig.update_layout(
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "left",
                "x": 0,
                "font": {"size": 12},
            }
        )

    fig.update_xaxes(
        showgrid=False,
        linecolor="#D0D7DE",
        zeroline=False,
        title_font={"size": 12},
    )
    fig.update_yaxes(
        gridcolor="#EEF1F4",
        zeroline=False,
        linecolor="#D0D7DE",
        title_font={"size": 12},
    )

    return fig


def format_amount_yi(value: float) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.2f} 亿元"


def format_int(value: float) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{int(round(value)):,}"


def format_pct(value: float, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.{digits}f}%"


def format_price(value: float, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{digits}f}"


def metric_row(items: list[tuple[str, str, str | None]]) -> None:
    if not items:
        return

    columns = st.columns(len(items))

    for column, item in zip(columns, items):
        label, value = item[0], item[1]
        help_text = item[2] if len(item) > 2 else None
        column.metric(label, value, help=help_text)


def empty_state(message: str) -> None:
    st.info(message)


def note(text: str) -> None:
    st.caption(text)


def section(title: str, description: str | None = None) -> None:
    st.subheader(title)
    if description:
        st.caption(description)


def download_button(frame: pd.DataFrame, filename: str, label: str, key: str) -> None:
    if frame.empty:
        return

    csv_bytes = frame.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=label,
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def date_range_filter(meta: dict, page_key: str) -> tuple:
    stored_start = f"_{page_key}_stored_start"
    stored_end = f"_{page_key}_stored_end"
    widget_start = f"{page_key}_start_date"
    widget_end = f"{page_key}_end_date"

    st.session_state.setdefault(stored_start, meta["min_date"])
    st.session_state.setdefault(stored_end, meta["max_date"])

    if widget_start not in st.session_state:
        st.session_state[widget_start] = st.session_state[stored_start]
    if widget_end not in st.session_state:
        st.session_state[widget_end] = st.session_state[stored_end]

    def _remember() -> None:
        st.session_state[stored_start] = st.session_state[widget_start]
        st.session_state[stored_end] = st.session_state[widget_end]

    columns = st.columns([1, 1, 2])

    start_date = columns[0].date_input(
        "开始日期",
        min_value=meta["min_date"],
        max_value=meta["max_date"],
        key=widget_start,
        on_change=_remember,
    )
    end_date = columns[1].date_input(
        "结束日期",
        min_value=meta["min_date"],
        max_value=meta["max_date"],
        key=widget_end,
        on_change=_remember,
    )
    columns[2].caption(
        f"数据库可用范围：{meta['min_date']:%Y-%m-%d} 至 "
        f"{meta['max_date']:%Y-%m-%d}，共 {meta['trading_days']} 个交易日"
    )

    validate_date_range(start_date, end_date)
    warn_non_trading_days(start_date, end_date)

    return start_date, end_date


def validate_date_range(start_date, end_date) -> None:
    if start_date > end_date:
        st.error("开始日期不能晚于结束日期，请重新选择。")
        st.stop()

    if start_date == end_date:
        st.warning(
            "当前只选择了单个交易日。市场成交额与涨跌家数仍可查看，"
            "但区间收益率、最大回撤等需要两个及以上交易日的指标会失真。"
        )


def warn_non_trading_days(start_date, end_date) -> None:
    trading_dates = db.load_trading_dates()
    if not trading_dates:
        return

    if start_date not in trading_dates:
        next_date = next(
            (item for item in trading_dates if item >= start_date), None
        )
        if next_date is None:
            st.info(
                f"开始日期 {start_date:%Y-%m-%d} 之后没有任何交易日数据。"
            )
        else:
            st.info(
                f"开始日期 {start_date:%Y-%m-%d} 不是交易日"
                f"（可能是周末或节假日），实际统计从 "
                f"{next_date:%Y-%m-%d} 开始。"
            )

    if end_date not in trading_dates:
        previous_date = next(
            (item for item in reversed(trading_dates) if item <= end_date),
            None,
        )
        if previous_date is None:
            st.info(
                f"结束日期 {end_date:%Y-%m-%d} 之前没有任何交易日数据。"
            )
        else:
            st.info(
                f"结束日期 {end_date:%Y-%m-%d} 不是交易日"
                f"（可能是周末或节假日），实际统计到 "
                f"{previous_date:%Y-%m-%d} 结束。"
            )
