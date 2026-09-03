#!/usr/bin/env python3
"""
Company Quality Scorer - 三维牛熊评分量化引擎

实现好公司、趋势、估值三个维度的结构化评分
基于"时间的朋友"理念，量化评估投资价值
"""

import json
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from statistics import mean, stdev

from agents.financial_data_fetcher import FinancialDataFetcher
from core.llm_client import LLMClient


class CompanyQualityScorer:
    """三维牛熊评分量化引擎

    评分体系:
    - 好公司评分 (45%): 商业模式穿越周期(40%) + 企业文化(30%) + 可理解性(30%)
    - 趋势评分 (30%): 行业趋势(40%) + 公司趋势(40%) + 市场情绪(20%)
    - 估值评分 (25%): 相对估值(35%) + 绝对估值(35%) + 安全边际(30%)
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        """初始化评分引擎

        Args:
            api_key: LLM API密钥
            model: 使用的模型名称
        """
        self.financial_fetcher = FinancialDataFetcher()
        self.llm_client = LLMClient(api_key=api_key, model=model)
        self.model = model

    def compute_comprehensive_score(
        self,
        stock_name: str,
        stock_code: str,
        financial_data: Optional[Dict[str, Any]] = None,
        industry: Optional[str] = None
    ) -> Dict[str, Any]:
        """计算综合牛熊评分

        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            financial_data: 财务数据（可选，为空则自动获取）
            industry: 行业分类（可选）

        Returns:
            {
                "bull_bear_score": 3.4,  # 最终综合评分
                "company_quality": {...},  # 好公司评分详情
                "trend": {...},           # 趋势评分详情
                "valuation": {...},       # 估值评分详情
                "weights_used": {...},    # 实际使用的权重
                "veto_triggered": bool,   # 是否触发一票否决
                "scoring_time": "2026-05-29 12:00:00"
            }
        """
        scoring_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 获取财务数据
        if financial_data is None:
            financial_data = self.financial_fetcher.get_stock_financial_data(stock_code, stock_name)

        # 获取历史数据
        historical_data = self.financial_fetcher.get_historical_financial_indicators(stock_code, years=5)

        # 获取估值数据（网络不稳定时不影响核心FOT评估）
        try:
            valuation_data = self.financial_fetcher.get_valuation_percentiles(stock_code)
        except Exception as e:
            print(f"    获取估值分位数失败(非致命): {str(e)[:60]}")
            valuation_data = {}

        # 获取行业对比数据
        industry_comparison = {}
        if industry:
            industry_comparison = self.financial_fetcher.get_industry_comparison_data(stock_code, industry)

        # 计算三个维度评分
        company_quality = self.score_company_quality(financial_data, historical_data, stock_name, stock_code)
        trend = self.score_trend(financial_data, historical_data, stock_name, stock_code, industry)
        valuation = self.score_valuation(financial_data, valuation_data, industry_comparison, stock_code)

        # 检查一票否决
        veto_triggered = self._check_veto_rules(company_quality)

        # 应用动态权重
        weights = self._get_dynamic_weights(company_quality, trend, valuation)

        # 计算最终评分
        raw_score = (
            company_quality["score"] * weights["company_quality"] +
            trend["score"] * weights["trend"] +
            valuation["score"] * weights["valuation"]
        )

        # 应用一票否决规则
        final_score = self._apply_veto_adjustment(raw_score, company_quality, trend, valuation, veto_triggered)

        return {
            "bull_bear_score": round(final_score, 1),
            "company_quality": company_quality,
            "trend": trend,
            "valuation": valuation,
            "weights_used": weights,
            "veto_triggered": veto_triggered,
            "scoring_time": scoring_time
        }

    def score_company_quality(
        self,
        financial_data: Dict[str, Any],
        historical_data: Dict[str, Any],
        stock_name: str,
        stock_code: str
    ) -> Dict[str, Any]:
        """好公司评分：评估"时间的朋友"特质

        三大子维度：
        1. 商业模式穿越周期能力 (40%)
        2. 企业文化抵御人性弱点 (30%)
        3. 可理解性/能力圈 (30%)

        Returns:
            {
                "score": 6.5,  # 总分 [-10, 10]
                "business_model": {"score": 7.0, "details": {...}},
                "corporate_culture": {"score": 6.0, "details": {...}},
                "understandability": {"score": 6.5, "details": {...}},
                "is_friend_of_time": True,
                "reasoning": "..."
            }
        """
        # 1. 商业模式穿越周期评分 (40%)
        business_model = self._score_business_model_durability(historical_data)

        # 2. 企业文化抵御人性弱点评分 (30%)
        corporate_culture = self._score_corporate_culture(financial_data, historical_data)

        # 3. 可理解性评分 (30%)
        understandability = self._score_understandability(financial_data, historical_data, stock_name, stock_code)

        # 加权合成
        total_score = (
            business_model["score"] * 0.40 +
            corporate_culture["score"] * 0.30 +
            understandability["score"] * 0.30
        )
        total_score = max(-10, min(10, round(total_score, 1)))

        # 判断是否为"时间的朋友"
        is_friend_of_time = (
            business_model["score"] >= 5 and
            corporate_culture["score"] >= 4 and
            understandability["score"] >= 5
        )

        return {
            "score": total_score,
            "business_model": business_model,
            "corporate_culture": corporate_culture,
            "understandability": understandability,
            "is_friend_of_time": is_friend_of_time,
            "reasoning": self._generate_quality_reasoning(business_model, corporate_culture, understandability)
        }

    def _score_business_model_durability(self, historical_data: Dict[str, Any]) -> Dict[str, Any]:
        """商业模式穿越周期能力评分

        评估要点:
        - ROE 均值（5年）: >20%(+3), 15-20%(+2), 10-15%(+1), 5-10%(0), <5%(-2)
        - ROE 稳定性（5年标准差）: <3%(+2), 3-5%(+1), 5-10%(0), >10%(-2)
        - 经营现金流/净利润（3年均值）: >1.2(+2), 1.0-1.2(+1), 0.8-1.0(0), 0.5-0.8(-1), <0.5(-3)
        - 毛利率稳定性（5年波动）: <3%(+2), 3-5%(+1), 5-10%(0), >10%(-2)
        - 资本开支/经营现金流（3年均值）: <30%(+1), 30-50%(0), 50-70%(-1), >70%(-2)
        """
        score_breakdown = []
        total_points = 0
        max_points = 0

        # ROE 均值评分
        roe_history = historical_data.get("roe_history", [])
        if roe_history:
            roe_values = [item["value"] for item in roe_history if self._is_valid_number(item["value"])]
            if roe_values:
                roe_mean = mean(roe_values)
                max_points += 3

                if roe_mean > 20:
                    total_points += 3
                    score_breakdown.append(f"ROE均值{roe_mean:.1f}%（优秀）+3")
                elif roe_mean > 15:
                    total_points += 2
                    score_breakdown.append(f"ROE均值{roe_mean:.1f}%（良好）+2")
                elif roe_mean > 10:
                    total_points += 1
                    score_breakdown.append(f"ROE均值{roe_mean:.1f}%（一般）+1")
                elif roe_mean > 5:
                    score_breakdown.append(f"ROE均值{roe_mean:.1f}%（偏低）0")
                else:
                    total_points -= 2
                    score_breakdown.append(f"ROE均值{roe_mean:.1f}%（差）-2")

                # ROE 稳定性评分
                if len(roe_values) >= 2:
                    try:
                        roe_std = stdev(roe_values)
                        max_points += 2

                        if roe_std < 3:
                            total_points += 2
                            score_breakdown.append(f"ROE稳定（标准差{roe_std:.1f}）+2")
                        elif roe_std < 5:
                            total_points += 1
                            score_breakdown.append(f"ROE较稳定（标准差{roe_std:.1f}）+1")
                        elif roe_std < 10:
                            score_breakdown.append(f"ROE波动中等（标准差{roe_std:.1f}）0")
                        else:
                            total_points -= 2
                            score_breakdown.append(f"ROE波动大（标准差{roe_std:.1f}）-2")
                    except statistics.StatisticsError:
                        pass
        else:
            score_breakdown.append("ROE数据不足 0")

        # 经营现金流质量评分
        ocf_history = historical_data.get("operating_cash_flow_history", [])
        # 这里需要净利润数据，暂时简化处理
        if ocf_history and len(ocf_history) >= 2:
            max_points += 2
            ocf_values = [item["value"] for item in ocf_history if self._is_valid_number(item["value"])]

            if ocf_values and mean(ocf_values) > 0:
                # 检查现金流是否稳定为正
                positive_ratio = len([v for v in ocf_values if v > 0]) / len(ocf_values)
                if positive_ratio >= 0.8:
                    total_points += 2
                    score_breakdown.append(f"现金流优秀（{positive_ratio*100:.0f}%为正）+2")
                else:
                    total_points += 1
                    score_breakdown.append(f"现金流一般（{positive_ratio*100:.0f}%为正）+1")
            else:
                score_breakdown.append("现金流数据不足 0")

        # 毛利率稳定性评分
        gross_margin_history = historical_data.get("gross_margin_history", [])
        if gross_margin_history and len(gross_margin_history) >= 3:
            margin_values = [item["value"] for item in gross_margin_history if self._is_valid_number(item["value"])]
            if margin_values:
                try:
                    margin_std = stdev(margin_values)
                    margin_mean = mean(margin_values)
                    cv = (margin_std / margin_mean * 100) if margin_mean > 0 else 999  # 变异系数

                    max_points += 2

                    if cv < 5:  # 变异系数小于5%视为非常稳定
                        total_points += 2
                        score_breakdown.append(f"毛利率稳定（CV={cv:.1f}%）+2")
                    elif cv < 15:
                        total_points += 1
                        score_breakdown.append(f"毛利率较稳定（CV={cv:.1f}%）+1")
                    elif cv < 30:
                        score_breakdown.append(f"毛利率波动中等（CV={cv:.1f}%）0")
                    else:
                        total_points -= 2
                        score_breakdown.append(f"毛利率波动大（CV={cv:.1f}%）-2")
                except statistics.StatisticsError:
                    pass
        else:
            score_breakdown.append("毛利率数据不足 0")

        # 资本开支评分
        fcf_history = historical_data.get("free_cash_flow_history", [])
        ocf_history = historical_data.get("operating_cash_flow_history", [])

        if fcf_history and ocf_history and len(fcf_history) >= 2:
            max_points += 1

            # 计算FCF/OCF比率
            fcf_ocf_ratios = []
            for fcf_item, ocf_item in zip(fcf_history, ocf_history):
                fcf_val = fcf_item.get("value")
                ocf_val = ocf_item.get("value")

                if self._is_valid_number(fcf_val) and self._is_valid_number(ocf_val) and ocf_val > 0:
                    ratio = (fcf_val / ocf_val) * 100  # 转为百分比
                    fcf_ocf_ratios.append(ratio)

            if fcf_ocf_ratios:
                avg_ratio = mean(fcf_ocf_ratios)
                # 这里的比率代表资本开支占经营现金流的比例
                capex_ratio = 100 - avg_ratio

                if capex_ratio < 30:
                    total_points += 1
                    score_breakdown.append(f"资本开支占比低（{capex_ratio:.0f}%）+1")
                elif capex_ratio < 50:
                    score_breakdown.append(f"资本开支占比中等（{capex_ratio:.0f}%）0")
                elif capex_ratio < 70:
                    total_points -= 1
                    score_breakdown.append(f"资本开支占比高（{capex_ratio:.0f}%）-1")
                else:
                    total_points -= 2
                    score_breakdown.append(f"资本开支占比很高（{capex_ratio:.0f}%）-2")
        else:
            score_breakdown.append("资本开支数据不足 0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _score_corporate_culture(self, financial_data: Dict, historical_data: Dict) -> Dict[str, Any]:
        """企业文化抵御人性弱点评分

        评估要点:
        - 分红+回购/净利润（3年均值）: >60%(+2), 40-60%(+1), 20-40%(0), <20%(-1)
        - 管理层持股变化: 增持(+2), 持平(0), 减持(-2)
        - 研发投入/营收（行业对比）: 高于行业中位数(+1), 持平(0), 低于(-1)
        - 商誉/净资产: <10%(+1), 10-30%(0), >30%(-2)
        """
        score_breakdown = []
        total_points = 0
        max_points = 0

        # 分红比例评分
        dividend_history = historical_data.get("dividend_history", [])
        if dividend_history:
            dividend_ratios = [item.get("dividend_ratio", 0) for item in dividend_history]
            if dividend_ratios:
                avg_dividend_ratio = mean(dividend_ratios) * 100  # 转为百分比
                max_points += 2

                if avg_dividend_ratio > 60:
                    total_points += 2
                    score_breakdown.append(f"分红比例高（{avg_dividend_ratio:.0f}%）+2")
                elif avg_dividend_ratio > 40:
                    total_points += 1
                    score_breakdown.append(f"分红比例良好（{avg_dividend_ratio:.0f}%）+1")
                elif avg_dividend_ratio > 20:
                    score_breakdown.append(f"分红比例一般（{avg_dividend_ratio:.0f}%）0")
                else:
                    total_points -= 1
                    score_breakdown.append(f"分红比例低（{avg_dividend_ratio:.0f}%）-1")
        else:
            score_breakdown.append("分红数据不足 0")

        # 研发投入评分（需要从业务概述中提取）
        business_overview = financial_data.get("business_overview", "")
        if "研发" in business_overview or "R&D" in business_overview.upper():
            # 简化处理：如果有提到研发，给予中性偏正评分
            max_points += 1
            total_points += 1
            score_breakdown.append("关注研发投入 +1")
        else:
            score_breakdown.append("研发投入信息不足 0")

        # 商誉/净资产评分
        balance_sheet = financial_data.get("balance_sheet", {})
        total_assets = self._parse_financial_number(balance_sheet.get("总资产"))
        intangible_assets = self._parse_financial_number(balance_sheet.get("无形资产"))
        goodwill = self._parse_financial_number(balance_sheet.get("商誉"))
        equity = self._parse_financial_number(balance_sheet.get("股东权益") or balance_sheet.get("股东权益合计"))

        if equity and equity > 0:
            max_points += 1

            # 商誉+无形资产合计
            intangible_total = (goodwill or 0) + (intangible_assets or 0)
            intangible_ratio = (intangible_total / equity) * 100

            if intangible_ratio < 10:
                total_points += 1
                score_breakdown.append(f"商誉占比低（{intangible_ratio:.1f}%）+1")
            elif intangible_ratio < 30:
                score_breakdown.append(f"商誉占比中等（{intangible_ratio:.1f}%）0")
            else:
                total_points -= 2
                score_breakdown.append(f"商誉占比高（{intangible_ratio:.1f}%）-2")
        else:
            score_breakdown.append("商誉数据不足 0")

        # 管理层诚信评分（简化处理，实际需要更多数据）
        max_points += 2
        # 默认给予中性评分，除非有违规记录
        total_points += 0
        score_breakdown.append("管理层诚信（无违规记录）0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _score_understandability(self, financial_data: Dict, historical_data: Dict, stock_name: str, stock_code: str) -> Dict[str, Any]:
        """可理解性（能力圈）评分

        评估要点:
        - 营收集中度（前3业务占比）: >70%(+2), 50-70%(+1), 30-50%(0), <30%(-1)
        - 业务复杂度（LLM评估）: 单一清晰(+2), 适度多元(0), 过度多元(-2)
        - 盈利可预测性（3年预测误差）: 误差<10%(+2), 10-20%(+1), 20-30%(0), >30%(-2)
        """
        score_breakdown = []
        total_points = 0
        max_points = 0

        # 业务复杂度评估（基于业务概述）
        business_overview = financial_data.get("business_overview", "")
        complexity_score = self._assess_business_complexity(business_overview, stock_name)
        max_points += 2
        total_points += complexity_score["points"]
        score_breakdown.append(complexity_score["reasoning"])

        # 盈利可预测性评分
        revenue_history = historical_data.get("revenue_growth_history", [])
        # 移除季度数据，只保留年报（每个year只保留一条或去重）
        seen_years = set()
        annual_revenue = []
        for item in revenue_history:
            yr = item.get("year", item.get("period", ""))
            yr_int = int(str(yr)[:4]) if str(yr)[:4].isdigit() else 0
            if yr_int and yr_int not in seen_years:
                seen_years.add(yr_int)
                annual_revenue.append(item)

        if annual_revenue and len(annual_revenue) >= 3:
            revenue_values = [item.get("value") for item in annual_revenue
                            if self._is_valid_number(item.get("value"))]

            if revenue_values:
                try:
                    # 计算增长率的标准差作为预测误差的代理指标
                    growth_rates = []
                    for i in range(1, len(revenue_values)):
                        if revenue_values[i-1] > 0:
                            growth_rate = ((revenue_values[i] - revenue_values[i-1]) / revenue_values[i-1]) * 100
                            growth_rates.append(abs(growth_rate))  # 使用绝对值

                    if growth_rates:
                        growth_volatility = stdev(growth_rates) if len(growth_rates) >= 2 else 0
                        max_points += 2

                        if growth_volatility < 10:
                            total_points += 2
                            score_breakdown.append(f"盈利可预测性好（波动{growth_volatility:.1f}%）+2")
                        elif growth_volatility < 20:
                            total_points += 1
                            score_breakdown.append(f"盈利可预测性中等（波动{growth_volatility:.1f}%）+1")
                        elif growth_volatility < 30:
                            score_breakdown.append(f"盈利可预测性一般（波动{growth_volatility:.1f}%）0")
                        else:
                            total_points -= 2
                            score_breakdown.append(f"盈利波动大（波动{growth_volatility:.1f}%）-2")
                except statistics.StatisticsError:
                    pass
        else:
            score_breakdown.append("盈利可预测性数据不足 0")

        # 营收集中度评分（简化处理）
        # 通常需要从年报中获取各业务板块占比，这里做简化判断
        max_points += 1
        if "业务涵盖" in business_overview or "多元化" in business_overview:
            score_breakdown.append("业务多元化，集中度信息需进一步确认 0")
        else:
            total_points += 1
            score_breakdown.append("业务相对专注 +1")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _assess_business_complexity(self, business_overview: str, stock_name: str) -> Dict[str, Any]:
        """评估业务复杂度"""
        complexity_keywords = {
            "high": ["多元化", "集团", "平台", "生态", "综合", "多项业务"],
            "medium": ["主要业务", "核心业务", "专注", "主营"],
            "low": ["单一", "专注", "龙头", "领先"]
        }

        overview_lower = business_overview.lower()

        high_count = sum(1 for kw in complexity_keywords["high"] if kw in business_overview)
        low_count = sum(1 for kw in complexity_keywords["low"] if kw in business_overview)

        if high_count >= 2 or ("多元化" in business_overview and "集团" in business_overview):
            return {
                "points": -2,
                "reasoning": "业务复杂度高（多元化集团）-2"
            }
        elif low_count >= 2:
            return {
                "points": 2,
                "reasoning": "业务清晰专注 +2"
            }
        else:
            return {
                "points": 0,
                "reasoning": "业务复杂度中等 0"
            }

    def score_trend(
        self,
        financial_data: Dict[str, Any],
        historical_data: Dict[str, Any],
        stock_name: str,
        stock_code: str,
        industry: Optional[str]
    ) -> Dict[str, Any]:
        """趋势评分：评估公司所处行业与自身的发展趋势

        三大子维度：
        1. 行业趋势 (40%)
        2. 公司趋势 (40%)
        3. 市场情绪趋势 (20%)

        Returns:
            {
                "score": 4.0,  # 总分 [-10, 10]
                "industry_trend": {"score": 5.0, "details": {...}},
                "company_trend": {"score": 4.0, "details": {...}},
                "sentiment_trend": {"score": 2.0, "details": {...}},
                "reasoning": "..."
            }
        """
        # 1. 行业趋势评分
        industry_trend = self._score_industry_trend(financial_data, historical_data, industry, stock_name, stock_code)

        # 2. 公司趋势评分
        company_trend = self._score_company_trend(historical_data)

        # 3. 市场情绪趋势评分
        sentiment_trend = self._score_sentiment_trend(financial_data, stock_code)

        # 加权合成
        total_score = (
            industry_trend["score"] * 0.40 +
            company_trend["score"] * 0.40 +
            sentiment_trend["score"] * 0.20
        )
        total_score = max(-10, min(10, round(total_score, 1)))

        return {
            "score": total_score,
            "industry_trend": industry_trend,
            "company_trend": company_trend,
            "sentiment_trend": sentiment_trend,
            "reasoning": self._generate_trend_reasoning(industry_trend, company_trend, sentiment_trend)
        }

    def _score_industry_trend(
        self, financial_data: Dict, historical_data: Dict, industry: Optional[str],
        stock_name: str, stock_code: str
    ) -> Dict[str, Any]:
        """行业趋势评分"""
        score_breakdown = []
        total_points = 0
        max_points = 0

        # 行业营收增速（通过公司增速推断）
        revenue_history = historical_data.get("revenue_growth_history", [])
        if revenue_history and len(revenue_history) >= 2:
            recent_revenues = [item.get("value") for item in revenue_history[:2]
                             if self._is_valid_number(item.get("value"))]

            if len(recent_revenues) >= 2 and recent_revenues[1] > 0:
                growth_rate = ((recent_revenues[0] - recent_revenues[1]) / recent_revenues[1]) * 100
                max_points += 3

                if growth_rate > 15:
                    total_points += 3
                    score_breakdown.append(f"营收高增长（{growth_rate:.1f}%）+3")
                elif growth_rate > 8:
                    total_points += 2
                    score_breakdown.append(f"营收稳健增长（{growth_rate:.1f}%）+2")
                elif growth_rate > 3:
                    total_points += 1
                    score_breakdown.append(f"营收温和增长（{growth_rate:.1f}%）+1")
                elif growth_rate > 0:
                    score_breakdown.append(f"营收缓慢增长（{growth_rate:.1f}%）0")
                else:
                    total_points -= 2
                    score_breakdown.append(f"营收负增长（{growth_rate:.1f}%）-2")
        else:
            score_breakdown.append("营收增速数据不足 0")

        # 行业政策环境（LLM评估）
        if self.llm_client.is_available():
            try:
                policy_assessment = self._assess_industry_policy(financial_data, industry, stock_name)
                max_points += 2
                total_points += policy_assessment["score"]
                score_breakdown.append(policy_assessment["reasoning"])
            except Exception:
                score_breakdown.append("政策环境评估失败 0")
        else:
            score_breakdown.append("政策环境评估（无LLM）0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _score_company_trend(self, historical_data: Dict) -> Dict[str, Any]:
        """公司趋势评分"""
        score_breakdown = []
        total_points = 0
        max_points = 0

        # 营收增速趋势
        revenue_history = historical_data.get("revenue_growth_history", [])
        if revenue_history and len(revenue_history) >= 3:
            revenues = [item.get("value") for item in revenue_history[:3]
                      if self._is_valid_number(item.get("value"))]

            if len(revenues) >= 3:
                # 计算加速/减速
                growth_1 = ((revenues[0] - revenues[1]) / revenues[1]) * 100 if revenues[1] > 0 else 0
                growth_2 = ((revenues[1] - revenues[2]) / revenues[2]) * 100 if revenues[2] > 0 else 0

                acceleration = growth_1 - growth_2

                max_points += 3

                if acceleration > 5 and growth_1 > 10:  # 加速且高增长
                    total_points += 3
                    score_breakdown.append(f"营收加速增长（加速{acceleration:.1f}%）+3")
                elif growth_1 > 10:
                    total_points += 2
                    score_breakdown.append(f"营收稳定高增长（{growth_1:.1f}%）+2")
                elif growth_1 > 5:
                    total_points += 1
                    score_breakdown.append(f"营收稳定增长（{growth_1:.1f}%）+1")
                elif growth_1 > 0:
                    score_breakdown.append(f"营收缓慢增长（{growth_1:.1f}%）0")
                else:
                    total_points -= 2
                    score_breakdown.append(f"营收负增长（{growth_1:.1f}%）-2")
        else:
            score_breakdown.append("营收趋势数据不足 0")

        # 净利润增速趋势
        # 这里简化处理，使用ROE趋势作为代理指标
        roe_history = historical_data.get("roe_history", [])
        if roe_history and len(roe_history) >= 2:
            roes = [item.get("value") for item in roe_history[:2]
                   if self._is_valid_number(item.get("value"))]

            if len(roes) >= 2:
                roe_trend = roes[0] - roes[1]
                max_points += 1

                if roe_trend > 2:
                    total_points += 1
                    score_breakdown.append(f"ROE提升（{roe_trend:.1f}%）+1")
                elif roe_trend > -2:
                    score_breakdown.append(f"ROE稳定（{roe_trend:.1f}%）0")
                else:
                    score_breakdown.append(f"ROE下降（{roe_trend:.1f}%）0")
        else:
            score_breakdown.append("ROE趋势数据不足 0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _score_sentiment_trend(self, financial_data: Dict, stock_code: str) -> Dict[str, Any]:
        """市场情绪趋势评分"""
        score_breakdown = []
        total_points = 0
        max_points = 1

        # 机构持仓变化（简化处理，实际需要专业数据源）
        # 使用成交量变化作为情绪的代理指标
        key_metrics = financial_data.get("key_metrics", {})
        volume_trend = key_metrics.get("量比") or key_metrics.get("volume_trend")

        if volume_trend:
            if "放大" in str(volume_trend):
                total_points += 1
                score_breakdown.append("成交量放大，情绪积极 +1")
            elif "萎缩" in str(volume_trend):
                score_breakdown.append("成交量萎缩，情绪谨慎 0")
            else:
                score_breakdown.append("成交量平稳 0")
        else:
            score_breakdown.append("成交量数据不足 0")

        # 分析师预期调整（需要专业数据源，简化处理）
        max_points += 1
        score_breakdown.append("分析师预期数据不足 0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _assess_industry_policy(
        self, financial_data: Dict, industry: Optional[str], stock_name: str
    ) -> Dict[str, Any]:
        """评估行业政策环境（使用LLM）"""
        business_overview = financial_data.get("business_overview", "")

        system_prompt = """你是一位政策分析专家，擅长评估行业政策环境。

请根据提供的业务概述，判断该行业当前的政策环境：
- 强支持: 国家政策大力扶持，列入重点发展产业
- 中性: 政策环境平稳，无明显支持或限制
- 限制: 政策收紧，存在监管限制

返回JSON格式：
{
    "assessment": "强支持|中性|限制",
    "score": 2,  # 强支持:2, 中性:0, 限制:-2
    "reasoning": "简短理由（1句话）"
}"""

        user_prompt = f"""股票：{stock_name}
行业：{industry or '未指定'}

业务概述：
{business_overview[:500]}

请评估该行业当前的政策环境。"""

        try:
            response = self.llm_client.chat(system_prompt, user_prompt, max_tokens=200)
            result = json.loads(response)

            return {
                "score": result.get("score", 0),
                "reasoning": result.get("reasoning", "政策评估")
            }
        except Exception as e:
            return {"score": 0, "reasoning": f"政策评估失败: {str(e)[:50]}"}

    def score_valuation(
        self,
        financial_data: Dict[str, Any],
        valuation_data: Dict[str, Any],
        industry_comparison: Dict[str, Any],
        stock_code: str
    ) -> Dict[str, Any]:
        """估值评分：衡量当前价格相对于内在价值的安全边际

        三大子维度：
        1. 相对估值 (35%)
        2. 绝对估值信号 (35%)
        3. 安全边际 (30%)

        Returns:
            {
                "score": -2.0,  # 总分 [-10, 10]
                "relative_valuation": {"score": -1.0, "details": {...}},
                "absolute_valuation": {"score": -2.0, "details": {...}},
                "safety_margin": {"score": -3.0, "details": {...}},
                "reasoning": "..."
            }
        """
        # 1. 相对估值评分
        relative_valuation = self._score_relative_valuation(financial_data, valuation_data, industry_comparison)

        # 2. 绝对估值信号评分
        absolute_valuation = self._score_absolute_valuation(financial_data, stock_code)

        # 3. 安全边际评分
        safety_margin = self._score_safety_margin(financial_data, valuation_data)

        # 加权合成
        total_score = (
            relative_valuation["score"] * 0.35 +
            absolute_valuation["score"] * 0.35 +
            safety_margin["score"] * 0.30
        )
        total_score = max(-10, min(10, round(total_score, 1)))

        return {
            "score": total_score,
            "relative_valuation": relative_valuation,
            "absolute_valuation": absolute_valuation,
            "safety_margin": safety_margin,
            "reasoning": self._generate_valuation_reasoning(relative_valuation, absolute_valuation, safety_margin)
        }

    def _score_relative_valuation(self, financial_data: Dict, valuation_data: Dict, industry_comparison: Dict) -> Dict:
        """相对估值评分"""
        score_breakdown = []
        total_points = 0
        max_points = 0

        # PE 分位数评分
        pe_percentile = valuation_data.get("pe_percentile_5y")
        if pe_percentile is not None:
            max_points += 3

            if pe_percentile < 20:
                total_points += 3
                score_breakdown.append(f"PE分位数低（{pe_percentile:.0f}%）+3")
            elif pe_percentile < 40:
                total_points += 1
                score_breakdown.append(f"PE分位数较低（{pe_percentile:.0f}%）+1")
            elif pe_percentile < 60:
                score_breakdown.append(f"PE分位数中性（{pe_percentile:.0f}%）0")
            elif pe_percentile < 80:
                total_points -= 1
                score_breakdown.append(f"PE分位数偏高（{pe_percentile:.0f}%）-1")
            else:
                total_points -= 3
                score_breakdown.append(f"PE分位数高（{pe_percentile:.0f}%）-3")
        else:
            score_breakdown.append("PE分位数数据不足 0")

        # PB 分位数评分
        pb_percentile = valuation_data.get("pb_percentile_5y")
        if pb_percentile is not None:
            max_points += 2

            if pb_percentile < 20:
                total_points += 2
                score_breakdown.append(f"PB分位数低（{pb_percentile:.0f}%）+2")
            elif pb_percentile < 40:
                total_points += 1
                score_breakdown.append(f"PB分位数较低（{pb_percentile:.0f}%）+1")
            elif pb_percentile < 60:
                score_breakdown.append(f"PB分位数中性（{pb_percentile:.0f}%）0")
            else:
                total_points -= 2
                score_breakdown.append(f"PB分位数偏高（{pb_percentile:.0f}%）-2")
        else:
            score_breakdown.append("PB分位数数据不足 0")

        # 行业对比评分
        industry_pe_diff = industry_comparison.get("stock_vs_industry_pe")
        if industry_pe_diff:
            max_points += 2

            try:
                diff_value = float(industry_pe_diff.replace('%', ''))
                if diff_value < -30:  # 低于行业30%以上
                    total_points += 2
                    score_breakdown.append(f"PE低于行业{industry_pe_diff} +2")
                elif diff_value < -10:
                    total_points += 1
                    score_breakdown.append(f"PE略低于行业{industry_pe_diff} +1")
                elif diff_value < 10:
                    score_breakdown.append(f"PE接近行业{industry_pe_diff} 0")
                elif diff_value < 30:
                    total_points -= 2
                    score_breakdown.append(f"PE高于行业{industry_pe_diff} -2")
                else:
                    total_points -= 2
                    score_breakdown.append(f"PE大幅高于行业{industry_pe_diff} -2")
            except (ValueError, AttributeError):
                score_breakdown.append("行业对比数据解析失败 0")
        else:
            score_breakdown.append("行业对比数据不足 0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _score_absolute_valuation(self, financial_data: Dict, stock_code: str) -> Dict:
        """绝对估值信号评分"""
        score_breakdown = []
        total_points = 0
        max_points = 0

        key_metrics = financial_data.get("key_metrics", {})

        # CAPE 评分（如果有的话）
        # 这里需要单独计算CAPE，暂时用PE代替
        pe = self._parse_financial_number(key_metrics.get("市盈率PE"))
        if pe is not None:
            max_points += 3

            if pe < 10:
                total_points += 3
                score_breakdown.append(f"PE/CAPE极低（{pe:.1f}）+3")
            elif pe < 15:
                total_points += 2
                score_breakdown.append(f"PE/CAPE低（{pe:.1f}）+2")
            elif pe < 25:
                score_breakdown.append(f"PE/CAPE合理（{pe:.1f}）0")
            elif pe < 35:
                total_points -= 2
                score_breakdown.append(f"PE/CAPE偏高（{pe:.1f}）-2")
            elif pe < 50:
                total_points -= 3
                score_breakdown.append(f"PE/CAPE高（{pe:.1f}）-3")
            else:
                total_points -= 4
                score_breakdown.append(f"PE/CAPE极高（{pe:.1f}）-4")
        else:
            score_breakdown.append("PE数据不足 0")

        # 股息率评分
        dividend_yield = self._parse_financial_number(key_metrics.get("股息率TTM"))
        if dividend_yield is not None:
            max_points += 2

            if dividend_yield >= 5:
                total_points += 2
                score_breakdown.append(f"股息率高（{dividend_yield:.1f}%）+2")
            elif dividend_yield >= 3:
                total_points += 1
                score_breakdown.append(f"股息率良好（{dividend_yield:.1f}%）+1")
            elif dividend_yield >= 1.5:
                score_breakdown.append(f"股息率一般（{dividend_yield:.1f}%）0")
            elif dividend_yield >= 0.5:
                total_points -= 1
                score_breakdown.append(f"股息率低（{dividend_yield:.1f}%）-1")
            else:
                total_points -= 2
                score_breakdown.append(f"股息率极低（{dividend_yield:.1f}%）-2")
        else:
            score_breakdown.append("股息率数据不足 0")

        # FCF Yield 评分（自由现金流收益率）
        # 需要市值和自由现金流数据，简化处理
        max_points += 3
        score_breakdown.append("FCF收益率数据不足 0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    def _score_safety_margin(self, financial_data: Dict, valuation_data: Dict) -> Dict:
        """安全边际评分"""
        score_breakdown = []
        total_points = 0
        max_points = 3

        # 内在价值折扣率（简化处理，需要DCF模型）
        # 使用PE分位数作为代理指标
        pe_percentile = valuation_data.get("pe_percentile_5y")
        if pe_percentile is not None:
            if pe_percentile < 20:
                total_points += 3
                score_breakdown.append(f"估值折扣率高（低分位数{pe_percentile:.0f}%）+3")
            elif pe_percentile < 40:
                total_points += 2
                score_breakdown.append(f"估值折扣率良好（低分位数{pe_percentile:.0f}%）+2")
            elif pe_percentile < 60:
                score_breakdown.append(f"估值合理（分位数{pe_percentile:.0f}%）0")
            else:
                total_points -= 3
                score_breakdown.append(f"估值溢价（高分位数{pe_percentile:.0f}%）-3")
        else:
            score_breakdown.append("安全边际数据不足 0")

        # 悲观情景下行空间（需要专业分析，简化处理）
        max_points += 2
        score_breakdown.append("下行空间数据不足 0")

        # 归一化到 [-10, 10]
        if max_points > 0:
            normalized_score = (total_points / max_points) * 10
            normalized_score = max(-10, min(10, normalized_score))
        else:
            normalized_score = 0

        return {
            "score": round(normalized_score, 1),
            "details": {
                "points_earned": total_points,
                "max_points": max_points,
                "breakdown": score_breakdown
            },
            "reasoning": "; ".join(score_breakdown)
        }

    # ================================================================
    # 辅助方法
    # ================================================================

    def _check_veto_rules(self, company_quality: Dict[str, Any]) -> bool:
        """检查一票否决规则

        触发条件（满足任一即触发）：
        1. 行业技术颠覆风险高
        2. 商业模式依赖单一非可再生资源
        3. 管理层重大诚信问题
        4. 连续3年经营现金流为负
        """
        # 检查好公司评分是否过低
        if company_quality["score"] <= -3:
            return True

        # 检查商业模式评分
        business_model_score = company_quality.get("business_model", {}).get("score", 0)
        if business_model_score <= -5:
            return True

        # 检查现金流情况
        # 这里需要检查连续3年现金流，暂时简化
        return False

    def _get_dynamic_weights(
        self, company_quality: Dict, trend: Dict, valuation: Dict
    ) -> Dict[str, float]:
        """动态权重调整"""
        default_weights = {
            "company_quality": 0.45,
            "trend": 0.30,
            "valuation": 0.25
        }

        # 好公司评分 ≤ -3（非好公司）
        if company_quality["score"] <= -3:
            return {"company_quality": 0.60, "trend": 0.20, "valuation": 0.20}

        # 趋势评分 ≥ 7（强趋势）
        if trend["score"] >= 7:
            return {"company_quality": 0.35, "trend": 0.45, "valuation": 0.20}

        # 估值评分 ≤ -5（严重高估）
        if valuation["score"] <= -5:
            return {"company_quality": 0.35, "trend": 0.20, "valuation": 0.45}

        return default_weights

    def _apply_veto_adjustment(
        self, raw_score: float, company_quality: Dict, trend: Dict, valuation: Dict, veto_triggered: bool
    ) -> float:
        """应用一票否决与上限规则"""
        score = raw_score

        # 规则1："时间的朋友"否决
        if veto_triggered:
            score = min(score, -2)

        # 规则2：好公司+好趋势+高估 = 不卖但等
        if company_quality["score"] >= 5 and trend["score"] >= 3 and valuation["score"] <= -5:
            score = max(score, -1)

        # 规则3：非好公司+趋势下行+高估 = 极度看空
        if company_quality["score"] <= -3 and trend["score"] <= -3 and valuation["score"] <= -3:
            score = min(score, -7)

        return score

    def _generate_quality_reasoning(self, business_model: Dict, corporate_culture: Dict, understandability: Dict) -> str:
        """生成好公司评分理由"""
        parts = []
        if business_model.get("reasoning"):
            parts.append(f"商业模式: {business_model['reasoning']}")
        if corporate_culture.get("reasoning"):
            parts.append(f"企业文化: {corporate_culture['reasoning']}")
        if understandability.get("reasoning"):
            parts.append(f"可理解性: {understandability['reasoning']}")
        return "; ".join(parts)

    def _generate_trend_reasoning(self, industry_trend: Dict, company_trend: Dict, sentiment_trend: Dict) -> str:
        """生成趋势评分理由"""
        parts = []
        if industry_trend.get("reasoning"):
            parts.append(f"行业: {industry_trend['reasoning']}")
        if company_trend.get("reasoning"):
            parts.append(f"公司: {company_trend['reasoning']}")
        if sentiment_trend.get("reasoning"):
            parts.append(f"情绪: {sentiment_trend['reasoning']}")
        return "; ".join(parts)

    def _generate_valuation_reasoning(self, relative_val: Dict, absolute_val: Dict, safety_margin: Dict) -> str:
        """生成估值评分理由"""
        parts = []
        if relative_val.get("reasoning"):
            parts.append(f"相对估值: {relative_val['reasoning']}")
        if absolute_val.get("reasoning"):
            parts.append(f"绝对估值: {absolute_val['reasoning']}")
        if safety_margin.get("reasoning"):
            parts.append(f"安全边际: {safety_margin['reasoning']}")
        return "; ".join(parts)

    def _is_valid_number(self, value: Any) -> bool:
        """检查是否为有效数字"""
        if value is None:
            return False
        try:
            num = float(value)
            return not (np.isnan(num) or np.isinf(num))
        except (ValueError, TypeError):
            return False

    def _parse_financial_number(self, value: Any) -> Optional[float]:
        """解析财务数字"""
        if value is None or value == "N/A":
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            # 移除百分号、单位等
            value = value.replace('%', '').replace('亿', '').replace('万', '').replace('元', '').strip()
            try:
                return float(value)
            except ValueError:
                return None

        return None
