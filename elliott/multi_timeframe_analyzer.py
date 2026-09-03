#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强型多时间框架共振分析器

核心功能:
- 多级别共振量化评估
- 信号强度量化
- 加权共振评分
- 趋势一致性分析
- 冲突检测和预警
"""

from typing import Dict, Any, List, Optional
import numpy as np

# ============================================================
# 时间框架权重配置
# ============================================================

TIMEFRAME_WEIGHTS = {
    'yearly': 0.40,    # 年线权重最高
    'monthly': 0.35,   # 月线权重
    'weekly': 0.25,     # 周线权重
    'daily': 0.00,      # 日线作为细节参考，不参与共振计算
}

# 方向评分映射
DIRECTION_SCORES = {
    'strong_bullish': 1.0,
    'bullish': 0.6,
    'weak_bullish': 0.3,
    'neutral': 0.0,
    'weak_bearish': -0.3,
    'bearish': -0.6,
    'strong_bearish': -1.0,
}

# 反向评分映射（用于看空场景被否认时）
REVERSE_DIRECTIONS = {
    'strong_bullish': 'strong_bearish',
    'bullish': 'bearish',
    'weak_bullish': 'weak_bearish',
    'neutral': 'neutral',
    'weak_bearish': 'weak_bullish',
    'bearish': 'bullish',
    'strong_bearish': 'strong_bullish',
}

# ============================================================
# 信号强度量化
# ============================================================

def quantify_signal_strength(signals: Dict[str, Any]) -> float:
    """
    量化信号强度 (-1.0 到 1.0)

    基于以下因素:
    - 确认信号数量和得分
    - 否认信号数量和得分
    - 净得分
    - 场景概率加权

    Args:
        signals: 信号检测结果字典 {
            'confirmed': [...],
            'denied': [...],
            'confirm_score': float,
            'deny_score': float,
            'directional_score': float
        }

    Returns:
        float: 信号强度，正值偏多，负值偏空
    """
    # 优先使用方向感知评分
    directional = signals.get('directional_score')
    if directional is not None:
        # 归一化到[-1, 1]
        return np.clip(directional / 3.0, -1.0, 1.0)

    # 回退到得分差值
    confirm_score = signals.get('confirm_score', 0)
    deny_score = signals.get('deny_score', 0)

    if confirm_score == 0 and deny_score == 0:
        return 0.0

    # 归一化得分差值
    max_score = max(confirm_score, deny_score)
    if max_score == 0:
        return 0.0

    normalized = (confirm_score - deny_score) / (max_score * 2) * 2  # scale to [-1, 1]
    return np.clip(normalized, -1.0, 1.0)


def classify_signal_strength(strength: float) -> str:
    """
    根据信号强度值分类

    Args:
        strength: 信号强度 (-1.0 到 1.0)

    Returns:
        str: 方向分类
    """
    abs_strength = abs(strength)

    if strength > 0.7:
        return 'strong_bullish'
    elif strength > 0.3:
        return 'bullish'
    elif strength > 0:
        return 'weak_bullish'
    elif strength < -0.7:
        return 'strong_bearish'
    elif strength < -0.3:
        return 'bearish'
    elif strength < 0:
        return 'weak_bearish'
    else:
        return 'neutral'


# ============================================================
# 多时间框架共振分析
# ============================================================

def analyze_resonance(timeframe_signals: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    多时间框架共振分析（增强版）

    Args:
        timeframe_signals: 各时间框架信号字典
            {
                'yearly': {signal_data},
                'monthly': {signal_data},
                'weekly': {signal_data}
            }

    Returns:
        dict: {
            'resonance': '强共振'/'弱共振'/'分歧'/'无信号',
            'resonance_icon': str,
            'direction': '看多'/'偏多'/'中性'/'偏空'/'看空',
            'details': str,
            'levels': {level: direction},
            'scores': {level: strength},
            'resonance_score': float,
            'warnings': list
        }
    """
    levels = {}
    scores = {}
    weighted_directional = 0.0

    # 分析每个时间框架
    for timeframe, signals in timeframe_signals.items():
        weight = TIMEFRAME_WEIGHTS.get(timeframe, 0)

        # 量化信号强度
        strength = quantify_signal_strength(signals)
        scores[timeframe] = strength

        # 分类方向
        direction = classify_signal_strength(strength)
        levels[timeframe] = direction

        # 加权方向得分
        directional_score = DIRECTION_SCORES.get(direction, 0)
        weighted_directional += weight * directional_score

    # 计算共振得分（基于方向一致性）
    resonance_score = calculate_resonance_score(levels, weighted_directional)

    # 判断共振类型和方向
    resonance_type, resonance_icon, overall_direction = classify_resonance(
        levels, weighted_directional, resonance_score
    )

    # 生成详情文本
    details = generate_resonance_details(levels, scores)

    # 检测冲突和预警
    warnings = detect_conflicts(levels, scores, overall_direction)

    return {
        'resonance': resonance_type,
        'resonance_icon': resonance_icon,
        'direction': overall_direction,
        'details': details,
        'levels': levels,
        'scores': scores,
        'resonance_score': resonance_score,
        'weighted_directional': weighted_directional,
        'warnings': warnings
    }


def calculate_resonance_score(levels: Dict[str, str],
                              weighted_directional: float) -> float:
    """
    计算共振得分 (0.0 到 1.0)

    考虑因素:
    - 方向一致性（所有级别同方向得分高）
    - 加权方向得分的绝对值（越极端得分越高）
    - 有效级别数量
    """
    if not levels:
        return 0.0

    # 计算方向一致性
    directions = list(levels.values())

    # 统计各方向数量
    bullish_count = sum(1 for d in directions if 'bullish' in d)
    bearish_count = sum(1 for d in directions if 'bearish' in d)
    neutral_count = sum(1 for d in directions if d == 'neutral')

    total = len(directions)

    # 方向一致性得分
    if bullish_count == total or bearish_count == total:
        consistency_score = 1.0  # 完全一致
    elif bullish_count >= 2 and bearish_count == 0:
        consistency_score = 0.8  # 偏多一致
    elif bearish_count >= 2 and bullish_count == 0:
        consistency_score = 0.8  # 偏空一致
    elif bullish_count > 0 and bearish_count > 0:
        consistency_score = 0.3  # 分歧
    else:
        consistency_score = 0.5  # 中性偏多或偏少

    # 加权方向得分绝对值（趋势强度）
    trend_strength = min(abs(weighted_directional), 1.0)

    # 综合共振得分
    resonance_score = consistency_score * 0.7 + trend_strength * 0.3

    return resonance_score


def classify_resonance(levels: Dict[str, str],
                       weighted_directional: float,
                       resonance_score: float) -> tuple:
    """
    分类共振类型和方向

    Returns:
        (resonance_type, icon, direction)
    """
    directions = list(levels.values())
    bullish_count = sum(1 for d in directions if 'bullish' in d)
    bearish_count = sum(1 for d in directions if 'bearish' in d)

    # 判断共振类型
    if resonance_score >= 0.8:
        resonance_type = '强共振'
    elif resonance_score >= 0.5:
        resonance_type = '弱共振'
    elif resonance_score >= 0.3:
        resonance_type = '分歧'
    else:
        resonance_type = '无信号'

    # 判断方向
    if weighted_directional > 0.5:
        direction = '看多'
        icon = '🟢🟢🟢'
    elif weighted_directional > 0.2:
        direction = '偏多'
        icon = '🟢🟢'
    elif weighted_directional < -0.5:
        direction = '看空'
        icon = '🔴🔴🔴'
    elif weighted_directional < -0.2:
        direction = '偏空'
        icon = '🔴🔴'
    else:
        direction = '中性'
        icon = '🟡'

    return resonance_type, icon, direction


def generate_resonance_details(levels: Dict[str, str],
                              scores: Dict[str, float]) -> str:
    """生成共振详情文本"""
    level_labels = {
        'yearly': '年线',
        'monthly': '月线',
        'weekly': '周线',
        'daily': '日线'
    }

    direction_icons = {
        'strong_bullish': '🟢🟢',
        'bullish': '🟢',
        'weak_bullish': '🟡',
        'neutral': '⚪',
        'weak_bearish': '🟡',
        'bearish': '🔴',
        'strong_bearish': '🔴🔴'
    }

    parts = []
    for level, direction in levels.items():
        label = level_labels.get(level, level)
        icon = direction_icons.get(direction, '⚪')
        score = scores.get(level, 0)

        # 显示得分（取整）
        score_str = f"({score:+.1f})" if abs(score) > 0.1 else ""

        parts.append(f"{label}{icon}{direction}{score_str}")

    return " | ".join(parts)


def detect_conflicts(levels: Dict[str, str],
                    scores: Dict[str, float],
                    overall_direction: str) -> List[str]:
    """
    检测冲突并生成预警

    Returns:
        list: 预警信息列表
    """
    warnings = []

    # 检测方向冲突
    directions = list(levels.values())
    bullish_count = sum(1 for d in directions if 'bullish' in d)
    bearish_count = sum(1 for d in directions if 'bearish' in d)

    # 冲突检测
    if bullish_count > 0 and bearish_count > 0:
        # 多空共存，检测哪一方占主导
        avg_score = np.mean([s for s in scores.values()])

        if overall_direction in ('看多', '偏多') and avg_score < 0:
            warnings.append(
                "⚠️ 波浪评分偏多但共振偏空，大趋势看多但短周期偏弱，需警惕短期回调风险"
            )
        elif overall_direction in ('看空', '偏空') and avg_score > 0:
            warnings.append(
                "⚠️ 波浪评分偏空但共振偏多，短周期企稳但大趋势仍弱，趋势反转尚待确认"
            )

    # 检测强度不匹配
    if 'yearly' in levels and 'weekly' in levels:
        yearly = levels['yearly']
        weekly = levels['weekly']

        yearly_bullish = 'bullish' in yearly
        weekly_bearish = 'bearish' in weekly

        if yearly_bullish and weekly_bearish:
            warnings.append(
                "⚠️ 年线看多但周线看空，可能处于调整阶段，需关注支撑位"
            )

        yearly_bearish = 'bearish' in yearly
        weekly_bullish = 'bullish' in weekly

        if yearly_bearish and weekly_bullish:
            warnings.append(
                "⚠️ 年线看空但周线看多，可能是反弹而非反转，需谨慎对待"
            )

    return warnings


# ============================================================
# 趋势一致性分析
# ============================================================

def analyze_trend_consistency(timeframe_signals: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析多时间框架趋势一致性

    Returns:
        dict: {
            'consistency_score': float (0-1),
            'trend_direction': 'bullish'/'bearish'/'neutral',
            'dominant_levels': list,
            'weakest_levels': list
        }
    """
    levels = {}
    scores = {}

    for timeframe, signals in timeframe_signals.items():
        strength = quantify_signal_strength(signals)
        scores[timeframe] = strength
        levels[timeframe] = classify_signal_strength(strength)

    if not levels:
        return {
            'consistency_score': 0.0,
            'trend_direction': 'neutral',
            'dominant_levels': [],
            'weakest_levels': []
        }

    # 计算一致性得分
    directions = list(levels.values())
    bullish_count = sum(1 for d in directions if 'bullish' in d)
    bearish_count = sum(1 for d in directions if 'bearish' in d)

    if bullish_count > bearish_count:
        trend_direction = 'bullish'
        dominant_count = bullish_count
    elif bearish_count > bullish_count:
        trend_direction = 'bearish'
        dominant_count = bearish_count
    else:
        trend_direction = 'neutral'
        dominant_count = 0

    # 一致性得分 = 主导级别数 / 总级别数
    consistency_score = dominant_count / len(levels) if levels else 0.0

    # 找出最强势和最弱势的级别
    if trend_direction == 'bullish':
        dominant_levels = [tf for tf, d in levels.items() if 'bullish' in d]
        weakest_levels = [tf for tf, d in levels.items() if 'bearish' in d]
    elif trend_direction == 'bearish':
        dominant_levels = [tf for tf, d in levels.items() if 'bearish' in d]
        weakest_levels = [tf for tf, d in levels.items() if 'bullish' in d]
    else:
        dominant_levels = []
        weakest_levels = []

    return {
        'consistency_score': consistency_score,
        'trend_direction': trend_direction,
        'dominant_levels': dominant_levels,
        'weakest_levels': weakest_levels,
        'levels': levels,
        'scores': scores
    }


# ============================================================
# 共振强度评分
# ============================================================

def calculate_resonance_strength(resonance_result: Dict[str, Any]) -> float:
    """
    计算共振强度得分 (0.0 - 10.0)

    Args:
        resonance_result: analyze_resonance() 的返回结果

    Returns:
        float: 共振强度得分
    """
    resonance_type = resonance_result.get('resonance', '无信号')
    resonance_score = resonance_result.get('resonance_score', 0.0)

    # 基于共振类型的基础分
    if resonance_type == '强共振':
        base_score = 8.0
    elif resonance_type == '弱共振':
        base_score = 5.0
    elif resonance_type == '分歧':
        base_score = 2.0
    else:  # 无信号
        base_score = 0.0

    # 用resonance_score微调
    adjusted_score = base_score * (0.5 + resonance_score * 0.5)

    return min(max(adjusted_score, 0.0), 10.0)


# ============================================================
# 快速共振检测（轻量级）
# ============================================================

def quick_resonance_check(directional_scores: Dict[str, float]) -> str:
    """
    快速共振检测（仅基于directional_score）

    Args:
        directional_scores: 各级别方向得分 {level: score}

    Returns:
        str: 'strong_bullish'/'bullish'/'neutral'/'bearish'/'strong_bearish'
    """
    if not directional_scores:
        return 'neutral'

    # 计算加权平均
    weighted_sum = 0.0
    weight_sum = 0.0

    for level, score in directional_scores.items():
        weight = TIMEFRAME_WEIGHTS.get(level, 0.25)
        weighted_sum += score * weight
        weight_sum += weight

    if weight_sum == 0:
        return 'neutral'

    avg_score = weighted_sum / weight_sum

    # 分类
    if avg_score > 1.5:
        return 'strong_bullish'
    elif avg_score > 0.5:
        return 'bullish'
    elif avg_score > -0.5:
        return 'neutral'
    elif avg_score > -1.5:
        return 'bearish'
    else:
        return 'strong_bearish'


# ============================================================
# 兼容旧接口的包装函数
# ============================================================

def analyze_multi_timeframe_correlation(index_name: str,
                                     timeframe_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    兼容旧接口的多时间框架分析包装函数

    Args:
        index_name: 指数名称（保留兼容性）
        timeframe_results: 各级别信号结果

    Returns:
        dict: 兼容旧格式的结果
    """
    result = analyze_resonance(timeframe_results)

    # 转换为旧格式
    level_labels = {'yearly': '年线', 'monthly': '月线', 'weekly': '周线', 'daily': '日线'}

    # 生成旧格式的levels
    old_levels = {}
    for level, direction in result['levels'].items():
        label = level_labels.get(level, level)
        if 'bullish' in direction:
            old_levels[label] = '看多' if 'strong' not in direction else '看多'
        elif 'bearish' in direction:
            old_levels[label] = '看空' if 'strong' not in direction else '看空'
        else:
            old_levels[label] = '中性'

    # 复用旧版本的details生成逻辑
    direction_icons = {
        '看多': '🟢',
        '偏多': '🟢',
        '中性': '🟡',
        '偏空': '🔴',
        '看空': '🔴'
    }

    details_parts = []
    for level, d in old_levels.items():
        icon = direction_icons.get(d, '⚪')
        details_parts.append(f"{level}{icon}{d}")
    details = " | ".join(details_parts)

    return {
        'resonance': result['resonance'],
        'resonance_icon': result['resonance_icon'],
        'direction': result['direction'],
        'details': details,
        'levels': old_levels,
        # 新增字段
        'resonance_score': result['resonance_score'],
        'warnings': result.get('warnings', [])
    }
