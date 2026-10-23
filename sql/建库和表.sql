-- 创建数据库
create database if not exists a_share_research
    default character set utf8mb4
    default collate utf8mb4_0900_ai_ci;

use a_share_research;

-- 创建股票日线行情表
create table if not exists stock_daily (
    trade_date date not null comment '交易日期',
    stock_code varchar(10) not null comment '股票代码',
    stock_name varchar(30) not null comment '股票名称',
    open_price decimal(12, 4) comment '开盘价',
    high_price decimal(12, 4) comment '最高价',
    low_price decimal(12, 4) comment '最低价',
    close_price decimal(12, 4) comment '收盘价',
    preclose_price decimal(12, 4) comment '前收盘价',
    volume decimal(20, 4) comment '成交量',
    amount decimal(20, 4) comment '成交额',
    adjust_flag varchar(2) comment '复权类型',
    turnover_rate decimal(12, 6) comment '换手率',
    trade_status varchar(2) comment '交易状态',
    pct_change decimal(12, 6) comment '涨跌幅（%）',
    primary key (trade_date, stock_code)
) comment = 'a股日线行情表';

-- 检查表是否创建成功
show tables;
describe stock_daily;