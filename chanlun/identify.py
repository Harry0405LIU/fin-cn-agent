#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论核心识别算法: 包含处理 → 分型 → 笔 → 线段 → 中枢

算法链严格按照缠论的几何结构递归定义实现:
1. merge_candlesticks: K线包含处理
2. detect_fractals: 顶底分型识别
3. detect_strokes: 笔的识别
4. detect_segments: 线段的识别（基于特征序列）
5. detect_pivots: 中枢的识别
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Optional
from chanlun.structures import MergedCandle, Fractal, Stroke, Segment, Pivot


# ============================================================
# Step 1: K线包含处理
# ============================================================

def merge_candlesticks(df: pd.DataFrame) -> pd.DataFrame:
    """
    处理K线包含关系，合并相互包含的K线。

    规则:
    - 如果相邻两根K线存在包含关系(一根的高>=另一根的高 且 一根的低<=另一根的低)，
      则按趋势方向合并:
      - 向上趋势: high=max(high1,high2), low=max(low1,low2)
      - 向下趋势: high=min(high1,high2), low=min(low1,low2)
    - 合并后需回溯检查是否与更早的K线产生新的包含关系

    Args:
        df: OHLCV DataFrame, 必须有 [date, open, high, low, close, volume] 列

    Returns:
        合并后的DataFrame，额外包含 original_indices 列
    """
    if len(df) < 2:
        return df.assign(original_indices=lambda x: [[i] for i in range(len(x))])

    # 构建合并序列
    merged = []
    records = df[['date', 'open', 'high', 'low', 'close', 'volume']].to_dict('records')

    # 第一个bar原样加入
    merged.append({
        **records[0],
        'original_indices': [0]
    })

    # 遍历后续bar，遇到包含关系时递归合并，并回溯检查更早的bar
    for i in range(1, len(records)):
        merged.append({
            **records[i],
            'original_indices': [i]
        })

        while len(merged) >= 2 and _is_inclusion(merged[-2], merged[-1]):
            prev = merged[-2]
            curr = merged[-1]
            direction = _get_merge_direction(merged[:-1], curr)
            merged[-2] = _merge_two_bars(prev, curr, direction)
            merged.pop()

    result = pd.DataFrame(merged)
    # 确保日期列是字符串
    if 'date' in result.columns:
        result['date'] = result['date'].astype(str)
    return result


def _is_inclusion(c1: dict, c2: dict) -> bool:
    """判断两根K线是否存在包含关系"""
    # c1包含c2
    c1_contains_c2 = (c1['high'] >= c2['high'] and c1['low'] <= c2['low'])
    # c2包含c1
    c2_contains_c1 = (c2['high'] >= c1['high'] and c2['low'] <= c1['low'])
    return c1_contains_c2 or c2_contains_c1


def _merge_two_bars(prev: dict, curr: dict, direction: int) -> dict:
    """将两个存在包含关系的K线按趋势方向合并"""
    if direction == 1:  # 向上趋势
        new_high = max(prev['high'], curr['high'])
        new_low = max(prev['low'], curr['low'])
    else:  # 向下趋势
        new_high = min(prev['high'], curr['high'])
        new_low = min(prev['low'], curr['low'])

    return {
        'date': curr['date'],
        'open': prev['open'],
        'high': new_high,
        'low': new_low,
        'close': curr['close'],
        'volume': prev['volume'] + curr['volume'],
        'original_indices': prev['original_indices'] + curr['original_indices']
    }


def _get_merge_direction(merged: List[dict], curr: dict) -> int:
    """
    确定合并方向（向上还是向下）

    规则：
    1. 优先使用当前bar与前一bar的高低关系判断
    2. 如果仍不明确，则使用前一bar与更早bar的高低关系
    3. 最后退回到当前bar实体方向

    对于向上趋势：取"高高" => high取max, low取max
    对于向下趋势：取"低低" => high取min, low取min
    """
    if len(merged) == 0:
        return 1 if curr['close'] >= curr['open'] else -1

    prev = merged[-1]
    if curr['high'] >= prev['high'] and curr['low'] >= prev['low']:
        return 1
    if curr['high'] <= prev['high'] and curr['low'] <= prev['low']:
        return -1

    if len(merged) >= 2:
        prev_prev = merged[-2]
        if prev['high'] > prev_prev['high'] and prev['low'] > prev_prev['low']:
            return 1
        if prev['high'] < prev_prev['high'] and prev['low'] < prev_prev['low']:
            return -1

    return 1 if curr['close'] >= curr['open'] else -1


# ============================================================
# Step 2: 分型识别
# ============================================================

def detect_fractals(df_merged: pd.DataFrame) -> List[Fractal]:
    """
    识别顶分型和底分型。

    规则:
    - 顶分型: 中间K线的高点最高 且 中间K线的低点最高
    - 底分型: 中间K线的低点最低 且 中间K线的高点最低
    - 分型必须交替出现（顶→底→顶→底...）
    - 若同向分型连续出现，取极值

    Args:
        df_merged: 合并后的DataFrame

    Returns:
        交替出现的Fractal列表
    """
    if len(df_merged) < 3:
        return []

    raw_fractals = []
    highs = df_merged['high'].values
    lows = df_merged['low'].values

    for i in range(1, len(df_merged) - 1):
        h_prev, h_curr, h_next = highs[i-1], highs[i], highs[i+1]
        l_prev, l_curr, l_next = lows[i-1], lows[i], lows[i+1]

        # 顶分型: 中间高最高 且 中间低最高
        if h_curr > h_prev and h_curr > h_next and l_curr >= l_prev and l_curr >= l_next:
            raw_fractals.append(Fractal(
                index=i,
                date=str(df_merged['date'].iloc[i]),
                price=h_curr,
                type='top',
                high=h_curr,
                low=l_curr
            ))

        # 底分型: 中间低最低 且 中间高最低
        elif l_curr < l_prev and l_curr < l_next and h_curr <= h_prev and h_curr <= h_next:
            raw_fractals.append(Fractal(
                index=i,
                date=str(df_merged['date'].iloc[i]),
                price=l_curr,
                type='bottom',
                high=h_curr,
                low=l_curr
            ))

    if not raw_fractals:
        return []

    # 处理连续同向分型，保留极值
    return _filter_fractals(raw_fractals)


def _filter_fractals(fractals: List[Fractal]) -> List[Fractal]:
    """过滤连续同向分型，确保顶底交替，保留极值"""
    if len(fractals) <= 1:
        return fractals

    filtered = [fractals[0]]

    for f in fractals[1:]:
        last = filtered[-1]

        if f.type == last.type:
            # 同向：保留更极端的
            if f.type == 'top' and f.price > last.price:
                filtered[-1] = f
            elif f.type == 'bottom' and f.price < last.price:
                filtered[-1] = f
        else:
            # 反向：检查距离
            # 如果两个分型的距离太近（合并后小于2根K线），跳过
            if f.index - last.index < 2:
                # 距离太近，保留更极端的
                if (f.type == 'top' and f.price > last.price) or \
                   (f.type == 'bottom' and f.price < last.price):
                    # 跳过较弱的那个
                    continue
                else:
                    filtered.pop()
                    filtered.append(f)
            else:
                filtered.append(f)

    # 清理连续同向（第二轮）
    return _ensure_alternating(filtered)


def _ensure_alternating(fractals: List[Fractal]) -> List[Fractal]:
    """确保分型序列严格交替"""
    if len(fractals) <= 1:
        return fractals

    result = [fractals[0]]

    for f in fractals[1:]:
        if f.type == result[-1].type:
            # 再次出现同向，保留更极端的
            if f.type == 'top' and f.price > result[-1].price:
                result[-1] = f
            elif f.type == 'bottom' and f.price < result[-1].price:
                result[-1] = f
        else:
            result.append(f)

    return result


# ============================================================
# Step 3: 笔的识别
# ============================================================

def detect_strokes(
    df_merged: pd.DataFrame,
    fractals: List[Fractal],
    min_kline_count: int = 1
) -> List[Stroke]:
    """
    连接相邻反向分型构成笔。

    规则:
    - 笔连接相邻的顶分型和底分型
    - 两个分型之间至少包含min_kline_count根独立K线
    - 上升笔: 底分型 → 顶分型, 且顶>底
    - 下降笔: 顶分型 → 底分型, 且底<顶

    Args:
        df_merged: 合并后DataFrame
        fractals: 已过滤的分型列表(已交替)
        min_kline_count: 笔内最少独立K线数

    Returns:
        Stroke列表
    """
    if len(fractals) < 2:
        return []

    strokes = []

    for i in range(len(fractals) - 1):
        f1 = fractals[i]
        f2 = fractals[i + 1]

        # 必须是相反类型
        if f1.type == f2.type:
            continue

        # 确定方向
        if f1.type == 'bottom' and f2.type == 'top':
            direction = 1  # 上升笔
        elif f1.type == 'top' and f2.type == 'bottom':
            direction = -1  # 下降笔
        else:
            continue

        # 检查是否有足够的独立K线
        # 分型本身占3根K线，两个分型可能共享边，至少需要1根独立K线
        kline_span = f2.index - f1.index
        if kline_span < 3:  # 至少间隔3（两个分型中间至少1根独立K线）
            continue

        # 获取笔内的价格范围
        segment_df = df_merged.iloc[f1.index:f2.index + 1]
        if len(segment_df) == 0:
            continue

        stroke_high = segment_df['high'].max()
        stroke_low = segment_df['low'].min()

        # 方向验证
        if direction == 1 and f2.price <= f1.price:
            continue  # 上升笔必须终点>起点
        if direction == -1 and f2.price >= f1.price:
            continue  # 下降笔必须终点<起点

        # 计算振幅
        amplitude = abs(f2.price - f1.price) / f1.price if f1.price > 0 else 0

        # 检查是否满足最少K线要求
        # 分型占的K线不算"独立K线"
        independent_klines = kline_span - 2  # 去掉两个分型本身
        if independent_klines < min_kline_count:
            continue

        strokes.append(Stroke(
            start_fractal=f1,
            end_fractal=f2,
            direction=direction,
            start_idx=f1.index,
            end_idx=f2.index,
            start_date=f1.date,
            end_date=f2.date,
            kline_count=kline_span + 1,
            amplitude=amplitude,
            high=stroke_high,
            low=stroke_low,
            macd_area=0.0
        ))

    return _filter_strokes(strokes, df_merged)


def _filter_strokes(strokes: List[Stroke], df_merged: pd.DataFrame) -> List[Stroke]:
    """
    笔的二次过滤: 确保方向交替，处理笔包含关系。

    规则: 如果连续两个笔同向，合并为一个更大的笔。
    """
    if len(strokes) <= 1:
        return strokes

    result = [strokes[0]]

    for s in strokes[1:]:
        last = result[-1]

        if s.direction == last.direction:
            # 同向笔合并: 起点取第一个笔的起点，终点取第二个笔的终点
            # 价格取更极端的
            if s.direction == 1:  # 都是上升笔
                if s.end_fractal.price > last.end_fractal.price:
                    # 新笔终点更高，合并
                    merged_stroke = Stroke(
                        start_fractal=last.start_fractal,
                        end_fractal=s.end_fractal,
                        direction=1,
                        start_idx=last.start_idx,
                        end_idx=s.end_idx,
                        start_date=last.start_date,
                        end_date=s.end_date,
                        kline_count=s.end_idx - last.start_idx + 1,
                        amplitude=abs(s.end_fractal.price - last.start_fractal.price) / last.start_fractal.price if last.start_fractal.price > 0 else 0,
                        high=max(last.high, s.high),
                        low=min(last.low, s.low),
                        macd_area=0.0
                    )
                    result[-1] = merged_stroke
                # 否则保留原来的
            else:  # 都是下降笔
                if s.end_fractal.price < last.end_fractal.price:
                    merged_stroke = Stroke(
                        start_fractal=last.start_fractal,
                        end_fractal=s.end_fractal,
                        direction=-1,
                        start_idx=last.start_idx,
                        end_idx=s.end_idx,
                        start_date=last.start_date,
                        end_date=s.end_date,
                        kline_count=s.end_idx - last.start_idx + 1,
                        amplitude=abs(s.end_fractal.price - last.start_fractal.price) / last.start_fractal.price if last.start_fractal.price > 0 else 0,
                        high=max(last.high, s.high),
                        low=min(last.low, s.low),
                        macd_area=0.0
                    )
                    result[-1] = merged_stroke
        else:
            result.append(s)

    return result


# ============================================================
# Step 4: 线段识别（最复杂部分）
# ============================================================

def detect_segments(
    df_merged: pd.DataFrame,
    strokes: List[Stroke]
) -> List[Segment]:
    """
    将笔组合为线段。线段至少由3笔组成，形成稳定的趋势段。

    基于特征序列的简化实现:
    - 向上线段: 特征序列 = 各下降笔的低点
    - 向下线段: 特征序列 = 各上升笔的高点
    - 线段破坏: 当反向笔突破线段起始点的极值时发生

    简化规则:
    1. 从第1笔开始，看前3笔确定线段方向
    2. 如果s0和s2同向，线段方向 = s0的方向
    3. 线段内持续的笔都朝同一方向推进
    4. 线段破坏: 反向笔突破线段起始极值

    Args:
        df_merged: 合并后DataFrame
        strokes: 笔列表

    Returns:
        Segment列表
    """
    if len(strokes) < 3:
        return []

    segments = []
    i = 0

    while i <= len(strokes) - 3:
        s0 = strokes[i]
        s1 = strokes[i + 1]
        s2 = strokes[i + 2]

        # 用s0和s2确定线段方向
        if s0.direction == s2.direction:
            seg_direction = s0.direction
        else:
            # s0和s2方向不同，尝试用s1/s3确定
            if i + 3 < len(strokes) and strokes[i + 1].direction == strokes[i + 3].direction:
                # 从i+1开始重新检查
                i += 1
                continue
            else:
                i += 1
                continue

        # 缠论基本规则：相邻线段必须方向交替
        # 如果新线段方向与上一线段相同，则跳过此位置
        if segments and seg_direction == segments[-1].direction:
            i += 1
            continue

        # 收集属于这个线段的笔
        seg_strokes = [s0, s1, s2]
        segment_start_low = min(s.low for s in seg_strokes)
        segment_start_high = max(s.high for s in seg_strokes)

        # 特征序列
        feature_sequence = _build_feature_sequence([s0, s1, s2], seg_direction)

        # 扩展线段
        j = i + 3
        while j < len(strokes):
            next_s = strokes[j]

            # 只有当next_s的方向与线段方向相反时，才加入特征序列
            if next_s.direction != seg_direction:
                feature_seq_price = next_s.low if seg_direction == 1 else next_s.high

                # 检查特征序列是否有包含关系，有则合并
                if feature_sequence:
                    last_feature = feature_sequence[-1]
                    if (seg_direction == 1 and feature_seq_price >= last_feature) or \
                       (seg_direction == -1 and feature_seq_price <= last_feature):
                        # 有包含，合并取更极端的
                        if seg_direction == 1:
                            feature_sequence[-1] = min(feature_seq_price, last_feature)
                        else:
                            feature_sequence[-1] = max(feature_seq_price, last_feature)
                    else:
                        feature_sequence.append(feature_seq_price)
                else:
                    feature_sequence.append(feature_seq_price)

            # 线段破坏检测
            if _is_segment_broken(seg_strokes, next_s, seg_direction, feature_sequence):
                break

            seg_strokes.append(next_s)
            # 更新线段极值
            segment_start_low = min(segment_start_low, next_s.low)
            segment_start_high = max(segment_start_high, next_s.high)

            j += 1

        # 记录线段
        if len(seg_strokes) >= 3:
            seg_high = max(s.high for s in seg_strokes)
            seg_low = min(s.low for s in seg_strokes)

            segments.append(Segment(
                strokes=seg_strokes,
                direction=seg_direction,
                start_idx=seg_strokes[0].start_idx,
                end_idx=seg_strokes[-1].end_idx,
                start_date=seg_strokes[0].start_date,
                end_date=seg_strokes[-1].end_date,
                start_price=(seg_strokes[0].start_fractal.price if seg_direction == 1
                           else seg_strokes[0].start_fractal.price),
                end_price=(seg_strokes[-1].end_fractal.price if seg_direction == 1
                         else seg_strokes[-1].end_fractal.price),
                high=seg_high,
                low=seg_low
            ))

        # 前进到下一个线段：从破坏笔开始（破坏笔自然成为新线段的起始笔）
        # j 指向破坏笔（未包含在seg_strokes中），破坏笔的方向通常与当前线段相反
        i = j

    return segments


def _build_feature_sequence(strokes: List[Stroke], direction: int) -> List[float]:
    """
    构建特征序列。

    向上线段(direction=1): 特征序列 = 下降笔的低点
    向下线段(direction=-1): 特征序列 = 上升笔的高点
    """
    features = []
    for s in strokes:
        if s.direction != direction:  # 与线段方向相反的笔
            features.append(s.low if direction == 1 else s.high)
    return features


def _is_segment_broken(
    seg_strokes: List[Stroke],
    next_stroke: Stroke,
    seg_direction: int,
    feature_sequence: List[float]
) -> bool:
    """
    判断线段是否被破坏。

    多层破坏检测规则:
    1. 直接极值突破: 反向笔突破线段第一个同向笔起点的极值
    2. 特征序列分型: 特征序列出现顶/底分型
    3. 深度回撤: 长线段中反向笔回撤超过线段幅度的50%
    4. 线段过长: 超过12笔后，出现明显反向波动（仅当下一笔方向相反时触发）

    规则:
    - 向上线段(seg_direction=1): 被向下笔破坏
    - 向下线段(seg_direction=-1): 被向上笔破坏
    """
    if not seg_strokes:
        return False

    num_strokes = len(seg_strokes)
    seg_high = max(s.high for s in seg_strokes)
    seg_low = min(s.low for s in seg_strokes)
    seg_range = seg_high - seg_low

    if seg_direction == 1:
        # 向上线段
        first_up_stroke_start_low = seg_strokes[0].start_fractal.price

        # 1. 直接的线段破坏: 向下笔跌破向上线段的起点极值
        if next_stroke.direction == -1:
            if next_stroke.low < first_up_stroke_start_low:
                return True

            # 3. 深度回撤: 长线段中，反向笔回撤超过50%
            if num_strokes >= 8 and seg_range > 0:
                retracement = (seg_high - next_stroke.low) / seg_range
                if retracement > 0.5:
                    return True

        # 2. 特征序列顶分型
        if len(feature_sequence) >= 3:
            f0, f1, f2 = feature_sequence[-3], feature_sequence[-2], feature_sequence[-1]
            if f1 > f0 and f1 > f2:
                return True

        # 4. 线段过长：超过12笔后出现明显反向波动（仅当下一笔方向相反时触发）
        if num_strokes >= 12 and next_stroke.direction != seg_direction:
            recent_range = max(s.high for s in seg_strokes[-5:]) - min(s.low for s in seg_strokes[-5:])
            if seg_range > 0 and recent_range / seg_range > 0.4:
                return True

    else:
        # 向下线段
        first_down_stroke_start_high = seg_strokes[0].start_fractal.price

        # 1. 直接的线段破坏: 向上笔突破向下线段的起点极值
        if next_stroke.direction == 1:
            if next_stroke.high > first_down_stroke_start_high:
                return True

            # 3. 深度反弹: 长线段中，反向笔反弹超过50%
            if num_strokes >= 8 and seg_range > 0:
                retracement = (next_stroke.high - seg_low) / seg_range
                if retracement > 0.5:
                    return True

        # 2. 特征序列底分型
        if len(feature_sequence) >= 3:
            f0, f1, f2 = feature_sequence[-3], feature_sequence[-2], feature_sequence[-1]
            if f1 < f0 and f1 < f2:
                return True

        # 4. 线段过长：超过12笔后出现明显反向波动（仅当下一笔方向相反时触发）
        if num_strokes >= 12 and next_stroke.direction != seg_direction:
            recent_range = max(s.high for s in seg_strokes[-5:]) - min(s.low for s in seg_strokes[-5:])
            if seg_range > 0 and recent_range / seg_range > 0.4:
                return True

    return False


# ============================================================
# Step 5: 中枢识别
# ============================================================

def detect_pivots(
    df_merged: pd.DataFrame,
    segments: List[Segment]
) -> List[Pivot]:
    """
    识别中枢: 按照缠论官方定义——某级别走势类型中，被至少三个连续次级别走势类型
    (线段)所重叠的价格区间。

    缠论核心规则:
    1. 任意3个连续线段价格区间重叠(ZG > ZD)即构成中枢
       - ZG(中枢上轨) = min(三个线段的高点)
       - ZD(中枢下轨) = max(三个线段的低点)
    2. 中枢方向:
       - 上涨中枢(下-上-下): s0和s2同向向下, s1反向向上 → 方向=1(上涨)
       - 下跌中枢(上-下-上): s0和s2同向向上, s1反转向下 → 方向=-1(下跌)
    3. 中枢延伸: 后续线段继续与中枢区间重叠，最多8段(9段=升级高级别)
       - 延伸时ZG/ZD随新区间收窄: ZG = min(当前ZG, 新线段高点)
    4. 相邻中枢: 前一个中枢的离开段可作为后一个中枢的进入段(共享边界线段)
       - 但两个相邻中枢的ZG/ZD价格区间不应重叠(否则为同一中枢的延伸)

    Args:
        df_merged: 合并后DataFrame
        segments: 线段列表

    Returns:
        Pivot列表
    """
    if len(segments) < 3:
        return []

    MAX_PIVOT_SEGMENTS = 8
    pivots = []
    i = 0

    while i <= len(segments) - 3:
        s0 = segments[i]
        s1 = segments[i + 1]
        s2 = segments[i + 2]

        # 三个连续线段价格区间重叠 → 构成中枢
        ZG = min(s0.high, s1.high, s2.high)
        ZD = max(s0.low, s1.low, s2.low)

        if ZG <= ZD:
            i += 1
            continue

        # 有效中枢
        pivot_segments = [s0, s1, s2]
        current_ZG = ZG
        current_ZD = ZD

        # 中枢方向: 标准形态下s0与s2同向，中枢方向与中间段相反
        if s0.direction == s2.direction:
            direction = -s1.direction
        else:
            dirs = [s0.direction, s1.direction, s2.direction]
            direction = 1 if sum(1 for d in dirs if d == 1) >= 2 else -1

        # 中枢延伸: 后续线段继续与当前区间重叠则延伸(最多8段)
        j = i + 3
        while j < len(segments) and len(pivot_segments) < MAX_PIVOT_SEGMENTS:
            next_seg = segments[j]
            next_ZG = min(current_ZG, next_seg.high)
            next_ZD = max(current_ZD, next_seg.low)

            if next_ZG > next_ZD:
                current_ZG = next_ZG
                current_ZD = next_ZD
                pivot_segments.append(next_seg)
                j += 1
            else:
                break

        # 检查是否与前一中枢价格区间重叠（重叠=同一中枢的延伸，非新生中枢）
        is_new_pivot = True
        overlap_prev_width = 0.0
        overlap_next_width = 0.0
        has_expansion = False
        expansion_ratio_prev = 0.0
        expansion_ratio_next = 0.0

        if pivots:
            last = pivots[-1]
            overlap_width = min(current_ZG, last.ZG) - max(current_ZD, last.ZD)

            if overlap_width > 0:
                # 价格区间重叠 → 仍在同一中枢区域，跳过
                is_new_pivot = False
                overlap_prev_width = overlap_width

                # 计算扩张比例
                current_range = current_ZG - current_ZD
                expansion_ratio_prev = overlap_width / current_range if current_range > 0 else 0

                # 判断是否为明显扩张（重叠比例>30%）
                if expansion_ratio_prev > 0.3:
                    has_expansion = True

        # 检查与后续线段是否可能形成新的中枢扩张
        # 这里暂时只记录当前中枢，不预测未来
        # 在实际应用中，当新的中枢形成时会检测重叠

        if is_new_pivot:
            pivots.append(Pivot(
                segments=pivot_segments,
                direction=direction,
                ZG=current_ZG,
                ZD=current_ZD,
                start_date=pivot_segments[0].start_date,
                end_date=pivot_segments[-1].end_date,
                start_idx=pivot_segments[0].start_idx,
                end_idx=pivot_segments[-1].end_idx,
                overlap_prev_width=overlap_prev_width,
                overlap_next_width=overlap_next_width,
                has_expansion=has_expansion,
                expansion_ratio_prev=expansion_ratio_prev,
                expansion_ratio_next=expansion_ratio_next
            ))

        # 前进: 下一个中枢可从j-1开始搜索（允许共享边界线段）
        # j指向第一个不重叠的线段(或len(segments))，j-1是最后一个重叠的线段
        i = max(i + 1, j - 1)

    return pivots


# ============================================================
# 完整识别流水线
# ============================================================

def chan_identify(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[Fractal], List[Stroke], List[Segment], List[Pivot]]:
    """
    运行完整的缠论识别流水线。

    Args:
        df: 原始OHLCV DataFrame, 必须有 [date, open, high, low, close, volume] 列

    Returns:
        (df_merged, fractals, strokes, segments, pivots)
    """
    # Step 1: K线包含处理
    df_merged = merge_candlesticks(df)

    # Step 2: 分型识别
    fractals = detect_fractals(df_merged)

    # Step 3: 笔的识别
    strokes = detect_strokes(df_merged, fractals)

    # Step 4: 线段识别
    segments = detect_segments(df_merged, strokes)

    # Step 5: 中枢识别
    pivots = detect_pivots(df_merged, segments)

    return df_merged, fractals, strokes, segments, pivots
