#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF分析器 - 三维综合评分
整合行业基本面、技术分析、艾略特波浪分析对ETF进行综合评分

评分维度和权重：
- 行业板块基本面: 35%  (行业前景、政策支持、周期位置)
- 技术分析:       35%  (MA25+成交量)
- 艾略特波浪分析: 30%  (波浪位置+上涨概率)

评分范围: -5 到 8
"""

import time
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

from .etf_fundamental import ETFFundamentalAnalyzer, RECOMMENDED_ETFS
from .elliott_agent import ElliottWaveAgent
from ..technical_analyzer import TechnicalAnalyzer


# ETF评分权重
ETF_WEIGHTS = {
    "fundamental": 0.35,
    "technical": 0.35,
    "elliott": 0.30,
}

# ETF推荐评级阈值（与个股统一）
ETF_RATING_THRESHOLDS = {
    "强烈推荐": 7.0,
    "推荐": 5.0,
    "中性": 0.0,
    "不推荐": -4.0,
    # < -4.0: 强烈不推荐
}


class ETFAnalyzer:
    """ETF三维综合分析器"""

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}

        self.fundamental_analyzer = ETFFundamentalAnalyzer()
        self.technical_analyzer = TechnicalAnalyzer()
        self.elliott_agent = ElliottWaveAgent(config)

    def analyze_single(
        self,
        etf_code: str,
        etf_name: str,
        favorable_industries: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        分析单个ETF，返回三维评分

        Args:
            etf_code: ETF代码
            etf_name: ETF名称
            favorable_industries: 当日利好行业列表

        Returns:
            ETF分析结果
        """
        print(f"  分析ETF {etf_name} ({etf_code})...")

        # 1. 行业基本面评分
        print(f"    行业基本面评分...")
        fundamental_result = self.fundamental_analyzer.analyze(
            etf_code, etf_name, favorable_industries
        )
        fundamental_score = fundamental_result.get("fundamental_score", 0)

        # 2. 技术分析评分
        print(f"    技术分析评分...")
        tech_result = None
        try:
            tech_result = self.technical_analyzer.analyze(etf_code, etf_name)
        except Exception as e:
            print(f"    技术分析失败: {str(e)[:60]}")

        if tech_result and "error" not in tech_result:
            tech_score = tech_result.get("score", 0)
        else:
            tech_score = 0

        # 3. 艾略特波浪评分
        print(f"    艾略特波浪评分...")
        elliott_result = None
        try:
            elliott_result = self.elliott_agent.analyze_etf(etf_code, etf_name)
        except Exception as e:
            print(f"    波浪分析失败: {str(e)[:60]}")

        if elliott_result and "error" not in elliott_result:
            elliott_score = elliott_result.get("elliott_score", 0)
        else:
            elliott_score = 0

        # 4. 综合评分
        has_elliott = (
            elliott_result
            and isinstance(elliott_result, dict)
            and "error" not in elliott_result
            and elliott_result.get("wave_position") not in (None, "分析失败", "数据不足")
        )
        combined_score = (
            fundamental_score * ETF_WEIGHTS["fundamental"]
            + tech_score * ETF_WEIGHTS["technical"]
            + elliott_score * ETF_WEIGHTS["elliott"]
        )
        combined_score = round(combined_score, 1)

        # 5. 确定评级（使用统一阈值）
        # 与个股保持一致：强烈推荐要求基本面和技术分都超过1.5
        both_positive = fundamental_score > 1.5 and tech_score > 1.5
        rating = self._determine_rating(combined_score, both_positive)
        is_recommended = rating in ("推荐", "强烈推荐")

        # 6. 生成推荐理由
        reason = self._generate_reason(
            etf_name, fundamental_score, tech_score, elliott_score,
            combined_score, fundamental_result, elliott_result, rating
        )

        print(
            f"    综合: {combined_score} | "
            f"基本面: {fundamental_score} | 技术: {tech_score} | 波浪: {elliott_score} | "
            f"评级: {rating}"
        )

        # 识别行业
        industry = fundamental_result.get("industry", "ETF基金")

        # 生成买卖点建议
        buy_sell = self._generate_buy_sell_advice(
            tech_result, elliott_result, rating, combined_score
        )

        return {
            "stock_code": etf_code,
            "stock_name": etf_name,
            "industry": industry,
            "source": "ETF",
            "technical_analysis": tech_result or {},
            "fundamental_analysis": fundamental_result,
            "elliott_analysis": elliott_result or {},
            "analysis_time": datetime.now().isoformat(),
            # Scores
            "fundamental_score": fundamental_score,
            "tech_score": tech_score,
            "elliott_score": elliott_score,
            "combined_score": combined_score,
            # Rating
            "rating": rating,
            "is_recommended": is_recommended,
            "both_positive": both_positive,
            "has_elliott": has_elliott,
            "risk_level": (tech_result or {}).get("risk_level", "中"),
            "operation_suggestion": (tech_result or {}).get("recommendation", "观望"),
            "recommendation_reason": reason,
            # Buy/Sell points
            "buy_point": buy_sell["buy_point"],
            "buy_reason": buy_sell["buy_reason"],
            "sell_point": buy_sell["sell_point"],
            "sell_reason": buy_sell["sell_reason"],
        }

    def analyze_etf_pool(
        self,
        etf_list: List[Dict[str, Any]],
        favorable_industries: Optional[List[Dict]] = None,
    ) -> List[Dict[str, Any]]:
        """
        批量分析ETF列表

        Args:
            etf_list: ETF列表 [{"stock_code": "515850.SH", "stock_name": "证券ETF富国", "industry": "ETF基金"}]
            favorable_industries: 当日利好行业列表

        Returns:
            分析结果列表
        """
        results = []

        for i, etf in enumerate(etf_list, 1):
            etf_code = etf.get("stock_code", etf.get("code", ""))
            etf_name = etf.get("stock_name", etf.get("name", ""))

            if not etf_code:
                continue

            print(f"\n  [{i}/{len(etf_list)}] ETF {etf_name} ({etf_code})")

            if i > 1:
                time.sleep(0.5)  # 避免API限频

            result = self.analyze_single(etf_code, etf_name, favorable_industries)
            results.append(result)

        # 按综合评分排序
        results.sort(key=lambda x: x["combined_score"], reverse=True)

        return results

    def _determine_rating(self, combined_score: float, both_positive: bool = False) -> str:
        """确定ETF评级（统一阈值，与个股一致）"""
        if combined_score >= ETF_RATING_THRESHOLDS["强烈推荐"] and both_positive:
            return "强烈推荐"
        elif combined_score >= ETF_RATING_THRESHOLDS["推荐"]:
            return "推荐"
        elif combined_score >= ETF_RATING_THRESHOLDS["中性"]:
            return "中性"
        elif combined_score >= ETF_RATING_THRESHOLDS["不推荐"]:
            return "不推荐"
        else:
            return "强烈不推荐"

    def _generate_reason(
        self,
        etf_name: str,
        fundamental_score: float,
        tech_score: float,
        elliott_score: float,
        combined_score: float,
        fundamental_result: Dict,
        elliott_result: Optional[Dict],
        rating: str,
    ) -> str:
        """生成推荐理由"""
        parts = []

        # 基本面
        if fundamental_score >= 5:
            parts.append("行业基本面前景良好")
        elif fundamental_score >= 2:
            parts.append("行业基本面中性偏正")
        elif fundamental_score < 0:
            parts.append("行业基本面前景偏弱")

        if fundamental_result.get("description"):
            parts.append(fundamental_result["description"].split("，")[0])

        # 技术面
        if tech_score >= 6:
            parts.append("技术面强势")
        elif tech_score >= 4:
            parts.append("技术面偏多")
        elif tech_score <= -3:
            parts.append("技术面弱势")

        # 波浪
        if elliott_result and "wave_position" in elliott_result:
            wave_pos = elliott_result["wave_position"]
            score_rationale = elliott_result.get("score_rationale", "")
            if "第3浪" in wave_pos:
                parts.append(f"波浪处于{wave_pos}(主升浪)")
            elif "第5浪" in wave_pos:
                parts.append(f"波浪处于{wave_pos}(趋势末期)")
            elif "调整浪末端" in wave_pos:
                parts.append("波浪处于调整浪末端(接近底部)")
            elif "调整浪" in wave_pos:
                parts.append(f"波浪处于{wave_pos}")
            elif "第1浪" in wave_pos:
                parts.append(f"波浪处于{wave_pos}(启动阶段)")
            if score_rationale:
                parts.append(score_rationale)

        return "；".join(parts) if parts else f"综合评分{combined_score}"

    def _generate_buy_sell_advice(
        self,
        tech_result: Optional[Dict],
        elliott_result: Optional[Dict],
        rating: str,
        combined_score: float,
    ) -> Dict[str, Any]:
        """基于技术指标和波浪分析生成ETF买入/卖出点建议"""
        result = {"buy_point": None, "buy_reason": "", "sell_point": None, "sell_reason": ""}

        data_summary = {}
        if tech_result and isinstance(tech_result, dict) and "error" not in tech_result:
            data_summary = tech_result.get("data_summary", {})

        close = data_summary.get("close", 0)
        ma25 = data_summary.get("ma25", 0)

        indicators = {}
        wave_pos = ""
        upside_prob = 50
        high_60 = 0
        low_60 = 0
        if elliott_result and isinstance(elliott_result, dict) and "error" not in elliott_result:
            indicators = elliott_result.get("indicators", {})
            wave_pos = elliott_result.get("wave_position", "")
            upside_prob = elliott_result.get("upside_probability", 50)
            high_60 = elliott_result.get("high_60", 0)
            low_60 = elliott_result.get("low_60", 0)

        ma20 = indicators.get("ma20", 0)
        ma60 = indicators.get("ma60", 0)
        rsi = indicators.get("rsi", 50)

        if not close or close <= 0:
            return result

        # Support levels (below current price)
        support_levels = []
        if ma25 and 0 < ma25 < close:
            support_levels.append(("MA25", ma25))
        if ma20 and 0 < ma20 < close:
            support_levels.append(("MA20", ma20))
        if ma60 and 0 < ma60 < close:
            support_levels.append(("MA60", ma60))
        if low_60 and 0 < low_60 < close:
            support_levels.append(("60日低点", low_60))

        # Resistance levels (above current price)
        resistance_levels = []
        if high_60 and high_60 > close:
            resistance_levels.append(("60日高点", high_60))
        if ma25 and ma25 > close:
            resistance_levels.append(("MA25", ma25))
        if ma20 and ma20 > close:
            resistance_levels.append(("MA20", ma20))
        if ma60 and ma60 > close:
            resistance_levels.append(("MA60", ma60))

        is_bullish = rating in ("推荐", "强烈推荐") or combined_score >= 3
        is_neutral = rating == "中性" or (0 <= combined_score < 3)
        is_bearish = rating in ("不推荐", "强烈不推荐") or combined_score < 0

        wave_bullish = any(k in wave_pos for k in ("第1浪", "第3浪", "调整浪末端", "反转"))
        wave_caution = any(k in wave_pos for k in ("第5浪", "超跌反弹"))

        buy_reasons = []
        sell_reasons = []

        if is_bullish or (is_neutral and wave_bullish):
            if support_levels:
                nearest = min(support_levels, key=lambda x: abs(x[1] - close))
                result["buy_point"] = round(nearest[1], 3)
                buy_reasons.append(f"回踩{nearest[0]}({nearest[1]:.3f})获支撑")
                others = [s for s in support_levels if s[0] != nearest[0]]
                if others:
                    second = min(others, key=lambda x: abs(x[1] - close))
                    buy_reasons.append(f"下方较强支撑{second[0]}({second[1]:.3f})")
            else:
                result["buy_point"] = round(close * 0.97, 3)
                buy_reasons.append("当前价位附近可分批建仓")

            if wave_bullish:
                buy_reasons.append(f"波浪位于{wave_pos}，上涨概率{upside_prob}%")
            if rsi < 30:
                buy_reasons.append(f"RSI={rsi:.0f}超卖")
            elif rsi < 40:
                buy_reasons.append(f"RSI={rsi:.0f}偏低")

            if resistance_levels:
                nearest_r = min(resistance_levels, key=lambda x: abs(x[1] - close))
                result["sell_point"] = round(nearest_r[1], 3)
                sell_reasons.append(f"接近{nearest_r[0]}({nearest_r[1]:.3f})压力位可减仓")
            if wave_caution:
                sell_reasons.append(f"波浪位于{wave_pos}，需警惕趋势反转")
            if rsi > 70:
                sell_reasons.append(f"RSI={rsi:.0f}超买，注意回调风险")

        elif is_neutral:
            if support_levels:
                nearest = min(support_levels, key=lambda x: abs(x[1] - close))
                result["buy_point"] = round(nearest[1], 3)
                buy_reasons.append(f"回踩{nearest[0]}({nearest[1]:.3f})可轻仓试探")
            else:
                result["buy_point"] = round(close * 0.95, 3)
                buy_reasons.append("等待更明确支撑信号")

            if resistance_levels:
                nearest_r = min(resistance_levels, key=lambda x: abs(x[1] - close))
                result["sell_point"] = round(nearest_r[1], 3)
                sell_reasons.append(f"反弹至{nearest_r[0]}({nearest_r[1]:.3f})可减仓")
            else:
                result["sell_point"] = round(close * 1.05, 3)
                sell_reasons.append("反弹5%左右可考虑减仓")

            buy_reasons.append("中性评级，控制仓位")
            if wave_pos:
                buy_reasons.append(f"波浪位置: {wave_pos}")

        else:
            if resistance_levels:
                nearest_r = min(resistance_levels, key=lambda x: abs(x[1] - close))
                result["sell_point"] = round(nearest_r[1], 3)
                sell_reasons.append(f"反弹至{nearest_r[0]}({nearest_r[1]:.3f})建议减仓离场")
            else:
                result["sell_point"] = round(close, 3)
                sell_reasons.append("弱势格局，建议逢高减仓")

            sell_reasons.append("综合评分偏空，不建议追涨")
            if wave_caution or "调整浪" in wave_pos:
                sell_reasons.append(f"波浪位于{wave_pos}，下行风险较大")
            if rsi < 30:
                result["buy_point"] = round(low_60 if low_60 and low_60 > 0 else close * 0.95, 3)
                buy_reasons.append(f"RSI={rsi:.0f}极度超卖，仅适合短线反弹博弈")

        result["buy_reason"] = "；".join(buy_reasons) if buy_reasons else "暂无明确买入信号"
        result["sell_reason"] = "；".join(sell_reasons) if sell_reasons else "暂无明确卖出信号"

        return result


def get_recommended_etfs_with_pool(
    pool_etfs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    合并自选池ETF和推荐ETF列表，去重

    Args:
        pool_etfs: 自选股票池中的ETF列表

    Returns:
        合并后的ETF列表
    """
    # 从推荐列表构建ETF字典
    all_etfs = {}
    for etf in RECOMMENDED_ETFS:
        key = etf["code"]
        all_etfs[key] = {
            "stock_code": etf["code"],
            "stock_name": etf["name"],
            "industry": etf["industry"],
            "source": "推荐",
        }

    # 加入自选池ETF（覆盖推荐列表中的同代码项）
    for etf in pool_etfs:
        code = etf.get("stock_code", etf.get("code", ""))
        name = etf.get("stock_name", etf.get("name", ""))
        industry = etf.get("industry", "ETF基金")
        # 确保ETF代码有后缀
        if "." not in code:
            code = _normalize_etf_code(code)
        all_etfs[code] = {
            "stock_code": code,
            "stock_name": name,
            "industry": industry,
            "source": "自选池",
        }

    return list(all_etfs.values())


def _normalize_etf_code(code: str) -> str:
    """将纯数字ETF代码标准化为带后缀的代码"""
    if "." in code:
        return code

    if code.startswith("51") or code.startswith("56") or code.startswith("58"):
        return f"{code}.SH"
    elif code.startswith("15") or code.startswith("16"):
        return f"{code}.SZ"
    else:
        return f"{code}.SH"  # 默认上交所
