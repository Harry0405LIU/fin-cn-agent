#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论信号状态管理

持久化信号追踪状态到JSON文件，支持跨运行分析。
"""

from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from config.settings import settings
from core.utils import load_json, save_json

CHANLUN_STATE_FILE = settings.DATA_DIR / "chanlun_state.json"


def load_state() -> dict:
    """加载缠论信号状态"""
    return load_json(CHANLUN_STATE_FILE, default={})


def save_state(state: dict):
    """保存缠论信号状态"""
    save_json(CHANLUN_STATE_FILE, state)


def update_signal_state(
    state: dict,
    symbol: str,
    name: str,
    date_str: str,
    trading_points: list,
    pivots: list,
    divergences: list
) -> list:
    """
    更新信号状态并返回新检测到的信号。

    Args:
        state: 当前状态dict
        symbol: 股票代码
        name: 股票名称
        date_str: 分析日期
        trading_points: 当前识别的买卖点列表
        pivots: 当前识别的中枢列表
        divergences: 当前识别的背驰列表

    Returns:
        新出现的买卖点序列号列表
    """
    key = symbol
    prev_data = state.get(key, {})

    # 序列化当前信号
    current_signals = []
    for tp in trading_points:
        signal_str = f"{tp.date}|{tp.point_type}|{tp.action}|{tp.price:.2f}|{tp.confidence}"
        current_signals.append(signal_str)

    # 找出新信号
    prev_signals = prev_data.get("signals", [])
    new_signals = [s for s in current_signals if s not in prev_signals]

    # 更新状态
    state[key] = {
        "name": name,
        "last_analysis_date": date_str,
        "signals": current_signals,
        "latest_type1_buy": _find_latest(trading_points, 1, 'buy'),
        "latest_type1_sell": _find_latest(trading_points, 1, 'sell'),
        "latest_type2_buy": _find_latest(trading_points, 2, 'buy'),
        "latest_type2_sell": _find_latest(trading_points, 2, 'sell'),
        "latest_type3_buy": _find_latest(trading_points, 3, 'buy'),
        "latest_type3_sell": _find_latest(trading_points, 3, 'sell'),
        "pivot_count": len(pivots),
        "divergence_count": len(divergences),
        "last_pivot_ZG": pivots[-1].ZG if pivots else None,
        "last_pivot_ZD": pivots[-1].ZD if pivots else None,
    }

    return new_signals


def _find_latest(trading_points: list, point_type: int, action: str) -> Optional[dict]:
    """找到最新指定类型的买卖点"""
    matching = [tp for tp in trading_points
                if hasattr(tp, 'point_type') and tp.point_type == point_type
                and hasattr(tp, 'action') and tp.action == action]
    if not matching:
        return None

    latest = matching[-1]
    return {
        "date": latest.date,
        "price": latest.price,
        "confidence": latest.confidence,
        "description": getattr(latest, 'description', '')
    }


def get_symbol_history(state: dict, symbol: str) -> dict:
    """获取某只股票的历史分析记录"""
    return state.get(symbol, {})


def clear_symbol_state(state: dict, symbol: str):
    """清除某只股票的状态"""
    if symbol in state:
        del state[symbol]


def list_analyzed_symbols(state: dict) -> List[str]:
    """列出所有已分析的股票"""
    return list(state.keys())
