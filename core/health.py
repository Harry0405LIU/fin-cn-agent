#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康检查与告警模块
心跳检测、自动检查 launchd 任务、数据新鲜度、异常告警
"""

import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    DATA_DIR, ELLIOTT_REPORT_DIR, ELLIOTT_STATE_FILE,
    XUEQIU_PUSH_STATE_FILE, CRAWLER_STATE_FILE, POST_STATE_FILE,
)
from core.utils import load_json
from core.logger import get_logger

logger = get_logger("health")

# 心跳文件
HEARTBEAT_FILE = os.path.join(DATA_DIR, "heartbeat.json")
HEALTH_REPORT_FILE = os.path.join(DATA_DIR, "health_report.json")


def write_heartbeat(module_name: str):
    """记录模块心跳"""
    heartbeats = load_json(HEARTBEAT_FILE, default={})
    heartbeats[module_name] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    from core.utils import save_json
    save_json(HEARTBEAT_FILE, heartbeats)


def check_heartbeat(max_idle_hours: int = 48) -> list:
    """
    检查各模块心跳，返回超时模块列表

    Args:
        max_idle_hours: 最大空闲时间(小时)，超过此时间视为异常
    """
    heartbeats = load_json(HEARTBEAT_FILE, default={})
    alerts = []
    cutoff = datetime.now() - timedelta(hours=max_idle_hours)

    for module, last_time_str in heartbeats.items():
        try:
            last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
            if last_time < cutoff:
                hours_idle = (datetime.now() - last_time).total_seconds() / 3600
                alerts.append({
                    "module": module,
                    "last_heartbeat": last_time_str,
                    "hours_idle": round(hours_idle, 1),
                    "severity": "warning" if hours_idle < max_idle_hours * 2 else "critical",
                })
        except ValueError:
            pass

    return alerts


def check_data_freshness() -> list:
    """
    检查数据新鲜度
    返回数据过期的模块列表
    """
    alerts = []
    now = datetime.now()

    # Elliott 数据
    elliott_state = load_json(ELLIOTT_STATE_FILE, default={})
    if elliott_state:
        dates = [v.get("date", "") for v in elliott_state.values() if isinstance(v, dict)]
        if dates:
            latest = max(dates)
            try:
                latest_dt = datetime.strptime(latest, "%Y-%m-%d")
                if (now - latest_dt).days > 3:
                    alerts.append({
                        "module": "elliott",
                        "issue": f"Elliott数据已过期{latest}",
                        "latest_date": latest,
                        "days_stale": (now - latest_dt).days,
                    })
            except ValueError:
                pass

    # 最近报告
    import glob
    reports = sorted(glob.glob(os.path.join(ELLIOTT_REPORT_DIR, "波浪预测日报_*.md")))
    if reports:
        latest_report = os.path.basename(reports[-1])
        try:
            date_part = latest_report.replace("波浪预测日报_", "").replace(".md", "")
            report_dt = datetime.strptime(date_part, "%Y-%m-%d")
            if (now - report_dt).days > 3:
                alerts.append({
                    "module": "elliott_report",
                    "issue": f"最新报告日期{date_part}已超过3天",
                    "days_stale": (now - report_dt).days,
                })
        except ValueError:
            pass

    return alerts


def check_launchd_status() -> list:
    """
    检查 launchd 定时任务是否正常加载
    """
    alerts = []
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")

    expected_plists = [
        "com.elliott.dailyupdate.plist",
        "com.stock.report.plist",
    ]

    for plist_name in expected_plists:
        plist_path = os.path.join(plist_dir, plist_name)
        if not os.path.exists(plist_path):
            alerts.append({
                "module": "launchd",
                "issue": f"{plist_name} 未安装",
                "severity": "warning",
            })

    return alerts


def run_full_health_check() -> dict:
    """
    执行完整健康检查

    Returns:
        dict: {
            "status": "healthy"/"warning"/"critical",
            "timestamp": str,
            "heartbeat_alerts": list,
            "data_freshness_alerts": list,
            "launchd_alerts": list,
            "system_info": dict,
        }
    """
    heartbeat_alerts = check_heartbeat()
    data_alerts = check_data_freshness()
    launchd_alerts = check_launchd_status()

    # 判断整体状态
    all_alerts = heartbeat_alerts + data_alerts + launchd_alerts
    if any(a.get("severity") == "critical" for a in all_alerts):
        status = "critical"
    elif all_alerts:
        status = "warning"
    else:
        status = "healthy"

    # 系统信息
    from core.data_cache import get_cache_info
    cache_info = get_cache_info()
    from core.logger import get_log_stats
    log_stats = get_log_stats()

    report = {
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "heartbeat_alerts": heartbeat_alerts,
        "data_freshness_alerts": data_alerts,
        "launchd_alerts": launchd_alerts,
        "system_info": {
            "cache": cache_info,
            "logs": log_stats,
        },
    }

    # 保存报告
    from core.utils import save_json
    save_json(HEALTH_REPORT_FILE, report)

    return report


def format_health_report(report: dict) -> str:
    """格式化健康报告为Markdown"""
    status_icons = {
        "healthy": "🟢",
        "warning": "🟡",
        "critical": "🔴",
    }
    icon = status_icons.get(report["status"], "⚪")

    lines = []
    lines.append(f"**{icon} FinAgent 健康状态: {report['status'].upper()}**")
    lines.append(f"> 检查时间: {report['timestamp']}")
    lines.append("")

    if report["heartbeat_alerts"]:
        lines.append("**⚠️ 心跳告警**")
        for a in report["heartbeat_alerts"]:
            lines.append(f"- {a['module']}: 空闲{a['hours_idle']}小时 ({a['severity']})")
        lines.append("")

    if report["data_freshness_alerts"]:
        lines.append("**⚠️ 数据过期**")
        for a in report["data_freshness_alerts"]:
            lines.append(f"- {a['module']}: {a['issue']}")
        lines.append("")

    if report["launchd_alerts"]:
        lines.append("**⚠️ 定时任务**")
        for a in report["launchd_alerts"]:
            lines.append(f"- {a['issue']}")
        lines.append("")

    if not report["heartbeat_alerts"] and not report["data_freshness_alerts"] and not report["launchd_alerts"]:
        lines.append("✅ 所有模块运行正常")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FinAgent 健康检查")
    parser.add_argument("--check", action="store_true", help="执行健康检查")
    parser.add_argument("--heartbeat", type=str, help="记录模块心跳")
    args = parser.parse_args()

    if args.heartbeat:
        write_heartbeat(args.heartbeat)
        print(f"心跳已记录: {args.heartbeat}")
    elif args.check:
        report = run_full_health_check()
        print(format_health_report(report))
    else:
        report = run_full_health_check()
        print(format_health_report(report))
