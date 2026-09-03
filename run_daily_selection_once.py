#!/usr/bin/env python3
"""
每日选股一次性执行脚本
用于定时任务调用，执行完成后退出
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import json

# 添加finagent到路径
sys.path.insert(0, str(Path(__file__).parent))

from agents.daily_selection_agent import DailyStockSelectionAgent
from core.logger import setup_logger


def main():
    """执行每日选股任务（一次性）"""
    # 初始化日志
    logger = setup_logger("daily_selection")

    try:
        logger.info("="*60)
        logger.info("开始每日选股任务")
        logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*60)

        # 创建选股Agent
        selector = DailyStockSelectionAgent()

        # 执行选股（使用自选股票池全量评估）
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

        # 保存执行状态
        state_file = selector.daily_selection_dir / "last_run_state.json"
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump({
                'last_run': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'success': True,
                'recommendations_count': len(recommendations)
            }, f, ensure_ascii=False, indent=2)

        logger.info("\n每日选股任务执行完成")
        return 0

    except Exception as e:
        logger.error(f"每日选股任务执行失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
