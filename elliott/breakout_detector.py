#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强型突破检测器 - 快速识别关键位突破

核心功能:
- 突破信号快速响应
- 成交量确认检测
- 动量确认检测
- 多重确认机制
- 突破强度评分
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import deque

# ============================================================
# 突破检测配置
# ============================================================

DEFAULT_BREAKOUT_THRESHOLD = 0.03  # 默认突破阈值（3%）
DEFAULT_MIN_CONFIRMATION_DAYS = 2     # 最少确认天数
DEFAULT_VOLUME_RATIO = 1.5           # 成交量放大倍数
DEFAULT_MOMENTUM_THRESHOLD = 0.02    # 动量阈值（2%）

# ============================================================
# 突破历史记录
# ============================================================

class BreakoutHistory:
    """突破历史记录管理"""

    def __init__(self, max_history: int = 20):
        self.history = {}  # {symbol: deque of records}
        self.max_history = max_history

    def add_record(self, symbol: str, record: Dict[str, Any]):
        """添加突破记录"""
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.max_history)
        self.history[symbol].append(record)

    def get_recent(self, symbol: str, days: int = 5) -> List[Dict[str, Any]]:
        """获取最近的突破记录"""
        if symbol not in self.history:
            return []
        records = list(self.history[symbol])[-days:]
        return records

    def get_consecutive_confirmations(self, symbol: str, threshold: float) -> int:
        """获取连续确认次数"""
        recent = self.get_recent(symbol)
        count = 0
        for record in reversed(recent):
            if record.get('confirmed', False) and record.get('ratio', 0) >= threshold:
                count += 1
            else:
                break
        return count


# ============================================================
# 增强型突破检测器
# ============================================================

class EnhancedBreakoutDetector:
    """增强型突破检测器"""

    def __init__(
        self,
        confirmation_threshold: float = DEFAULT_BREAKOUT_THRESHOLD,
        min_confirmation_days: int = DEFAULT_MIN_CONFIRMATION_DAYS,
        volume_ratio: float = DEFAULT_VOLUME_RATIO,
        momentum_threshold: float = DEFAULT_MOMENTUM_THRESHOLD
    ):
        """
        Args:
            confirmation_threshold: 突破确认阈值（默认3%）
            min_confirmation_days: 最少确认天数
            volume_ratio: 成交量确认倍数
            momentum_threshold: 动量确认阈值
        """
        self.confirmation_threshold = confirmation_threshold
        self.min_confirmation_days = min_confirmation_days
        self.volume_ratio = volume_ratio
        self.momentum_threshold = momentum_threshold
        self.history = BreakoutHistory()

    def detect_breakout(
        self,
        symbol: str,
        current_price: float,
        resistance_level: float,
        volume_data: Optional[pd.Series] = None,
        momentum_data: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        检测向上突破信号

        Args:
            symbol: 标的代码
            current_price: 当前价格
            resistance_level: 阻力位
            volume_data: 成交量数据（最近N根）
            momentum_data: 动量数据（最近N根）

        Returns:
            dict: {
                'confirmed': bool,
                'strength': float (0-10),
                'duration': int,
                'confirmations': list
            }
        """
        if resistance_level <= 0:
            return {
                'confirmed': False,
                'strength': 0.0,
                'duration': 0,
                'confirmations': []
            }

        # 计算突破幅度
        breakout_ratio = (current_price - resistance_level) / resistance_level
        is_breakout = breakout_ratio > self.confirmation_threshold

        # 记录本次检测
        record = {
            'timestamp': datetime.now(),
            'price': current_price,
            'resistance': resistance_level,
            'ratio': breakout_ratio,
            'confirmed': is_breakout
        }
        self.history.add_record(symbol, record)

        # 检查连续确认
        confirmations = []
        strength = 0.0

        if is_breakout:
            # 成交量确认
            volume_confirmed = self._check_volume_confirmation(volume_data, resistance_level)

            # 动量确认
            momentum_confirmed = self._check_momentum_confirmation(momentum_data, resistance_level)

            # 计算突破强度
            strength = min(breakout_ratio * 100, 10)

            confirmations = {
                'price_breakout': True,
                'volume_confirmation': volume_confirmed,
                'momentum_confirmation': momentum_confirmed
            }

            # 检查历史连续性
            consecutive = self.history.get_consecutive_confirmations(
                symbol, self.confirmation_threshold
            )

            # 多重确认机制
            if consecutive >= self.min_confirmation_days:
                if volume_confirmed or momentum_confirmed:
                    return {
                        'confirmed': True,
                        'strength': strength,
                        'duration': consecutive,
                        'confirmations': confirmations,
                        'breakout_ratio': breakout_ratio * 100
                    }

        return {
            'confirmed': False,
            'strength': strength,
            'duration': 0,
            'confirmations': confirmations,
            'breakout_ratio': breakout_ratio * 100
        }

    def detect_breakdown(
        self,
        symbol: str,
        current_price: float,
        support_level: float,
        volume_data: Optional[pd.Series] = None,
        momentum_data: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        检测向下突破（跌破支撑）信号

        Args:
            symbol: 标的代码
            current_price: 当前价格
            support_level: 支撑位
            volume_data: 成交量数据
            momentum_data: 动量数据

        Returns:
            dict: 突破检测结果
        """
        if support_level <= 0:
            return {
                'confirmed': False,
                'strength': 0.0,
                'duration': 0,
                'confirmations': []
            }

        # 计算跌破幅度
        breakdown_ratio = (support_level - current_price) / support_level
        is_breakdown = breakdown_ratio > self.confirmation_threshold

        # 记录本次检测
        record = {
            'timestamp': datetime.now(),
            'price': current_price,
            'support': support_level,
            'ratio': breakdown_ratio,
            'confirmed': is_breakdown
        }
        self.history.add_record(symbol, record)

        # 检查连续确认
        strength = 0.0
        confirmations = {}

        if is_breakdown:
            # 成交量确认（下跌放量）
            volume_confirmed = self._check_volume_confirmation_down(volume_data, support_level)

            # 动量确认
            momentum_confirmed = self._check_momentum_confirmation_down(momentum_data, support_level)

            strength = min(breakdown_ratio * 100, 10)

            confirmations = {
                'price_breakdown': True,
                'volume_confirmation': volume_confirmed,
                'momentum_confirmation': momentum_confirmed
            }

            # 检查历史连续性
            consecutive = self.history.get_consecutive_confirmations(
                symbol, self.confirmation_threshold
            )

            if consecutive >= self.min_confirmation_days:
                if volume_confirmed or momentum_confirmed:
                    return {
                        'confirmed': True,
                        'strength': strength,
                        'duration': consecutive,
                        'confirmations': confirmations,
                        'breakdown_ratio': breakdown_ratio * 100
                    }

        return {
            'confirmed': False,
            'strength': strength,
            'duration': 0,
            'confirmations': confirmations,
            'breakdown_ratio': breakdown_ratio * 100
        }

    def _check_volume_confirmation(self, volume_data: Optional[pd.Series],
                                  level: float) -> bool:
        """检查成交量是否支持向上突破"""
        if volume_data is None or len(volume_data) < 2:
            return False

        current_volume = volume_data.iloc[-1]
        prev_volume = volume_data.iloc[-2]
        avg_volume = volume_data.tail(20).mean() if len(volume_data) >= 20 else volume_data.mean()

        # 放量确认
        if current_volume > avg_volume * self.volume_ratio:
            return True

        # 连续放量
        if len(volume_data) >= 3:
            if (volume_data.iloc[-1] > volume_data.iloc[-2] and
                volume_data.iloc[-2] > volume_data.iloc[-3]):
                return True

        return False

    def _check_volume_confirmation_down(self, volume_data: Optional[pd.Series],
                                        level: float) -> bool:
        """检查成交量是否支持向下突破"""
        if volume_data is None or len(volume_data) < 2:
            return False

        current_volume = volume_data.iloc[-1]
        prev_volume = volume_data.iloc[-2]
        avg_volume = volume_data.tail(20).mean() if len(volume_data) >= 20 else volume_data.mean()

        # 放量下跌
        if current_volume > avg_volume * self.volume_ratio:
            return True

        return False

    def _check_momentum_confirmation(self, momentum_data: Optional[pd.Series],
                                     level: float) -> bool:
        """检查动量是否支持向上突破"""
        if momentum_data is None or len(momentum_data) < 2:
            return False

        # 简单动量：最近价格涨幅
        current = momentum_data.iloc[-1]
        prev = momentum_data.iloc[-2]

        if (current - prev) / prev > self.momentum_threshold:
            return True

        return False

    def _check_momentum_confirmation_down(self, momentum_data: Optional[pd.Series],
                                         level: float) -> bool:
        """检查动量是否支持向下突破"""
        if momentum_data is None or len(momentum_data) < 2:
            return False

        current = momentum_data.iloc[-1]
        prev = momentum_data.iloc[-2]

        if (prev - current) / prev > self.momentum_threshold:
            return True

        return False


# ============================================================
# 快速突破检测函数（无状态）
# ============================================================

def fast_detect_breakout(
    current_price: float,
    resistance_level: float,
    volume_data: Optional[pd.Series] = None,
    volume_ratio: float = 1.5,
    momentum_threshold: float = 0.02
) -> Tuple[bool, float]:
    """
    快速检测向上突破（无状态版本）

    Returns:
        (is_breakout: bool, strength: float)
    """
    # 价格突破
    price_breakout = current_price > resistance_level * (1 + DEFAULT_BREAKOUT_THRESHOLD)

    if not price_breakout:
        return False, 0.0

    # 计算强度
    strength = min((current_price - resistance_level) / resistance_level * 100, 10)

    # 成交量确认
    volume_confirmed = False
    if volume_data is not None and len(volume_data) >= 2:
        current_volume = volume_data.iloc[-1]
        avg_volume = volume_data.tail(20).mean() if len(volume_data) >= 20 else volume_data.mean()
        volume_confirmed = current_volume > avg_volume * volume_ratio

    # 动量确认（用价格变化替代）
    momentum_confirmed = False
    if volume_data is not None and len(volume_data) >= 2:
        # 简单用成交量变化作为动量代理
        momentum_confirmed = volume_data.iloc[-1] > volume_data.iloc[-2] * 1.1

    # 多重确认
    if volume_confirmed or momentum_confirmed:
        return True, strength

    return False, strength


def fast_detect_breakdown(
    current_price: float,
    support_level: float,
    volume_data: Optional[pd.Series] = None,
    volume_ratio: float = 1.5
) -> Tuple[bool, float]:
    """
    快速检测向下突破（无状态版本）

    Returns:
        (is_breakdown: bool, strength: float)
    """
    # 价格跌破
    price_breakdown = current_price < support_level * (1 - DEFAULT_BREAKOUT_THRESHOLD)

    if not price_breakdown:
        return False, 0.0

    # 计算强度
    strength = min((support_level - current_price) / support_level * 100, 10)

    # 成交量确认
    volume_confirmed = False
    if volume_data is not None and len(volume_data) >= 2:
        current_volume = volume_data.iloc[-1]
        avg_volume = volume_data.tail(20).mean() if len(volume_data) >= 20 else volume_data.mean()
        volume_confirmed = current_volume > avg_volume * volume_ratio

    if volume_confirmed:
        return True, strength

    return False, strength


# ============================================================
# 突破强度分类
# ============================================================

def classify_breakout_strength(strength: float) -> str:
    """
    根据强度值分类突破

    Args:
        strength: 突破强度（0-10）

    Returns:
        str: 强度分类描述
    """
    if strength >= 8:
        return "极强突破"
    elif strength >= 5:
        return "强突破"
    elif strength >= 3:
        return "中等突破"
    elif strength >= 1:
        return "弱突破"
    else:
        return "未突破"


# ============================================================
# 基于DataFrame的批量突破检测
# ============================================================

def detect_breakouts_from_dataframe(
    df: pd.DataFrame,
    resistance_levels: List[float],
    support_levels: List[float],
    min_strength: float = 1.0
) -> Dict[str, Any]:
    """
    从DataFrame中批量检测突破

    Args:
        df: K线数据（包含close, volume列）
        resistance_levels: 阻力位列表
        support_levels: 支撑位列表
        min_strength: 最小突破强度

    Returns:
        dict: 突破检测结果
    """
    if df is None or len(df) < 5:
        return {'breakouts': [], 'breakdowns': []}

    current_price = df['close'].iloc[-1]
    volume_data = df['volume'].tail(20) if 'volume' in df.columns else None

    breakouts = []
    breakdowns = []

    # 检测向上突破
    for resistance in resistance_levels:
        if resistance <= 0:
            continue

        is_breakout, strength = fast_detect_breakout(
            current_price, resistance, volume_data
        )

        if is_breakout and strength >= min_strength:
            breakouts.append({
                'level': resistance,
                'strength': strength,
                'class': classify_breakout_strength(strength),
                'ratio': (current_price - resistance) / resistance * 100
            })

    # 检测向下突破
    for support in support_levels:
        if support <= 0:
            continue

        is_breakdown, strength = fast_detect_breakdown(
            current_price, support, volume_data
        )

        if is_breakdown and strength >= min_strength:
            breakdowns.append({
                'level': support,
                'strength': strength,
                'class': classify_breakout_strength(strength),
                'ratio': (support - current_price) / support * 100
            })

    return {
        'breakouts': sorted(breakouts, key=lambda x: x['strength'], reverse=True),
        'breakdowns': sorted(breakdowns, key=lambda x: x['strength'], reverse=True),
        'current_price': current_price
    }


# ============================================================
# 关键变化追踪
# ============================================================

class CriticalChangeTracker:
    """关键变化追踪器 - 用于报告中的"关键信号变化追踪"章节"""

    def __init__(self):
        self.previous_state = {}
        self.current_state = {}

    def update(self, symbol: str, state: Dict[str, Any]):
        """更新状态"""
        self.previous_state[symbol] = self.current_state.get(symbol, {}).copy()
        self.current_state[symbol] = state

    def get_critical_changes(self, symbol: str) -> List[Dict[str, Any]]:
        """获取关键变化列表"""
        changes = []
        prev = self.previous_state.get(symbol, {})
        curr = self.current_state.get(symbol, {})

        # 阻力位突破变化
        prev_breakouts = prev.get('breakouts', [])
        curr_breakouts = curr.get('breakouts', [])

        for breakout in curr_breakouts:
            level = breakout['level']
            if not any(b['level'] == level for b in prev_breakouts):
                changes.append({
                    'type': 'breakout',
                    'description': f'突破{level:.0f}阻力位',
                    'strength': breakout['strength'],
                    'icon': '🚀'
                })

        # 支撑位跌破变化
        prev_breakdowns = prev.get('breakdowns', [])
        curr_breakdowns = curr.get('breakdowns', [])

        for breakdown in curr_breakdowns:
            level = breakdown['level']
            if not any(b['level'] == level for b in prev_breakdowns):
                changes.append({
                    'type': 'breakdown',
                    'description': f'跌破{level:.0f}支撑位',
                    'strength': breakdown['strength'],
                    'icon': '⚠️'
                })

        # 成交量异常
        prev_vol_anomaly = prev.get('volume_anomaly', False)
        curr_vol_anomaly = curr.get('volume_anomaly', False)

        if curr_vol_anomaly and not prev_vol_anomaly:
            changes.append({
                'type': 'volume_anomaly',
                'description': '成交量异常放大',
                'icon': '📈'
            })

        return sorted(changes, key=lambda x: x.get('strength', 0), reverse=True)
