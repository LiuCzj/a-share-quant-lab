use a_share_research;

select count(*) as total_records
from stock_daily;

select
    stock_code,
    stock_name,
    count(*) as record_count,
    min(trade_date) as first_date,
    max(trade_date) as last_date
from stock_daily
group by stock_code, stock_name
order by stock_code;

select
    trade_date as '交易日期',
    stock_code as '股票代码',
    stock_name as '股票名称',
    open_price as '开盘价',
    close_price as '收盘价',
    pct_change as '涨跌幅（%）'
from stock_daily
order by trade_date, stock_code
limit 20;

show create table stock_daily;

select
    count(*) as total_records,
    count(distinct trade_date, stock_code) as unique_stock_dates
from stock_daily;
