#!/usr/bin/env python3
"""
每日选股定时任务
每天定时执行选股Agent，生成选股报告
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import time
import schedule
import json

# 添加finagent到路径
sys.path.insert(0, str(Path(__file__).parent))

from agents.daily_selection_agent import DailyStockSelectionAgent
from elliott.stock_analyzer import regenerate_all_stock_reports
from core.logger import setup_logger

# 初始化日志
logger = setup_logger("daily_selection")

# 配置
DAILY_TIME = "09:00"  # 每日执行时间


def run_daily_selection():
    """执行每日选股任务"""
    try:
        logger.info("="*60)
        logger.info("开始每日选股任务")
        logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*60)

        # 创建选股Agent
        selector = DailyStockSelectionAgent()

        # 执行选股（使用自选股票池全量评估，包含所有A股、港股、ETF）
        result = selector.run_stock_pool_selection()

        # 检查是否有推荐股票
        recommendations = result.get('recommendations', [])
        if recommendations:
            logger.info(f"\n✓ 选股完成！推荐 {len(recommendations)} 只股票")
            for i, stock in enumerate(recommendations, 1):
                logger.info(f"  {i}. {stock.get('stock_name')} ({stock.get('stock_code')}) - 评级: {stock.get('rating')}")
        else:
            logger.warning("\n⚠️ 今日暂无推荐股票")

        logger.info(f"\n报告已保存: {result.get('report_path')}")

        # 同步刷新所有个股波浪分析报告
        try:
            logger.info("\n开始同步刷新个股波浪分析报告...")
            wave_result = regenerate_all_stock_reports()
            logger.info(f"波浪报告刷新完成: 成功 {wave_result['success']}, 失败 {wave_result['fail']}")
        except Exception as e:
            logger.error(f"波浪报告刷新失败: {e}")

    except Exception as e:
        logger.error(f"每日选股任务执行失败: {e}")
        import traceback
        logger.error(traceback.format_exc())


def main():
    """主函数"""
    logger.info("="*60)
    logger.info("每日选股定时任务服务启动")
    logger.info(f"计划执行时间: 每天 {DAILY_TIME}")
    logger.info("="*60)

    # 设置定时任务
    schedule.every().day.at(DAILY_TIME).do(run_daily_selection)

    # 立即执行一次（用于测试）
    logger.info("首次启动立即执行一次...")
    run_daily_selection()

    # 循环检查定时任务
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"定时任务执行错误: {e}")

        # 每分钟检查一次
        time.sleep(60)


if __name__ == "__main__":
    main()