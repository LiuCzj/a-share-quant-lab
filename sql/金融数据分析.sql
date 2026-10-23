use a_share_research;
select * from stock_daily;

-- ======比较5只股票的区间表现========
with ranked_prices as (
    select
        stock_code,
        stock_name,
        trade_date,
        close_price,
        row_number() over (
            partition by stock_code
            order by trade_date
        ) as first_rank,
        row_number() over (
            partition by stock_code
            order by trade_date desc
        ) as last_rank
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
),
first_prices as (
    select
        stock_code,
        stock_name,
        trade_date as first_date,
        close_price as first_close
    from ranked_prices
    where first_rank = 1
),
last_prices as (
    select
        stock_code,
        trade_date as last_date,
        close_price as last_close
    from ranked_prices
    where last_rank = 1
)
select
    f.stock_code as '股票代码',
    f.stock_name as '股票名称',
    f.first_date as '首个交易日',
    f.first_close as '首日收盘价',
    l.last_date as '最后交易日',
    l.last_close as '末日收盘价',
    round(
        (l.last_close / f.first_close - 1) * 100,
        2
    ) as '区间涨跌幅（%）'
from first_prices f
join last_prices l
    on f.stock_code = l.stock_code
order by `区间涨跌幅（%）` desc;


-- 每天有多少只股票上涨、下跌？

select
    trade_date as '交易日期',
    count(*) as '股票数量',
    sum(case when pct_change > 0 then 1 else 0 end) as '上涨家数',
    sum(case when pct_change < 0 then 1 else 0 end) as '下跌家数',
    sum(case when pct_change = 0 then 1 else 0 end) as '平盘家数',
    round(avg(pct_change), 2) as '平均涨跌幅（%）'
from stock_daily
group by trade_date
order by trade_date;


-- 哪只股票的成交额最高

select
    stock_code as '股票代码',
    stock_name as '股票名称',
    count(*) as '交易记录数',
    round(avg(amount), 2) as '日均成交额',
    round(sum(amount), 2) as '区间累计成交额'
from stock_daily
where trade_date between '2025-01-01' and '2025-03-31'
group by stock_code, stock_name
order by sum(amount) desc;

-- 找出涨跌幅最大的交易日

select
    trade_date as '交易日期',
    stock_code as '股票代码',
    stock_name as '股票名称',
    pct_change as '涨跌幅（%）',
    amount as '成交额'
from stock_daily
where pct_change is not null
order by abs(pct_change) desc
limit 10;

-- ==========计算每日收益率============
with daily_returns as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        lag(close_price) over (
            partition by stock_code
            order by trade_date
        ) as prev_close
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
)
select
    trade_date as '交易日期',
    stock_code as '股票代码',
    stock_name as '股票名称',
    prev_close as '上一交易日收盘价',
    close_price as '当日收盘价',
    round((close_price / nullif(prev_close, 0) - 1) * 100, 4) as '日收益率（%）'
from daily_returns
order by stock_code, trade_date;

-- ===========计算股票波动率=============
with daily_returns as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        lag(close_price) over (
            partition by stock_code
            order by trade_date
        ) as prev_close
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
),
returns_calculated as (
    select
        trade_date,
        stock_code,
        stock_name,
        (close_price / nullif(prev_close, 0) - 1) * 100 as daily_return_pct
    from daily_returns
)
select
    stock_code as '股票代码',
    stock_name as '股票名称',
    count(daily_return_pct) as '有效收益率天数',
    round(avg(daily_return_pct), 4) as '平均日收益率（%）',
    round(stddev_samp(daily_return_pct), 4) as '日收益率标准差（百分点）',
    round(min(daily_return_pct), 4) as '单日最大跌幅（%）',
    round(max(daily_return_pct), 4) as '单日最大涨幅（%）'
from returns_calculated
group by stock_code, stock_name
order by stddev_samp(daily_return_pct) desc;


-- =============计算最大回撤===============
with running_peaks as (
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
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
),
drawdowns as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        historical_peak,
        (close_price / nullif(historical_peak, 0) - 1) * 100 as drawdown_pct
    from running_peaks
)
select
    stock_code as '股票代码',
    stock_name as '股票名称',
    round(max(close_price), 4) as '区间最高收盘价',
    round(min(drawdown_pct), 4) as '最大回撤（%）'
from drawdowns
group by stock_code, stock_name
order by min(drawdown_pct) asc;