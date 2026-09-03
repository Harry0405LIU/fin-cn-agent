#!/usr/bin/env python3
"""
生成详细样式每日选股报告的定时任务
包含技术分析和价值分析的详细评分
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import json

# 添加finagent到路径
sys.path.insert(0, str(Path(__file__).parent))

from agents.daily_selection_agent import DailyStockSelectionAgent
from generate_missing_md_reports import generate_md_report
from core.logger import setup_logger
from config.settings import settings

# 初始化日志
logger = setup_logger("daily_selection_md")

# 输出目录
OUTPUT_DIR = settings.BASE_DIR / "每日选股"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def generate_daily_selection_md_report():
    """生成详细样式的每日选股报告"""
    try:
        logger.info("="*60)
        logger.info("开始生成详细样式每日选股报告")
        logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*60)

        # 1. 运行每日选股分析
        logger.info("\n[1/2] 运行每日选股分析...")
        selector = DailyStockSelectionAgent()
        result = selector.run_stock_pool_selection()

        if not result:
            logger.error("每日选股分析失败")
            return False

        # 2. 保存JSON数据（使用详细版文件名，避免覆盖简单版）
        selection_date = result.get('selection_date', datetime.now().strftime('%Y-%m-%d'))
        json_filename = f"每日选股_{selection_date}_详细版.json"
        json_path = OUTPUT_DIR / json_filename

        logger.info(f"\n[2/2] 保存数据并生成MD报告...")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"  JSON数据已保存: {json_path}")

        # 3. 生成MD报告
        generate_md_report(json_path)
        md_filename = f"每日选股_{selection_date}_详细版.md"
        md_path = OUTPUT_DIR / md_filename
        logger.info(f"  MD报告已生成: {md_path}")

        # 统计信息
        analyzed_stocks = result.get('analyzed_stocks', [])
        recommendations = result.get('recommendations', [])

        logger.info(f"\n✅ 报告生成完成！")
        logger.info(f"  分析股票: {len(analyzed_stocks)}只")
        logger.info(f"  推荐股票: {len(recommendations)}只")

        # 推荐分布
        if recommendations:
            buy_count = len([r for r in recommendations if r.get('_new_rating') in ['推荐', '强烈推荐']])
            hold_count = len([r for r in recommendations if r.get('_new_rating') == '中性'])
            sell_count = len([r for r in recommendations if r.get('_new_rating') in ['不推荐', '强烈不推荐']])

            logger.info(f"  推荐分布: 买入{buy_count} | 持有{hold_count} | 卖出{sell_count}")

        logger.info(f"\n报告文件:")
        logger.info(f"  JSON: {json_path}")
        logger.info(f"  MD:   {md_path}")

        return True

    except Exception as e:
        logger.error(f"生成报告失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """主函数 - 可用于定时任务"""
    logger.info("详细样式每日选股报告生成器")
    logger.info("="*60)

    success = generate_daily_selection_md_report()

    if success:
        logger.info("\n✅ 任务完成")
        sys.exit(0)
    else:
        logger.error("\n❌ 任务失败")
        sys.exit(1)


if __name__ == "__main__":
    main()