#!/usr/bin/env python3
"""
技术分析Agent - 四种情况判断系统
基于25日均线、5日成交量、60日成交量进行技术分析
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class TechnicalAnalyzer:
    """技术分析器 - 四种情况判断"""

    # 预定义的四种情况规则说明
    SITUATION_RULES = {
        "情况1": {
            "description": "股价在25日均线下方 + 5日成交量小于60日成交量",
            "recommendation": "不推荐",
            "score": -5,
            "risk": "高",
            "reasoning": "股价处于弱势区域，且量能不足，缺乏上攻动力，建议规避。"
        },
        "情况2": {
            "description": "股价突破25日均线 + 5日成交量上穿60日成交量",
            "recommendation": "短线关注",
            "score": 4,
            "risk": "中高",
            "reasoning": "股价突破重要均线，且量价齐升，短线动能较强，可适度关注。"
        },
        "情况3": {
            "description": "股价在25日均线上方 + 5日成交量大于60日成交量且成交量放大",
            "recommendation": "波段关注",
            "score": 6,
            "risk": "中",
            "reasoning": "股价在强势区域，量能持续放大，波段机会明显，可积极参与。"
        },
        "情况4": {
            "description": "股价在25日均线上方 + 5日成交量小于60日成交量且成交量萎缩",
            "recommendation": "长线关注",
            "score": 8,
            "risk": "低",
            "reasoning": "股价强势且量能萎缩，说明筹码锁定良好，长线资金布局，适合长线关注。"
        }
    }

    # 技术分析规则配置
    RULES = {
        "ma25_period": 25,           # 25日均线
        "vol5_period": 5,            # 5日成交量
        "vol60_period": 60,          # 60日成交量
        "near_threshold": 0.02,      # 接近均线的阈值（2%）
        "touch_threshold": 0.005,    # 回踩均线的阈值（0.5%）
        "vol_increase_threshold": 1.2,  # 成交量放大阈值（1.2倍）
        "vol_decrease_threshold": 0.8,  # 成交量萎缩阈值（0.8倍）
    }

    def __init__(self):
        pass

    def analyze(
        self,
        stock_code: str,
        stock_name: Optional[str] = None,
        days: int = 120
    ) -> Dict[str, Any]:
        """执行技术分析 - 量价时空四维评分系统"""
        try:
            df = self._fetch_stock_data(stock_code, days)
            if df.empty:
                return {
                    "stock_code": stock_code,
                    "stock_name": stock_name or stock_code,
                    "error": "无法获取股票数据",
                    "timestamp": datetime.now().isoformat()
                }

            # 计算技术指标
            df = self._calculate_indicators(df)

            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None

            # 将动量数据注入details（在_analyze_situation中添加）
            if "momentum_5d" in df.columns:
                latest_momentum = float(latest.get('momentum_5d', 0))
            else:
                latest_momentum = 0

            # 判断四种情况 + 计算四维所需数据
            situation = self._analyze_situation(df, latest, prev)

            # 注入动量到details
            situation["details"]["momentum_5d"] = latest_momentum

            # 四维融合评分
            recommendation, score, risk_level, scoring_breakdown = self._get_recommendation_by_situation(situation)

            # 生成信号列表
            signals = self._generate_signals(situation, df, latest, prev)

            result = {
                "stock_code": stock_code,
                "stock_name": stock_name or self._get_stock_name(stock_code),
                "timestamp": datetime.now().isoformat(),
                "latest_price": float(latest['close']),
                "change_percent": self._calculate_change_percent(df),
                # 四种情况分析
                "situation": situation,
                # 综合
                "signals": signals,
                "score": score,
                "recommendation": recommendation,
                "risk_level": risk_level,
                "data_summary": {
                    "close": float(latest['close']),
                    "ma10": float(latest.get('MA10', 0)),
                    "ma25": float(latest.get('MA25', 0)),
                    "ma60": float(latest.get('MA60', 0)),
                    "vol5": float(latest.get('VOL5', 0)),
                    "vol60": float(latest.get('VOL60', 0)),
                    "volume": int(latest.get('volume', 0)),
                    "atr14": float(latest.get('ATR14', 0)),
                },
                # 四维得分明细
                "dimension_scores": {
                    "price": {
                        "position_vs_ma25": round(situation["details"].get("price_diff_pct", 0), 2),
                        "ma_alignment": self._describe_ma_alignment(latest),
                        "momentum_5d": round(latest_momentum, 2),
                        "price_position_score": round(scoring_breakdown.get("price_position", 0), 2),
                        "ma_alignment_score": round(scoring_breakdown.get("ma_alignment", 0), 2),
                        "momentum_score": round(scoring_breakdown.get("momentum_factor", 0), 2),
                    },
                    "volume": {
                        "vol_ratio": round(situation["details"].get("vol_ratio", 1.0), 2),
                        "vol_price_coordination": self._describe_vol_coordination(situation),
                        "vol_level_score": round(scoring_breakdown.get("vol_level", 0), 2),
                        "vol_coordination_score": round(scoring_breakdown.get("vol_price_coordination", 0), 2),
                    },
                    "time": {
                        "consecutive_above_ma25": situation["details"].get("consecutive_above_ma25", 0),
                        "is_consolidating": situation["details"].get("is_consolidating", False),
                        "amplitude_20d": situation["details"].get("amplitude_20d", 0),
                        "amplitude_5d": situation["details"].get("amplitude_5d", 0),
                        "trend_persistence_score": round(scoring_breakdown.get("trend_persistence", 0), 2),
                        "consolidation_score": round(scoring_breakdown.get("consolidation_factor", 0), 2),
                    },
                    "space": {
                        "upside_atr": situation["details"].get("upside_atr", 0),
                        "downside_atr": situation["details"].get("downside_atr", 0),
                        "resistance": situation["details"].get("resistance", 0),
                        "support": situation["details"].get("support", 0),
                        "space_upside_score": round(scoring_breakdown.get("space_upside", 0), 2),
                        "space_downside_score": round(scoring_breakdown.get("space_downside", 0), 2),
                        "space_downside_risk": round(scoring_breakdown.get("space_downside_risk", 0), 2),
                    },
                    "fusion": {
                        "price_weighted": round(scoring_breakdown.get("price_weighted", 0), 2),
                        "volume_weighted": round(scoring_breakdown.get("volume_weighted", 0), 2),
                        "time_weighted": round(scoring_breakdown.get("time_weighted", 0), 2),
                        "space_weighted": round(scoring_breakdown.get("space_weighted", 0), 2),
                    },
                    "adjustments": {
                        "resonance_bonus": round(scoring_breakdown.get("resonance_bonus", 0), 2),
                        "divergence_penalty": round(scoring_breakdown.get("divergence_penalty", 0), 2),
                        "pullback_adjustment": round(scoring_breakdown.get("pullback_adjustment", 0), 2),
                        "overheat_penalty": round(scoring_breakdown.get("overheat_penalty", 0), 2),
                        "divergence_detected": situation["details"].get("divergence_detected", False),
                        "pullback_quality": situation["details"].get("pullback_quality", 0),
                        "raw_score_before_adjustments": round(scoring_breakdown.get("raw_score", 0), 2),
                    }
                },
                # 情况规则说明（现在与评分体系解耦，仅作为描述标签）
                "situation_rule": self.SITUATION_RULES.get(
                    situation.get('type', ''),
                    {"description": "技术形态一般", "recommendation": "观望", "score": 0, "risk": "中", "reasoning": "技术形态不明确，建议观望。"}
                ),
                # 向后兼容
                "ma_analysis": self._generate_ma_analysis(latest, situation),
                "volume_analysis": self._generate_volume_analysis(latest, situation),
                "trend_analysis": self._generate_trend_analysis(latest, situation),
            }

            return result

        except Exception as e:
            import traceback
            return {
                "stock_code": stock_code,
                "stock_name": stock_name or stock_code,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }

    def _analyze_situation(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        prev: Optional[pd.Series]
    ) -> Dict[str, Any]:
        """
        判断四种情况 + 计算量价时空四维所需全部数据：
        1. 股价在25日均线下方 + 5日成交量小于60日成交量 → 不推荐
        2. 股价突破25日均线 + 5日成交量上穿60日成交量 → 短线关注
        3. 股价在25日均线上方回踩企稳 + 5日成交量回踩60日成交量且成交量放大 → 波段关注
        4. 股价在25日均线上方回踩企稳 + 5日成交量小于60日成交量且成交量萎缩 → 长线关注
        """
        ma10 = latest.get('MA10', 0)
        ma25 = latest.get('MA25', 0)
        ma60 = latest.get('MA60', 0)
        vol5 = latest.get('VOL5', 0)
        vol60 = latest.get('VOL60', 0)
        close = latest.get('close', 0)
        atr14 = latest.get('ATR14', 0)

        situation_type = ""
        description = ""
        details = {}

        # === 核心量化数据（所有情况共享） ===
        price_diff_pct = ((close - ma25) / ma25 * 100) if ma25 > 0 else 0
        tolerance_pct = self.RULES["touch_threshold"] * 100  # 0.5%
        vol_ratio = vol5 / vol60 if vol60 > 0 else 1.0

        details["price_diff_pct"] = round(price_diff_pct, 2)
        details["vol_ratio"] = round(vol_ratio, 2)
        details["atr14"] = round(float(atr14), 4) if atr14 > 0 else 0
        details["rsi"] = round(float(latest.get("RSI14", 50)), 1)

        # ---- 时（Time）维度数据 ----
        # 趋势持续性：收盘价连续在MA25上方的天数
        consecutive_above_ma25 = 0
        for i in range(len(df) - 1, -1, -1):
            if df.iloc[i]['close'] > df.iloc[i]['MA25']:
                consecutive_above_ma25 += 1
            else:
                break
        details["consecutive_above_ma25"] = consecutive_above_ma25

        # 统计连续低于MA25的天数（用于下跌趋势惩罚）
        consecutive_below_ma25 = 0
        for i in range(len(df) - 1, -1, -1):
            if df.iloc[i]['close'] < df.iloc[i]['MA25']:
                consecutive_below_ma25 += 1
            else:
                break
        details["consecutive_below_ma25"] = consecutive_below_ma25

        # 横盘检测：近20日价格振幅是否收窄（布林带宽度或简单的高低点振幅）
        if len(df) >= 20:
            recent_20 = df.tail(20)
            amplitude_20d = (recent_20['close'].max() - recent_20['close'].min()) / recent_20['close'].mean() * 100
            # 近5日振幅
            recent_5 = df.tail(5)
            amplitude_5d = (recent_5['close'].max() - recent_5['close'].min()) / recent_5['close'].mean() * 100
            # 振幅收窄 = 横盘蓄力
            details["amplitude_20d"] = round(amplitude_20d, 2)
            details["amplitude_5d"] = round(amplitude_5d, 2)
            details["is_consolidating"] = amplitude_5d < amplitude_20d * 0.6  # 近5日振幅明显收窄
        else:
            details["amplitude_20d"] = 0
            details["amplitude_5d"] = 0
            details["is_consolidating"] = False

        # ---- 空（Space）维度数据 ----
        # 上行空间：距离最近阻力位（60日高点 / MA120 / 近期高点）的距离，以ATR为单位
        if len(df) >= 60 and atr14 > 0:
            high_60d = df['high'].tail(60).max() if 'high' in df.columns else df['close'].tail(60).max()
            high_20d = df['high'].tail(20).max() if 'high' in df.columns else df['close'].tail(20).max()
            # 取MA60和近期高点中的较近者作为阻力
            resistance = max(ma60, close)  # 如果ma60低于当前价，取近期高点
            if ma60 > close:
                resistance = ma60
            elif high_20d > close:
                resistance = high_20d
            else:
                resistance = close + atr14 * 3  # 如果都在下方，用ATR估算
            upside_atr = (resistance - close) / atr14 if atr14 > 0 else 0
            # 下行支撑：MA25 或 近期低点
            support = max(ma25, df['low'].tail(20).min() if 'low' in df.columns else ma25)
            downside_atr = (close - support) / atr14 if atr14 > 0 else 0
            details["resistance"] = round(float(resistance), 2)
            details["support"] = round(float(support), 2)
            details["upside_atr"] = round(upside_atr, 2)
            details["downside_atr"] = round(downside_atr, 2)
        else:
            details["resistance"] = float(close)
            details["support"] = float(ma25)
            details["upside_atr"] = 1.0
            details["downside_atr"] = 1.0

        # ---- 价格在60日区间的位置（0=60日最低, 1=60日最高） ----
        if len(df) >= 60:
            high_60d = df['high'].tail(60).max() if 'high' in df.columns else df['close'].tail(60).max()
            low_60d = df['low'].tail(60).min() if 'low' in df.columns else df['close'].tail(60).min()
            range_60d = high_60d - low_60d
            price_60d_pos = ((close - low_60d) / range_60d) if range_60d > 0 else 0.5
        else:
            price_60d_pos = 0.5
        details["price_position"] = round(price_60d_pos, 3)

        # ---- 量价背离检测 ----
        divergence_detected = False
        if len(df) >= 40:
            # 比较最近20天和前20天的价格高点与量能高点
            recent_20_df = df.tail(20)
            prior_20_df = df.iloc[-40:-20]
            recent_high = recent_20_df['close'].max()
            prior_high = prior_20_df['close'].max()
            recent_vol_max = recent_20_df['volume'].max()
            prior_vol_max = prior_20_df['volume'].max()
            # 价格新高，但量能未新高 → 顶背离
            if recent_high > prior_high and recent_vol_max < prior_vol_max * 0.9:
                divergence_detected = True
            # 价格未新低，但量能新低 → 底背离（积极信号）
            recent_low = recent_20_df['close'].min()
            prior_low = prior_20_df['close'].min()
            if recent_low > prior_low and recent_vol_max < prior_vol_max * 0.7:
                divergence_detected = True  # 底背离也记录，但评分时正向处理
        details["divergence_detected"] = divergence_detected

        # ---- 回踩质量检测 ----
        pullback_quality = 0  # -1=不良回踩, 0=无回踩/一般, 1=良性回踩
        if len(df) >= 10 and price_diff_pct > tolerance_pct:
            # 回溯查找最近一次接近MA25（±2%以内）的日期
            found_pullback = False
            for i in range(len(df) - 2, max(len(df) - 30, -1), -1):
                row = df.iloc[i]
                row_ma25 = row.get('MA25', 0)
                if row_ma25 > 0:
                    row_diff = (row['close'] - row_ma25) / row_ma25 * 100
                    if abs(row_diff) <= 2.0:
                        # 检测到回踩，评估回踩期间量能
                        if i >= 3:
                            pullback_vol = df.iloc[i-3:i+1]['volume'].mean()
                            normal_vol = df.iloc[max(0,i-20):i-3]['volume'].mean() if i > 3 else pullback_vol
                            vol_on_pullback = pullback_vol / normal_vol if normal_vol > 0 else 1.0
                            # 回踩后反弹速度：回踩日到现在的涨幅
                            recovery_gain = (close - row['close']) / row['close'] * 100
                            if vol_on_pullback < 0.85 and recovery_gain > 1.0:
                                pullback_quality = 1  # 缩量回踩 + 快速反弹 = 良性
                            elif vol_on_pullback > 1.2 and recovery_gain < 0.5:
                                pullback_quality = -1  # 放量回踩 + 反弹乏力 = 不良
                        found_pullback = True
                        break
            if not found_pullback:
                pullback_quality = 0
        details["pullback_quality"] = pullback_quality

        # === 判断情况2: 股价突破25日均线 + 5日成交量上穿60日成交量 ===
        if prev is not None:
            prev_close = prev.get('close', 0)
            prev_vol5 = prev.get('VOL5', 0)
            prev_vol60 = prev.get('VOL60', 0)

            price_breakout = (prev_close <= ma25) and (close > ma25)
            vol_breakout = (prev_vol5 <= prev_vol60) and (vol5 > vol60)

            if price_breakout and vol_breakout:
                situation_type = "情况2"
                description = "股价突破25日均线，成交量上穿60日均线"
                details.update({
                    "action": "价格突破",
                    "vol_action": "量价齐升",
                    "prev_close": float(prev_close),
                    "prev_ma25": float(prev.get('MA25', 0)),
                    "prev_vol5": float(prev_vol5),
                    "prev_vol60": float(prev_vol60),
                })

        # === 如果不是情况2，继续判断其他情况 ===
        if situation_type == "":
            price_above_ma = close > ma25 and price_diff_pct > tolerance_pct
            price_near_ma = abs(price_diff_pct) <= tolerance_pct
            price_below_ma = close < ma25 and price_diff_pct < -tolerance_pct
            vol_above = vol5 > vol60

            # 成交量变化判断
            if len(df) >= 5:
                recent_vol5 = df['VOL5'].tail(3).values
                vol_trend = "increasing" if recent_vol5[-1] > recent_vol5[-2] > recent_vol5[-3] else "decreasing"
            else:
                vol_trend = "unknown"

            if (price_above_ma or price_near_ma) and (not vol_above) and vol_trend == "decreasing":
                situation_type = "情况4"
                if price_near_ma:
                    description = "股价在25日均线附近（±0.5%），成交量萎缩"
                    details.update({"action": "均线附近整理", "vol_action": "量能萎缩"})
                else:
                    description = "股价在25日均线上方，成交量萎缩"
                    details.update({"action": "强势调整", "vol_action": "量能萎缩"})
            elif (price_above_ma or price_near_ma) and vol_above and vol_trend == "increasing":
                situation_type = "情况3"
                if price_near_ma:
                    description = "股价在25日均线附近（±0.5%），成交量放大"
                else:
                    description = "股价在25日均线上方，成交量放大"
                details.update({"action": "强势" if not price_near_ma else "均线附近放量", "vol_action": "量能放大"})
            elif price_below_ma and (not vol_above):
                situation_type = "情况1"
                description = "股价在25日均线下方，成交量不足"
                details.update({"action": "弱势", "vol_action": "量能不足"})
            else:
                situation_type = "其他"
                if price_below_ma:
                    if vol_above:
                        description = "股价在25日均线下方，但成交量放大"
                        details.update({"action": "弱势反弹", "vol_action": "量能放大"})
                    else:
                        description = "股价在25日均线下方，成交量萎缩"
                        details.update({"action": "弱势", "vol_action": "量能萎缩"})
                elif price_near_ma:
                    description = "股价在25日均线附近，成交量一般"
                    details.update({"action": "均线附近整理", "vol_action": "量能一般"})
                else:
                    description = "股价在25日均线上方，但成交量不是持续放大/萎缩"
                    details.update({"action": "强势调整", "vol_action": "量能一般"})

        return {
            "type": situation_type,
            "description": description,
            "details": details,
            "indicators": {
                "close": float(close),
                "ma10": float(ma10),
                "ma25": float(ma25),
                "ma60": float(ma60),
                "vol5": float(vol5),
                "vol60": float(vol60),
                "atr14": float(atr14) if atr14 > 0 else 0,
            }
        }

    def _get_recommendation_by_situation(self, situation: Dict[str, Any]) -> tuple:
        """量价时空四维融合评分体系

        四维权重：
        - 价（Price） 35%：价格位置 + 动量 + 多MA排列
        - 量（Volume）25%：量能水平 + 量价配合
        - 时（Time）  20%：趋势持续性 + 横盘蓄力
        - 空（Space） 20%：上行空间 + 下行支撑

        额外调整：
        - 量价共振加成：价+量同时看多时 +1.5
        - 顶背离惩罚：-1.5
        - 回踩质量：±1.0
        """
        details = situation.get("details", {})
        indicators = situation.get("indicators", {})

        # ============================================================
        # 维度一：价（Price）— 价格位置 + 多MA排列 + 动量
        # ============================================================
        price_diff_pct = details.get("price_diff_pct", 0)
        if not isinstance(price_diff_pct, (int, float)):
            price_diff_pct = 0

        tolerance_pct = self.RULES["touch_threshold"] * 100  # 0.5%

        # 1a. 价格位置因子（相对MA25）— 上限扩展到+7，渐变区间扩展到10%
        # +10% → +7, +0.5% → 0, -0.5% → 0, -5% → -5
        if price_diff_pct > tolerance_pct:
            price_position = min(7.0, (price_diff_pct - tolerance_pct) / 10.0 * 7.0)
        elif price_diff_pct < -tolerance_pct:
            price_position = max(-5.0, (price_diff_pct + tolerance_pct) / 5.0 * 5.0)
        else:
            price_position = 0

        # 1b. 多MA排列因子 — MA10 > MA25 > MA60 为多头排列
        ma10 = indicators.get("ma10", 0)
        ma25 = indicators.get("ma25", 0)
        ma60 = indicators.get("ma60", 0)
        close = indicators.get("close", 0)

        if ma10 > 0 and ma25 > 0 and ma60 > 0:
            if ma10 > ma25 > ma60:
                ma_alignment = 1.0  # 标准多头排列
            elif ma10 > ma25 and ma25 <= ma60:
                ma_alignment = 0.5  # 短期转多但中期未确认
            elif ma10 < ma25 < ma60:
                ma_alignment = -1.0  # 标准空头排列
            elif ma10 < ma25 and ma25 >= ma60:
                ma_alignment = -0.5  # 短期转空
            else:
                ma_alignment = 0  # 交叉混乱
        else:
            ma_alignment = 0

        # 1c. 短期动量因子 — 近5日涨跌幅
        momentum_5d = details.get("momentum_5d", 0)
        if not isinstance(momentum_5d, (int, float)):
            momentum_5d = 0
        # 5日涨跌幅映射到 [-1.5, +1.5]
        if momentum_5d > 0:
            momentum_factor = min(1.5, momentum_5d / 10.0 * 1.5)
        else:
            momentum_factor = max(-1.5, momentum_5d / 10.0 * 1.5)

        # 价维度综合 = 价格位置 + MA排列 + 动量
        price_factor = price_position + ma_alignment + momentum_factor
        price_factor = max(-6.0, min(8.0, price_factor))

        # ============================================================
        # 维度二：量（Volume）— 量能水平 + 量价配合
        # ============================================================
        vol_ratio = details.get("vol_ratio", 1.0)
        if not isinstance(vol_ratio, (int, float)) or vol_ratio <= 0:
            vol_ratio = 1.0

        # 2a. 量能水平因子（连续渐变，消除1.0~1.5的"死亡区"）
        # 0.8~1.2: 真正中性（0分）
        # 1.2~1.8: 线性递进 +0.5 → +2.0
        # >1.8: 继续递进到 +2.5
        # 0.5~0.8: 线性递减 0 → -1.5
        # <0.5: -2.0
        if vol_ratio >= 1.8:
            vol_level = min(2.5, 2.0 + (vol_ratio - 1.8) / 1.0 * 0.5)
        elif vol_ratio >= 1.2:
            vol_level = (vol_ratio - 1.2) / 0.6 * 2.0  # 1.2→1.8 映射到 0→2.0
        elif vol_ratio >= 0.8:
            vol_level = 0  # 中性区
        elif vol_ratio >= 0.5:
            vol_level = (vol_ratio - 0.8) / 0.3 * 1.5  # 0.5→0.8 映射到 -1.5→0
        else:
            vol_level = -2.0

        # 2b. 量价配合因子 — 当价格在MA25上方时，量能>1.0即为正向确认
        vol_price_coordination = 0
        if price_diff_pct > tolerance_pct and vol_ratio > 1.0:
            # 价格强势 + 量能高于均值 = 量价配合良好
            coordination_strength = min(1.0, (vol_ratio - 1.0) / 0.5)  # 1.0→1.5 映射到 0→1.0
            vol_price_coordination = coordination_strength * 1.0
        elif price_diff_pct < -tolerance_pct and vol_ratio > 1.2:
            # 价格弱势但放量 = 可能出货
            vol_price_coordination = -0.5

        # 量维度综合
        volume_factor = vol_level + vol_price_coordination
        volume_factor = max(-2.5, min(3.5, volume_factor))

        # ============================================================
        # 维度三：时（Time）— 趋势持续性 + 横盘蓄力
        # ============================================================
        # 3a. 趋势持续性因子
        consecutive_days = details.get("consecutive_above_ma25", 0)
        am_consolidating = details.get("is_consolidating", False)
        amplitude_5d = details.get("amplitude_5d", 10)
        amplitude_20d = details.get("amplitude_20d", 10)

        if consecutive_days >= 60:
            trend_persistence = -0.5  # 长期高位，警惕过热
        elif consecutive_days >= 30:
            trend_persistence = 1.2  # 中期趋势确立，稳定性好
        elif consecutive_days >= 15:
            trend_persistence = 1.0
        elif consecutive_days >= 5:
            trend_persistence = 0.5
        elif consecutive_days >= 2:
            trend_persistence = 0.2  # 刚站上，不稳定
        else:
            trend_persistence = 0

        # 价格若在MA25下方，趋势持续性反向计分
        if price_diff_pct < -tolerance_pct:
            consecutive_below_days = details.get("consecutive_below_ma25", 0)
            if consecutive_below_days >= 20:
                trend_persistence = -1.5  # 长期下跌趋势
            elif consecutive_below_days >= 10:
                trend_persistence = -0.8
            elif consecutive_below_days >= 5:
                trend_persistence = -0.3
            else:
                trend_persistence = -0.1  # 短期回调

        # 3b. 横盘蓄力因子 — "横有多长，竖有多高"
        consolidation_factor = 0
        if am_consolidating and amplitude_20d > 0:
            # 横盘振幅收窄 + 横盘持续 → 蓄力待发
            consolidation_ratio = amplitude_5d / amplitude_20d if amplitude_20d > 0 else 1.0
            if consolidation_ratio < 0.4:
                consolidation_factor = 1.0  # 振幅显著收窄，蓄力充分
            elif consolidation_ratio < 0.6:
                consolidation_factor = 0.5
        elif amplitude_20d > 30:
            consolidation_factor = -0.5  # 宽幅震荡，方向不明

        # 时维度综合
        time_factor = trend_persistence + consolidation_factor
        time_factor = max(-1.5, min(2.0, time_factor))

        # ============================================================
        # 维度四：空（Space）— 上行空间 + 下行支撑
        # ============================================================
        upside_atr = details.get("upside_atr", 1.0)
        downside_atr = details.get("downside_atr", 1.0)

        # 4a. 上行空间因子 — 距离阻力位的ATR倍数
        if upside_atr >= 3.0:
            space_upside = 1.0  # 空间充裕
        elif upside_atr >= 2.0:
            space_upside = 0.7
        elif upside_atr >= 1.0:
            space_upside = 0.3
        elif upside_atr >= 0.5:
            space_upside = -0.3  # 空间不大
        else:
            space_upside = -0.8  # 接近阻力位，空间很小

        # 4b. 下行支撑因子 — 距离支撑位的ATR倍数（止损保护）
        if downside_atr >= 3.0:
            space_downside = -0.5  # 支撑太远，止损成本大
        elif downside_atr >= 2.0:
            space_downside = 0  # 中性
        elif downside_atr >= 1.0:
            space_downside = 0.5  # 支撑较近，止损明确
        elif downside_atr > 0:
            space_downside = 0.7  # 紧贴支撑，止损成本小
        else:
            space_downside = 0

        # 4c. 高位下行风险因子 — 价格在60日高位区时，下跌风险显著（P2 #5）
        space_downside_risk = 0
        price_60d_pos = details.get("price_position", 0.5)
        if price_60d_pos > 0.9:
            space_downside_risk = -0.8  # 接近60日高点，下跌风险大
        elif price_60d_pos > 0.8:
            space_downside_risk = -0.3  # 偏高位

        # 空维度综合
        space_factor = space_upside + space_downside + space_downside_risk
        space_factor = max(-1.5, min(1.5, space_factor))  # 负向扩大到-1.5

        # ============================================================
        # 额外调整项
        # ============================================================
        # 量价共振：价和量同时正向贡献时，额外加成
        resonance_bonus = 0
        if price_position > 1.0 and vol_level > 0.5:
            resonance_bonus = 1.5  # 量价共振，信号可靠度高
        elif price_position > 0.5 and vol_level > 0:
            resonance_bonus = 0.5  # 轻度共振

        # 顶背离惩罚
        divergence_penalty = 0
        if details.get("divergence_detected", False):
            if price_diff_pct > tolerance_pct:
                divergence_penalty = -1.5  # 高位顶背离
            else:
                divergence_penalty = 0.5  # 低位底背离，反而是积极信号

        # 回踩质量调整
        pullback_adjustment = 0
        pb_quality = details.get("pullback_quality", 0)
        if pb_quality == 1:
            pullback_adjustment = 1.0  # 良性回踩（缩量+快速反弹）
        elif pb_quality == -1:
            pullback_adjustment = -1.0  # 不良回踩（放量+反弹乏力）

        # 高位过热惩罚 — 价格远高于MA25时追高风险增加（均值回归视角）
        overheat_penalty = 0
        if price_diff_pct > 15:
            overheat_penalty = -2.0    # 严重过热
        elif price_diff_pct > 10:
            overheat_penalty = -1.0    # 明显过热
        elif price_diff_pct > 7:
            overheat_penalty = -0.5    # 轻度过热

        # RSI超买加成惩罚 — 高位+RSI超买=双重风险
        rsi_val = details.get("rsi", 50)
        if rsi_val is not None and price_diff_pct > 5:
            if rsi_val > 70:
                overheat_penalty -= 1.0   # RSI超买叠加
            elif rsi_val > 65:
                overheat_penalty -= 0.5

        # 价格在60日高点附近进一步惩罚
        price_60d_pos = details.get("price_position", 0.5)
        if price_60d_pos > 0.95 and price_diff_pct > 5:
            overheat_penalty -= 0.5  # 接近60日高点+高于MA25=高位风险

        # ============================================================
        # 四维融合
        # ============================================================
        price_weighted = price_factor * 0.35
        volume_weighted = volume_factor * 0.25
        time_weighted = time_factor * 0.20
        space_weighted = space_factor * 0.20
        raw_score = (price_weighted + volume_weighted + time_weighted + space_weighted) * 2.5

        # 加上额外调整
        score = raw_score + resonance_bonus + divergence_penalty + pullback_adjustment + overheat_penalty
        score = round(score, 1)

        # Clamp to [-7, 8]
        score = max(-7.0, min(8.0, score))

        # ============================================================
        # 推荐标签与风险等级（基于综合评分）
        # ============================================================
        if score >= 6:
            recommendation = "长线关注"
            risk_level = "低"
        elif score >= 4:
            recommendation = "波段关注"
            risk_level = "中"
        elif score >= 2:
            recommendation = "短线关注"
            risk_level = "中高"
        elif score >= -1:
            recommendation = "观望"
            risk_level = "中"
        elif score >= -3:
            recommendation = "谨慎"
            risk_level = "中高"
        else:
            recommendation = "不推荐"
            risk_level = "高"

        # 评分明细（用于输出和调试）
        breakdown = {
            "price_position": price_position,
            "ma_alignment": ma_alignment,
            "momentum_factor": momentum_factor,
            "price_factor": price_factor,
            "vol_level": vol_level,
            "vol_price_coordination": vol_price_coordination,
            "volume_factor": volume_factor,
            "trend_persistence": trend_persistence,
            "consolidation_factor": consolidation_factor,
            "time_factor": time_factor,
            "space_upside": space_upside,
            "space_downside": space_downside,
            "space_downside_risk": space_downside_risk,
            "space_factor": space_factor,
            "price_weighted": price_weighted,
            "volume_weighted": volume_weighted,
            "time_weighted": time_weighted,
            "space_weighted": space_weighted,
            "raw_score": raw_score,
            "resonance_bonus": resonance_bonus,
            "divergence_penalty": divergence_penalty,
            "pullback_adjustment": pullback_adjustment,
            "overheat_penalty": overheat_penalty,
        }

        return recommendation, score, risk_level, breakdown

    def _generate_signals(self, situation: Dict[str, Any], df: pd.DataFrame, latest: pd.Series, prev: Optional[pd.Series]) -> list:
        """生成信号列表（量价时空四维信号）"""
        signals = []
        situation_type = situation.get("type", "")
        details = situation.get("details", {})

        # --- 趋势信号 ---
        if situation_type == "情况4":
            signals.append({
                "type": "long_term_buy",
                "description": "长线机会，缩量回踩企稳，可分批建仓",
                "strength": 3,
                "direction": "bullish",
                "category": "趋势"
            })
        elif situation_type == "情况3":
            signals.append({
                "type": "swing_buy",
                "description": "波段机会，放量确认，短线介入",
                "strength": 2,
                "direction": "bullish",
                "category": "趋势"
            })
        elif situation_type == "情况2":
            signals.append({
                "type": "short_term_buy",
                "description": "短线突破信号，量价齐升",
                "strength": 1,
                "direction": "bullish",
                "category": "趋势"
            })
        elif situation_type == "情况1":
            signals.append({
                "type": "not_recommended",
                "description": "股价弱势，量能不足，不建议介入",
                "strength": -2,
                "direction": "bearish",
                "category": "趋势"
            })

        # --- 量价共振信号 ---
        price_diff_pct = details.get("price_diff_pct", 0)
        vol_ratio = details.get("vol_ratio", 1.0)
        if price_diff_pct > 0.5 and vol_ratio > 1.2:
            signals.append({
                "type": "resonance",
                "description": "量价共振：价格强势+量能放大，信号可靠度高",
                "strength": 2,
                "direction": "bullish",
                "category": "量价配合"
            })
        elif price_diff_pct > 2 and vol_ratio <= 0.8:
            signals.append({
                "type": "price_volume_divergence_short",
                "description": "价强量缩：高位缩量，需警惕动能衰减",
                "strength": -1,
                "direction": "bearish",
                "category": "量价配合"
            })

        # --- 时（Time）维度信号 ---
        consecutive_days = details.get("consecutive_above_ma25", 0)
        if consecutive_days >= 30:
            signals.append({
                "type": "established_trend",
                "description": f"趋势确立：连续{consecutive_days}日站上MA25，中期趋势稳固",
                "strength": 1,
                "direction": "bullish",
                "category": "时间"
            })
        if details.get("is_consolidating", False):
            signals.append({
                "type": "consolidating",
                "description": "横盘蓄力：近5日振幅显著收窄，蓄力待发",
                "strength": 1,
                "direction": "bullish",
                "category": "时间"
            })

        # --- 空（Space）维度信号 ---
        upside_atr = details.get("upside_atr", 0)
        if upside_atr >= 3:
            signals.append({
                "type": "ample_upside",
                "description": f"上行空间充裕（{upside_atr:.1f}倍ATR），趋势延续概率大",
                "strength": 1,
                "direction": "bullish",
                "category": "空间"
            })
        elif upside_atr < 0.5 and upside_atr > 0:
            signals.append({
                "type": "tight_upside",
                "description": "接近阻力位，上行空间不足，注意追高风险",
                "strength": -1,
                "direction": "bearish",
                "category": "空间"
            })

        # --- 背离信号 ---
        if details.get("divergence_detected", False):
            if price_diff_pct > 0:
                signals.append({
                    "type": "bearish_divergence",
                    "description": "顶背离：价格新高但量能未跟随，警惕回调",
                    "strength": -2,
                    "direction": "bearish",
                    "category": "背离"
                })
            else:
                signals.append({
                    "type": "bullish_divergence",
                    "description": "底背离：价格企稳但量能极度萎缩，可能触底",
                    "strength": 1,
                    "direction": "bullish",
                    "category": "背离"
                })

        # --- 回踩质量信号 ---
        pb_quality = details.get("pullback_quality", 0)
        if pb_quality == 1:
            signals.append({
                "type": "healthy_pullback",
                "description": "良性回踩：缩量回踩MA25+快速反弹，筹码锁定良好",
                "strength": 2,
                "direction": "bullish",
                "category": "回踩"
            })
        elif pb_quality == -1:
            signals.append({
                "type": "unhealthy_pullback",
                "description": "不良回踩：放量回踩+反弹乏力，注意风险",
                "strength": -1,
                "direction": "bearish",
                "category": "回踩"
            })

        return signals

    def _describe_ma_alignment(self, latest: pd.Series) -> str:
        """描述多MA排列状态"""
        ma10 = latest.get('MA10', 0)
        ma25 = latest.get('MA25', 0)
        ma60 = latest.get('MA60', 0)
        close = latest.get('close', 0)
        if ma10 > 0 and ma25 > 0 and ma60 > 0:
            if ma10 > ma25 > ma60:
                return "标准多头排列"
            elif ma10 > ma25:
                return "短期转多"
            elif ma10 < ma25 < ma60:
                return "标准空头排列"
            elif ma10 < ma25:
                return "短期转空"
            else:
                return "交叉混乱"
        return "数据不足"

    def _describe_vol_coordination(self, situation: Dict[str, Any]) -> str:
        """描述量价配合状态"""
        details = situation.get("details", {})
        price_diff = details.get("price_diff_pct", 0)
        vol_ratio = details.get("vol_ratio", 1.0)
        if price_diff > 0.5 and vol_ratio > 1.2:
            return "量价共振（看多）"
        elif price_diff > 0.5 and vol_ratio > 1.0:
            return "量能温和配合"
        elif price_diff > 0.5 and vol_ratio <= 1.0:
            return "价强量弱（需警惕）"
        elif price_diff < -0.5 and vol_ratio > 1.2:
            return "价弱量增（可能出货）"
        elif price_diff < -0.5 and vol_ratio <= 1.0:
            return "量价双弱"
        else:
            return "量价中性"

    def _generate_ma_analysis(self, latest: pd.Series, situation: Dict[str, Any]) -> Dict[str, Any]:
        """生成均线分析（兼容旧接口，含多MA）"""
        ma10 = latest.get('MA10', 0)
        ma25 = latest.get('MA25', 0)
        ma60 = latest.get('MA60', 0)
        close = latest.get('close', 0)
        diff_pct = ((close - ma25) / ma25 * 100) if ma25 > 0 else 0

        return {
            "ma_alignment": self._describe_ma_alignment(latest),
            "current_price_vs_ma": {
                "MA10": {
                    "value": float(ma10),
                    "diff_pct": round(((close - ma10) / ma10 * 100) if ma10 > 0 else 0, 2),
                    "status": "above" if close > ma10 else "below"
                },
                "MA25": {
                    "value": float(ma25),
                    "diff_pct": round(diff_pct, 2),
                    "status": "above" if close > ma25 else "below"
                },
                "MA60": {
                    "value": float(ma60),
                    "diff_pct": round(((close - ma60) / ma60 * 100) if ma60 > 0 else 0, 2),
                    "status": "above" if close > ma60 else "below"
                },
            },
            "cross_signals": [],
            "signals": []
        }

    def _generate_volume_analysis(self, latest: pd.Series, situation: Dict[str, Any]) -> Dict[str, Any]:
        """生成成交量分析（兼容旧接口）"""
        vol5 = latest.get('VOL5', 0)
        vol60 = latest.get('VOL60', 0)
        vol_ratio = vol5 / vol60 if vol60 > 0 else 0
        details = situation.get("details", {})

        return {
            "current_volume": int(latest.get('volume', 0)),
            "average_volume": float(vol60),
            "volume_ratio": round(vol_ratio, 2),
            "volume_trend": "放量" if vol5 > vol60 else "缩量",
            "volume_price_status": situation.get("description", ""),
            "vol_coordination": self._describe_vol_coordination(situation),
            "volume_signals": [],
            "signals": []
        }

    def _generate_trend_analysis(self, latest: pd.Series, situation: Dict[str, Any]) -> Dict[str, Any]:
        """生成趋势分析（兼容旧接口，含时空维度数据）"""
        details = situation.get("details", {})
        return {
            "overall_trend": "强势" if latest.get('close', 0) > latest.get('MA25', 0) else "弱势",
            "current_amplitude": details.get("amplitude_5d", 0),
            "consecutive_above_ma25": details.get("consecutive_above_ma25", 0),
            "is_consolidating": details.get("is_consolidating", False),
            "upside_atr": details.get("upside_atr", 0),
            "downside_atr": details.get("downside_atr", 0),
            "pullback_quality": details.get("pullback_quality", 0),
            "divergence_detected": details.get("divergence_detected", False),
            "period_trends": {},
            "signals": []
        }

    # ============================================================
    # 数据获取与指标计算
    # ============================================================

    def _fetch_stock_data(self, stock_code: str, days: int) -> pd.DataFrame:
        """获取股票数据（使用多数据源自动切换）"""
        from core.multi_source_fetcher import fetch_stock_data

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y-%m-%d')

        df = fetch_stock_data(stock_code, start_date, end_date)
        return df

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标（含量价时空所需指标）"""
        df = df.copy()

        # 均线系统
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA25'] = df['close'].rolling(window=self.RULES["ma25_period"]).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()

        # 成交量均线
        df['VOL5'] = df['volume'].rolling(window=self.RULES["vol5_period"]).mean()
        df['VOL60'] = df['volume'].rolling(window=self.RULES["vol60_period"]).mean()

        # ATR(14) — 用于空间维度（空）
        high = df['high'] if 'high' in df.columns else df['close']
        low = df['low'] if 'low' in df.columns else df['close']
        tr1 = high - low
        tr2 = abs(high - df['close'].shift(1))
        tr3 = abs(low - df['close'].shift(1))
        df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR14'] = df['TR'].rolling(window=14).mean()

        # 涨跌幅
        df['change_pct'] = df['close'].pct_change() * 100

        # 价格动量 — 近5日涨跌幅
        df['momentum_5d'] = df['close'].pct_change(5) * 100

        # RSI(14) — 用于高位过热检测
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, float('nan'))
        df['RSI14'] = 100.0 - (100.0 / (1.0 + rs))
        df['RSI14'] = df['RSI14'].fillna(50.0)

        return df

    def _calculate_change_percent(self, df: pd.DataFrame) -> float:
        """计算涨跌幅"""
        if len(df) < 2:
            return 0.0
        return round(((df.iloc[-1]['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100, 2)

    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票名称"""
        try:
            from agents.financial_data_fetcher import FinancialDataFetcher
            fetcher = FinancialDataFetcher()
            code, is_hk = fetcher._normalize_code(stock_code)
            name = fetcher._get_stock_name(code, is_hk)
            return name if name else stock_code
        except:
            return stock_code


class TechnicalAgent(TechnicalAnalyzer):
    """
    向后兼容别名 - 原 technical_agent.py 的 TechnicalAgent 已合并到 TechnicalAnalyzer。
    接受 api_key/model 参数以兼容旧的调用方式，实际分析完全由 TechnicalAnalyzer 完成。
    """

    def __init__(self, api_key=None, model=None):
        super().__init__()

    def analyze(self, stock_code, stock_name=None, days=120, use_llm=False):
        """兼容旧 TechnicalAgent.analyze() 接口，use_llm 参数被忽略。"""
        return super().analyze(stock_code=stock_code, stock_name=stock_name, days=days)


def analyze_stock(
    stock_code: str,
    stock_name: Optional[str] = None,
    days: int = 120
) -> Dict[str, Any]:
    """便捷函数：分析股票"""
    analyzer = TechnicalAnalyzer()
    return analyzer.analyze(stock_code, stock_name, days)
