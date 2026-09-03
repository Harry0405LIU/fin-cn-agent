#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论分析Agent - 继承BaseAgent，封装个股缠论分析的完整流程。
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.base_agent import BaseAgent
from chanlun.stock_analyzer import StockChanAnalyzer
from chanlun.backtest import run_chan_backtest, format_chan_backtest_report
from config.settings import settings


class ChanTheoryAgent(BaseAgent):
    """
    缠论分析Agent。

    Config keys:
        - symbol: 股票代码 (必填)
        - name: 股票名称 (必填)
        - market: 市场 SH/SZ/HK (默认SH)
        - timeframe: 数据周期 (默认30min，可选: daily, 30min, 60min)
        - years: 数据年数 (默认5，仅对日线级别有效)
        - output_dir: 输出目录 (可选)
        - run_backtest: 是否运行回测 (默认False)

    Usage:
        agent = ChanTheoryAgent({"symbol": "sh600519", "name": "贵州茅台"})
        result = agent.execute()
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(name="ChanTheoryAgent", config=config or {})

    def validate_config(self) -> bool:
        """验证配置"""
        required = ["symbol", "name"]
        for key in required:
            if key not in self.config or not self.config[key]:
                self.log_error(f"缺少配置项: {key}")
                return False

        # 验证timeframe参数
        timeframe = self.config.get("timeframe")
        if timeframe and timeframe not in ['daily', '30min', '60min', 'weekly', 'monthly']:
            self.log_error(f"不支持的时间周期: {timeframe}，支持: daily, 30min, 60min, weekly, monthly")
            return False

        return True

    def run(self, *args, **kwargs) -> Dict:
        """
        执行缠论分析。

        Returns:
            {
                'success': bool,
                'message': str,
                'data': {
                    'report_path': str,
                    'chart_path': str,
                    'backtest_report': str (if run_backtest),
                    'summary': dict,
                },
                'timestamp': str,
            }
        """
        symbol = self.config["symbol"]
        name = self.config["name"]
        market = self.config.get("market", "SH")
        timeframe = self.config.get("timeframe", settings.CHANLUN_TIMEFRAME)
        years = self.config.get("years", 5)
        run_backtest = self.config.get("run_backtest", False)

        self.log_info(f"开始缠论分析: {name} ({symbol}), 市场={market}, 周期={timeframe}, 数据年数={years}")

        # 创建分析器
        analyzer = StockChanAnalyzer(symbol=symbol, name=name, market=market, timeframe=timeframe)

        # 获取数据
        self.log_info("获取数据...")
        if not analyzer.fetch_data(years=years):
            return {
                "success": False,
                "message": f"数据获取失败: {symbol}",
                "data": {},
                "timestamp": datetime.now().isoformat(),
            }

        # 分析
        self.log_info("运行缠论分析...")
        if not analyzer.analyze():
            return {
                "success": False,
                "message": f"分析失败: {symbol}",
                "data": {},
                "timestamp": datetime.now().isoformat(),
            }

        # 确定输出目录
        output_dir = self.config.get("output_dir")
        if output_dir:
            output_dir = Path(output_dir)
        else:
            output_dir = settings.CHANLUN_REPORT_DIR

        output_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime('%Y%m%d')

        # 生成报告
        self.log_info("生成报告...")
        report_path = output_dir / f"缠论分析_{symbol}_{date_str}.md"
        analyzer.generate_report(save_path=report_path)

        # 生成图表
        self.log_info("生成图表...")
        chart_dir = settings.CHANLUN_CHART_DIR
        chart_dir.mkdir(parents=True, exist_ok=True)
        chart_path = chart_dir / f"缠论分析_{symbol}_{date_str}.png"
        analyzer.generate_chart(save_path=chart_path)

        # 回测
        backtest_report = ""
        if run_backtest:
            self.log_info("运行回测...")
            try:
                bt_result = run_chan_backtest(analyzer.df)
                backtest_report = format_chan_backtest_report(bt_result)
                bt_path = output_dir / f"缠论回测_{symbol}_{date_str}.md"
                with open(bt_path, 'w', encoding='utf-8') as f:
                    f.write(backtest_report)
            except Exception as e:
                self.log_error(f"回测失败: {e}")
                backtest_report = f"回测失败: {e}"

        # 摘要
        summary = analyzer.get_summary()

        self.log_info(f"分析完成: {summary['buy_count']}个买点, {summary['sell_count']}个卖点")

        return {
            "success": True,
            "message": f"缠论分析完成: {name} ({symbol})",
            "data": {
                "report_path": str(report_path),
                "chart_path": str(chart_path),
                "backtest_report": backtest_report if run_backtest else "",
                "summary": summary,
            },
            "timestamp": datetime.now().isoformat(),
        }
