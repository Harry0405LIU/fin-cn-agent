#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
艾略特波浪信号检测模块
提取信号检测逻辑和状态管理
v1.2 新增: 场景自动更新、多级别关联分析、信号权重系统
"""

import os
import re
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings

ELLIOTT_STATE_FILE = settings.DATA_DIR / "elliott_state.json"
from core.utils import load_json, save_json


# ============================================================
# 信号检测（含权重评分）
# ============================================================

def check_signals(scenario, close, volume, prev_volume, prev_close):
    """
    基于关键词的信号检测，返回 (confirmed_list, denied_list)
    """
    confirmed = []
    denied = []

    for sig in scenario["confirm_signals"]:
        triggered = _check_single_signal(sig, close, volume, prev_volume, prev_close, scenario)
        if triggered:
            confirmed.append(sig)

    for sig in scenario["deny_signals"]:
        triggered = _check_single_signal(sig, close, volume, prev_volume, prev_close, scenario)
        if triggered:
            denied.append(sig)

    return confirmed, denied


def check_signals_weighted(scenario, close, volume, prev_volume, prev_close):
    """
    带权重的信号检测，返回 (confirmed_list, denied_list, confirm_score, deny_score)
    权重基于信号强度: 数值距离越近权重越高，放量幅度越大权重越高
    """
    confirmed = []
    denied = []
    confirm_score = 0.0
    deny_score = 0.0

    for sig in scenario["confirm_signals"]:
        triggered, weight = _check_signal_with_weight(sig, close, volume, prev_volume, prev_close, scenario)
        if triggered:
            confirmed.append(sig)
            confirm_score += weight

    for sig in scenario["deny_signals"]:
        triggered, weight = _check_signal_with_weight(sig, close, volume, prev_volume, prev_close, scenario)
        if triggered:
            denied.append(sig)
            deny_score += weight

    return confirmed, denied, confirm_score, deny_score


def _check_signal_with_weight(signal, close, volume, prev_volume, prev_close, scenario):
    """
    信号检测+权重计算
    返回 (triggered: bool, weight: float)
    权重范围 0.5 ~ 3.0:
    - 基础权重 1.0
    - 突破/跌破: 距离越远权重越高 (1.0 ~ 2.0)
    - 放量/缩量: 幅度越大权重越高 (1.0 ~ 3.0)
    - 创新高/新低: 权重 1.5
    """
    num = _extract_number(signal)

    # 突破
    if "突破" in signal and num is not None:
        if close > num:
            # 超出比例越大权重越高
            pct_above = (close - num) / num * 100
            weight = min(1.0 + pct_above / 5.0, 2.0)
            return True, weight
        return False, 0.0

    # 跌破
    if "跌破" in signal and num is not None:
        if close < num:
            pct_below = (num - close) / num * 100
            weight = min(1.0 + pct_below / 5.0, 2.0)
            return True, weight
        return False, 0.0

    # 放量/放大 + 价格上涨
    if "放量" in signal or "放大" in signal:
        if prev_volume and prev_volume > 0 and volume > prev_volume and close > prev_close:
            ratio = volume / prev_volume
            weight = min(0.5 + ratio, 3.0)  # 放量2倍=2.5, 3倍=3.0
            return True, weight
        return False, 0.0

    # 缩量/萎缩 + 价格下跌
    if "缩量" in signal or "萎缩" in signal:
        if prev_volume and prev_volume > 0 and volume < prev_volume and close < prev_close:
            ratio = prev_volume / max(volume, 1)
            weight = min(0.5 + ratio * 0.5, 2.5)
            return True, weight
        return False, 0.0

    # 创新高
    if "创新高" in signal:
        resistance = scenario.get("key_resistance", float("inf"))
        if close >= resistance:
            return True, 1.5
        return False, 0.0

    # 创新低
    if "创新低" in signal or "更低低点" in signal:
        support = scenario.get("key_support", 0)
        if close <= support:
            return True, 1.5
        return False, 0.0

    # 双顶
    if "双顶" in signal:
        resistance = scenario.get("key_resistance", float("inf"))
        if close >= resistance * 0.98:
            return True, 1.0
        return False, 0.0

    # 头肩顶
    if "头肩顶" in signal:
        support = scenario.get("key_support", float("inf"))
        if close <= support:
            return True, 1.2
        return False, 0.0

    # 无法收复
    if "无法收复" in signal and num is not None:
        if close < num:
            pct_below = (num - close) / num * 100
            weight = min(1.0 + pct_below / 5.0, 2.0)
            return True, weight
        return False, 0.0

    # 无法匹配的信号: 默认不触发
    return False, 0.0


def _extract_number(text):
    """从文本中提取第一个数字"""
    match = re.search(r'[\d,]+\.?\d*', text.replace(",", ""))
    if match:
        return float(match.group().replace(",", ""))
    return None


def _check_single_signal(signal, close, volume, prev_volume, prev_close, scenario):
    """
    简单关键词信号检测（兼容旧接口）
    """
    triggered, _ = _check_signal_with_weight(signal, close, volume, prev_volume, prev_close, scenario)
    return triggered


# ============================================================
# 场景自动更新
# ============================================================

def auto_adjust_scenario(scenario, close, key_support_pct=0.03, key_resistance_pct=0.03):
    """
    基于最新收盘价自动调整场景的支撑/阻力位数值

    策略:
    - 如果价格已突破关键阻力位超过 resistance_pct，则将阻力位上调至最近的整数关口
    - 如果价格已跌破关键支撑位超过 support_pct，则将支撑位下调至最近的整数关口
    - 同时更新信号中的数值
    - 返回调整后的场景副本（不修改原场景）

    Args:
        scenario: 原始场景字典
        close: 最新收盘价
        key_support_pct: 支撑位调整阈值（默认3%）
        key_resistance_pct: 阻力位调整阈值（默认3%）
    """
    import copy
    adjusted = copy.deepcopy(scenario)

    support = scenario.get("key_support", 0)
    resistance = scenario.get("key_resistance", float("inf"))

    changed = False

    # 价格已突破阻力位超过阈值
    if resistance and close > resistance * (1 + key_resistance_pct):
        new_resistance = _round_to_significant(close * 1.05, close)
        adjusted["key_resistance"] = new_resistance
        adjusted["_auto_adjusted_resistance"] = {
            "from": resistance, "to": new_resistance,
            "reason": f"价格{close:.0f}已突破阻力位{resistance:.0f}超过{key_resistance_pct*100:.0f}%"
        }
        # 更新信号中的数值
        adjusted["confirm_signals"] = [
            _update_signal_price(s, resistance, new_resistance) for s in adjusted["confirm_signals"]
        ]
        adjusted["deny_signals"] = [
            _update_signal_price(s, resistance, new_resistance) for s in adjusted["deny_signals"]
        ]
        changed = True

    # 价格已跌破支撑位超过阈值
    if support and close < support * (1 - key_support_pct):
        new_support = _round_to_significant(close * 0.95, close)
        adjusted["key_support"] = new_support
        adjusted["_auto_adjusted_support"] = {
            "from": support, "to": new_support,
            "reason": f"价格{close:.0f}已跌破支撑位{support:.0f}超过{key_support_pct*100:.0f}%"
        }
        adjusted["confirm_signals"] = [
            _update_signal_price(s, support, new_support) for s in adjusted["confirm_signals"]
        ]
        adjusted["deny_signals"] = [
            _update_signal_price(s, support, new_support) for s in adjusted["deny_signals"]
        ]
        changed = True

    if changed:
        adjusted["_auto_adjusted"] = True

    return adjusted


def _round_to_significant(value, reference):
    """将数值圆整到有意义的关口（基于参考值的量级）"""
    if reference >= 10000:
        return round(value / 500) * 500  # 500的整数倍
    elif reference >= 1000:
        return round(value / 100) * 100  # 100的整数倍
    elif reference >= 100:
        return round(value / 10) * 10  # 10的整数倍
    else:
        return round(value, 1)


def _update_signal_price(signal, old_price, new_price):
    """更新信号文本中的价格数值"""
    num = _extract_number(signal)
    if num is not None and abs(num - old_price) / max(old_price, 1) < 0.05:
        # 如果信号中的数字接近旧价格，替换为新价格
        return signal.replace(str(int(num)), str(int(new_price)))
    return signal


def generate_breakout_scenario(close, index_name, level="yearly"):
    """
    当价格突破关键位时自动生成新场景建议

    Args:
        close: 最新收盘价
        index_name: 指数名称
        level: 时间级别

    Returns:
        新场景字典或None
    """
    # 简单策略: 突破后生成"突破确认"场景
    support = _round_to_significant(close * 0.97, close)
    resistance = _round_to_significant(close * 1.08, close)

    return {
        "name": f"突破{int(close)}后延续上行",
        "probability": 30,
        "key_support": support,
        "key_resistance": resistance,
        "wave_position": f"突破后主升浪延续中",
        "target": f"{resistance:.0f}-{_round_to_significant(close * 1.15, close):.0f}",
        "confirm_signals": [f"突破{resistance:.0f}", "放量上攻", f"回调不跌破{support:.0f}"],
        "deny_signals": [f"跌破{support:.0f}且无法收复", f"{resistance:.0f}附近双顶", "量价背离明显"],
        "_auto_generated": True,
    }


# ============================================================
# 多时间级别关联分析
# ============================================================

def analyze_multi_timeframe_correlation(index_name, timeframe_results):
    """
    分析多时间级别的信号一致性

    Args:
        index_name: 指数名称
        timeframe_results: dict, {level_key: {"confirmed": [...], "denied": [...], "scenarios": [...]}}
            每个级别包含信号检测结果

    Returns:
        dict: {
            "resonance": "强共振"/"弱共振"/"分歧"/"无信号",
            "resonance_icon": str,
            "direction": "看多"/"看空"/"中性",
            "details": str,
            "levels": {level: direction}
        }
    """
    levels = {}
    for level, result in timeframe_results.items():
        # 优先使用方向感知评分（考虑场景多空属性）
        # directional_score: 正值=偏多，负值=偏空
        # 看空场景被否认（net<0）意味着空头不成立→实际偏多
        directional = result.get("directional_score")
        if directional is not None:
            if directional > 0.3:
                levels[level] = "看多"
            elif directional < -0.3:
                levels[level] = "看空"
            else:
                levels[level] = "中性"
        else:
            confirmed = result.get("confirmed", [])
            denied = result.get("denied", [])
            confirm_score = result.get("confirm_score", len(confirmed))
            deny_score = result.get("deny_score", len(denied))

            if confirm_score > deny_score:
                levels[level] = "看多"
            elif deny_score > confirm_score:
                levels[level] = "看空"
            elif confirmed or denied:
                levels[level] = "中性"
            else:
                levels[level] = "无信号"

    directions = list(levels.values())

    # 判断共振
    bullish_count = directions.count("看多")
    bearish_count = directions.count("看空")

    if bullish_count >= 3:
        resonance = "强共振"
        direction = "看多"
        icon = "🟢🟢🟢"
    elif bullish_count >= 2 and bearish_count == 0:
        resonance = "弱共振"
        direction = "偏多"
        icon = "🟢🟢"
    elif bearish_count >= 3:
        resonance = "强共振"
        direction = "看空"
        icon = "🔴🔴🔴"
    elif bearish_count >= 2 and bullish_count == 0:
        resonance = "弱共振"
        direction = "偏空"
        icon = "🔴🔴"
    elif bullish_count > 0 and bearish_count > 0:
        resonance = "分歧"
        direction = "中性"
        icon = "🟡"
    else:
        resonance = "无信号"
        direction = "中性"
        icon = "⚪"

    level_labels = {"yearly": "年线", "monthly": "月线", "weekly": "周线"}
    details_parts = []
    for level, d in levels.items():
        label = level_labels.get(level, level)
        d_icon = "🟢" if d == "看多" else "🔴" if d == "看空" else "🟡" if d == "中性" else "⚪"
        details_parts.append(f"{label}{d_icon}{d}")
    details = " | ".join(details_parts)

    return {
        "resonance": resonance,
        "resonance_icon": icon,
        "direction": direction,
        "details": details,
        "levels": levels,
    }


# ============================================================
# 状态管理
# ============================================================

def load_state():
    """加载信号状态文件"""
    return load_json(ELLIOTT_STATE_FILE, default={})


def save_state(state):
    """保存信号状态文件"""
    save_json(ELLIOTT_STATE_FILE, state)


def update_state(state, data_date_str, level, index_name, scenario_name, confirmed, denied):
    """更新某个指数某个时间级别某个场景的信号状态"""
    key = f"{level}|{index_name}|{scenario_name}"
    if key not in state:
        state[key] = {}
    prev = state[key].get("confirmed", [])
    # 新确认信号 = 本次触发的 - 上次已记录的
    new_confirmed = [s for s in confirmed if s not in prev]
    state[key] = {
        "date": data_date_str,
        "confirmed": confirmed,
        "denied": denied,
        "new_confirmed": new_confirmed,
    }
    return new_confirmed


def migrate_state(state):
    """将旧格式的状态键迁移为新格式（添加年线级别前缀）"""
    migrated = {}
    for key, val in state.items():
        if '|' in key and not key.startswith(('yearly|', 'monthly|', 'weekly|')):
            new_key = f"yearly|{key}"
            migrated[new_key] = val
        else:
            migrated[key] = val
    return migrated
