#!/usr/bin/env python3
"""
补跑缺失的股票分析，合并到已有报告中。
用法: python scripts/fix_missing_stocks.py
"""
import sys, os, json, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.daily_selection_agent import DailyStockSelectionAgent
from config.settings import settings

REPORT_JSON = settings.BASE_DIR / "每日选股" / "每日选股_2026-05-04.json"

def main():
    # Load existing report
    with open(REPORT_JSON, 'r', encoding='utf-8') as f:
        report = json.load(f)

    pool_codes = {s['stock_code']: s for s in report['stock_pool']}
    analyzed_codes = {s['stock_code'] for s in report['recommendations']}
    missing_codes = set(pool_codes.keys()) - analyzed_codes

    print(f"Pool: {len(pool_codes)}, Analyzed: {len(analyzed_codes)}, Missing: {len(missing_codes)}")

    if not missing_codes:
        print("All stocks already analyzed!")
        return

    # Build missing stock dicts (same format as stock_pool)
    missing_stocks = []
    for code in sorted(missing_codes):
        pool_entry = pool_codes[code]
        missing_stocks.append({
            "stock_code": code,
            "stock_name": pool_entry.get("stock_name", code),
            "industry": pool_entry.get("industry", "其他"),
            "source": pool_entry.get("source", "自选池"),
        })
        print(f"  Missing: {pool_entry.get('stock_name', code)} ({code}) [{pool_entry.get('industry', 'N/A')}]")

    # Create agent and analyze missing stocks
    agent = DailyStockSelectionAgent()
    new_results = agent._analyze_stock_pool(missing_stocks)

    print(f"\nSuccessfully analyzed: {len(new_results)}/{len(missing_stocks)}")

    # Merge results
    all_analyzed = report['recommendations'] + new_results
    print(f"Total stocks after merge: {len(all_analyzed)}")

    # Re-generate recommendations
    print("\nRe-generating recommendations with all stocks...")
    recommendations = agent._generate_recommendations(all_analyzed)

    # Update report
    report['recommendations'] = recommendations
    report['analyzed_stocks_count'] = len(recommendations)
    report['analyzed_stocks'] = [
        {"stock_code": r['stock_code'], "stock_name": r['stock_name']}
        for r in recommendations
    ]

    # Re-calculate summary
    scores = [r.get('combined_score', 0) or 0 for r in recommendations]
    report['summary'] = {
        'total_industries': len(report.get('favorable_industries', [])),
        'total_analyzed': len(recommendations),
        'total_recommended': len([r for r in recommendations if r.get('is_recommended')]),
        'avg_score': round(sum(scores) / len(scores), 2) if scores else 0,
    }

    # Update top picks
    report['top_picks'] = [r for r in recommendations if r.get('is_recommended')]

    # Save updated JSON
    with open(REPORT_JSON, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"Updated JSON saved: {REPORT_JSON}")

    # Regenerate markdown
    agent._generate_stock_pool_markdown_report(report, "每日选股_2026-05-04")
    print("Markdown report regenerated.")

    # Print final stats
    print(f"\n=== Final Stats ===")
    print(f"Total analyzed: {len(recommendations)}")
    print(f"Recommended: {len(report['top_picks'])}")
    print(f"Average score: {report['summary']['avg_score']}")

if __name__ == "__main__":
    main()
