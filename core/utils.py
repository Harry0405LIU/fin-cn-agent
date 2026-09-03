#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具函数
"""

import json
import os
from datetime import datetime


def load_json(filepath: str, default=None):
    """加载JSON文件"""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default if default is not None else {}
    return default if default is not None else {}


def save_json(filepath: str, data, indent=2):
    """保存JSON文件"""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def is_trading_day(force=False, market="a", date=None):
    """
    判断是否为交易日
    委托给 core.trading_calendar 模块实现

    Args:
        force: 强制返回True
        market: "a" (A股) 或 "hk" (港股)
        date: 指定日期 (datetime 或 str "YYYY-MM-DD")

    支持旧调用方式:
        is_trading_day(date_obj)  → 位置参数 date_obj 会被自动识别为 date
        is_trading_day(force=True)
    """
    from core.trading_calendar import is_trading_day as _is_trading_day
    # 兼容: 如果第一个位置参数是 datetime/str 但不是 bool，视为 date
    if force is not False and not isinstance(force, bool):
        date = force
        force = False

    # 如果强制运行，直接返回True
    if force:
        return True

    return _is_trading_day(date=date, market=market)


def is_weekday():
    """判断今天是否为工作日(周一至周五)"""
    return datetime.now().weekday() < 5
