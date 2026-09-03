#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强型缠论中枢状态分析器
优化中枢状态识别，添加中枢扩张判断和多级别分析
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

class PivotState(Enum):
    """中枢状态枚举"""
    INSIDE_PIVOT = "中枢震荡"      # 价格在中枢区间内
    ABOVE_PIVOT = "中枢上方"        # 价格在中枢上沿之上
    BELOW_PIVOT = "中枢下方"        # 价格在中枢下沿之下
    PIVOT_EXPANSION = "中枢扩张"   # 两个相邻中枢有重叠
    NO_PIVOT = "无中枢"            # 没有有效中枢
    TREND_UP = "上涨趋势"           # 明确上涨趋势
    TREND_DOWN = "下跌趋势"         # 明确下跌趋势

@dataclass
class PivotInfo:
    """中枢信息"""
    ZG: float           # 中枢上沿
    ZD: float           # 中枢下沿
    segments_count: int # 构成中枢的线段数量
    direction: int      # 中枢方向 (1=上涨, -1=下跌)
    start_idx: int      # 起始索引
    end_idx: int        # 结束索引
    overlap_next: bool  # 与下一个中枢重叠
    overlap_prev: bool  # 与上一个中枢重叠
    expansion_ratio: float = 0.0  # 扩张比例（重叠区域占当前中枢的比例）

def analyze_pivot_states(pivots: List, current_price: float, current_idx: int) -> Dict[str, Any]:
    """
    增强型中枢状态分析

    Returns:
        dict: {
            'current_state': 当前状态,
            'pivot_info': 中枢信息,
            'multi_level_context': 多级别上下文,
            'expansion_info': 扩张信息
        }
    """
    if not pivots:
        return {
            'current_state': PivotState.NO_PIVOT,
            'pivot_info': None,
            'multi_level_context': '无有效中枢，关注中枢形成后的买卖点',
            'expansion_info': None
        }

    # 找到当前有效的中枢（包含当前价格或最近的中枢）
    current_pivot = None
    for pivot in reversed(pivots):
        if pivot.start_idx <= current_idx <= pivot.end_idx:
            current_pivot = pivot
            break

    if not current_pivot:
        # 如果没有包含当前价格的中枢，取最近的中枢
        current_pivot = pivots[-1]

    ZG = current_pivot.ZG
    ZD = current_pivot.ZD
    segments_count = len(current_pivot.segments)

    # 基础状态判断
    if current_price > ZG:
        base_state = PivotState.ABOVE_PIVOT
        position_desc = f"价格在中枢上方 ({current_price:.2f} > {ZG:.2f})"
    elif current_price < ZD:
        base_state = PivotState.BELOW_PIVOT
        position_desc = f"价格在中枢下方 ({current_price:.2f} < {ZD:.2f})"
    else:
        base_state = PivotState.INSIDE_PIVOT
        position_desc = f"价格在中枢区间内 [{ZD:.2f}, {ZG:.2f}]"

    # 检查中枢扩张（与相邻中枢重叠）
    expansion_info = None
    expansion_state = base_state

    pivot_index = pivots.index(current_pivot)

    # 检查与前一个中枢的重叠
    if pivot_index > 0:
        prev_pivot = pivots[pivot_index - 1]
        overlap_width = min(ZG, prev_pivot.ZG) - max(ZD, prev_pivot.ZD)

        if overlap_width > 0:
            # 计算扩张比例
            current_range = ZG - ZD
            expansion_ratio = overlap_width / current_range if current_range > 0 else 0

            expansion_info = {
                'type': 'with_previous',
                'overlap_width': overlap_width,
                'expansion_ratio': expansion_ratio,
                'prev_pivot_ZG': prev_pivot.ZG,
                'prev_pivot_ZD': prev_pivot.ZD,
                'current_ZG': ZG,
                'current_ZD': ZD,
                'overlap_range': [max(ZD, prev_pivot.ZD), min(ZG, prev_pivot.ZG)]
            }

            # 根据扩张比例和位置判断状态
            if expansion_ratio > 0.3:  # 重叠超过30%认为是明显扩张
                expansion_state = PivotState.PIVOT_EXPANSION
                position_desc += f" | 与前一中枢扩张 (重叠{overlap_width:.2f}元, 比例{expansion_ratio:.1%})"

    # 检查与后一个中枢的重叠（如果存在）
    if pivot_index < len(pivots) - 1:
        next_pivot = pivots[pivot_index + 1]
        overlap_width_next = min(ZG, next_pivot.ZG) - max(ZD, next_pivot.ZD)

        if overlap_width_next > 0:
            if expansion_info:
                expansion_info['with_next'] = {
                    'overlap_width': overlap_width_next,
                    'next_pivot_ZG': next_pivot.ZG,
                    'next_pivot_ZD': next_pivot.ZD
                }
            else:
                # 只有向后扩张的情况
                expansion_ratio = overlap_width_next / (ZG - ZD) if (ZG - ZD) > 0 else 0

                if expansion_ratio > 0.3:
                    expansion_state = PivotState.PIVOT_EXPANSION
                    position_desc += f" | 与后一中枢扩张 (重叠{overlap_width_next:.2f}元, 比例{expansion_ratio:.1%})"

    # 构建中枢信息
    pivot_info = {
        'ZG': ZG,
        'ZD': ZD,
        'segments_count': segments_count,
        'direction': current_pivot.direction,
        'direction_text': '上涨' if current_pivot.direction > 0 else '下跌',
        'strength': '强' if segments_count >= 6 else ('中' if segments_count >= 4 else '弱'),
        'price_range': ZG - ZD
    }

    # 多级别上下文（模拟更高级别的判断）
    multi_level_context = generate_multi_level_context(base_state, expansion_info, pivot_info)

    return {
        'current_state': expansion_state,
        'state_description': position_desc,
        'pivot_info': pivot_info,
        'multi_level_context': multi_level_context,
        'expansion_info': expansion_info
    }

def generate_multi_level_context(base_state: PivotState, expansion_info: Dict, pivot_info: Dict) -> str:
    """
    生成多级别分析建议

    在实际应用中，这里应该结合日线、周线级别的中枢分析
    现在提供基于当前状态的判断建议
    """
    if base_state == PivotState.PIVOT_EXPANSION:
        if pivot_info['direction'] > 0:
            return "上涨中枢扩张，趋势延续概率高，关注回调后的买入机会"
        else:
            return "下跌中枢扩张，反弹压力较大，建议观望"

    elif base_state == PivotState.ABOVE_PIVOT:
        if pivot_info['direction'] > 0:
            return "上涨中枢上方，趋势良好，可逢低介入"
        else:
            return "下跌中枢上方，可能是反弹，谨慎乐观"

    elif base_state == PivotState.BELOW_PIVOT:
        if pivot_info['direction'] < 0:
            return "下跌中枢下方，趋势疲弱，谨慎抄底"
        else:
            return "上涨中枢下方，回调企稳，关注支撑"

    elif base_state == PivotState.INSIDE_PIVOT:
        if pivot_info['direction'] > 0:
            return "上涨中枢震荡，蓄势待突破，耐心等待"
        else:
            return "下跌中枢震荡，弱势反弹，谨慎参与"

    else:
        return "无明确中枢，关注买卖点信号"

def format_enhanced_pivot_signal(result: Dict[str, Any]) -> str:
    """
    格式化增强版缠论信号用于报告显示

    根据增强分析结果返回更详细的状态描述
    """
    state = result['current_state']
    desc = result['state_description']
    pivot_info = result['pivot_info']
    expansion = result['expansion_info']
    multi_level = result['multi_level_context']

    # 基础状态显示
    if state == PivotState.PIVOT_EXPANSION:
        return f"**中枢扩张** {desc}"
    elif state == PivotState.INSIDE_PIVOT:
        return f"**中枢震荡** {desc}"
    elif state == PivotState.ABOVE_PIVOT:
        return f"**中枢上方** {desc}"
    elif state == PivotState.BELOW_PIVOT:
        return f"**中枢下方** {desc}"
    else:
        return "—"

# 向后兼容的原始函数
def extract_enhanced_chan_signal(chan_analysis: Dict, current_price: float = None) -> str:
    """
    增强版缠论信号提取（向后兼容）

    整合原有逻辑和新的增强分析
    """
    if not chan_analysis or not isinstance(chan_analysis, dict):
        return "N/A"

    # 使用原始逻辑获取买卖点
    from datetime import datetime, timedelta
    buy_points = chan_analysis.get("active_buys", [])
    sell_points = chan_analysis.get("active_sells", [])

    cutoff_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
    recent_buys = [bp for bp in buy_points if bp.get("date", "") >= cutoff_date]
    recent_sells = [sp for sp in sell_points if sp.get("date", "") >= cutoff_date]

    # 有买卖点时显示买卖点
    if recent_buys or recent_sells:
        parts = []
        if recent_buys:
            buy_by_type = {}
            conf_priority = {"high": 3, "medium": 2, "low": 1, "N/A": 0}
            conf_code_map = {"high": "h", "medium": "m", "low": "l", "N/A": ""}

            for bp in recent_buys:
                btype = bp.get("type", 0)
                conf = bp.get("confidence", "N/A")
                priority = conf_priority.get(conf, 0)
                code = conf_code_map.get(conf, "")

                if btype not in buy_by_type or priority > buy_by_type[btype][0]:
                    buy_by_type[btype] = (priority, code)

            buy_types = sorted(buy_by_type.keys())
            if buy_types:
                buy_signal = ",".join(f"买{t}({buy_by_type[t][1]})" for t in buy_types)
                parts.append(f"**{buy_signal}**")

        if recent_sells:
            sell_by_type = {}
            conf_priority = {"high": 3, "medium": 2, "low": 1, "N/A": 0}
            conf_code_map = {"high": "h", "medium": "m", "low": "l", "N/A": ""}

            for sp in recent_sells:
                stype = sp.get("type", 0)
                conf = sp.get("confidence", "N/A")
                priority = conf_priority.get(conf, 0)
                code = conf_code_map.get(conf, "")

                if stype not in sell_by_type or priority > sell_by_type[stype][0]:
                    sell_by_type[stype] = (priority, code)

            sell_types = sorted(sell_by_type.keys())
            if sell_types:
                sell_signal = ",".join(f"卖{t}({sell_by_type[t][1]})" for t in sell_types)
                parts.append(sell_signal)

        if parts:
            return ",".join(parts) if parts else "—"

    # 无买卖点时判断中枢状态
    last_pivot = chan_analysis.get('last_pivot', {})
    if last_pivot and current_price:
        ZG = last_pivot.get('ZG', 0)
        ZD = last_pivot.get('ZD', 0)
        has_expansion = last_pivot.get('has_expansion', False)
        expansion_ratio_prev = last_pivot.get('expansion_ratio_prev', 0.0)
        overlap_prev_width = last_pivot.get('overlap_prev_width', 0.0)

        if ZG > 0 and ZD > 0 and current_price > 0:
            expansion_suffix = ""
            if has_expansion and expansion_ratio_prev > 0:
                expansion_suffix = (
                    f" | **中枢扩张** (重叠{overlap_prev_width:.2f}元, "
                    f"比例{expansion_ratio_prev:.1%})"
                )

            if current_price > ZG:
                return f"**中枢上方** ({current_price:.2f} > {ZG:.2f})" + expansion_suffix
            elif current_price < ZD:
                return f"**中枢下方** ({current_price:.2f} < {ZD:.2f})" + expansion_suffix
            else:
                if has_expansion:
                    return (f"**中枢扩张** (区间[{ZD:.2f}, {ZG:.2f}] | "
                            f"重叠{overlap_prev_width:.2f}元, 比例{expansion_ratio_prev:.1%})")
                return f"**中枢震荡** (区间[{ZD:.2f}, {ZG:.2f}])"

    return "—"