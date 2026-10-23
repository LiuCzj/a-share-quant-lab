from __future__ import annotations

import streamlit as st

from ..ui import section


def render(meta: dict) -> None:
    st.header("🤖 AI 智能投研")
    st.caption(
        "目标：让大模型基于本项目真实数据库回答问题，"
        "而不是脱离数据凭空生成内容。"
    )

    st.warning(
        "**本页面尚未实现。** 当前没有任何可用的问答功能，"
        "下方内容为设计规划，不代表已完成的能力。"
    )

    st.divider()

    section(
        "🎯 设计目标",
        "把自然语言问题翻译成受控的数据查询，再由大模型组织结论。",
    )

    st.markdown(
        """
用户提出问题时，系统不应直接让模型作答，而应走完这条链路：

1. 解析问题，识别需要的数据范围、指标和维度；
2. 调用受控的数据查询工具，从 `stock_daily` / `stock_info` 取数；
3. 由代码完成计算，得到可复核的数值结果；
4. 把查询结果与计算过程一起交给模型，生成研究摘要；
5. 在回答中标注数据来源、时间区间和计算口径。

这样做的核心考虑是：**行情数字必须来自数据库，不能来自模型记忆。**
"""
    )

    st.divider()

    section("🧰 计划实现的工具", "每个工具都应是参数明确、可单独验证的函数。")

    st.markdown(
        """
| 工具 | 作用 | 关键约束 |
|---|---|---|
| `query_market_summary` | 区间市场成交额、涨跌家数、等权收益 | 只接受日期区间参数 |
| `query_stock_history` | 指定股票的历史行情与区间指标 | 股票代码必须存在于 `stock_info` |
| `query_industry_ranking` | 行业区间收益率排名 | 复用行业分析的同一套口径 |
| `query_backtest_result` | 读取当前策略回测指标 | 只读，不允许修改回测参数 |
| `compare_stocks` | 多只股票的区间表现对比 | 最多 10 只，防止超长上下文 |
"""
    )

    section("🛡️ 必须处理的风险", "这些决定了助手能不能用于真实研究场景。")

    st.markdown(
        """
- **SQL 注入**：所有查询使用参数绑定，禁止拼接用户输入；工具层只暴露白名单函数，不开放任意 SQL。
- **参数校验**：日期、股票代码、数量上限都要在进入数据库前校验，避免全表扫描。
- **事实核验**：模型回答中的每个数字都要能追溯到具体工具调用结果，无法追溯的一律不输出。
- **过程可追踪**：记录工具名、入参、返回行数和耗时，便于复现与排查。
- **失败降级**：模型 API 超时或返回异常时，明确提示失败，不编造结论。
- **口径一致**：助手引用的指标必须与看板页面使用同一套 SQL 与计算逻辑，避免同一问题两个答案。
"""
    )

    st.divider()

    section("📦 当前已具备的数据基础")

    metric_columns = st.columns(4)
    metric_columns[0].metric("股票数量", f"{meta['stock_count']:,} 只")
    metric_columns[1].metric("行情记录", f"{meta['record_count']:,} 条")
    metric_columns[2].metric("交易日数", f"{meta['trading_days']} 天")
    metric_columns[3].metric(
        "数据区间",
        f"{meta['min_date']:%Y-%m-%d} ~ {meta['max_date']:%Y-%m-%d}",
    )

    st.caption(
        "以上数据已经可以直接支撑工具调用层的开发。"
        "在接入大模型之前，建议先完成工具函数与单元验证，"
        "确保每个查询都能给出可复核的结果。"
    )

    with st.expander("为什么先做工具，再接模型？", expanded=False):
        st.markdown(
            """
因为模型的能力上限由工具决定。如果工具返回的数据本身不可靠，
再强的模型也只会把错误数据包装得更像结论。

先把每个查询函数写成"给定明确参数，返回明确结果"的纯函数，
用真实数据验证一遍，再让模型去调用，问题会被限制在
"模型选错工具"或"模型误读结果"这两个可排查的范围内。
"""
        )
