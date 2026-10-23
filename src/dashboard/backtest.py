from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.02
EPSILON = 1e-9


@dataclass(frozen=True)
class CostModel:
    commission: float = 0.0003
    stamp_tax: float = 0.0005
    slippage: float = 0.001

    @property
    def buy_rate(self) -> float:
        return self.commission + self.slippage

    @property
    def sell_rate(self) -> float:
        return self.commission + self.stamp_tax + self.slippage


@dataclass
class BacktestResult:
    net_value: pd.Series
    benchmark_value: pd.Series
    daily_return: pd.Series
    benchmark_return: pd.Series
    drawdown: pd.Series
    benchmark_drawdown: pd.Series
    stats: dict
    benchmark_stats: dict
    trades: pd.DataFrame
    rebalance_dates: list[pd.Timestamp]
    holding_count: pd.Series
    turnover: pd.Series
    exposure: pd.Series
    costs: pd.Series


def momentum_rebalance_weights(
    close_matrix: pd.DataFrame,
    lookback: int = 20,
    top_n: int = 10,
    rebalance_days: int = 5,
) -> dict[pd.Timestamp, pd.Series]:
    dates = close_matrix.index
    weights: dict[pd.Timestamp, pd.Series] = {}

    if lookback <= 0 or rebalance_days <= 0 or len(dates) <= lookback + 1:
        return weights

    for position in range(lookback, len(dates) - 1, rebalance_days):
        decision_date = dates[position]
        base_date = dates[position - lookback]

        current = close_matrix.loc[decision_date]
        base = close_matrix.loc[base_date]

        valid = current.notna() & base.notna() & base.gt(0)
        if not valid.any():
            continue

        momentum = (current[valid] / base[valid] - 1).dropna()
        if momentum.empty:
            continue

        picked = momentum.nlargest(min(top_n, len(momentum))).index
        if len(picked) == 0:
            continue

        weights[decision_date] = pd.Series(
            1.0 / len(picked), index=list(picked)
        )

    return weights


def ma_crossover_rebalance_weights(
    close_matrix: pd.DataFrame,
    stock_code: str,
    fast_window: int = 5,
    slow_window: int = 20,
) -> dict[pd.Timestamp, pd.Series]:
    if stock_code not in close_matrix.columns:
        raise ValueError(f"价格矩阵中不存在股票 {stock_code}")

    if fast_window >= slow_window:
        raise ValueError("快线窗口必须小于慢线窗口")

    series = close_matrix[stock_code]
    fast_ma = series.rolling(fast_window).mean()
    slow_ma = series.rolling(slow_window).mean()

    holding = (fast_ma > slow_ma).astype(float)
    holding[slow_ma.isna() | fast_ma.isna()] = np.nan

    dates = close_matrix.index
    weights: dict[pd.Timestamp, pd.Series] = {}

    for position in range(1, len(dates) - 1):
        current = holding.iloc[position]
        previous = holding.iloc[position - 1]

        if pd.isna(current):
            continue
        if pd.isna(previous):
            previous = 0.0

        if current != previous:
            weights[dates[position]] = pd.Series(
                [current], index=[stock_code]
            )

    return weights


def equal_weight_benchmark(close_matrix: pd.DataFrame) -> pd.Series:
    daily = close_matrix.pct_change(fill_method=None).mean(axis=1)
    return daily.fillna(0.0)


def performance_stats(
    net_value: pd.Series,
    daily_return: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    empty = {
        "total_return": float("nan"),
        "annual_return": float("nan"),
        "volatility": float("nan"),
        "sharpe": float("nan"),
        "max_drawdown": float("nan"),
        "calmar": float("nan"),
        "win_rate": float("nan"),
        "best_day": float("nan"),
        "worst_day": float("nan"),
        "days": 0,
    }

    if net_value.empty or len(daily_return) < 2:
        return empty

    total_return = float(net_value.iloc[-1]) - 1.0
    periods = len(daily_return)
    years = periods / TRADING_DAYS_PER_YEAR

    if years > 0 and total_return > -1:
        annual_return = (1.0 + total_return) ** (1.0 / years) - 1.0
    else:
        annual_return = float("nan")

    volatility = float(
        daily_return.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )

    if volatility > 0 and not np.isnan(annual_return):
        sharpe = (annual_return - risk_free_rate) / volatility
    else:
        sharpe = float("nan")

    cumulative_max = net_value.cummax()
    drawdown = net_value / cumulative_max - 1.0
    max_drawdown = float(drawdown.min())

    if max_drawdown < 0 and not np.isnan(annual_return):
        calmar = annual_return / abs(max_drawdown)
    else:
        calmar = float("nan")

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "win_rate": _win_rate(daily_return),
        "best_day": float(daily_return.max()),
        "worst_day": float(daily_return.min()),
        "days": periods,
    }


def _win_rate(daily_return: pd.Series) -> float:
    active = daily_return[daily_return.abs() > EPSILON]
    if active.empty:
        return float("nan")
    return float((active > 0).mean())


def run_backtest(
    open_matrix: pd.DataFrame,
    close_matrix: pd.DataFrame,
    rebalance_weights: dict[pd.Timestamp, pd.Series],
    cost_model: CostModel | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> BacktestResult:
    cost_model = cost_model or CostModel()

    dates = close_matrix.index
    codes = list(close_matrix.columns)
    code_position = {code: index for index, code in enumerate(codes)}

    day_count = len(dates)
    code_count = len(codes)

    if day_count < 2 or code_count == 0:
        raise ValueError("回测区间内没有足够的可交易数据")

    weights_at_open = np.zeros((day_count, code_count))
    weights_after_open = np.zeros((day_count, code_count))
    cost_array = np.zeros(day_count)
    turnover_array = np.zeros(day_count)

    previous_close = close_matrix.shift(1)
    gap_matrix = np.nan_to_num(
        (open_matrix / previous_close - 1).to_numpy(dtype=float),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    intraday_matrix = np.nan_to_num(
        (close_matrix / open_matrix - 1).to_numpy(dtype=float),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    tradable_matrix = open_matrix.notna().to_numpy()

    trade_records: list[dict] = []
    rebalance_dates: list[pd.Timestamp] = []

    current_weights = np.zeros(code_count)

    for day in range(day_count):
        weights_at_open[day] = current_weights

        target_series = None
        if day > 0:
            target_series = rebalance_weights.get(dates[day - 1])

        if target_series is not None and not target_series.empty:
            target = np.zeros(code_count)
            for code, weight in target_series.items():
                position = code_position.get(code)
                if position is not None:
                    target[position] = float(weight)

            target = np.where(tradable_matrix[day], target, 0.0)

            blocked = (~tradable_matrix[day]) & (weights_at_open[day] > 0)
            target = np.where(blocked, weights_at_open[day], target)
            weights_after_open[day] = target

            delta = target - weights_at_open[day]
            changed = np.nonzero(np.abs(delta) > EPSILON)[0]

            for position in changed:
                trade_records.append(
                    {
                        "执行日期": dates[day],
                        "股票代码": codes[position],
                        "方向": "买入" if delta[position] > 0 else "卖出",
                        "权重变化": float(delta[position]),
                        "执行价": float(open_matrix.iat[day, position])
                        if np.isfinite(open_matrix.iat[day, position])
                        else float("nan"),
                    }
                )

            rebalance_dates.append(dates[day])
        else:
            weights_after_open[day] = weights_at_open[day]

        buy_weight = np.clip(
            weights_after_open[day] - weights_at_open[day], 0, None
        ).sum()
        sell_weight = np.clip(
            weights_at_open[day] - weights_after_open[day], 0, None
        ).sum()

        turnover_array[day] = buy_weight + sell_weight
        cost_array[day] = (
            buy_weight * cost_model.buy_rate
            + sell_weight * cost_model.sell_rate
        )

        current_weights = weights_after_open[day]

    gap_return = (weights_at_open * gap_matrix).sum(axis=1)
    intraday_return = (weights_after_open * intraday_matrix).sum(axis=1)

    net_return = (1.0 + gap_return) * (1.0 + intraday_return) - 1.0
    net_return = net_return - cost_array

    net_value = pd.Series((1.0 + net_return).cumprod(), index=dates)
    daily_return = pd.Series(net_return, index=dates)

    benchmark_daily = equal_weight_benchmark(close_matrix)
    benchmark_value = pd.Series(
        (1.0 + benchmark_daily).cumprod(), index=dates
    )

    drawdown = net_value / net_value.cummax() - 1.0
    benchmark_drawdown = benchmark_value / benchmark_value.cummax() - 1.0

    holding_count = pd.Series(
        (weights_after_open > EPSILON).sum(axis=1), index=dates
    )
    exposure = pd.Series(weights_after_open.sum(axis=1), index=dates)

    trades = pd.DataFrame(
        trade_records,
        columns=["执行日期", "股票代码", "方向", "权重变化", "执行价"],
    )

    return BacktestResult(
        net_value=net_value,
        benchmark_value=benchmark_value,
        daily_return=daily_return,
        benchmark_return=benchmark_daily,
        drawdown=drawdown,
        benchmark_drawdown=benchmark_drawdown,
        stats=performance_stats(net_value, daily_return, risk_free_rate),
        benchmark_stats=performance_stats(
            benchmark_value, benchmark_daily, risk_free_rate
        ),
        trades=trades,
        rebalance_dates=rebalance_dates,
        holding_count=holding_count,
        turnover=pd.Series(turnover_array, index=dates),
        exposure=exposure,
        costs=pd.Series(cost_array, index=dates),
    )
