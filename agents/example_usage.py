#!/usr/bin/env python3
"""
股票多空辩论分析 - 使用示例
"""

import os
from pathlib import Path
from agents.financial_data_fetcher import FinancialDataFetcher
from agents.debate_agent import DebateAgent
from config.settings import settings


def example_basic_usage():
    """基本使用示例"""
    print("=" * 60)
    print("示例 1: 基本使用")
    print("=" * 60)

    # 设置API密钥
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置环境变量 ANTHROPIC_API_KEY")
        return

    # 创建财务数据获取器
    fetcher = FinancialDataFetcher()

    # 获取财务数据
    stock_code = "000001"  # 平安银行
    print(f"\n正在获取 {stock_code} 的财务数据...")
    financial_data = fetcher.get_stock_financial_data(stock_code)

    # 创建辩论Agent
    debate_agent = DebateAgent(
        api_key=api_key,
        rounds=2,
        output_dir=settings.DEBATE_REPORT_DIR
    )

    # 进行辩论分析
    stock_name = financial_data.get("stock_name", "未知")
    result = debate_agent.conduct_debate(
        stock_name=stock_name,
        stock_code=stock_code,
        financial_data=financial_data,
        save_report=True
    )

    # 显示结果
    print(f"\n投资评级: {result['final_summary'].get('investment_rating', 'N/A')}")
    print(f"信心水平: {result['final_summary'].get('confidence_level', 'N/A')}")


def example_custom_rounds():
    """自定义辩论轮数"""
    print("\n" + "=" * 60)
    print("示例 2: 自定义辩论轮数")
    print("=" * 60)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置环境变量 ANTHROPIC_API_KEY")
        return

    # 增加辩论轮数以获得更深入的分析
    debate_agent = DebateAgent(
        api_key=api_key,
        rounds=3,  # 3轮辩论
        output_dir=settings.DEBATE_REPORT_DIR
    )

    # ... 进行分析


def example_multiple_stocks():
    """分析多只股票"""
    print("\n" + "=" * 60)
    print("示例 3: 批量分析多只股票")
    print("=" * 60)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置环境变量 ANTHROPIC_API_KEY")
        return

    # 定义要分析的股票列表
    stocks = [
        {"code": "000001", "name": "平安银行"},
        {"code": "000002", "name": "万科A"},
        {"code": "600036", "name": "招商银行"},
    ]

    fetcher = FinancialDataFetcher()
    debate_agent = DebateAgent(
        api_key=api_key,
        rounds=2,
        output_dir=settings.DEBATE_REPORT_DIR
    )

    for stock in stocks:
        print(f"\n正在分析 {stock['name']} ({stock['code']})...")
        financial_data = fetcher.get_stock_financial_data(stock["code"], stock["name"])

        debate_agent.conduct_debate(
            stock_name=stock["name"],
            stock_code=stock["code"],
            financial_data=financial_data,
            save_report=True
        )


def example_direct_agent_usage():
    """直接使用单个Agent"""
    print("\n" + "=" * 60)
    print("示例 4: 直接使用单个Agent")
    print("=" * 60)

    from agents.bull_agent import BullAgent
    from agents.bear_agent import BearAgent

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置环境变量 ANTHROPIC_API_KEY")
        return

    # 创建单个Agent
    bull = BullAgent(api_key=api_key)
    bear = BearAgent(api_key=api_key)

    # 获取数据
    fetcher = FinancialDataFetcher()
    financial_data = fetcher.get_stock_financial_data("000001", "平安银行")

    # 看多分析
    print("\n看多分析:")
    bull_result = bull.analyze_financials(
        stock_name="平安银行",
        stock_code="000001",
        financial_data=financial_data
    )
    print(f"看多观点: {bull_result.get('summary', 'N/A')}")

    # 看空分析
    print("\n看空分析:")
    bear_result = bear.analyze_financials(
        stock_name="平安银行",
        stock_code="000001",
        financial_data=financial_data
    )
    print(f"看空观点: {bear_result.get('summary', 'N/A')}")


if __name__ == "__main__":
    # 运行示例
    print("股票多空辩论分析 - 使用示例\n")

    # 选择要运行的示例
    import sys

    if len(sys.argv) > 1:
        example_num = sys.argv[1]
        if example_num == "1":
            example_basic_usage()
        elif example_num == "2":
            example_custom_rounds()
        elif example_num == "3":
            example_multiple_stocks()
        elif example_num == "4":
            example_direct_agent_usage()
        else:
            print("请选择示例编号: 1, 2, 3, 或 4")
    else:
        # 默认运行示例1
        example_basic_usage()

        print("\n\n其他可用示例:")
        print("  python example_usage.py 1  - 基本使用")
        print("  python example_usage.py 2  - 自定义辩论轮数")
        print("  python example_usage.py 3  - 批量分析多只股票")
        print("  python example_usage.py 4  - 直接使用单个Agent")
