#!/usr/bin/env python3
"""
策略回测系统
支持多种策略的历史数据回测
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

from .indicators import calculate_all_indicators


@dataclass
class Trade:
    """交易记录"""
    date: str
    action: str  # 'buy' or 'sell'
    price: float
    shares: int
    value: float
    reason: str


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    win_rate: float
    trades: List[Trade]
    equity_curve: pd.DataFrame


class Strategy:
    """策略基类"""
    
    def __init__(self, name: str):
        self.name = name
    
    def on_data(self, df: pd.DataFrame, position: int, cash: float) -> Optional[str]:
        """
        根据数据生成交易信号
        
        Args:
            df: 历史数据到当前日期
            position: 当前持仓股数
            cash: 当前现金
            
        Returns:
            'buy', 'sell', 或 None
        """
        raise NotImplementedError


class MAStrategy(Strategy):
    """均线交叉策略"""
    
    def __init__(self, short_period: int = 5, long_period: int = 20):
        super().__init__(f"MA{short_period}_MA{long_period}")
        self.short_period = short_period
        self.long_period = long_period
    
    def on_data(self, df: pd.DataFrame, position: int, cash: float) -> Optional[str]:
        if len(df) < self.long_period:
            return None
        
        ma_short = df[f'MA{self.short_period}'].iloc[-1]
        ma_long = df[f'MA{self.long_period}'].iloc[-1]
        ma_short_prev = df[f'MA{self.short_period}'].iloc[-2]
        ma_long_prev = df[f'MA{self.long_period}'].iloc[-2]
        
        # 金叉买入
        if ma_short > ma_long and ma_short_prev <= ma_long_prev and position == 0:
            return 'buy'
        
        # 死叉卖出
        if ma_short < ma_long and ma_short_prev >= ma_long_prev and position > 0:
            return 'sell'
        
        return None


class RSIStrategy(Strategy):
    """RSI策略"""
    
    def __init__(self, oversold: int = 30, overbought: int = 70):
        super().__init__(f"RSI_{oversold}_{overbought}")
        self.oversold = oversold
        self.overbought = overbought
    
    def on_data(self, df: pd.DataFrame, position: int, cash: float) -> Optional[str]:
        if 'RSI' not in df.columns or len(df) < 2:
            return None
        
        rsi = df['RSI'].iloc[-1]
        rsi_prev = df['RSI'].iloc[-2]
        
        # 超卖反弹买入
        if rsi_prev < self.oversold and rsi >= self.oversold and position == 0:
            return 'buy'
        
        # 超买回落卖出
        if rsi_prev > self.overbought and rsi <= self.overbought and position > 0:
            return 'sell'
        
        return None


class BacktestEngine:
    """回测引擎"""
    
    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission: float = 0.001,
        slippage: float = 0.001
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
    
    def run(
        self,
        df: pd.DataFrame,
        strategy: Strategy,
        position_size: float = 0.95
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            df: 历史数据DataFrame
            strategy: 策略实例
            position_size: 仓位比例（每次使用资金的比例）
            
        Returns:
            BacktestResult
        """
        df = df.copy()
        df = calculate_all_indicators(df)
        
        cash = self.initial_capital
        position = 0
        trades = []
        equity_curve = []
        
        # 获取策略所需的最小数据长度
        min_period = getattr(strategy, 'long_period', 20)
        
        for i in range(min_period, len(df)):
            current_data = df.iloc[:i+1]
            current_price = current_data['close'].iloc[-1]
            current_date = current_data['date'].iloc[-1]
            
            # 获取交易信号
            signal = strategy.on_data(current_data, position, cash)
            
            if signal == 'buy' and cash > 0:
                # 计算买入数量
                buy_value = cash * position_size
                shares = int(buy_value / (current_price * (1 + self.slippage)))
                
                if shares > 0:
                    cost = shares * current_price * (1 + self.slippage)
                    commission_cost = cost * self.commission
                    total_cost = cost + commission_cost
                    
                    if total_cost <= cash:
                        cash -= total_cost
                        position += shares
                        trades.append(Trade(
                            date=current_date,
                            action='buy',
                            price=current_price,
                            shares=shares,
                            value=total_cost,
                            reason=strategy.name
                        ))
            
            elif signal == 'sell' and position > 0:
                # 卖出
                sell_value = position * current_price * (1 - self.slippage)
                commission_cost = sell_value * self.commission
                total_value = sell_value - commission_cost
                
                cash += total_value
                trades.append(Trade(
                    date=current_date,
                    action='sell',
                    price=current_price,
                    shares=position,
                    value=total_value,
                    reason=strategy.name
                ))
                position = 0
            
            # 记录权益曲线
            equity = cash + position * current_price
            equity_curve.append({
                'date': current_date,
                'equity': equity,
                'cash': cash,
                'position': position,
                'price': current_price
            })
        
        # 计算最终收益
        final_price = df['close'].iloc[-1]
        final_capital = cash + position * final_price
        
        # 计算收益指标
        equity_df = pd.DataFrame(equity_curve)
        returns = equity_df['equity'].pct_change().dropna()
        
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        
        # 年化收益
        days = len(df)
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0
        
        # 最大回撤
        cummax = equity_df['equity'].cummax()
        drawdown = (equity_df['equity'] - cummax) / cummax
        max_drawdown = drawdown.min()
        
        # 夏普比率
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252) if returns.std() != 0 else 0
        
        # 胜率
        trade_returns = []
        for i in range(0, len(trades) - 1, 2):
            if i + 1 < len(trades):
                buy_trade = trades[i] if trades[i].action == 'buy' else trades[i+1]
                sell_trade = trades[i+1] if trades[i+1].action == 'sell' else trades[i]
                if buy_trade.action == 'buy' and sell_trade.action == 'sell':
                    trade_return = (sell_trade.value - buy_trade.value) / buy_trade.value
                    trade_returns.append(trade_return)
        
        win_rate = sum(1 for r in trade_returns if r > 0) / len(trade_returns) if trade_returns else 0
        
        return BacktestResult(
            strategy_name=strategy.name,
            start_date=df['date'].iloc[0],
            end_date=df['date'].iloc[-1],
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            trade_count=len(trades),
            win_rate=win_rate,
            trades=trades,
            equity_curve=equity_df
        )
    
    def compare_strategies(
        self,
        df: pd.DataFrame,
        strategies: List[Strategy]
    ) -> pd.DataFrame:
        """对比多个策略"""
        results = []
        for strategy in strategies:
            result = self.run(df, strategy)
            results.append({
                '策略': result.strategy_name,
                '总收益': f"{result.total_return:.2%}",
                '年化收益': f"{result.annual_return:.2%}",
                '最大回撤': f"{result.max_drawdown:.2%}",
                '夏普比率': f"{result.sharpe_ratio:.2f}",
                '交易次数': result.trade_count,
                '胜率': f"{result.win_rate:.2%}",
                '最终资金': f"{result.final_capital:,.2f}"
            })
        return pd.DataFrame(results)


# 便捷函数
def run_backtest(df: pd.DataFrame, strategy_name: str = 'MA5_MA20') -> BacktestResult:
    """快速回测"""
    engine = BacktestEngine()
    
    if strategy_name == 'MA5_MA20':
        strategy = MAStrategy(5, 20)
    elif strategy_name == 'MA10_MA30':
        strategy = MAStrategy(10, 30)
    elif strategy_name == 'RSI':
        strategy = RSIStrategy()
    else:
        strategy = MAStrategy(5, 20)
    
    return engine.run(df, strategy)

