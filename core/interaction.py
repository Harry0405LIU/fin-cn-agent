#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双向交互模块
支持通过企业微信回调接收指令并执行
指令: /force, /status, /analyze <股票代码>
"""

import os
import sys
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATA_DIR


# 指令注册表
_COMMANDS: Dict[str, dict] = {}


def register_command(name: str, description: str, handler: Callable):
    """
    注册指令处理器

    Args:
        name: 指令名 (如 "/status")
        description: 指令描述
        handler: 处理函数，签名为 handler(args: str) -> str
    """
    _COMMANDS[name] = {
        "description": description,
        "handler": handler,
    }


def get_registered_commands() -> Dict[str, dict]:
    """获取所有已注册指令"""
    return _COMMANDS.copy()


def execute_command(command_text: str) -> str:
    """
    执行指令

    Args:
        command_text: 完整指令文本 (如 "/status" 或 "/analyze 600519")

    Returns:
        str: 执行结果文本
    """
    parts = command_text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd not in _COMMANDS:
        return f"未知指令: {cmd}\n可用指令: {', '.join(_COMMANDS.keys())}"

    try:
        result = _COMMANDS[cmd]["handler"](args)
        return result
    except Exception as e:
        return f"指令执行失败: {e}"


# ============================================================
# 内置指令
# ============================================================

def _cmd_force(args: str) -> str:
    """强制运行Elliott日报"""
    from core.morning_brief import send_morning_brief
    success = send_morning_brief(force=True)
    return "晨报推送已触发" if success else "晨报推送失败"


def _cmd_status(args: str) -> str:
    """查看系统状态"""
    lines = []
    lines.append(f"**FinAgent 系统状态**")
    lines.append(f"> {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 数据缓存
    from core.data_cache import get_cache_info
    cache_info = get_cache_info()
    lines.append(f"📊 数据缓存: {cache_info['files']}个文件, {cache_info['total_size_mb']}MB")

    # Elliott状态
    from elliott.signals import load_state
    state = load_state()
    active_signals = sum(1 for v in state.values() if v.get("confirmed"))
    lines.append(f"🌊 Elliott信号: {len(state)}个跟踪中, {active_signals}个已确认")

    # 交易日历
    from core.trading_calendar import is_trading_day
    lines.append(f"📅 今日交易日: {'是' if is_trading_day() else '否'}")

    # 最近报告
    from config.settings import ELLIOTT_REPORT_DIR
    import glob
    reports = sorted(glob.glob(os.path.join(ELLIOTT_REPORT_DIR, "波浪预测日报_*.md")))
    if reports:
        latest = os.path.basename(reports[-1])
        lines.append(f"📄 最新报告: {latest}")

    return "\n".join(lines)


def _cmd_analyze(args: str) -> str:
    """分析指定股票/指数"""
    if not args.strip():
        return "请指定股票代码，如: /analyze 600519"

    code = args.strip()
    lines = []
    lines.append(f"**分析 {code}**")
    lines.append("")

    try:
        # 尝试获取数据
        if code.startswith("sh") or code.startswith("sz") or code.startswith("HSI") or code.startswith("HSTECH"):
            source = "a" if code.startswith(("sh", "sz")) else "hk"
            from core.data_fetcher import fetch_a_share_data, fetch_hk_data
            if source == "a":
                df = fetch_a_share_data(code)
            else:
                df = fetch_hk_data(code)

            if df.empty:
                return f"无法获取 {code} 数据"

            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else last
            close = float(last["close"])
            prev_close = float(prev["close"])
            change = (close - prev_close) / prev_close * 100

            lines.append(f"最新收盘: {close:,.2f}")
            lines.append(f"涨跌幅: {change:+.2f}%")

            # 简单技术指标
            if len(df) >= 20:
                ma5 = df["close"].tail(5).mean()
                ma20 = df["close"].tail(20).mean()
                lines.append(f"MA5: {ma5:,.2f} | MA20: {ma20:,.2f}")
                if close > ma5 > ma20:
                    lines.append("趋势: 🟢 多头排列")
                elif close < ma5 < ma20:
                    lines.append("趋势: 🔴 空头排列")
                else:
                    lines.append("趋势: 🟡 震荡")
        else:
            return f"不支持的代码格式: {code}，请使用 sh000001 / sz399001 / HSI 等格式"
    except Exception as e:
        lines.append(f"分析失败: {e}")

    return "\n".join(lines)


def _cmd_help(args: str) -> str:
    """显示帮助"""
    lines = ["**FinAgent 指令列表**", ""]
    for cmd, info in _COMMANDS.items():
        lines.append(f"- `{cmd}` - {info['description']}")
    return "\n".join(lines)


def _cmd_backtest(args: str) -> str:
    """运行回测"""
    if not args.strip():
        return "请指定代码，如: /backtest sh000001"

    code = args.strip()
    try:
        from elliott.backtest import BacktestEngine, ma_cross_signal
        engine = BacktestEngine()
        source = "hk" if code.startswith(("HSI", "HSTECH")) else "a"
        result = engine.run_backtest(
            symbol=code,
            signal_func=ma_cross_signal,
            start_date="2025-01-01",
            end_date=datetime.now().strftime("%Y-%m-%d"),
            source=source,
            hold_days=5,
            stop_loss_pct=0.03,
            take_profit_pct=0.05,
        )
        return (f"**回测结果 {code}**\n"
                f"交易次数: {result.total_trades}\n"
                f"胜率: {result.win_rate:.1f}%\n"
                f"收益: {result.total_pnl_pct:+.2f}%\n"
                f"最大回撤: {result.max_drawdown_pct:.2f}%\n"
                f"夏普比率: {result.sharpe_ratio:.2f}")
    except Exception as e:
        return f"回测失败: {e}"


# 注册内置指令
register_command("/force", "强制运行晨报推送", _cmd_force)
register_command("/status", "查看系统状态", _cmd_status)
register_command("/analyze", "分析指定股票/指数 (如 /analyze sh000001)", _cmd_analyze)
register_command("/backtest", "运行回测 (如 /backtest sh000001)", _cmd_backtest)
register_command("/help", "显示帮助", _cmd_help)


# ============================================================
# Webhook 回调服务器（可选，用于接收企业微信回调）
# ============================================================

class CommandHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器，处理企业微信回调"""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
            # 企业微信回调格式
            content = data.get("Content", data.get("text", {}).get("content", ""))
            if content.startswith("/"):
                result = execute_command(content)
            else:
                result = "请使用 / 开头的指令，如 /help"
        except Exception as e:
            result = f"处理失败: {e}"

        response = json.dumps({
            "msgtype": "text",
            "text": {"content": result}
        }, ensure_ascii=False)

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(response.encode("utf-8"))

    def log_message(self, format, *args):
        print(f"[CommandServer] {args[0]}")


def start_command_server(port=8199):
    """启动指令回调服务器"""
    server = HTTPServer(("0.0.0.0", port), CommandHandler)
    print(f"FinAgent 指令服务器启动在端口 {port}")
    print(f"可用指令: {', '.join(_COMMANDS.keys())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n指令服务器已停止")
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FinAgent 双向交互服务")
    parser.add_argument("--server", action="store_true", help="启动回调服务器")
    parser.add_argument("--port", type=int, default=8199, help="服务器端口")
    parser.add_argument("--cmd", type=str, help="直接执行指令")
    args = parser.parse_args()

    if args.cmd:
        print(execute_command(args.cmd))
    elif args.server:
        start_command_server(args.port)
    else:
        print("使用 --server 启动回调服务器，或 --cmd 执行指令")
        print(f"可用指令: {', '.join(_COMMANDS.keys())}")
