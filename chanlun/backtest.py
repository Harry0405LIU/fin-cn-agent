#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论回测模块

集成 core.backtest.Strategy 接口，支持对缠论买卖点信号进行历史回测。
"""

import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
from datetime import datetime

from core.backtest import Strategy, BacktestEngine, BacktestResult, Trade
from core.indicators import calculate_all_indicators, calculate_macd, calculate_ma
from chanlun.identify import chan_identify
from chanlun.divergence import calculate_stroke_macd_areas, detect_divergence, get_macd_columns
from chanlun.trading_points import identify_trading_points
from chanlun.structures import TradingPoint


class ChanTheoryStrategy(Strategy):
    """
    缠论策略 - 实现 core.backtest.Strategy 接口。

    在 on_data() 首次调用时预计算所有缠论信号，
    之后每次bar检查信号映射表以生成买卖信号。

    支持的信号类型:
    - use_type1: 第一类买卖点 (趋势背驰)
    - use_type2: 第二类买卖点 (回踩确认)
    - use_type3: 第三类买卖点 (中枢突破)
    """

    def __init__(
        self,
        name: str = "ChanTheory",
        use_type1: bool = True,
        use_type2: bool = True,
        use_type3: bool = True,
        signal_delay_bars: int = 1,
    ):
        super().__init__(name)
        self.use_type1 = use_type1
        self.use_type2 = use_type2
        self.use_type3 = use_type3
        self.signal_delay_bars = signal_delay_bars

        # 内部状态
        self._fitted: bool = False
        self._trading_points: List[TradingPoint] = []
        self._signal_map: Dict[str, List[TradingPoint]] = {}  # date_str -> [trading points]
        self._last_signal_action: Optional[str] = None

    def fit(self, df: pd.DataFrame):
        """
        预计算所有缠论信号。

        在回测循环开始前调用，一次计算所有历史信号。
        """
        if len(df) < 60:
            return

        # 计算指标
        df = calculate_ma(df.copy())
        df = calculate_macd(df)

        # 缠论识别
        df_merged, fractals, strokes, segments, pivots = chan_identify(df)

        # MACD面积
        df_merged = get_macd_columns(df, df_merged)
        strokes = calculate_stroke_macd_areas(df_merged, strokes)

        # 背驰
        divergences = detect_divergence(df_merged, pivots, strokes, segments)

        # 买卖点
        self._trading_points = identify_trading_points(
            df_merged, pivots, divergences, strokes, segments, fractals
        )

        # 构建信号映射表: date -> [trading points]
        self._signal_map = {}
        for tp in self._trading_points:
            if not self._should_use_point(tp):
                continue
            date_key = str(tp.date)[:10]
            if date_key not in self._signal_map:
                self._signal_map[date_key] = []
            self._signal_map[date_key].append(tp)

        self._fitted = True

    def _should_use_point(self, tp: TradingPoint) -> bool:
        """判断是否使用该类型的买卖点"""
        if tp.point_type == 1 and not self.use_type1:
            return False
        if tp.point_type == 2 and not self.use_type2:
            return False
        if tp.point_type == 3 and not self.use_type3:
            return False
        return True

    def on_data(
        self,
        df: pd.DataFrame,
        position: int,
        cash: float
    ) -> Optional[str]:
        """
        回测引擎每个bar调用的信号生成方法。

        Args:
            df: 当前bar的完整历史数据
            position: 当前持仓股数
            cash: 当前现金

        Returns:
            'buy', 'sell', 或 None
        """
        # 等到有足够数据时才预计算信号 (至少需要60根K线)
        if not self._fitted and len(df) >= 60:
            self.fit(df)
            return None

        if not self._fitted:
            return None

        # 用日期字符串查找信号（与fit()中构建的key格式一致）
        current_date = str(df['date'].iloc[-1])[:10]
        tps = self._signal_map.get(current_date, [])
        if not tps:
            return None

        # 优先处理最近的信号
        tp = tps[-1]

        if tp.action == 'buy' and position == 0:
            self._last_signal_action = 'buy'
            return 'buy'
        elif tp.action == 'sell' and position > 0:
            self._last_signal_action = 'sell'
            return 'sell'

        return None


def run_chan_backtest(
    df: pd.DataFrame,
    use_type1: bool = True,
    use_type2: bool = True,
    use_type3: bool = True,
    initial_capital: float = 100000.0,
) -> BacktestResult:
    """
    运行缠论回测的便捷函数。

    Args:
        df: OHLCV DataFrame
        use_type1: 是否使用一类买卖点
        use_type2: 是否使用二类买卖点
        use_type3: 是否使用三类买卖点
        initial_capital: 初始资金

    Returns:
        BacktestResult
    """
    engine = BacktestEngine(initial_capital=initial_capital)

    strategy = ChanTheoryStrategy(
        use_type1=use_type1,
        use_type2=use_type2,
        use_type3=use_type3,
    )

    # 在完整数据上预计算信号
    strategy.fit(df)

    return engine.run(df, strategy)


def format_chan_backtest_report(result: BacktestResult) -> str:
    """
    生成缠论回测的Markdown报告。

    Args:
        result: 回测结果

    Returns:
        Markdown格式的报告
    """
    lines = []
    lines.append("# 缠论策略回测报告")
    lines.append("")
    lines.append(f"**策略**: {result.strategy_name}")
    lines.append(f"**回测区间**: {result.start_date} ~ {result.end_date}")
    lines.append("")

    lines.append("## 收益指标")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 初始资金 | {result.initial_capital:,.2f} |")
    lines.append(f"| 最终资金 | {result.final_capital:,.2f} |")
    lines.append(f"| 总收益率 | {result.total_return:+.2%} |")
    lines.append(f"| 年化收益率 | {result.annual_return:+.2%} |")
    lines.append(f"| 最大回撤 | {result.max_drawdown:.2%} |")
    lines.append(f"| 夏普比率 | {result.sharpe_ratio:.2f} |")
    lines.append(f"| 交易次数 | {result.trade_count} |")
    lines.append(f"| 胜率 | {result.win_rate:.2%} |")
    lines.append("")

    if result.trades:
        lines.append("## 交易明细")
        lines.append("")
        lines.append("| # | 日期 | 操作 | 价格 | 股数 | 金额 |")
        lines.append("|---|------|------|------|------|------|")
        for i, trade in enumerate(result.trades):
            action = "买入" if trade.action == 'buy' else "卖出"
            lines.append(
                f"| {i+1} | {trade.date} | {action} | {trade.price:.2f} "
                f"| {trade.shares} | {trade.value:,.2f} |"
            )
        lines.append("")

    return "\n".join(lines)


def compare_chan_variants(
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
) -> pd.DataFrame:
    """
    对比不同缠论买卖点组合的回测效果。

    测试组合:
    - 仅一买/一卖
    - 仅二买/二卖
    - 仅三买/三卖
    - 全部买卖点
    - 一买+二买 (仅买点)
    - 一买+二买+三买 (仅买点)

    Args:
        df: OHLCV DataFrame
        initial_capital: 初始资金

    Returns:
        对比结果DataFrame
    """
    results = []

    variants = [
        ("缠论-仅一买卖", True, False, False),
        ("缠论-仅二买卖", False, True, False),
        ("缠论-仅三买卖", False, False, True),
        ("缠论-全部", True, True, True),
        ("缠论-一买+二买(仅买点)", True, True, False),
        ("缠论-一二三买(仅买点)", True, True, True),
    ]

    for name, use1, use2, use3 in variants:
        strategy = ChanTheoryStrategy(
            name=name,
            use_type1=use1,
            use_type2=use2,
            use_type3=use3,
        )
        strategy.fit(df)  # 在完整数据上预计算信号
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run(df, strategy)
        results.append({
            '策略': result.strategy_name,
            '总收益': f"{result.total_return:+.2%}",
            '年化收益': f"{result.annual_return:+.2%}",
            '最大回撤': f"{result.max_drawdown:.2%}",
            '夏普比率': f"{result.sharpe_ratio:.2f}",
            '交易次数': result.trade_count,
            '胜率': f"{result.win_rate:.2%}",
            '最终资金': f"{result.final_capital:,.2f}",
        })

    return pd.DataFrame(results)
