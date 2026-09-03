#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态评分系统 - 基于技术指标动态计算场景概率

核心功能:
- 动量指标评分
- 成交量确认评分
- 突破强度评分
- 市场情绪评分
- 多因子综合评分
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

# ============================================================
# 技术指标权重配置
# ============================================================

DEFAULT_WEIGHTS = {
    'momentum': 0.30,     # 动量指标权重
    'volume': 0.25,      # 成交量确认权重
    'breakout': 0.25,    # 突破强度权重
    'sentiment': 0.20    # 市场情绪权重
}

# 市场情绪阈值（基于涨跌幅）
SENTIMENT_THRESHOLDS = {
    'strong_bullish': 2.0,    # 强烈看多
    'bullish': 1.0,           # 看多
    'neutral': -1.0,          # 中性
    'bearish': -2.0,          # 看空
    'strong_bearish': -3.0    # 强烈看空
}

# ============================================================
# 动量指标计算
# ============================================================

def calculate_momentum_score(df: pd.DataFrame, current_price: float) -> float:
    """
    计算动量指标得分 (-1.0 到 1.0)

    考虑因素:
    - MACD指标状态
    - RSI超买超卖
    - MA趋势强度
    - 价格动量

    Returns:
        float: 动量得分，正值偏多，负值偏空
    """
    if df is None or len(df) < 20:
        return 0.0

    score = 0.0

    # MACD指标
    if 'MACD' in df.columns and 'MACD_SIGNAL' in df.columns:
        macd = df['MACD'].iloc[-1]
        signal = df['MACD_SIGNAL'].iloc[-1]
        macd_hist = macd - signal

        # MACD金叉/死叉
        if macd > signal:
            score += 0.3  # 金叉
            if macd_hist > 0:
                score += min(macd_hist / current_price * 1000, 0.2)  # 强度
        else:
            score -= 0.3  # 死叉
            if macd_hist < 0:
                score -= min(abs(macd_hist) / current_price * 1000, 0.2)

    # RSI指标
    if 'RSI' in df.columns:
        rsi = df['RSI'].iloc[-1]
        if rsi < 30:
            score += 0.2  # 超卖
        elif rsi > 70:
            score -= 0.2  # 超买
        elif 40 <= rsi <= 60:
            score += 0.1  # 健康区间

    # MA趋势强度
    if 'MA20' in df.columns and 'MA60' in df.columns:
        ma20 = df['MA20'].iloc[-1]
        ma60 = df['MA60'].iloc[-1]

        if ma20 > ma60:
            score += 0.2  # 短期在长期之上

            # 趋势加速/减速
            ma20_prev = df['MA20'].iloc[-2] if len(df) >= 2 else ma20
            if ma20 > ma20_prev:
                score += 0.1  # 趋势加速
        else:
            score -= 0.2

            ma20_prev = df['MA20'].iloc[-2] if len(df) >= 2 else ma20
            if ma20 < ma20_prev:
                score -= 0.1  # 趋势减速

    # 价格动量
    if len(df) >= 5:
        price_change = (current_price - df['close'].iloc[-5]) / df['close'].iloc[-5]
        if price_change > 0:
            score += min(price_change * 2, 0.2)
        else:
            score += max(price_change * 2, -0.2)

    return np.clip(score, -1.0, 1.0)


# ============================================================
# 成交量确认评分
# ============================================================

def calculate_volume_confirmation(df: pd.DataFrame, expected_direction: Optional[str] = None) -> float:
    """
    计算成交量确认得分 (-1.0 到 1.0)

    Args:
        df: K线数据
        expected_direction: 期望方向 ('bullish'/'bearish'/None)

    Returns:
        float: 成交量得分
    """
    if df is None or len(df) < 2 or 'volume' not in df.columns:
        return 0.0

    current_volume = df['volume'].iloc[-1]
    prev_volume = df['volume'].iloc[-2]
    avg_volume = df['volume'].tail(20).mean()

    score = 0.0

    # 成交量放大
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
    if volume_ratio > 1.5:
        score += 0.3
    elif volume_ratio > 1.2:
        score += 0.15

    # 成交量趋势
    vol_ma5 = df['volume'].tail(5).mean()
    vol_ma20 = df['volume'].tail(20).mean()
    if vol_ma5 > vol_ma20 * 1.1:
        score += 0.2

    # 价量配合
    if expected_direction:
        price_change = (df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2]
        vol_change = (current_volume - prev_volume) / prev_volume if prev_volume > 0 else 0

        if expected_direction == 'bullish':
            if price_change > 0 and vol_change > 0:
                score += 0.3  # 价涨量增
            elif price_change > 0 and vol_change < -0.2:
                score -= 0.2  # 价涨量缩
        elif expected_direction == 'bearish':
            if price_change < 0 and vol_change > 0:
                score += 0.3  # 价跌量增
            elif price_change < 0 and vol_change < -0.2:
                score -= 0.2  # 价跌量缩

    return np.clip(score, -1.0, 1.0)


# ============================================================
# 突破强度评分
# ============================================================

def calculate_breakout_strength(current_price: float, resistance_level: float,
                                support_level: float = None) -> float:
    """
    计算突破强度得分 (-1.0 到 1.0)

    Args:
        current_price: 当前价格
        resistance_level: 阻力位
        support_level: 支撑位

    Returns:
        float: 突破强度得分
    """
    score = 0.0

    # 向上突破
    if resistance_level > 0 and current_price > resistance_level:
        breakout_ratio = (current_price - resistance_level) / resistance_level
        # 突破幅度越大得分越高
        score += min(breakout_ratio * 5, 0.8)

    # 向下突破
    if support_level and support_level > 0 and current_price < support_level:
        breakdown_ratio = (support_level - current_price) / support_level
        score -= min(breakdown_ratio * 5, 0.8)

    # 距离关键位的相对位置
    if support_level and resistance_level:
        range_val = resistance_level - support_level
        if range_val > 0:
            position = (current_price - support_level) / range_val
            # 中位以上偏多，中位以下偏空
            score += (position - 0.5) * 0.4

    return np.clip(score, -1.0, 1.0)


# ============================================================
# 市场情绪评分
# ============================================================

def calculate_market_sentiment(df: pd.DataFrame, current_price: float) -> float:
    """
    计算市场情绪得分 (-1.0 到 1.0)

    基于最近涨跌幅、波动率等计算
    """
    if df is None or len(df) < 5:
        return 0.0

    score = 0.0

    # 最近涨跌幅
    recent_changes = []
    for i in range(1, min(6, len(df))):
        change = (df['close'].iloc[-i] - df['close'].iloc[-i-1]) / df['close'].iloc[-i-1]
        recent_changes.append(change)

    avg_change = np.mean(recent_changes)

    # 涨跌分布
    up_days = sum(1 for c in recent_changes if c > 0)
    total_days = len(recent_changes)
    up_ratio = up_days / total_days if total_days > 0 else 0.5

    # 涨跌幅得分
    if avg_change > SENTIMENT_THRESHOLDS['strong_bullish'] / 100:
        score += 0.5
    elif avg_change > SENTIMENT_THRESHOLDS['bullish'] / 100:
        score += 0.3
    elif avg_change < SENTIMENT_THRESHOLDS['strong_bearish'] / 100:
        score -= 0.5
    elif avg_change < SENTIMENT_THRESHOLDS['bearish'] / 100:
        score -= 0.3

    # 涨跌比例得分
    if up_ratio >= 0.7:
        score += 0.3
    elif up_ratio <= 0.3:
        score -= 0.3

    # 波动率（过高降低情绪得分）
    if len(recent_changes) >= 3:
        volatility = np.std(recent_changes)
        if volatility > 0.04:  # 日波动超过4%
            score *= 0.8  # 降低得分

    return np.clip(score, -1.0, 1.0)


# ============================================================
# 综合评分
# ============================================================

def calculate_composite_score(df: pd.DataFrame, current_price: float,
                               resistance_level: float = None,
                               support_level: float = None,
                               weights: Dict[str, float] = None) -> Dict[str, float]:
    """
    计算综合技术评分

    Args:
        df: K线数据
        current_price: 当前价格
        resistance_level: 阻力位
        support_level: 支撑位
        weights: 权重配置

    Returns:
        dict: 包含各维度得分和综合得分
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS.copy()

    # 计算各维度得分
    momentum_score = calculate_momentum_score(df, current_price)
    volume_score = calculate_volume_confirmation(df)
    breakout_score = calculate_breakout_strength(
        current_price,
        resistance_level or current_price * 1.1,
        support_level
    )
    sentiment_score = calculate_market_sentiment(df, current_price)

    # 综合得分
    total_score = (
        momentum_score * weights['momentum'] +
        volume_score * weights['volume'] +
        breakout_score * weights['breakout'] +
        sentiment_score * weights['sentiment']
    )

    return {
        'momentum': momentum_score,
        'volume': volume_score,
        'breakout': breakout_score,
        'sentiment': sentiment_score,
        'total': np.clip(total_score, -1.0, 1.0)
    }


# ============================================================
# 动态场景概率调整
# ============================================================

def dynamic_scene_probability_adjustment(
    base_probabilities: Dict[str, float],
    technical_signals: Dict[str, float],
    scenario_types: Dict[str, str]
) -> Dict[str, float]:
    """
    基于技术信号动态调整场景概率

    Args:
        base_probabilities: 基础概率字典 {场景名: 基础概率}
        technical_signals: 技术信号 {'total': 综合得分, ...}
        scenario_types: 场景类型 {场景名: 'bullish'/'bearish'/'neutral'}

    Returns:
        dict: 调整后的概率字典
    """
    total_signal = technical_signals.get('total', 0)

    adjusted_probs = {}
    for scenario, base_prob in base_probabilities.items():
        signal_factor = 1.0
        scenario_type = scenario_types.get(scenario, 'neutral')

        # 看多场景：技术信号越正，概率越高
        if scenario_type == 'bullish':
            signal_factor = 1.0 + total_signal * 0.8
        # 看空场景：技术信号越负，概率越高
        elif scenario_type == 'bearish':
            signal_factor = 1.0 - total_signal * 0.8
        # 中性场景：在信号强时概率降低
        elif scenario_type == 'neutral':
            signal_factor = 1.0 - abs(total_signal) * 0.5

        # 应用调整，确保概率范围合理
        adjusted = base_prob * signal_factor
        adjusted_probs[scenario] = min(max(adjusted, 5), 95)

    return adjust_probability_sum(adjusted_probs)


def adjust_probability_sum(probabilities: Dict[str, float]) -> Dict[str, float]:
    """
    调整概率使其总和为100%
    """
    total = sum(probabilities.values())
    if total <= 0:
        return probabilities

    scale = 100.0 / total
    return {k: v * scale for k, v in probabilities.items()}


# ============================================================
# 场景类型推断
# ============================================================

def infer_scenario_type(scenario: Dict[str, Any]) -> str:
    """
    根据场景内容推断其类型

    Args:
        scenario: 场景字典

    Returns:
        str: 'bullish'/'bearish'/'neutral'
    """
    # 从场景名推断
    name = scenario.get('name', '').lower()

    bullish_keywords = ['上升', '推动', '突破', '主升', '反弹', '上涨', '牛市', '启动', '延续']
    bearish_keywords = ['下跌', '调整', '回调', '见顶', '下跌', '熊市', '筑顶', '反转']
    neutral_keywords = ['震荡', '整理', '区间', '待定', '横盘']

    for keyword in bullish_keywords:
        if keyword in name:
            return 'bullish'

    for keyword in bearish_keywords:
        if keyword in name:
            return 'bearish'

    for keyword in neutral_keywords:
        if keyword in name:
            return 'neutral'

    # 从_bullish字段推断（如果存在）
    if '_bullish' in scenario:
        if scenario['_bullish'] is True:
            return 'bullish'
        elif scenario['_bullish'] is False:
            return 'bearish'

    # 默认返回中性
    return 'neutral'


# ============================================================
# 批量动态评分
# ============================================================

def batch_dynamic_score_scenarios(
    scenarios: List[Dict[str, Any]],
    df: pd.DataFrame,
    current_price: float,
    resistance_level: float = None,
    support_level: float = None
) -> List[Dict[str, Any]]:
    """
    批量对场景列表进行动态评分和概率调整

    Args:
        scenarios: 场景列表
        df: K线数据
        current_price: 当前价格
        resistance_level: 阻力位
        support_level: 支撑位

    Returns:
        list: 调整后的场景列表
    """
    # 计算技术信号
    tech_signals = calculate_composite_score(
        df, current_price, resistance_level, support_level
    )

    # 准备基础概率和场景类型
    base_probs = {}
    scenario_types = {}

    for scenario in scenarios:
        name = scenario.get('name', '')
        base_probs[name] = scenario.get('probability', 50)
        scenario_types[name] = infer_scenario_type(scenario)

    # 动态调整概率
    adjusted_probs = dynamic_scene_probability_adjustment(
        base_probs, tech_signals, scenario_types
    )

    # 应用调整后的概率
    adjusted_scenarios = []
    for scenario in scenarios:
        adjusted = scenario.copy()
        name = scenario.get('name', '')
        if name in adjusted_probs:
            adjusted['probability'] = round(adjusted_probs[name], 1)
            adjusted['_dynamic_adjusted'] = True
            adjusted['_tech_signals'] = tech_signals

        adjusted_scenarios.append(adjusted)

    return adjusted_scenarios
