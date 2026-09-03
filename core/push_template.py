#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一推送模板
设计统一的 FinAgent 推送模板：标题栏+概要+详情+操作建议
"""

from datetime import datetime


class PushTemplate:
    """FinAgent 统一推送模板"""

    @staticmethod
    def format(title: str, summary: str, details: str, advice: str = "",
               module: str = "", urgency: str = "normal") -> str:
        """
        生成统一的推送消息

        Args:
            title: 标题
            summary: 概要（1-3句话）
            details: 详情内容（Markdown格式）
            advice: 操作建议
            module: 来源模块标识
            urgency: 紧急程度 "normal"/"important"/"urgent"
        """
        urgency_icons = {
            "normal": "📋",
            "important": "⚠️",
            "urgent": "🚨",
        }
        icon = urgency_icons.get(urgency, "📋")

        lines = []
        # 标题栏
        module_tag = f"[{module}]" if module else ""
        lines.append(f"**{icon} {module_tag} {title}**")
        lines.append(f"> {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

        # 概要
        lines.append(f"> {summary}")
        lines.append("")

        # 详情
        lines.append("---")
        lines.append("")
        lines.append(details)
        lines.append("")

        # 操作建议
        if advice:
            lines.append("---")
            lines.append("")
            lines.append(f"💡 **操作建议**: {advice}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_elliott_daily(data_date, summary_text, details_text) -> str:
        """格式化波浪预测日报推送"""
        return PushTemplate.format(
            title=f"波浪预测日报 {data_date}",
            summary=summary_text,
            details=details_text,
            advice="仅供参考，不构成投资建议",
            module="Elliott",
            urgency="normal",
        )

    @staticmethod
    def format_xueqiu_hot(date_text, summary_text, details_text) -> str:
        """格式化雪球热帖推送"""
        return PushTemplate.format(
            title=f"雪球热帖 {date_text}",
            summary=summary_text,
            details=details_text,
            advice="关注市场情绪变化",
            module="Xueqiu",
            urgency="normal",
        )

    @staticmethod
    def format_signal_alert(index_name, signal_type, details_text) -> str:
        """格式化信号告警推送"""
        return PushTemplate.format(
            title=f"{index_name} {signal_type}信号触发",
            summary=f"{index_name} 出现重要{signal_type}信号",
            details=details_text,
            advice="请及时关注后续走势",
            module="Elliott",
            urgency="important",
        )

    @staticmethod
    def format_backtest_report(symbol, win_rate, pnl_pct, sharpe) -> str:
        """格式化回测报告推送"""
        return PushTemplate.format(
            title=f"回测报告 {symbol}",
            summary=f"胜率 {win_rate:.1f}% | 收益 {pnl_pct:+.2f}% | 夏普 {sharpe:.2f}",
            details="详见回测报告",
            advice="策略仅供参考",
            module="Backtest",
            urgency="normal",
        )
