#!/usr/bin/env python3
"""
立即运行简单版本选股
"""
import sys
import os
from pathlib import Path
from datetime import datetime
import json

# 添加finagent到路径
sys.path.insert(0, str(Path(__file__).parent))

from agents.daily_selection_agent import DailyStockSelectionAgent

def main():
    print("="*60)
    print("开始生成简单版本每日选股报告")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    try:
        # 创建选股Agent
        selector = DailyStockSelectionAgent()

        # 执行选股
        print("\n[1/2] 运行每日选股分析...")
        result = selector.run_stock_pool_selection()

        # 检查结果
        recommendations = result.get('recommendations', [])
        if recommendations:
            print(f"\n✓ 选股完成！推荐 {len(recommendations)} 只股票")
            for i, stock in enumerate(recommendations[:10], 1):  # 只显示前10个
                print(f"  {i}. {stock.get('stock_name')} ({stock.get('stock_code')}) - 评级: {stock.get('rating')}")
            if len(recommendations) > 10:
                print(f"  ... 还有 {len(recommendations)-10} 只股票")
        else:
            print("\n⚠️ 今日暂无推荐股票")

        print(f"\n报告数据已保存")

        # 保存执行状态
        state_file = selector.daily_selection_dir / "last_run_state.json"
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump({
                'last_run': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'success': True,
                'recommendations_count': len(recommendations)
            }, f, ensure_ascii=False, indent=2)

        print("\n✅ 简单版本选股任务执行完成")
        return 0

    except Exception as e:
        print(f"\n❌ 每日选股任务执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())