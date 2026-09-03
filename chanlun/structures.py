#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缠论数据结构定义: 分型、笔、线段、中枢、背驰、买卖点"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MergedCandle:
    """K线包含处理后的合并K线"""
    index: int                          # 在合并序列中的位置
    date: str                           # 日期
    open: float
    high: float
    low: float
    close: float
    volume: float
    original_indices: List[int] = field(default_factory=list)  # 源数据行索引


@dataclass
class Fractal:
    """
    分型: 三根K线组成的转折信号
    - 顶分型(type='top'): 中间K线高点最高且低点最高 (形如∧)
    - 底分型(type='bottom'): 中间K线低点最低且高点最低 (形如∨)
    """
    index: int                          # 在合并后DataFrame中的位置
    date: str
    price: float                        # 顶分型用high, 底分型用low
    type: str                           # 'top' 或 'bottom'
    high: float
    low: float


@dataclass
class Stroke:
    """
    笔: 连接相邻顶底分型的最小运动单元
    - 上升笔(direction=1): 底分型 → 顶分型
    - 下降笔(direction=-1): 顶分型 → 底分型
    """
    start_fractal: Fractal
    end_fractal: Fractal
    direction: int                      # 1=上升笔, -1=下降笔
    start_idx: int                      # 起始索引(合并后DataFrame)
    end_idx: int                        # 结束索引(合并后DataFrame)
    start_date: str
    end_date: str
    kline_count: int                    # 笔内包含的K线数
    amplitude: float                    # 涨跌幅 abs(end-start)/start
    high: float                         # 笔内最高价
    low: float                          # 笔内最低价
    macd_area: float = 0.0              # 笔内MACD柱面积(由divergence.py填充)


@dataclass
class Segment:
    """
    线段: 至少三笔重叠构成的稳定趋势段

    特征序列:
    - 向上线段: 特征序列 = 各下降笔的低点
    - 向下线段: 特征序列 = 各上升笔的高点
    """
    strokes: List[Stroke]               # 组成线段的笔列表
    direction: int                      # 1=向上线段, -1=向下线段
    start_idx: int
    end_idx: int
    start_date: str
    end_date: str
    start_price: float
    end_price: float
    high: float                         # 线段内最高价
    low: float                          # 线段内最低价


@dataclass
class Pivot:
    """
    中枢: 至少三个连续次级别走势类型重叠形成的价格区间

    中枢区间公式: [max(low1,low2,low3), min(high1,high2,high3)]
    ZG(中枢上轨) = min(high1, high2, high3)
    ZD(中枢下轨) = max(low1, low2, low3)
    有效条件: ZG > ZD
    """
    segments: List[Segment]             # 构成中枢的线段(至少3段)
    direction: int                      # 中枢所在的趋势方向 1=上涨趋势, -1=下跌趋势
    ZG: float                           # 中枢上轨
    ZD: float                           # 中枢下轨
    start_date: str
    end_date: str
    start_idx: int
    end_idx: int
    overlap_prev_width: float = 0.0   # 与前一中枢的重叠宽度
    overlap_next_width: float = 0.0  # 与后一中枢的重叠宽度
    has_expansion: bool = False        # 是否有扩张（重叠比例>30%）
    expansion_ratio_prev: float = 0.0 # 与前一中枢的扩张比例
    expansion_ratio_next: float = 0.0 # 与后一中枢的扩张比例


@dataclass
class Divergence:
    """
    背驰: 价格创新高/低但动能衰竭的信号
    - 顶背驰('top'): 价格更高但MACD面积更小 → 卖点信号
    - 底背驰('bottom'): 价格更低但MACD面积更小 → 买点信号
    - 盘整背驰('consolidation'): 盘整中的背驰
    """
    pivot: Optional[Pivot]              # 关联中枢
    divergence_type: str                # 'top', 'bottom', 'consolidation_top', 'consolidation_bottom'
    index: int                          # 背驰发生的K线位置
    date: str
    price: float                        # 背驰点价格
    entering_macd_area: float           # 进入段MACD面积
    leaving_macd_area: float            # 离开段MACD面积
    strength: str                       # 'strong', 'normal', 'weak'


@dataclass
class TradingPoint:
    """
    买卖点: 缠论的三类买卖点信号

    第一类(1): 趋势末端的背驰点 → 风险最高、空间最大
    第二类(2): 一买后回踩不破前低(或一卖后反弹不破前高) → 安全性更高
    第三类(3): 离开中枢后回抽不重回中枢内 → 趋势加速信号
    """
    index: int                          # 信号发生的K线位置
    date: str
    point_type: int                     # 1, 2, 3
    action: str                         # 'buy' 或 'sell'
    price: float
    pivot: Optional[Pivot] = None       # 关联中枢(一买/一卖/三买/三卖关联)
    divergence: Optional[Divergence] = None  # 关联背驰(一买/一卖关联)
    description: str = ""
    confidence: str = 'medium'          # 'high', 'medium', 'low'
