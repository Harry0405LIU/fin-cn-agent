#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinAgent elliott wave module"""

from elliott.signals import (
    check_signals,
    check_signals_weighted,
    update_state,
    load_state,
    save_state,
    auto_adjust_scenario,
    analyze_multi_timeframe_correlation,
    _round_to_significant,
    generate_breakout_scenario,
)

from elliott.dynamic_scoring import (
    calculate_composite_score,
    calculate_momentum_score,
    calculate_volume_confirmation,
    calculate_breakout_strength,
    calculate_market_sentiment,
    dynamic_scene_probability_adjustment,
    batch_dynamic_score_scenarios,
    infer_scenario_type,
)

from elliott.breakout_detector import (
    EnhancedBreakoutDetector,
    BreakoutHistory,
    fast_detect_breakout,
    fast_detect_breakdown,
    classify_breakout_strength,
    detect_breakouts_from_dataframe,
    CriticalChangeTracker,
)

from elliott.multi_timeframe_analyzer import (
    analyze_resonance,
    calculate_resonance_strength,
    analyze_trend_consistency,
    quick_resonance_check,
    quantify_signal_strength,
)

from elliott.stock_analyzer import (
    StockWaveAnalyzer,
    get_elliott_for_selection,
    regenerate_all_stock_reports,
)

__all__ = [
    # signals
    'check_signals',
    'check_signals_weighted',
    'update_state',
    'load_state',
    'save_state',
    'auto_adjust_scenario',
    'analyze_multi_timeframe_correlation',
    '_round_to_significant',
    'generate_breakout_scenario',
    # dynamic_scoring
    'calculate_composite_score',
    'calculate_momentum_score',
    'calculate_volume_confirmation',
    'calculate_breakout_strength',
    'calculate_market_sentiment',
    'dynamic_scene_probability_adjustment',
    'batch_dynamic_score_scenarios',
    'infer_scenario_type',
    # breakout_detector
    'EnhancedBreakoutDetector',
    'BreakoutHistory',
    'fast_detect_breakout',
    'fast_detect_breakdown',
    'classify_breakout_strength',
    'detect_breakouts_from_dataframe',
    'CriticalChangeTracker',
    # multi_timeframe_analyzer
    'analyze_resonance',
    'calculate_resonance_strength',
    'analyze_trend_consistency',
    'quick_resonance_check',
    'quantify_signal_strength',
    # stock_analyzer
    'StockWaveAnalyzer',
    'get_elliott_for_selection',
    'regenerate_all_stock_reports',
]
