use a_share_research;

with base_data as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
),
daily_returns as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        lag(close_price) over (
            partition by stock_code
            order by trade_date
        ) as prev_close
    from base_data
),
returns_calculated as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        (close_price / nullif(prev_close, 0) - 1) * 100 as daily_return_pct
    from daily_returns
),
running_peaks as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        max(close_price) over (
            partition by stock_code
            order by trade_date
            rows between unbounded preceding and current row
        ) as historical_peak
    from base_data
),
drawdowns as (
    select
        stock_code,
        stock_name,
        (close_price / nullif(historical_peak, 0) - 1) * 100 as drawdown_pct
    from running_peaks
),
period_returns as (
    select
        stock_code,
        stock_name,
        max(case when row_num = 1 then close_price end) as first_close,
        max(case when row_num = total_rows then close_price end) as last_close
    from (
        select
            trade_date,
            stock_code,
            stock_name,
            close_price,
            row_number() over (
                partition by stock_code
                order by trade_date
            ) as row_num,
            count(*) over (
                partition by stock_code
            ) as total_rows
        from base_data
    ) as ranked_prices
    group by stock_code, stock_name
),
return_summary as (
    select
        stock_code,
        stock_name,
        count(daily_return_pct) as valid_return_days,
        avg(daily_return_pct) as avg_daily_return,
        stddev_samp(daily_return_pct) as daily_volatility
    from returns_calculated
    group by stock_code, stock_name
),
drawdown_summary as (
    select
        stock_code,
        stock_name,
        min(drawdown_pct) as max_drawdown
    from drawdowns
    group by stock_code, stock_name
)
select
    p.stock_code as '股票代码',
    p.stock_name as '股票名称',
    round((p.last_close / nullif(p.first_close, 0) - 1) * 100, 2) as '区间涨跌幅（%）',
    s.valid_return_days as '有效收益率天数',
    round(s.avg_daily_return, 4) as '平均日收益率（%）',
    round(s.daily_volatility, 4) as '日收益率标准差（百分点）',
    round(d.max_drawdown, 4) as '最大回撤（%）'
from period_returns as p
join return_summary as s
    on p.stock_code = s.stock_code
join drawdown_summary as d
    on p.stock_code = d.stock_code
order by p.stock_code;
