#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论三类买卖点识别模块

三类买卖点的精确定义:
- 第一类: 趋势末端背驰点 (一买=下跌趋势底背驰, 一卖=上涨趋势顶背驰)
- 第二类: 一类买卖点后回踩/反弹不破前极值 (确认趋势反转)
- 第三类: 离开中枢后回抽不重回中枢 (趋势加速)

核心原则: 三类买卖点均围绕中枢产生，无中枢则无标准买卖点。
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Optional
from chanlun.structures import (
    Fractal, Stroke, Segment, Pivot, Divergence, TradingPoint
)


def identify_trading_points(
    df_merged: pd.DataFrame,
    pivots: List[Pivot],
    divergences: List[Divergence],
    strokes: List[Stroke],
    segments: List[Segment],
    fractals: List[Fractal]
) -> List[TradingPoint]:
    """
    识别所有三类买卖点。

    Args:
        df_merged: 合并后K线DataFrame
        pivots: 中枢列表
        divergences: 背驰列表
        strokes: 笔列表
        segments: 线段列表
        fractals: 分型列表

    Returns:
        TradingPoint列表(按时间排序)
    """
    points = []

    # Step 1: 识别第一类买卖点 (基于趋势背驰)
    type1_points = _identify_type1(df_merged, pivots, divergences)
    points.extend(type1_points)

    # Step 2: 识别第二类买卖点 (基于第一类买卖点后的回踩/反弹)
    type2_points = _identify_type2(df_merged, type1_points, strokes, fractals)
    points.extend(type2_points)

    # Step 3: 识别第三类买卖点 (基于中枢的离开和回抽)
    type3_points = _identify_type3(df_merged, pivots, strokes, fractals, segments)
    points.extend(type3_points)

    # 去重并按时间排序
    points = _deduplicate_points(points)
    points.sort(key=lambda p: p.index)

    return points


def _identify_type1(
    df_merged: pd.DataFrame,
    pivots: List[Pivot],
    divergences: List[Divergence]
) -> List[TradingPoint]:
    """
    第一类买卖点: 趋势末端的背驰点。

    条件:
    - 一买: 下跌趋势(>=2个同向下跌中枢), 最后一个中枢出现底背驰
    - 一卖: 上涨趋势(>=2个同向上涨中枢), 最后一个中枢出现顶背驰

    风险最高、空间最大，需严格确认背驰有效性。
    """
    points = []

    # 按方向分组
    down_pivots = [p for p in pivots if p.direction == -1]
    up_pivots = [p for p in pivots if p.direction == 1]

    # 一买: 下跌趋势底背驰 或 盘整底背驰
    for div in divergences:
        if div.pivot and div.pivot.direction == -1:
            if div.divergence_type == 'bottom':
                # 趋势底背驰: 确认在最后2个下跌中枢中
                if div.pivot in down_pivots[-2:]:
                    confidence = _div_strength_to_confidence(div.strength)
                    points.append(TradingPoint(
                        index=div.index,
                        date=div.date,
                        point_type=1,
                        action='buy',
                        price=div.price,
                        pivot=div.pivot,
                        divergence=div,
                        description=f"一买(底背驰): 下跌趋势动能衰竭, MACD面积从{div.entering_macd_area:.4f}降至{div.leaving_macd_area:.4f}",
                        confidence=confidence
                    ))
            elif div.divergence_type == 'consolidation_bottom':
                # 盘整底背驰: 下降一个置信度等级
                raw_conf = _div_strength_to_confidence(div.strength)
                confidence = {'high': 'medium', 'medium': 'low'}.get(raw_conf, 'low')
                points.append(TradingPoint(
                    index=div.index,
                    date=div.date,
                    point_type=1,
                    action='buy',
                    price=div.price,
                    pivot=div.pivot,
                    divergence=div,
                    description=f"一买(盘整底背驰): 中枢内动能衰竭, MACD面积从{div.entering_macd_area:.4f}降至{div.leaving_macd_area:.4f}",
                    confidence=confidence
                ))

    # 一卖: 上涨趋势顶背驰 或 盘整顶背驰
    for div in divergences:
        if div.pivot and div.pivot.direction == 1:
            if div.divergence_type == 'top':
                if div.pivot in up_pivots[-2:]:
                    confidence = _div_strength_to_confidence(div.strength)
                    points.append(TradingPoint(
                        index=div.index,
                        date=div.date,
                        point_type=1,
                        action='sell',
                        price=div.price,
                        pivot=div.pivot,
                        divergence=div,
                        description=f"一卖(顶背驰): 上涨趋势动能衰竭, MACD面积从{div.entering_macd_area:.4f}降至{div.leaving_macd_area:.4f}",
                        confidence=confidence
                    ))
            elif div.divergence_type == 'consolidation_top':
                raw_conf = _div_strength_to_confidence(div.strength)
                confidence = {'high': 'medium', 'medium': 'low'}.get(raw_conf, 'low')
                points.append(TradingPoint(
                    index=div.index,
                    date=div.date,
                    point_type=1,
                    action='sell',
                    price=div.price,
                    pivot=div.pivot,
                    divergence=div,
                    description=f"一卖(盘整顶背驰): 中枢内动能衰竭, MACD面积从{div.entering_macd_area:.4f}降至{div.leaving_macd_area:.4f}",
                    confidence=confidence
                ))

    return points


def _identify_type2(
    df_merged: pd.DataFrame,
    type1_points: List[TradingPoint],
    strokes: List[Stroke],
    fractals: List[Fractal]
) -> List[TradingPoint]:
    """
    第二类买卖点: 一类买卖点后的次级别回踩/反弹不破前极值。

    条件:
    - 二买: 一买之后，出现次级别回调:
      - 回调低点 > 一买低点 (不破前低)
      - 回调结束后的底分型位置
    - 二卖: 一卖之后，出现次级别反弹:
      - 反弹高点 < 一卖高点 (不破前高)
      - 反弹结束后的顶分型位置

    安全性比一类买卖点高，确认趋势反转。
    """
    points = []

    for tp1 in type1_points:
        # 在当前一类买卖点之后找最近的同向分型
        if tp1.action == 'buy':
            # 二买: 一买后回调不破前低
            # 找一买之后的底分型（下降笔结束后的底分型）
            for frac in fractals:
                if frac.index <= tp1.index:
                    continue
                if frac.type != 'bottom':
                    continue

                # 检查是否在一买之后的合理范围内（60个K线以内）
                if frac.index - tp1.index > 60:
                    break

                # 回调低点必须比一买高
                if frac.price > tp1.price:
                    # 确认这个底分型之前有一笔下降（回调）
                    prev_fracs = [f for f in fractals if f.index < frac.index and f.index > tp1.index]
                    if prev_fracs:
                        # 有回调但没破前低，这是二买
                        points.append(TradingPoint(
                            index=frac.index,
                            date=frac.date,
                            point_type=2,
                            action='buy',
                            price=frac.price,
                            pivot=tp1.pivot,
                            description=f"二买: 一买后回调不破前低({tp1.price:.2f}), 确认位置{frac.price:.2f}",
                            confidence='high' if frac.price > tp1.price * 1.01 else 'medium'
                        ))
                        break  # 只取最近的第一个

        elif tp1.action == 'sell':
            # 二卖: 一卖后反弹不破前高
            for frac in fractals:
                if frac.index <= tp1.index:
                    continue
                if frac.type != 'top':
                    continue

                if frac.index - tp1.index > 60:
                    break

                if frac.price < tp1.price:
                    prev_fracs = [f for f in fractals if f.index < frac.index and f.index > tp1.index]
                    if prev_fracs:
                        points.append(TradingPoint(
                            index=frac.index,
                            date=frac.date,
                            point_type=2,
                            action='sell',
                            price=frac.price,
                            pivot=tp1.pivot,
                            description=f"二卖: 一卖后反弹不破前高({tp1.price:.2f}), 确认位置{frac.price:.2f}",
                            confidence='high' if frac.price < tp1.price * 0.99 else 'medium'
                        ))
                        break

    return points


def _identify_type3(
    df_merged: pd.DataFrame,
    pivots: List[Pivot],
    strokes: List[Stroke],
    fractals: List[Fractal],
    segments: List[Segment]
) -> List[TradingPoint]:
    """
    第三类买卖点: 离开中枢后回抽不重回中枢。

    条件:
    - 三买: 次级别走势向上离开中枢后:
      - 价格突破中枢上轨ZG
      - 随后回踩
      - 回踩低点 > ZG (不进入中枢)
    - 三卖: 次级别走势向下离开中枢后:
      - 价格跌破中枢下轨ZD
      - 随后反弹
      - 反弹高点 < ZD (不进入中枢)

    趋势加速信号，代表多空力量失衡扩大。
    三买/三卖无需一类买卖点前提，独立有效。
    """
    points = []

    if not pivots:
        return points

    # 对每个中枢检查三买/三卖条件
    for pivot in pivots:
        ZG = pivot.ZG
        ZD = pivot.ZD

        # 找中枢之后的笔
        later_strokes = [s for s in strokes if s.start_idx > pivot.end_idx]
        if not later_strokes:
            continue

        # ---- 三买: 向上离开中枢后回踩不入中枢 ----
        if pivot.direction == 1:
            # 找到离开中枢的向上笔
            for i, s in enumerate(later_strokes):
                if s.direction != 1:
                    continue

                # 这笔的高点必须突破ZG
                if s.high <= ZG:
                    continue

                # 找这笔之后的回调
                following_strokes = later_strokes[i + 1:]
                for fs in following_strokes:
                    if fs.direction == -1:  # 下降笔（回调）
                        # 回调低点不能进入中枢（必须高于ZG）
                        if fs.low > ZG:
                            # 找到三买!
                            # 三买位置 = 回调笔的终点（底分型位置）
                            price = fs.end_fractal.price

                            # 确认回调低点确实在ZG之上
                            confirmed = fs.low > ZG

                            if confirmed:
                                points.append(TradingPoint(
                                    index=fs.end_idx,
                                    date=fs.end_date,
                                    point_type=3,
                                    action='buy',
                                    price=price,
                                    pivot=pivot,
                                    description=f"三买: 突破中枢上轨{ZG:.2f}后回踩{fs.low:.2f}不进入中枢, 确认位置{price:.2f}",
                                    confidence='high' if fs.low > ZG * 1.02 else 'medium'
                                ))
                        break  # 每对突破+回调只取一次

        # ---- 三卖: 向下离开中枢后反弹不入中枢 ----
        else:
            for i, s in enumerate(later_strokes):
                if s.direction != -1:
                    continue

                # 这笔的低点必须跌破ZD
                if s.low >= ZD:
                    continue

                following_strokes = later_strokes[i + 1:]
                for fs in following_strokes:
                    if fs.direction == 1:  # 上升笔（反弹）
                        if fs.high < ZD:
                            price = fs.end_fractal.price

                            confirmed = fs.high < ZD

                            if confirmed:
                                points.append(TradingPoint(
                                    index=fs.end_idx,
                                    date=fs.end_date,
                                    point_type=3,
                                    action='sell',
                                    price=price,
                                    pivot=pivot,
                                    description=f"三卖: 跌破中枢下轨{ZD:.2f}后反弹{fs.high:.2f}不进入中枢, 确认位置{price:.2f}",
                                    confidence='high' if fs.high < ZD * 0.98 else 'medium'
                                ))
                        break

    return points


def _div_strength_to_confidence(strength: str) -> str:
    """将背驰强度映射为置信度"""
    return {
        'strong': 'high',
        'normal': 'medium',
        'weak': 'low'
    }.get(strength, 'medium')


def _deduplicate_points(points: List[TradingPoint]) -> List[TradingPoint]:
    """
    去重:
    1. 同一位置同类型买卖点只保留一个
    2. 同一中枢的三类买卖点只保留第一次有效的
    """
    seen = set()
    pivot_type3_triggered = set()  # (pivot_id, action) -> already triggered
    result = []

    for p in sorted(points, key=lambda x: (x.index, x.point_type, x.action)):
        # 同一位置去重
        pos_key = (p.index, p.point_type, p.action)
        if pos_key in seen:
            continue
        seen.add(pos_key)

        # Type 3: 同一中枢同向只保留第一个信号
        if p.point_type == 3 and p.pivot:
            pivot_id = id(p.pivot)
            trigger_key = (pivot_id, p.action)
            if trigger_key in pivot_type3_triggered:
                continue
            pivot_type3_triggered.add(trigger_key)

        result.append(p)

    return result


def get_active_signals(
    trading_points: List[TradingPoint],
    current_idx: int
) -> Tuple[List[TradingPoint], List[TradingPoint]]:
    """
    获取当前时间点有效的买卖信号。

    Args:
        trading_points: 所有买卖点
        current_idx: 当前bar索引

    Returns:
        (active_buy_signals, active_sell_signals)

    信号有效期:
    - 买入信号: 直到被同类型新卖出信号覆盖
    - 卖出信号: 直到被同类型新买入信号覆盖
    """
    active_buys = []
    active_sells = []

    for tp in trading_points:
        if tp.index > current_idx:
            break

        if tp.action == 'buy':
            # 检查是否被后续卖出信号使无效
            still_valid = True
            for tp2 in trading_points:
                if tp2.index > tp.index and tp2.index <= current_idx:
                    if tp2.action == 'sell':
                        still_valid = False
                        break
            if still_valid:
                active_buys.append(tp)

        elif tp.action == 'sell':
            still_valid = True
            for tp2 in trading_points:
                if tp2.index > tp.index and tp2.index <= current_idx:
                    if tp2.action == 'buy':
                        still_valid = False
                        break
            if still_valid:
                active_sells.append(tp)

    # 只保留最近的信号
    active_buys = active_buys[-3:] if len(active_buys) > 3 else active_buys
    active_sells = active_sells[-3:] if len(active_sells) > 3 else active_sells

    return active_buys, active_sells
