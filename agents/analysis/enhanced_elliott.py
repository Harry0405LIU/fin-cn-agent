#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版艾略特波浪分析模块
支持个股动态波浪分析
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 尝试导入akshare，如果失败则使用项目的数据获取模块
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    from core.data_fetcher import fetch_a_share_data, fetch_hk_data
    DATA_FETCHER_AVAILABLE = True
except ImportError:
    DATA_FETCHER_AVAILABLE = False


class EnhancedElliottAnalyzer:
    """增强版艾略特波浪分析器 - 支持个股动态分析"""

    def __init__(self):
        self.price_cache = {}

    def fetch_stock_data(self, symbol: str, years: int = 3) -> Optional[pd.DataFrame]:
        """获取股票数据"""
        cache_key = f"{symbol}_{years}y"
        if cache_key in self.price_cache:
            return self.price_cache[cache_key]

        try:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=years*365)).strftime('%Y-%m-%d')

            df = None

            # 优先使用项目的数据获取模块
            if DATA_FETCHER_AVAILABLE:
                try:
                    # 判断市场类型
                    if symbol.endswith('.HK'):
                        # 港股
                        df = fetch_hk_data(symbol, start_date, end_date)
                    else:
                        # A股 - 统一处理格式
                        # 统一转换为带前缀的格式
                        if '.' not in symbol:
                            # 纯数字代码，需要添加前缀
                            if symbol.startswith('6'):
                                symbol = f'sh{symbol}'
                            else:
                                symbol = f'sz{symbol}'
                        elif not symbol.startswith(('sh', 'sz')):
                            # 有后缀但没有前缀
                            if symbol.endswith('.SH'):
                                code = symbol.replace('.SH', '')
                                symbol = f'sh{code}'
                            elif symbol.endswith('.SZ'):
                                code = symbol.replace('.SZ', '')
                                symbol = f'sz{code}'

                        df = fetch_a_share_data(symbol, start_date, end_date)

                    if df is not None and not df.empty:
                        print(f"  使用项目数据获取模块成功获取 {symbol} 数据")
                except Exception as e:
                    print(f"  项目数据获取模块失败: {e}")
                    df = None

            # 如果项目模块失败，尝试直接使用akshare
            if df is None and AKSHARE_AVAILABLE:
                try:
                    end_date_ak = datetime.now().strftime('%Y%m%d')
                    start_date_ak = (datetime.now() - timedelta(days=years*365)).strftime('%Y%m%d')

                    # 根据代码格式选择数据源
                    if symbol.startswith('sh') or symbol.startswith('sz'):
                        # 去掉前缀
                        code = symbol[2:]
                        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                               start_date=start_date_ak, end_date=end_date_ak, adjust="qfq")
                    elif symbol.endswith('.HK'):
                        # 港股
                        hk_code = symbol.replace('.HK', '')
                        if len(hk_code) == 4:
                            hk_code = '0' + hk_code
                        df = ak.stock_hk_daily(symbol=hk_code, adjust='qfq')
                    else:
                        # 默认尝试A股
                        df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                               start_date=start_date_ak, end_date=end_date_ak, adjust="qfq")

                    if df is not None and not df.empty:
                        print(f"  使用akshare成功获取 {symbol} 数据")
                except Exception as e:
                    print(f"  akshare数据获取失败: {e}")
                    df = None

            if df is None or df.empty:
                return None

            # 标准化列名
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume'
            })

            # 确保有必需的列
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                # 尝试英文列名
                df = df.rename(columns={
                    'Date': 'date',
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                    'Volume': 'volume'
                })

            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)

            self.price_cache[cache_key] = df
            return df

        except Exception as e:
            print(f"获取 {symbol} 数据失败: {e}")
            return None

    def resample_to_timeframe(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """重采样数据到不同时间框架"""
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()
        df = df.set_index('date')

        if timeframe == 'weekly':
            resampled = df.resample('W').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
        elif timeframe == 'monthly':
            resampled = df.resample('ME').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
        else:
            resampled = df

        return resampled.reset_index()

    def detect_swings(self, df: pd.DataFrame, window: int = 5) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """检测波峰波谷"""
        df = df.copy()
        df['high_max'] = df['high'].rolling(window=window, center=True).max()
        df['low_min'] = df['low'].rolling(window=window, center=True).min()

        peaks = df[(df['high'] == df['high_max']) &
                  (df['high'].shift(1) < df['high']) &
                  (df['high'].shift(-1) < df['high'])].copy()

        troughs = df[(df['low'] == df['low_min']) &
                    (df['low'].shift(1) > df['low']) &
                    (df['low'].shift(-1) > df['low'])].copy()

        return peaks, troughs

    def calculate_fibonacci_levels(self, high_price: float, low_price: float) -> Dict[str, float]:
        """计算斐波那契回调位"""
        diff = high_price - low_price
        return {
            '0%': high_price,
            '23.6%': high_price - 0.236 * diff,
            '38.2%': high_price - 0.382 * diff,
            '50%': high_price - 0.5 * diff,
            '61.8%': high_price - 0.618 * diff,
            '78.6%': high_price - 0.786 * diff,
            '100%': low_price,
        }

    def analyze_wave_structure(self, df: pd.DataFrame, level_name: str = "日线") -> Dict:
        """分析波浪结构"""
        if df is None or df.empty:
            return {}

        current_price = float(df.iloc[-1]['close'])
        high_price = float(df['high'].max())
        low_price = float(df['low'].min())

        # 计算关键位
        fib_levels = self.calculate_fibonacci_levels(high_price, low_price)

        # 计算移动平均线
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()

        # 趋势判断
        ma20 = df['MA20'].iloc[-1] if not pd.isna(df['MA20'].iloc[-1]) else 0
        ma60 = df['MA60'].iloc[-1] if not pd.isna(df['MA60'].iloc[-1]) else 0

        # 正确的横盘判定：MA20和MA60偏离<2%视为横盘
        if ma60 > 0:
            ma_diff_pct = abs(ma20 - ma60) / ma60 * 100
            if ma_diff_pct < 2.0:
                trend = "横盘"
            elif ma20 > ma60:
                trend = "上涨"
            else:
                trend = "下跌"
        else:
            trend = "横盘"  # 数据不足时视为横盘

        # 位置判断
        if high_price > low_price:
            position_ratio = (current_price - low_price) / (high_price - low_price)
        else:
            position_ratio = 0.5

        # 检测波峰波谷
        peaks, troughs = self.detect_swings(df)

        return {
            'current_price': current_price,
            'high_price': high_price,
            'low_price': low_price,
            'fib_levels': fib_levels,
            'trend': trend,
            'ma20': ma20,
            'ma60': ma60,
            'position_ratio': position_ratio,
            'peaks_count': len(peaks),
            'troughs_count': len(troughs),
            'df': df
        }

    def generate_elliott_scenarios(self, analysis: Dict) -> List[Dict]:
        """生成艾略特波浪场景（偏左侧评分：趋势启动和调整结束时高分）"""
        current = analysis['current_price']
        high = analysis['high_price']
        low = analysis['low_price']
        trend = analysis['trend']
        ratio = analysis['position_ratio']

        scenarios = []

        # 根据当前趋势和位置生成不同场景
        if trend == "上涨":
            if ratio > 0.7:
                # 接近高点 - 第5浪末端（趋势结束，低分）
                scenarios.append({
                    'name': '推动浪第5浪末端',
                    'probability': 40,
                    'description': f'当前价格{current:.2f}接近历史高点{high:.2f}，可能处于第5浪末端，注意顶部风险。',
                    'bullish': False,
                    'score': 1,  # 低分：趋势结束，离场时机
                    'key_level': high
                })
                scenarios.append({
                    'name': 'B浪反弹中',
                    'probability': 30,
                    'description': f'当前反弹可能是B浪，后续C浪回调目标在{low:.2f}附近。',
                    'bullish': False,
                    'score': 2,  # 低分：调整中继
                    'key_level': low
                })
                scenarios.append({
                    'name': '主升浪第3浪延伸',
                    'probability': 30,
                    'description': f'上涨动能强劲，可能处于第3浪延伸阶段，突破{high:.2f}后目标看高一线。',
                    'bullish': True,
                    'score': 5,  # 中分：趋势已确立，但不是左侧
                    'key_level': high * 1.1
                })
            elif ratio > 0.4:
                # 中部位置 - 第3浪或第4浪
                scenarios.append({
                    'name': '推动浪第3浪中',
                    'probability': 35,
                    'description': f'处于第3浪上涨中，上涨动能充足，目标突破前期高点。',
                    'bullish': True,
                    'score': 5,  # 中分：趋势已确立
                    'key_level': high
                })
                scenarios.append({
                    'name': '调整浪4浪',
                    'probability': 30,
                    'description': f'可能处于第4浪调整，后续还有第5浪上涨。',
                    'bullish': True,
                    'score': 3,  # 中低分：趋势中继调整
                    'key_level': high * 0.95
                })
                scenarios.append({
                    'name': '调整浪A浪',
                    'probability': 25,
                    'description': f'可能处于A浪回调中，支撑位在{low:.2f}附近。',
                    'bullish': False,
                    'score': 2,  # 低分：调整开始
                    'key_level': low
                })
                scenarios.append({
                    'name': '平台整理',
                    'probability': 10,
                    'description': f'当前处于平台整理阶段，等待方向选择。',
                    'bullish': None,
                    'score': 0,
                    'key_level': (high + low) / 2
                })
            else:
                # 底部位置 - 第1浪或C浪末端（高分）
                scenarios.append({
                    'name': '推动浪第1浪',
                    'probability': 40,
                    'description': f'可能处于新一轮推动浪的第1浪，底部特征明显。',
                    'bullish': True,
                    'score': 9,  # 高分：趋势启动，最佳进场时机
                    'key_level': high
                })
                scenarios.append({
                    'name': '调整浪C浪末端',
                    'probability': 35,
                    'description': f'可能处于C浪下跌末端，接近{low:.2f}支撑位，关注企稳信号。',
                    'bullish': True,
                    'score': 8,  # 高分：调整结束，次佳进场时机
                    'key_level': low
                })
                scenarios.append({
                    'name': '2浪回调中',
                    'probability': 25,
                    'description': f'可能处于第2浪回调中，是较好的加仓时机。',
                    'bullish': True,
                    'score': 7,  # 高分：回调结束，进场时机
                    'key_level': low * 1.05
                })
        else:  # 下跌或横盘
            if ratio > 0.6:
                # 高位下跌 - A浪开始（低分）
                scenarios.append({
                    'name': 'A浪下跌开始',
                    'probability': 40,
                    'description': f'当前从高位回落，可能处于A浪下跌开始，离场时机。',
                    'bullish': False,
                    'score': 1,  # 低分：调整开始，离场时机
                    'key_level': low
                })
                scenarios.append({
                    'name': 'B浪反弹',
                    'probability': 30,
                    'description': f'当前反弹为B浪概率较大，后续C浪回调目标{low:.2f}。',
                    'bullish': False,
                    'score': 3,  # 中低分：暂时观望
                    'key_level': low
                })
                scenarios.append({
                    'name': '下跌中继反弹',
                    'probability': 30,
                    'description': f'仅为下跌中继的反弹，后续将继续下跌。',
                    'bullish': False,
                    'score': 2,  # 低分：反弹结束
                    'key_level': low * 0.9
                })
            elif ratio > 0.3:
                # 中部位置 - C浪下跌中（中等低分）
                scenarios.append({
                    'name': 'C浪下跌中',
                    'probability': 35,
                    'description': f'处于C浪下跌中，目标{low:.2f}附近，等待C浪结束。',
                    'bullish': False,
                    'score': 2,  # 低分：下跌中
                    'key_level': low
                })
                scenarios.append({
                    'name': '调整浪4浪',
                    'probability': 25,
                    'description': f'可能处于第4浪调整，后续还有第5浪上涨。',
                    'bullish': True,
                    'score': 3,  # 中低分：趋势中继
                    'key_level': high
                })
                scenarios.append({
                    'name': '下跌趋势延续',
                    'probability': 40,
                    'description': f'下跌趋势延续，未见企稳信号。',
                    'bullish': False,
                    'score': 1,  # 低分：下跌延续
                    'key_level': low * 0.95
                })
            else:
                # 底部位置 - C浪末端或大级别底部（高分）
                scenarios.append({
                    'name': 'C浪末端',
                    'probability': 40,
                    'description': f'可能处于C浪下跌末端，接近{low:.2f}支撑位，关注企稳信号。',
                    'bullish': True,
                    'score': 8,  # 高分：调整结束，进场时机
                    'key_level': low
                })
                scenarios.append({
                    'name': '大级别底部',
                    'probability': 35,
                    'description': f'接近历史低点{low:.2f}，可能处于大级别底部区域。',
                    'bullish': True,
                    'score': 9,  # 高分：大级别底部，最佳进场时机
                    'key_level': high
                })
                scenarios.append({
                    'name': '底部构筑中',
                    'probability': 30,
                    'description': f'在{low:.2f}附近构筑底部，关注企稳信号。',
                    'bullish': True,
                    'score': 7,  # 高分：底部区域
                    'key_level': low * 1.05
                })

        return scenarios

    def calculate_multi_timeframe_resonance(self, daily_analysis: Dict,
                                           weekly_analysis: Optional[Dict] = None,
                                           monthly_analysis: Optional[Dict] = None) -> Dict:
        """计算多级别共振"""
        # 转换趋势为数值
        def trend_to_score(trend):
            if trend == "上涨":
                return 1
            elif trend == "下跌":
                return -1
            else:
                return 0

        daily_trend = trend_to_score(daily_analysis.get('trend', '横盘'))
        weekly_trend = trend_to_score(weekly_analysis.get('trend', '横盘')) if weekly_analysis else 0
        monthly_trend = trend_to_score(monthly_analysis.get('trend', '横盘')) if monthly_analysis else 0

        total_score = daily_trend + weekly_trend + monthly_trend

        if total_score >= 2:
            resonance = "🟢 多头共振"
            direction = "向上"
            details = "日线、周线、月线趋势一致向上，形成较强的多头共振，上涨概率较大。"
            resonance_score = 3
        elif total_score <= -2:
            resonance = "🔴 空头共振"
            direction = "向下"
            details = "日线、周线、月线趋势一致向下，形成较强的空头共振，下跌风险较高。"
            resonance_score = -3
        else:
            resonance = "🟡 趋势分歧"
            direction = "震荡"
            details = "多级别趋势存在分歧，方向尚未明确，建议观望等待信号确认。"
            resonance_score = 0

        return {
            'resonance': resonance,
            'direction': direction,
            'details': details,
            'score': resonance_score,
            'daily_trend': daily_analysis.get('trend', '横盘'),
            'weekly_trend': weekly_analysis.get('trend', '横盘') if weekly_analysis else None,
            'monthly_trend': monthly_analysis.get('trend', '横盘') if monthly_analysis else None,
        }

    def analyze_stock(self, stock_code: str, stock_name: str = "",
                      years: int = 3) -> Dict[str, Any]:
        """
        分析单只股票的艾略特波浪结构

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            years: 分析年数

        Returns:
            波浪分析结果
        """
        # 获取日线数据
        daily_df = self.fetch_stock_data(stock_code, years)
        if daily_df is None or daily_df.empty:
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'elliott_score': 0,
                'wave_position': '数据不足',
                'description': '无法获取股票数据',
                'error': 'no_data'
            }

        # 重采样为周线和月线
        weekly_df = self.resample_to_timeframe(daily_df, 'weekly')
        monthly_df = self.resample_to_timeframe(daily_df, 'monthly')

        # 分析各时间级别
        daily_analysis = self.analyze_wave_structure(daily_df, "日线")
        weekly_analysis = self.analyze_wave_structure(weekly_df, "周线") if not weekly_df.empty else None
        monthly_analysis = self.analyze_wave_structure(monthly_df, "月线") if not monthly_df.empty else None

        # 生成场景
        daily_scenarios = self.generate_elliott_scenarios(daily_analysis)

        # 计算综合评分
        # 基于场景的加权评分
        scenario_score = sum(s['score'] * s['probability'] / 100 for s in daily_scenarios)

        # 多级别共振评分
        resonance = self.calculate_multi_timeframe_resonance(daily_analysis, weekly_analysis, monthly_analysis)

        # 综合评分 = 场景评分(70%) + 共振评分(30%)
        elliott_score = scenario_score * 0.7 + resonance['score'] * 0.3

        # 选择最高概率的场景作为主要波浪位置
        main_scenario = max(daily_scenarios, key=lambda x: x['probability'])

        # 构建返回结果
        result = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'elliott_score': round(elliott_score, 1),
            'wave_position': main_scenario['name'],
            'description': main_scenario['description'],
            'scenarios': daily_scenarios,
            'resonance': resonance,
            'current_price': daily_analysis['current_price'],
            'high_price': daily_analysis['high_price'],
            'low_price': daily_analysis['low_price'],
            'trend': daily_analysis['trend'],
            'fib_levels': daily_analysis['fib_levels'],
            'daily_analysis': {
                'trend': daily_analysis['trend'],
                'position_ratio': daily_analysis['position_ratio'],
                'ma20': daily_analysis['ma20'],
                'ma60': daily_analysis['ma60'],
            },
            'weekly_analysis': {
                'trend': weekly_analysis['trend'],
                'position_ratio': weekly_analysis['position_ratio'],
            } if weekly_analysis else None,
            'monthly_analysis': {
                'trend': monthly_analysis['trend'],
                'position_ratio': monthly_analysis['position_ratio'],
            } if monthly_analysis else None,
        }

        return result
