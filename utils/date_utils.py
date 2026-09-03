#!/usr/bin/env python3
"""
日期时间工具函数
"""

from datetime import datetime, timedelta
from typing import List, Optional


def parse_date(date_str: str, fmt: str = '%Y-%m-%d') -> datetime:
    """解析日期字符串"""
    return datetime.strptime(date_str, fmt)


def format_date(dt: datetime, fmt: str = '%Y-%m-%d') -> str:
    """格式化日期"""
    return dt.strftime(fmt)


def get_date_range(start_date: str, end_date: str) -> List[str]:
    """获取日期范围内的所有日期"""
    start = parse_date(start_date)
    end = parse_date(end_date)
    dates = []
    current = start
    while current <= end:
        dates.append(format_date(current))
        current += timedelta(days=1)
    return dates


def get_last_n_days(n: int, fmt: str = '%Y-%m-%d') -> List[str]:
    """获取最近n天的日期列表"""
    today = datetime.now()
    return [format_date(today - timedelta(days=i), fmt) for i in range(n)]


def is_weekend(date_str: str) -> bool:
    """判断是否为周末"""
    dt = parse_date(date_str)
    return dt.weekday() >= 5


def get_recent_trading_dates(n: int = 5, fmt: str = '%Y-%m-%d') -> List[str]:
    """获取最近n个交易日（简化版，仅排除周末）"""
    dates = []
    current = datetime.now()
    while len(dates) < n:
        if current.weekday() < 5:  # 周一到周五
            dates.append(format_date(current, fmt))
        current -= timedelta(days=1)
    return dates
