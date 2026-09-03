#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量艾略特波浪分析脚本（v2 - 对齐指数分析体系）
读取自选股票池中的所有股票/ETF，逐一生成波浪分析报告

v2 升级:
- 使用 StockWaveAnalyzer（zigzag波浪检测 + 加权信号验证 + 状态管理）
- 报告格式对齐 elliott/daily_update.py 的指数日报格式
- 支持 A股/港股/ETF
"""

import sys
import os
import re
import time
import traceback
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from elliott.stock_analyzer import StockWaveAnalyzer
from elliott.signals import load_state, save_state

# ============================================================
# 配置
# ============================================================

STOCK_POOL_FILE = settings.BASE_DIR / "自选股票池.md"
OUTPUT_DIR = settings.BASE_DIR / "波浪预测" / "每日更新" / "个股分析"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 增量模式：跳过已存在的报告
SKIP_EXISTING = False

# 限定市场（None=全部, 'HK'=仅港股, 'A'=仅A股）
ONLY_MARKETS = None


def parse_stock_pool(file_path: Path) -> list[dict]:
    """解析自选股票池文件，提取所有唯一股票"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    stocks = {}  # code -> {code, name, market}

    # 模式1: 行业: code(name), code(name), ...
    line_pattern = re.compile(r'([\w]+)\.(SH|SZ|HK)\s*\(([^)]+)\)')

    # 模式2: 表格 | 名称 | 代码 |
    table_pattern = re.compile(r'\|\s*([^\s|]+)\s*\|\s*(\d{4,6})\s*\|')

    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # 匹配行业行格式
        matches = line_pattern.findall(line)
        for code, market, name in matches:
            code = code.strip()
            market = market.strip()
            key = f"{code}.{market}"
            if key not in stocks:
                stocks[key] = {'code': code, 'name': name.strip(), 'market': market}

        # 匹配表格格式
        table_matches = table_pattern.findall(line)
        for name, code in table_matches:
            name = name.strip()
            code = code.strip()
            if name and code and name not in ('名称', '代码', ':'):
                key = f"{code}.SH" if len(code) == 6 and code.startswith(('5', '6', '9')) else \
                      f"{code}.SZ" if len(code) == 6 else \
                      f"{code}.HK" if len(code) <= 5 else None
                if key and key not in stocks:
                    market = 'SH' if len(code) == 6 and code.startswith(('5', '6', '9')) else \
                             'SZ' if len(code) == 6 else 'HK'
                    stocks[key] = {'code': code, 'name': name, 'market': market}

    return list(stocks.values())


def format_akshare_symbol(code: str, market: str) -> tuple[str, str]:
    """将股票代码格式化为 data_fetcher 需要的格式"""
    code = code.strip()
    if market == 'HK':
        if len(code) == 4:
            code = '0' + code
        return f"{code}.HK", f"({code}.HK)"
    elif market in ('SH', 'SZ'):
        return f"{market.lower()}{code}", f"({code}.{market})"
    else:
        return f"{market.lower()}{code}", f"({code}.{market})"


def main():
    if not STOCK_POOL_FILE.exists():
        print(f"错误: 股票池文件不存在: {STOCK_POOL_FILE}")
        sys.exit(1)

    print(f"读取股票池: {STOCK_POOL_FILE}")
    stocks = parse_stock_pool(STOCK_POOL_FILE)

    # 按市场过滤
    if ONLY_MARKETS == 'HK':
        stocks = [s for s in stocks if s['market'] == 'HK']
    elif ONLY_MARKETS == 'A':
        stocks = [s for s in stocks if s['market'] in ('SH', 'SZ')]

    print(f"解析到 {len(stocks)} 只股票/ETF\n")

    # 加载状态
    state = load_state()
    print(f"已加载状态文件\n")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, stock in enumerate(stocks, 1):
        code = stock['code']
        name = stock['name']
        market = stock['market']

        # 格式化输出文件名（港股加后缀避免与A股同名冲突）
        if market == 'HK':
            report_name = f"{name}_港股_波浪分析报告.md"
        else:
            report_name = f"{name}_波浪分析报告.md"
        report_path = OUTPUT_DIR / report_name

        # 增量模式：跳过已存在的
        if SKIP_EXISTING and report_path.exists():
            print(f"[{i}/{len(stocks)}] {name} ({code}.{market}) - 跳过（已存在）")
            skip_count += 1
            continue

        symbol, _ = format_akshare_symbol(code, market)

        print(f"\n{'='*60}")
        print(f"[{i}/{len(stocks)}] {name} ({code}.{market}) -> {symbol}")
        print(f"{'='*60}")

        try:
            analyzer = StockWaveAnalyzer(symbol, name, market)
            if not analyzer.fetch_data():
                print(f"  ❌ 数据获取失败")
                fail_count += 1
                continue

            analyzer.generate_report(report_path, state)
            success_count += 1

        except Exception as e:
            print(f"  ❌ 异常: {e}")
            traceback.print_exc()
            fail_count += 1

        # 避免请求过快
        time.sleep(0.5)

    # 保存状态
    try:
        save_state(state)
        print(f"\n状态已保存")
    except Exception as e:
        print(f"\n状态保存失败: {e}")

    print(f"\n{'='*60}")
    print(f"批量分析完成！")
    print(f"成功: {success_count}, 跳过: {skip_count}, 失败: {fail_count}")
    print(f"报告目录: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
