use a_share_research;


-- ======检查重复记录、缺失值和价格逻辑==================
select
    stock_code as '股票代码',
    stock_name as '股票名称',
    count(*) as '记录总数',
    count(distinct trade_date) as '交易日期数量',
    count(*) - count(distinct trade_date) as '重复日期数量'
from stock_daily
group by stock_code, stock_name
order by stock_code;



select
    stock_code as '股票代码',
    stock_name as '股票名称',
    count(*) as '记录总数',
    sum(case when trade_date is null then 1 else 0 end) as '缺失交易日期数',
    sum(case when close_price is null then 1 else 0 end) as '缺失收盘价数',
    sum(case when open_price is null then 1 else 0 end) as '缺失开盘价数',
    sum(case when high_price is null then 1 else 0 end) as '缺失最高价数',
    sum(case when low_price is null then 1 else 0 end) as '缺失最低价数',
    sum(case when volume is null then 1 else 0 end) as '缺失成交量数',
    sum(case when amount is null then 1 else 0 end) as '缺失成交额数',
    sum(case when pct_change is null then 1 else 0 end) as '缺失涨跌幅数'
from stock_daily
group by stock_code, stock_name
order by stock_code;


select
    trade_date as '交易日期',
    stock_code as '股票代码',
    stock_name as '股票名称',
    open_price as '开盘价',
    high_price as '最高价',
    low_price as '最低价',
    close_price as '收盘价'
from stock_daily
where high_price < low_price
   or high_price < greatest(open_price, close_price)
   or low_price > least(open_price, close_price);



-- ================检查交易日期是否完整==============
select
    stock_code as '股票代码',
    stock_name as '股票名称',
    min(trade_date) as '首个交易日期',
    max(trade_date) as '最后交易日期',
    count(*) as '行情记录数',
    count(distinct trade_date) as '不同交易日期数'
from stock_daily
group by stock_code, stock_name
order by stock_code;


-- ============检查成交量和成交额的差异值===============================
select
    trade_date as '交易日期',
    stock_code as '股票代码',
    stock_name as '股票名称',
    volume as '成交量',
    amount as '成交额',
    trade_status as '交易状态'
from stock_daily
where volume < 0
   or amount < 0
order by stock_code, trade_date;


-- =================检查复权价格与每日涨跌幅的一致性========================

-- 先确认数据库里保存的复权类型
select
    adjust_flag as '复权类型代码',
    count(*) as '记录数量'
from stock_daily
group by adjust_flag
order by adjust_flag;

-- 比较自行计算的收益率与数据源涨跌幅
with return_comparison as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        pct_change,
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
    round(prev_close, 4) as '上一条前复权收盘价',
    round(close_price, 4) as '当日前复权收盘价',
    round((close_price / nullif(prev_close, 0) - 1) * 100, 4) as '自行计算日收益率（%）',
    round(pct_change, 4) as '数据源涨跌幅（%）',
    round(
        (close_price / nullif(prev_close, 0) - 1) * 100 - pct_change,
        4
    ) as '两者差值（百分点）'
from return_comparison
order by stock_code, trade_date;

-- 再检查差异较大的记录
with return_comparison as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        pct_change,
        lag(close_price) over (
            partition by stock_code
            order by trade_date
        ) as prev_close
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
),
comparison_result as (
    select
        trade_date,
        stock_code,
        stock_name,
        pct_change,
        (close_price / nullif(prev_close, 0) - 1) * 100 as calculated_return
    from return_comparison
)
select
    trade_date as '交易日期',
    stock_code as '股票代码',
    stock_name as '股票名称',
    round(calculated_return, 4) as '自行计算日收益率（%）',
    round(pct_change, 4) as '数据源涨跌幅（%）',
    round(calculated_return - pct_change, 4) as '两者差值（百分点）'
from comparison_result
where abs(calculated_return - pct_change) > 0.1
order by abs(calculated_return - pct_change) desc;


-- 检查全部记录的最大差值
with return_comparison as (
    select
        trade_date,
        stock_code,
        stock_name,
        close_price,
        pct_change,
        lag(close_price) over (
            partition by stock_code
            order by trade_date
        ) as prev_close
    from stock_daily
    where trade_date between '2025-01-01' and '2025-03-31'
),
comparison_result as (
    select
        trade_date,
        stock_code,
        stock_name,
        (close_price / nullif(prev_close, 0) - 1) * 100 as calculated_return,
        pct_change
    from return_comparison
)
select
    count(calculated_return) as '有效比较记录数',
    round(max(abs(calculated_return - pct_change)), 6) as '最大绝对差值（百分点）',
    round(avg(abs(calculated_return - pct_change)), 6) as '平均绝对差值（百分点）'
from comparison_result
where calculated_return is not null
  and pct_change is not null;
