#!/usr/bin/env python3
"""
Bull Agent - 唱多Agent（芒格 persona）
专注于挖掘股票的积极因素和看涨理由
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import json
from pathlib import Path

from core.llm_client import LLMClient


class BullAgent:
    """唱多Agent - 寻找和强调股票的积极因素（芒格 persona）"""

    # 内置 fallback persona（当 skills/persona 文件缺失时使用）
    _FALLBACK_PERSONA = """你是查理·芒格，以多头/辩护方身份分析这只股票。你的核心信念：以合理价格买入伟大企业远胜以便宜价格买入平庸企业。反过来想——先排除死地：列出所有失败路径，如果都已定价或被排除，即可下注。护城河——转换成本、品牌定价权、网络效应、规模经济，至少一项在加宽。激励——管理层、渠道、客户的激励结构是否让公司长期做正确的事？你的结论倾向：BET（可下注）/ INVESTIGATE（值得深研）/ WAIT（等更好价格）。所有判断必须基于提供的财务数据；数据不足时标注「数据不足」而非臆造。"""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        """
        初始化唱多Agent

        Args:
            api_key: LLM API密钥（支持Anthropic/DeepSeek/OpenAI）
            model: 使用的模型名称
        """
        self.llm_client = LLMClient(api_key=api_key, model=model)
        self.model = self.llm_client.model or model
        self.role = "芒格（多头）"
        self.stance = "bullish"

        # 加载芒格多头 persona
        self.persona = self._load_persona()

    def _load_persona(self, persona_path: Optional[str] = None) -> str:
        """加载 persona 文件，缺失时 fallback 到内置版本。"""
        if persona_path is None:
            # 自动查找：skills/persona/munger-bull.md
            candidates = [
                Path(__file__).resolve().parent.parent / "skills" / "persona" / "munger-bull.md",
                Path("skills/persona/munger-bull.md"),
            ]
        else:
            candidates = [Path(persona_path)]

        for path in candidates:
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    # 去掉 markdown 标题行（以 # 开头）
                    lines = [l for l in content.split("\n") if not l.startswith("# ")]
                    persona = "\n".join(lines).strip()
                    if persona:
                        return persona
                except Exception:
                    pass

        print(f"  ⚠ 芒格 persona 文件未找到，使用内置精简版")
        return self._FALLBACK_PERSONA

    def analyze_financials(
        self,
        stock_name: str,
        stock_code: str,
        financial_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        分析财务数据，寻找积极因素

        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            financial_data: 财务数据
            context: 额外的上下文信息（如对手观点）

        Returns:
            分析结果字典
        """
        system_prompt = self.persona + """

你的分析应该专业、有理有据，但带有明确的看多倾向。

**重要：你需要从三个维度进行结构化评分**
- 好公司评分 (Company Quality): 评估商业模式穿越周期、企业文化、可理解性
- 趋势评分 (Trend): 评估行业趋势、公司趋势、市场情绪
- 估值评分 (Valuation): 评估相对估值、绝对估值、安全边际

每个维度评分范围：[-10, +10]，分数越高越看多。"""

        financial_summary = self._format_financial_data(financial_data)

        user_prompt = f"""请分析以下股票的财务数据，提供看多观点：

股票名称：{stock_name}
股票代码：{stock_code}

财务数据：
{financial_summary}

"""
        if context and context.get("opponent_view"):
            user_prompt += f"""
对手（看空分析师）的主要观点：
{context['opponent_view']}

请针对上述看空观点进行反驳，并提供你的看多论据。
"""

        user_prompt += """
请以JSON格式返回分析结果，包含以下字段：
{
    "summary": "整体看多观点总结（1-2句话）",
    "key_bullish_points": [
        "看多观点1",
        "看多观点2",
        ...
    ],
    "financial_strengths": [
        "财务优势1",
        "财务优势2",
        ...
    ],
    "growth_catalysts": [
        "增长催化剂1",
        "增长催化剂2",
        ...
    ],
    "counter_arguments": [
        "对看空观点的反驳1",
        "对看空观点的反驳2",
        ...
    ],
    "conclusion": "综合结论",
    "dimension_scores": {
        "company_quality": {
            "score": 7.5,
            "reasoning": "商业模式优秀，现金流稳定，业务清晰",
            "sub_scores": {
                "business_model": 8.0,
                "corporate_culture": 7.0,
                "understandability": 7.5
            },
            "is_friend_of_time": true
        },
        "trend": {
            "score": 6.0,
            "reasoning": "行业景气度回升，公司增长加速",
            "sub_scores": {
                "industry_trend": 6.5,
                "company_trend": 6.0,
                "sentiment_trend": 5.0
            }
        },
        "valuation": {
            "score": 4.0,
            "reasoning": "估值合理偏低，具备安全边际",
            "sub_scores": {
                "relative_valuation": 4.5,
                "absolute_valuation": 4.0,
                "safety_margin": 3.5
            }
        }
    }
}
"""

        response = self._call_llm(system_prompt, user_prompt)
        return self._parse_json_response(response)

    def rebut(
        self,
        opponent_view: str,
        stock_name: str,
        financial_data: Dict[str, Any]
    ) -> str:
        """
        反驳对手的观点

        Args:
            opponent_view: 对手的观点
            stock_name: 股票名称
            financial_data: 财务数据

        Returns:
            反驳内容
        """
        system_prompt = """你是一位专业的看多分析师，面对看空分析师的质疑，你需要：
1. 仔细分析对方的观点
2. 基于事实和数据进行专业反驳
3. 指出对方分析中的不足或错误
4. 重申看多的核心论据
5. 保持专业和理性，避免情绪化

你的投资人格：""" + self.persona

        user_prompt = f"""股票：{stock_name}

核心财务数据：
{self._format_financial_data(financial_data)}

看空分析师的观点：
{opponent_view}

请从看多角度进行反驳，指出对方观点的问题，并重申看多论据。
"""

        response = self._call_llm(system_prompt, user_prompt)
        return response

    def _format_financial_data(self, data: Dict[str, Any]) -> str:
        """格式化财务数据用于分析"""
        formatted = []

        if "income_statement" in data:
            formatted.append("=== 利润表 ===")
            for key, value in data["income_statement"].items():
                formatted.append(f"{key}: {value}")

        if "balance_sheet" in data:
            formatted.append("\n=== 资产负债表 ===")
            for key, value in data["balance_sheet"].items():
                formatted.append(f"{key}: {value}")

        if "cash_flow" in data:
            formatted.append("\n=== 现金流量表 ===")
            for key, value in data["cash_flow"].items():
                formatted.append(f"{key}: {value}")

        if "key_metrics" in data:
            formatted.append("\n=== 关键指标 ===")
            for key, value in data["key_metrics"].items():
                formatted.append(f"{key}: {value}")

        if "business_overview" in data:
            formatted.append("\n=== 业务概述 ===")
            formatted.append(data["business_overview"])

        return "\n".join(formatted)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用LLM API，带超时保护。

        在主线程中使用 signal.alarm() 硬超时；在子线程中 signal 不可用，
        则依赖 threading.Thread.join(timeout) 在调用方的外层超时保护。
        """
        import threading
        import signal

        is_main = threading.current_thread() is threading.main_thread()

        if is_main:
            class _Timeout(Exception):
                pass

            def _handler(signum, frame):
                raise _Timeout("LLM API调用超时(180s)")

            old_handler = signal.signal(signal.SIGALRM, _handler)
            signal.alarm(180)  # 180秒硬超时
            try:
                result = self.llm_client.chat(system_prompt, user_prompt)
                signal.alarm(0)
                return result
            except _Timeout:
                signal.alarm(0)
                raise Exception("LLM API调用超时(180s)")
            except Exception as e:
                signal.alarm(0)
                raise Exception(f"LLM API调用失败: {e}")
            finally:
                signal.signal(signal.SIGALRM, old_handler)
        else:
            # In daemon thread: skip signal, rely on caller's thread join timeout
            result = self.llm_client.chat(system_prompt, user_prompt)
            return result

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        try:
            # 尝试提取JSON部分
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                # 如果没有JSON格式，返回原始文本
                return {
                    "raw_response": response,
                    "summary": "无法解析为JSON格式",
                    "key_bullish_points": [],
                    "financial_strengths": [],
                    "growth_catalysts": [],
                    "counter_arguments": [],
                    "conclusion": response
                }
        except json.JSONDecodeError as e:
            return {
                "raw_response": response,
                "summary": f"JSON解析失败: {e}",
                "key_bullish_points": [],
                "financial_strengths": [],
                "growth_catalysts": [],
                "counter_arguments": [],
                "conclusion": response
            }
