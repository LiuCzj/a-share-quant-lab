from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard import db  # noqa: E402
from dashboard.pages import ai, industry, market, stock, strategy  # noqa: E402

PAGES = {
    "市场总览": market.render,
    "个股分析": stock.render,
    "行业分析": industry.render,
    "量化策略": strategy.render,
    "AI 智能投研": ai.render,
}


def configure_page() -> None:
    st.set_page_config(
        page_title="A股智能投研与量化分析平台",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def load_context() -> dict:
    try:
        db.check_connection()
        return db.load_meta()
    except (SQLAlchemyError, db.DataUnavailableError, ValueError, TypeError) as error:
        st.error(
            "数据源连接或初始化失败。请确认 data/market.db 已生成，"
            "或 .env 中的 MySQL 连接配置可用。"
        )
        with st.expander("错误详情", expanded=False):
            st.code(f"{type(error).__name__}: {error}")
        st.stop()


def render_sidebar_top(meta: dict) -> str:
    with st.sidebar:
        st.title("📈 A股投研平台")
        st.caption("真实行情 · SQL 分析 · 策略回测")
        st.divider()

        page = st.radio(
            "功能导航",
            options=list(PAGES.keys()),
            label_visibility="collapsed",
        )

    return page


def render_sidebar_bottom(meta: dict) -> None:
    with st.sidebar:
        st.divider()

        st.subheader("📦 数据概览")
        st.caption(
            f"股票数量：{meta['stock_count']:,} 只\n\n"
            f"行情记录：{meta['record_count']:,} 条\n\n"
            f"正常交易：{meta['normal_count']:,} 条　"
            f"停牌：{meta['suspended_count']:,} 条\n\n"
            f"交易日数：{meta['trading_days']} 天\n\n"
            f"数据区间：{meta['min_date']:%Y-%m-%d} 至 "
            f"{meta['max_date']:%Y-%m-%d}"
        )

        with st.expander("数据口径说明", expanded=False):
            st.markdown(
                """
- 数据来源：BaoStock 日线行情，已入库 MySQL `a_share_research`。
- 复权方式：前复权（`adjust_flag = 2`）。
- 交易状态：仅 `trade_status = '1'` 的记录计入涨跌、成交额与收益统计。
- 行业分类：证监会行业门类，取自 `stock_info`，为当前时点分类。
- 基准定义：全市场等权、每日再平衡，不含交易成本，不等同于任何公开指数。
"""
            )

        if st.button("🔄 重新加载数据", width="stretch"):
            st.cache_data.clear()
            st.rerun()

        st.caption("查询结果会缓存 30 分钟；重新导入数据后点上方按钮刷新。")

        st.divider()
        st.caption("仅用于数据分析与研究，不构成投资建议。")


def main() -> None:
    configure_page()

    st.title("📈 A 股智能投研与量化分析平台")
    st.caption(
        "以真实 A 股行情数据为基础，覆盖市场分析、个股研究、"
        "行业对比与策略回测"
    )

    meta = load_context()
    page = render_sidebar_top(meta)

    PAGES[page](meta)

    render_sidebar_bottom(meta)

    st.divider()
    st.caption(
        f"A股智能投研与量化分析平台　|　"
        f"数据区间 {meta['min_date']:%Y-%m-%d} ~ "
        f"{meta['max_date']:%Y-%m-%d}　|　"
        f"共 {meta['stock_count']:,} 只股票、"
        f"{meta['record_count']:,} 条行情记录　|　"
        "本平台用于数据分析与研究，不构成投资建议"
    )


main()
