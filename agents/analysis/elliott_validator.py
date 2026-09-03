#!/usr/bin/env python3
"""
艾略特波浪验证器

对任意波浪分析结果执行完整的规则检查，生成ValidationReport。
可用于：
1. 日线ETF分析结果验证 (analyze_etf输出)
2. 日线指数场景分析验证
3. 每日选股报告中波浪划线的质量审查

用法：
    from .elliott_validator import ElliottWaveValidator

    validator = ElliottWaveValidator()
    report = validator.validate(wave_result, current_price=xxx)
    if report.has_iron_violations:
        print(f"波浪标注存在铁律违反: {report.summary}")
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

import pandas as pd

from .elliott_rules import (
    WaveStructure,
    WavePoint,
    WaveSegment,
    RuleViolation,
    ValidationReport,
    Severity,
    RuleCategory,
    extract_wave_structure,
    classify_pattern,
    IRON_RULES,
    GUIDELINES,
    SOFT_GUIDES,
    ALL_RULES_INFO,
    _compute_segments,
)


class ElliottWaveValidator:
    """
    艾略特波浪验证器

    验证流程：
    1. 从波浪分析结果中提取标准 WaveStructure
    2. 依次执行：铁律 → 强指导 → 弱指导 → 形态识别
    3. 计算质量评分 (0-100)
    4. 生成验证报告
    """

    def __init__(self, strict: bool = False):
        """
        Args:
            strict: 若为True，则任何强指导违反都会使quality_score扣更多分
        """
        self.strict = strict

    def validate(
        self,
        wave_result: dict,
        current_price: float = 0.0,
        price_data: Optional[pd.DataFrame] = None,
    ) -> ValidationReport:
        """
        验证波浪分析结果

        Args:
            wave_result: 波浪分析结果dict (来自analyze_etf、_label_waves等)
            current_price: 当前价格 (从wave_result中推断，或手动指定)
            price_data: 原始价格数据 (可选，用于更精确的检查)

        Returns:
            ValidationReport 验证报告
        """
        # Step 1: 提取标准化波浪结构
        ws = extract_wave_structure(wave_result, current_price)

        # 如果无法提取有效结构，返回空报告
        if not ws.wave_points:
            return ValidationReport(
                source="empty",
                timestamp=datetime.now().isoformat(),
                quality_score=0,
                summary="无法从输入中提取波浪结构，无法验证",
            )

        # Step 2: 执行铁律检查
        iron_violations = []
        for rule_id, check_fn in IRON_RULES:
            try:
                violation = check_fn(ws)
                if violation:
                    iron_violations.append(violation)
            except Exception as e:
                iron_violations.append(RuleViolation(
                    rule_id=rule_id,
                    category=RuleCategory.IRON,
                    severity=Severity.ERROR,
                    description=f"规则检查异常: {e}",
                ))

        # Step 3: 执行强指导检查
        guideline_violations = []
        for rule_id, check_fn in GUIDELINES:
            try:
                violation = check_fn(ws)
                if violation:
                    guideline_violations.append(violation)
            except Exception:
                pass  # 指导检查失败不阻塞

        # Step 4: 执行弱指导检查
        soft_violations = []
        for rule_id, check_fn in SOFT_GUIDES:
            try:
                violation = check_fn(ws)
                if violation:
                    soft_violations.append(violation)
            except Exception:
                pass

        # Step 5: 形态识别
        pattern_assessment = classify_pattern(ws)

        # Step 6: 计算质量评分
        quality_score = self._compute_quality(
            ws, iron_violations, guideline_violations, soft_violations
        )

        # Step 7: 生成摘要
        summary = self._build_summary(
            iron_violations, guideline_violations, soft_violations,
            pattern_assessment, quality_score
        )

        # Build report
        position = wave_result.get("position", wave_result.get("wave_position", ""))
        source = f"wave:{position}" if position else "wave_analysis"

        report = ValidationReport(
            source=source,
            timestamp=datetime.now().isoformat(),
            iron_rule_violations=iron_violations,
            guideline_violations=guideline_violations,
            soft_guide_violations=soft_violations,
            pattern_assessment=pattern_assessment,
            quality_score=quality_score,
            summary=summary,
        )

        return report

    def validate_batch(
        self,
        results: List[dict],
        prices: Optional[List[float]] = None,
    ) -> List[ValidationReport]:
        """批量验证多个波浪分析结果"""
        reports = []
        for i, result in enumerate(results):
            cp = prices[i] if prices and i < len(prices) else 0.0
            reports.append(self.validate(result, current_price=cp))
        return reports

    def _compute_quality(
        self,
        ws: WaveStructure,
        iron_violations: List[RuleViolation],
        guideline_violations: List[RuleViolation],
        soft_violations: List[RuleViolation],
    ) -> int:
        """
        计算浪型质量评分 (0-100)

        基准100分：
        - 每个铁律违反: -30
        - 每个强指导违反: -10 (strict模式下 -15)
        - 每个弱指导违反: -3 (strict模式下 -5)
        - 结构不完整: -20
        - 最低分: 0
        """
        score = 100

        # 铁律
        score -= len(iron_violations) * 30

        # 强指导
        guide_penalty = 15 if self.strict else 10
        score -= len(guideline_violations) * guide_penalty

        # 弱指导
        soft_penalty = 5 if self.strict else 3
        score -= len(soft_violations) * soft_penalty

        # 结构完整性
        if ws.num_impulse < 1:
            score -= 20
        elif ws.num_impulse < 2:
            score -= 10

        if not ws.wave_points:
            score -= 30

        return max(0, min(100, score))

    def _build_summary(
        self,
        iron_violations: List[RuleViolation],
        guideline_violations: List[RuleViolation],
        soft_violations: List[RuleViolation],
        pattern: Dict[str, Any],
        quality_score: int,
    ) -> str:
        """生成可读的验证摘要"""
        parts = []

        if iron_violations:
            iron_rules = [v.rule_id for v in iron_violations]
            parts.append(f"铁律违反: {', '.join(iron_rules)}")
        else:
            parts.append("铁律通过")

        if guideline_violations:
            guide_rules = [v.rule_id for v in guideline_violations]
            parts.append(f"指导违反({len(guideline_violations)}项): {', '.join(guide_rules)}")
        else:
            parts.append("强指导通过")

        if soft_violations:
            soft_rules = [v.rule_id for v in soft_violations]
            parts.append(f"弱指导提示({len(soft_violations)}项)")

        pattern_name = pattern.get("pattern", "unknown")
        confidence = pattern.get("confidence", 0)
        parts.append(f"形态: {pattern_name}({confidence:.0%})")

        parts.append(f"质量评分: {quality_score}/100")

        return " | ".join(parts)

    @staticmethod
    def report_to_markdown(report: ValidationReport, title: str = "波浪验证报告") -> str:
        """将验证报告转为Markdown格式（用于嵌入每日报告）"""
        lines = [
            f"### 🔍 {title}",
            "",
            f"**质量评分**: `{report.quality_score}/100`",
            f"**摘要**: {report.summary}",
            "",
        ]

        if report.iron_rule_violations:
            lines.append("#### ❌ 铁律违反")
            lines.append("| 规则 | 描述 | 详情 |")
            lines.append("|------|------|------|")
            for v in report.iron_rule_violations:
                lines.append(f"| {v.rule_id} | {v.description} | {v.detail} |")
            lines.append("")

        if report.guideline_violations:
            lines.append("#### ⚠️ 强指导违反")
            lines.append("| 规则 | 描述 | 详情 |")
            lines.append("|------|------|------|")
            for v in report.guideline_violations:
                lines.append(f"| {v.rule_id} | {v.description} | {v.detail} |")
            lines.append("")

        if report.soft_guide_violations:
            lines.append("#### ℹ️ 弱指导提示")
            lines.append("| 规则 | 描述 |")
            lines.append("|------|------|")
            for v in report.soft_guide_violations:
                lines.append(f"| {v.rule_id} | {v.description} |")
            lines.append("")

        if report.pattern_assessment:
            pa = report.pattern_assessment
            lines.append(f"#### 形态评估")
            lines.append(f"- **识别形态**: {pa.get('pattern', 'N/A')}")
            lines.append(f"- **置信度**: {pa.get('confidence', 0):.0%}")
            if pa.get("notes"):
                for note in pa["notes"]:
                    lines.append(f"- {note}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def report_to_compact_str(report: ValidationReport) -> str:
        """紧凑的单行验证字符串（用于列表展示）"""
        parts = []
        if report.has_iron_violations:
            ids = ",".join(v.rule_id for v in report.iron_rule_violations)
            parts.append(f"❌{ids}")
        else:
            parts.append("✅铁律OK")

        if report.has_guideline_violations:
            parts.append(f"⚠️{len(report.guideline_violations)}项指导违反")

        parts.append(f"质量:{report.quality_score}")

        return " ".join(parts)


class BatchReportValidator:
    """
    批量报告验证器 — 对每日选股报告中的所有波浪分析进行验证

    用法：
        validator = BatchReportValidator()
        summary = validator.validate_daily_picks(picks_list)
        print(summary)
    """

    def __init__(self, strict: bool = False):
        self.validator = ElliottWaveValidator(strict=strict)
        self.reports: List[ValidationReport] = []

    def validate_daily_picks(
        self,
        picks: List[dict],
        etf_analyses: Optional[Dict[str, dict]] = None,
    ) -> Dict[str, Any]:
        """
        验证每日选股中的所有波浪分析

        Args:
            picks: 每日选股结果列表 (daily_selection的输出)
            etf_analyses: {etf_code: analyze_etf结果} 字典 (可选)

        Returns:
            批量验证汇总
        """
        self.reports = []
        iron_violation_count = 0
        low_quality_count = 0

        for pick in picks:
            etf_code = pick.get("etf_code", pick.get("stock_code", ""))
            etf_name = pick.get("etf_name", pick.get("stock_name", ""))

            # 从pick中提取波浪分析
            wave_analysis = pick.get("elliott_analysis", {})
            if not wave_analysis and etf_analyses:
                wave_analysis = etf_analyses.get(etf_code, {})

            if not wave_analysis or not isinstance(wave_analysis, dict):
                continue

            current_price = pick.get("close", pick.get("last_price", 0))
            report = self.validator.validate(wave_analysis, current_price=current_price)

            # 添加标识信息
            report.source = f"{etf_code}({etf_name})"
            self.reports.append(report)

            if report.has_iron_violations:
                iron_violation_count += 1
            if report.quality_score < 60:
                low_quality_count += 1

        total = len(self.reports)
        return {
            "total_validated": total,
            "iron_violation_count": iron_violation_count,
            "low_quality_count": low_quality_count,
            "avg_quality_score": (
                sum(r.quality_score for r in self.reports) / total if total > 0 else 0
            ),
            "reports": self.reports,
        }

    def generate_summary_markdown(self, batch_summary: Dict[str, Any]) -> str:
        """生成批量验证汇总的Markdown"""
        lines = [
            "## 📊 波浪质量审核",
            "",
            f"- 验证标的数: **{batch_summary['total_validated']}**",
            f"- 铁律违反数: **{batch_summary['iron_violation_count']}**",
            f"- 低质量(<60分): **{batch_summary['low_quality_count']}**",
            f"- 平均质量分: **{batch_summary['avg_quality_score']:.1f}/100**",
            "",
        ]

        if batch_summary['iron_violation_count'] > 0:
            lines.append("### ⚠️ 存在铁律违反的标的")
            lines.append("| 标的 | 质量分 | 铁律违反 | 详情 |")
            lines.append("|------|--------|----------|------|")
            for r in batch_summary['reports']:
                if r.has_iron_violations:
                    violations_str = "; ".join(
                        f"{v.rule_id}: {v.description}" for v in r.iron_rule_violations
                    )
                    lines.append(
                        f"| {r.source} | {r.quality_score} | "
                        f"{len(r.iron_rule_violations)}项 | {violations_str} |"
                    )
            lines.append("")

        if batch_summary['low_quality_count'] > 0:
            lines.append("### ⚡ 低质量波浪标注(<60分)")
            lines.append("| 标的 | 质量分 | 主要问题 |")
            lines.append("|------|--------|----------|")
            for r in batch_summary['reports']:
                if r.quality_score < 60:
                    issues = []
                    if r.has_iron_violations:
                        issues.extend(v.rule_id for v in r.iron_rule_violations)
                    if r.has_guideline_violations:
                        issues.extend(v.rule_id for v in r.guideline_violations[:3])
                    issues_str = ", ".join(issues) if issues else "多个弱指导提示"
                    lines.append(f"| {r.source} | {r.quality_score} | {issues_str} |")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# 便捷函数
# ============================================================

def validate_wave_count(
    wave_result: dict,
    current_price: float = 0.0,
) -> ValidationReport:
    """便捷函数：验证单个波浪分析结果"""
    validator = ElliottWaveValidator()
    return validator.validate(wave_result, current_price=current_price)


def validate_daily_picks(
    picks: List[dict],
    etf_analyses: Optional[Dict[str, dict]] = None,
) -> Dict[str, Any]:
    """便捷函数：批量验证每日选股结果"""
    batch = BatchReportValidator()
    return batch.validate_daily_picks(picks, etf_analyses)
