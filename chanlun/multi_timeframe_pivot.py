#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多时间框架缠论中枢分析器
结合30分钟(日线中枢)、日线(周线中枢)两个级别进行共振判断
"""

from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class MultiLevelPivotResult:
    """多级别中枢分析结果"""
    # 30分钟级别（对应日线中枢）
    tf30_state: str           # 中枢震荡/中枢上方/中枢下方/中枢扩张
    tf30_zg: float
    tf30_zd: float
    tf30_expansion: bool

    # 日线级别（对应周线中枢）
    daily_state: Optional[str]  # 可能为None（无数据）
    daily_zg: Optional[float]
    daily_zd: Optional[float]
    daily_expansion: Optional[bool]

    # 综合判断
    combined_direction: str   # 看涨/看跌/方向不明确
    combined_signal: str      # 综合信号描述


def analyze_multi_timeframe_pivot(
    tf30_chan_result: Dict[str, Any],
    daily_chan_result: Optional[Dict[str, Any]] = None
) -> MultiLevelPivotResult:
    """
    多级别中枢综合分析

    缠论级别对应关系：
    - 30分钟线段 → 日线中枢 (tf30)
    - 日线线段 → 周线中枢 (daily)

    根据两个级别的中枢状态，给出方向判断：
    - 30分钟中枢震荡 + 日线中枢上涨 = 看涨
    - 30分钟中枢震荡 + 日线中枢下跌 = 看跌
    - 30分钟中枢扩张 + 日线中枢 = 方向不明确
    """
    # 解析30分钟级别状态
    tf30_state, tf30_zg, tf30_zd, tf30_expansion = _parse_pivot_state(tf30_chan_result)

    # 解析日线级别状态
    daily_state = None
    daily_zg = None
    daily_zd = None
    daily_expansion = None

    if daily_chan_result and daily_chan_result.get("success"):
        daily_state, daily_zg, daily_zd, daily_expansion = _parse_pivot_state(daily_chan_result)

    # 综合判断
    if daily_state is None:
        # 没有日线数据时，只能基于30分钟判断
        if tf30_state == "中枢上方":
            combined_direction = "看涨"
            combined_signal = "30分钟中枢上方（仅单级别判断，日线无数据）"
        elif tf30_state == "中枢下方":
            combined_direction = "看跌"
            combined_signal = "30分钟中枢下方（仅单级别判断，日线无数据）"
        elif tf30_expansion:
            combined_direction = "方向不明确"
            combined_signal = "30分钟中枢扩张（仅单级别判断，日线无数据）"
        else:
            combined_direction = "方向不明确"
            combined_signal = "30分钟中枢震荡中（仅单级别判断，日线无数据）"
    else:
        # 有日线数据，执行多级别共振判断
        combined_direction, combined_signal = _judge_multi_level(
            tf30_state, tf30_expansion,
            daily_state, daily_expansion,
            tf30_zg, tf30_zd, daily_zg, daily_zd
        )

    return MultiLevelPivotResult(
        tf30_state=tf30_state,
        tf30_zg=tf30_zg,
        tf30_zd=tf30_zd,
        tf30_expansion=tf30_expansion,
        daily_state=daily_state,
        daily_zg=daily_zg,
        daily_zd=daily_zd,
        daily_expansion=daily_expansion,
        combined_direction=combined_direction,
        combined_signal=combined_signal,
    )


def _parse_pivot_state(chan_result: Dict[str, Any]) -> Tuple[str, float, float, bool]:
    """
    从缠论分析结果中解析中枢状态

    Returns:
        (state, zg, zd, has_expansion)
    """
    last_pivot = chan_result.get("last_pivot")
    current_price = chan_result.get("current_price", 0)

    if not last_pivot:
        return ("无中枢", 0, 0, False)

    zg = last_pivot.get("ZG", 0)
    zd = last_pivot.get("ZD", 0)
    has_expansion = last_pivot.get("has_expansion", False)

    if zg <= 0 or zd <= 0:
        return ("无中枢", 0, 0, False)

    if current_price > zg:
        state = "中枢上方"
    elif current_price < zd:
        state = "中枢下方"
    elif has_expansion:
        state = "中枢扩张"
    else:
        state = "中枢震荡"

    return state, zg, zd, has_expansion


def _judge_multi_level(
    tf30_state: str, tf30_expansion: bool,
    daily_state: str, daily_expansion: bool,
    tf30_zg: float, tf30_zd: float,
    daily_zg: float, daily_zd: float
) -> Tuple[str, str]:
    """
    多级别共振判断

    核心理念：
    - 大级别（日线=周线中枢）决定方向
    - 小级别（30分钟=日线中枢）决定时机
    - 扩张代表不确定性
    """
    # 规则0：小级别扩张 → 方向不明确（需要等待）
    if tf30_expansion and daily_expansion:
        return ("方向不明确",
                "30分钟和日线均存在中枢扩张，等待级别收敛后再判断")

    if tf30_expansion:
        if daily_state == "中枢上方":
            return ("方向不明确",
                    "30分钟中枢扩张但日线中枢上方，短期震荡偏多，等待30分钟扩张收敛")
        elif daily_state == "中枢下方":
            return ("方向不明确",
                    "30分钟中枢扩张且日线中枢下方，短期震荡偏空，等待30分钟扩张收敛")
        else:
            return ("方向不明确",
                    f"30分钟中枢扩张(日线{daily_state})，趋势方向待明确")

    if daily_expansion:
        # 日线扩张，以30分钟为参考但降低置信度
        if tf30_state == "中枢上方":
            return ("看涨",
                    "日线中枢扩张中，但30分钟中枢上方，短期偏多（注意日线扩张风险）")
        elif tf30_state == "中枢下方":
            return ("看跌",
                    "日线中枢扩张中，且30分钟中枢下方，短期偏空（注意日线扩张风险）")
        else:
            return ("方向不明确",
                    "日线中枢扩张中，30分钟震荡，等待明确方向")

    # 规则1：30分钟中枢上方 + 日线中枢上方 = 强烈看涨
    if tf30_state == "中枢上方" and daily_state == "中枢上方":
        return ("看涨", "30分钟和日线均在中枢上方，共振看涨，趋势强劲")

    # 规则2：30分钟中枢上方 + 日线中枢震荡 = 看涨
    if tf30_state == "中枢上方" and daily_state == "中枢震荡":
        return ("看涨", "30分钟中枢上方，日线中枢震荡，短期偏多")

    # 规则3：30分钟中枢上方 + 日线中枢下方 = 谨慎
    if tf30_state == "中枢上方" and daily_state == "中枢下方":
        return ("方向不明确",
                "30分钟中枢上方但日线中枢下方，可能仅为反弹，需谨慎")

    # 规则4：30分钟中枢震荡 + 日线中枢上涨 = 看涨
    if tf30_state == "中枢震荡" and daily_state == "中枢上方":
        return ("看涨", "日线中枢上方，30分钟震荡蓄势，待突破加仓")

    # 规则5：30分钟中枢震荡 + 日线中枢下跌 = 看跌
    if tf30_state == "中枢震荡" and daily_state == "中枢下方":
        return ("看跌", "日线中枢下方，30分钟震荡偏弱，注意下行风险")

    # 规则6：30分钟中枢震荡 + 日线中枢震荡 = 方向不明确
    if tf30_state == "中枢震荡" and daily_state == "中枢震荡":
        return ("方向不明确", "30分钟和日线均在中枢震荡，等待级别突破")

    # 规则7：30分钟中枢下方 + 日线中枢下方 = 强烈看跌
    if tf30_state == "中枢下方" and daily_state == "中枢下方":
        return ("看跌", "30分钟和日线均在中枢下方，共振看跌，趋势偏弱")

    # 规则8：30分钟中枢下方 + 日线中枢震荡 = 看跌
    if tf30_state == "中枢下方" and daily_state == "中枢震荡":
        return ("看跌", "30分钟中枢下方，日线中枢震荡，短期偏空")

    # 规则9：30分钟中枢下方 + 日线中枢上方 = 谨慎
    if tf30_state == "中枢下方" and daily_state == "中枢上方":
        return ("方向不明确",
                "30分钟中枢下方但日线中枢上方，可能仅为回调，关注企稳信号")

    # 默认
    return ("方向不明确", f"级别状态不明确(30分钟:{tf30_state}, 日线:{daily_state})")


def format_multi_level_pivot(result: MultiLevelPivotResult) -> str:
    """
    格式化为报告显示用的简短字符串
    """
    parts = [f"**{result.tf30_state}**"]

    if result.daily_state:
        parts.append(f"日线中枢:{{result.daily_state}}")

    parts.append(result.combined_direction)

    return " | ".join(parts)


def format_multi_level_detail(result: MultiLevelPivotResult) -> str:
    """
    格式化为报告显示用的详细字符串
    """
    lines = []
    lines.append(f"- **30分钟**: {result.tf30_state}")
    if result.tf30_zg > 0:
        lines[-1] += f" (ZG={result.tf30_zg:.2f}, ZD={result.tf30_zd:.2f})"
        if result.tf30_expansion:
            lines[-1] += " [扩张]"

    if result.daily_state:
        lines.append(f"- **日线**: {result.daily_state}")
        if result.daily_zg and result.daily_zd:
            lines[-1] += f" (ZG={result.daily_zg:.2f}, ZD={result.daily_zd:.2f})"
            if result.daily_expansion:
                lines[-1] += " [扩张]"

    lines.append(f"- **综合**: **{result.combined_direction}**")
    lines.append(f"  {result.combined_signal}")

    return "\n".join(lines)