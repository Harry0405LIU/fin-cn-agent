#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
晨报聚合模块
将波浪预测+雪球热帖+股票日报合并为一条晨报推送
支持配置推送时段（避免非交易时间打扰）
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    ELLIOTT_REPORT_DIR, XUEQIU_HOT_DIR, VAULT_DIR,
    ELLIOTT_WEBHOOK_URL,
)
from core.wechat import WeChatPusher
from core.utils import load_json, save_json, is_trading_day
from core.trading_calendar import is_trading_day as calendar_is_trading_day


def collect_morning_brief(date_str=None):
    """
    收集各模块最新报告，生成晨报摘要

    Args:
        date_str: 日期字符串 "YYYY-MM-DD"，默认今天

    Returns:
        str: 晨报Markdown内容
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# ☀️ FinAgent 晨报 {date_str}")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据日期: {date_str}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # 1. 波浪预测摘要
    elliott_summary = _collect_elliott_summary(date_str)
    if elliott_summary:
        lines.append("## 📊 波浪预测")
        lines.append("")
        lines.append(elliott_summary)
        lines.append("")

    # 2. 雪球热帖摘要
    xueqiu_summary = _collect_xueqiu_summary(date_str)
    if xueqiu_summary:
        lines.append("## 🔥 雪球热帖")
        lines.append("")
        lines.append(xueqiu_summary)
        lines.append("")

    # 3. 系统状态
    lines.append("## 🔧 系统状态")
    lines.append("")
    lines.append(f"> 所有模块运行正常 | 交易日: {'是' if calendar_is_trading_day() else '否'}")
    lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("*FinAgent 晨报 | 自动生成*")

    return "\n".join(lines)


def _collect_elliott_summary(date_str):
    """收集波浪预测日报摘要"""
    report_path = os.path.join(ELLIOTT_REPORT_DIR, f"波浪预测日报_{date_str}.md")
    if not os.path.exists(report_path):
        # 尝试找最新的
        import glob
        reports = sorted(glob.glob(os.path.join(ELLIOTT_REPORT_DIR, "波浪预测日报_*.md")))
        if reports:
            report_path = reports[-1]
        else:
            return None

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取总览表
        summary_lines = []
        in_overview = False
        for line in content.split("\n"):
            if "指数总览" in line:
                in_overview = True
                continue
            if in_overview:
                if line.startswith("## ") or line.startswith("━━"):
                    break
                if line.strip() and not line.startswith("|------"):
                    summary_lines.append(line)

        if summary_lines:
            return "\n".join(summary_lines)
    except Exception:
        pass

    return None


def _collect_xueqiu_summary(date_str):
    """收集雪球热帖摘要"""
    import glob
    pattern = os.path.join(XUEQIU_HOT_DIR, "雪球热帖_*.md")
    files = sorted(glob.glob(pattern))
    if not files:
        return None

    # 取最新的一个文件
    latest = files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取关键段落（市场情绪 + 投资建议）
        summary_lines = []
        for line in content.split("\n"):
            if any(kw in line for kw in ["市场情绪", "投资建议", "热门话题", "行业板块"]):
                summary_lines.append(line)
            elif summary_lines and line.strip() and not line.startswith("#"):
                if len(summary_lines) < 15:
                    summary_lines.append(line)
                else:
                    break

        if summary_lines:
            return "\n".join(summary_lines[:15]) + "\n> ...(详见完整报告)"
    except Exception:
        pass

    return None


def should_push_now():
    """
    判断当前是否应该推送
    规则: 交易日的 8:30-9:30 和 15:00-16:00 推送
    非交易日不推送
    """
    if not is_trading_day():
        return False

    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # 早盘前推送: 8:30-9:30
    if hour == 8 and minute >= 30:
        return True
    if hour == 9 and minute <= 30:
        return True

    # 收盘后推送: 15:00-16:00
    if hour == 15:
        return True
    if hour == 16 and minute == 0:
        return True

    return False


def send_morning_brief(force=False):
    """
    发送晨报聚合推送

    Args:
        force: 强制发送，忽略时段检查
    """
    if not force and not should_push_now():
        print("当前不在推送时段，跳过（使用 --force 强制推送）")
        return False

    brief = collect_morning_brief()
    if not brief or len(brief) < 50:
        print("晨报内容为空，跳过推送")
        return False

    pusher = WeChatPusher(ELLIOTT_WEBHOOK_URL)
    success = pusher.split_and_send(brief)

    if success:
        print("晨报推送成功")
    else:
        print("晨报推送部分失败")

    return success


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FinAgent 晨报聚合推送")
    parser.add_argument("--force", action="store_true", help="强制推送，忽略时段检查")
    parser.add_argument("--preview", action="store_true", help="仅预览，不推送")
    args = parser.parse_args()

    if args.preview:
        brief = collect_morning_brief()
        print(brief)
    else:
        send_morning_brief(force=args.force)
