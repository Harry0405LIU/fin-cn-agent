#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论个股分析器

参照 elliott/stock_analyzer.py 的 StockWaveAnalyzer 模式，
实现单只股票的缠论分析，包括: 数据获取 → 缠论识别 → 报告生成 → 图表输出。
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

from chanlun.structures import Fractal, Stroke, Segment, Pivot, TradingPoint, Divergence
from chanlun.identify import chan_identify
from chanlun.divergence import calculate_stroke_macd_areas, detect_divergence, get_macd_columns
from chanlun.trading_points import identify_trading_points, get_active_signals
from chanlun.charts import plot_chan_chart, plot_segment_detail
from core.data_fetcher import fetch_a_share_data, fetch_hk_data
from core.indicators import calculate_macd, calculate_ma
from config.settings import settings


class StockChanAnalyzer:
    """
    个股缠论分析器。

    Usage:
        analyzer = StockChanAnalyzer("sh600519", "贵州茅台", "SH")
        analyzer.fetch_data(years=5)
        analyzer.analyze()
        analyzer.generate_report(Path("report.md"))
        analyzer.generate_chart(Path("chart.png"))
    """

    @staticmethod
    def _get_display_timeframe(timeframe: str) -> str:
        """将timeframe转换为显示名称"""
        timeframe_map = {
            'daily': '日线',
            'weekly': '周线',
            'monthly': '月线',
            '30min': '30分钟',
            '60min': '60分钟',
        }
        return timeframe_map.get(timeframe, timeframe)

    def __init__(self, symbol: str, name: str, market: str = 'SH', timeframe: str = None):
        self.symbol = symbol
        self.name = name
        self.market = market.upper()
        # 默认使用配置中的时间框架，或传入的timeframe，默认为30min
        self.timeframe = timeframe or settings.CHANLUN_TIMEFRAME
        self.analysis_timeframe = self._get_display_timeframe(self.timeframe)

        # 原始数据
        self.df: Optional[pd.DataFrame] = None
        self.df_merged: Optional[pd.DataFrame] = None

        # 缠论结构
        self.fractals: List[Fractal] = []
        self.strokes: List[Stroke] = []
        self.segments: List[Segment] = []
        self.pivots: List[Pivot] = []
        self.divergences: List[Divergence] = []
        self.trading_points: List[TradingPoint] = []

        # 分析元数据
        self.analysis_date: str = datetime.now().strftime('%Y-%m-%d')
        self.analysis_success: bool = False
        self.data_start_date: str = ""
        self.data_end_date: str = ""

    def fetch_data(self, years: int = 5) -> bool:
        """
        获取股票数据。

        Args:
            years: 数据年数（仅对日线级别有效，30分钟级别使用配置的月数）

        Returns:
            是否成功
        """
        end_date = datetime.now().strftime('%Y-%m-%d')

        # 根据timeframe计算开始日期
        if self.timeframe == '30min':
            # 30分钟数据使用配置的月数
            months = settings.CHANLUN_DATA_MONTHS
            start_date = (datetime.now() - timedelta(days=months * 30)).strftime('%Y-%m-%d')
            min_data_required = 60  # 日线数据至少60条
        else:
            # 日线及其他级别使用years参数
            start_date = (datetime.now() - timedelta(days=years * 365)).strftime('%Y-%m-%d')
            min_data_required = 60

        try:
            if self.market in ('SH', 'SZ'):
                if self.market == 'SH':
                    akshare_symbol = f"sh{self.symbol.replace('sh', '').replace('SH', '').replace('sz', '').replace('SZ', '')}"
                else:
                    akshare_symbol = f"sz{self.symbol.replace('sh', '').replace('SH', '').replace('sz', '').replace('SZ', '')}"

                self.df = fetch_a_share_data(akshare_symbol, start_date, end_date, period=self.timeframe)
            elif self.market == 'HK':
                # 港股：用 core.data_fetcher.fetch_hk_data（自带 akshare→akshare→yfinance
                # 多源 fallback，日线）。缠论本就按日线分析（旧实现取 60m 后重采样为日线），
                # 直接用日线等价、历史更全，且修掉旧 yfinance 路径的 lstrip('0') 代码转换
                # 与 60m 730 天限制两个 bug。
                # 港股无分钟源、按日线分析，30min 的 months*30 窗口太短（形不成中枢），
                # 改用 years 取多年日线，确保有足够笔/线段构造中枢。
                hk_years = max(years, 3)
                hk_start = (datetime.now() - timedelta(days=hk_years * 365)).strftime('%Y-%m-%d')
                hk_df = fetch_hk_data(self.symbol, hk_start, end_date)
                if hk_df is None or hk_df.empty:
                    print(f"港股数据获取失败(所有源): {self.symbol}")
                    return False
                self.df = hk_df
                print(f"港股日线数据获取成功: {self.symbol}, {len(self.df)} 条")
            else:
                print(f"不支持的市场: {self.market}")
                return False

            if self.df is None or len(self.df) < min_data_required:
                print(f"数据不足: {self.symbol}, 需要至少{min_data_required}条日线数据")
                return False

            # 确保列名标准化
            self.df.columns = [c.lower() for c in self.df.columns]

            self.data_start_date = str(self.df['date'].iloc[0])[:16]  # 包含时间
            self.data_end_date = str(self.df['date'].iloc[-1])[:16]

            print(f"数据获取成功: {self.symbol} {self.name}, {len(self.df)}条{self.analysis_timeframe}数据 "
                  f"({self.data_start_date} ~ {self.data_end_date})")
            return True

        except Exception as e:
            print(f"数据获取失败: {self.symbol} {self.name}, 错误: {e}")
            return False

    def analyze(self) -> bool:
        """
        运行完整的缠论分析链。

        流程:
        1. 计算技术指标 (MA, MACD)
        2. 运行缠论识别 (包含处理 → 分型 → 笔 → 线段 → 中枢)
        3. 计算MACD面积
        4. 检测背驰
        5. 识别买卖点

        Returns:
            是否分析成功
        """
        if self.df is None or len(self.df) < 60:
            print("数据不足，无法分析")
            return False

        try:
            # Step 0: 计算技术指标
            df_with_indicators = calculate_ma(self.df.copy())
            df_with_indicators = calculate_macd(df_with_indicators)

            # Step 1: 缠论识别
            print(f"  [1/5] 运行缠论识别 (基于{self.analysis_timeframe}数据)...")
            self.df_merged, self.fractals, self.strokes, self.segments, self.pivots = \
                chan_identify(df_with_indicators)

            print(f"     分型: {len(self.fractals)}个, 笔: {len(self.strokes)}个, "
                  f"线段: {len(self.segments)}个, 中枢: {len(self.pivots)}个")

            # Step 2: 计算MACD面积
            print("  [2/5] 计算MACD面积...")
            self.df_merged = get_macd_columns(self.df, self.df_merged)
            self.strokes = calculate_stroke_macd_areas(self.df_merged, self.strokes)

            # Step 3: 检测背驰
            print("  [3/5] 检测背驰...")
            self.divergences = detect_divergence(
                self.df_merged, self.pivots, self.strokes, self.segments
            )
            print(f"     检测到 {len(self.divergences)} 个背驰信号")

            # Step 4: 识别买卖点
            print("  [4/5] 识别买卖点...")
            self.trading_points = identify_trading_points(
                self.df_merged, self.pivots, self.divergences,
                self.strokes, self.segments, self.fractals
            )

            buys = [tp for tp in self.trading_points if tp.action == 'buy']
            sells = [tp for tp in self.trading_points if tp.action == 'sell']
            print(f"     检测到 {len(buys)} 个买点, {len(sells)} 个卖点")

            self.analysis_success = True
            print("  [5/5] 分析完成!")
            return True

        except Exception as e:
            print(f"分析失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def generate_report(self, save_path: Optional[Path] = None) -> str:
        """
        生成缠论分析Markdown报告。

        Args:
            save_path: 报告保存路径，默认自动生成

        Returns:
            报告内容字符串
        """
        if save_path is None:
            report_dir = settings.CHANLUN_REPORT_DIR
            report_dir.mkdir(parents=True, exist_ok=True)
            save_path = report_dir / f"缠论分析_{self.symbol}_{self.analysis_date}.md"

        lines = []
        self._add_report_header(lines)
        self._add_structure_summary(lines)
        self._add_pivot_analysis(lines)
        self._add_divergence_analysis(lines)
        self._add_trading_signals(lines)
        self._add_current_status(lines)
        self._add_disclaimer(lines)

        report = "\n".join(lines)

        # 保存
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(report)

        return report

    def _add_report_header(self, lines: List[str]):
        """报告头部"""
        current_price = self.df['close'].iloc[-1] if self.df is not None else 0
        change = 0
        if self.df is not None and len(self.df) >= 2:
            change = (self.df['close'].iloc[-1] / self.df['close'].iloc[-2] - 1) * 100

        lines.append(f"# 缠论分析报告: {self.name} ({self.symbol})")
        lines.append("")
        lines.append(f"**分析日期**: {self.analysis_date}")
        lines.append(f"**分析级别**: {self.analysis_timeframe}")
        lines.append(f"**数据区间**: {self.data_start_date} ~ {self.data_end_date}")
        lines.append(f"**当前价格**: {current_price:.2f}")
        lines.append(f"**涨跌幅**: {change:+.2f}%")
        lines.append("")

    def _add_structure_summary(self, lines: List[str]):
        """缠论结构总结"""
        lines.append("---")
        lines.append("## 一、缠论结构总览")
        lines.append("")

        lines.append("| 结构 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| 顶分型 | {len([f for f in self.fractals if f.type=='top'])} |")
        lines.append(f"| 底分型 | {len([f for f in self.fractals if f.type=='bottom'])} |")
        lines.append(f"| 上升笔 | {len([s for s in self.strokes if s.direction==1])} |")
        lines.append(f"| 下降笔 | {len([s for s in self.strokes if s.direction==-1])} |")
        lines.append(f"| 线段 | {len(self.segments)} |")
        lines.append(f"| 中枢 | {len(self.pivots)} |")
        lines.append(f"| 背驰 | {len(self.divergences)} |")
        lines.append(f"| 买点 | {len([tp for tp in self.trading_points if tp.action=='buy'])} |")
        lines.append(f"| 卖点 | {len([tp for tp in self.trading_points if tp.action=='sell'])} |")
        lines.append("")

        # 线段结构详情
        if self.segments:
            lines.append("### 线段列表")
            lines.append("")
            lines.append("| # | 方向 | 起始日 | 结束日 | 笔数 | 振幅 |")
            lines.append("|---|------|--------|--------|------|------|")
            for i, seg in enumerate(self.segments):
                amplitude = abs(seg.end_price - seg.start_price) / seg.start_price * 100 if seg.start_price > 0 else 0
                lines.append(
                    f"| {i+1} | {'↑ 上升' if seg.direction==1 else '↓ 下降'} "
                    f"| {seg.start_date[:10]} | {seg.end_date[:10]} "
                    f"| {len(seg.strokes)} | {amplitude:+.2f}% |"
                )
            lines.append("")

    def _add_pivot_analysis(self, lines: List[str]):
        """中枢分析"""
        lines.append("---")
        lines.append("## 二、中枢分析")
        lines.append("")

        if not self.pivots:
            lines.append("> 未检测到有效中枢。")
            lines.append("")
            return

        lines.append("| # | 类型 | 上轨(ZG) | 下轨(ZD) | 区间宽度 | 起始日 | 结束日 | 线段数 |")
        lines.append("|---|------|----------|----------|----------|--------|--------|--------|")
        for i, p in enumerate(self.pivots):
            width = (p.ZG - p.ZD) / p.ZD * 100 if p.ZD > 0 else 0
            direction_label = "上涨趋势" if p.direction == 1 else "下跌趋势"
            lines.append(
                f"| {i+1} | {direction_label} "
                f"| {p.ZG:.2f} | {p.ZD:.2f} "
                f"| {width:.2f}% "
                f"| {p.start_date[:10]} | {p.end_date[:10]} "
                f"| {len(p.segments)} |"
            )
        lines.append("")

        # 最新中枢详情
        last_pivot = self.pivots[-1]
        lines.append(f"### 最新中枢详情")
        lines.append(f"- **ZG(上轨)**: {last_pivot.ZG:.2f}")
        lines.append(f"- **ZD(下轨)**: {last_pivot.ZD:.2f}")
        lines.append(f"- **中枢区间**: [{last_pivot.ZD:.2f}, {last_pivot.ZG:.2f}]")
        lines.append(f"- **方向**: {'上涨趋势' if last_pivot.direction == 1 else '下跌趋势'}")
        lines.append(f"- **时间**: {last_pivot.start_date[:10]} ~ {last_pivot.end_date[:10]}")
        lines.append("")

    def _add_divergence_analysis(self, lines: List[str]):
        """背驰分析"""
        lines.append("---")
        lines.append("## 三、背驰分析")
        lines.append("")

        if not self.divergences:
            lines.append("> 未检测到背驰信号。")
            lines.append("")
            return

        lines.append("| # | 类型 | 日期 | 价格 | 进入段面积 | 离开段面积 | 强度 |")
        lines.append("|---|------|------|------|------------|------------|------|")
        for i, d in enumerate(self.divergences):
            type_map = {
                'top': '顶背驰(一卖)',
                'bottom': '底背驰(一买)',
                'consolidation_top': '盘整顶背驰',
                'consolidation_bottom': '盘整底背驰',
            }
            lines.append(
                f"| {i+1} | {type_map.get(d.divergence_type, d.divergence_type)} "
                f"| {d.date[:10]} | {d.price:.2f} "
                f"| {d.entering_macd_area:.4f} | {d.leaving_macd_area:.4f} "
                f"| {d.strength} |"
            )
        lines.append("")

    def _add_trading_signals(self, lines: List[str]):
        """买卖点信号"""
        lines.append("---")
        lines.append("## 四、买卖点信号")
        lines.append("")

        if not self.trading_points:
            lines.append("> 未检测到买卖点信号。")
            lines.append("")
            return

        lines.append("| # | 类型 | 操作 | 日期 | 价格 | 置信度 | 描述 |")
        lines.append("|---|------|------|------|------|--------|------|")
        for i, tp in enumerate(self.trading_points):
            type_label = f"{'一' if tp.point_type==1 else '二' if tp.point_type==2 else '三'}{'买' if tp.action=='buy' else '卖'}"
            confidence_emoji = {'high': '🟢', 'medium': '🟡', 'low': '🔴'}
            lines.append(
                f"| {i+1} | {type_label} | {'买入' if tp.action=='buy' else '卖出'} "
                f"| {tp.date[:10]} | {tp.price:.2f} "
                f"| {confidence_emoji.get(tp.confidence, '')} {tp.confidence} "
                f"| {tp.description[:60]} |"
            )
        lines.append("")

        # 买卖点汇总
        buys = [tp for tp in self.trading_points if tp.action == 'buy']
        sells = [tp for tp in self.trading_points if tp.action == 'sell']

        lines.append("### 买点汇总")
        for b in buys:
            lines.append(f"- **{b.date[:10]}** - {'一买' if b.point_type==1 else '二买' if b.point_type==2 else '三买'} @ {b.price:.2f} ({b.confidence})")
        lines.append("")

        lines.append("### 卖点汇总")
        for s in sells:
            lines.append(f"- **{s.date[:10]}** - {'一卖' if s.point_type==1 else '二卖' if s.point_type==2 else '三卖'} @ {s.price:.2f} ({s.confidence})")
        lines.append("")

    def _add_current_status(self, lines: List[str]):
        """当前状态与操作建议"""
        lines.append("---")
        lines.append("## 五、当前状态与操作建议")
        lines.append("")

        if not self.analysis_success:
            lines.append("> 分析未完成，无法提供建议。")
            lines.append("")
            return

        # 当前价格
        current_price = self.df['close'].iloc[-1]

        # 找最近的有效买卖点
        active_buys, active_sells = get_active_signals(
            self.trading_points, len(self.df_merged) - 1
        )

        # 中枢位置
        if self.pivots:
            last_pivot = self.pivots[-1]
            ZG = last_pivot.ZG
            ZD = last_pivot.ZD
            has_expansion = getattr(last_pivot, 'has_expansion', False)
            expansion_ratio_prev = getattr(last_pivot, 'expansion_ratio_prev', 0.0)
            overlap_prev_width = getattr(last_pivot, 'overlap_prev_width', 0.0)

            if current_price > ZG:
                position = f"价格在最新中枢上方 (>{ZG:.2f})"
                if has_expansion:
                    position += f" | 中枢扩张(重叠{overlap_prev_width:.2f}元,比例{expansion_ratio_prev:.1%})"
                suggestion = "若回踩不破ZG，关注三买机会；若跌破ZG，观望。"
            elif current_price < ZD:
                position = f"价格在最新中枢下方 (<{ZD:.2f})"
                if has_expansion:
                    position += f" | 中枢扩张(重叠{overlap_prev_width:.2f}元,比例{expansion_ratio_prev:.1%})"
                suggestion = "若反弹不破ZD，关注三卖机会；若突破ZD，观望。"
            else:
                position = f"价格在最新中枢区间内 [{ZD:.2f}, {ZG:.2f}]"
                if has_expansion:
                    position += f" | 中枢扩张(重叠{overlap_prev_width:.2f}元,比例{expansion_ratio_prev:.1%})"
                suggestion = "中枢震荡中，建议观望等待方向明确。"
        else:
            position = "无有效中枢"
            suggestion = "趋势中，关注中枢形成后的买卖点。"

        lines.append(f"**当前价格**: {current_price:.2f}")
        lines.append(f"**中枢位置**: {position}")
        lines.append(f"**操作建议**: {suggestion}")
        lines.append("")

        # 活跃信号
        if active_buys:
            lines.append("### 当前有效买点")
            for b in active_buys[-3:]:
                lines.append(f"- **{b.date[:10]}** {'一买' if b.point_type==1 else '二买' if b.point_type==2 else '三买'} @ {b.price:.2f}")
        else:
            lines.append("### 当前有效买点: 无")

        if active_sells:
            lines.append("### 当前有效卖点")
            for s in active_sells[-3:]:
                lines.append(f"- **{s.date[:10]}** {'一卖' if s.point_type==1 else '二卖' if s.point_type==2 else '三卖'} @ {s.price:.2f}")
        else:
            lines.append("### 当前有效卖点: 无")

        lines.append("")

    def _add_disclaimer(self, lines: List[str]):
        """免责声明"""
        lines.append("---")
        lines.append("## 免责声明")
        lines.append("")
        lines.append("> 缠论分析基于严格的几何结构分类，不代表对未来价格走势的预测。")
        lines.append("> 所有买卖点信号仅供参考，不构成投资建议。")
        lines.append("> 实际操作中应结合基本面、市场情绪等多维因素综合判断。")
        lines.append("> **缠论的真谛: 不测而测 — 不做预测，只做分类应对。**")
        lines.append("")

    def generate_chart(self, save_path: Optional[Path] = None) -> str:
        """
        生成缠论分析图表。

        Args:
            save_path: 图表保存路径

        Returns:
            保存路径
        """
        if save_path is None:
            chart_dir = settings.CHANLUN_CHART_DIR
            chart_dir.mkdir(parents=True, exist_ok=True)
            save_path = chart_dir / f"缠论分析_{self.symbol}_{self.analysis_date}.png"

        path = plot_chan_chart(
            df=self.df,
            df_merged=self.df_merged,
            fractals=self.fractals,
            strokes=self.strokes,
            segments=self.segments,
            pivots=self.pivots,
            trading_points=self.trading_points,
            divergences=self.divergences,
            title=f"缠论分析: {self.name} ({self.symbol})",
            save_path=str(save_path),
            show_macd=True,
        )

        # 同时生成线段细节图
        if self.segments:
            detail_path = str(save_path).replace('.png', '_detail.png')
            plot_segment_detail(
                df_merged=self.df_merged,
                segments=self.segments,
                pivots=self.pivots,
                save_path=detail_path,
            )

        return path

    def get_summary(self) -> Dict[str, Any]:
        """获取分析摘要"""
        buys = [tp for tp in self.trading_points if tp.action == 'buy']
        sells = [tp for tp in self.trading_points if tp.action == 'sell']

        latest_buy = buys[-1] if buys else None
        latest_sell = sells[-1] if sells else None
        last_pivot = self.pivots[-1] if self.pivots else None

        return {
            'symbol': self.symbol,
            'name': self.name,
            'current_price': self.df['close'].iloc[-1] if self.df is not None else 0,
            'analysis_date': self.analysis_date,
            'fractal_count': len(self.fractals),
            'stroke_count': len(self.strokes),
            'segment_count': len(self.segments),
            'pivot_count': len(self.pivots),
            'divergence_count': len(self.divergences),
            'buy_count': len(buys),
            'sell_count': len(sells),
            'latest_buy': {
                'date': latest_buy.date, 'price': latest_buy.price,
                'type': f"{latest_buy.point_type}买", 'confidence': latest_buy.confidence
            } if latest_buy else None,
            'latest_sell': {
                'date': latest_sell.date, 'price': latest_sell.price,
                'type': f"{latest_sell.point_type}卖", 'confidence': latest_sell.confidence
            } if latest_sell else None,
            'last_pivot': {
                'ZG': last_pivot.ZG, 'ZD': last_pivot.ZD,
                'start_date': last_pivot.start_date, 'end_date': last_pivot.end_date,
                'has_expansion': getattr(last_pivot, 'has_expansion', False),
                'expansion_ratio_prev': getattr(last_pivot, 'expansion_ratio_prev', 0.0),
                'expansion_ratio_next': getattr(last_pivot, 'expansion_ratio_next', 0.0),
                'overlap_prev_width': getattr(last_pivot, 'overlap_prev_width', 0.0),
                'overlap_next_width': getattr(last_pivot, 'overlap_next_width', 0.0),
            } if last_pivot else None,
        }

def fetch_hk_30min_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    获取港股30分钟数据并重采样为日线数据（用于缠论分析）

    Args:
        symbol: 股票代码（如 1880）
        start: 开始日期 YYYYMMDD
        end: 结束日期 YYYYMMDD

    Returns:
        日线数据DataFrame
    """
    import yfinance as yf

    # 转换代码格式: 01880.HK / 01880 -> 1880
    yf_code = symbol.replace('.HK', '').replace('.hk', '')
    yf_code = yf_code.lstrip('0')

    try:
        ticker = yf.Ticker(yf_code + '.HK')
        # 获取30分钟数据
        hist = ticker.history(start=start, end=end, interval='60m', auto_adjust=False)

        if hist.empty:
            print(f"yfinance获取港股60分钟数据为空")
            return pd.DataFrame()

        # 转换为统一格式
        df = pd.DataFrame({
            'date': hist.index.strftime('%Y-%m-%d'),
            'open': hist['Open'].values,
            'high': hist['High'].values,
            'low': hist['Low'].values,
            'close': hist['Close'].values,
            'volume': hist['Volume'].values
        })
        print(f"yfinance成功获取港股60分钟数据: {len(df)} 条")

        # 重采样为日线数据（用于缠论分析）
        df_daily = df.resample('D').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        print(f"重采样为日线数据: {len(df_daily)} 条")
        return df_daily

    except Exception as e:
        print(f"fetch_hk_30min_data 失败: {e}")
        return pd.DataFrame()

