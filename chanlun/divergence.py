#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论背驰检测模块

基于MACD动能比较，检测趋势背驰和盘整背驰:
- 趋势背驰: 趋势(>=2个同向中枢)中，离开段比进入段价格更极端但MACD面积更小
- 盘整背驰: 盘整(1个中枢)中，中枢两端同向笔/线段动量衰竭

背驰是判断走势转折的唯一客观信号。
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Optional
from chanlun.structures import Stroke, Segment, Pivot, Divergence
from core.indicators import calculate_macd


def calculate_stroke_macd_areas(
    df: pd.DataFrame,
    strokes: List[Stroke]
) -> List[Stroke]:
    """
    计算每笔的MACD柱面积(MACD_Hist的累加值)。

    MACD面积用于度量笔/线段的动量强度。面积越大，动量越强。

    Args:
        df: 已计算MACD的DataFrame(需要MACD_Hist列)，索引应映射到笔的start_idx/end_idx
        strokes: 笔列表

    Returns:
        更新了macd_area的笔列表
    """
    if 'MACD_Hist' not in df.columns:
        return strokes

    for s in strokes:
        # 确保索引有效
        start = max(0, s.start_idx)
        end = min(len(df) - 1, s.end_idx)

        if start <= end and end < len(df):
            hist_values = df['MACD_Hist'].iloc[start:end + 1]
            s.macd_area = abs(hist_values.sum()) if len(hist_values) > 0 else 0.0

    return strokes


def detect_divergence(
    df: pd.DataFrame,
    pivots: List[Pivot],
    strokes: List[Stroke],
    segments: List[Segment]
) -> List[Divergence]:
    """
    检测趋势背驰和盘整背驰。

    趋势背驰检测:
    1. 需要至少2个同向中枢
    2. 对最后一个中枢，比较进入段和离开段的动能:
       - 顶背驰: 离开段价格更高，但MACD面积更小
       - 底背驰: 离开段价格更低，但MACD面积更小

    盘整背驰检测:
    1. 只有1个中枢或中枢数量不够2个的趋势
    2. 比较中枢进入段和离开段
    3. 同样是价格更极端但MACD更小
    4. 信号强度不如趋势背驰

    Args:
        df: 已计算MACD的DataFrame
        pivots: 中枢列表
        strokes: 笔列表(含macd_area)
        segments: 线段列表

    Returns:
        Divergence列表
    """
    if not pivots:
        return []

    divergences = []

    # 按方向分组
    up_pivots = [p for p in pivots if p.direction == 1]
    down_pivots = [p for p in pivots if p.direction == -1]

    # 1. 趋势背驰检测 (需要>=2个同向中枢)
    _detect_trend_divergence(df, up_pivots, 'top', divergences)
    _detect_trend_divergence(df, down_pivots, 'bottom', divergences)

    # 2. 盘整背驰检测 (只有1个中枢或不足2个时)
    single_pivot_groups = _get_single_pivot_groups(pivots)
    for pivot in single_pivot_groups:
        _detect_consolidation_divergence(df, pivot, segments, divergences)

    # 3. 无中枢时，检查连续同向笔之间的背驰
    if not pivots:
        _detect_stroke_divergence(df, strokes, divergences)

    return sorted(divergences, key=lambda d: d.index)


def _detect_trend_divergence(
    df: pd.DataFrame,
    pivots: List[Pivot],
    div_type: str,
    divergences: List[Divergence]
):
    """检测趋势背驰: 比较最后一个中枢的进入段和离开段"""
    if len(pivots) < 2:
        return

    # 取最后一个中枢
    last_pivot = pivots[-1]

    segs = last_pivot.segments
    if len(segs) < 3:
        return

    entering_seg = segs[0]   # 进入段
    leaving_seg = segs[-1]   # 离开段

    # 找到进入段和离开段中的关键笔(与趋势同向的笔)
    entering_strokes = [s for s in entering_seg.strokes if s.direction == last_pivot.direction]
    leaving_strokes = [s for s in leaving_seg.strokes if s.direction == last_pivot.direction]

    if not entering_strokes or not leaving_strokes:
        return

    # 计算MACD面积
    entering_area = sum(abs(s.macd_area) for s in entering_strokes)
    leaving_area = sum(abs(s.macd_area) for s in leaving_strokes)

    if entering_area <= 0:
        return

    # 价格比较和背驰判断
    entering_price = entering_strokes[-1].end_fractal.price
    leaving_price = leaving_strokes[-1].end_fractal.price

    divergence_detected = False
    price_extreme = leaving_price

    if div_type == 'top':
        # 顶背驰: 价格更高但MACD更小
        if leaving_price > entering_price and leaving_area < entering_area:
            divergence_detected = True
    else:
        # 底背驰: 价格更低但MACD更小
        if leaving_price < entering_price and leaving_area < entering_area:
            divergence_detected = True

    if divergence_detected:
        # 判断强度
        area_ratio = leaving_area / entering_area if entering_area > 0 else 1.0

        # 强度映射
        if area_ratio < 0.5:
            strength = 'strong'
        elif area_ratio < 0.8:
            strength = 'normal'
        else:
            strength = 'weak'

        div_index = leaving_seg.end_idx
        div_date = leaving_seg.end_date

        divergences.append(Divergence(
            pivot=last_pivot,
            divergence_type=div_type,
            index=div_index,
            date=div_date,
            price=price_extreme,
            entering_macd_area=entering_area,
            leaving_macd_area=leaving_area,
            strength=strength
        ))


def _detect_consolidation_divergence(
    df: pd.DataFrame,
    pivot: Pivot,
    segments: List[Segment],
    divergences: List[Divergence]
):
    """检测盘整背驰: 只有一个中枢时的动能比较"""
    segs = pivot.segments
    if len(segs) < 3:
        return

    entering_seg = segs[0]
    leaving_seg = segs[-1]

    entering_strokes = [s for s in entering_seg.strokes if s.direction == pivot.direction]
    leaving_strokes = [s for s in leaving_seg.strokes if s.direction == pivot.direction]

    if not entering_strokes or not leaving_strokes:
        return

    entering_area = sum(abs(s.macd_area) for s in entering_strokes)
    leaving_area = sum(abs(s.macd_area) for s in leaving_strokes)

    if entering_area <= 0:
        return

    entering_price = entering_strokes[-1].end_fractal.price
    leaving_price = leaving_strokes[-1].end_fractal.price

    if pivot.direction == 1:
        # 上涨盘整
        # 价格必须高于中枢上轨(ZG)才是真正的创新高
        if leaving_price > entering_price and leaving_price > pivot.ZG and leaving_area < entering_area:
            div_type = 'consolidation_top'
        else:
            return
    else:
        # 下跌盘整
        # 价格应在中枢区间附近（ZD的98%-105%范围内），允许小幅波动
        if leaving_price < entering_price and leaving_area < entering_area:
            # 检查价格是否在中枢附近
            z_range = pivot.ZG - pivot.ZD
            near_zd = pivot.ZD + z_range * 0.02  # 允许ZD下方2%的波动
            if leaving_price < near_zd:
                div_type = 'consolidation_bottom'
            else:
                return  # 不在中枢附近，不是盘整背驰
        else:
            return

    area_ratio = leaving_area / entering_area if entering_area > 0 else 1.0
    strength = 'strong' if area_ratio < 0.5 else ('normal' if area_ratio < 0.8 else 'weak')

    divergences.append(Divergence(
        pivot=pivot,
        divergence_type=div_type,
        index=leaving_seg.end_idx,
        date=leaving_seg.end_date,
        price=leaving_price,
        entering_macd_area=entering_area,
        leaving_macd_area=leaving_area,
        strength=strength
    ))


def _detect_stroke_divergence(
    df: pd.DataFrame,
    strokes: List[Stroke],
    divergences: List[Divergence]
):
    """
    无中枢时，检测连续同向笔之间的背驰(最弱的信号)。
    """
    if len(strokes) < 3:
        return

    # 找连续同向的笔对
    for i in range(len(strokes) - 2):
        s0 = strokes[i]
        # 跳过中间反向笔
        for j in range(i + 2, min(i + 5, len(strokes))):
            s1 = strokes[j]
            if s0.direction != s1.direction:
                continue

            if s0.macd_area <= 0 or s1.macd_area <= 0:
                continue

            if s0.direction == 1:
                # 上升笔的顶背驰
                if s1.end_fractal.price > s0.end_fractal.price and s1.macd_area < s0.macd_area:
                    divergences.append(Divergence(
                        pivot=None,
                        divergence_type='consolidation_top',
                        index=s1.end_idx,
                        date=s1.end_date,
                        price=s1.end_fractal.price,
                        entering_macd_area=s0.macd_area,
                        leaving_macd_area=s1.macd_area,
                        strength='weak'
                    ))
            else:
                # 下降笔的底背驰
                if s1.end_fractal.price < s0.end_fractal.price and s1.macd_area < s0.macd_area:
                    divergences.append(Divergence(
                        pivot=None,
                        divergence_type='consolidation_bottom',
                        index=s1.end_idx,
                        date=s1.end_date,
                        price=s1.end_fractal.price,
                        entering_macd_area=s0.macd_area,
                        leaving_macd_area=s1.macd_area,
                        strength='weak'
                    ))


def _get_single_pivot_groups(pivots: List[Pivot]) -> List[Pivot]:
    """
    返回应进行盘整背驰检测的中枢。

    规则:
    - 同向中枢 >= 2个: 最后一个中枢做趋势背驰检测，其余做盘整背驰检测
    - 同向中枢 < 2个: 所有中枢做盘整背驰检测

    这确保了多中枢趋势中的早期中枢也不会遗漏背驰信号。
    """
    if not pivots:
        return []

    up_pivots = [p for p in pivots if p.direction == 1]
    down_pivots = [p for p in pivots if p.direction == -1]

    result = []

    # 上涨中枢: 最后一个做趋势背驰，其余(如有)做盘整背驰
    if len(up_pivots) >= 2:
        result.extend(up_pivots[:-1])
    else:
        result.extend(up_pivots)

    # 下跌中枢: 最后一个做趋势背驰，其余(如有)做盘整背驰
    if len(down_pivots) >= 2:
        result.extend(down_pivots[:-1])
    else:
        result.extend(down_pivots)

    return result


def get_macd_columns(df: pd.DataFrame, df_merged: pd.DataFrame) -> pd.DataFrame:
    """
    确保DataFrame有MACD列。

    因为MACD需要在包含处理前计算（基于原始close数据），
    但笔的索引指向合并后的DataFrame。
    我们计算MACD后，需要将MACD值映射到合并后的索引。

    简化处理：直接对合并后的df计算MACD。
    注意：这会导致MACD值略有偏差，但在实践中影响很小。

    Args:
        df: 原始DataFrame
        df_merged: 合并后DataFrame

    Returns:
        含MACD列的合并后DataFrame
    """
    # 直接在合并后数据上计算MACD
    if 'MACD_Hist' not in df_merged.columns:
        df_merged = calculate_macd(df_merged)
    return df_merged
