#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雪球热帖内容增强工具

用于在资产配置建议板块中补充：
- 每日持仓变动的交易动作明细
- 当前配置的组合回测收益率
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.multi_source_fetcher import MultiSourceDataFetcher

DATE_PATTERN = re.compile(r'雪球热帖_(\d{8})\.md')


def parse_asset_allocation_section(content: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """提取资产配置建议区块，并返回前/中/后内容"""
    match = re.search(r'(## 💼 资产配置建议[\s\S]*?)(?=^## \S|\Z)', content, re.M)
    if not match:
        return None, None, None

    before = content[:match.start(1)]
    section = match.group(1).rstrip()
    after = content[match.end(1):]
    return before, section, after


def parse_allocation_table(section: str) -> List[Dict[str, str]]:
    """解析资产配置区块中的配置表格"""
    lines = [line.rstrip() for line in section.splitlines()]
    table_lines = [line for line in lines if line.strip().startswith('|')]

    if len(table_lines) < 3:
        return []

    rows = []
    for line in table_lines[2:]:
        if not line.strip() or set(line.strip()) <= {'|', '-'}:
            continue

        parts = [part.strip() for part in line.strip().strip('|').split('|')]
        if len(parts) < 5:
            continue

        # 归一化代码格式
        code = _normalize_symbol(parts[1])

        rows.append({
            'asset': parts[0],
            'code': code,
            'market': parts[2],
            'weight': parts[3],
            'reason': parts[4]
        })

    return rows


def _normalize_weight(weight: str) -> float:
    if not weight:
        return 0.0

    text = weight.replace('%', '').strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _normalize_symbol(code: str) -> str:
    code = code.strip().upper()

    if not code:
        return code

    # 已经有后缀格式，直接返回
    if '.' in code:
        return code

    # 处理带前缀的代码格式 (SZ300476 -> 300476.SZ, SH600519 -> 600519.SH)
    if code.startswith('SZ') and len(code) == 8 and code[2:].isdigit():
        return code[2:] + '.SZ'
    if code.startswith('SH') and len(code) == 8 and code[2:].isdigit():
        return code[2:] + '.SH'
    if code.startswith('HK') and len(code) == 8 and code[2:].isdigit():
        return code[2:].zfill(5) + '.HK'
    if code.startswith('BJ') and len(code) == 8 and code[2:].isdigit():
        return code[2:] + '.BJ'

    # 纯数字格式
    if code.isdigit():
        if len(code) <= 5:
            return code.zfill(5) + '.HK'

        if len(code) == 6:
            if code.startswith(('6', '5', '9')):
                return code + '.SH'
            return code + '.SZ'

    return code


def find_all_hot_post_files(watch_dir: Path) -> List[Path]:
    files = sorted(
        [p for p in watch_dir.glob('雪球热帖_*.md') if DATE_PATTERN.search(p.name)],
        key=lambda p: DATE_PATTERN.search(p.name).group(1)
    )
    return files


def find_previous_hot_post_file(filepath: Path, watch_dir: Path) -> Optional[Path]:
    files = find_all_hot_post_files(watch_dir)
    current_date = DATE_PATTERN.search(filepath.name)
    if not current_date:
        return None

    dates = [DATE_PATTERN.search(p.name).group(1) for p in files]
    try:
        idx = dates.index(current_date.group(1))
        if idx > 0:
            return files[idx - 1]
    except ValueError:
        return None

    return None


def find_asset_entry_exit(symbol: str, filepath: Path, watch_dir: Path) -> Tuple[Optional[datetime], Optional[datetime]]:
    files = find_all_hot_post_files(watch_dir)
    symbol = _normalize_symbol(symbol)
    entry_date = None
    exit_date = None

    for p in files:
        date_match = DATE_PATTERN.search(p.name)
        if not date_match:
            continue
        file_date = datetime.strptime(date_match.group(1), '%Y%m%d')

        with open(p, 'r', encoding='utf-8') as f:
            text = f.read()
        _, section, _ = parse_asset_allocation_section(text)
        codes = set()
        if section:
            alloc = parse_allocation_table(section)
            codes = {_normalize_symbol(item['code']) for item in alloc}

        if entry_date is None:
            if symbol in codes:
                entry_date = file_date
        else:
            if symbol not in codes:
                exit_date = file_date
                break

    return entry_date, exit_date


def build_position_change_summary(
    current_alloc: List[Dict[str, str]],
    previous_alloc: List[Dict[str, str]]
) -> str:
    if not previous_alloc:
        return "**每日持仓变化：**\n- 无昨日持仓数据，无法比较持仓变动。"

    previous_map = {item['code']: _normalize_weight(item['weight']) for item in previous_alloc}
    current_map = {item['code']: _normalize_weight(item['weight']) for item in current_alloc}

    lines = ["**每日持仓变化：**"]
    changes = []

    for item in current_alloc:
        code = item['code']
        current_weight = current_map.get(code, 0.0)
        prev_weight = previous_map.get(code)

        if prev_weight is None:
            changes.append(f"- 新进：{item['asset']} ({code})，配置比例 {current_weight:.0f}%")
            continue

        if abs(current_weight - prev_weight) < 0.5:
            continue

        if current_weight > prev_weight:
            changes.append(
                f"- 加仓：{item['asset']} ({code})，{prev_weight:.0f}% → {current_weight:.0f}%"
            )
        elif current_weight < prev_weight:
            changes.append(
                f"- 减仓：{item['asset']} ({code})，{prev_weight:.0f}% → {current_weight:.0f}%"
            )

    for item in previous_alloc:
        code = item['code']
        if code not in current_map:
            prev_weight = previous_map.get(code, 0.0)
            changes.append(f"- 卖出：{item['asset']} ({code})，{prev_weight:.0f}% → 0%")

    if not changes:
        lines.append("- 今日持仓总体维持，配置微调较小。")
    else:
        lines.extend(changes)

    return '\n'.join(lines)


def _extract_date_from_filename(filepath: Path) -> Optional[datetime]:
    match = DATE_PATTERN.search(filepath.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), '%Y%m%d')
    except ValueError:
        return None


def build_backtest_summary(
    allocation: List[Dict[str, str]],
    filepath: Path,
    watch_dir: Path,
    reference_date: Optional[datetime] = None
) -> str:
    if not allocation:
        return ""

    if reference_date is None:
        reference_date = datetime.now()

    fetcher = MultiSourceDataFetcher()
    lines = ["**配置回测结果：**"]
    asset_lines = []

    for item in allocation:
        symbol = _normalize_symbol(item['code'])
        entry_date, exit_date = find_asset_entry_exit(symbol, filepath, watch_dir)
        if not entry_date:
            asset_lines.append(f"- {item['asset']} ({symbol})：未找到首次纳入日期，无法回测。")
            continue

        end_date = exit_date or reference_date
        if end_date < entry_date:
            end_date = reference_date

        try:
            df = fetcher.fetch_stock_data(
                symbol,
                start_date=entry_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d')
            )
        except Exception as e:
            asset_lines.append(f"- {item['asset']} ({symbol})：数据获取失败，{e}")
            continue

        if df is None or df.empty:
            asset_lines.append(f"- {item['asset']} ({symbol})：无历史价格数据，无法回测。")
            continue

        df = df[['date', 'close']].copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.dropna(subset=['close']).sort_values('date')

        if len(df) < 5:
            asset_lines.append(
                f"- {item['asset']} ({symbol})：历史数据不足，入仓 {entry_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}。"
            )
            continue

        df = df.set_index('date')
        prices = df['close']

        # 计算交易天数（只计算交易日）
        trading_days = len(prices)
        # 最少需要5个交易日才有回测意义
        if trading_days < 5:
            asset_lines.append(
                f"- {item['asset']} ({symbol})：持有时间不足（{trading_days}个交易日），暂不回测。"
            )
            continue

        # 过滤异常价格：0、负数或单日变化超过90%（可能是数据错误或除权除息）
        valid_prices = prices[(prices > 0) & (prices < prices.quantile(0.99) * 2)]
        if len(valid_prices) < len(prices):
            # 如果过滤后数据严重减少，使用原始数据但添加警告
            if len(valid_prices) < 3:
                asset_lines.append(f"- {item['asset']} ({symbol})：价格数据异常，无法可靠回测。")
                continue
            prices = valid_prices

        # 计算收益率（防止除零）
        first_price = prices.iloc[0]
        if first_price <= 0:
            asset_lines.append(f"- {item['asset']} ({symbol})：起始价格异常，无法回测。")
            continue

        total_return = prices.iloc[-1] / first_price - 1
        days = (prices.index[-1] - prices.index[0]).days or 1

        # 如果收益率异常（单日变化超过50%且持有天数小于5天），可能是数据问题
        if abs(total_return) > 0.5 and days < 5:
            asset_lines.append(f"- {item['asset']} ({symbol})：价格波动异常（{total_return:+.2%}），数据可能有问题，暂不回测。")
            continue
        days = (prices.index[-1] - prices.index[0]).days or 1
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0
        drawdown = prices / prices.cummax() - 1
        max_drawdown = drawdown.min()
        returns = prices.pct_change().dropna()
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252) if returns.std() != 0 else 0

        period_label = f"{entry_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
        hold_label = "已清仓" if exit_date else "持有中"
        asset_lines.append(
            f"- {item['asset']} ({symbol})：{period_label}，累计收益 {total_return:+.2%}，年化 {annual_return:+.2%}，最大回撤 {max_drawdown:+.2%}，夏普 {sharpe_ratio:.2f}，{hold_label}。"
        )

    if not asset_lines:
        return ""

    lines.extend(asset_lines)
    lines.append("- 说明：每个标的从首次纳入建议后开始计算，直到已知清仓/当前持有日期；不含交易成本。")
    return '\n'.join(lines)


def enrich_asset_allocation_section(content: str, filepath: Path, watch_dir: Path) -> str:
    before, section, after = parse_asset_allocation_section(content)
    if section is None:
        return content

    current_alloc = parse_allocation_table(section)
    if not current_alloc:
        return content

    prev_file = find_previous_hot_post_file(filepath, watch_dir)
    previous_alloc = []
    if prev_file and prev_file.exists():
        prev_text = prev_file.read_text(encoding='utf-8')
        _, prev_section, _ = parse_asset_allocation_section(prev_text)
        if prev_section:
            previous_alloc = parse_allocation_table(prev_section)

    change_text = build_position_change_summary(current_alloc, previous_alloc)
    backtest_text = build_backtest_summary(
        current_alloc,
        filepath=filepath,
        watch_dir=watch_dir,
        reference_date=_extract_date_from_filename(filepath)
    )

    insert_block = change_text
    if backtest_text:
        if insert_block:
            insert_block += '\n\n' + backtest_text
        else:
            insert_block = backtest_text

    if not insert_block:
        return content

    if '**今日配置变动原因：**' in section:
        section = section.replace('**今日配置变动原因：**', f"{insert_block}\n\n**今日配置变动原因：**")
    elif '今日配置变动原因：' in section:
        section = section.replace('今日配置变动原因：', f"{insert_block}\n\n今日配置变动原因：")
    else:
        section = section + '\n\n' + insert_block

    return before + section + after
