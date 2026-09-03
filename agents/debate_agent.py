#!/usr/bin/env python3
"""
Debate Agent - 巴菲特-芒格辩论 Agent
协调巴菲特（空头）和芒格（多头）进行辩论，并生成最终报告
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import os
from pathlib import Path

from .bull_agent import BullAgent
from .bear_agent import BearAgent
from core.llm_client import LLMClient
from config.settings import settings


class DebateAgent:
    """巴菲特-芒格辩论 Agent - 协调巴菲特（空头）和芒格（多头）的辩论"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        rounds: int = 2,
        output_dir: Optional[Path] = None
    ):
        """
        初始化辩论Agent

        Args:
            api_key: LLM API密钥（支持Anthropic/DeepSeek/OpenAI）
            model: 使用的模型名称
            rounds: 辩论轮数
            output_dir: 报告输出目录
        """
        self.bull_agent = BullAgent(api_key=api_key, model=model)
        self.bear_agent = BearAgent(api_key=api_key, model=model)
        self.llm_client = LLMClient(api_key=api_key, model=model)
        self.model = self.llm_client.model or model
        self.rounds = rounds
        self.output_dir = output_dir or settings.BASE_DIR / "研报" / "个股分析"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.enable_master_report = os.environ.get("ENABLE_MASTER_REPORT", "").lower() in ("true", "1", "yes")

    def conduct_debate(
        self,
        stock_name: str,
        stock_code: str,
        financial_data: Dict[str, Any],
        save_report: bool = True
    ) -> Dict[str, Any]:
        """
        进行多空辩论

        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            financial_data: 财务数据
            save_report: 是否保存报告

        Returns:
            辩论结果
        """
        print(f"开始分析 {stock_name} ({stock_code})...")
        print("=" * 60)

        # 确保股票名称不为空，优先使用 financial_data 中的名称
        final_stock_name = stock_name
        if not final_stock_name or final_stock_name.strip() == "":
            final_stock_name = financial_data.get("stock_name", stock_code)
            if not final_stock_name or final_stock_name.strip() == "":
                final_stock_name = stock_code

        debate_history = {
            "stock_name": final_stock_name,
            "stock_code": stock_code,
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "initial_analysis": {},
            "debate_rounds": [],
            "final_summary": {}
        }

        # 使用最终的股票名称进行分析
        stock_name = final_stock_name

        # 第一轮：双方独立分析
        print("\n=== 第一轮：独立分析 ===")

        print("芒格（多头）正在分析...")
        bull_analysis = self.bull_agent.analyze_financials(
            stock_name, stock_code, financial_data
        )
        debate_history["initial_analysis"]["bull"] = bull_analysis
        print(f"芒格（多头）观点：{bull_analysis.get('summary', 'N/A')}")

        print("\n巴菲特（空头）正在分析...")
        bear_analysis = self.bear_agent.analyze_financials(
            stock_name, stock_code, financial_data
        )
        debate_history["initial_analysis"]["bear"] = bear_analysis
        print(f"巴菲特（空头）观点：{bear_analysis.get('summary', 'N/A')}")

        # 辩论轮次
        bull_view = self._extract_summary(bull_analysis)
        bear_view = self._extract_summary(bear_analysis)

        for round_num in range(1, self.rounds + 1):
            print(f"\n=== 第{round_num + 1}轮：辩论 ===")

            # 唱多反驳
            print(f"  芒格（多头）反驳第{round_num}轮...")
            bull_rebuttal = self.bull_agent.rebut(bear_view, stock_name, financial_data)
            debate_history["debate_rounds"].append({
                "round": round_num + 1,
                "speaker": "bull",
                "content": bull_rebuttal
            })
            bull_view = bull_rebuttal
            print(f"    芒格（多头）：{bull_rebuttal[:100]}...")

            # 唱空反驳
            print(f"  巴菲特（空头）反驳第{round_num}轮...")
            bear_rebuttal = self.bear_agent.rebut(bull_view, stock_name, financial_data)
            debate_history["debate_rounds"].append({
                "round": round_num + 1,
                "speaker": "bear",
                "content": bear_rebuttal
            })
            bear_view = bear_rebuttal
            print(f"    巴菲特（空头）：{bear_rebuttal[:100]}...")

        # 生成最终总结
        print("\n=== 生成最终总结 ===")
        final_summary = self._generate_final_summary(
            stock_name, stock_code, bull_analysis, bear_analysis, debate_history
        )
        debate_history["final_summary"] = final_summary

        # 保存报告
        if save_report:
            self._save_report(debate_history)
            print(f"\n报告已保存到: {self.output_dir}")

        return debate_history

    def _extract_summary(self, analysis: Dict[str, Any]) -> str:
        """提取分析摘要"""
        if "summary" in analysis and analysis["summary"]:
            return analysis["summary"]
        if "conclusion" in analysis and analysis["conclusion"]:
            return analysis["conclusion"]
        if "raw_response" in analysis:
            return analysis["raw_response"][:500]
        return str(analysis)

    def _generate_final_summary(
        self,
        stock_name: str,
        stock_code: str,
        bull_analysis: Dict[str, Any],
        bear_analysis: Dict[str, Any],
        debate_history: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成最终总结（含三维评分）"""
        system_prompt = """你是一位资深的投资分析师，需要综合看多和看空双方的观点，给出一个平衡、客观的投资建议。

你的任务是：
1. 总结双方的核心论点
2. 识别双方都认同的事实
3. 识别存在分歧的关键点
4. 基于双方观点给出综合判断
5. 提供投资建议（看多/看空/中性）及理由
6. 指出需要持续关注的关键指标或事件
7. **重要：综合双方的三维评分，给出平衡的维度评分**

你的结论应该是平衡、客观、有理有据的。"""

        bull_summary = self._extract_summary(bull_analysis)
        bear_summary = self._extract_summary(bear_analysis)

        # 收集辩论要点
        debate_points = []
        for round_data in debate_history.get("debate_rounds", []):
            speaker = "芒格（多头）" if round_data["speaker"] == "bull" else "巴菲特（空头）"
            content = round_data["content"]
            debate_points.append(f"{speaker}: {content[:300]}")

        user_prompt = f"""股票：{stock_name} ({stock_code})

请综合以下多空辩论，给出最终的投资分析报告：

=== 芒格（多头）观点 ===
{bull_summary}

关键看多点：
{chr(10).join(f"- {p}" for p in bull_analysis.get('key_bullish_points', []))}

芒格（多头）三维评分：
{self._format_dimension_scores(bull_analysis.get('dimension_scores', {}))}

=== 巴菲特（空头）观点 ===
{bear_summary}

关键看空点：
{chr(10).join(f"- {p}" for p in bear_analysis.get('key_bearish_points', []))}

巴菲特（空头）三维评分：
{self._format_dimension_scores(bear_analysis.get('dimension_scores', {}))}

=== 辩论过程 ===
{chr(10).join(debate_points)}

请以JSON格式返回综合分析：
{{
    "investment_rating": "强烈买入|买入|持有|卖出|强烈卖出",
    "confidence_level": "高|中|低",
    "key_agreements": [
        "双方共识1",
        "双方共识2"
    ],
    "key_disagreements": [
        "分歧点1",
        "分歧点2"
    ],
    "bullish_strengths": [
        "多头优势1",
        "多头优势2"
    ],
    "bearish_risks": [
        "空头风险1",
        "空头风险2"
    ],
    "key_watch_factors": [
        "需要关注因素1",
        "需要关注因素2"
    ],
    "comprehensive_conclusion": "综合结论（3-5段详细分析）",
    "dimension_scores": {{
        "company_quality": {{
            "score": 5.5,
            "reasoning": "综合双方观点，该公司商业模式稳健，现金流良好，但业务复杂度需关注",
            "sub_scores": {{
                "business_model": 6.0,
                "corporate_culture": 5.5,
                "understandability": 5.0
            }},
            "is_friend_of_time": true
        }},
        "trend": {{
            "score": 3.5,
            "reasoning": "行业景气度尚可，公司增长平稳，但催化剂不足",
            "sub_scores": {{
                "industry_trend": 4.0,
                "company_trend": 3.5,
                "sentiment_trend": 3.0
            }}
        }},
        "valuation": {{
            "score": -1.0,
            "reasoning": "估值偏高，缺乏足够安全边际",
            "sub_scores": {{
                "relative_valuation": -1.5,
                "absolute_valuation": -1.0,
                "safety_margin": -0.5
            }}
        }}
    }}
}}
"""

        response = self._call_llm(system_prompt, user_prompt)
        return self._parse_json_response(response)

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
                raise _Timeout("LLM API调用超时(120s)")

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
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                return {
                    "raw_response": response,
                    "investment_rating": "无法确定",
                    "comprehensive_conclusion": response
                }
        except json.JSONDecodeError as e:
            return {
                "raw_response": response,
                "investment_rating": "无法确定",
                "comprehensive_conclusion": response
            }

    def _save_report(self, debate_history: Dict[str, Any]) -> Path:
        """保存辩论报告，同一股票只保留最新一份"""
        stock_name = debate_history["stock_name"]
        stock_code = debate_history["stock_code"]
        if not stock_name or stock_name.strip() == "":
            stock_name = stock_code

        # 清理该股票的旧报告文件，避免重复累积
        code_suffix = stock_code.split(".")[0]
        patterns = [f"*_{code_suffix}_多空辩论报告.md", f"*_{code_suffix}_多空辩论报告.json",
                    f"*_{stock_code}_多空辩论报告.md", f"*_{stock_code}_多空辩论报告.json"]
        # HK stocks: also clean alternate code format (with/without leading zeros)
        if stock_code.endswith(".HK"):
            market = "HK"
            num = code_suffix
            alt_num = str(int(num))  # strips leading zeros
            alt_code = f"{alt_num}.{market}"
            if alt_code != stock_code:
                patterns.append(f"*_{alt_code}_多空辩论报告.md")
                patterns.append(f"*_{alt_code}_多空辩论报告.json")
        for pattern in patterns:
            for old_file in self.output_dir.rglob(pattern):
                try:
                    old_file.unlink()
                except OSError:
                    pass

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stock_name_safe = stock_name.replace(" ", "_").replace("/", "_")
        filename = f"{timestamp}_{stock_name_safe}_{stock_code}_多空辩论报告.md"
        filepath = self.output_dir / filename

        # 生成Markdown报告
        markdown_content = self._generate_markdown_report(debate_history)

        # 保存文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        # 同时保存JSON格式
        json_filename = filename.replace('.md', '.json')
        json_filepath = self.output_dir / json_filename
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(debate_history, f, ensure_ascii=False, indent=2)

        return filepath

    def _generate_markdown_report(self, debate_history: Dict[str, Any]) -> str:
        """生成Markdown格式报告"""
        lines = []

        # 确保股票名称不为空
        stock_name = debate_history["stock_name"]
        if not stock_name or stock_name.strip() == "":
            stock_name = debate_history["stock_code"]

        # 标题
        lines.append(f"# {stock_name} ({debate_history['stock_code']}) 巴菲特-芒格辩论报告")
        lines.append(f"\n**分析时间**: {debate_history['analysis_date']}")
        lines.append("\n---\n")

        # 初始分析
        lines.append("## 初始分析\n")
        lines.append("### 芒格（多头）观点\n")
        bull = debate_history["initial_analysis"]["bull"]
        lines.append(f"**核心观点**: {bull.get('summary', 'N/A')}\n")
        if bull.get('key_bullish_points'):
            lines.append("**关键看多点**:")
            for point in bull.get('key_bullish_points', []):
                lines.append(f"- {point}")
        if bull.get('financial_strengths'):
            lines.append("\n**财务优势**:")
            for strength in bull.get('financial_strengths', []):
                lines.append(f"- {strength}")

        lines.append("\n### 巴菲特（空头）观点\n")
        bear = debate_history["initial_analysis"]["bear"]
        lines.append(f"**核心观点**: {bear.get('summary', 'N/A')}\n")
        if bear.get('key_bearish_points'):
            lines.append("**关键看空点**:")
            for point in bear.get('key_bearish_points', []):
                lines.append(f"- {point}")
        if bear.get('risk_factors'):
            lines.append("\n**风险因素**:")
            for risk in bear.get('risk_factors', []):
                lines.append(f"- {risk}")

        # 辩论过程
        if debate_history.get("debate_rounds"):
            lines.append("\n---\n")
            lines.append("## 辩论过程\n")
            for round_data in debate_history["debate_rounds"]:
                speaker_name = "芒格（多头）" if round_data["speaker"] == "bull" else "巴菲特（空头）"
                lines.append(f"### 第{round_data['round']}轮 - {speaker_name}\n")
                lines.append(round_data["content"])
                lines.append("\n")

        # 最终总结
        if debate_history.get("final_summary"):
            lines.append("---\n")
            lines.append("## 综合分析\n")
            final = debate_history["final_summary"]

            lines.append(f"**投资评级**: {final.get('investment_rating', 'N/A')}")
            lines.append(f"**信心水平**: {final.get('confidence_level', 'N/A')}\n")

            if final.get('key_agreements'):
                lines.append("### 双方共识\n")
                for agreement in final.get('key_agreements', []):
                    lines.append(f"- {agreement}")
                lines.append("")

            if final.get('key_disagreements'):
                lines.append("### 关键分歧\n")
                for disagreement in final.get('key_disagreements', []):
                    lines.append(f"- {disagreement}")
                lines.append("")

            if final.get('bullish_strengths'):
                lines.append("### 多头优势\n")
                for strength in final.get('bullish_strengths', []):
                    lines.append(f"- {strength}")
                lines.append("")

            if final.get('bearish_risks'):
                lines.append("### 空头风险\n")
                for risk in final.get('bearish_risks', []):
                    lines.append(f"- {risk}")
                lines.append("")

            if final.get('key_watch_factors'):
                lines.append("### 需要关注的因素\n")
                for factor in final.get('key_watch_factors', []):
                    lines.append(f"- {factor}")
                lines.append("")

            if final.get('comprehensive_conclusion'):
                lines.append("### 综合结论\n")
                lines.append(final.get('comprehensive_conclusion'))

        lines.append("\n---\n")
        lines.append("*本报告由AI生成，仅供参考，不构成投资建议。*")

        return "\n".join(lines)

    def _format_dimension_scores(self, dimension_scores: Dict[str, Any]) -> str:
        """格式化三维评分信息"""
        if not dimension_scores:
            return "（三维评分信息缺失）"

        parts = []
        for dim_name, dim_data in dimension_scores.items():
            if isinstance(dim_data, dict) and "score" in dim_data:
                score = dim_data.get("score", 0)
                reasoning = dim_data.get("reasoning", "")
                dim_cn_names = {
                    "company_quality": "好公司评分",
                    "trend": "趋势评分",
                    "valuation": "估值评分"
                }
                dim_cn = dim_cn_names.get(dim_name, dim_name)
                parts.append(f"- {dim_cn}: {score:.1f}/10 - {reasoning}")

        return "\n".join(parts) if parts else "（三维评分信息格式错误）"

    def generate_master_report(
        self,
        stock_name: str,
        stock_code: str,
        debate_json: Dict[str, Any],
        financial_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成长篇大师报告：综合巴菲特镜子测试 + 芒格失败路径 + 格栅思维。

        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            financial_data: 财务数据
            debate_json: 已完成的辩论完整 JSON（从磁盘加载）

        Returns:
            大师报告 Markdown 文本
        """
        # 提取辩论关键信息
        bull_analysis = debate_json.get("initial_analysis", {}).get("bull", {})
        bear_analysis = debate_json.get("initial_analysis", {}).get("bear", {})
        final_summary = debate_json.get("final_summary", {})
        debate_rounds = debate_json.get("debate_rounds", [])

        # 整理辩论要点
        debate_summary_lines = []
        for rd in debate_rounds:
            speaker = "芒格（多头）" if rd.get("speaker") == "bull" else "巴菲特（空头）"
            content = rd.get("content", "")[:500]
            debate_summary_lines.append(f"### 第{rd.get('round', '?')}轮 - {speaker}\n\n{content}")

        debate_summary = "\n\n".join(debate_summary_lines)

        # 整理财务数据摘要
        fin_summary = self._format_financial_data_compact(financial_data) if financial_data else "（财务数据未提供，基于辩论内容生成）"

        system_prompt = """你是资深投资分析师，需要综合巴菲特（空头）和芒格（多头）的辩论，生成一份深度大师报告。

报告必须包含以下结构（恰好使用这些标题），基于辩论内容和财务数据，数据不足时标注「数据不足」而非臆造。"""

        user_prompt = f"""股票：{stock_name} ({stock_code})

请基于以下辩论和财务数据，生成一份深度大师报告。

=== 巴菲特（空头）初始分析 ===
{bull_analysis.get('summary', 'N/A') if isinstance(bull_analysis, dict) else 'N/A'}

=== 芒格（多头）初始分析 ===
{bear_analysis.get('summary', 'N/A') if isinstance(bear_analysis, dict) else 'N/A'}

=== 辩论过程 ===
{debate_summary}

=== 最终综合评分 ===
投资评级：{final_summary.get('investment_rating', 'N/A')}
信心水平：{final_summary.get('confidence_level', 'N/A')}
综合结论：{final_summary.get('comprehensive_conclusion', 'N/A')}

=== 财务数据摘要 ===
{fin_summary}

请按以下格式输出报告（Markdown）：

# {stock_name} ({stock_code}) 大师深度分析报告

## 1. 执行摘要
（3-5句话：这支股票的核心矛盾是什么，巴菲特和芒格最尖锐的分歧在哪里）

## 2. 巴菲特镜子测试五维
| 维度 | 评分(0-1) | 核心证据 | 判断 |
|---|---|---|---|
| 生意本质 | | | |
| 护城河 | | | |
| 管理层 | | | |
| 估值 | | | |
| 安全边际 | | | |
| **总分** | **/5** | | |

## 3. 芒格失败路径清单
| 失败路径 | 概率 | 影响程度 | 触发信号 |
|---|---|---|---|
| | | | |

## 4. 格栅思维交叉验证
（至少3个学科模型：微观经济学/博弈论/心理学/生态学，每个写明结论）

## 5. 关键分歧与共识
- 共识点：
- 分歧点：

## 6. 综合下注结论
（综合巴菲特的安全边际和芒格的失败路径分析，给出最终判断）
"""

        response = self._call_llm(system_prompt, user_prompt)
        return response

    def _format_financial_data_compact(self, data: Dict[str, Any]) -> str:
        """格式化财务数据为紧凑摘要（供大师报告使用）。"""
        parts = []
        for section, label in [
            ("income_statement", "利润表"),
            ("balance_sheet", "资产负债表"),
            ("cash_flow", "现金流量表"),
            ("key_metrics", "关键指标"),
        ]:
            if section in data and data[section]:
                parts.append(f"=== {label} ===")
                for key, value in data[section].items():
                    parts.append(f"  {key}: {value}")
        if data.get("business_overview"):
            parts.append(f"\n=== 业务概述 ===")
            parts.append(data["business_overview"][:500])
        return "\n".join(parts) if parts else "（财务数据缺失）"

