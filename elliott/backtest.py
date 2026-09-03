#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略回测框架
支持多日持仓、止盈止损模拟，生成回测报告（胜率、最大回撤、夏普比率）
"""

import os
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from core.data_fetcher import fetch_a_share_data, fetch_hk_data


@dataclass
class BacktestPosition:
    """回测持仓"""
    entry_date: str
    entry_price: float
    shares: int = 100  # 默认100股
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""  # "止盈"/"止损"/"到期"/"手动"
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    start_date: str
    end_date: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    avg_hold_days: float = 0.0
    positions: List[BacktestPosition] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


class BacktestEngine:
    """策略回测引擎"""

    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital

    def run_backtest(
        self,
        symbol: str,
        signal_func,
        start_date: str,
        end_date: str,
        source: str = "a",
        hold_days: int = 5,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.10,
    ) -> BacktestResult:
        """
        运行策略回测

        Args:
            symbol: 指数/股票代码
            signal_func: 信号生成函数，签名为 signal_func(df, idx) -> str
                返回 "buy"/"sell"/"hold"
            start_date: 回测开始日期
            end_date: 回测结束日期
            source: "a" (A股) 或 "hk" (港股)
            hold_days: 最大持仓天数
            stop_loss_pct: 止损比例 (如 0.05 = 5%)
            take_profit_pct: 止盈比例 (如 0.10 = 10%)

        Returns:
            BacktestResult
        """
        # 获取数据
        if source == "a":
            df = fetch_a_share_data(symbol)
        else:
            df = fetch_hk_data(symbol)

        if df.empty:
            return BacktestResult(symbol=symbol, start_date=start_date, end_date=end_date)

        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].reset_index(drop=True)

        if len(df) < 10:
            return BacktestResult(symbol=symbol, start_date=start_date, end_date=end_date)

        positions = []
        capital = self.initial_capital
        equity_curve = [capital]
        current_position = None

        for i in range(1, len(df)):
            row = df.iloc[i]
            date_str = row["date"].strftime("%Y-%m-%d")
            close = float(row["close"])

            # 如果有持仓，检查止损/止盈/到期
            if current_position is not None:
                current_position, capital, closed = self._check_exit(
                    current_position, close, date_str, capital, hold_days
                )
                if closed:
                    positions.append(current_position)
                    current_position = None

            # 如果没有持仓，检查买入信号
            if current_position is None:
                signal = signal_func(df, i)
                if signal == "buy":
                    # 指数/ETF可能面值较高，使用1手=1份（非100股）
                    shares = max(1, int(capital * 0.95 / close))
                    entry_cost = close * shares
                    current_position = BacktestPosition(
                        entry_date=date_str,
                        entry_price=close,
                        shares=shares,
                        stop_loss=close * (1 - stop_loss_pct),
                        take_profit=close * (1 + take_profit_pct),
                    )
                    capital -= entry_cost

            # 记录权益曲线
            if current_position:
                equity = capital + current_position.shares * close
            else:
                equity = capital
            equity_curve.append(equity)

        # 强制平仓
        if current_position is not None:
            last_close = float(df.iloc[-1]["close"])
            last_date = df.iloc[-1]["date"].strftime("%Y-%m-%d")
            current_position.exit_date = last_date
            current_position.exit_price = last_close
            current_position.exit_reason = "到期"
            current_position.pnl = (last_close - current_position.entry_price) * current_position.shares
            current_position.pnl_pct = (last_close / current_position.entry_price - 1) * 100
            capital += current_position.shares * last_close
            positions.append(current_position)

        # 计算回测指标
        return self._calculate_metrics(symbol, start_date, end_date, positions, equity_curve)

    def _check_exit(self, position: BacktestPosition, close: float,
                    date_str: str, capital: float, hold_days: int):
        """检查是否应该平仓"""
        closed = False

        # 止损
        if position.stop_loss and close <= position.stop_loss:
            position.exit_date = date_str
            position.exit_price = close
            position.exit_reason = "止损"
            position.pnl = (close - position.entry_price) * position.shares
            position.pnl_pct = (close / position.entry_price - 1) * 100
            capital += position.shares * close
            closed = True

        # 止盈
        elif position.take_profit and close >= position.take_profit:
            position.exit_date = date_str
            position.exit_price = close
            position.exit_reason = "止盈"
            position.pnl = (close - position.entry_price) * position.shares
            position.pnl_pct = (close / position.entry_price - 1) * 100
            capital += position.shares * close
            closed = True

        # 到期
        elif position.entry_date:
            entry_dt = datetime.strptime(position.entry_date, "%Y-%m-%d")
            current_dt = datetime.strptime(date_str, "%Y-%m-%d")
            if (current_dt - entry_dt).days >= hold_days:
                position.exit_date = date_str
                position.exit_price = close
                position.exit_reason = "到期"
                position.pnl = (close - position.entry_price) * position.shares
                position.pnl_pct = (close / position.entry_price - 1) * 100
                capital += position.shares * close
                closed = True

        return position, capital, closed

    def _calculate_metrics(self, symbol, start_date, end_date, positions, equity_curve):
        """计算回测指标"""
        result = BacktestResult(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            total_trades=len(positions),
            positions=positions,
            equity_curve=equity_curve,
        )

        if not positions:
            return result

        # 胜率
        winning = [p for p in positions if p.pnl > 0]
        losing = [p for p in positions if p.pnl <= 0]
        result.winning_trades = len(winning)
        result.losing_trades = len(losing)
        result.win_rate = len(winning) / len(positions) * 100 if positions else 0

        # 总盈亏
        result.total_pnl = sum(p.pnl for p in positions)
        result.total_pnl_pct = (equity_curve[-1] / self.initial_capital - 1) * 100 if equity_curve else 0

        # 最大回撤
        if equity_curve:
            peak = equity_curve[0]
            max_dd = 0
            for equity in equity_curve:
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
            result.max_drawdown_pct = max_dd * 100

        # 夏普比率 (假设无风险利率3%)
        if len(equity_curve) > 1:
            returns = np.diff(equity_curve) / equity_curve[:-1]
            if len(returns) > 0 and np.std(returns) > 0:
                risk_free_daily = 0.03 / 252
                result.sharpe_ratio = (np.mean(returns) - risk_free_daily) / np.std(returns) * np.sqrt(252)

        # 平均持仓天数
        hold_days_list = []
        for p in positions:
            if p.entry_date and p.exit_date:
                days = (datetime.strptime(p.exit_date, "%Y-%m-%d") -
                        datetime.strptime(p.entry_date, "%Y-%m-%d")).days
                hold_days_list.append(days)
        result.avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0

        return result

    @staticmethod
    def format_backtest_report(result: BacktestResult) -> str:
        """格式化回测报告为Markdown"""
        lines = []
        lines.append(f"# 回测报告: {result.symbol}")
        lines.append("")
        lines.append(f"> 回测期间: {result.start_date} ~ {result.end_date}")
        lines.append("")
        lines.append("## 📊 回测概要")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总交易次数 | {result.total_trades} |")
        lines.append(f"| 盈利次数 | {result.winning_trades} |")
        lines.append(f"| 亏损次数 | {result.losing_trades} |")
        lines.append(f"| 胜率 | {result.win_rate:.1f}% |")
        lines.append(f"| 总盈亏 | {result.total_pnl:+,.2f} ({result.total_pnl_pct:+.2f}%) |")
        lines.append(f"| 最大回撤 | {result.max_drawdown_pct:.2f}% |")
        lines.append(f"| 夏普比率 | {result.sharpe_ratio:.2f} |")
        lines.append(f"| 平均持仓天数 | {result.avg_hold_days:.1f} |")
        lines.append("")

        if result.positions:
            lines.append("## 📋 交易明细")
            lines.append("")
            for p in result.positions:
                icon = "🟢" if p.pnl > 0 else "🔴"
                lines.append(f"**{icon} {p.entry_date}** → {p.exit_date or '持仓中'} | "
                             f"买入: {p.entry_price:.2f} | 卖出: {p.exit_price:.2f if p.exit_price else 'N/A'} | "
                             f"盈亏: {p.pnl:+,.2f} ({p.pnl_pct:+.2f}%) | 原因: {p.exit_reason}")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# 内置信号策略
# ============================================================

def ma_cross_signal(df: pd.DataFrame, idx: int, short_window: int = 5, long_window: int = 20) -> str:
    """均线交叉信号策略"""
    if idx < long_window:
        return "hold"
    short_ma = df["close"].iloc[idx - short_window:idx + 1].mean()
    long_ma = df["close"].iloc[idx - long_window:idx + 1].mean()
    prev_short_ma = df["close"].iloc[idx - short_window - 1:idx].mean()
    prev_long_ma = df["close"].iloc[idx - long_window - 1:idx].mean()

    # 金叉买入
    if prev_short_ma <= prev_long_ma and short_ma > long_ma:
        return "buy"
    # 死叉卖出
    if prev_short_ma >= prev_long_ma and short_ma < long_ma:
        return "sell"
    return "hold"


def breakout_signal(df: pd.DataFrame, idx: int, window: int = 20) -> str:
    """突破信号策略: 价格突破N日最高价买入"""
    if idx < window:
        return "hold"
    high = df["close"].iloc[idx - window:idx].max()
    if df["close"].iloc[idx] > high:
        return "buy"
    return "hold"
