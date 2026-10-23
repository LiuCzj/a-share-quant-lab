-- ======创建股票基础信息表======
use a_share_research;

create table if not exists stock_info (
    stock_code varchar(10) not null comment '股票代码',
    stock_name varchar(30) not null comment '股票名称',
    exchange_name varchar(20) comment '交易所',
    list_date date comment '上市日期',
    industry_name varchar(50) comment '所属行业',
    primary key (stock_code)
) comment = 'a股股票基础信息表';


-- ===========把现有 5 只股票写入基础信息表===================
insert into stock_info (
    stock_code,
    stock_name
)
select distinct
    stock_code,
    stock_name
from stock_daily
on duplicate key update
    stock_name = values(stock_name);


-- 检查结果
select
    stock_code as '股票代码',
    stock_name as '股票名称',
    exchange_name as '交易所',
    list_date as '上市日期',
    industry_name as '所属行业'
from stock_info
order by stock_code;
