#!/usr/bin/env python3
"""
技术指标计算模块
支持MACD、KDJ、RSI、MA等常用指标
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional


def calculate_ma(df: pd.DataFrame, periods: list = [5, 10, 20, 60]) -> pd.DataFrame:
    """
    计算移动平均线
    
    Args:
        df: DataFrame with 'close' column
        periods: MA周期列表
        
    Returns:
        添加了MA列的DataFrame
    """
    df = df.copy()
    for period in periods:
        df[f'MA{period}'] = df['close'].rolling(window=period).mean()
    return df


def calculate_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> pd.DataFrame:
    """
    计算MACD指标
    
    Args:
        df: DataFrame with 'close' column
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期
        
    Returns:
        添加了MACD列的DataFrame
    """
    df = df.copy()
    
    # 计算EMA
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    
    # MACD线
    df['MACD'] = ema_fast - ema_slow
    
    # 信号线
    df['MACD_Signal'] = df['MACD'].ewm(span=signal, adjust=False).mean()
    
    # MACD柱状图
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    
    return df


def calculate_rsi(df: pd.DataFrame, period: int = 14, method: str = 'wilder') -> pd.DataFrame:
    """
    计算RSI指标

    Args:
        df: DataFrame with 'close' column
        period: RSI周期
        method: 计算方法，'wilder'(Wilder平滑，默认) 或 'sma'(简单移动平均)

    Returns:
        添加了RSI列的DataFrame
    """
    df = df.copy()

    # 计算价格变化
    delta = df['close'].diff()

    # 分离上涨和下跌
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    # 使用Wilder指数平滑（TradingView、同花顺等平台使用此方法）
    if method == 'wilder':
        gain_avg = gain.ewm(alpha=1/period, adjust=False).mean()
        loss_avg = loss.ewm(alpha=1/period, adjust=False).mean()
    else:
        # SMA方法（传统计算方式）
        gain_avg = gain.rolling(window=period).mean()
        loss_avg = loss.rolling(window=period).mean()

    # 计算RS和RSI
    rs = gain_avg / loss_avg
    df['RSI'] = 100 - (100 / (1 + rs))

    return df


def calculate_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """
    计算KDJ指标
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        n: RSV周期
        m1: K平滑系数
        m2: D平滑系数
        
    Returns:
        添加了KDJ列的DataFrame
    """
    df = df.copy()
    
    # 计算RSV
    low_list = df['low'].rolling(window=n, min_periods=n).min()
    high_list = df['high'].rolling(window=n, min_periods=n).max()
    rsv = (df['close'] - low_list) / (high_list - low_list) * 100
    
    # 计算K、D、J
    df['K'] = rsv.ewm(com=m1-1, adjust=False).mean()
    df['D'] = df['K'].ewm(com=m2-1, adjust=False).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    
    return df


def calculate_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0
) -> pd.DataFrame:
    """
    计算布林带
    
    Args:
        df: DataFrame with 'close' column
        period: 周期
        std_dev: 标准差倍数
        
    Returns:
        添加了布林带列的DataFrame
    """
    df = df.copy()
    
    # 中轨 (MA)
    df['BOLL_MID'] = df['close'].rolling(window=period).mean()
    
    # 标准差
    rolling_std = df['close'].rolling(window=period).std()
    
    # 上轨和下轨
    df['BOLL_UP'] = df['BOLL_MID'] + (rolling_std * std_dev)
    df['BOLL_DOWN'] = df['BOLL_MID'] - (rolling_std * std_dev)
    
    return df


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算所有技术指标
    
    Args:
        df: DataFrame with OHLCV data
        
    Returns:
        添加了所有技术指标的DataFrame
    """
    df = df.copy()
    df = calculate_ma(df)
    df = calculate_macd(df)
    df = calculate_rsi(df)
    df = calculate_kdj(df)
    df = calculate_bollinger(df)
    return df


def get_indicator_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    获取最新指标摘要
    
    Args:
        df: DataFrame with indicators
        
    Returns:
        指标摘要字典
    """
    if df.empty:
        return {}
    
    latest = df.iloc[-1]
    
    summary = {
        'price': round(latest.get('close', 0), 2),
        'ma5': round(latest.get('MA5', 0), 2) if 'MA5' in latest else None,
        'ma20': round(latest.get('MA20', 0), 2) if 'MA20' in latest else None,
        'rsi': round(latest.get('RSI', 0), 2) if 'RSI' in latest else None,
        'macd': round(latest.get('MACD', 0), 4) if 'MACD' in latest else None,
        'k': round(latest.get('K', 0), 2) if 'K' in latest else None,
        'd': round(latest.get('D', 0), 2) if 'D' in latest else None,
        'boll_up': round(latest.get('BOLL_UP', 0), 2) if 'BOLL_UP' in latest else None,
        'boll_down': round(latest.get('BOLL_DOWN', 0), 2) if 'BOLL_DOWN' in latest else None,
    }
    
    # 添加信号判断
    signals = []
    
    # MACD信号
    if 'MACD' in latest and 'MACD_Signal' in latest:
        if latest['MACD'] > latest['MACD_Signal']:
            signals.append('MACD金叉')
        elif latest['MACD'] < latest['MACD_Signal']:
            signals.append('MACD死叉')
    
    # RSI信号
    if 'RSI' in latest:
        if latest['RSI'] > 70:
            signals.append('RSI超买')
        elif latest['RSI'] < 30:
            signals.append('RSI超卖')
    
    # KDJ信号
    if 'K' in latest and 'D' in latest:
        if latest['K'] > latest['D'] and latest['K'] < 80:
            signals.append('KDJ金叉')
        elif latest['K'] < latest['D'] and latest['K'] > 20:
            signals.append('KDJ死叉')
    
    summary['signals'] = signals
    
    return summary
