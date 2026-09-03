#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论图表生成模块

生成叠加了缠论结构标记的K线分析图表:
- 分型标记 (△顶 / ▽底)
- 笔的连线
- 中枢区间 (矩形区域)
- 买卖点标记
- MACD背驰注释
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Optional
from chanlun.structures import (
    Fractal, Stroke, Segment, Pivot, TradingPoint, Divergence
)

# 中文字体配置 (复用 elliott/charts.py 的配置)
plt.rcParams['font.family'] = ['PingFang HK', 'STHeiti', 'Heiti TC', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


def plot_chan_chart(
    df: pd.DataFrame,
    df_merged: pd.DataFrame,
    fractals: List[Fractal],
    strokes: List[Stroke],
    segments: List[Segment],
    pivots: List[Pivot],
    trading_points: List[TradingPoint],
    divergences: List[Divergence] = None,
    title: str = "缠论分析",
    save_path: Optional[str] = None,
    show_macd: bool = True,
) -> str:
    """
    生成完整的缠论分析图表。

    布局:
    1. 主图: K线价格 + 分型 + 笔 + 中枢区域
    2. 成交量
    3. MACD (可选)

    Args:
        df: 原始OHLCV DataFrame
        df_merged: 合并后DataFrame
        fractals: 分型列表
        strokes: 笔列表
        segments: 线段列表
        pivots: 中枢列表
        trading_points: 买卖点列表
        divergences: 背驰列表
        title: 图表标题
        save_path: 保存路径
        show_macd: 是否显示MACD子图

    Returns:
        保存的图表文件路径
    """
    if divergences is None:
        divergences = []

    n_subplots = 3 if show_macd else 2
    height_ratios = [4, 1, 1.5] if show_macd else [4, 1]

    fig, axes = plt.subplots(
        n_subplots, 1, figsize=(20, 12),
        gridspec_kw={'height_ratios': height_ratios},
        sharex=True
    )
    fig.suptitle(title, fontsize=16, fontweight='bold', y=0.98)

    ax_main = axes[0]
    ax_vol = axes[1]
    ax_macd = axes[2] if show_macd else None

    # 使用合并后的数据绘图
    n_bars = len(df_merged)
    x = np.arange(n_bars)
    dates = df_merged['date'].values

    # ========== 主图 ==========
    # 价格线
    ax_main.plot(x, df_merged['close'].values, color='#333', linewidth=1.2, label='收盘价', zorder=2)
    ax_main.fill_between(x, df_merged['low'].values, df_merged['high'].values,
                         alpha=0.15, color='#666', zorder=1)

    # 均线
    if 'MA20' in df_merged.columns:
        ax_main.plot(x, df_merged['MA20'].values, color='#FF9800', linewidth=0.8,
                    linestyle='--', alpha=0.7, label='MA20')
    if 'MA60' in df_merged.columns:
        ax_main.plot(x, df_merged['MA60'].values, color='#2196F3', linewidth=0.8,
                    linestyle='--', alpha=0.7, label='MA60')

    # 中枢区域
    for pivot in pivots:
        xi = pivot.start_idx
        xj = pivot.end_idx
        if 0 <= xi < n_bars and 0 <= xj < n_bars:
            rect = mpatches.Rectangle(
                (xi, pivot.ZD), xj - xi, pivot.ZG - pivot.ZD,
                linewidth=1, edgecolor='#E91E63' if pivot.direction == 1 else '#4CAF50',
                facecolor='#FFCDD2' if pivot.direction == 1 else '#C8E6C9',
                alpha=0.3, zorder=0
            )
            ax_main.add_patch(rect)
            # 标注ZG/ZD
            ax_main.axhline(y=pivot.ZG, xmin=xi/n_bars, xmax=xj/n_bars,
                          color='#E91E63', linewidth=0.8, linestyle=':', alpha=0.6)
            ax_main.axhline(y=pivot.ZD, xmin=xi/n_bars, xmax=xj/n_bars,
                          color='#4CAF50', linewidth=0.8, linestyle=':', alpha=0.6)

    # 笔的连线
    for stroke in strokes:
        if 0 <= stroke.start_idx < n_bars and 0 <= stroke.end_idx < n_bars:
            color = '#D32F2F' if stroke.direction == 1 else '#1976D2'
            ax_main.plot([stroke.start_idx, stroke.end_idx],
                        [stroke.start_fractal.price, stroke.end_fractal.price],
                        color=color, linewidth=1.8, alpha=0.8, zorder=3)

    # 分型标记
    top_x, top_y, top_dates = [], [], []
    bottom_x, bottom_y, bottom_dates = [], [], []
    for f in fractals:
        if 0 <= f.index < n_bars:
            if f.type == 'top':
                top_x.append(f.index)
                top_y.append(f.price)
                top_dates.append(f.date)
            else:
                bottom_x.append(f.index)
                bottom_y.append(f.price)
                bottom_dates.append(f.date)

    ax_main.scatter(top_x, top_y, marker='v', color='#D32F2F', s=60, zorder=5, label='顶分型')
    ax_main.scatter(bottom_x, bottom_y, marker='^', color='#1976D2', s=60, zorder=5, label='底分型')

    # 买卖点标记
    buy_colors = {1: '#FF5722', 2: '#FF9800', 3: '#FFC107'}  # 一买深橙, 二买橙, 三买浅橙
    sell_colors = {1: '#4CAF50', 2: '#388E3C', 3: '#1B5E20'}  # 一卖绿, 二卖深绿, 三卖最深绿
    buy_sizes = {1: 150, 2: 120, 3: 90}
    sell_sizes = {1: 150, 2: 120, 3: 90}

    for tp in trading_points:
        if not (0 <= tp.index < n_bars):
            continue
        if tp.action == 'buy':
            ax_main.scatter(tp.index, tp.price, marker='^',
                          color=buy_colors.get(tp.point_type, '#FF5722'),
                          s=buy_sizes.get(tp.point_type, 100), zorder=10,
                          edgecolors='white', linewidth=1.5)
            ax_main.annotate(f'B{tp.point_type}', (tp.index, tp.price),
                           textcoords="offset points", xytext=(0, 12),
                           fontsize=8, fontweight='bold',
                           color=buy_colors.get(tp.point_type, '#FF5722'),
                           ha='center', zorder=11)
        else:
            ax_main.scatter(tp.index, tp.price, marker='v',
                          color=sell_colors.get(tp.point_type, '#4CAF50'),
                          s=sell_sizes.get(tp.point_type, 100), zorder=10,
                          edgecolors='white', linewidth=1.5)
            ax_main.annotate(f'S{tp.point_type}', (tp.index, tp.price),
                           textcoords="offset points", xytext=(0, -12),
                           fontsize=8, fontweight='bold',
                           color=sell_colors.get(tp.point_type, '#4CAF50'),
                           ha='center', zorder=11)

    # 背驰标注 (画箭头连接两个极值点)
    for div in divergences:
        if div.pivot and 0 <= div.index < n_bars:
            ax_main.annotate(
                f"{'顶背驰' if 'top' in div.divergence_type else '底背驰'}",
                xy=(div.index, div.price),
                xytext=(div.index, div.price * 1.05 if 'top' in div.divergence_type else div.price * 0.95),
                fontsize=8, fontweight='bold',
                color='#E91E63' if 'top' in div.divergence_type else '#4CAF50',
                ha='center',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='#999'),
                zorder=12
            )

    # 图例
    handles, labels = ax_main.get_legend_handles_labels()
    # 添加自定义图例
    legend_elements = [
        mpatches.Patch(facecolor='#FFCDD2', edgecolor='#E91E63', alpha=0.3, label='上涨中枢'),
        mpatches.Patch(facecolor='#C8E6C9', edgecolor='#4CAF50', alpha=0.3, label='下跌中枢'),
    ]
    ax_main.legend(handles=handles + legend_elements, loc='upper left', fontsize=8, ncol=2)

    ax_main.set_ylabel('价格', fontsize=11)
    ax_main.grid(True, alpha=0.3)

    # ========== 成交量图 ==========
    colors = ['#EF5350' if df_merged['close'].iloc[i] >= df_merged['open'].iloc[i]
              else '#26A69A' for i in range(n_bars)]
    ax_vol.bar(x, df_merged['volume'].values, color=colors, alpha=0.7, width=1.0)
    ax_vol.set_ylabel('成交量', fontsize=10)
    ax_vol.grid(True, alpha=0.2, axis='y')

    # ========== MACD子图 ==========
    if show_macd and 'MACD_Hist' in df_merged.columns and ax_macd is not None:
        macd_values = df_merged['MACD'].values
        signal_values = df_merged['MACD_Signal'].values
        hist_values = df_merged['MACD_Hist'].values

        # MACD柱
        hist_colors = ['#EF5350' if h >= 0 else '#26A69A' for h in hist_values]
        ax_macd.bar(x, hist_values, color=hist_colors, alpha=0.6, width=1.0)

        # MACD线
        ax_macd.plot(x, macd_values, color='#FF5722', linewidth=1.0, label='MACD')
        ax_macd.plot(x, signal_values, color='#2196F3', linewidth=1.0, label='Signal')

        ax_macd.axhline(y=0, color='#999', linewidth=0.5, linestyle='-')
        ax_macd.set_ylabel('MACD', fontsize=10)
        ax_macd.legend(loc='upper left', fontsize=8)
        ax_macd.grid(True, alpha=0.2)

    # X轴标签
    if n_bars > 100:
        step = max(1, n_bars // 20)
        tick_positions = x[::step]
        tick_labels = dates[::step]
    else:
        tick_positions = x
        tick_labels = dates

    ax_main.set_xticks(tick_positions)
    ax_main.set_xticklabels([str(d)[:10] for d in tick_labels], rotation=45, ha='right', fontsize=8)

    plt.tight_layout()
    plt.subplots_adjust(hspace=0.05)

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return save_path

    plt.close(fig)
    return save_path if save_path else ""


def plot_segment_detail(
    df_merged: pd.DataFrame,
    segments: List[Segment],
    pivots: List[Pivot],
    save_path: str,
) -> str:
    """
    线段级别的细节图，用于调试线段检测算法。

    显示每个线段的笔结构、特征序列和线段破坏点。
    """
    fig, ax = plt.subplots(1, 1, figsize=(20, 8))

    n_bars = len(df_merged)
    x = np.arange(n_bars)

    ax.plot(x, df_merged['close'].values, color='#333', linewidth=1.0, alpha=0.5)

    # 每个线段用不同颜色标注
    colors = plt.cm.tab10(np.linspace(0, 1, max(1, len(segments))))

    for i, seg in enumerate(segments):
        seg_x = np.arange(seg.start_idx, seg.end_idx + 1)
        seg_close = df_merged['close'].iloc[seg.start_idx:seg.end_idx + 1].values
        color = colors[i % len(colors)]
        ax.plot(seg_x, seg_close, color=color, linewidth=2.5, label=f'线段{i+1}({"↑" if seg.direction==1 else "↓"})')

        # 画线段内的笔
        for stroke in seg.strokes:
            ax.plot([stroke.start_idx, stroke.end_idx],
                   [stroke.start_fractal.price, stroke.end_fractal.price],
                   color=color, linewidth=1.0, linestyle='--', alpha=0.5)

    # 中枢
    for pivot in pivots:
        ax.axhspan(pivot.ZD, pivot.ZG, alpha=0.15, color='#E91E63')

    ax.legend(loc='upper left', fontsize=8)
    ax.set_title('线段结构细节', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return save_path
