#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个股艾略特波浪分析器 - 对齐指数分析体系

核心能力:
- 自动 zigzag 检测 + 波浪标注（复用 ElliottWaveAgent）
- 自动生成场景（带支撑/阻力/目标价/确认否认信号）
- 加权信号检测 (check_signals_weighted)
- 场景自动调整 (auto_adjust_scenario)
- 多级别共振分析 (analyze_multi_timeframe_correlation)
- 状态管理 (update_state/load_state/save_state)
- 报告格式对齐 elliott/daily_update.py 的指数日报
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

import math
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from core.data_fetcher import fetch_a_share_data, fetch_hk_data, resample_to_monthly, resample_to_weekly
from elliott.signals import (
    check_signals_weighted,
    update_state,
    load_state,
    save_state,
    auto_adjust_scenario,
    analyze_multi_timeframe_correlation,
    _round_to_significant,
)

from elliott.dynamic_scoring import (
    batch_dynamic_score_scenarios,
    calculate_composite_score,
    infer_scenario_type,
)

from elliott.breakout_detector import (
    EnhancedBreakoutDetector,
    fast_detect_breakout,
    fast_detect_breakdown,
    classify_breakout_strength,
    detect_breakouts_from_dataframe,
    CriticalChangeTracker,
)

from elliott.multi_timeframe_analyzer import (
    analyze_resonance,
    calculate_resonance_strength,
)

# ============================================================
# 状态管理封装（key 前缀 STOCK: 避免与指数冲突）
# ============================================================

def stock_update_state(state, data_date_str, level_key, symbol, scenario_name, confirmed, denied):
    return update_state(state, data_date_str, level_key, f"STOCK:{symbol}", scenario_name, confirmed, denied)


# ============================================================
# 场景模板：根据波位类型自动生成场景
# ============================================================

# 核心模板集：按趋势方向 + 波浪阶段组织
# 格式: (场景名模板, 概率, 看多/空/中性, 确认信号模板key, 否认信号模板key)

# --- 上升趋势模板 ---
_TEMPLATES_UPTREND = {
    "early": [  # 浪1/浪2 — 初期不确定
        ("上升浪启动阶段", 35, True, "bullish_breakout", "bearish_breakdown"),
        ("底部震荡蓄势", 35, None, "range_support", "range_breakdown"),
        ("反弹失败风险", 30, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "mid": [  # 浪3 — 主升
        ("主升浪第3浪延伸", 40, True, "bullish_breakout", "bearish_top"),
        ("第3浪见顶回落", 30, False, "bearish_top", "bullish_breakout"),
        ("平台整理蓄势", 30, None, "range_support", "range_breakdown"),
    ],
    "late": [  # 浪4/浪5 — 末期风险
        ("浪5冲顶进行中", 30, True, "bullish_breakout", "bearish_top"),
        ("顶部区域筑顶", 40, False, "bearish_top", "bullish_breakout"),
        ("高位震荡派发", 30, None, "range_support", "range_breakdown"),
    ],
    "extension": [  # 延伸浪
        ("推动浪延伸加速", 40, True, "bullish_breakout", "bearish_top"),
        ("延伸浪见顶回落", 30, False, "bearish_top", "bullish_breakout"),
        ("高位整理待方向", 30, None, "range_support", "range_breakdown"),
    ],
    "correction": [  # ABC调整
        ("调整浪下跌进行中", 35, False, "bearish_continuation", "bullish_reversal"),
        ("调整末端企稳反弹", 35, True, "support_hold", "bearish_continuation"),
        ("调整加深风险", 30, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "ending": [  # 浪5末端 / C浪末端
        ("浪5末端冲顶", 25, True, "bullish_breakout", "bearish_top"),
        ("顶部确认反转", 45, False, "bearish_top", "bullish_breakout"),
        ("高位震荡派发", 30, None, "range_support", "range_breakdown"),
    ],
    "reversal": [  # 趋势反转
        ("趋势反转向上确认", 35, True, "bullish_breakout", "bearish_failure"),
        ("反弹还是反转待确认", 35, None, "support_hold", "bearish_breakdown"),
        ("假突破风险", 30, False, "bearish_top", "bullish_reversal"),
    ],
    "default": [  # 上涨趋势默认
        ("上升趋势延续", 35, True, "bullish_breakout", "bearish_breakdown"),
        ("高位震荡整理", 30, None, "range_support", "range_breakdown"),
        ("回调风险加大", 35, False, "bearish_top", "bullish_reversal"),
    ],
}

# --- 下跌趋势模板 ---
_TEMPLATES_DOWNTREND = {
    "early": [  # 下跌浪1/浪2 — 初期
        ("下跌推动浪延续", 35, False, "bearish_continuation", "bullish_reversal"),
        ("超跌反弹酝酿中", 30, True, "support_hold", "bearish_continuation"),
        ("下跌中继风险", 35, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "mid": [  # 下跌浪3 — 主跌
        ("主跌浪加速下行", 40, False, "bearish_continuation", "bullish_reversal"),
        ("加速赶底阶段", 30, True, "support_hold", "bearish_continuation"),
        ("下跌中继整理", 30, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "late": [  # 下跌浪4/浪5 — 赶底
        ("下跌末浪赶底", 35, False, "bearish_continuation", "support_hold"),
        ("底部区域形成中", 35, True, "support_hold", "bearish_continuation"),
        ("下跌加速延伸风险", 30, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "extension": [  # 下跌延伸
        ("下跌延伸加速中", 40, False, "bearish_continuation", "bullish_reversal"),
        ("恐慌性赶底", 30, True, "support_hold", "bearish_continuation"),
        ("下跌中继整理", 30, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "correction": [  # 下跌后的ABC反弹
        ("反弹进行中", 30, True, "bullish_breakout", "bearish_top"),
        ("反弹见顶再下跌", 40, False, "bearish_top", "bullish_breakout"),
        ("趋势反转向上", 30, True, "bullish_breakout", "bearish_failure"),
    ],
    "ending": [  # 下跌5浪末端
        ("下跌末端底部形成", 35, True, "support_hold", "bearish_continuation"),
        ("新一轮下跌风险", 35, False, "bearish_continuation", "bullish_reversal"),
        ("底部确认尚需时间", 30, None, "range_support", "range_breakdown"),
    ],
    "reversal": [  # 下跌趋势反转
        ("下跌趋势反转确认", 35, True, "bullish_breakout", "bearish_failure"),
        ("超跌反弹待确认", 35, None, "support_hold", "bearish_breakdown"),
        ("下跌中继风险", 30, False, "bearish_breakdown", "bullish_reversal"),
    ],
    "default": [  # 下跌趋势默认
        ("下跌趋势延续", 40, False, "bearish_continuation", "bullish_reversal"),
        ("超跌反弹可能", 30, True, "support_hold", "bearish_continuation"),
        ("底部震荡整理", 30, None, "range_support", "range_breakdown"),
    ],
}

# --- 横盘/中性模板 ---
_TEMPLATES_NEUTRAL = [
    ("区间震荡偏多", 35, True, "range_support", "range_breakdown"),
    ("横盘整理待方向", 35, None, "range_support", "range_breakdown"),
    ("区间震荡偏空", 30, False, "range_breakdown", "range_support"),
]

# 保留精确匹配的旧 registry（兼容旧 position key）
SCENARIO_REGISTRY = {
    "推动浪第1浪": _TEMPLATES_UPTREND["early"],
    "推动浪第2浪调整": _TEMPLATES_UPTREND["early"],
    "推动浪第3浪": _TEMPLATES_UPTREND["mid"],
    "推动浪第4浪调整": _TEMPLATES_UPTREND["late"],
    "推动浪第5浪": _TEMPLATES_UPTREND["late"],
    "推动浪第3浪延伸": _TEMPLATES_UPTREND["extension"],
    "调整浪A浪": _TEMPLATES_UPTREND["correction"],
    "调整浪B浪反弹": _TEMPLATES_UPTREND["correction"],
    "调整浪C浪": _TEMPLATES_UPTREND["correction"],
    "调整浪C浪末端": _TEMPLATES_UPTREND["ending"],
    "新一轮上升推动浪第1浪": _TEMPLATES_UPTREND["reversal"],
    "趋势反转向上": _TEMPLATES_UPTREND["reversal"],
    "大浪5浪上升末期": _TEMPLATES_UPTREND["ending"],
    "大浪5浪上升末期(顶部确认)": _TEMPLATES_UPTREND["ending"],
    "大浪5浪上升后ABC调整": _TEMPLATES_UPTREND["correction"],
    "大浪顶部后ABC调整": _TEMPLATES_UPTREND["correction"],
    # 下跌趋势
    "下跌推动浪第1浪": _TEMPLATES_DOWNTREND["early"],
    "下跌推动浪第2浪反弹": _TEMPLATES_DOWNTREND["early"],
    "下跌推动浪第3浪": _TEMPLATES_DOWNTREND["mid"],
    "下跌推动浪第4浪反弹": _TEMPLATES_DOWNTREND["late"],
    "下跌推动浪第5浪": _TEMPLATES_DOWNTREND["late"],
    "下跌推动浪第3浪延伸": _TEMPLATES_DOWNTREND["extension"],
    "下跌5浪后A浪反弹": _TEMPLATES_DOWNTREND["correction"],
    "下跌5浪后B浪回落": _TEMPLATES_DOWNTREND["correction"],
    "下跌5浪后C浪反弹": _TEMPLATES_DOWNTREND["correction"],
    "下跌5浪后A浪反弹末端": _TEMPLATES_DOWNTREND["ending"],
    "下跌5浪后反弹末端": _TEMPLATES_DOWNTREND["ending"],
    "下跌5浪后趋势反转": _TEMPLATES_DOWNTREND["reversal"],
    # 中性
    "调整浪": _TEMPLATES_NEUTRAL,
    "数据不足": _TEMPLATES_NEUTRAL,
    "未知": _TEMPLATES_NEUTRAL,
}


def _match_templates(position: str, trend: str) -> list:
    """
    基于关键词模糊匹配场景模板（处理 zigzag 产生的 40+ 种 position 字符串）。

    匹配策略（按优先级）：
    1. 精确匹配 SCENARIO_REGISTRY
    2. 按关键词推断趋势方向 + 波浪阶段，选择对应模板族
    3. 根据 MA20/MA60 趋势选择趋势感知的默认模板

    Args:
        position: zigzag 标注的波位字符串
        trend: MA20/MA60 趋势 ("上涨"/"下跌"/"横盘")

    Returns:
        场景模板列表 [(name, prob, bullish, confirm_key, deny_key), ...]
    """
    # Step 1: 精确匹配
    if position in SCENARIO_REGISTRY:
        return SCENARIO_REGISTRY[position]

    # Step 2: 关键词推断
    is_down = "下跌" in position or "下降" in position
    is_up = "上升" in position or "上涨" in position or "新一轮" in position
    is_reversal = "反转" in position
    is_ending = "末端" in position or "末期" in position
    is_extension = "延伸" in position
    is_abc = "ABC" in position or "调整浪" in position or "调整" in position
    is_impulse = "推动浪" in position
    is_correction_wave = "反弹" in position or "A浪" in position or "B浪" in position or "C浪" in position

    # Determine trend family
    if is_reversal:
        # Reversal: direction flips
        if is_up or "向上" in position:
            return _TEMPLATES_UPTREND["reversal"]
        elif is_down or "向下" in position:
            return _TEMPLATES_DOWNTREND["reversal"]
        else:
            return _TEMPLATES_UPTREND["reversal"] if trend == "下跌" else _TEMPLATES_DOWNTREND["reversal"]

    if is_down:
        family = _TEMPLATES_DOWNTREND
    elif is_up:
        family = _TEMPLATES_UPTREND
    else:
        # 无法从 position 判断方向 → 用 MA 趋势决定
        family = _TEMPLATES_UPTREND if trend == "上涨" else _TEMPLATES_DOWNTREND if trend == "下跌" else None

    if family is None:
        return _TEMPLATES_NEUTRAL

    # Determine wave phase
    if is_extension:
        return family["extension"]
    if is_ending:
        return family["ending"]
    if "第1浪" in position or "第2浪" in position:
        return family["early"]
    if "第3浪" in position and "第3浪延伸" not in position:
        return family["mid"]
    if "第4浪" in position or "第5浪" in position:
        return family["late"]
    if is_correction_wave or is_abc:
        return family["correction"]
    if is_impulse:
        return family["mid"]  # 通用推动浪 → 中期

    # Step 3: 趋势感知的默认模板
    return family["default"]


def _get_default_by_trend(trend: str) -> list:
    """根据 MA 趋势返回趋势感知的默认模板"""
    if trend == "上涨":
        return _TEMPLATES_UPTREND["default"]
    elif trend == "下跌":
        return _TEMPLATES_DOWNTREND["default"]
    else:
        return _TEMPLATES_NEUTRAL

# 信号模板：根据场景类型生成 confirm/deny 信号
SIGNAL_TEMPLATES = {
    "bullish_breakout": {
        "confirm": ["突破{resistance}", "放量上攻", "回调不跌破{support}"],
        "deny": ["跌破{support}且无法收复", "{resistance}附近双顶", "量价背离明显"],
    },
    "bearish_top": {
        "confirm": ["{resistance}附近受阻回落", "跌破{mid}", "MACD顶背离"],
        "deny": ["突破{resistance}创新高", "回调幅度有限", "指标持续走强"],
    },
    "bearish_breakdown": {
        "confirm": ["跌破{support}", "放量下跌", "反弹无力"],
        "deny": ["{support}支撑有效", "缩量企稳", "形成双底"],
    },
    "bullish_reversal": {
        "confirm": ["突破{mid}", "形成更高低点", "MACD金叉"],
        "deny": ["跌破{support}创新低", "反弹夭折", "量能不足"],
    },
    "support_hold": {
        "confirm": ["{support}支撑有效", "缩量企稳", "形成更高低点"],
        "deny": ["跌破{support}", "放量下破", "反弹无力"],
    },
    "support_break": {
        "confirm": ["跌破{support}", "反弹无法收复{support}", "技术指标转弱"],
        "deny": ["{support}支撑有效", "快速收复{support}", "形成双底"],
    },
    "range_support": {
        "confirm": ["{support}支撑有效", "{resistance}压力明显", "波动率收窄"],
        "deny": ["跌破{support}", "突破{resistance}", "波动率突然放大"],
    },
    "range_breakdown": {
        "confirm": ["跌破{support}", "波动率放大", "反弹无力"],
        "deny": ["{support}支撑有效", "缩量企稳", "形成双底"],
    },
    "bearish_continuation": {
        "confirm": ["跌破{support}", "反弹受阻{mid}", "技术指标持续走弱"],
        "deny": ["突破{mid}并站稳", "形成更高低点", "底部放量"],
    },
    "bearish_failure": {
        "confirm": ["{resistance}受阻回落", "跌破{mid}", "MACD死叉"],
        "deny": ["突破{resistance}并站稳", "量价配合良好", "回调不破{support}"],
    },
}


def _format_price(price: float, reference: float = 100) -> str:
    """根据价格量级格式化显示"""
    price = float(price)
    if reference >= 1000:
        return f"{price:,.0f}"
    elif reference >= 100:
        return f"{price:.1f}"
    elif reference >= 10:
        return f"{price:.2f}"
    else:
        return f"{price:.3f}"


def _generate_signals(template_key: str, support: float, resistance: float, reference: float = 100) -> Tuple[List[str], List[str]]:
    """根据模板生成确认/否认信号（嵌入实际价位）"""
    tpl = SIGNAL_TEMPLATES.get(template_key, SIGNAL_TEMPLATES["bullish_breakout"])
    mid = (support + resistance) / 2

    fmt_s = _format_price(support, reference)
    fmt_r = _format_price(resistance, reference)
    fmt_m = _format_price(mid, reference)

    confirm = []
    for s in tpl["confirm"]:
        s = s.replace("{support}", fmt_s).replace("{resistance}", fmt_r).replace("{mid}", fmt_m)
        confirm.append(s)

    deny = []
    for s in tpl["deny"]:
        s = s.replace("{support}", fmt_s).replace("{resistance}", fmt_r).replace("{mid}", fmt_m)
        deny.append(s)

    return confirm, deny


def _find_nearest_support(wave_points: List[Dict], current_price: float, fib_levels: Dict[str, float]) -> float:
    """从浪点中找到最近的支撑位"""
    candidates = []
    if wave_points:
        lows = [wp for wp in wave_points if wp['type'] == 'LOW' and wp['price'] < current_price]
        if lows:
            nearest = max(lows, key=lambda wp: wp['price'])
            candidates.append(nearest['price'])

    # 从斐波那契位补充
    for v in fib_levels.values():
        if v < current_price * 0.99:
            candidates.append(float(v))

    if candidates:
        return max(candidates)
    return current_price * 0.9


def _find_nearest_resistance(wave_points: List[Dict], current_price: float, fib_levels: Dict[str, float], high_price: float) -> float:
    """从浪点中找到最近的阻力位"""
    candidates = []
    if wave_points:
        highs = [wp for wp in wave_points if wp['type'] == 'HIGH' and wp['price'] > current_price]
        if highs:
            nearest = min(highs, key=lambda wp: wp['price'])
            candidates.append(nearest['price'])

    # 从斐波那契位补充
    for v in fib_levels.values():
        if v > current_price * 1.01:
            candidates.append(float(v))

    if candidates:
        return min(candidates)
    return current_price * 1.1


def _compute_target(support: float, resistance: float, is_bullish: Optional[bool], wave_position: str) -> str:
    """根据场景方向计算目标价区间"""
    range_val = resistance - support
    if is_bullish:
        t1 = resistance + range_val * 0.382
        t2 = resistance + range_val * 0.618
    elif is_bullish is False:
        t1 = support - range_val * 0.382
        t2 = support - range_val * 0.618
    else:
        return "突破方向待定"

    ref = max(support, resistance)
    return f"{_format_price(min(t1, t2), ref)}-{_format_price(max(t1, t2), ref)}"


def auto_generate_scenarios(
    wave_result: Dict[str, Any],
    current_price: float,
    high_price: float,
    low_price: float,
    fib_levels: Dict[str, float],
    timeframe_label: str = "日线",
    ma_trend: str = ""
) -> List[Dict[str, Any]]:
    """
    将 zigzag 波浪识别结果转换为指数体系标准场景格式。

    Args:
        wave_result: _label_waves() 或 _detect_wave_position() 的返回结果
        current_price: 当前收盘价
        high_price: 历史最高（数据范围内）
        low_price: 历史最低（数据范围内）
        fib_levels: 斐波那契回调位字典 {level_name: price}
        timeframe_label: 时间级别标签
        ma_trend: MA20/MA60 趋势 ("上涨"/"下跌"/"横盘")，用于模糊匹配的后备方向判断

    Returns:
        场景列表，每个场景格式对齐 INDICES 手工场景:
        {name, probability, key_support, key_resistance, wave_position, target, confirm_signals, deny_signals}
    """
    position = wave_result.get("position", "推动浪第3浪")
    wave_points = wave_result.get("wave_points", [])
    description = wave_result.get("description", "")
    detail = wave_result.get("detail", {})

    # 查找支撑位和阻力位
    support = _find_nearest_support(wave_points, current_price, fib_levels)
    resistance = _find_nearest_resistance(wave_points, current_price, fib_levels, high_price)

    # 圆整价位
    ref_price = max(current_price, resistance)
    support = _round_to_significant(support, ref_price)
    resistance = _round_to_significant(resistance, ref_price)

    # 选择合适的场景模板（关键词模糊匹配 + 趋势感知默认）
    # 优先使用 position 中的方向关键词，其次使用 MA 趋势
    trend_hint = ma_trend
    if "下跌" in position:
        trend_hint = "下跌"
    elif "上升" in position or "上涨" in position:
        trend_hint = "上涨"
    templates = _match_templates(position, trend_hint)

    scenarios = []
    for name_tpl, probability, bullish, confirm_key, deny_key in templates:
        target = _compute_target(support, resistance, bullish, position)
        confirm_sigs, deny_sigs = _generate_signals(confirm_key, support, resistance, ref_price)

        wave_pos_desc = f"{timeframe_label}{name_tpl}"
        if description:
            wave_pos_desc += f"，{description}"

        scenarios.append({
            "name": name_tpl,
            "probability": probability,
            "key_support": support,
            "key_resistance": resistance,
            "wave_position": wave_pos_desc,
            "target": target,
            "confirm_signals": confirm_sigs,
            "deny_signals": deny_sigs,
            "_bullish": bullish,
        })

    return scenarios


# ============================================================
# 默认场景生成（zigzag 失败时的后备方案）
# ============================================================

def generate_default_scenarios(
    current_price: float,
    high_price: float,
    low_price: float,
    fib_levels: Dict[str, float],
    trend: str,
    timeframe_label: str = "日线"
) -> List[Dict[str, Any]]:
    """zigzag 失败时的后备场景生成（趋势感知 + 斐波那契位）"""
    ref = max(current_price, high_price)

    if trend == "上涨":
        support = _round_to_significant(fib_levels.get("38.2%", current_price * 0.95), ref)
        resistance = _round_to_significant(high_price, ref)
        tpls = _TEMPLATES_UPTREND["default"]
    elif trend == "下跌":
        support = _round_to_significant(low_price, ref)
        resistance = _round_to_significant(fib_levels.get("61.8%", current_price * 1.05), ref)
        tpls = _TEMPLATES_DOWNTREND["default"]
    else:
        support = _round_to_significant(fib_levels.get("50%", current_price * 0.95), ref)
        resistance = _round_to_significant(fib_levels.get("50%", current_price * 1.05), ref)
        tpls = _TEMPLATES_NEUTRAL

    scenarios = []
    for name, prob, bullish, ck, dk in tpls:
        target = _compute_target(support, resistance, bullish, name)
        confirm_sigs, deny_sigs = _generate_signals(ck, support, resistance, ref)
        scenarios.append({
            "name": name,
            "probability": prob,
            "key_support": support,
            "key_resistance": resistance,
            "wave_position": f"{timeframe_label}波浪结构待确认（指标推断）",
            "target": target,
            "confirm_signals": confirm_sigs,
            "deny_signals": deny_sigs,
            "_bullish": bullish,
        })
    return scenarios


def _extract_anchor_pivots(higher_result: Dict[str, Any], max_anchors: int = 8) -> list:
    """从高级别分析结果中提取关键浪点，作为低级别 zigzag 的结构锚点。

    只取最近 N 个浪点（默认 8 个 = 约一个完整五浪+ABC）。
    传全部浪点会导致低级别 zigzag 过拟合（周线出现 150+ 标注浪点）。
    锚点使用负 idx（表示"窗口外"）以保持时间顺序。
    """
    wave_points = higher_result.get("wave_points", [])
    if not wave_points:
        return []

    # 只取最近的几个浪点，覆盖当前结构的上下文
    recent = wave_points[-max_anchors:] if len(wave_points) > max_anchors else wave_points

    anchors = []
    for i, wp in enumerate(recent):
        anchors.append({
            'idx': -(len(recent) - i),
            'price': wp['price'],
            'type': wp['type'],
            'date': wp.get('date', ''),
        })
    return anchors


# ============================================================
# StockWaveAnalyzer 主类
# ============================================================

class StockWaveAnalyzer:
    """个股艾略特波浪分析器（对齐指数分析体系）"""

    def __init__(self, symbol: str, name: str, market: str = 'SH', use_enhanced: bool = True):
        """
        Args:
            symbol: akshare 格式代码 (如 'sh600519', 'hk00700')
            name: 股票名称
            market: 市场 SH/SZ/HK
            use_enhanced: 是否使用增强型分析（动态评分+突破检测）
        """
        self.symbol = symbol
        self.name = name
        self.market = market
        self.daily_df = None
        self.weekly_df = None
        self.monthly_df = None
        self._wave_agent = None  # 延迟初始化
        self.use_enhanced = use_enhanced
        self._breakout_detector = None  # 延迟初始化
        self._change_tracker = None  # 关键变化追踪器

    def _get_wave_agent(self):
        """延迟初始化 ElliottWaveAgent（避免不必要的初始化开销）"""
        if self._wave_agent is None:
            from agents.analysis.elliott_agent import ElliottWaveAgent
            self._wave_agent = ElliottWaveAgent(config={"webhook_url": None})
        return self._wave_agent

    def _get_breakout_detector(self):
        """延迟初始化 EnhancedBreakoutDetector"""
        if self._breakout_detector is None and self.use_enhanced:
            self._breakout_detector = EnhancedBreakoutDetector()
        return self._breakout_detector

    def _get_change_tracker(self):
        """获取或初始化关键变化追踪器"""
        if self._change_tracker is None and self.use_enhanced:
            self._change_tracker = CriticalChangeTracker()
        return self._change_tracker

    def _enhanced_scenario_scoring(self, scenarios: List[Dict[str, Any]],
                                  df: pd.DataFrame,
                                  current_price: float,
                                  resistance_level: float = None,
                                  support_level: float = None) -> List[Dict[str, Any]]:
        """
        使用增强型评分系统调整场景概率

        Args:
            scenarios: 原始场景列表
            df: K线数据
            current_price: 当前价格
            resistance_level: 阻力位
            support_level: 支撑位

        Returns:
            list: 调整后的场景列表
        """
        if not self.use_enhanced or not scenarios:
            return scenarios

        # 使用批量动态评分
        adjusted_scenarios = batch_dynamic_score_scenarios(
            scenarios, df, current_price, resistance_level, support_level
        )

        # 增加突破检测信息
        if self._breakout_detector:
            for scenario in adjusted_scenarios:
                resistance = scenario.get('key_resistance', float('inf'))
                support = scenario.get('key_support', 0)

                # 向上突破检测
                if resistance < current_price * 1.5:  # 合理范围内的阻力位
                    is_breakout, strength = fast_detect_breakout(
                        current_price, resistance,
                        df['volume'] if 'volume' in df.columns else None
                    )
                    scenario['_breakout_status'] = {
                        'is_breakout': is_breakout,
                        'strength': strength,
                        'class': classify_breakout_strength(strength) if is_breakout else '未突破'
                    }

                # 向下突破检测
                if support > 0 and support < current_price * 0.9:
                    is_breakdown, strength = fast_detect_breakdown(
                        current_price, support,
                        df['volume'] if 'volume' in df.columns else None
                    )
                    scenario['_breakdown_status'] = {
                        'is_breakdown': is_breakdown,
                        'strength': strength,
                        'class': classify_breakout_strength(strength) if is_breakdown else '未跌破'
                    }

        return adjusted_scenarios

    def _detect_key_breakouts(self, df: pd.DataFrame,
                                current_price: float,
                                fib_levels: Dict[str, float]) -> Dict[str, Any]:
        """
        检测关键位的突破

        Args:
            df: K线数据
            current_price: 当前价格
            fib_levels: 斐波那契位

        Returns:
            dict: 突破检测结果
        """
        if not self.use_enhanced:
            return {'breakouts': [], 'breakdowns': []}

        # 提取阻力和支撑位
        resistance_levels = [v for k, v in fib_levels.items() if v > current_price]
        support_levels = [v for k, v in fib_levels.items() if v < current_price]

        # 批量检测
        return detect_breakouts_from_dataframe(df, resistance_levels, support_levels)

    def fetch_data(self, years: int = 10) -> bool:
        """获取日线数据并重采样为周线/月线"""
        print(f"  正在获取 {self.name} ({self.symbol}) 的数据...")
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=years * 365)).strftime('%Y-%m-%d')

        try:
            if self.market == 'HK':
                self.daily_df = fetch_hk_data(self.symbol, start_date, end_date)
            else:
                self.daily_df = fetch_a_share_data(self.symbol, start_date, end_date)
        except Exception as e:
            print(f"  获取数据异常: {e}")
            return False

        if self.daily_df is None or self.daily_df.empty:
            print(f"  无法获取 {self.symbol} 的数据")
            return False

        print(f"  获取到 {len(self.daily_df)} 条日线数据")

        df_copy = self.daily_df.copy()
        df_copy['date'] = pd.to_datetime(df_copy['date'])
        df_copy = df_copy.set_index('date')

        self.monthly_df = resample_to_monthly(df_copy)
        self.weekly_df = resample_to_weekly(df_copy)

        print(f"  月线: {len(self.monthly_df)} 条, 周线: {len(self.weekly_df)} 条")
        return True

    def _analyze_timeframe(self, df: pd.DataFrame, level_key: str, level_name: str,
                           anchor_pivots: list = None) -> Dict[str, Any]:
        """
        对单个时间级别运行完整的 zigzag 检测 + 波浪标注 + 场景生成。

        Args:
            df: 该级别的K线数据（日/周/月）
            level_key: 'daily'/'weekly'/'monthly'
            level_name: '日线'/'周线'/'月线'
            anchor_pivots: 高级别传递下来的关键拐点锚点列表（自上而下分析链）

        Returns:
            {
                'current_price', 'high_price', 'low_price',
                'fib_levels', 'trend', 'scenarios',
                'wave_result', 'ma20', 'ma60', 'anchor_pivots'
            }
        """
        if df is None or len(df) < 30:
            return {}

        # 重置索引，确保 date 是列
        work_df = df.copy()
        if isinstance(work_df.index, pd.DatetimeIndex):
            work_df = work_df.reset_index()

        current_price = float(work_df.iloc[-1]['close'])
        high_price = float(work_df['high'].max())
        low_price = float(work_df['low'].min())

        # 斐波那契回调位
        diff = high_price - low_price
        fib_levels = {
            '0%': high_price,
            '23.6%': high_price - 0.236 * diff,
            '38.2%': high_price - 0.382 * diff,
            '50%': high_price - 0.5 * diff,
            '61.8%': high_price - 0.618 * diff,
            '78.6%': high_price - 0.786 * diff,
            '100%': low_price,
        }

        # MA 趋势
        work_df['MA20'] = work_df['close'].rolling(20).mean()
        work_df['MA60'] = work_df['close'].rolling(60).mean()
        ma20 = float(work_df['MA20'].iloc[-1]) if not pd.isna(work_df['MA20'].iloc[-1]) else 0
        ma60 = float(work_df['MA60'].iloc[-1]) if not pd.isna(work_df['MA60'].iloc[-1]) else 0
        trend = "上涨" if ma20 > ma60 else "下跌" if ma20 < ma60 else "横盘"

        # 尝试 zigzag 波浪检测
        scenarios = None
        wave_result = None

        try:
            agent = self._get_wave_agent()
            # 计算指标
            df_with_indicators = agent._calculate_wave_indicators(work_df)

            # 多分辨率 zigzag
            # 月线使用更高阈值（0.25），过滤子浪级别的微小转折（13-22%），
            # 只保留主浪结构（30%+），配合 _label_downward_waves 的浪5底
            # 延伸逻辑，自动产出干净的三段式结构。
            # 周线/日线保持双分辨率（0.15 + 0.08）捕捉更多细节。
            MAX_BARS = 500
            df_zigzag = df_with_indicators.tail(MAX_BARS) if len(df_with_indicators) > MAX_BARS else df_with_indicators

            if level_key == 'monthly':
                coarse_threshold = 0.25
                pivots_coarse = agent._detect_zigzag(df_zigzag, threshold=coarse_threshold)
                # 慢速股票（如长江电力）月线波动小，高阈值可能检不出足够转折点
                if len(pivots_coarse) < 4:
                    pivots_coarse = agent._detect_zigzag(df_zigzag, threshold=0.15)
                # 同时检测细粒度zigzag，用于验证波浪铁律并选择更优浪型
                # 0.25粗粒度可能遗漏重要转折（如阿里巴巴遗漏129/101等），
                # 通过validate_wave_count对比粗/细粒度可选出更合理的浪型标注
                pivots_fine = agent._detect_zigzag(df_zigzag, threshold=0.15)
            else:
                coarse_threshold = 0.15
                pivots_coarse = agent._detect_zigzag(df_zigzag, threshold=0.15)
                pivots_fine = agent._detect_zigzag(df_zigzag, threshold=0.08)

            # 自上而下分析链：从高级别结果注入关键拐点作为锚点
            # 月线 zigzag 全覆盖，但日线 tail(500) 可能遗漏早期的极限高低点
            if anchor_pivots:
                pivots_coarse = list(anchor_pivots) + list(pivots_coarse)
                if pivots_fine is not None:
                    pivots_fine = list(anchor_pivots) + list(pivots_fine)

            coarse_result = agent._label_waves(pivots_coarse, current_price)
            fine_result = agent._label_waves(pivots_fine, current_price) if pivots_fine is not None else None

            # 验证并选择更优的波浪计数
            # 月线只有 coarse，直接使用
            if fine_result is not None:
                try:
                    wave_result = agent._validate_wave_count(coarse_result, fine_result, current_price)
                except Exception:
                    wave_result = coarse_result if len(coarse_result.get("wave_points", [])) >= len(fine_result.get("wave_points", [])) else fine_result
            else:
                wave_result = coarse_result

            # 如果 zigzag 成功，生成场景
            if wave_result and wave_result.get("position") != "数据不足" and wave_result.get("wave_points"):
                scenarios = auto_generate_scenarios(
                    wave_result, current_price, high_price, low_price, fib_levels, level_name, trend
                )
        except Exception as e:
            # zigzag 失败，使用后备方案
            pass

        # 后备方案：基于趋势+斐波那契的通用场景
        if scenarios is None:
            scenarios = generate_default_scenarios(
                current_price, high_price, low_price, fib_levels, trend, level_name
            )

        # 增强型评分：动态调整场景概率并检测突破
        if scenarios and self.use_enhanced:
            scenarios = self._enhanced_scenario_scoring(
                scenarios, work_df, current_price, fib_levels.get('50%'), fib_levels.get('50%')
            )

        # 提取关键拐点向下传递（自上而下分析链）
        # 合并上级传入的锚点 + 本级新发现的浪点，避免锚点在传递中丢失
        new_anchors = _extract_anchor_pivots(wave_result) if wave_result else []
        if anchor_pivots:
            # 去重合并：以 price+type+date 为 key
            seen = set()
            merged = []
            for a in list(anchor_pivots) + list(new_anchors):
                key = (round(a['price'], 2), a['type'], str(a.get('date', ''))[:10])
                if key not in seen:
                    seen.add(key)
                    merged.append(a)
            # 按 idx 排序保持时间顺序
            merged.sort(key=lambda a: a['idx'])
            anchor_pivots = merged
        elif new_anchors:
            anchor_pivots = new_anchors
        else:
            anchor_pivots = []

        return {
            'current_price': current_price,
            'high_price': high_price,
            'low_price': low_price,
            'fib_levels': fib_levels,
            'trend': trend,
            'ma20': ma20,
            'ma60': ma60,
            'scenarios': scenarios,
            'wave_result': wave_result,
            'anchor_pivots': anchor_pivots,
        }

    def generate_report(self, save_path: Path, state: Optional[Dict] = None) -> str:
        """
        生成完整的 markdown 分析报告（格式对齐指数日报）。

        Args:
            save_path: 报告保存路径
            state: 状态字典（可选，用于信号跟踪）

        Returns:
            报告文本
        """
        if self.daily_df is None or self.daily_df.empty:
            return ""

        # 加载状态（如未传入）
        if state is None:
            state = load_state()

        # 自上而下分析链：月线 → 周线 + 日线
        # 月线 zigzag 全覆盖全量数据，提取锚点同时传给周线和日线。
        # 周线的 zigzag 结果太嘈杂（511根K线产生大量微小转折），不适合做中转。
        monthly = self._analyze_timeframe(self.monthly_df, "monthly", "月线", None)
        monthly_anchors = monthly.get('anchor_pivots', [])
        weekly = self._analyze_timeframe(self.weekly_df, "weekly", "周线", monthly_anchors)
        daily = self._analyze_timeframe(self.daily_df, "daily", "日线", monthly_anchors)

        if not daily:
            return ""

        # 确定日期
        df_copy = self.daily_df.copy()
        df_copy['date'] = pd.to_datetime(df_copy['date'])
        data_date = df_copy['date'].max()
        data_date_str = data_date.strftime('%Y-%m-%d') if hasattr(data_date, 'strftime') else str(data_date)[:10]

        lines = []
        lines.append(f"# {self.name} ({self.symbol}) 波浪分析报告")
        lines.append("")
        lines.append(f"> 数据日期: {data_date_str} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")

        # 基本信息
        lines.append("## 📊 基本信息")
        lines.append("")
        lines.append("| 项目 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 当前价格 | {daily['current_price']:.2f} |")
        lines.append(f"| 历史最高 | {daily['high_price']:.2f} |")
        lines.append(f"| 历史最低 | {daily['low_price']:.2f} |")
        if daily['high_price'] > 0:
            lines.append(f"| 距离最高点 | {((daily['high_price'] - daily['current_price']) / daily['high_price'] * 100):.2f}% |")
        if daily['low_price'] > 0:
            lines.append(f"| 距离最低点 | {((daily['current_price'] - daily['low_price']) / daily['low_price'] * 100):.2f}% |")
        lines.append(f"| MA20 | {daily['ma20']:.2f} |")
        lines.append(f"| MA60 | {daily['ma60']:.2f} |")
        lines.append(f"| 趋势 | {daily['trend']} |")
        lines.append("")

        # 关键信号变化追踪（增强版）
        if self.use_enhanced:
            lines.append("## 🚨 关键信号变化追踪")
            lines.append("")
            lines.append("### 突破性变化")

            # 检测关键突破
            breakout_result = self._detect_key_breakouts(
                self.daily_df, daily['current_price'], daily['fib_levels']
            )

            if breakout_result.get('breakouts'):
                for breakout in breakout_result['breakouts'][:3]:  # 显示前3个
                    lines.append(f"- [x] 突破{breakout['level']:.0f}阻力位 (强度: {breakout['strength']:.1f}/10 - {breakout['class']})")
            else:
                lines.append("- 无向上突破")

            lines.append("")
            lines.append("### 跌破风险")
            if breakout_result.get('breakdowns'):
                for breakdown in breakout_result['breakdowns'][:3]:  # 显示前3个
                    lines.append(f"- [⚠️] 跌破{breakdown['level']:.0f}支撑位 (强度: {breakdown['strength']:.1f}/10 - {breakdown['class']})")
            else:
                lines.append("- 未跌破关键支撑")
            lines.append("")

            # 技术信号分析（动态评分）
            lines.append("### 技术信号分析")
            tech_signals = calculate_composite_score(
                self.daily_df, daily['current_price'],
                daily['fib_levels'].get('50%', daily['current_price'] * 1.1),
                daily['fib_levels'].get('50%', daily['current_price'] * 0.9)
            )
            lines.append(f"- **动量评分**: {tech_signals['momentum']:+.2f} (MACD/RSI/MA综合)")
            lines.append(f"- **成交量评分**: {tech_signals['volume']:+.2f} (量价配合度)")
            lines.append(f"- **突破评分**: {tech_signals['breakout']:+.2f} (突破强度)")
            lines.append(f"- **市场情绪**: {tech_signals['sentiment']:+.2f} (近期涨跌)")
            lines.append(f"- **综合技术分**: {tech_signals['total']:+.2f}")
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("")

        # 波浪标注 — 月线展示完整结构，周线/日线仅展示摘要
        lines.append("## 🌊 波浪标注")
        lines.append("")
        lines.append("> 月线 zigzag 覆盖全量数据，展示完整多年度波浪结构。")
        lines.append("> 周线/日线仅展示当前所处波位，详细浪点以月线为准。")
        lines.append("")

        for level_key, label, tf_analysis in [
            ("monthly", "月线（完整结构）", monthly),
            ("weekly", "周线（当前波位）", weekly),
            ("daily", "日线（当前波位）", daily),
        ]:
            wave_result = tf_analysis.get('wave_result') if tf_analysis else None
            wave_points = wave_result.get('wave_points', []) if wave_result else []
            position = wave_result.get('position', '') if wave_result else ''
            description = wave_result.get('description', '') if wave_result else ''

            lines.append(f"### {label}")
            lines.append("")
            if position:
                lines.append(f"> 波位: **{position}** — {description[:200]}")
                lines.append("")

            # 只有月线展示完整浪点表格。周线/日线 zigzag 产生大量微小
            # pivots（特别是注入月线锚点后），修正阶段不重启推动浪会导致
            # 所有小 pivots 被标为调整C浪X，表格冗长且无意义。
            # 周线/日线仅展示波位摘要，完整结构以月线为准。
            if level_key == 'monthly' and len(wave_points) >= 1:
                lines.append("| 波浪 | 类型 | 价格 | 日期 | 涨跌幅 |")
                lines.append("|------|------|------|------|--------|")
                prev_price = None
                for wp in wave_points:
                    wtype = "🔺高点" if wp['type'] == 'HIGH' else "🔻低点"
                    price = wp['price']
                    date_str = str(wp.get('date', ''))[:10]
                    wlabel = wp.get('label', '')

                    if prev_price is not None and prev_price != 0:
                        chg = (price - prev_price) / prev_price * 100
                        chg_str = f"+{chg:.1f}%" if wp['type'] == 'HIGH' else f"{chg:.1f}%"
                    else:
                        chg_str = "-"

                    lines.append(f"| {wlabel} | {wtype} | {price:.2f} | {date_str} | {chg_str} |")
                    prev_price = price
                lines.append("")
            elif level_key != 'monthly':
                lines.append("> 详见月线波浪结构")
                lines.append("")

        # 斐波那契回调位
        lines.append("## 📐 斐波那契回调位")
        lines.append("")
        lines.append("| 水平 | 价格 |")
        lines.append("|------|------|")
        for level, price in daily['fib_levels'].items():
            current_status = " ✅当前" if abs(price - daily['current_price']) < daily['current_price'] * 0.05 else ""
            lines.append(f"| {level} | {price:.2f}{current_status} |")
        lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")

        # 各时间级别详细分析
        tf_config = [
            ("daily", "🕐 日线级别分析", daily, self.daily_df),
            ("weekly", "📅 周线级别分析", weekly, self.weekly_df),
            ("monthly", "📆 月线级别分析", monthly, self.monthly_df),
        ]

        tf_signal_summary = {}

        for level_key, section_title, tf_analysis, tf_df in tf_config:
            if not tf_analysis or not tf_analysis.get('scenarios'):
                continue

            lines.append(f"## {section_title}")
            lines.append("")
            lines.append("---")
            lines.append("")

            tf_close = tf_analysis['current_price']

            # 获取该级别的成交量和前值
            if tf_df is not None and len(tf_df) >= 2:
                tf_volume = float(tf_df.iloc[-1].get('volume', 0)) if pd.notna(tf_df.iloc[-1].get('volume', 0)) else 0
                tf_prev_volume = float(tf_df.iloc[-2].get('volume', 0)) if pd.notna(tf_df.iloc[-2].get('volume', 0)) else 0
                tf_prev_close = float(tf_df.iloc[-2].get('close', tf_close))
            else:
                tf_volume = 0
                tf_prev_volume = 0
                tf_prev_close = tf_close

            level_confirm_score = 0.0
            level_deny_score = 0.0
            level_confirmed = []
            level_denied = []
            level_directional = 0.0  # 正值偏多，负值偏空

            for scenario in tf_analysis['scenarios']:
                # 自动调整场景
                adjusted = auto_adjust_scenario(scenario, tf_close)
                if adjusted.get("_auto_adjusted"):
                    lines.append(f"> 🔄 场景自动调整: {scenario['name']}")
                    if "_auto_adjusted_resistance" in adjusted:
                        adj = adjusted["_auto_adjusted_resistance"]
                        lines.append(f">   阻力位 {adj['from']:,.0f} → {adj['to']:,.0f} ({adj['reason']})")
                    if "_auto_adjusted_support" in adjusted:
                        adj = adjusted["_auto_adjusted_support"]
                        lines.append(f">   支撑位 {adj['from']:,.0f} → {adj['to']:,.0f} ({adj['reason']})")
                    lines.append("")

                # 加权信号检测
                confirmed, denied, confirm_score, deny_score = check_signals_weighted(
                    adjusted, tf_close, tf_volume, tf_prev_volume, tf_prev_close
                )
                level_confirm_score += confirm_score
                level_deny_score += deny_score
                level_confirmed.extend(confirmed)
                level_denied.extend(denied)

                # 方向感知评分：看空场景被否认(net<0)=实际偏多
                is_bullish = adjusted.get('_bullish', None)
                prob = adjusted.get('probability', 50) / 100.0
                net_score = confirm_score - deny_score
                if is_bullish is True:
                    level_directional += net_score * prob
                elif is_bullish is False:
                    level_directional -= net_score * prob  # 看空否认→偏多贡献

                # 状态更新
                new_confirmed = stock_update_state(
                    state, data_date_str, level_key, self.symbol, adjusted["name"], confirmed, denied
                )

                prob = adjusted["probability"]

                if denied and not confirmed:
                    status = "可能性降低"
                    status_icon = "🔴"
                elif confirmed and not denied:
                    if net_score >= 2.0:
                        status = "可能性大幅增强"
                        status_icon = "🟢🟢"
                    else:
                        status = "可能性增强"
                        status_icon = "🟢"
                elif confirmed and denied:
                    if net_score > 0:
                        status = "信号偏多,需观察"
                        status_icon = "🟡↗"
                    elif net_score < 0:
                        status = "信号偏空,需观察"
                        status_icon = "🟡↘"
                    else:
                        status = "信号矛盾,需观察"
                        status_icon = "🟡"
                else:
                    status = "信号未触发"
                    status_icon = "⚪"

                lines.append(f"**{adjusted['name']}** [{prob}%] {status_icon}{status}")
                lines.append("")
                lines.append(f"> 波浪位置: {adjusted['wave_position']}")
                lines.append(f"> 关键支撑: **{adjusted['key_support']:,.0f}** | 关键阻力: **{adjusted['key_resistance']:,.0f}** | 目标: **{adjusted['target']}**")
                if confirmed or denied:
                    lines.append(f"> 信号评分: 确认 {confirm_score:.1f} | 否认 {deny_score:.1f} | 净分 {net_score:+.1f}")
                lines.append("")

                if confirmed:
                    conf_text = "、".join(confirmed)
                    new_tag = ""
                    if new_confirmed:
                        new_tag = f" 🆕新增: {'、'.join(new_confirmed)}"
                    lines.append(f"- ✅ **已确认**: {conf_text}{new_tag}")
                else:
                    lines.append(f"- ✅ **已确认**: 无")

                if denied:
                    deny_text = "、".join(denied)
                    lines.append(f"- ❌ **已否认**: {deny_text}")
                else:
                    lines.append(f"- ❌ **已否认**: 无")

                lines.append("")

            tf_signal_summary[level_key] = {
                "confirmed": level_confirmed,
                "denied": level_denied,
                "confirm_score": level_confirm_score,
                "deny_score": level_deny_score,
                "directional_score": round(level_directional, 2),
            }

        # 多级别共振分析
        if tf_signal_summary:
            # 使用增强型共振分析
            if self.use_enhanced:
                correlation = analyze_resonance(tf_signal_summary)
                resonance_strength = calculate_resonance_strength(correlation)

                lines.append("## 🎯 多级别共振分析")
                lines.append("")
                lines.append(f"**{correlation['resonance_icon']} {correlation['resonance']}** | 方向: **{correlation['direction']}**")
                lines.append(f"> {correlation['details']}")
                lines.append(f"**共振强度得分**: {resonance_strength:.1f}/10")

                # 显示预警
                if correlation.get('warnings'):
                    lines.append("")
                    lines.append("### 风险预警")
                    for warning in correlation['warnings']:
                        lines.append(f"> {warning}")
            else:
                # 兼容旧版本
                correlation = analyze_multi_timeframe_correlation(self.name, tf_signal_summary)
                lines.append("## 🎯 多级别共振分析")
                lines.append("")
                lines.append(f"**{correlation['resonance_icon']} {correlation['resonance']}** | 方向: **{correlation['direction']}**")
                lines.append(f"> {correlation['details']}")

                # 矛盾检测：加权均分 vs 共振方向
                if tf_signal_summary:
                    monthly_dir = tf_signal_summary.get('monthly', {}).get('directional_score', 0)
                    weekly_dir = tf_signal_summary.get('weekly', {}).get('directional_score', 0)
                    daily_dir = tf_signal_summary.get('daily', {}).get('directional_score', 0)
                    directional_avg = monthly_dir * 0.5 + weekly_dir * 0.3 + daily_dir * 0.2
                    if directional_avg > 1.5 and correlation.get('direction') in ('偏空', '看空'):
                        lines.append("> ⚠️ 波浪评分偏多但共振偏空，表明月线看多但短周期偏弱，需警惕短期回调风险")
                    elif directional_avg < -1.5 and correlation.get('direction') in ('偏多', '看多'):
                        lines.append("> ⚠️ 波浪评分偏空但共振偏多，短周期企稳但大趋势仍弱，趋势反转尚待确认")

            lines.append("")

        # 操作建议（结合波浪位置和价格位置）
        lines.append("## 💡 操作建议")
        lines.append("")

        # 增强版操作策略
        if self.use_enhanced:
            tech_signals = calculate_composite_score(
                self.daily_df, daily['current_price'],
                daily['fib_levels'].get('50%', daily['current_price'] * 1.1),
                daily['fib_levels'].get('50%', daily['current_price'] * 0.9)
            )

            lines.append("### 基于最新信号的策略更新")
            lines.append("")

            # 根据技术评分给出建议
            total_score = tech_signals['total']
            direction = correlation.get('direction', '中性') if self.use_enhanced else '中性'

            if total_score > 0.3 and direction in ('看多', '偏多'):
                lines.append("**短期操作**: 技术指标偏强，可考虑跟随突破信号")
                lines.append(f"- **止损位**: MA20下方（当前MA20: {daily['ma20']:.2f}）")
                lines.append(f"- **目标位**: 关注上方阻力位 {daily['fib_levels'].get('0%', daily['current_price'] * 1.1):.0f}")
                lines.append("- **仓位**: 建议逐步加仓，控制风险")
            elif total_score < -0.3 and direction in ('看空', '偏空'):
                lines.append("**短期操作**: 技术指标偏弱，建议减仓或观望")
                lines.append(f"- **止损位**: 如有持仓建议严格止损")
                lines.append(f"- **支撑位**: 关注下方支撑位 {daily['fib_levels'].get('61.8%', daily['current_price'] * 0.9):.0f}")
                lines.append("- **仓位**: 建议轻仓或空仓，防范风险")
            else:
                lines.append("**短期操作**: 趋势不明，建议谨慎操作")
                lines.append("- **操作**: 轻仓试探或观望等待")
                lines.append("- **止损**: 严格设置止损，控制回撤")
                lines.append("- **等待**: 等待多级别共振确认后再加仓")

            lines.append("")
            lines.append("### 风险预警更新")
            lines.append("")

            # 根据斐波那契位设置预警
            fib = daily['fib_levels']
            if '23.6%' in fib:
                lines.append(f"- ⚠️ 若跌破 {fib['23.6%']:.0f} 点，需重新评估上升趋势")
            if '50%' in fib:
                lines.append(f"- ✅ 突破 {fib['50%']:.0f} 点可视为趋势确认信号")

            # 成交量预警
            volume_ratio = tech_signals['volume']
            if volume_ratio > 0.5:
                lines.append("- 📈 成交量配合良好，突破有效性较高")
            elif volume_ratio < -0.5:
                lines.append("- 📉 成交量萎缩，需警惕假突破")
            else:
                lines.append("- ⚪ 成交量中性，需观察后续变化")

            lines.append("")
        else:
            # 旧版本操作建议
            pass

        # 获取月线波位关键词
        monthly_wave_result = monthly.get('wave_result') if monthly else {}
        wave_position = monthly_wave_result.get('position', '') if monthly_wave_result else ''

        if direction in ('看多', '偏多'):
            if '第3浪' in wave_position:
                lines.append("- **主升浪进行中**: 可持有或沿均线支撑加仓")
                lines.append(f"- **止损位**: MA20下方（当前MA20: {daily['ma20']:.2f}）")
                lines.append("- **目标位**: 关注上方斐波那契扩展位")
            elif '第5浪' in wave_position:
                lines.append("- **上升浪末端**: 建议逐步止盈，不宜追高")
                lines.append("- **关注反转信号**: 成交量萎缩或MACD顶背离")
            elif any(kw in wave_position for kw in ('调整浪', '第2浪', '第4浪')):
                lines.append("- **回调中**: 关注斐波那契支撑位企稳信号")
                fib = daily.get('fib_levels', {})
                fib_618 = fib.get('61.8%', 0)
                if fib_618:
                    lines.append(f"- **关键支撑**: {fib_618:.2f}（61.8%回调位）")
                lines.append("- **操作**: 企稳后可轻仓试探")
            else:
                lines.append("- **偏多操作**: 可轻仓试探性做多")
                lines.append("- **止损位**: 建议设置在近期低点下方")
                lines.append("- **等待确认**: 等待更多信号确认再加仓")
        elif direction in ('看空', '偏空'):
            if '第3浪' in wave_position:
                lines.append("- **主跌浪进行中**: 强烈建议空仓观望")
                lines.append("- **切勿抄底**: 下跌推动浪第3浪通常跌幅最大")
            elif '第5浪' in wave_position:
                lines.append("- **下跌末期**: 可能接近底部，但需等待反转信号")
                lines.append("- **关注**: 放量企稳、MACD底背离等反转信号")
            else:
                lines.append("- **偏空防守**: 建议减仓或观望")
                lines.append("- **止损位**: 如有持仓建议严格止损")
                lines.append("- **等待企稳**: 等待明确反转信号再入场")
        else:
            lines.append("- **谨慎操作**: 趋势不明，建议谨慎操作")
            lines.append("- **等待确认**: 等待多级别趋势共振再入场")
            lines.append("- **控制仓位**: 严格控制仓位，防范风险")

        lines.append("")

        # 综合分析结论
        lines.append("## 📋 分析结论")
        lines.append("")

        # elliott_score（与 get_elliott_for_selection 一致）
        if tf_signal_summary:
            m_dir = tf_signal_summary.get('monthly', {}).get('directional_score', 0)
            w_dir = tf_signal_summary.get('weekly', {}).get('directional_score', 0)
            d_dir = tf_signal_summary.get('daily', {}).get('directional_score', 0)
            directional_avg = m_dir * 0.5 + w_dir * 0.3 + d_dir * 0.2
            elliott_score = round(10.0 * (2.0 / (1.0 + math.exp(-directional_avg / 2.5)) - 1.0), 1)

            # 评分标签
            if elliott_score >= 7.5:
                score_label = "强烈看多"
            elif elliott_score >= 5:
                score_label = "看多"
            elif elliott_score >= 2.5:
                score_label = "偏多"
            elif elliott_score >= -1.5:
                score_label = "中性"
            elif elliott_score >= -4:
                score_label = "偏空"
            else:
                score_label = "看空"

            # 关键支撑/阻力（日线斐波那契）
            fib = daily.get('fib_levels', {})
            supports = [(k, v) for k, v in fib.items() if v <= tf_close]
            resistances = [(k, v) for k, v in fib.items() if v >= tf_close]
            nearest_support = sorted(supports, key=lambda x: tf_close - x[1])[0] if supports else (None, 0)
            nearest_resistance = sorted(resistances, key=lambda x: x[1] - tf_close)[0] if resistances else (None, 0)

            lines.append(f"- **波浪评分**: {elliott_score:+.1f}/10（{score_label}）")
            lines.append(f"- **当前波位**: {wave_position or 'N/A'}")
            lines.append(f"- **共振方向**: {direction}（{resonance}）")
            if nearest_support[0]:
                lines.append(f"- **关键支撑**: {nearest_support[1]:.2f}（{nearest_support[0]}回调位）")
            if nearest_resistance[0]:
                lines.append(f"- **关键阻力**: {nearest_resistance[1]:.2f}（{nearest_resistance[0]}回调位）")

            # 综合判断
            if elliott_score >= 5 and direction in ('看多', '偏多'):
                lines.append("- **综合判断**: 多级别共振看多，波浪评分偏强，可关注做多机会")
            elif elliott_score <= -4 and direction in ('看空', '偏空'):
                lines.append("- **综合判断**: 多级别共振看空，波浪评分偏弱，建议回避或减仓")
            elif elliott_score >= 2.5 and direction in ('看多', '偏多'):
                lines.append("- **综合判断**: 短期偏多，但信号强度一般，建议轻仓操作")
            elif elliott_score <= -2.5 and direction in ('看空', '偏空'):
                lines.append("- **综合判断**: 短期偏空，建议观望等待")
            else:
                lines.append("- **综合判断**: 信号矛盾或中性，建议谨慎操作，等待方向明确")

            # 风险提示
            if elliott_score > 2.5 and direction in ('偏空', '看空'):
                lines.append("- ⚠️ **风险提示**: 波浪评分偏多但共振偏空，短周期偏弱需警惕回调")
            elif elliott_score < -2.5 and direction in ('偏多', '看多'):
                lines.append("- ⚠️ **风险提示**: 波浪评分偏空但共振偏多，短周期企稳但大趋势仍弱")

            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("*免责声明: 本报告仅为技术分析参考,不构成投资建议。市场有风险,投资需谨慎。*")
        lines.append("")

        report_text = "\n".join(lines)

        # 保存报告
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(report_text)

        print(f"  报告已保存: {save_path}")

        # 保存状态
        try:
            save_state(state)
        except Exception:
            pass

        return report_text


# ============================================================
# 每日选股集成：兼容 EnhancedElliottAnalyzer 格式的接口
# ============================================================

def get_elliott_for_selection(symbol: str, name: str, market: str,
                               years: int = 10, use_enhanced: bool = True) -> Dict[str, Any]:
    """
    供每日选股调用的波浪分析接口，输出兼容 EnhancedElliottAnalyzer.analyze_stock() 格式。

    Args:
        symbol: akshare 格式代码 (如 'sh600519' / '01810.HK')
        name: 股票名称
        market: 市场 SH/SZ/HK
        years: 分析年数
        use_enhanced: 是否使用增强版分析（默认True）

    Returns:
        dict 包含 elliott_score, wave_position, description, scenarios,
        resonance, trend, fib_levels 等字段
        """
    try:
        analyzer = StockWaveAnalyzer(symbol, name, market, use_enhanced=use_enhanced)
        if not analyzer.fetch_data(years=years):
            return _elliott_error_result(symbol, name, 'no_data')

        # 自上而下分析链（与 generate_report 一致）
        monthly = analyzer._analyze_timeframe(analyzer.monthly_df, "monthly", "月线", None)
        monthly_anchors = monthly.get('anchor_pivots', [])
        weekly = analyzer._analyze_timeframe(analyzer.weekly_df, "weekly", "周线", monthly_anchors)
        daily = analyzer._analyze_timeframe(analyzer.daily_df, "daily", "日线", monthly_anchors)

        if not daily:
            return _elliott_error_result(symbol, name, 'insufficient_data')

        # 信号检测（月线场景）+ 方向感知评分
        df_copy = analyzer.daily_df.copy()
        df_copy['date'] = pd.to_datetime(df_copy['date'])
        tf_close = daily['current_price']

        # 计算各级别成交量数据（月线/周线使用各自级别，避免日线短期波动误触信号）
        def _get_tf_volume_data(df):
            """从指定级别DataFrame获取最新成交量和前值"""
            if df is None or len(df) < 2:
                return 0, 0, 0
            has_vol = 'volume' in df.columns and pd.notna(df['volume'].iloc[-1])
            if not has_vol:
                return 0, 0, 0
            vol = float(df['volume'].iloc[-1]) if pd.notna(df['volume'].iloc[-1]) else 0
            prev_vol = float(df['volume'].iloc[-2]) if pd.notna(df['volume'].iloc[-2]) else 0
            prev_close = float(df['close'].iloc[-2]) if pd.notna(df['close'].iloc[-2]) else float(df['close'].iloc[-1])
            return vol, prev_vol, prev_close

        m_vol, m_prev_vol, m_prev_close = _get_tf_volume_data(analyzer.monthly_df)
        w_vol, w_prev_vol, w_prev_close = _get_tf_volume_data(analyzer.weekly_df)
        d_vol, d_prev_vol, d_prev_close = _get_tf_volume_data(analyzer.daily_df)

        tf_signal_summary = {}
        monthly_directional = 0.0

        if monthly.get('scenarios'):
            for scenario in monthly['scenarios']:
                adjusted = auto_adjust_scenario(scenario, tf_close)
                confirmed, denied, confirm_score, deny_score = check_signals_weighted(
                    adjusted, tf_close, m_vol, m_prev_vol, m_prev_close
                )
                is_bullish = adjusted.get('_bullish', None)
                prob = adjusted.get('probability', 50) / 100.0
                net_score = confirm_score - deny_score
                if is_bullish is True:
                    monthly_directional += net_score * prob
                elif is_bullish is False:
                    monthly_directional -= net_score * prob

            tf_signal_summary['monthly'] = {'directional_score': round(monthly_directional, 2)}

        # 周线信号
        weekly_directional = 0.0
        if weekly.get('scenarios'):
            for scenario in weekly['scenarios']:
                adjusted = auto_adjust_scenario(scenario, tf_close)
                confirmed, denied, confirm_score, deny_score = check_signals_weighted(
                    adjusted, tf_close, w_vol, w_prev_vol, w_prev_close
                )
                is_bullish = adjusted.get('_bullish', None)
                prob = adjusted.get('probability', 50) / 100.0
                net_score = confirm_score - deny_score
                if is_bullish is True:
                    weekly_directional += net_score * prob
                elif is_bullish is False:
                    weekly_directional -= net_score * prob

            tf_signal_summary['weekly'] = {'directional_score': round(weekly_directional, 2)}

        # 日线信号
        daily_directional = 0.0
        if daily.get('scenarios'):
            for scenario in daily['scenarios']:
                adjusted = auto_adjust_scenario(scenario, tf_close)
                confirmed, denied, confirm_score, deny_score = check_signals_weighted(
                    adjusted, tf_close, d_vol, d_prev_vol, d_prev_close
                )
                is_bullish = adjusted.get('_bullish', None)
                prob = adjusted.get('probability', 50) / 100.0
                net_score = confirm_score - deny_score
                if is_bullish is True:
                    daily_directional += net_score * prob
                elif is_bullish is False:
                    daily_directional -= net_score * prob

            tf_signal_summary['daily'] = {'directional_score': round(daily_directional, 2)}

        # 多级别共振
        if use_enhanced:
            correlation = analyze_resonance(tf_signal_summary) if tf_signal_summary else {
                'resonance': '无信号', 'direction': '中性', 'resonance_icon': '⚪', 'details': '',
                'levels': {}, 'resonance_score': 0.0, 'warnings': []
            }
        else:
            correlation = analyze_multi_timeframe_correlation(name, tf_signal_summary) if tf_signal_summary else {
                'resonance': '无信号', 'direction': '中性', 'resonance_icon': '⚪', 'details': '', 'levels': {}
            }

        direction = correlation.get('direction', '中性')

        # elliott_score：加权平均三个级别的 directional_score
        # 月线 50%，周线 30%，日线 20%，sigmoid 映射到 (-10, 10)
        directional_avg = (monthly_directional * 0.5 +
                           weekly_directional * 0.3 +
                           daily_directional * 0.2)
        elliott_score = round(10.0 * (2.0 / (1.0 + math.exp(-directional_avg / 2.5)) - 1.0), 1)

        # wave_position：从月线波位
        wave_result = monthly.get('wave_result') or {}
        wave_position = wave_result.get('position', '') or wave_result.get('description', '')[:80]

        # ============================================================
        # 偏左侧评分调整：趋势启动和调整结束时高分
        # ============================================================
        # 1浪（趋势启动）：+8分（最佳进场时机）
        if '1浪' in wave_position and '下跌' not in wave_position and '第5浪' not in wave_position:
            elliott_score += 8
        # 2浪回调：+6分（次佳进场时机）
        elif '2浪' in wave_position:
            elliott_score += 6
        # C浪末端/Z浪末端：+7分（调整结束）
        elif 'C浪末端' in wave_position or 'Z浪末端' in wave_position:
            elliott_score += 7
        # 大级别底部：+8分
        elif '大级别底部' in wave_position or '底部构筑' in wave_position:
            elliott_score += 8
        # 3浪：-2分（趋势已确立，不是左侧）
        elif '3浪' in wave_position and '下跌' not in wave_position:
            elliott_score -= 2
        # 5浪/末端：-6分（趋势结束，离场时机）
        elif '第5浪' in wave_position or '末端' in wave_position:
            elliott_score -= 6
        # A浪/调整开始：-5分（离场时机）
        elif 'A浪' in wave_position:
            elliott_score -= 5

        # ============================================================
        # 原有的波浪位置评分兜底逻辑（保留）
        # ============================================================
        if wave_position:
            if '下跌推动浪第3浪延伸' in wave_position:
                elliott_score = min(elliott_score, -3.0)
            elif '下跌推动浪第3浪' in wave_position:
                elliott_score = min(elliott_score, -2.0)
            elif '下跌推动浪第1浪' in wave_position:
                elliott_score = min(elliott_score, 0.0)
            elif '下跌推动浪第5浪' in wave_position and '反弹' not in wave_position and '反转' not in wave_position:
                elliott_score = min(elliott_score, 0.0)

        # position_ratio 高位风险约束（P1 #4）
        # 价格在历史高低点间的位置，0=最低，1=最高
        high_price = daily.get('high_price', tf_close)
        low_price = daily.get('low_price', tf_close)
        pos_range = high_price - low_price
        position_ratio = ((tf_close - low_price) / pos_range) if pos_range > 0 else 0.5

        if position_ratio > 0.95:
            elliott_score = min(elliott_score, 2.0)   # 接近历史极高点，评分上限+2
        elif position_ratio > 0.90:
            elliott_score = min(elliott_score, 4.0)   # 高位区，评分上限+4
        elif position_ratio > 0.85:
            elliott_score = min(elliott_score, 6.0)   # 偏高位，评分上限+6

        # 第5浪末期 + 高位 = 双重风险
        wave_pos_for_constraint = monthly.get('wave_result', {}).get('position', '') if monthly.get('wave_result') else ''
        if position_ratio > 0.85 and ('第5浪' in wave_pos_for_constraint or '末端' in wave_pos_for_constraint):
            elliott_score = min(elliott_score, 1.0)   # 第5浪末期+高位，评分上限+1

        if not wave_position:
            wave_position = daily.get('trend', 'N/A')

        # 构建 wave_detail
        wave_points = wave_result.get('wave_points', [])
        structure_parts = []
        for wp in wave_points:
            lbl = wp.get('label', '')
            pr = wp.get('price', 0)
            structure_parts.append(f"{lbl}({pr:.1f})")
        wave_structure = ' → '.join(structure_parts) if structure_parts else ''
        position_reasoning = wave_result.get('description', '')

        # position_ratio（已在上面约束中计算）

        # 月线场景信号验证
        monthly_scenarios = monthly.get('scenarios', [])
        validation_signals = {}
        for s in monthly_scenarios:
            adjusted = auto_adjust_scenario(s, tf_close)
            confirmed, denied, _, _ = check_signals_weighted(
                adjusted, tf_close, m_vol, m_prev_vol, m_prev_close
            )
            if confirmed or denied:
                validation_signals[s['name']] = {'confirmed': confirmed, 'denied': denied}

        # score_rationale
        score_rationale = (
            f"月线{monthly_directional:+.1f}(50%) + "
            f"周线{weekly_directional:+.1f}(30%) + "
            f"日线{daily_directional:+.1f}(20%) → "
            f"elliott_score={elliott_score:+.1f}"
        )

        # 月线收盘价序列（用于波浪可视化：完整价格曲线 + 波浪转折点叠加）
        monthly_series = []
        try:
            if analyzer.monthly_df is not None and len(analyzer.monthly_df) > 0:
                mdf = analyzer.monthly_df.copy()
                mdf['date'] = pd.to_datetime(mdf['date'])
                monthly_series = [
                    {'date': str(d)[:10], 'close': float(c) if pd.notna(c) else None}
                    for d, c in zip(mdf['date'], mdf['close'])
                ]
        except Exception:
            monthly_series = []

        return {
            'stock_code': symbol,
            'stock_name': name,
            'elliott_score': elliott_score,
            'wave_position': wave_position,
            'description': wave_result.get('description', ''),
            'scenarios': monthly_scenarios,
            'resonance': {
                'resonance': correlation.get('resonance', ''),
                'icon': correlation.get('resonance_icon', ''),
                'direction': correlation.get('direction', ''),
                'details': correlation.get('details', ''),
                'score': {'看多': 3, '偏多': 2, '中性': 0, '偏空': -2, '看空': -3}.get(
                    correlation.get('direction', '中性'), 0
                ),
                # 新增增强版字段
                'resonance_score': correlation.get('resonance_score', 0.0),
                'warnings': correlation.get('warnings', []),
            },
            'current_price': tf_close,
            'high_price': high_price,
            'low_price': low_price,
            'trend': daily.get('trend', 'N/A'),
            'fib_levels': daily.get('fib_levels', {}),
            'daily_analysis': {
                'trend': daily.get('trend', 'N/A'),
                'position_ratio': position_ratio,
                'ma20': daily.get('ma20', 0),
                'ma60': daily.get('ma60', 0),
            },
            'weekly_analysis': {
                'trend': weekly.get('trend', 'N/A') if weekly else 'N/A',
                'position_ratio': (
                    (tf_close - weekly['low_price']) / (weekly['high_price'] - weekly['low_price'])
                    if weekly and weekly.get('high_price', 0) > weekly.get('low_price', 0) else 0.5
                ),
            } if weekly else None,
            'monthly_analysis': {
                'trend': monthly.get('trend', 'N/A') if monthly else 'N/A',
                'position_ratio': (
                    (tf_close - monthly['low_price']) / (monthly['high_price'] - monthly['low_price'])
                    if monthly and monthly.get('high_price', 0) > monthly.get('low_price', 0) else 0.5
                ),
            } if monthly else None,
            'wave_detail': {
                'wave_structure': wave_structure,
                'position_reasoning': position_reasoning,
            },
            'wave_points': wave_points,
            'monthly_series': monthly_series,
            'validation': validation_signals if validation_signals else None,
            'score_rationale': score_rationale,
            # 增强版额外字段
            'tech_signals': calculate_composite_score(analyzer.daily_df, tf_close,
                daily['fib_levels'].get('50%', tf_close * 1.1),
                daily['fib_levels'].get('50%', tf_close * 0.9)
            ) if analyzer.use_enhanced else None,
            'breakout_status': analyzer._detect_key_breakouts(analyzer.daily_df, tf_close, daily['fib_levels']) if analyzer.use_enhanced else None,
            'enhanced_version': analyzer.use_enhanced,
        }
    except Exception as e:
        return _elliott_error_result(symbol, name, str(e)[:80])


def _elliott_error_result(symbol: str, name: str, error: str) -> Dict[str, Any]:
    return {
        'stock_code': symbol,
        'stock_name': name,
        'elliott_score': 0,
        'wave_position': '数据不足' if error == 'insufficient_data' else '分析失败',
        'description': error,
        'error': error,
        'scenarios': [],
        'resonance': {'resonance': '无信号', 'icon': '⚪', 'direction': '中性', 'details': '', 'score': 0},
        'current_price': 0, 'high_price': 0, 'low_price': 0,
        'trend': 'N/A',
        'fib_levels': {},
        'daily_analysis': None, 'weekly_analysis': None, 'monthly_analysis': None,
        'wave_detail': {'wave_structure': '', 'position_reasoning': ''},
        'validation': None,
        'score_rationale': error,
    }


# ============================================================
# 批量报告刷新（供 run_daily_selection 复用）
# ============================================================

def regenerate_all_stock_reports(stock_pool_file: str = None,
                                  output_dir: str = None) -> Dict[str, int]:
    """
    批量重新生成所有个股波浪分析报告。

    Args:
        stock_pool_file: 自选股票池文件路径，默认 ~/fin-agent-output/自选股票池.md
        output_dir: 报告输出目录，默认 ~/fin-agent-output/波浪预测/每日更新/个股分析

    Returns:
        {'success': N, 'skip': N, 'fail': N}
    """
    import re
    import time as time_mod
    from pathlib import Path

    if stock_pool_file is None:
        stock_pool_file = str(settings.BASE_DIR / "自选股票池.md")
    if output_dir is None:
        output_dir = str(settings.BASE_DIR / "波浪预测" / "每日更新" / "个股分析")

    pool_path = Path(stock_pool_file)
    if not pool_path.exists():
        print(f"错误: 股票池文件不存在: {stock_pool_file}")
        return {'success': 0, 'skip': 0, 'fail': 0}

    with open(pool_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 解析股票池（与 batch_elliott_analysis.py 一致）
    line_pattern = re.compile(r'([\w]+)\.(SH|SZ|HK)\s*\(([^)]+)\)')
    table_pattern = re.compile(r'\|\s*([^\s|]+)\s*\|\s*(\d{4,6})\s*\|')

    stocks = {}
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        for code, market, name in line_pattern.findall(line):
            key = f"{code}.{market}"
            if key not in stocks:
                stocks[key] = {'code': code.strip(), 'name': name.strip(), 'market': market.strip()}
        for name, code in table_pattern.findall(line):
            name, code = name.strip(), code.strip()
            if name and code and name not in ('名称', '代码', ':'):
                market = ('SH' if code.startswith(('5', '6', '9')) else
                          'SZ' if len(code) == 6 else 'HK')
                key = f"{code}.{market}"
                if key not in stocks:
                    stocks[key] = {'code': code, 'name': name, 'market': market}

    stock_list = list(stocks.values())

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    state = load_state()
    success = skip = fail = 0

    for stock in stock_list:
        code = stock['code']
        name = stock['name']
        market = stock['market']

        # 格式化 symbol
        if market == 'HK':
            hk_code = code.strip()
            if len(hk_code) == 4:
                hk_code = '0' + hk_code
            symbol = f"{hk_code}.HK"
        else:
            symbol = f"{market.lower()}{code}"

        # 报告文件名
        if market == 'HK':
            report_name = f"{name}_港股_波浪分析报告.md"
        else:
            report_name = f"{name}_波浪分析报告.md"
        report_path = out_dir / report_name

        try:
            analyzer = StockWaveAnalyzer(symbol, name, market)
            if not analyzer.fetch_data(years=10):
                fail += 1
                continue
            analyzer.generate_report(report_path, state)
            success += 1
        except Exception:
            fail += 1

        time_mod.sleep(0.3)

    try:
        save_state(state)
    except Exception:
        pass

    print(f"批量波浪报告刷新完成: 成功 {success}, 失败 {fail}")
    return {'success': success, 'skip': skip, 'fail': fail}
