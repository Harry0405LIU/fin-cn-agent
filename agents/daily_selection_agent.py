#!/usr/bin/env python3
"""
每日选股Agent (Daily Stock Selection Agent)
6步Pipeline:
1. 结合"经典理论"分析利好行业
2. 结合"滚雪球"信息和雪球数据找到行业龙头股
3. 构建选股池
4. 通过牛熊分析agent和技术分析agent对个股进行分析
5. 给出买入推荐评级
6. 每日生成文档
"""

import os
import re
import json
import time
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path

from .bull_agent import BullAgent
from .bear_agent import BearAgent
from .technical_analyzer import TechnicalAgent
from .debate_agent import DebateAgent
from .financial_data_fetcher import FinancialDataFetcher
from .company_quality_scorer import CompanyQualityScorer
from .analysis.etf_analyzer import ETFAnalyzer, get_recommended_etfs_with_pool, _normalize_etf_code
from .analysis.elliott_agent import ElliottWaveAgent
from .analysis.enhanced_elliott import EnhancedElliottAnalyzer
from .analysis.bottom_asset_screener import BottomAssetScreener
from chanlun.stock_analyzer import StockChanAnalyzer
from elliott.stock_analyzer import get_elliott_for_selection
from core.llm_client import LLMClient
from core.io_utils import read_text_with_retry
from config.settings import settings

DEFAULT_STOCKS = {
    "白酒与高端消费品": ["600519.SH"],
    "科技（AI与数字经济）": ["002230.SZ", "300059.SZ"],
    "半导体": ["688981.SH", "002371.SZ", "688012.SH"],
    "新能源": ["300750.SZ", "002594.SZ", "601012.SH", "300274.SZ"],
    "医药生物": ["603259.SH", "600276.SH", "300760.SZ"],
    "贵金属（黄金/铜）": ["601899.SH", "600547.SH"],
    "高股息公用事业": ["600900.SH", "601088.SH"],
    "消费电子": ["002475.SZ", "002241.SZ"],
    "金融": ["600030.SH", "601318.SH", "600036.SH", "002142.SZ"],
    "汽车": ["601633.SH"],
    "地产基建": ["600048.SH", "601668.SH"],
    "港股科技": ["09988.HK", "0700.HK", "3690.HK", "01810.HK"],
    "港股医药": ["2269.HK", "6160.HK"],
    "港股消费": ["6862.HK", "2331.HK"],
    "互联网/数字经济": ["300033.SZ"],
}

FALLBACK_INDUSTRIES = [
    {"name": "科技（AI与数字经济）", "reason": "政策大力支持，AI产业趋势明确", "weight": 0.9},
    {"name": "新能源", "reason": "碳中和目标，全球能源转型", "weight": 0.85},
    {"name": "半导体", "reason": "国产替代趋势，战略产业", "weight": 0.8},
    {"name": "消费电子", "reason": "消费复苏，新品周期", "weight": 0.75},
    {"name": "医药生物", "reason": "人口老龄化，创新药突破", "weight": 0.7},
    {"name": "贵金属（黄金/铜）", "reason": "避险需求，通胀对冲", "weight": 0.7},
    {"name": "金融", "reason": "估值修复，高股息", "weight": 0.65},
    {"name": "高股息公用事业", "reason": "防御属性，稳定分红", "weight": 0.6},
]

# 牛熊评级 → 基础评分（连续渐变，消除7分跳跃）
RATING_BASE_SCORE = {
    "强烈买入": 8.0,
    "买入": 5.0,
    "持有": 1.0,    # 持有≠0，表示"基本面尚可但缺乏催化剂"
    "卖出": -5.0,
    "强烈卖出": -8.0,
}

# 信心水平调节系数
CONFIDENCE_MULTIPLIER = {
    "高": 1.25,   # 高信心放大25%
    "中": 1.0,    # 中信心不变
    "低": 0.7,    # 低信心压缩30%
}

# 保留旧映射作为回退（兼容无confidence_level的旧缓存数据）
RATING_SCORE_MAP = {
    "强烈买入": 10,
    "买入": 7,
    "持有": 0,
    "卖出": -7,
    "强烈卖出": -10,
}

# 新评分体系权重配置（去掉微观买卖点评分）
# 技术面分析（40%）+ 价值面分析（60%）
NEW_STOCK_WEIGHTS = {
    "technical_analysis": 0.40,    # 技术面总权重40%
    "value_analysis": 0.60,        # 价值面总权重60%（原三维评分）
}

# 技术面子维度权重（去掉微观买卖点，重新分配为100%）
TECHNICAL_SUB_WEIGHTS = {
    "short_term_timing": 0.40,     # 短期时机评分 40%
    "medium_term_trend": 0.60,     # 中期趋势评分 60%
}

# 兼容旧权重配置
STOCK_WEIGHTS = {
    "technical": 0.30,
    "bull_bear": 0.30,
    "elliott": 0.25,
    "chan": 0.15,
}

# 统一评级阈值（个股与ETF共用）
RATING_THRESHOLDS = {
    "强烈推荐": 7.0,
    "推荐": 5.0,
    "中性": 0.0,
    "不推荐": -4.0,
    # < -4.0: 强烈不推荐
}


def _color_score(score, label=None):
    """为评分添加颜色高亮。高分红色，中分橙色，低分绿色（A股风格）。
    支持纯数字和带后缀的字符串（如 "7*", "0 (未评估)"）。
    """
    # Extract numeric value and suffix
    suffix = ""
    val = None
    if isinstance(score, (int, float)):
        val = float(score)
    elif isinstance(score, str):
        import re as _re
        m = _re.match(r'^(-?[\d.]+)(.*)', score.strip())
        if m:
            try:
                val = float(m.group(1))
                suffix = m.group(2)
            except ValueError:
                pass
    if val is None:
        return str(score) if label is None else f"{label}{score}"
    # Display: integers as int, floats with 1 decimal
    if isinstance(score, float):
        text = f"{val:.1f}"
    else:
        text = str(int(val)) if val == int(val) else f"{val:.1f}"
    if suffix:
        text = f"{text}{suffix}"
    if label is not None:
        text = f"{label}{text}"
    if val >= 7:
        return f'<span style="color:#e74c3c;font-weight:bold">{text}</span>'
    elif val >= 4:
        return f'<span style="color:#e67e22;font-weight:bold">{text}</span>'
    elif val <= -4:
        return f'<span style="color:#27ae60">{text}</span>'
    return text


def _highlight_dy_cape(dv, cape, text):
    """股息率>4% 且 CAPE<=20 同时满足时，高亮显示（金色背景+加粗）。"""
    if dv is not None and cape is not None and isinstance(dv, (int, float)) and isinstance(cape, (int, float)):
        if dv > 4 and cape <= 20:
            return f'<span style="background-color:#fff3cd;font-weight:bold">{text}</span>'
    return text


def _to_akshare_format(stock_code: str) -> tuple:
    """将选股agent的 stock_code 格式转换为 akshare 格式。

    Args:
        stock_code: 如 '600519.SH' / '01810.HK' / '000858.SZ'
    Returns:
        (symbol, market) 如 ('sh600519', 'SH') / ('01810.HK', 'HK')
    """
    code = stock_code.strip()
    if '.' in code:
        pure, market = code.rsplit('.', 1)
        market = market.upper()
    else:
        pure = code
        if code.startswith(('6', '5', '9')):
            market = 'SH'
        elif code.startswith(('0', '3', '2')):
            market = 'SZ'
        else:
            market = 'HK'

    if market == 'HK':
        if len(pure) == 4:
            pure = '0' + pure
        return (f"{pure}.HK", 'HK')
    elif market == 'SH':
        return (f"sh{pure}", 'SH')
    elif market == 'SZ':
        return (f"sz{pure}", 'SZ')
    else:
        return (f"{market.lower()}{pure}", market)


def _compute_chan_score(buy_points: list, sell_points: list) -> float:
    """根据缠论活跃买卖点计算评分。

    评分逻辑:
    - 一买(Type 1): +3.0 (趋势衰竭反转，最强买点)
    - 二买(Type 2): +2.0 (回踩确认，次强买点)
    - 三买(Type 3): +1.0 (突破回踩，较弱买点)
    - 一卖(Type 1): -3.0
    - 二卖(Type 2): -2.0
    - 三卖(Type 3): -1.0
    - 多信号叠加，上限 ±5.0

    只考虑最近20个交易日内出现的买卖点。
    """
    if not buy_points and not sell_points:
        return 0.0

    cutoff_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')

    buy_type_scores = {1: 3.0, 2: 2.0, 3: 1.0}
    sell_type_scores = {1: -3.0, 2: -2.0, 3: -1.0}

    score = 0.0
    for bp in buy_points:
        if bp.get("date", "") >= cutoff_date:
            score += buy_type_scores.get(bp.get("type", 0), 0)

    for sp in sell_points:
        if sp.get("date", "") >= cutoff_date:
            score += sell_type_scores.get(sp.get("type", 0), 0)

    return max(-5.0, min(5.0, score))


def _format_chan_signals(buy_points: list, sell_points: list) -> str:
    """格式化缠论买卖点显示文字，用于报告表格列。

    仅显示最近20个交易日内出现的买卖点，例如:
    - "买1(h),买3(m)" 表示近20日有一买(高置信度)和三买(中置信度)
    - "卖2" 表示近20日有二卖
    - "—" 表示近20日无活跃信号

    置信度: h=high, m=medium, l=low
    """
    cutoff_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')

    recent_buys = [bp for bp in buy_points if bp.get("date", "") >= cutoff_date]
    recent_sells = [sp for sp in sell_points if sp.get("date", "") >= cutoff_date]

    if not recent_buys and not recent_sells:
        return "—"

    parts = []
    if recent_buys:
        # 按类型分组，取最高置信度
        buy_by_type = {}
        conf_priority = {"high": 3, "medium": 2, "low": 1, "N/A": 0}
        conf_code_map = {"high": "h", "medium": "m", "low": "l", "N/A": ""}
        for bp in recent_buys:
            btype = bp.get("type", 0)
            conf = bp.get("confidence", "N/A")
            priority = conf_priority.get(conf, 0)
            code = conf_code_map.get(conf, "")
            # 同类型取最高置信度（priority越大越高）
            if btype not in buy_by_type or priority > buy_by_type[btype][0]:
                buy_by_type[btype] = (priority, code)
        buy_types = sorted(buy_by_type.keys())
        parts.append(",".join(f"买{t}({buy_by_type[t][1]})" for t in buy_types))
    if recent_sells:
        sell_by_type = {}
        conf_priority = {"high": 3, "medium": 2, "low": 1, "N/A": 0}
        conf_code_map = {"high": "h", "medium": "m", "low": "l", "N/A": ""}
        for sp in recent_sells:
            stype = sp.get("type", 0)
            conf = sp.get("confidence", "N/A")
            priority = conf_priority.get(conf, 0)
            code = conf_code_map.get(conf, "")
            if stype not in sell_by_type or priority > sell_by_type[stype][0]:
                sell_by_type[stype] = (priority, code)
        sell_types = sorted(sell_by_type.keys())
        parts.append(",".join(f"卖{t}({sell_by_type[t][1]})" for t in sell_types))

    return ",".join(parts) if parts else "—"


def _chan_pivot_position(current_price: float, last_pivot: dict) -> str:
    """判断当前价格相对于最新中枢的位置。"""
    if not last_pivot:
        return "无中枢"
    zg = last_pivot.get("ZG", 0)
    zd = last_pivot.get("ZD", 0)
    if current_price > zg:
        return f"中枢上方(>{zg:.2f})"
    elif current_price < zd:
        return f"中枢下方(<{zd:.2f})"
    else:
        return f"中枢内[{zd:.2f},{zg:.2f}]"


class DailyStockSelectionAgent:

    # 每日全量分析时跳过的行业（按前缀匹配）。
    # 「周金涛底部」系列由 BottomAssetScreener 自动维护，动辄 700+ 只小盘冷门股，
    # 不值得每天做牛熊深度辩论；它们仍保留在股票池文件里，供每周/专题回顾。
    EXCLUDED_ANALYSIS_INDUSTRY_PREFIXES = ("周金涛底部",)

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        base_dir: Optional[Path] = None
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.base_dir = base_dir or settings.BASE_DIR

        self.classic_theory_dir = self.base_dir / "经典理论"
        self.xueqiu_dir = self.base_dir / "滚雪球"
        self.daily_selection_dir = self.base_dir / "每日选股"
        self.debate_report_dir = self.base_dir / "研报" / "个股分析"
        self.stock_pool_file = self.base_dir / "自选股票池.md"

        for dir_path in [self.classic_theory_dir, self.xueqiu_dir, self.daily_selection_dir, self.debate_report_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Ensure stock pool file exists
        if not self.stock_pool_file.exists():
            self._init_stock_pool_file()

        # Unified LLM client - auto-detects Claude Code / Anthropic / DeepSeek / OpenAI
        self.llm_client = LLMClient(model=model)

        if not self.llm_client.is_available():
            raise RuntimeError(
                "未找到LLM API Key！请设置以下环境变量之一：\n"
                "  ANTHROPIC_AUTH_TOKEN (Claude Code) 或 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY 或 OPENAI_API_KEY"
            )

        # Sub-agents initialized with LLM
        self.client = self.llm_client
        self.bull_agent = BullAgent(model=model)
        self.bear_agent = BearAgent(model=model)
        self.debate_agent = DebateAgent(
            model=model, rounds=3, output_dir=self.debate_report_dir
        )
        self.financial_fetcher = FinancialDataFetcher()
        self.company_quality_scorer = CompanyQualityScorer(model=model)  # 新增：三维评分引擎
        self._dividend_yield_cache = {}  # In-memory cache for current run
        self._dividend_yield_cache_file = self.daily_selection_dir / "dividend_yield_cache.json"
        self._industry_cache_file = self.daily_selection_dir / "industry_cache.json"
        self._load_dividend_yield_cache()  # Load from file if from today
        self._cape_cache = {}  # In-memory cache for CAPE (Cyclically Adjusted P/E)
        self._cape_cache_file = self.daily_selection_dir / "cape_cache.json"
        self._load_cape_cache()  # Load from file if from today
        self._elliott_ema_cache = {}  # Multi-day EMA cache for elliott score smoothing

        self.technical_agent = TechnicalAgent(api_key=self.api_key, model=model)
        self.etf_analyzer = ETFAnalyzer()
        self.elliott_agent = ElliottWaveAgent()
        self.enhanced_elliott_analyzer = EnhancedElliottAnalyzer()

    # ================================================================
    # Main Pipeline
    # ================================================================

    def run_stock_pool_selection(self, target_date: str = None) -> Dict[str, Any]:
        """Run full pipeline on ALL stocks from the stock pool file.

        This method evaluates every stock already in the stock pool file,
        ensuring comprehensive analysis including A-shares, HK stocks, and ETFs.

        Args:
            target_date: Optional date string YYYY-MM-DD. Defaults to today.
        """
        selection_date = target_date or datetime.now().strftime("%Y-%m-%d")

        print(f"\n{'='*60}")
        print(f"自选股票池全量评估 - {selection_date}")
        print(f"{'='*60}\n")

        # Step 1: 结合"经典理论"分析利好行业
        print("=== 第1步：结合经典理论分析利好行业 ===")
        favorable_industries = self._analyze_favorable_industries()
        self._save_industry_cache(favorable_industries)  # Cache for daily updates

        # Step 1.5: 从雪球热帖发现新股票，同步到自选池
        print("\n=== 第1.5步：扫描雪球热帖发现高热度股票 ===")
        xq_discovered = self._discover_xueqiu_stocks()
        if xq_discovered:
            print(f"  从雪球热帖发现 {len(xq_discovered)} 只潜在高热度股票")
            # Merge into pool file
            pool_before = self._read_stock_pool_file()
            added_count = 0
            for xq_stock in xq_discovered:
                code = xq_stock["code"]
                name = xq_stock["name"]
                industry = xq_stock.get("industry", "其他")
                # Check if already in pool
                all_existing = {e["code"] for entries in pool_before.values() for e in entries}
                if code in all_existing:
                    continue
                if industry not in pool_before:
                    pool_before[industry] = []
                pool_before[industry].append({"code": code, "name": name})
                print(f"    + {name} ({code}) -> {industry}")
                added_count += 1
            if added_count > 0:
                self._write_stock_pool_file(pool_before)
                print(f"  已追加 {added_count} 只新股票到自选池文件")
            else:
                print(f"  所有雪球热帖股票已存在自选池中")
        else:
            print(f"  未从雪球热帖发现新股票")

        # Step 1.7: 周金涛底部资产筛选
        print("\n=== 第1.7步：周金涛底部资产筛选 ===")
        bottom_results = None
        try:
            bottom_screener = BottomAssetScreener(config={"model": self.model})
            bottom_results = bottom_screener.run()
            bottom_ranked = bottom_results.get("data", {}).get("ranked_assets", [])
            print(f"  底部资产筛选完成，推荐 {len(bottom_ranked)} 只")
            for i, asset in enumerate(bottom_ranked[:5], 1):
                print(f"    {i}. {asset.get('code')} {asset.get('name')} "
                      f"涨幅:{asset.get('gain_pct',0):.1f}% 评分:{asset.get('composite_score',0)}")
        except Exception as e:
            print(f"  底部资产筛选失败: {e}")

        # Step 2: 读取自选股票池全部股票
        print("\n=== 第2步：读取自选股票池 ===")
        file_pool = self._read_stock_pool_file()
        stock_pool = self._convert_pool_dict_to_list(file_pool)
        self._resolve_stock_names(stock_pool)
        print(f"  自选股票池共 {len(stock_pool)} 只股票（含A股、港股、ETF）")
        stock_pool = self._filter_daily_analysis_pool(stock_pool)

        # Separate analyzable stocks (A-share + HK) from ETFs
        analyzable_stocks = []
        etf_list = []
        for s in stock_pool:
            code = s["stock_code"]
            # ETF/LOF codes: 6 digits, starting with 51/56/58 (SH ETF) or 15/16 (SZ ETF/LOF)
            pure_code = code.split(".")[0] if "." in code else code
            if len(pure_code) == 6 and (pure_code.startswith("5") or pure_code.startswith("15") or pure_code.startswith("16")):
                # Normalize ETF code with suffix
                if "." not in code:
                    s["stock_code"] = _normalize_etf_code(code)
                etf_list.append(s)
            else:
                analyzable_stocks.append(s)

        print(f"  可分析股票: {len(analyzable_stocks)} 只 (A股+港股)")
        print(f"  ETF基金: {len(etf_list)} 只 (将进行三维分析)")

        # Step 2.5: 显示周金涛底部资产信息（仅供参考，不筛选）
        print("\n=== 第2.5步：周金涛底部资产信息 ===")
        if bottom_results and bottom_results.get("data"):
            bottom_ranked = bottom_results.get("data", {}).get("ranked_assets", [])
            bottom_codes = set(asset.get("code") for asset in bottom_ranked)
            print(f"  周金涛底部资产共 {len(bottom_codes)} 只")

            # 统计股票池中有多少底部资产
            bottom_in_pool = [s for s in analyzable_stocks if s["stock_code"] in bottom_codes]
            print(f"  股票池中的底部资产: {len(bottom_in_pool)} 只")

            if bottom_ranked:
                print(f"  底部资产示例（前5只）:")
                for i, asset in enumerate(bottom_ranked[:5], 1):
                    print(f"    {i}. {asset.get('name')} ({asset.get('code')}) - 涨幅:{asset.get('gain_pct',0):.1f}%")
        else:
            print("  未获取到周金涛底部资产数据")

        for etf in etf_list:
            print(f"    - {etf.get('stock_name', etf['stock_code'])} ({etf['stock_code']})")

        # Step 3: 构建选股池
        print(f"\n=== 第3步：构建选股池（{len(analyzable_stocks)}只股票） ===")
        print(f"  将对所有股票进行技术分析和价值分析（LLM三维评分）")
        for s in analyzable_stocks[:10]:  # 只显示前10只
            print(f"  - {s.get('stock_name', s['stock_code'])} ({s['stock_code']}) [{s.get('industry', 'N/A')}]")
        if len(analyzable_stocks) > 10:
            print(f"  ... 还有 {len(analyzable_stocks) - 10} 只股票")

        # Step 4: 通过牛熊分析agent和技术分析agent对个股进行分析
        print(f"\n=== 第4步：分析选股池（共{len(analyzable_stocks)}只股票，含牛熊分析） ===")
        analyzed_stocks = self._analyze_stock_pool(analyzable_stocks)

        # Step 5: 给出买入推荐评级
        print(f"\n=== 第5步：综合评分和推荐 ===")
        recommendations = self._generate_recommendations(analyzed_stocks)

        # Step 5.2: 标记"时间的朋友"（不再硬筛选——保留全部推荐，按综合评分排序；
        #           时间的朋友通过 is_time_friend 标志在报告中打标 ★）
        print(f"\n=== 第5.2步：标记时间的朋友 ===")
        time_friend_count = sum(1 for rec in recommendations if rec.get("is_time_friend"))
        print(f"  全部推荐: {len(recommendations)} 只，其中时间的朋友: {time_friend_count} 只（已打标，不过滤）")
        recommendations_filtered = recommendations

        # Show filtered stocks
        for i, rec in enumerate(recommendations_filtered[:10], 1):
            print(f"    {i}. {rec.get('stock_name', rec['stock_code'])} ({rec['stock_code']})")

        # Step 5.5: 分析ETF (三维评分：基本面+技术+波浪)
        etf_recommendations = []
        if etf_list or True:  # Always run to include recommended ETFs
            print(f"\n=== 第5.5步：ETF三维分析 ===")
            # Merge pool ETFs with recommended ETFs
            all_etfs = get_recommended_etfs_with_pool(etf_list)
            print(f"  待分析ETF: {len(all_etfs)} 只 (自选池{len(etf_list)} + 推荐{len(all_etfs)-len(etf_list)})")
            etf_recommendations = self.etf_analyzer.analyze_etf_pool(
                all_etfs, favorable_industries
            )
            print(f"\nETF分析完成，共 {len(etf_recommendations)} 只ETF评分：")
            for i, rec in enumerate(etf_recommendations[:5], 1):
                print(
                    f"  {i}. {rec['stock_name']} ({rec['stock_code']}) - "
                    f"综合: {rec['combined_score']}, "
                    f"基本面: {rec['fundamental_score']}, "
                    f"技术: {rec['tech_score']}, "
                    f"波浪: {rec['elliott_score']}, "
                    f"评级: {rec['rating']}"
                )

        # Step 5.8: 生成大师深度报告（仅推荐股，默认关闭）
        print(f"\n=== 第5.8步：生成大师深度报告 ===")
        if self.debate_agent.enable_master_report:
            recommended_stocks = [r for r in recommendations_filtered if r.get("is_recommended")]
            print(f"  大师报告已启用，将为 {len(recommended_stocks)} 只推荐股生成...")
            master_reports = {}
            for rec in recommended_stocks:
                stock_code = rec["stock_code"]
                stock_name = rec.get("stock_name", stock_code)
                code_suffix = stock_code.split(".")[0]
                try:
                    # 从磁盘加载最新 debate JSON
                    candidates = sorted(
                        list(self.debate_report_dir.rglob(f"*_{code_suffix}_多空辩论报告.json"))
                        + list(self.debate_report_dir.rglob(f"*_{stock_code}_多空辩论报告.json"))
                        + (list(self.debate_report_dir.rglob(f"*_{str(int(code_suffix))}.HK_多空辩论报告.json")) if stock_code.endswith(".HK") and str(int(code_suffix)) + ".HK" != stock_code else []),
                        key=lambda f: f.stat().st_mtime, reverse=True
                    )
                    if candidates:
                        with open(candidates[0], "r", encoding="utf-8") as f:
                            debate_json = json.load(f)
                        print(f"    生成 {stock_name} 大师报告...")
                        report_md = self.debate_agent.generate_master_report(
                            stock_name, stock_code, debate_json
                        )
                        # 保存大师报告
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        stock_name_safe = stock_name.replace(" ", "_").replace("/", "_")
                        master_filename = f"{timestamp}_{stock_name_safe}_{stock_code}_大师报告.md"
                        master_path = self.debate_report_dir / master_filename
                        master_path.write_text(report_md, encoding="utf-8")
                        print(f"    大师报告已保存: {master_filename}")
                        master_reports[stock_code] = master_filename
                    else:
                        print(f"    ⚠ {stock_name} 未找到辩论报告，跳过")
                except Exception as e:
                    print(f"    ⚠ {stock_name} 大师报告生成失败: {str(e)[:80]}")
            if master_reports:
                print(f"  大师报告完成: {len(master_reports)} 份")
        else:
            print(f"  大师报告未启用（设置 ENABLE_MASTER_REPORT=true 开启），跳过")

        print(f"\n=== 第6步：生成每日选股报告 ===")
        report = self._generate_daily_report(
            selection_date, favorable_industries, analyzable_stocks, analyzed_stocks, recommendations_filtered
        )

        # Add ETF recommendations to report
        report["etf_recommendations"] = etf_recommendations
        report["etf_list"] = [
            {"stock_name": e.get("stock_name", ""), "stock_code": e["stock_code"], "industry": e.get("industry", "ETF基金")}
            for e in etf_list
        ]
        report["etf_summary"] = {
            "total_etfs": len(etf_recommendations),
            "recommended": len([e for e in etf_recommendations if e["is_recommended"]]),
            "top_etf": etf_recommendations[0] if etf_recommendations else None,
        }

        # Add bottom asset results to report
        if bottom_results and bottom_results.get("success"):
            report["bottom_assets"] = bottom_results.get("data", {})

        # Regenerate markdown with ETF section
        self._generate_stock_pool_markdown_report(report, f"每日选股_{selection_date}")

        # Re-save JSON with ETF data included
        json_filename = f"每日选股_{selection_date}.json"
        json_path = self.daily_selection_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"JSON报告已更新(含ETF): {json_path}")

        # Sync new stocks back to the stock pool file
        self._sync_stock_pool_file(analyzed_stocks)

        return report

    def run_daily_update(self) -> Dict[str, Any]:
        """Efficient daily update: only re-run technical analysis, reuse cached data.

        Optimization rules:
        - Industry analysis: Load from same-day cache (skip LLM call)
        - Technical analysis: Always re-run, but reuse cached OHLCV data (same-day)
        - Bull/bear analysis: Use cached report if financial period unchanged
        - Dividend yield: Use same-day file cache
        """
        selection_date = datetime.now().strftime("%Y-%m-%d")

        print(f"\n{'='*60}")
        print(f"每日选股增量更新 - {selection_date}")
        print(f"{'='*60}\n")

        # Step 1: Load cached industry analysis (skip LLM)
        print("=== 第1步：加载缓存的利好行业 ===")
        favorable_industries = self._load_industry_cache()
        if favorable_industries is None:
            print("  缓存不可用，执行完整行业分析...")
            favorable_industries = self._analyze_favorable_industries()
            self._save_industry_cache(favorable_industries)
        else:
            print(f"  使用今日缓存: {len(favorable_industries)} 个利好行业")

        # Step 1.7: 周金涛底部资产筛选（每日更新重新评估）
        print("\n=== 第1.7步：周金涛底部资产筛选（增量更新） ===")
        bottom_results = None
        try:
            bottom_screener = BottomAssetScreener(config={"model": self.model})
            bottom_results = bottom_screener.run()
            bottom_ranked = bottom_results.get("data", {}).get("ranked_assets", [])
            print(f"  底部资产筛选完成，推荐 {len(bottom_ranked)} 只")
        except Exception as e:
            print(f"  底部资产筛选失败: {e}")

        # Step 2-6: Same as run_stock_pool_selection
        print("\n=== 第2步：读取自选股票池 ===")
        file_pool = self._read_stock_pool_file()
        stock_pool = self._convert_pool_dict_to_list(file_pool)
        self._resolve_stock_names(stock_pool)
        print(f"  自选股票池共 {len(stock_pool)} 只股票（含A股、港股、ETF）")
        stock_pool = self._filter_daily_analysis_pool(stock_pool)

        analyzable_stocks = []
        etf_list = []
        for s in stock_pool:
            code = s["stock_code"]
            pure_code = code.split(".")[0] if "." in code else code
            if len(pure_code) == 6 and (pure_code.startswith("5") or pure_code.startswith("15") or pure_code.startswith("16")):
                if "." not in code:
                    s["stock_code"] = _normalize_etf_code(code)
                etf_list.append(s)
            else:
                analyzable_stocks.append(s)

        print(f"  可分析股票: {len(analyzable_stocks)} 只 (A股+港股)")
        print(f"  ETF基金: {len(etf_list)} 只")

        # Step 2.5: 显示周金涛底部资产信息（仅供参考，不筛选）
        print("\n=== 第2.5步：周金涛底部资产信息 ===")
        if bottom_results and bottom_results.get("data"):
            bottom_ranked = bottom_results.get("data", {}).get("ranked_assets", [])
            bottom_codes = set(asset.get("code") for asset in bottom_ranked)
            print(f"  周金涛底部资产共 {len(bottom_codes)} 只")

            # 统计股票池中有多少底部资产
            bottom_in_pool = [s for s in analyzable_stocks if s["stock_code"] in bottom_codes]
            print(f"  股票池中的底部资产: {len(bottom_in_pool)} 只")

            if bottom_ranked:
                print(f"  底部资产示例（前5只）:")
                for i, asset in enumerate(bottom_ranked[:5], 1):
                    print(f"    {i}. {asset.get('name')} ({asset.get('code')}) - 涨幅:{asset.get('gain_pct',0):.1f}%")
        else:
            print("  未获取到周金涛底部资产数据")

        print(f"\n=== 第3步：构建选股池（{len(analyzable_stocks)}只股票） ===")
        print(f"  将对所有股票进行技术分析和价值分析（含缓存优化）")

        print(f"\n=== 第4步：分析选股池（技术分析+缓存牛熊） ===")
        analyzed_stocks = self._analyze_stock_pool(analyzable_stocks)

        print(f"\n=== 第5步：综合评分和推荐 ===")
        recommendations = self._generate_recommendations(analyzed_stocks)

        # Step 5.2: 标记"时间的朋友"（不再硬筛选——保留全部推荐，按综合评分排序；
        #           时间的朋友通过 is_time_friend 标志在报告中打标 ★）
        print(f"\n=== 第5.2步：标记时间的朋友 ===")
        time_friend_count = sum(1 for rec in recommendations if rec.get("is_time_friend"))
        print(f"  全部推荐: {len(recommendations)} 只，其中时间的朋友: {time_friend_count} 只（已打标，不过滤）")
        recommendations_filtered = recommendations

        # Show filtered stocks
        for i, rec in enumerate(recommendations_filtered[:10], 1):
            print(f"    {i}. {rec.get('stock_name', rec['stock_code'])} ({rec['stock_code']})")

        print(f"\n=== 第5.5步：ETF三维分析 ===")
        etf_recommendations = []
        all_etfs = get_recommended_etfs_with_pool(etf_list)
        print(f"  待分析ETF: {len(all_etfs)} 只")
        etf_recommendations = self.etf_analyzer.analyze_etf_pool(
            all_etfs, favorable_industries
        )

        # Step 5.8: 生成大师深度报告（仅推荐股，默认关闭）
        print(f"\n=== 第5.8步：生成大师深度报告 ===")
        if self.debate_agent.enable_master_report:
            recommended_stocks = [r for r in recommendations_filtered if r.get("is_recommended")]
            print(f"  大师报告已启用，将为 {len(recommended_stocks)} 只推荐股生成...")
            master_reports = {}
            for rec in recommended_stocks:
                stock_code = rec["stock_code"]
                stock_name = rec.get("stock_name", stock_code)
                code_suffix = stock_code.split(".")[0]
                try:
                    # 从磁盘加载最新 debate JSON
                    candidates = sorted(
                        list(self.debate_report_dir.rglob(f"*_{code_suffix}_多空辩论报告.json"))
                        + list(self.debate_report_dir.rglob(f"*_{stock_code}_多空辩论报告.json"))
                        + (list(self.debate_report_dir.rglob(f"*_{str(int(code_suffix))}.HK_多空辩论报告.json")) if stock_code.endswith(".HK") and str(int(code_suffix)) + ".HK" != stock_code else []),
                        key=lambda f: f.stat().st_mtime, reverse=True
                    )
                    if candidates:
                        with open(candidates[0], "r", encoding="utf-8") as f:
                            debate_json = json.load(f)
                        print(f"    生成 {stock_name} 大师报告...")
                        report_md = self.debate_agent.generate_master_report(
                            stock_name, stock_code, debate_json
                        )
                        # 保存大师报告
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        stock_name_safe = stock_name.replace(" ", "_").replace("/", "_")
                        master_filename = f"{timestamp}_{stock_name_safe}_{stock_code}_大师报告.md"
                        master_path = self.debate_report_dir / master_filename
                        master_path.write_text(report_md, encoding="utf-8")
                        print(f"    大师报告已保存: {master_filename}")
                        master_reports[stock_code] = master_filename
                    else:
                        print(f"    ⚠ {stock_name} 未找到辩论报告，跳过")
                except Exception as e:
                    print(f"    ⚠ {stock_name} 大师报告生成失败: {str(e)[:80]}")
            if master_reports:
                print(f"  大师报告完成: {len(master_reports)} 份")
        else:
            print(f"  大师报告未启用（设置 ENABLE_MASTER_REPORT=true 开启），跳过")

        print(f"\n=== 第6步：生成每日选股报告 ===")
        report = self._generate_daily_report(
            selection_date, favorable_industries, analyzable_stocks, analyzed_stocks, recommendations_filtered
        )

        report["etf_recommendations"] = etf_recommendations
        report["etf_list"] = [
            {"stock_name": e.get("stock_name", ""), "stock_code": e["stock_code"], "industry": e.get("industry", "ETF基金")}
            for e in etf_list
        ]
        report["etf_summary"] = {
            "total_etfs": len(etf_recommendations),
            "recommended": len([e for e in etf_recommendations if e["is_recommended"]]),
            "top_etf": etf_recommendations[0] if etf_recommendations else None,
        }

        self._generate_stock_pool_markdown_report(report, f"每日选股_{selection_date}")

        # Re-save JSON with ETF data included
        json_filename = f"每日选股_{selection_date}.json"
        json_path = self.daily_selection_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"JSON报告已更新(含ETF): {json_path}")

        self._sync_stock_pool_file(analyzed_stocks)

        return report

    def _load_industry_cache(self) -> Optional[List[Dict[str, Any]]]:
        """Load industry analysis from same-day cache file."""
        try:
            if self._industry_cache_file.exists():
                with open(self._industry_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cache_date = data.get("date", "")
                today = datetime.now().strftime("%Y-%m-%d")
                if cache_date == today:
                    return data.get("industries")
        except Exception:
            pass
        return None

    def _save_industry_cache(self, industries: List[Dict[str, Any]]):
        """Save industry analysis to cache file with today's date."""
        try:
            data = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "industries": industries,
            }
            with open(self._industry_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _convert_pool_dict_to_list(self, pool_dict: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
        """Convert stock pool dict {industry: [{code, name}]} to list of stock entries.

        Deduplicates by stock code — when the same stock appears under multiple
        industries (e.g. original category + 周金涛底部), the first occurrence wins.
        """
        stock_list = []
        seen_codes = set()
        for industry, entries in pool_dict.items():
            for entry in entries:
                code = entry["code"]
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                name = entry.get("name", "")
                stock_list.append({
                    "stock_code": code,
                    "stock_name": name if name else f"{industry}代表股",
                    "industry": industry,
                    "source": "自选股票池",
                })
        return stock_list

    def _filter_daily_analysis_pool(self, stock_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """剔除每日分析中无需深度辩论的行业（如周金涛底部系列），减少 LLM token 消耗。

        这些股票仍保留在自选股票池文件中，只是不参与每日全量牛熊辩论。
        """
        prefixes = tuple(self.EXCLUDED_ANALYSIS_INDUSTRY_PREFIXES)
        kept = []
        excluded_count = 0
        for s in stock_pool:
            industry = s.get("industry", "") or ""
            if industry.startswith(prefixes):
                excluded_count += 1
            else:
                kept.append(s)
        if excluded_count:
            print(f"  已跳过 {excluded_count} 只「周金涛底部」系列股票（保留在股票池文件，不做每日深度分析）")
        return kept

    def _generate_stock_pool_markdown_report(self, report: Dict[str, Any], filename: str):
        """Generate comprehensive markdown report for stock pool evaluation."""
        md_lines = [
            f"# 每日选股报告 - {report['selection_date']}",
            "",
            f"**生成时间**: {report['generation_time']}",
            f"**选股日期**: {report['selection_date']}",
            f"**评分算法**: v2 (连续渐变评分 + 波浪平滑)",
            "",
            "---",
            "",
            "## 选股概览",
            "",
            f"- 分析行业数: {report['summary']['total_industries']}",
            f"- 分析股票数: {report['summary']['total_analyzed']}",
            f"- 推荐股票数: {report['summary']['total_recommended']}",
            f"- 平均评分: {report['summary']['avg_score']:.2f}",
            f"- ETF基金数: {len(report.get('etf_list', []))}",
            f"- ETF分析数: {report.get('etf_summary', {}).get('total_etfs', 0)}",
            "",
            "---",
            "",
            "## 利好行业（经典理论）",
            "",
        ]

        for industry in report["favorable_industries"]:
            md_lines.extend([
                f"- **{industry['name']}**",
                f"  - 理由: {industry['reason']}",
                f"  - 权重: {industry.get('weight', 0.5)}",
                "",
            ])

        # Top picks section
        md_lines.extend(["---", "", "## 重点推荐", ""])
        top_picks = report.get("top_picks", [])
        if top_picks:
            for i, pick in enumerate(top_picks, 1):
                bb_score_display = str(pick.get('bull_bear_score', 0))
                if pick.get('bull_bear_missing'):
                    bb_score_display += " (未评估)"
                _dy = pick.get('dividend_yield')
                _cape = pick.get('cape')
                _dy_d = f"{_dy}%" if _dy is not None else "-"
                _cape_d = f"{_cape:.1f}" if _cape is not None else "-"
                md_lines.extend([
                    f"### {i}. {pick['stock_name']} ({pick['stock_code']}) - {pick['rating']}",
                    "",
                    f"- **综合评分**: {_color_score(pick['combined_score'])}",
                    f"- **技术评分**: {_color_score(pick['tech_score'])}",
                    f"- **牛熊评分**: {_color_score(bb_score_display)}",
                    f"- **波浪评分**: {_color_score(pick.get('elliott_score', 0))}{' (无数据)' if not pick.get('has_elliott', False) else ''}",
                    f"- **风险等级**: {pick.get('risk_level', 'N/A')}",
                    f"- **操作建议**: {pick.get('operation_suggestion', 'N/A')}",
                    f"- **股息率**: {_highlight_dy_cape(_dy, _cape, _dy_d)}",
                    f"- **CAPE**: {_highlight_dy_cape(_dy, _cape, _cape_d)}",
                    f"- **行业**: {pick.get('industry', 'N/A')}",
                    f"- **双重看多**: {'是 ★' if pick.get('both_positive') else '否'}",
                    f"- **推荐理由**: {pick['recommendation_reason']}",
                    "",
                ])
        else:
            md_lines.append("今日无重点推荐股票。\n")

        # 买卖点建议模块
        md_lines.extend(["---", "", "## 买卖点建议", ""])

        # Get recommendations early for buy/sell point analysis
        recommendations = report.get("recommendations", [])

        # 筛选出有缠论买卖点的股票
        buy_sell_stocks = []
        for rec in recommendations:
            chan_signals = rec.get("chan_signals", "—")
            if chan_signals != "—" and chan_signals != "":
                buy_sell_stocks.append(rec)

        if buy_sell_stocks:
            md_lines.append(f"以下股票/ETF近期出现缠论买卖点信号（仅显示最近20个交易日内的活跃信号）：\n")

            # 按信号类型分组显示
            buy_stocks = []
            sell_stocks = []

            for stock in buy_sell_stocks:
                chan_signals = stock.get("chan_signals", "")
                if "买" in chan_signals and "卖" not in chan_signals:
                    buy_stocks.append(stock)
                elif "卖" in chan_signals and "买" not in chan_signals:
                    sell_stocks.append(stock)
                elif "买" in chan_signals and "卖" in chan_signals:
                    # 同时有买卖点，添加到两个列表
                    buy_stocks.append(stock)
                    sell_stocks.append(stock)

            if buy_stocks:
                md_lines.extend([
                    "### 买入信号 🟢",
                    "",
                    "| 股票 | 代码 | 缠论信号 | 综合评分 | 收盘价 | 行业 |",
                    "|------|------|---------|---------|--------|------|",
                ])
                for stock in buy_stocks:
                    tech = stock.get("technical_analysis", {})
                    data_summary = tech.get("data_summary", {})
                    close = data_summary.get("close", "N/A")
                    md_lines.append(
                        f"| {stock['stock_name']} | {stock['stock_code']} | "
                        f"{stock.get('chan_signals', '—')} | "
                        f"{_color_score(stock['combined_score'])} | {close} | {stock.get('industry', 'N/A')} |"
                    )
                md_lines.append("")

            if sell_stocks:
                md_lines.extend([
                    "### 卖出信号 🔴",
                    "",
                    "| 股票 | 代码 | 缠论信号 | 综合评分 | 收盘价 | 行业 |",
                    "|------|------|---------|---------|--------|------|",
                ])
                for stock in sell_stocks:
                    tech = stock.get("technical_analysis", {})
                    data_summary = tech.get("data_summary", {})
                    close = data_summary.get("close", "N/A")
                    md_lines.append(
                        f"| {stock['stock_name']} | {stock['stock_code']} | "
                        f"{stock.get('chan_signals', '—')} | "
                        f"{_color_score(stock['combined_score'])} | {close} | {stock.get('industry', 'N/A')} |"
                    )
                md_lines.append("")

            md_lines.extend([
                "",
                "**信号说明**:",
                "- **买1/买2/买3**: 缠论第一/二/三类买点",
                "- **卖1/卖2/卖3**: 缠论第一/二/三类卖点",
                "- **置信度**: h=high(高), m=medium(中), l=low(低)",
                "- **买1/买2**: 趋势反转和回踩确认，较强信号",
                "- **买3**: 突破回踩，相对较弱信号",
                "",
            ])
        else:
            md_lines.append("当前无活跃买卖点信号\n")

        # All analyzed stocks grouped by rating
        md_lines.extend(["---", "", "## 全部分析结果", ""])

        # Group by rating for clear display
        rating_order = ["强烈推荐", "推荐", "中性", "不推荐", "强烈不推荐"]
        rating_emoji = {"强烈推荐": "🌟", "推荐": "📈", "中性": "➖", "不推荐": "🔻", "强烈不推荐": "⛔"}

        rating_groups = {}
        for rec in recommendations:
            rating = rec.get("rating", "中性")
            if rating not in rating_groups:
                rating_groups[rating] = []
            rating_groups[rating].append(rec)

        global_idx = 0  # Unified sequence number across all rating groups
        for rating in rating_order:
            group = rating_groups.get(rating, [])
            if not group:
                continue
            emoji = rating_emoji.get(rating, "➖")
            dual_count = sum(1 for s in group if s.get("both_positive"))
            dual_mark = f" (含{dual_count}只双重看多)" if dual_count > 0 else ""
            md_lines.extend([
                f"### {emoji} {rating}{dual_mark} ({len(group)} 只)",
                "",
            ])

            # Table header
            md_lines.extend([
                "| # | 股票 | 代码 | 综合评分 | 技术 | 牛熊 | 波浪 | 波浪位置 | 缠论买卖点 | 风险 | 操作 | 股息率 | CAPE | 行业 | 双重看多 | 朋友 | 收盘价 | MA25 | 价差% | 买入点 | 卖出点 |",
                "|---|------|------|---------|------|------|------|---------|---------|------|------|------|------|---------|------|--------|------|------|--------|--------|--------|",
            ])

            for rec in group:
                global_idx += 1
                tech = rec.get("technical_analysis", {})
                data_summary = tech.get("data_summary", {})
                close = data_summary.get("close", "N/A")
                ma25 = data_summary.get("ma25", "N/A")
                price_diff = ""
                if isinstance(close, (int, float)) and isinstance(ma25, (int, float)) and ma25 > 0:
                    diff_pct = (close - ma25) / ma25 * 100
                    price_diff = f"{diff_pct:+.1f}%"
                else:
                    price_diff = "N/A"
                both = "★" if rec.get("both_positive") else ""
                friend = "★" if rec.get("is_time_friend") else ""
                bb_score = rec.get("bull_bear_score")
                bb_display = str(bb_score) if bb_score is not None else "0"
                if rec.get("bull_bear_missing"):
                    bb_display += "*"
                elliott_score = rec.get("elliott_score", 0)
                elliott_analysis = rec.get("elliott_analysis", {})
                wave_pos = elliott_analysis.get("wave_position", "-") if isinstance(elliott_analysis, dict) else "-"
                if wave_pos in ("分析失败", "数据不足", None):
                    wave_pos = "-"
                risk = rec.get("risk_level", tech.get("risk_level", "-"))
                operation = rec.get("operation_suggestion", tech.get("recommendation", "-"))
                dv = rec.get("dividend_yield")
                dv_display = f"{dv}%" if dv is not None else "-"
                cape = rec.get("cape")
                cape_display = f"{cape:.1f}" if cape is not None else "-"
                # Highlight if both conditions met: 股息率>4% and CAPE<=20
                dv_display = _highlight_dy_cape(dv, cape, dv_display)
                cape_display = _highlight_dy_cape(dv, cape, cape_display)
                chan_signals = rec.get("chan_signals", "—")
                md_lines.append(
                    f"| {global_idx} | {rec['stock_name']} | {rec['stock_code']} | "
                    f"{_color_score(rec['combined_score'])} | {_color_score(rec['tech_score'])} | {_color_score(bb_display)} | {_color_score(elliott_score)} | {wave_pos} | "
                    f"{chan_signals} | "
                    f"{risk} | {operation} | {dv_display} | {cape_display} | {rec.get('industry', 'N/A')} | {both} | {friend} | {close} | {ma25} | {price_diff} | "
                    f"{rec.get('buy_point', '-') or '-'} | {rec.get('sell_point', '-') or '-'} |"
                )
            md_lines.append("")

        # Per-stock detailed analysis
        md_lines.extend(["---", "", "## 个股详细分析", ""])
        for i, rec in enumerate(recommendations, 1):
            tech = rec.get("technical_analysis", {})
            bb = rec.get("bull_bear_analysis", {})
            ea = rec.get("elliott_analysis", {})

            elliott_score = rec.get("elliott_score", 0)
            has_elliott = rec.get("has_elliott", False)
            _dy = rec.get('dividend_yield')
            _cape = rec.get('cape')
            _dy_d = f"{_dy}%" if _dy is not None else "-"
            _cape_d = f"{_cape:.1f}" if _cape is not None else "-"

            has_chan = rec.get("has_chan", False)
            chan_score = rec.get("chan_score", 0)
            chan_signals = rec.get("chan_signals", "—")

            _friend_tag = " · ⏰时间的朋友" if rec.get("is_time_friend") else ""
            md_lines.extend([
                f"### {i}. {rec['stock_name']} ({rec['stock_code']}) - {rec['rating']}{_friend_tag}",
                "",
                f"- **综合评分**: {_color_score(rec['combined_score'])}",
                f"- **技术评分**: {_color_score(rec['tech_score'])}",
                f"- **牛熊评分**: {_color_score(rec.get('bull_bear_score', 0))}{' (未评估)' if rec.get('bull_bear_missing') else ''}",
                f"- **波浪评分**: {_color_score(elliott_score)}{' (无数据)' if not has_elliott else ''}",
                f"- **缠论评分**: {_color_score(chan_score)}{' (无数据)' if not has_chan else ''}",
                f"- **缠论信号**: {chan_signals}",
                f"- **风险等级**: {rec.get('risk_level', tech.get('risk_level', 'N/A'))}",
                f"- **操作建议**: {rec.get('operation_suggestion', tech.get('recommendation', 'N/A'))}",
                f"- **股息率**: {_highlight_dy_cape(_dy, _cape, _dy_d)}",
                f"- **CAPE**: {_highlight_dy_cape(_dy, _cape, _cape_d)}",
                f"- **行业**: {rec.get('industry', 'N/A')}",
                f"- **双重看多**: {'是 ★' if rec.get('both_positive') else '否'}",
                "",
            ])

            # Buy/Sell point advice
            buy_point = rec.get("buy_point")
            sell_point = rec.get("sell_point")
            buy_reason = rec.get("buy_reason", "")
            sell_reason = rec.get("sell_reason", "")
            if buy_point or sell_point:
                md_lines.append("**买卖点建议**:")
                if buy_point:
                    md_lines.append(f"- 买入点: {buy_point:.3f} — {buy_reason}")
                if sell_point:
                    md_lines.append(f"- 卖出点: {sell_point:.3f} — {sell_reason}")
                md_lines.append("")

            # Tech details
            data_summary = tech.get("data_summary", {})
            if data_summary:
                md_lines.extend([
                    "**技术详情**:",
                    f"- 收盘价: {data_summary.get('close', 'N/A')}",
                    f"- MA25: {data_summary.get('ma25', 'N/A')}",
                    f"- 5日均量: {data_summary.get('vol5', 'N/A')}",
                    f"- 60日均量: {data_summary.get('vol60', 'N/A')}",
                    "",
                ])

            # Bull/Bear details
            if bb and isinstance(bb, dict) and "error" not in bb:
                md_lines.extend([
                    "**牛熊辩论**:",
                    f"- 投资评级: {bb.get('investment_rating', 'N/A')}",
                    f"- 信心水平: {bb.get('confidence_level', 'N/A')}",
                ])
                if bb.get("key_agreements"):
                    md_lines.append(f"- 共识: {', '.join(str(x) for x in bb['key_agreements'][:3])}")
                if bb.get("key_disagreements"):
                    md_lines.append(f"- 分歧: {', '.join(str(x) for x in bb['key_disagreements'][:3])}")
                if bb.get("bullish_strengths"):
                    md_lines.append(f"- 多方优势: {', '.join(str(x) for x in bb['bullish_strengths'][:3])}")
                if bb.get("bearish_risks"):
                    md_lines.append(f"- 空方风险: {', '.join(str(x) for x in bb['bearish_risks'][:3])}")
                if bb.get("comprehensive_conclusion"):
                    md_lines.append(f"- 综合结论: {bb['comprehensive_conclusion'][:200]}")
                md_lines.append("")
            elif bb and isinstance(bb, dict) and "error" in bb:
                md_lines.append(f"**牛熊辩论**: 分析失败 - {bb['error'][:100]}\n")

            # Elliott wave details - Enhanced format with multi-level analysis
            if has_elliott:
                current_price = ea.get("current_price", "N/A")
                high_price = ea.get("high_price", "N/A")
                low_price = ea.get("low_price", "N/A")
                trend = ea.get("trend", "N/A")
                wave_pos = ea.get("wave_position", "N/A")

                # Check if this is enhanced Elliott analysis (has scenarios)
                scenarios = ea.get("scenarios", [])
                fib_levels = ea.get("fib_levels", {})
                resonance = ea.get("resonance", {})
                daily_analysis = ea.get("daily_analysis", {})
                weekly_analysis = ea.get("weekly_analysis", {})
                monthly_analysis = ea.get("monthly_analysis", {})

                is_enhanced = bool(scenarios and isinstance(scenarios, list))

                if is_enhanced:
                    # Enhanced format - detailed multi-level analysis like standalone report
                    md_lines.extend([
                        "**波浪分析**:",
                        "",
                        f"**当前价格**: {current_price} | **历史最高**: {high_price} | **历史最低**: {low_price}",
                        f"**MA20**: {daily_analysis.get('ma20', 'N/A')} | **MA60**: {daily_analysis.get('ma60', 'N/A')}",
                        f"**趋势**: {trend}",
                        "",
                    ])

                    # Fibonacci levels
                    if fib_levels:
                        md_lines.extend([
                            "**斐波那契回调位**:",
                            "| 水平 | 价格 |",
                            "|------|------|",
                        ])
                        for level, price in fib_levels.items():
                            md_lines.append(f"| {level} | {price:.2f} |")
                        md_lines.append("")

                    # Daily level analysis
                    md_lines.extend([
                        "**日线级别分析**:",
                        f"**当前趋势**: {trend}",
                        f"**MA20**: {daily_analysis.get('ma20', 'N/A')} | **MA60**: {daily_analysis.get('ma60', 'N/A')}",
                        "",
                        "**可能性场景**:",
                        "",
                    ])
                    for scenario in scenarios:
                        emoji = "🟢" if scenario.get('bullish') else "🔴" if scenario.get('bullish') is False else "🟡"
                        md_lines.extend([
                            f"**{emoji} {scenario.get('name', 'N/A')}** [{scenario.get('probability', 0)}%]",
                            "",
                            f"> {scenario.get('description', 'N/A')}",
                            "",
                        ])

                    # Weekly level analysis
                    if weekly_analysis and weekly_analysis.get('trend'):
                        md_lines.extend([
                            "**周线级别分析**:",
                            f"**当前趋势**: {weekly_analysis.get('trend', 'N/A')}",
                            f"**当前价格**: {current_price}",
                            f"**历史最高**: {high_price}",
                            f"**历史最低**: {low_price}",
                            "",
                        ])
                        # Weekly scenarios would need to be generated or stored separately
                        md_lines.extend([
                            "**可能性场景**:",
                            f"- {wave_pos} (基于日线分析)",
                            "",
                        ])

                    # Monthly level analysis
                    if monthly_analysis and monthly_analysis.get('trend'):
                        md_lines.extend([
                            "**月线级别分析**:",
                            f"**当前趋势**: {monthly_analysis.get('trend', 'N/A')}",
                            f"**当前价格**: {current_price}",
                            f"**历史最高**: {high_price}",
                            f"**历史最低**: {low_price}",
                            "",
                            "**可能性场景**:",
                            f"- {wave_pos} (基于日线分析)",
                            "",
                        ])

                    # Multi-level resonance
                    if resonance:
                        md_lines.extend([
                            "**多级别共振分析**:",
                            f"**{resonance.get('resonance', 'N/A')}** | 方向: **{resonance.get('direction', 'N/A')}**",
                            "",
                            f"> {resonance.get('details', 'N/A')}",
                            "",
                        ])

                    # Summary
                    md_lines.extend([
                        "**综合评价**:",
                        f"- **波浪位置**: {wave_pos}",
                        f"- **波浪评分**: {elliott_score}",
                        f"- **主要场景**: {scenarios[0].get('name', 'N/A') if scenarios else 'N/A'} (概率: {scenarios[0].get('probability', 0)}%)",
                        "",
                    ])

                else:
                    # Fallback to original simple format
                    wave_desc = ea.get("description", "")
                    score_rationale = ea.get("score_rationale", "")
                    wave_structure = ea.get("wave_detail", {}).get("wave_structure", "")
                    md_lines.extend([
                        "**波浪分析**:",
                        f"- 波浪位置: {wave_pos}",
                        f"- 波浪评分: {elliott_score}",
                    ])
                    if wave_desc:
                        md_lines.append(f"- 分析: {wave_desc}")
                    if wave_structure:
                        md_lines.append(f"- 浪型结构: {wave_structure}")
                    if score_rationale:
                        md_lines.append(f"- 评分理由: {score_rationale}")
                    position_reasoning = ea.get("wave_detail", {}).get("position_reasoning", "")
                    if position_reasoning:
                        md_lines.append(f"- 位置判断依据: {position_reasoning}")

                    # 波浪规则验证结果
                    validation = ea.get("validation")
                    if validation:
                        quality = validation.get("quality_score", 0)
                        iron = validation.get("iron_rule_violations", [])
                        guidelines = validation.get("guideline_violations", [])
                        pattern = validation.get("pattern_assessment", {})
                        md_lines.append(f"- **波浪质量评分**: {quality}/100")
                        if iron:
                            md_lines.append(f"- ❌ **铁律违反**: {'; '.join(v['description'] for v in iron)}")
                        if guidelines:
                            guide_strs = [f"{v['rule_id']}: {v['description']}" for v in guidelines[:3]]
                            md_lines.append(f"- ⚠️ 指导违反: {'; '.join(guide_strs)}")
                        if pattern:
                            md_lines.append(f"- 识别形态: {pattern.get('pattern', 'N/A')}(置信度{pattern.get('confidence', 0):.0%})")
                    md_lines.append("")

            # Chan Theory details - 缠论买卖点分析
            if has_chan:
                ca = rec.get("chan_analysis", {})
                cp_summary = ca.get("summary", {})
                ca_buys = ca.get("active_buys", [])
                ca_sells = ca.get("active_sells", [])
                last_pivot = ca.get("last_pivot")
                current_price_cp = ca.get("current_price", 0)
                pivot_pos = _chan_pivot_position(current_price_cp, last_pivot)

                md_lines.extend([
                    "**缠论分析**:",
                    "",
                    "**计算逻辑**: 缠论(缠中说禅理论)是一种纯几何结构分类的技术分析方法，通过K线包含处理→分型→笔→线段→中枢→背驰→买卖点的严格递归流程识别趋势转折点。",
                    "",
                    "> **核心步骤**:",
                    "> 1. **K线包含处理**: 将存在包含关系的相邻K线进行合并(上涨趋势取高高，下跌趋势取低低)，消除冗余信息",
                    "> 2. **分型识别**: 在合并后K线中寻找顶分型(中间K线高点最高、低点最高)和底分型(中间K线低点最低、高点最低)",
                    "> 3. **笔的构建**: 连接相邻的顶底分型，要求至少包含1根独立K线，且顶底分型交替出现",
                    "> 4. **线段划分**: ≥3笔重叠构成线段，通过特征序列分析判断线段破坏，形成稳定的趋势段",
                    "> 5. **中枢识别**: 3个连续线段价格重叠区间构成中枢(ZG=min(高点), ZD=max(低点))，是缠论最核心的价格引力区间",
                    "> 6. **背驰检测**: 通过MACD柱面积对比，判断进入段与离开段力度是否衰竭(趋势背驰需≥2同向中枢，盘整背驰只需1个中枢)",
                    "> 7. **买卖点定位**: 基于中枢、背驰和价格位置关系，识别三类买卖点",
                    "",
                    "**三类买卖点定义**:",
                    "- **一买/一卖**: 趋势背驰后的反转点，离开段MACD面积 < 进入段面积(力度衰竭)，是最可靠的转折信号",
                    "- **二买/二卖**: 一买/一卖后的回踩/反弹确认，价格回调到中枢附近，不创新低/新高",
                    "- **三买/三卖**: 离开中枢后回抽/反弹不进入中枢区间，确认原趋势被打破",
                    "",
                ])

                # Structure statistics
                md_lines.extend([
                    f"**{rec['stock_name']} ({rec['stock_code']}) 缠论结构数据**:",
                    f"- 分型: {ca.get('fractal_count', 0)}个 | 笔: {ca.get('stroke_count', 0)}个 | 线段: {ca.get('segment_count', 0)}个 | 中枢: {ca.get('pivot_count', 0)}个",
                    f"- 背驰: {ca.get('divergence_count', 0)}个 | 买点: {len(ca_buys)}个 | 卖点: {len(ca_sells)}个",
                    f"- 当前价格: {current_price_cp:.2f}",
                    f"- 中枢位置: {pivot_pos}",
                    "",
                ])

                if last_pivot:
                    has_expansion = last_pivot.get('has_expansion', False)
                    expansion_ratio = last_pivot.get('expansion_ratio_prev', 0.0)
                    overlap_width = last_pivot.get('overlap_prev_width', 0.0)

                    md_lines.extend([
                        f"**最新中枢**: ZG={last_pivot.get('ZG', 0):.2f}, ZD={last_pivot.get('ZD', 0):.2f}",
                        f"  - 中枢区间宽度: {(last_pivot.get('ZG', 0) - last_pivot.get('ZD', 0)) / last_pivot.get('ZD', 1) * 100:.2f}%",
                        f"  - 时间: {last_pivot.get('start_date', '')[:10]} ~ {last_pivot.get('end_date', '')[:10]}",
                    ])

                    if has_expansion:
                        md_lines.append(
                            f"  - **中枢扩张**: 重叠{overlap_width:.2f}元, 比例{expansion_ratio:.1%}"
                        )
                    md_lines.append("")

                    # 多级别中枢分析
                    multi_level = ca.get("multi_level", {})
                    if multi_level:
                        tf30_state = multi_level.get("tf30_state", "")
                        daily_state = multi_level.get("daily_state")
                        combined_dir = multi_level.get("combined_direction", "")
                        combined_signal = multi_level.get("combined_signal", "")

                        if daily_state:
                            md_lines.extend([
                                "**多级别中枢分析**:",
                                f"  - 30分钟(日线中枢): {tf30_state}"
                                f" (ZG={multi_level.get('tf30_zg', 0):.2f}, ZD={multi_level.get('tf30_zd', 0):.2f})",
                                f"  - 日线(周线中枢): {daily_state}"
                                + (f" (ZG={multi_level.get('daily_zg', 0):.2f}, ZD={multi_level.get('daily_zd', 0):.2f})"
                                   if multi_level.get('daily_zg') else ""),
                                f"  - **综合判断: {combined_dir}**",
                                f"  - {combined_signal}",
                                "",
                            ])

                    # Price relative to pivot analysis
                    zg = last_pivot.get('ZG', 0)
                    zd = last_pivot.get('ZD', 0)
                    if current_price_cp > zg:
                        md_lines.append(f"  - 当前价格 **高于** 中枢上轨(ZG={zg:.2f})，若回踩不破ZG则可能形成三买")
                    elif current_price_cp < zd:
                        md_lines.append(f"  - 当前价格 **低于** 中枢下轨(ZD={zd:.2f})，若反弹不破ZD则可能形成三卖")
                    else:
                        md_lines.append(f"  - 当前价格 **在** 中枢区间内[{zd:.2f}, {zg:.2f}]，处于中枢震荡")
                        if has_expansion:
                            md_lines.append(f"    注意: 该中枢与前一中枢扩张重叠，趋势方向待明确")
                    md_lines.append("")

                # Active buy signals
                if ca_buys:
                    md_lines.append("**活跃买点**:")
                    for b in ca_buys:
                        type_name = {1: "一买(趋势反转)", 2: "二买(回踩确认)", 3: "三买(突破回踩)"}
                        b_type = b.get("type", 0)
                        md_lines.append(f"- **{b['date']}** | {type_name.get(b_type, f'{b_type}买')} @ {b['price']:.2f} (置信度：{b.get('confidence', 'N/A')})")
                    md_lines.append("")

                # Active sell signals
                if ca_sells:
                    md_lines.append("**活跃卖点**:")
                    for s in ca_sells:
                        type_name = {1: "一卖(趋势反转)", 2: "二卖(反弹确认)", 3: "三卖(破位回抽)"}
                        s_type = s.get("type", 0)
                        md_lines.append(f"- **{s['date']}** | {type_name.get(s_type, f'{s_type}卖')} @ {s['price']:.2f} (置信度：{s.get('confidence', 'N/A')})")
                    md_lines.append("")

                if not ca_buys and not ca_sells:
                    md_lines.append("**活跃买卖点**: 当前无活跃买卖点信号")
                    md_lines.append("")

                # Scoring explanation
                md_lines.extend([
                    "**缠论评分规则**:",
                    "- 一买 +3.0 | 二买 +2.0 | 三买 +1.0",
                    "- 一卖 -3.0 | 二卖 -2.0 | 三卖 -1.0",
                    "- 多信号叠加，上限±5.0，仅计入20日内活跃信号",
                    "",
                ])

        # ETF section
        etf_list = report.get("etf_list", [])
        etf_recs = report.get("etf_recommendations", [])
        etf_summary = report.get("etf_summary", {})
        # Sort ETF recommendations by rating group, then by score descending
        if etf_recs:
            etf_rating_sort = {"强烈推荐": 0, "推荐": 1, "中性": 2, "不推荐": 3, "强烈不推荐": 4}
            etf_recs.sort(key=lambda x: (etf_rating_sort.get(x.get("rating", "中性"), 5), -x.get("combined_score", 0)))
        if etf_recs:
            md_lines.extend(["---", "", "## ETF基金三维分析", ""])
            md_lines.extend([
                f"分析ETF: {etf_summary.get('total_etfs', len(etf_recs))} 只 | "
                f"推荐: {etf_summary.get('recommended', 0)} 只",
                "",
                "> 三维评分 = 行业基本面(35%) + 技术分析(35%) + 艾略特波浪(30%)",
                "",
            ])

            # ETF rating groups
            etf_rating_order = ["强烈推荐", "推荐", "中性", "不推荐", "强烈不推荐"]
            etf_rating_emoji = {"强烈推荐": "🌟", "推荐": "📈", "中性": "➖", "不推荐": "🔻", "强烈不推荐": "⛔"}
            etf_rating_groups = {}
            for rec in etf_recs:
                rating = rec.get("rating", "中性")
                if rating not in etf_rating_groups:
                    etf_rating_groups[rating] = []
                etf_rating_groups[rating].append(rec)

            etf_global_idx = 0  # Unified sequence number for ETF section
            for rating in etf_rating_order:
                group = etf_rating_groups.get(rating, [])
                if not group:
                    continue
                emoji = etf_rating_emoji.get(rating, "➖")
                md_lines.extend([
                    f"### {emoji} {rating} ({len(group)} 只)",
                    "",
                    "| # | ETF名称 | 代码 | 综合 | 基本面 | 技术 | 波浪 | 波浪位置 | 行业 | 买入点 | 卖出点 |",
                    "|---|---------|------|------|--------|------|------|---------|------|--------|--------|",
                ])
                for rec in group:
                    etf_global_idx += 1
                    elliott = rec.get("elliott_analysis", {})
                    wave_pos = elliott.get("wave_position", "N/A") if isinstance(elliott, dict) else "N/A"
                    buy_pt = rec.get("buy_point")
                    sell_pt = rec.get("sell_point")
                    md_lines.append(
                        f"| {etf_global_idx} | {rec['stock_name']} | {rec['stock_code']} | "
                        f"{_color_score(rec['combined_score'])} | {_color_score(rec.get('fundamental_score', 0))} | "
                        f"{_color_score(rec.get('tech_score', 0))} | {_color_score(rec.get('elliott_score', 0))} | "
                        f"{wave_pos} | {rec.get('industry', 'N/A')} | "
                        f"{buy_pt or '-'} | {sell_pt or '-'} |"
                    )
                md_lines.append("")

            # ETF detailed analysis
            md_lines.extend(["---", "", "### ETF详细分析", ""])
            for i, rec in enumerate(etf_recs, 1):
                md_lines.extend([
                    f"**{i}. {rec['stock_name']} ({rec['stock_code']})** - {rec['rating']}",
                    "",
                    f"- 综合: {_color_score(rec['combined_score'])} | "
                    f"基本面: {_color_score(rec.get('fundamental_score', 0))} | "
                    f"技术: {_color_score(rec.get('tech_score', 0))} | "
                    f"波浪: {_color_score(rec.get('elliott_score', 0))}{' (无数据)' if not rec.get('has_elliott', False) else ''}",
                    f"- 风险等级: {rec.get('risk_level', 'N/A')} | "
                    f"操作建议: {rec.get('operation_suggestion', 'N/A')}",
                    f"- 推荐理由: {rec.get('recommendation_reason', 'N/A')}",
                ])
                # Elliott wave detail
                elliott = rec.get("elliott_analysis", {})
                if isinstance(elliott, dict) and "description" in elliott:
                    md_lines.append(f"- 波浪分析: {elliott['description']}")
                if isinstance(elliott, dict) and "score_rationale" in elliott:
                    md_lines.append(f"- 波浪评分理由: {elliott['score_rationale']}")
                wave_struct = elliott.get("wave_detail", {}).get("wave_structure", "") if isinstance(elliott, dict) else ""
                if wave_struct:
                    md_lines.append(f"- 浪型结构: {wave_struct}")
                # Fundamental detail
                fundamental = rec.get("fundamental_analysis", {})
                if isinstance(fundamental, dict) and "description" in fundamental:
                    md_lines.append(f"- 基本面: {fundamental['description']}")
                # Buy/Sell point advice
                buy_point = rec.get("buy_point")
                sell_point = rec.get("sell_point")
                buy_reason = rec.get("buy_reason", "")
                sell_reason = rec.get("sell_reason", "")
                if buy_point or sell_point:
                    if buy_point:
                        md_lines.append(f"- 买入点: {buy_point:.3f} — {buy_reason}")
                    if sell_point:
                        md_lines.append(f"- 卖出点: {sell_point:.3f} — {sell_reason}")
                md_lines.append("")

        elif etf_list:
            md_lines.extend(["---", "", "## ETF基金（仅列表）", ""])
            md_lines.extend([
                "| # | 名称 | 代码 | 行业 |",
                "|---|------|------|------|",
            ])
            for i, etf in enumerate(etf_list, 1):
                md_lines.append(
                    f"| {i} | {etf.get('stock_name', 'N/A')} | {etf['stock_code']} | {etf.get('industry', 'N/A')} |"
                )
            md_lines.append("")

        # Disclaimers
        md_lines.extend([
            "---",
            "",
            "## 备注",
            "",
            "- 本报告基于技术分析（25日均线+成交量四种情况判断）、牛熊辩论Agent、艾略特波浪分析和缠论综合生成",
            "- 个股综合评分 = 技术评分 × 30% + 牛熊评分 × 30% + 波浪评分 × 25% + 缠论评分 × 15%（无数据维度按比例重新分配至其他维度）",
            "- 买入点基于均线支撑位（MA20/MA25/MA60）和60日低点计算，卖出点基于60日高点压力位计算",
            "- 买卖点建议仅供参考，需结合市场环境和个人风险承受能力综合判断",
            "- 标注 ★双重看多 的股票表示技术面和牛熊辩论均看多，优先关注",
            "- ETF评分基于三维模型：行业基本面(35%) + 技术分析(35%) + 艾略特波浪(30%)",
            "- 投资需谨慎，请结合其他因素综合判断",
            "",
        ])

        md_path = self.daily_selection_dir / f"{filename}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        print(f"Markdown报告已保存: {md_path}")

    # ================================================================
    # Step 1: 结合"经典理论"分析利好行业
    # ================================================================

    def _analyze_favorable_industries(
        self, override_industries: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        if override_industries:
            return [
                {"name": name, "reason": "用户指定", "weight": 1.0}
                for name in override_industries
            ]

        theory_files = list(self.classic_theory_dir.glob("*.md"))

        if not theory_files or not self.llm_client.is_available():
            if not theory_files:
                print("未找到经典理论文件，使用默认行业列表")
            else:
                print("无LLM API Key，使用默认行业列表")
            print(f"识别到{len(FALLBACK_INDUSTRIES)}个默认利好行业:")
            for ind in FALLBACK_INDUSTRIES:
                print(f"  - {ind['name']}: {ind['reason']} (权重: {ind['weight']})")
            return FALLBACK_INDUSTRIES

        print(f"找到{len(theory_files)}个经典理论文件，使用LLM分析 ({self.llm_client.get_provider_name()})...")
        theory_content = []
        for f in theory_files:
            try:
                content = read_text_with_retry(f)
                theory_content.append(f"文件：{f.name}\n{content[:3000]}")
            except Exception as e:
                print(f"读取文件{f.name}失败: {e}")

        if not theory_content:
            print("所有理论文件读取失败，使用默认行业列表")
            return FALLBACK_INDUSTRIES

        try:
            system_prompt = """你是一位投资策略专家，擅长解读经典投资理论并识别利好行业。

你的任务是：
1. 分析提供的经典投资理论内容
2. 识别当前市场环境下最受益的行业
3. 为每个行业给出理由和权重（0-1之间）

尽量将行业名称匹配到以下已知行业中：
白酒与高端消费品、科技（AI与数字经济）、半导体、新能源、医药生物、贵金属（黄金/铜）、高股息公用事业、消费电子、金融、汽车、地产基建、港股科技、港股医药、港股消费、互联网/数字经济

返回JSON格式：
{
    "favorable_industries": [
        {
            "name": "行业名称",
            "reason": "利好理由",
            "weight": 0.8
        }
    ]
}"""

            user_prompt = (
                "请分析以下经典投资理论，识别当前最受益的行业：\n\n"
                + "\n\n".join(theory_content)
            )

            response_text = self.llm_client.chat(system_prompt, user_prompt, max_tokens=2000)

            result = self._parse_json_response(response_text)
            favorable_industries = result.get("favorable_industries", [])

            if not favorable_industries:
                print("LLM返回为空，使用默认行业列表")
                return FALLBACK_INDUSTRIES

        except Exception as e:
            print(f"LLM分析失败: {e}，使用默认行业列表")
            return FALLBACK_INDUSTRIES

        print(f"识别到{len(favorable_industries)}个利好行业:")
        for industry in favorable_industries:
            print(f"  - {industry['name']}: {industry['reason']} (权重: {industry.get('weight', 0.5)})")

        return favorable_industries

    # ================================================================
    # Step 2: 结合"滚雪球"信息找到行业龙头股
    # ================================================================

    def _filter_industry_leaders(
        self, industries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        print("扫描滚雪球数据...")

        # Read xueqiu hot post files
        xueqiu_files = sorted(
            list(self.xueqiu_dir.glob("*.md")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        # Parse stock codes and context from xueqiu files
        xueqiu_stocks = {}  # code -> {name, context, source}
        for f in xueqiu_files[:20]:  # Only read recent 20 files
            try:
                content = f.read_text(encoding="utf-8")
                # Match 6-digit A-share codes and 4-5 digit HK codes
                codes_6 = re.findall(r"\b(\d{6})\b", content)
                # Also match explicit HK stock code references (e.g., "09988.HK", "0700.HK")
                codes_hk = re.findall(r"\b(\d{4,5})\.HK\b", content, re.IGNORECASE)
                all_codes = set(codes_6) | set(codes_hk)
                for code in all_codes:
                    if code not in xueqiu_stocks:
                        # Get surrounding context (100 chars around the code)
                        idx = content.find(code)
                        context_snippet = content[max(0, idx - 50):idx + 50] if idx >= 0 else ""
                        xueqiu_stocks[code] = {
                            "name": f"雪球提及_{code}",
                            "context": context_snippet,
                            "source": f.name,
                        }
            except Exception:
                continue

        print(f"从滚雪球数据中提取到 {len(xueqiu_stocks)} 个股票代码")

        # Match xueqiu stocks with favorable industries
        # Read stock pool from file (user + agent maintained)
        file_pool = self._read_stock_pool_file()
        # Merge with DEFAULT_STOCKS (file takes priority, defaults fill gaps)
        # stock_sources: {industry: [codes]}
        stock_sources = {}
        for industry_name, codes in DEFAULT_STOCKS.items():
            stock_sources[industry_name] = list(codes)
        for industry_name, entries in file_pool.items():
            codes = [e["code"] for e in entries]
            if industry_name in stock_sources:
                # Merge: file pool may have additional stocks
                merged = list(dict.fromkeys(stock_sources[industry_name] + codes))
                stock_sources[industry_name] = merged
            else:
                stock_sources[industry_name] = codes

        industry_leaders = []
        favorable_names = {ind["name"] for ind in industries}

        for industry_name, codes in DEFAULT_STOCKS.items():
            if industry_name not in favorable_names:
                continue

            for code in codes:
                stock_info = {
                    "stock_code": code,
                    "stock_name": f"{industry_name}代表股",
                    "industry": industry_name,
                    "source": "默认股票池",
                }

                # Enrich with xueqiu data if available
                pure_code = code.split(".")[0]
                if pure_code in xueqiu_stocks:
                    xq = xueqiu_stocks[pure_code]
                    stock_info["source"] = f"雪球+默认池 ({xq['source']})"
                    stock_info["xueqiu_context"] = xq["context"]

                industry_leaders.append(stock_info)

        # Add xueqiu-only stocks that match favorable industries (via context keywords)
        for code, info in xueqiu_stocks.items():
            if any(s["stock_code"].split(".")[0] == code for s in industry_leaders):
                continue

            # Check if xueqiu context mentions any favorable industry
            context_lower = info.get("context", "").lower()
            matched_industry = None
            for ind in industries:
                if ind["name"] in context_lower:
                    matched_industry = ind["name"]
                    break

            if matched_industry:
                # Infer stock code suffix
                full_code = self._infer_full_stock_code(code)
                industry_leaders.append({
                    "stock_code": full_code,
                    "stock_name": info["name"],
                    "industry": matched_industry,
                    "source": f"雪球 ({info['source']})",
                    "xueqiu_context": info["context"],
                })

        # Deduplicate by stock code
        unique = {}
        for leader in industry_leaders:
            code = leader["stock_code"]
            if code not in unique:
                unique[code] = leader
        industry_leaders = list(unique.values())

        # Resolve real stock names
        self._resolve_stock_names(industry_leaders)

        print(f"共筛选出 {len(industry_leaders)} 只行业龙头股")
        for leader in industry_leaders:
            print(f"  - {leader['stock_name']} ({leader['stock_code']}) [{leader['industry']}] from {leader['source']}")

        return industry_leaders

    def _infer_full_stock_code(self, pure_code: str) -> str:
        """Infer full stock code with suffix from a numeric code.

        - 6 digits starting with 6/0/3/4/8: A-share (SH/SZ/BJ)
        - 1-5 digits: HK stock (.HK suffix)
        """
        code_len = len(pure_code)
        if code_len == 6:
            if pure_code.startswith("6"):
                return f"{pure_code}.SH"
            elif pure_code.startswith("0") or pure_code.startswith("3"):
                return f"{pure_code}.SZ"
            elif pure_code.startswith("4") or pure_code.startswith("8"):
                return f"{pure_code}.BJ"
        # 1-5 digit codes: treat as HK stock codes
        if 1 <= code_len <= 5:
            return f"{pure_code}.HK"
        return pure_code

    def _discover_xueqiu_stocks(self) -> List[Dict[str, str]]:
        """Scan recent Xueqiu hot post files for mentioned stocks.

        Uses name-based matching: searches Xueqiu content for known stock names
        from the STOCK_NAMES dictionary, then resolves them to codes.

        Returns a list of discovered stocks: [{"code": "600519.SH", "name": "贵州茅台", "industry": "白酒"}, ...]
        """
        discovered = []

        # Build name->code reverse lookup from STOCK_NAMES
        name_to_code = {}
        for code, name in self.STOCK_NAMES.items():
            # Only index names that are 2+ Chinese chars (skip stock codes used as names)
            if name and len(name) >= 2 and '一' <= name[0] <= '鿿':
                # Keep the first (most canonical) code for each name
                if name not in name_to_code:
                    name_to_code[name] = code

        # Scan recent Xueqiu files
        xueqiu_files = sorted(
            list(self.xueqiu_dir.glob("*.md")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:20]

        codes_found = set()

        for f in xueqiu_files:
            try:
                content = f.read_text(encoding="utf-8")

                # Name-based matching: search for known stock names in Xueqiu content
                for name, code in name_to_code.items():
                    if name in content and code not in codes_found:
                        pure = code.split(".")[0] if "." in code else code
                        if pure in codes_found:
                            continue
                        codes_found.add(pure)
                        full_code = self._normalize_stock_code(code)
                        industry = self._classify_stock_by_code(full_code, name)
                        discovered.append({
                            "code": full_code,
                            "name": name,
                            "industry": industry,
                        })

            except Exception:
                continue

        # Deduplicate by code
        unique = {}
        for d in discovered:
            if d["code"] not in unique:
                unique[d["code"]] = d
        return list(unique.values())

    # ================================================================
    # Step 3: 构建选股池
    # ================================================================

    def _build_stock_pool(
        self,
        industry_leaders: List[Dict[str, Any]],
        custom_stocks: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        stock_pool = list(industry_leaders)
        existing_codes = {s["stock_code"] for s in stock_pool}

        if custom_stocks:
            print(f"添加{len(custom_stocks)}只自选股到选股池...")
            for code in custom_stocks:
                if code not in existing_codes:
                    stock_pool.append({
                        "stock_code": code,
                        "stock_name": f"自选股{code}",
                        "industry": "自选",
                        "source": "用户自选",
                    })
                    existing_codes.add(code)

        # If stock pool is too small, add from DEFAULT_STOCKS
        if len(stock_pool) < 5:
            print("选股池不足5只，补充默认股票池...")
            for industry_name, codes in DEFAULT_STOCKS.items():
                for code in codes:
                    if code not in existing_codes:
                        stock_pool.append({
                            "stock_code": code,
                            "stock_name": f"{industry_name}代表股",
                            "industry": industry_name,
                            "source": "默认补充",
                        })
                        existing_codes.add(code)

        print(f"选股池共有 {len(stock_pool)} 只股票")
        return stock_pool

    # ================================================================
    # Step 4: 通过牛熊分析agent和技术分析agent对个股进行分析
    # ================================================================

    def _analyze_single_stock(self, stock: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze a single stock with all agents. Returns analyzed_stock dict or None on failure."""
        stock_code = stock["stock_code"]
        stock_name = stock.get("stock_name", f"股票{stock_code}")
        max_retries = 3

        # (a) Technical analysis - always run
        print(f"  执行技术分析...")
        tech_result = None
        for retry in range(max_retries):
            try:
                tech_result = self.technical_agent.analyze(
                    stock_code, stock_name, use_llm=False
                )
                break
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"  重试 {retry + 1}/{max_retries}: {str(e)[:50]}...")
                    time.sleep(2)
                else:
                    print(f"  技术分析失败（已重试{max_retries}次）: {str(e)[:100]}")

        if tech_result is None or "error" in tech_result:
            print(f"  跳过此股票（技术分析失败）")
            return None

        analyzed_stock = {
            **stock,
            "technical_analysis": tech_result,
            "analysis_time": datetime.now().isoformat(),
        }

        # (a1.5) Fetch dividend yield directly (needed for cached debate reports)
        dividend_yield = self._dividend_yield_cache.get(stock_code)
        if dividend_yield is None and stock_code not in self._dividend_yield_cache:
            current_price = None
            try:
                current_price = tech_result.get("data_summary", {}).get("close")
            except Exception:
                pass
            dividend_yield = self._fetch_dividend_yield(stock_code, current_price)
            self._dividend_yield_cache[stock_code] = dividend_yield
        analyzed_stock["dividend_yield"] = dividend_yield

        # (a1.6) Fetch CAPE (Cyclically Adjusted P/E Ratio)
        cape = self._cape_cache.get(stock_code)
        if cape is None and stock_code not in self._cape_cache:
            current_price_cape = None
            try:
                current_price_cape = tech_result.get("data_summary", {}).get("close")
            except Exception:
                pass
            cape = self._fetch_cape(stock_code, current_price_cape)
            self._cape_cache[stock_code] = cape
        analyzed_stock["cape"] = cape

        # (a2) Elliott wave analysis - 使用 StockWaveAnalyzer (zigzag-based, 对齐个股报告)
        print(f"  执行波浪分析...")
        elliott_result = None
        try:
            ak_symbol, ak_market = _to_akshare_format(stock_code)
            elliott_result = get_elliott_for_selection(ak_symbol, stock_name, ak_market, years=10, use_enhanced=True)
            if elliott_result and "error" not in elliott_result:
                analyzed_stock["elliott_analysis"] = elliott_result
                wave_pos = elliott_result.get("wave_position", "N/A")
                elliott_score = elliott_result.get("elliott_score", 0)
                trend = elliott_result.get("trend", "N/A")
                resonance = elliott_result.get("resonance", {}).get("resonance", "N/A")
                print(f"  波浪位置: {wave_pos}, 趋势: {trend}, 共振: {resonance}, 波浪评分: {elliott_score}")
            else:
                print(f"  波浪分析失败: {elliott_result.get('description', 'unknown')[:60] if elliott_result else 'no result'}")
        except Exception as e:
            print(f"  StockWaveAnalyzer 波浪分析异常: {str(e)[:60]}")
            # 回退到原版分析器（禁用增强功能）
            try:
                print(f"  尝试使用原版波浪分析器...")
                elliott_result = self.elliott_agent.analyze_etf(stock_code, stock_name)
                if elliott_result and "error" not in elliott_result:
                    analyzed_stock["elliott_analysis"] = elliott_result
                    wave_pos = elliott_result.get("wave_position", "N/A")
                    elliott_score = elliott_result.get("elliott_score", 0)
                    print(f"  波浪位置: {wave_pos}, 波浪评分: {elliott_score}")
                else:
                    print(f"  原版波浪分析也失败")
            except Exception as e2:
                print(f"  原版波浪分析异常: {str(e2)[:60]}")

        # (a2.5) Chan Theory analysis - 缠论买卖点识别（多级别）
        print(f"  执行缠论分析（30分钟 + 日线）...")
        chan_result = None
        daily_chan_result = None  # 日线级别（周线中枢）
        try:
            from chanlun.multi_timeframe_pivot import (
                analyze_multi_timeframe_pivot, format_multi_level_detail
            )
            ak_symbol, ak_market = _to_akshare_format(stock_code)

            # 级别1: 30分钟数据 → 日线中枢
            chan_analyzer = StockChanAnalyzer(
                symbol=ak_symbol, name=stock_name, market=ak_market, timeframe='30min'
            )
            if chan_analyzer.fetch_data():
                if chan_analyzer.analyze():
                    chan_summary = chan_analyzer.get_summary()
                    active_buys = [tp for tp in chan_analyzer.trading_points if tp.action == 'buy']
                    active_sells = [tp for tp in chan_analyzer.trading_points if tp.action == 'sell']
                    buy_pts = [
                        {"date": tp.date[:10], "type": tp.point_type, "price": tp.price, "confidence": tp.confidence}
                        for tp in active_buys
                    ]
                    sell_pts = [
                        {"date": tp.date[:10], "type": tp.point_type, "price": tp.price, "confidence": tp.confidence}
                        for tp in active_sells
                    ]
                    chan_result = {
                        "success": True,
                        "summary": chan_summary,
                        "active_buys": buy_pts,
                        "active_sells": sell_pts,
                        "fractal_count": chan_summary.get("fractal_count", 0),
                        "stroke_count": chan_summary.get("stroke_count", 0),
                        "segment_count": chan_summary.get("segment_count", 0),
                        "pivot_count": chan_summary.get("pivot_count", 0),
                        "divergence_count": chan_summary.get("divergence_count", 0),
                        "last_pivot": chan_summary.get("last_pivot"),
                        "current_price": chan_summary.get("current_price", 0),
                    }
                    chan_score = _compute_chan_score(buy_pts, sell_pts)
                    chan_result["chan_score"] = chan_score
                    print(f"  30分钟缠论: {chan_summary.get('buy_count', 0)}买/{chan_summary.get('sell_count', 0)}卖, "
                          f"中枢{chan_summary.get('pivot_count', 0)}, 评分{chan_score}")
                else:
                    chan_result = {"success": False, "error": "30分钟分析失败"}
            else:
                chan_result = {"success": False, "error": "30分钟数据获取失败"}

            # 级别2: 日线数据 → 周线中枢（仅在30分钟成功时尝试）
            if chan_result and chan_result.get("success"):
                try:
                    daily_analyzer = StockChanAnalyzer(
                        symbol=ak_symbol, name=stock_name, market=ak_market, timeframe='daily'
                    )
                    if daily_analyzer.fetch_data():
                        if daily_analyzer.analyze():
                            daily_summary = daily_analyzer.get_summary()
                            daily_chan_result = {
                                "success": True,
                                "last_pivot": daily_summary.get("last_pivot"),
                                "current_price": daily_summary.get("current_price", 0),
                                "pivot_count": daily_summary.get("pivot_count", 0),
                            }
                            print(f"  日线缠论: 中枢{daily_summary.get('pivot_count', 0)}个")
                        else:
                            daily_chan_result = {"success": False, "error": "日线分析失败"}
                    else:
                        daily_chan_result = {"success": False, "error": "日线数据获取失败"}
                except Exception as e:
                    daily_chan_result = {"success": False, "error": str(e)}

            # 多级别综合分析
            if chan_result and chan_result.get("success"):
                multi_result = analyze_multi_timeframe_pivot(chan_result, daily_chan_result)
                chan_result["multi_level"] = {
                    "tf30_state": multi_result.tf30_state,
                    "tf30_zg": multi_result.tf30_zg,
                    "tf30_zd": multi_result.tf30_zd,
                    "tf30_expansion": multi_result.tf30_expansion,
                    "daily_state": multi_result.daily_state,
                    "daily_zg": multi_result.daily_zg,
                    "daily_zd": multi_result.daily_zd,
                    "daily_expansion": multi_result.daily_expansion,
                    "combined_direction": multi_result.combined_direction,
                    "combined_signal": multi_result.combined_signal,
                }
                chan_result["daily_chan"] = daily_chan_result
                multi_detail = format_multi_level_detail(multi_result)
                print(f"  多级别综合: {multi_result.combined_direction}")
        except Exception as e:
            chan_result = {"success": False, "error": str(e)}
            print(f"  缠论分析异常: {str(e)[:80]}")
        analyzed_stock["chan_analysis"] = chan_result

        # (b) Bull/Bear analysis - with financial reports + report caching
        print(f"  技术评分: {tech_result.get('score', 0)}, 建议: {tech_result.get('recommendation', 'N/A')}")

        if self.llm_client.is_available():
            # Check for cached debate report
            cache_result = self._find_cached_debate_report(stock_code)
            if cache_result:
                cached_report, latest_period_from_cache = cache_result
                cached_period = cached_report.get("report_period", "")
                final_summary = cached_report.get("final_summary", {})
                print(f"  使用已缓存的多空论证报告 (财报期: {cached_period or 'N/A'})")
                analyzed_stock["bull_bear_analysis"] = final_summary
                analyzed_stock["debate_cached"] = True

                # 检查缓存是否缺少三维评分，或使用旧版维度结构(sub_scores)，若是则(重新)计算
                has_dimension_scores = (
                    "dimension_bull_bear_score" in final_summary
                    or "dimension_scores" in final_summary
                )
                # 检测旧版维度结构：company_quality 用 sub_scores 且缺新维度键(corporate_culture/understandability)
                _legacy_cq = final_summary.get("dimension_scores", {}).get("company_quality", {})
                _is_legacy_format = (
                    isinstance(_legacy_cq, dict)
                    and isinstance(_legacy_cq.get("sub_scores"), dict)
                    and "corporate_culture" not in _legacy_cq
                    and "understandability" not in _legacy_cq
                )
                if (not has_dimension_scores) or _is_legacy_format:
                    print(f"    缓存{'使用旧版维度评分(sub_scores)，升级为新版三维' if _is_legacy_format else '缺少三维评分'}，补充计算...")
                    try:
                        financial_data = self.financial_fetcher.get_stock_financial_data(
                            stock_code, stock_name
                        )
                    except Exception as e:
                        print(f"    财报获取失败: {str(e)[:60]}，使用空数据")
                        financial_data = {}
                    industry = self._classify_stock_by_code(stock_code, stock_name)
                    try:
                        dimension_comprehensive = self.company_quality_scorer.compute_comprehensive_score(
                            stock_name, stock_code, financial_data, industry
                        )
                        final_summary["dimension_scores"] = {
                            "company_quality": dimension_comprehensive["company_quality"],
                            "trend": dimension_comprehensive["trend"],
                            "valuation": dimension_comprehensive["valuation"],
                        }
                        dimension_bull_bear_score = self._compute_dimension_based_bull_bear_score(
                            dimension_comprehensive, final_summary
                        )
                        final_summary["dimension_bull_bear_score"] = dimension_bull_bear_score
                        print(f"    三维评分补充完成: 好公司{dimension_comprehensive['company_quality']['score']}, "
                              f"趋势{dimension_comprehensive['trend']['score']}, "
                              f"估值{dimension_comprehensive['valuation']['score']}")
                        # 更新缓存以包含三维评分
                        cached_report["final_summary"] = final_summary
                        self._save_debate_cache(
                            stock_code, stock_name, cached_report,
                            latest_period_from_cache or ""
                        )
                    except Exception as e:
                        print(f"    三维评分补充失败: {str(e)[:80]}")
                else:
                    # 缓存已有三维评分，验证并纠正"时间的朋友"评估
                    cached_ds = final_summary.get("dimension_scores", {})
                    cached_cq = cached_ds.get("company_quality", {}) if isinstance(cached_ds, dict) else {}
                    cached_subs = cached_cq.get("sub_scores", {}) if isinstance(cached_cq, dict) else {}
                    cached_fot = cached_cq.get("is_friend_of_time", None) if isinstance(cached_cq, dict) else None

                    # 基于实际sub_scores重新计算FOT
                    if isinstance(cached_subs, dict):
                        biz = cached_subs.get("business_model", 0)
                        cul = cached_subs.get("corporate_culture", 0)
                        und = cached_subs.get("understandability", 0)
                        # 如果有量化子维度，重新校验FOT
                        has_quant_subs = cul > 0 or und > 0  # 量化引擎子维度名称
                        if has_quant_subs:
                            correct_fot = (biz >= 5 and cul >= 4 and und >= 5)
                        else:
                            # LLM子维度(如corporate_governance)，无法验证，保持原值
                            correct_fot = cached_fot if cached_fot is not None else False
                    else:
                        correct_fot = cached_fot if cached_fot is not None else False

                    if cached_fot != correct_fot:
                        print(f"    FOT修正: {cached_fot} → {correct_fot} (biz={biz}, cul={cul}, und={und})")
                        if isinstance(cached_cq, dict):
                            cached_cq["is_friend_of_time"] = correct_fot
                        cached_ds["company_quality"] = cached_cq
                        final_summary["dimension_scores"] = cached_ds
                        cached_report["final_summary"] = final_summary
                        self._save_debate_cache(
                            stock_code, stock_name, cached_report,
                            latest_period_from_cache or ""
                        )
                    else:
                        print(f"    缓存已有完整FOT评估(correct={correct_fot})，跳过补充计算")

                    bb_score = final_summary.get("dimension_bull_bear_score", {}).get("bull_bear_score", 0)
                    bb_score = bb_score if isinstance(bb_score, (int, float)) else 0
                    print(f"    三维评分: {bb_score} (缓存)")

                rating = final_summary.get("investment_rating", "无法确定")
                confidence = final_summary.get("confidence_level", "中")
                print(f"  牛熊评级: {rating}, 信心: {confidence} (缓存)")
            else:
                print(f"  执行牛熊辩论分析 (LLM: {self.llm_client.get_provider_name()})...")
                bb_max_retries = 2
                bb_success = False
                for bb_attempt in range(bb_max_retries):
                    try:
                        bull_bear_result = self._analyze_bull_bear_with_financials(
                            stock_name, stock_code, tech_result
                        )
                        if "error" not in bull_bear_result:
                            analyzed_stock["bull_bear_analysis"] = bull_bear_result
                            rating = bull_bear_result.get("investment_rating", "无法确定")
                            confidence = bull_bear_result.get("confidence_level", "中")
                            base_score = RATING_BASE_SCORE.get(rating, 0)
                            confidence_mult = CONFIDENCE_MULTIPLIER.get(confidence, 1.0)
                            bb_score = max(-10, min(10, round(base_score * confidence_mult, 1)))
                            print(f"  牛熊评级: {rating}, 信心: {confidence}, 评分: {bb_score}")
                            bb_success = True
                            break
                        else:
                            if bb_attempt < bb_max_retries - 1:
                                print(f"  牛熊分析LLM调用失败，5秒后重试 ({bb_attempt+1}/{bb_max_retries})...")
                                time.sleep(5)
                            else:
                                analyzed_stock["bull_bear_analysis"] = bull_bear_result
                                print(f"  牛熊分析失败（已重试{bb_max_retries}次）: {str(bull_bear_result.get('error', ''))[:80]}")
                    except Exception as e:
                        if bb_attempt < bb_max_retries - 1:
                            print(f"  牛熊分析异常，5秒后重试 ({bb_attempt+1}/{bb_max_retries}): {str(e)[:60]}")
                            time.sleep(5)
                        else:
                            print(f"  牛熊分析失败（已重试{bb_max_retries}次）: {str(e)[:100]}")
                            analyzed_stock["bull_bear_analysis"] = {"error": str(e)}

        return analyzed_stock

    def _analyze_stock_pool(self, stock_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        analyzed_stocks = []
        import threading

        for i, stock in enumerate(stock_pool, 1):
            stock_code = stock["stock_code"]
            stock_name = stock.get("stock_name", f"股票{stock_code}")

            # Add inter-stock delay to avoid API rate limiting
            if i > 1:
                time.sleep(1)

            print(f"\n[{i}/{len(stock_pool)}] 分析 {stock_name} ({stock_code})...")

            # Run analysis with per-stock timeout (600s) to prevent hangs
            # 600s = 10min, enough for LLM debate (3 rounds) which can take 3-5min per stock
            result_holder = [None]
            error_holder = [None]

            def _run():
                try:
                    result_holder[0] = self._analyze_single_stock(stock)
                except Exception as e:
                    error_holder[0] = e

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=600)

            if t.is_alive():
                print(f"  ⚠ {stock_name} 分析超时(600s)，跳过")
                # Thread is daemon, will be cleaned up when process exits
                continue

            if error_holder[0]:
                print(f"  ⚠ {stock_name} 分析异常: {str(error_holder[0])[:80]}")
                continue

            analyzed_stock = result_holder[0]
            if analyzed_stock is not None:
                analyzed_stocks.append(analyzed_stock)

        # Save dividend yield cache to file for reuse on same-day runs
        self._save_dividend_yield_cache()
        self._save_cape_cache()

        return analyzed_stocks

    def _analyze_bull_bear_with_financials(
        self,
        stock_name: str,
        stock_code: str,
        tech_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Bull/bear analysis with real financial report data. Saves report for caching.

        集成三维评分系统：好公司、趋势、估值
        """

        # Step 1: Fetch real financial data
        print(f"    获取财报数据...")
        try:
            financial_data = self.financial_fetcher.get_stock_financial_data(
                stock_code, stock_name
            )
        except Exception as e:
            print(f"    财报获取失败: {str(e)[:60]}，使用技术指标数据")
            financial_data = {}

        # Step 1.5: 获取行业信息（用于三维评分）
        industry = self._classify_stock_by_code(stock_code, stock_name)

        # Step 1.6: 计算三维评分（量化引擎）
        print(f"    计算三维评分...")
        try:
            dimension_comprehensive = self.company_quality_scorer.compute_comprehensive_score(
                stock_name, stock_code, financial_data, industry
            )
            print(f"    三维评分: 好公司{dimension_comprehensive['company_quality']['score']}, "
                  f"趋势{dimension_comprehensive['trend']['score']}, "
                  f"估值{dimension_comprehensive['valuation']['score']}")
        except Exception as e:
            print(f"    三维评分计算失败: {str(e)[:60]}")
            dimension_comprehensive = None

        # Step 2: Enrich with technical analysis data
        data_summary = tech_result.get("data_summary", {})
        latest_price = data_summary.get("close", 0)
        ma25 = data_summary.get("ma25", 0)
        vol5 = data_summary.get("vol5", 0)
        vol60 = data_summary.get("vol60", 0)
        price_diff_pct = ((latest_price - ma25) / ma25 * 100) if ma25 > 0 else 0
        vol_ratio = vol5 / vol60 if vol60 > 0 else 0

        if vol_ratio > 1.2:
            volume_trend = "成交量明显放大"
        elif vol_ratio > 0.8:
            volume_trend = "成交量基本持平"
        else:
            volume_trend = "成交量萎缩"

        situation = tech_result.get("situation", {})
        tech_recommendation = tech_result.get("recommendation", "观望")
        tech_score = tech_result.get("score", 0)

        # Merge tech data into financial_data
        tech_overview = (
            f"技术面：当前价格{latest_price}, MA25={ma25:.2f}, "
            f"偏离均线{price_diff_pct:.1f}%, 量比{vol_ratio:.2f}({volume_trend}), "
            f"技术建议: {tech_recommendation}(评分{tech_score}), "
            f"形态: {situation.get('description', 'N/A')}"
        )

        if financial_data.get("business_overview"):
            financial_data["business_overview"] += f"\n\n{tech_overview}"
        else:
            financial_data["business_overview"] = f"{stock_name} ({stock_code})\n{tech_overview}"

        if not financial_data.get("key_metrics"):
            financial_data["key_metrics"] = {}
        financial_data["key_metrics"].update({
            "current_price": latest_price,
            "ma25": ma25,
            "price_vs_ma25_pct": round(price_diff_pct, 2),
            "volume_trend": volume_trend,
            "vol_ratio": round(vol_ratio, 2),
            "tech_recommendation": tech_recommendation,
            "tech_score": tech_score,
            "situation_type": situation.get("type", "其他"),
        })

        # Step 3: Conduct debate with full financial data, save report
        try:
            debate_result = self.debate_agent.conduct_debate(
                stock_name, stock_code, financial_data, save_report=True
            )
        except Exception as e:
            err_str = str(e)
            # LLM 故障时回退到量化三维评分：好公司/趋势/估值由 CompanyQualityScorer
            # 量化引擎计算、不依赖 LLM。否则整份报告的"价值评分"会变成 N/A。
            if dimension_comprehensive:
                print(f"    LLM辩论失败({err_str[:60]})，回退到量化三维评分兜底")
                return self._build_quantitative_fallback_summary(
                    financial_data, dimension_comprehensive
                )
            if "超时" in err_str or "Timeout" in err_str or "timed out" in err_str.lower():
                print(f"    LLM调用超时，跳过牛熊分析")
                return {"error": f"LLM超时: {err_str[:100]}"}
            raise

        final_summary = debate_result.get("final_summary", {})

        # 融合三维评分到最终摘要中
        if dimension_comprehensive:
            # 优先使用量化评分，如果LLM也返回了dimension_scores则进行融合
            llm_dimension_scores = final_summary.get("dimension_scores", {})

            # 融合策略：60%量化 + 40%LLM定性
            if llm_dimension_scores:
                fused_dimension_scores = self._fuse_dimension_scores(
                    dimension_comprehensive, llm_dimension_scores
                )
                final_summary["dimension_scores"] = fused_dimension_scores
            else:
                # 如果LLM没有返回三维评分，直接使用量化评分
                final_summary["dimension_scores"] = {
                    "company_quality": dimension_comprehensive["company_quality"],
                    "trend": dimension_comprehensive["trend"],
                    "valuation": dimension_comprehensive["valuation"]
                }

            # 计算基于三维评分的牛熊评分（替代原有的rating+confidence查表逻辑）
            dimension_bull_bear_score = self._compute_dimension_based_bull_bear_score(
                dimension_comprehensive, final_summary
            )
            final_summary["dimension_bull_bear_score"] = dimension_bull_bear_score

        # Extract dividend yield from financial data for report display
        dividend_yield = financial_data.get("key_metrics", {}).get("股息率TTM", None)
        if dividend_yield and dividend_yield != "N/A":
            final_summary["dividend_yield"] = dividend_yield

        # Step 4: Save cached report with financial period info
        report_period = self._extract_report_period(financial_data)
        self._save_debate_cache(stock_code, stock_name, debate_result, report_period)

        return final_summary

    def _build_quantitative_fallback_summary(
        self, financial_data: Dict[str, Any], dimension_comprehensive: Dict[str, Any]
    ) -> Dict[str, Any]:
        """LLM 牛熊辩论不可用时，用量化三维评分构造兜底摘要。

        好公司/趋势/估值三个维度由 CompanyQualityScorer 量化引擎计算，不依赖 LLM。
        LLM 故障（如余额不足/连接失败）时用它兜底，避免报告"价值评分"整体变成 N/A。
        """
        dimension_bull_bear_score = self._compute_dimension_based_bull_bear_score(
            dimension_comprehensive, {}
        )
        summary = {
            "investment_rating": dimension_bull_bear_score["investment_rating"],
            "confidence_level": dimension_bull_bear_score["confidence_level"],
            "dimension_scores": {
                "company_quality": dimension_comprehensive.get("company_quality", {}),
                "trend": dimension_comprehensive.get("trend", {}),
                "valuation": dimension_comprehensive.get("valuation", {}),
            },
            "dimension_bull_bear_score": dimension_bull_bear_score,
            "comprehensive_conclusion": "（LLM 牛熊辩论不可用，价值评分由量化三维引擎计算）",
        }
        dividend_yield = financial_data.get("key_metrics", {}).get("股息率TTM", None)
        if dividend_yield and dividend_yield != "N/A":
            summary["dividend_yield"] = dividend_yield
        return summary

    # ================================================================
    # Debate Report Cache
    # ================================================================

    def _load_dividend_yield_cache(self):
        """Load dividend yield cache from file if it's from today."""
        try:
            if self._dividend_yield_cache_file.exists():
                with open(self._dividend_yield_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cache_date = data.get("date", "")
                today = datetime.now().strftime("%Y-%m-%d")
                if cache_date == today:
                    self._dividend_yield_cache = data.get("cache", {})
                    print(f"  加载股息率缓存: {len(self._dividend_yield_cache)} 只股票 (日期: {cache_date})")
        except Exception:
            pass

    def _load_prev_elliott_scores(self) -> Dict[str, float]:
        """Load previous trading day's elliott scores from JSON report for EMA seeding."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            json_files = sorted(self.daily_selection_dir.glob("每日选股_*.json"), reverse=True)
            for jf in json_files:
                date_str = jf.stem.replace("每日选股_", "")
                if date_str < today:
                    with open(jf, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    scores = {}
                    for r in data.get("recommendations", []):
                        code = r.get("stock_code", "")
                        if code and r.get("has_elliott", False):
                            scores[code] = r.get("elliott_score", 0)
                    if scores:
                        print(f"  加载前日波浪评分: {len(scores)} 只股票 (日期: {date_str})")
                        # Seed EMA cache from previous report
                        self._elliott_ema_cache.update(scores)
                    return scores
        except Exception:
            pass
        return {}

    def _save_dividend_yield_cache(self):
        """Save dividend yield cache to file with today's date."""
        try:
            data = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "cache": {k: v for k, v in self._dividend_yield_cache.items() if v is not None},
            }
            with open(self._dividend_yield_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_cape_cache(self):
        """Load CAPE cache from file if it's from today."""
        try:
            if self._cape_cache_file.exists():
                with open(self._cape_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cache_date = data.get("date", "")
                today = datetime.now().strftime("%Y-%m-%d")
                if cache_date == today:
                    self._cape_cache = data.get("cache", {})
                    print(f"  加载CAPE缓存: {len(self._cape_cache)} 只股票 (日期: {cache_date})")
        except Exception:
            pass

    def _save_cape_cache(self):
        """Save CAPE cache to file with today's date."""
        try:
            data = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "cache": {k: v for k, v in self._cape_cache.items() if v is not None},
            }
            with open(self._cape_cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _fetch_dividend_yield(self, stock_code: str, current_price: float = None) -> Optional[float]:
        """Fetch dividend yield with multiple fallback sources.
        Source 1: AKShare stock_fhps_detail_em (stable, not rate-limited)
        Source 2: yfinance (fallback, may be rate-limited)
        Returns dividend yield as percentage (e.g. 2.5) or None.
        """
        # Normalize stock code for AKShare (remove suffix)
        ak_code = stock_code.split(".")[0] if "." in stock_code else stock_code
        is_hk = stock_code.endswith(".HK")

        # Source 1: AKShare stock_fhps_detail_em (primary - stable, no rate limit)
        if not is_hk:
            try:
                import akshare as ak
                df = ak.stock_fhps_detail_em(symbol=ak_code)
                if df is not None and len(df) > 0:
                    impl = df[df['方案进度'] == '实施分配'].sort_values('最新公告日期', ascending=False)
                    if len(impl) > 0:
                        # TTM: sum dividends from report periods in the last 12 months
                        latest_period = str(impl.iloc[0]['报告期'])
                        latest_year = int(latest_period[:4])
                        latest_month = int(latest_period[5:7]) if len(latest_period) >= 7 else 12
                        total_div = 0.0
                        count = 0
                        for _, row in impl.iterrows():
                            period = str(row['报告期'])
                            div = row.get('现金分红-现金分红比例', 0)
                            if isinstance(div, (int, float)) and div > 0:
                                p_year = int(period[:4])
                                p_month = int(period[5:7]) if len(period) >= 7 else 0
                                if p_year == latest_year:
                                    total_div += div / 10
                                    count += 1
                                elif p_year == latest_year - 1 and p_month > latest_month:
                                    total_div += div / 10
                                    count += 1
                        if total_div > 0 and current_price and current_price > 0:
                            yield_pct = round(total_div / current_price * 100, 2)
                            if yield_pct <= 15:
                                print(f"  股息率TTM: {yield_pct}% (AKShare, {count}次分红)")
                                return yield_pct
            except Exception:
                pass
        else:
            # Source 1b: AKShare stock_hk_fhpx_detail_ths for HK stocks
            try:
                import akshare as ak
                # HK stocks use 4-digit HKEX code (strip leading zero from 5-digit padded code)
                hk_code_4 = ak_code[1:] if len(ak_code) == 5 and ak_code[0] == '0' else ak_code
                df = ak.stock_hk_fhpx_detail_ths(symbol=hk_code_4)
                if df is not None and len(df) > 0:
                    completed = df[df['进度'] == '实施完成'].copy()
                    if len(completed) > 0:
                        # Parse ex-dates for TTM calculation
                        ex_dates = []
                        for _, row in completed.iterrows():
                            ex_date = row.get('除净日')
                            if ex_date and str(ex_date) != 'NaT' and str(ex_date) != 'nan':
                                try:
                                    ex_dt = datetime.strptime(str(ex_date)[:10], '%Y-%m-%d')
                                    plan = str(row.get('方案', ''))
                                    match = re.search(r'每股[^\d]*([\d.]+)', plan)
                                    if match:
                                        amount = float(match.group(1))
                                        if '美元' in plan:
                                            amount = amount * 7.8  # USD/HKD peg
                                        ex_dates.append((ex_dt, amount))
                                except (ValueError, TypeError):
                                    pass
                        if ex_dates:
                            ex_dates.sort(key=lambda x: x[0], reverse=True)
                            latest_dt = ex_dates[0][0]
                            cutoff_dt = latest_dt - timedelta(days=365)
                            total_div = 0.0
                            count = 0
                            for ex_dt, amount in ex_dates:
                                if ex_dt >= cutoff_dt:
                                    total_div += amount
                                    count += 1
                            if total_div > 0 and current_price and current_price > 0:
                                yield_pct = round(total_div / current_price * 100, 2)
                                if yield_pct <= 15:
                                    print(f"  股息率TTM: {yield_pct}% (AKShare HK, {count}次分红)")
                                    return yield_pct
            except Exception:
                pass

        # Source 2: yfinance (fallback - may be rate limited)
        try:
            import yfinance as yf
            if stock_code.endswith(".SH"):
                yf_code = stock_code.replace(".SH", ".SS")
            elif stock_code.endswith(".SZ"):
                yf_code = stock_code
            elif stock_code.endswith(".HK"):
                yf_code = stock_code
            else:
                yf_code = stock_code

            time.sleep(0.5)  # Rate limit protection
            ticker = yf.Ticker(yf_code)
            info = ticker.info

            # Check for rate limit error
            if not info or (info.get("regularMarketPrice") is None and info.get("previousClose") is None):
                time.sleep(3)
                ticker = yf.Ticker(yf_code)
                info = ticker.info

            trail_yield = info.get("trailingAnnualDividendYield")
            if trail_yield and isinstance(trail_yield, (int, float)) and 0 < trail_yield < 0.15:
                dividend_yield = round(trail_yield * 100, 2)
                print(f"  股息率TTM: {dividend_yield}% (yfinance)")
                return dividend_yield
            div_yield = info.get("dividendYield")
            if div_yield and isinstance(div_yield, (int, float)) and div_yield > 0:
                if div_yield > 1:
                    yield_pct = round(div_yield, 2)
                else:
                    yield_pct = round(div_yield * 100, 2)
                if yield_pct <= 15:
                    print(f"  股息率TTM: {yield_pct}% (yfinance)")
                    return yield_pct
            trail_rate = info.get("trailingAnnualDividendRate")
            price = info.get("currentPrice") or info.get("previousClose")
            if trail_rate and price and isinstance(trail_rate, (int, float)) and isinstance(price, (int, float)) and price > 0:
                yield_pct = round(trail_rate / price * 100, 2)
                if yield_pct <= 15:
                    print(f"  股息率TTM: {yield_pct}% (yfinance computed)")
                    return yield_pct
        except Exception as e:
            err_msg = str(e)[:80]
            if "Too Many" in err_msg or "Rate" in err_msg:
                print(f"  yfinance限流: {err_msg}")

        return None

    def _fetch_cape(self, stock_code: str, current_price: float = None) -> Optional[float]:
        """Fetch CAPE (Cyclically Adjusted P/E Ratio).

        Formula: CAPE = Current Price / 5-year average annual EPS

        Source 1: AKShare stock_financial_abstract for 5-year annual EPS
                  (uses year-end 基本每股收益 data, going back up to 10 years)
        Source 2: yfinance (fallback, trailingPE)

        Returns CAPE ratio (e.g. 15.5) or None.
        """
        if not current_price or current_price <= 0:
            return None

        ak_code = stock_code.split(".")[0] if "." in stock_code else stock_code
        is_hk = stock_code.endswith(".HK")

        # Source 1: AKShare stock_financial_abstract (stable, widely used)
        if not is_hk:
            try:
                import akshare as ak
                df = ak.stock_financial_abstract(symbol=ak_code)
                if df is not None and len(df) > 0:
                    # Find the "基本每股收益" row
                    eps_row = None
                    for _, row in df.iterrows():
                        if str(row.get("指标", "")).strip() == "基本每股收益":
                            eps_row = row
                            break

                    if eps_row is not None:
                        # Collect year-end EPS values (columns ending with "1231")
                        eps_by_year = {}
                        for col in df.columns:
                            col_str = str(col).strip()
                            # Match annual report period: YYYY1231
                            if len(col_str) >= 8 and col_str[-4:] == "1231":
                                year = int(col_str[:4])
                                val = eps_row.get(col)
                                if val is not None and str(val) != "nan":
                                    try:
                                        eps_val = float(val)
                                        if eps_val > 0:
                                            eps_by_year[year] = eps_val
                                    except (ValueError, TypeError):
                                        pass

                        if len(eps_by_year) >= 3:
                            # Take the most recent 5 years
                            sorted_years = sorted(eps_by_year.keys(), reverse=True)
                            recent_years = sorted_years[:5]
                            eps_sum = sum(eps_by_year[y] for y in recent_years)
                            avg_eps = eps_sum / len(recent_years)

                            if avg_eps > 0:
                                cape = round(current_price / avg_eps, 2)
                                if 0 < cape < 500:
                                    print(f"  CAPE: {cape} (AKShare, {len(recent_years)}年年均EPS={avg_eps:.2f})")
                                    return cape
                        else:
                            print(f"  CAPE: 年度EPS数据不足({len(eps_by_year)}年), 跳过")
            except Exception as e:
                print(f"  CAPE AKShare获取失败: {str(e)[:60]}")
        else:
            # Source 1b: AKShare stock_financial_hk_analysis_indicator_em for HK stocks
            try:
                import akshare as ak
                hk_code_5 = ak_code.zfill(5)  # e.g. "700" -> "00700"
                df = ak.stock_financial_hk_analysis_indicator_em(symbol=hk_code_5)
                if df is not None and len(df) > 0:
                    # Collect annual BASIC_EPS values, filter positive
                    eps_values = []
                    for _, row in df.iterrows():
                        try:
                            eps_val = float(row.get('BASIC_EPS', 0))
                            if eps_val > 0:
                                eps_values.append(eps_val)
                        except (ValueError, TypeError):
                            pass
                    if len(eps_values) >= 3:
                        recent = eps_values[:5]  # Data is already sorted by REPORT_DATE desc
                        avg_eps = sum(recent) / len(recent)
                        if avg_eps > 0:
                            cape = round(current_price / avg_eps, 2)
                            if 0 < cape < 500:
                                print(f"  CAPE: {cape} (AKShare HK, {len(recent)}年年均EPS={avg_eps:.2f})")
                                return cape
                    else:
                        print(f"  CAPE: HK年度EPS数据不足({len(eps_values)}年), 跳过")
            except Exception as e:
                print(f"  CAPE HK AKShare获取失败: {str(e)[:60]}")

        # Source 2: yfinance (fallback to trailing PE)
        try:
            import yfinance as yf
            if stock_code.endswith(".SH"):
                yf_code = stock_code.replace(".SH", ".SS")
            elif stock_code.endswith(".SZ"):
                yf_code = stock_code
            elif stock_code.endswith(".HK"):
                yf_code = stock_code
            else:
                yf_code = stock_code

            time.sleep(0.5)
            ticker = yf.Ticker(yf_code)
            info = ticker.info
            if info:
                trailing_pe = info.get("trailingPE")
                if trailing_pe and isinstance(trailing_pe, (int, float)) and 0 < trailing_pe < 500:
                    print(f"  CAPE: {trailing_pe} (yfinance trailingPE fallback)")
                    return round(float(trailing_pe), 2)
        except Exception as e:
            err_msg = str(e)[:80]
            if "Too Many" in err_msg or "Rate" in err_msg:
                print(f"  yfinance限流: {err_msg}")

        return None

    def _find_cached_debate_report(self, stock_code: str) -> Optional[tuple]:
        """Find a cached debate report for the given stock.
        Returns (report_data, latest_period) tuple if valid cache exists, None otherwise.
        A report is stale if a new financial report period has been published since.
        """
        # Find the latest report for this stock code
        code_suffix = stock_code.split(".")[0]
        pattern = f"*_{code_suffix}_多空辩论报告.json"
        candidates = list(self.debate_report_dir.rglob(pattern))

        # Also try with the full code (e.g., 600519.SH)
        pattern2 = f"*_{stock_code}_多空辩论报告.json"
        candidates.extend(list(self.debate_report_dir.rglob(pattern2)))

        if not candidates:
            return None

        # Get the most recent report
        latest_file = max(candidates, key=lambda f: f.stat().st_mtime)

        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)
        except Exception:
            return None

        # Check if the report has a report_period and whether it's still current
        cached_period = report_data.get("report_period", "")

        # Always check for new financial reports, regardless of whether cached_period exists
        latest_period = self._get_latest_report_period(stock_code)

        if cached_period and latest_period:
            # Both periods available — direct comparison
            if latest_period > cached_period:
                print(f"    新财报已发布({latest_period} > 缓存{cached_period})，需要更新")
                return None
            elif latest_period == cached_period:
                # Periods match, but check if the analysis was done BEFORE this report
                # was published (can happen when report_period was backfilled).
                if self._analysis_predates_report(report_data, cached_period):
                    return None
        elif latest_period:
            # No cached_period but we can get latest_period — backfill it.
            # Check if analysis was done before this report was published.
            if self._analysis_predates_report(report_data, latest_period):
                print(f"    缓存无财报期，分析日期早于财报发布，需要更新")
                return None
            # Analysis date is after the report publish date, or we can't determine —
            # backfill the period for future comparisons.
            print(f"    缓存无财报期，当前最新财报期: {latest_period}，将回填")
        else:
            # No latest_period available — fall back to age-based check
            analysis_date_str = report_data.get("analysis_date", "")
            try:
                analysis_date = datetime.strptime(analysis_date_str, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - analysis_date).days > 90:
                    print(f"    缓存报告超过90天且无法获取财报期，需要更新")
                    return None
            except (ValueError, TypeError):
                return None

        return (report_data, latest_period)

    def _save_debate_cache(
        self,
        stock_code: str,
        stock_name: str,
        debate_result: Dict[str, Any],
        report_period: str,
    ) -> None:
        """Save debate result with report period info for caching."""
        debate_result["report_period"] = report_period
        debate_result["stock_code"] = stock_code
        debate_result["stock_name"] = stock_name

        # The DebateAgent already saves the report if save_report=True
        # We just need to ensure report_period is in the saved file
        # Find the latest saved report and update it
        code_suffix = stock_code.split(".")[0]
        candidates = list(self.debate_report_dir.rglob(f"*_{code_suffix}_多空辩论报告.json"))
        candidates.extend(list(self.debate_report_dir.rglob(f"*_{stock_code}_多空辩论报告.json")))
        # HK stocks: also try alternate code format
        if stock_code.endswith(".HK"):
            alt_num = str(int(code_suffix))
            alt_code = f"{alt_num}.HK"
            if alt_code != stock_code:
                candidates.extend(list(self.debate_report_dir.rglob(f"*_{alt_code}_多空辩论报告.json")))

        if candidates:
            latest_file = max(candidates, key=lambda f: f.stat().st_mtime)
            try:
                with open(latest_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing["report_period"] = report_period
                with open(latest_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2, default=str)
            except Exception:
                pass

    def _analysis_predates_report(self, report_data: Dict[str, Any], period: str) -> bool:
        """Check if the analysis was done before the financial report was published.

        Uses quarter-specific filing deadlines for Chinese A/HK stocks:
        - Q1 (03-31): due April 30
        - H1  (06-30): due August 31
        - Q3  (09-30): due October 31
        - Annual (12-31): due April 30 next year

        We consider the report "available" 15 days before the deadline,
        since most companies file well before the deadline.
        Returns True if the analysis predates the report (stale), False otherwise.
        """
        analysis_date_str = report_data.get("analysis_date", "")
        if not analysis_date_str:
            return False  # Can't determine, don't flag

        try:
            analysis_dt = datetime.strptime(analysis_date_str, "%Y-%m-%d %H:%M:%S")
            period_dt = datetime.strptime(period, "%Y-%m-%d")
            year = period_dt.year
            month = period_dt.month

            # Filing deadlines per quarter
            if month == 3:    # Q1
                deadline = datetime(year, 4, 30)
            elif month == 6:  # H1
                deadline = datetime(year, 8, 31)
            elif month == 9:  # Q3
                deadline = datetime(year, 10, 31)
            elif month == 12: # Annual
                deadline = datetime(year + 1, 4, 30)
            else:
                deadline = period_dt + timedelta(days=90)

            # Most companies file at least 15 days before the deadline
            earliest_available = deadline - timedelta(days=15)

            if analysis_dt < earliest_available:
                print(f"    分析日期({analysis_date_str[:10]})早于财报最早发布({earliest_available.strftime('%Y-%m-%d')})，需要更新")
                return True
        except (ValueError, TypeError):
            pass
        return False

    def _extract_report_period(self, financial_data: Dict[str, Any]) -> str:
        """Extract the latest financial report period from financial data."""
        for section in ["income_statement", "balance_sheet", "cash_flow"]:
            section_data = financial_data.get(section, {})
            if isinstance(section_data, dict):
                # Look for common period field names
                for key in ["报告期", "报告日期", "report_date", "period"]:
                    if key in section_data:
                        return str(section_data[key])
        return ""

    def _get_latest_report_period(self, stock_code: str) -> Optional[str]:
        """Get the latest available financial report period for a stock via akshare.
        Returns period string like '2025-12-31' or None.
        """
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
        is_hk = ".HK" in stock_code

        if is_hk:
            # HK stocks: use stock_financial_hk_analysis_indicator_em (5-digit code)
            try:
                import akshare as ak
                hk_code = code.zfill(5)  # e.g. "700" -> "00700"
                df = ak.stock_financial_hk_analysis_indicator_em(symbol=hk_code)
                if df is not None and not df.empty and "REPORT_DATE" in df.columns:
                    raw = str(df.iloc[0]["REPORT_DATE"])[:10]
                    if raw and raw != "None":
                        return raw
            except Exception:
                pass
        else:
            # A stocks: use stock_financial_report_sina (most reliable)
            try:
                import akshare as ak
                prefix = "sh" if stock_code.endswith(".SH") else "sz"
                df = ak.stock_financial_report_sina(stock=f"{prefix}{code}", symbol="利润表")
                if df is not None and not df.empty and "报告日" in df.columns:
                    raw = str(df.iloc[0]["报告日"])
                    # Format: "20260331" -> "2026-03-31"
                    if len(raw) >= 8 and raw.isdigit():
                        formatted = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
                        return formatted
            except Exception:
                pass

            # Fallback: stock_profit_sheet_by_yearly_em (may be broken)
            try:
                import akshare as ak
                df = ak.stock_profit_sheet_by_yearly_em(symbol=code)
                if df is not None and not df.empty and "报告期" in df.columns:
                    return str(df.iloc[0]["报告期"])[:10]
            except Exception:
                pass

        return None

    # ================================================================
    # Step 5: 给出买入推荐评级
    # ================================================================

    def _generate_recommendations(
        self, analyzed_stocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        recommendations = []

        # Load previous day's elliott scores for smoothing
        prev_elliott_scores = self._load_prev_elliott_scores()

        for stock in analyzed_stocks:
            tech_analysis = stock.get("technical_analysis", {})
            bull_bear_analysis = stock.get("bull_bear_analysis", {})
            elliott_analysis = stock.get("elliott_analysis", {})

            # 时间的朋友标记（来自三维评分 company_quality.is_friend_of_time）
            _dim_scores = bull_bear_analysis.get("dimension_scores", {}) if isinstance(bull_bear_analysis, dict) else {}
            _company_quality = _dim_scores.get("company_quality", {}) if isinstance(_dim_scores, dict) else {}
            is_time_friend = bool(_company_quality.get("is_friend_of_time", False)) if isinstance(_company_quality, dict) else False

            # Tech score
            tech_score = tech_analysis.get("score", 0)
            if isinstance(tech_score, dict):
                tech_score = tech_score.get("normalized_score", 0)

            # Bull/Bear score - 使用新的三维评分系统
            has_bull_bear = (
                bull_bear_analysis
                and "error" not in bull_bear_analysis
            )

            if has_bull_bear:
                # 优先使用 dimension_bull_bear_score（来自三维评分引擎）
                if "dimension_bull_bear_score" in bull_bear_analysis:
                    dimension_bb_data = bull_bear_analysis["dimension_bull_bear_score"]
                    bull_bear_score = dimension_bb_data.get("bull_bear_score", 0)
                    rating = dimension_bb_data.get("investment_rating", "持有")
                    # confidence_level 在新系统中由评分强度决定
                elif "dimension_scores" in bull_bear_analysis:
                    # 从dimension_scores计算价值评分
                    dimension_scores = bull_bear_analysis["dimension_scores"]
                    if isinstance(dimension_scores, dict):
                        company = dimension_scores.get("company_quality", {})
                        trend = dimension_scores.get("trend", {})
                        valuation = dimension_scores.get("valuation", {})

                        company_score = company.get("score", 0) if isinstance(company, dict) else 0
                        trend_score = trend.get("score", 0) if isinstance(trend, dict) else 0
                        valuation_score = valuation.get("score", 0) if isinstance(valuation, dict) else 0

                        # 价值评分 = 好公司45% + 趋势30% + 估值25%
                        bull_bear_score = round(company_score * 0.45 + trend_score * 0.3 + valuation_score * 0.25, 1)
                        rating = "持有"  # 默认评级
                else:
                    # 回退到原有的 rating + confidence 查表逻辑
                    rating = bull_bear_analysis.get("investment_rating", "持有")
                    confidence = bull_bear_analysis.get("confidence_level", "中")
                    base_score = RATING_BASE_SCORE.get(rating, 0)
                    confidence_mult = CONFIDENCE_MULTIPLIER.get(confidence, 1.0)
                    bull_bear_score = round(base_score * confidence_mult, 1)

                bull_bear_score = max(-10.0, min(10.0, bull_bear_score))
            else:
                bull_bear_score = 0
                rating = None

            # Elliott wave score
            has_elliott = (
                elliott_analysis
                and isinstance(elliott_analysis, dict)
                and "error" not in elliott_analysis
                and elliott_analysis.get("wave_position") not in (None, "分析失败", "数据不足")
            )
            elliott_score = elliott_analysis.get("elliott_score", 0) if has_elliott else 0

            # Elliott score smoothing: 70% today + 30% EMA (covers multi-day history)
            # This prevents large day-to-day swings from wave reclassification
            stock_code = stock.get("stock_code", "")
            if has_elliott:
                if stock_code in self._elliott_ema_cache:
                    prev_ema = self._elliott_ema_cache[stock_code]
                    elliott_score = round(elliott_score * 0.7 + prev_ema * 0.3, 1)
                self._elliott_ema_cache[stock_code] = elliott_score

            # Chan Theory score
            chan_analysis = stock.get("chan_analysis", {})
            has_chan = (
                chan_analysis
                and isinstance(chan_analysis, dict)
                and chan_analysis.get("success") is True
            )
            chan_score = chan_analysis.get("chan_score", 0) if has_chan else 0

            # 新评分体系：技术分析50% + 价值分析50%
            # 技术分析 = 短期时机40% + 中期趋势60%（缠论信号不参与评分，仅作展示）
            # 价值分析 = 好公司45% + 趋势30% + 估值25%（原三维评分）

            # 计算技术分析总分（归一化到0-10分制）
            # 注意：chan_score已不再参与技术评分，仅用于显示缠论信号
            if has_elliott:
                # 有短期时机和中期趋势评分
                technical_total = (
                    tech_score * TECHNICAL_SUB_WEIGHTS["short_term_timing"] +
                    elliott_score * TECHNICAL_SUB_WEIGHTS["medium_term_trend"]
                )
            else:
                # 只有短期时机评分
                technical_total = tech_score

            # 计算综合评分（技术50% + 价值50%）
            if has_bull_bear:
                combined_score = (
                    technical_total * NEW_STOCK_WEIGHTS["technical_analysis"] +
                    bull_bear_score * NEW_STOCK_WEIGHTS["value_analysis"]
                )
            else:
                combined_score = technical_total  # 如果没有价值评分，直接使用技术评分

            # ============================================================
            # 估值风险调整已移除（CAPE + 股息率）
            # ============================================================
            # 在新的三维评分系统中，估值已作为独立维度纳入评分
            # 不再需要后置的 CAPE/股息率调整
            # 这些指标已在 CompanyQualityScorer 的估值评分中处理
            # CAPE 和股息率数据仍保留在 stock 中用于报告展示


            # Determine recommendation rating (unified thresholds)
            tech_positive = tech_score > 0
            bull_positive = bull_bear_score > 1.5 and has_bull_bear  # "持有"~1.0不算正
            both_positive = tech_positive and bull_positive

            if combined_score >= RATING_THRESHOLDS["强烈推荐"] and both_positive:
                rec_rating = "强烈推荐"
            elif combined_score >= RATING_THRESHOLDS["推荐"]:
                rec_rating = "推荐"
            elif combined_score >= RATING_THRESHOLDS["中性"]:
                rec_rating = "中性"
            elif combined_score >= RATING_THRESHOLDS["不推荐"]:
                rec_rating = "不推荐"
            else:
                rec_rating = "强烈不推荐"

            # 波浪强烈看空时，限制最高评级为"中性"
            if has_elliott and elliott_score <= -6:
                rating_order = {"强烈推荐": 0, "推荐": 1, "中性": 2, "不推荐": 3, "强烈不推荐": 4}
                if rating_order.get(rec_rating, 2) < rating_order["中性"]:
                    rec_rating = "中性"

            # Risk level from technical analysis
            risk_level = tech_analysis.get("risk_level", "中")

            # Operation suggestion from technical analysis
            operation_suggestion = tech_analysis.get("recommendation", "观望")

            # Dividend yield: prefer direct fetch, fallback to bull/bear analysis
            dividend_yield = stock.get("dividend_yield")
            if dividend_yield is None and has_bull_bear:
                dividend_yield = bull_bear_analysis.get("dividend_yield")

            # CAPE: from direct fetch only (no bull/bear fallback)
            cape = stock.get("cape")

            # Generate buy/sell point advice
            buy_sell = self._generate_buy_sell_advice(
                tech_analysis, elliott_analysis, rec_rating, combined_score
            )

            # Chan signals display text
            chan_signals_text = _format_chan_signals(
                chan_analysis.get("active_buys", []) if has_chan else [],
                chan_analysis.get("active_sells", []) if has_chan else [],
            )

            recommendation = {
                **stock,
                "tech_score": tech_score,
                "bull_bear_score": bull_bear_score,
                "elliott_score": elliott_score,
                "chan_score": chan_score,
                "combined_score": combined_score,
                "rating": rec_rating,
                "both_positive": both_positive,
                "is_time_friend": is_time_friend,
                "bull_bear_missing": not has_bull_bear,
                "has_elliott": has_elliott,
                "has_chan": has_chan,
                "chan_signals": chan_signals_text,
                "risk_level": risk_level,
                "operation_suggestion": operation_suggestion,
                "dividend_yield": dividend_yield,
                "cape": cape,
                "is_recommended": rec_rating in ("强烈推荐", "推荐"),
                "recommendation_reason": self._get_recommendation_reason(
                    tech_analysis, bull_bear_analysis, rec_rating, elliott_analysis
                ),
                "buy_point": buy_sell["buy_point"],
                "buy_reason": buy_sell["buy_reason"],
                "sell_point": buy_sell["sell_point"],
                "sell_reason": buy_sell["sell_reason"],
            }
            recommendations.append(recommendation)

        # Sort: by rating group (推荐→不推荐), then by combined_score descending
        rating_sort_order = {"强烈推荐": 0, "推荐": 1, "中性": 2, "不推荐": 3, "强烈不推荐": 4}
        recommendations.sort(
            key=lambda x: (rating_sort_order.get(x.get("rating", "中性"), 5), -x["combined_score"]),
        )

        top_count = 10
        top_recommendations = recommendations[:top_count]

        print(f"\n综合评分完成，推荐前 {len(top_recommendations)} 只股票（共 {len(recommendations)} 只评分）：")
        for i, rec in enumerate(top_recommendations, 1):
            chan_str = f", 缠论: {rec.get('chan_signals', '—')}"
            bb_str = f", 牛熊评分: {rec.get('bull_bear_score', 0)}"
            print(
                f"  {i}. {rec['stock_name']} ({rec['stock_code']}) - "
                f"综合: {rec['combined_score']}, 技术: {rec['tech_score']}{bb_str}{chan_str}, "
                f"评级: {rec['rating']}"
                + (" ★双重看多" if rec["both_positive"] else "")
            )

        return recommendations

    def _generate_technical_interpretation(
        self,
        tech_score: float,
        elliott_score: float,
        chan_score: float,
        tech_analysis: Dict[str, Any],
        elliott_analysis: Optional[Dict[str, Any]] = None,
        chan_analysis: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """生成技术分析详细解读

        返回格式：
        {
            "short_term_timing": "短期时机评分 X.X：解读内容",
            "medium_term_trend": "中期趋势评分 X.X：解读内容",
            "micro_trading_points": "微观买卖点评分 X.X：解读内容",
            "overall_interpretation": "整体解读：综合分析内容"
        }
        """
        interpretations = {}

        # 1. 短期时机评分解读（原技术评分）
        tech_situation = tech_analysis.get("situation", {})
        tech_type = tech_situation.get("type", "")
        tech_description = tech_situation.get("description", "")

        tech_interpretations = {
            "情况4": "日线级别股价强势，量能萎缩，筹码锁定良好，适合长线持有",
            "情况3": "日线级别股价强势且量能放大，波段机会明显",
            "情况2": "日线级别股价突破且量价齐升，短线动能较强",
            "情况1": "日线级别股价弱势且量能不足，短期缺乏机会",
        }

        short_term_text = tech_interpretations.get(tech_type, tech_description)
        interpretations["short_term_timing"] = f"短期时机评分 {tech_score:.1f}：{short_term_text}"

        # 2. 中期趋势评分解读（原波浪评分）
        if elliott_analysis and isinstance(elliott_analysis, dict):
            wave_position = elliott_analysis.get("wave_position", "")
            wave_trend = elliott_analysis.get("trend", "")
            wave_resonance = elliott_analysis.get("resonance", "")

            trend_interpretations = {
                "主升浪": "处于主升浪阶段，中期上涨趋势明确",
                "ABC调整反弹": "处于ABC调整反弹阶段，中期趋势不明",
                "调整浪": "处于调整浪阶段，中期偏弱",
                "分析失败": "波浪分析失败，无法判断趋势",
                "数据不足": "数据不足，无法进行波浪分析"
            }

            trend_text = trend_interpretations.get(wave_position, f"波浪位置：{wave_position}")
            if wave_trend:
                trend_text += f"，趋势：{wave_trend}"
            if wave_resonance and wave_resonance != "无共振":
                trend_text += f"，共振：{wave_resonance}"

            interpretations["medium_term_trend"] = f"中期趋势评分 {elliott_score:.1f}：{trend_text}"
        else:
            interpretations["medium_term_trend"] = f"中期趋势评分 {elliott_score:.1f}：无波浪分析数据"

        # 3. 微观买卖点评分解读（原缠论评分）
        if chan_analysis and isinstance(chan_analysis, dict):
            chan_buy_points = chan_analysis.get("buy_points", [])
            chan_sell_points = chan_analysis.get("sell_points", [])
            chan_divergence = chan_analysis.get("divergence", [])

            if chan_buy_points:
                point_text = f"检测到{len(chan_buy_points)}个买点"
                if chan_divergence:
                    point_text += f"，有背驰信号"
                micro_text = f"30分钟级别{point_text}，微观结构偏向买方"
            elif chan_sell_points:
                point_text = f"检测到{len(chan_sell_points)}个卖点"
                micro_text = f"30分钟级别{point_text}，微观结构偏向卖方"
            else:
                micro_text = "30分钟级别无明显买卖点，微观结构中性"

            interpretations["micro_trading_points"] = f"微观买卖点评分 {chan_score:.1f}：{micro_text}"
        else:
            interpretations["micro_trading_points"] = f"微观买卖点评分 {chan_score:.1f}：无缠论分析数据"

        # 4. 整体解读
        overall_parts = []

        # 短期判断
        if tech_score >= 5:
            overall_parts.append("短期技术面强势")
        elif tech_score >= 2:
            overall_parts.append("短期技术面中性偏好")
        elif tech_score >= 0:
            overall_parts.append("短期技术面中性")
        else:
            overall_parts.append("短期技术面偏弱")

        # 中期判断
        if elliott_score >= 5:
            overall_parts.append("中期趋势向上")
        elif elliott_score >= 0:
            overall_parts.append("中期处于震荡整理")
        else:
            overall_parts.append("中期趋势偏弱")

        # 微观判断
        if chan_score >= 5:
            overall_parts.append("微观层面有明确买点")
        elif chan_score >= 2:
            overall_parts.append("微观层面有支撑信号")
        elif chan_score >= 0:
            overall_parts.append("微观层面结构中性")
        else:
            overall_parts.append("微观层面偏向卖方")

        # 综合判断
        if tech_score >= 5 and elliott_score >= 0:
            overall_parts.append("技术面整体向好")
        elif tech_score <= 2 and elliott_score <= -3:
            overall_parts.append("技术面整体偏弱")
        else:
            overall_parts.append("技术面多空交织")

        # 特殊情况
        if tech_score >= 5 and elliott_score < 0:
            overall_parts.append("短期强势可能与中期背离，注意风险")
        elif tech_score < 2 and elliott_score >= 5:
            overall_parts.append("短期偏弱但中期向好，可能是布局机会")

        interpretations["overall_interpretation"] = "解读：" + "；".join(overall_parts) + "。"

        return interpretations

    def _get_recommendation_reason(
        self,
        tech_analysis: Dict[str, Any],
        bull_bear_analysis: Dict[str, Any],
        rec_rating: str,
        elliott_analysis: Optional[Dict[str, Any]] = None,
    ) -> str:
        situation = tech_analysis.get("situation", {})
        situation_type = situation.get("type", "")
        description = situation.get("description", "")

        reason_map = {
            "情况4": "长线关注：股价强势且量能萎缩，筹码锁定良好",
            "情况3": "波段关注：股价强势且量能放大，波段机会明显",
            "情况2": "短线关注：股价突破且量价齐升，短线动能较强",
            "情况1": "不推荐：股价弱势且量能不足",
        }

        tech_reason = reason_map.get(situation_type, description)

        bb_reason = ""
        if bull_bear_analysis and "error" not in bull_bear_analysis:
            rating = bull_bear_analysis.get("investment_rating", "")
            confidence = bull_bear_analysis.get("confidence_level", "")
            agreements = bull_bear_analysis.get("key_agreements", [])
            if rating:
                bb_reason = f"；牛熊辩论评级: {rating}"
                if confidence:
                    bb_reason += f"（信心: {confidence}）"
                if agreements:
                    bb_reason += f"，共识: {', '.join(agreements[:2])}"

        wave_reason = ""
        if elliott_analysis and isinstance(elliott_analysis, dict) and "error" not in elliott_analysis:
            wave_pos = elliott_analysis.get("wave_position", "")
            if wave_pos and wave_pos not in ("分析失败", "数据不足"):
                wave_reason = f"；波浪位置: {wave_pos}"

        return tech_reason + bb_reason + wave_reason

    def _generate_buy_sell_advice(
        self,
        tech_analysis: Dict[str, Any],
        elliott_analysis: Optional[Dict[str, Any]],
        rating: str,
        combined_score: float,
        is_etf: bool = False,
    ) -> Dict[str, Any]:
        """
        基于技术指标和波浪分析生成买入/卖出点建议

        Returns:
            {
                "buy_point": float or None,  # 买入点价格
                "buy_reason": str,            # 买入理由
                "sell_point": float or None,  # 卖出点价格
                "sell_reason": str,           # 卖出理由
            }
        """
        result = {"buy_point": None, "buy_reason": "", "sell_point": None, "sell_reason": ""}

        # --- Extract available data ---
        data_summary = tech_analysis.get("data_summary", {})
        close = data_summary.get("close", 0)
        ma25 = data_summary.get("ma25", 0)
        situation = tech_analysis.get("situation", {})
        situation_type = situation.get("type", "")

        # Elliott indicators
        indicators = {}
        wave_pos = ""
        upside_prob = 50
        high_60 = 0
        low_60 = 0
        if elliott_analysis and isinstance(elliott_analysis, dict) and "error" not in elliott_analysis:
            indicators = elliott_analysis.get("indicators", {})
            wave_pos = elliott_analysis.get("wave_position", "")
            upside_prob = elliott_analysis.get("upside_probability", 50)
            high_60 = elliott_analysis.get("high_60", 0)
            low_60 = elliott_analysis.get("low_60", 0)

        ma20 = indicators.get("ma20", 0)
        ma60 = indicators.get("ma60", 0)
        rsi = indicators.get("rsi", 50)
        macd_hist = indicators.get("macd_hist", 0)

        if not close or close <= 0:
            return result

        # --- Determine support levels (for buy points) ---
        support_levels = []
        if ma25 and ma25 > 0 and ma25 < close:
            support_levels.append(("MA25", ma25))
        if ma20 and ma20 > 0 and ma20 < close:
            support_levels.append(("MA20", ma20))
        if ma60 and ma60 > 0 and ma60 < close:
            support_levels.append(("MA60", ma60))
        if low_60 and low_60 > 0 and low_60 < close:
            support_levels.append(("60日低点", low_60))

        # --- Determine resistance levels (for sell points) ---
        resistance_levels = []
        if high_60 and high_60 > 0 and high_60 > close:
            resistance_levels.append(("60日高点", high_60))
        if ma25 and ma25 > 0 and ma25 > close:
            resistance_levels.append(("MA25", ma25))
        if ma20 and ma20 > 0 and ma20 > close:
            resistance_levels.append(("MA20", ma20))
        if ma60 and ma60 > 0 and ma60 > close:
            resistance_levels.append(("MA60", ma60))

        # --- Buy point logic ---
        is_bullish = rating in ("推荐", "强烈推荐") or combined_score >= 3
        is_neutral = rating == "中性" or (0 <= combined_score < 3)
        is_bearish = rating in ("不推荐", "强烈不推荐") or combined_score < 0

        # Wave-based boost
        wave_bullish = any(k in wave_pos for k in ("第1浪", "第3浪", "调整浪末端", "反转"))
        wave_caution = any(k in wave_pos for k in ("第5浪", "超跌反弹"))

        buy_reasons = []
        sell_reasons = []

        if is_bullish or (is_neutral and wave_bullish):
            # Has buy point
            if support_levels:
                # Pick nearest support as primary buy point
                nearest_support = min(support_levels, key=lambda x: abs(x[1] - close))
                result["buy_point"] = round(nearest_support[1], 3)
                buy_reasons.append(f"回踩{nearest_support[0]}({nearest_support[1]:.3f})获支撑")

                # If multiple supports, mention them
                if len(support_levels) > 1:
                    second_support = [s for s in support_levels if s[0] != nearest_support[0]]
                    if second_support:
                        second = min(second_support, key=lambda x: abs(x[1] - close))
                        buy_reasons.append(f"下方较强支撑{second[0]}({second[1]:.3f})")
            else:
                # No support below - stock is at lows, potential bottom
                result["buy_point"] = round(close * 0.97, 3)  # ~3% below current
                buy_reasons.append("当前价位附近可分批建仓")

            # Add contextual reasons
            if wave_bullish:
                buy_reasons.append(f"波浪位于{wave_pos}，上涨概率{upside_prob}%")
            if situation_type == "情况3":
                buy_reasons.append("量价齐升，波段机会")
            elif situation_type == "情况4":
                buy_reasons.append("强势缩量，筹码锁定")
            elif situation_type == "情况2":
                buy_reasons.append("突破放量，短线动能")
            if rsi < 30:
                buy_reasons.append(f"RSI={rsi:.0f}超卖")
            elif rsi < 40:
                buy_reasons.append(f"RSI={rsi:.0f}偏低")

            # Sell point for bullish stocks (take profit)
            if resistance_levels:
                nearest_resist = min(resistance_levels, key=lambda x: abs(x[1] - close))
                result["sell_point"] = round(nearest_resist[1], 3)
                sell_reasons.append(f"接近{nearest_resist[0]}({nearest_resist[1]:.3f})压力位可减仓")
            elif high_60 and high_60 > close:
                result["sell_point"] = round(high_60, 3)
                sell_reasons.append(f"突破60日高点({high_60:.3f})后可考虑止盈")

            if wave_caution:
                sell_reasons.append(f"波浪位于{wave_pos}，需警惕趋势反转")
            if rsi > 70:
                sell_reasons.append(f"RSI={rsi:.0f}超买，注意回调风险")

        elif is_neutral:
            # Neutral - both buy and sell points with caution
            if support_levels:
                nearest_support = min(support_levels, key=lambda x: abs(x[1] - close))
                result["buy_point"] = round(nearest_support[1], 3)
                buy_reasons.append(f"回踩{nearest_support[0]}({nearest_support[1]:.3f})可轻仓试探")
            else:
                result["buy_point"] = round(close * 0.95, 3)
                buy_reasons.append("等待更明确支撑信号再介入")

            if resistance_levels:
                nearest_resist = min(resistance_levels, key=lambda x: abs(x[1] - close))
                result["sell_point"] = round(nearest_resist[1], 3)
                sell_reasons.append(f"反弹至{nearest_resist[0]}({nearest_resist[1]:.3f})可减仓")
            else:
                result["sell_point"] = round(close * 1.05, 3)
                sell_reasons.append("反弹5%左右可考虑减仓")

            buy_reasons.append("中性评级，控制仓位")
            if wave_pos:
                buy_reasons.append(f"波浪位置: {wave_pos}")

        else:
            # Bearish - mainly sell point
            if resistance_levels:
                nearest_resist = min(resistance_levels, key=lambda x: abs(x[1] - close))
                result["sell_point"] = round(nearest_resist[1], 3)
                sell_reasons.append(f"反弹至{nearest_resist[0]}({nearest_resist[1]:.3f})建议减仓离场")
            else:
                result["sell_point"] = round(close, 3)
                sell_reasons.append("弱势格局，建议逢高减仓")

            sell_reasons.append("综合评分偏空，不建议追涨")
            if wave_caution or "调整浪" in wave_pos:
                sell_reasons.append(f"波浪位于{wave_pos}，下行风险较大")
            if rsi < 30:
                # Even bearish stocks can be oversold
                result["buy_point"] = round(low_60 if low_60 and low_60 > 0 else close * 0.95, 3)
                buy_reasons.append(f"RSI={rsi:.0f}极度超卖，仅适合短线反弹博弈")
            elif situation_type == "情况1":
                sell_reasons.append("技术面弱势，量能不足")

        result["buy_reason"] = "；".join(buy_reasons) if buy_reasons else "暂无明确买入信号"
        result["sell_reason"] = "；".join(sell_reasons) if sell_reasons else "暂无明确卖出信号"

        return result

    # ================================================================
    # Step 6: 每日生成文档
    # ================================================================

    def _generate_daily_report(
        self,
        selection_date: str,
        favorable_industries: List[Dict[str, Any]],
        stock_pool: List[Dict[str, Any]],
        analyzed_stocks: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        top_picks = [r for r in recommendations if r["rating"] in ("强烈推荐", "推荐")]

        report = {
            "selection_date": selection_date,
            "generation_time": datetime.now().isoformat(),
            "favorable_industries": favorable_industries,
            "industry_leaders": [
                {"stock_name": s.get("stock_name", ""), "stock_code": s["stock_code"], "industry": s.get("industry", "")}
                for s in stock_pool
            ],
            "stock_pool": stock_pool,
            "stock_pool_size": len(stock_pool),
            "analyzed_stocks": [
                {"stock_name": s.get("stock_name", ""), "stock_code": s["stock_code"]}
                for s in analyzed_stocks
            ],
            "analyzed_stocks_count": len(analyzed_stocks),
            "recommendations": recommendations,
            "top_picks": [
                {
                    "stock_name": r["stock_name"],
                    "stock_code": r["stock_code"],
                    "industry": r.get("industry", ""),
                    "combined_score": r["combined_score"],
                    "tech_score": r["tech_score"],
                    "bull_bear_score": r["bull_bear_score"],
                    "elliott_score": r.get("elliott_score", 0),
                    "chan_score": r.get("chan_score", 0),
                    "chan_signals": r.get("chan_signals", "—"),
                    "rating": r["rating"],
                    "both_positive": r["both_positive"],
                    "bull_bear_missing": r.get("bull_bear_missing", False),
                    "has_elliott": r.get("has_elliott", False),
                    "has_chan": r.get("has_chan", False),
                    "risk_level": r.get("risk_level", "中"),
                    "operation_suggestion": r.get("operation_suggestion", "观望"),
                    "dividend_yield": r.get("dividend_yield"),
                    "cape": r.get("cape"),
                    "recommendation_reason": r["recommendation_reason"],
                }
                for r in top_picks
            ],
            "summary": {
                "total_industries": len(favorable_industries),
                "total_analyzed": len(analyzed_stocks),
                "total_recommended": len(top_picks),
                "avg_score": (
                    sum(r["combined_score"] for r in recommendations) / len(recommendations)
                    if recommendations
                    else 0
                ),
            },
        }

        # Save JSON
        json_filename = f"每日选股_{selection_date}.json"
        json_path = self.daily_selection_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"JSON报告已保存: {json_path}")

        return report

    # ================================================================
    # Stock Pool File (自选股票池.md)
    # ================================================================

    def _init_stock_pool_file(self) -> None:
        """Create the stock pool file with DEFAULT_STOCKS if it doesn't exist."""
        lines = [
            "# 自选股票池",
            "#",
            "# 格式：行业名称: 股票代码1, 股票代码2, ...",
            "#",
            "# 说明：",
            "# - 此文件由 DailyStockSelectionAgent 自动生成并维护",
            "# - 你也可以手动编辑此文件来添加/删除股票",
            "# - Agent 运行时会读取此文件，新发现的股票会自动追加到对应行业下",
            "# - 股票代码格式：A股 6位数字.SH/.SZ，港股 4位数字.HK",
            "# - 以 # 开头的行为注释，会被忽略",
            "# - Agent 不会删除你手动添加的股票，只会追加新股票",
            "#",
            "",
        ]
        for industry, codes in DEFAULT_STOCKS.items():
            lines.append(f"{industry}: {', '.join(codes)}")
        lines.append("")
        self.stock_pool_file.write_text("\n".join(lines), encoding="utf-8")
        print(f"自选股票池文件已创建: {self.stock_pool_file}")

    def _read_stock_pool_file(self) -> Dict[str, List[Dict[str, str]]]:
        """Read the stock pool file and return {industry: [{"code": "600519.SH", "name": "贵州茅台"}, ...]}.
        
        Supports two formats:
        1. 行业: 代码(名称), 代码(名称), ...
        2. Markdown table: | 名称 | 代码 |  (categorized by preceding section headers)
        """
        pool = {}
        if not self.stock_pool_file.exists():
            return pool
        try:
            # 股票池是报告的核心数据源：OneDrive 同步窗口可能持续数分钟，
            # 这里用更长退避窗口（约8.5分钟）确保能跨过同步锁，避免整份报告个股数据为空。
            content = read_text_with_retry(self.stock_pool_file, max_attempts=10, base_delay=1.0)
            lines = content.splitlines()
            current_table_section = ""  # Track which table section we're in
            
            for line_text in lines:
                line_text = line_text.strip()
                if not line_text or line_text.startswith("#"):
                    continue
                
                # Detect table section headers (e.g., "名称 | 代码" repeated before each table)
                if line_text.startswith("|") and "名称" in line_text and "代码" in line_text:
                    # Next section starts - determine category from context
                    continue
                
                # Skip table separator lines
                if line_text.startswith("|") and ":---" in line_text:
                    continue
                
                # Parse table rows: | name | code |
                if line_text.startswith("|"):
                    parts = [p.strip() for p in line_text.split("|")]
                    parts = [p for p in parts if p]  # Remove empty strings
                    if len(parts) >= 2:
                        name = parts[0]
                        code = parts[1]
                        if name and code and name != "名称" and code != "代码":
                            # Determine industry from code format
                            industry = self._classify_stock_by_code(code, name)
                            full_code = self._normalize_stock_code(code)
                            if industry not in pool:
                                pool[industry] = []
                            # Check if already exists
                            existing_codes = [e["code"] for e in pool[industry]]
                            if full_code not in existing_codes:
                                pool[industry].append({"code": full_code, "name": name})
                    continue
                
                # Parse "名称 代码" or pure name lines (e.g., "隧道股份" or "自由现金流etf 159201")
                # Skip lines that look like section headers or comments
                if line_text.startswith("---") or line_text.startswith(">"):
                    continue
                
                # Try "name code" format (e.g., "自由现金流etf 159201")
                m = re.match(r'^(.+?)\s+(\d{5,6})$', line_text)
                if m:
                    name = m.group(1).strip()
                    code = m.group(2)
                    industry = self._classify_stock_by_code(code, name)
                    full_code = self._normalize_stock_code(code)
                    if industry not in pool:
                        pool[industry] = []
                    existing_codes = [e["code"] for e in pool[industry]]
                    if full_code not in existing_codes:
                        pool[industry].append({"code": full_code, "name": name})
                    continue
                
                # Try pure name format (e.g., "隧道股份", "波司登") — resolve code via API
                if re.match(r'^[\u4e00-\u9fff]', line_text) and len(line_text) >= 2 and ':' not in line_text:
                    name = line_text
                    # Check if already in pool by name
                    all_names = [e["name"] for entries in pool.values() for e in entries]
                    if name in all_names:
                        continue
                    # Resolve stock code via suggest API
                    code = self._resolve_stock_code_by_name(name)
                    if code:
                        industry = self._classify_stock_by_code(code, name)
                        if industry not in pool:
                            pool[industry] = []
                        existing_codes = [e["code"] for e in pool[industry]]
                        if code not in existing_codes:
                            pool[industry].append({"code": code, "name": name})
                    continue
                
                # Parse bare "CODE(NAME)" or "CODE" lines (no industry prefix)
                bare_code_match = re.match(r'^(\d{4,6}\.(?:SH|SZ|HK))\s*(?:\((.+?)\))?$', line_text)
                if bare_code_match:
                    code = self._normalize_stock_code(bare_code_match.group(1))
                    name = bare_code_match.group(2) or ""
                    industry = self._classify_stock_by_code(code, name)
                    if industry not in pool:
                        pool[industry] = []
                    existing_codes = [e["code"] for e in pool[industry]]
                    if code not in existing_codes:
                        pool[industry].append({"code": code, "name": name})
                    continue

                # Parse "行业: 代码(名称), ..." format
                if ":" not in line_text:
                    continue
                industry, codes_str = line_text.split(":", 1)
                industry = industry.strip()
                if not industry:
                    continue
                entries = []
                for token in codes_str.split(","):
                    token = token.strip()
                    if not token:
                        continue
                    # Parse "600519.SH(贵州茅台)" or "600519.SH"
                    m = re.match(r'^(\S+?)\((.+?)\)$', token)
                    if m:
                        code = m.group(1)
                        name = m.group(2)
                        # Normalize ETF codes
                        code = self._normalize_stock_code(code)
                        entries.append({"code": code, "name": name})
                    else:
                        code = self._normalize_stock_code(token)
                        entries.append({"code": code, "name": ""})
                if industry and entries:
                    if industry in pool:
                        # Merge with existing
                        existing_codes = [e["code"] for e in pool[industry]]
                        for entry in entries:
                            if entry["code"] not in existing_codes:
                                pool[industry].append(entry)
                                existing_codes.append(entry["code"])
                    else:
                        pool[industry] = entries
        except Exception as e:
            print(f"读取自选股票池文件失败: {e}")
        return pool

    def _normalize_stock_code(self, code: str) -> str:
        """Normalize a stock code by adding the correct market suffix if missing."""
        # Remove trailing non-numeric chars like 'T' (e.g., "600872T" -> "600872")
        # but preserve .HK/.SH/.SZ suffixes
        if "." in code:
            base, suffix = code.rsplit(".", 1)
            # Clean base: remove trailing letters
            base = re.sub(r'[A-Za-z]+$', '', base)
            return f"{base}.{suffix}" if base else code
        # Bare 6-digit code - infer suffix
        # Remove trailing letters first
        code_clean = re.sub(r'[A-Za-z]+$', '', code)
        if len(code_clean) == 6:
            if code_clean.startswith("6") or code_clean.startswith("5") or code_clean.startswith("56") or code_clean.startswith("58"):
                return f"{code_clean}.SH"
            elif code_clean.startswith("0") or code_clean.startswith("3") or code_clean.startswith("15"):
                return f"{code_clean}.SZ"
            elif code_clean.startswith("4") or code_clean.startswith("8"):
                return f"{code_clean}.BJ"
            else:
                return f"{code_clean}.SH"
        # Bare 5-digit or 4-digit code - likely HK
        if code_clean.isdigit() and len(code_clean) <= 5:
            return f"{code_clean.zfill(5)}.HK"
        return code

    def _resolve_stock_code_by_name(self, name: str) -> Optional[str]:
        """Resolve a stock/ETF name to its code using tencent/sina suggest APIs.
        
        Priority: A-share > HK > skip US/bonds/indices.
        """
        import requests as req
        candidates = []
        
        # Try tencent suggest API
        # Format: v_hint="market~code~name~pinyin~type"
        try:
            url = f"https://smartbox.gtimg.cn/s3/?v=2&q={name}&t=all"
            resp = req.get(url, timeout=5)
            if resp.status_code == 200:
                text = resp.text
                for hint in re.findall(r'v_hint="([^"]+)"', text):
                    parts = hint.split("~")
                    if len(parts) >= 5:
                        code_raw = parts[1]
                        stock_type = parts[4] if len(parts) > 4 else ""
                        if stock_type in ("BOND", "IDX", "GP-US"):
                            continue
                        if code_raw and code_raw.isdigit():
                            candidates.append(code_raw)
        except Exception:
            pass
        
        # Try sina suggest API
        try:
            url = f"https://suggest3.sinajs.cn/suggest/type=&key={name}&name=suggestdata"
            resp = req.get(url, timeout=5, headers={"Referer": "https://finance.sina.com.cn"})
            if resp.status_code == 200:
                text = resp.text
                if '="' in text:
                    data = text.split('="')[1].rstrip('";\n')
                    if data:
                        for item in data.split(";"):
                            parts = item.split(",")
                            if len(parts) >= 5:
                                code_raw = parts[3]
                                if code_raw and code_raw.isdigit():
                                    candidates.append(code_raw)
        except Exception:
            pass
        
        if candidates:
            # Prefer A-share (6-digit) over HK (5-digit)
            a_share = [c for c in candidates if len(c) == 6]
            if a_share:
                return self._normalize_stock_code(a_share[0])
            # Then HK
            hk = [c for c in candidates if len(c) <= 5]
            if hk:
                return self._normalize_stock_code(hk[0])
            return self._normalize_stock_code(candidates[0])
        
        return None

    def _classify_stock_by_code(self, code: str, name: str) -> str:
        """Classify a stock into an industry based on code and name."""
        # Normalize code first for reliable classification
        normalized_code = self._normalize_stock_code(code)
        pure_code = normalized_code.split(".")[0]
        
        # ETF detection
        if "ETF" in name:
            return "ETF基金"
        if len(pure_code) == 6 and (pure_code.startswith("5") or pure_code.startswith("15") or pure_code.startswith("16")):
            return "ETF基金"
        
        # Known industry mappings from STOCK_NAMES
        for known_code, known_name in self.STOCK_NAMES.items():
            if known_code == normalized_code or known_code == code:
                # Find industry from DEFAULT_STOCKS
                for ind, codes in DEFAULT_STOCKS.items():
                    if normalized_code in codes or code in codes:
                        return ind
                break
        
        # Heuristic classification
        if normalized_code.endswith(".HK"):
            if "科技" in name or "AI" in name or "阿里" in name or "腾讯" in name or "小米" in name or "比亚迪" in name or "智谱" in name or "MINIMAX" in name:
                return "港股科技"
            if "医药" in name or "生物" in name or "药明" in name or "百济" in name or "制药" in name or "矽智" in name or "晶泰" in name or "英矽" in name:
                return "港股医药"
            if "消费" in name or "海底" in name or "李宁" in name or "泡泡" in name or "玛特" in name:
                return "港股消费"
            if "地产" in name or "置地" in name or "华润" in name:
                return "港股地产"
            if "金" in name or "矿" in name or "资源" in name:
                return "贵金属（黄金/铜）"
            if "风" in name or "电" in name or "能" in name:
                return "新能源"
            # AI/tech companies with English names
            if any(c.isalpha() and c.isupper() for c in name):
                return "港股科技"
            return "港股其他"
        
        # A-share heuristics
        name_industry_map = {
            "银行": "金融", "证券": "金融", "保险": "金融", "金融": "金融",
            "医药": "医药生物", "生物": "医药生物", "健康": "医药生物", "奥泰": "医药生物",
            "半导体": "半导体", "芯片": "半导体", "微电": "半导体", "集电": "半导体",
            "存储": "半导体", "澜起": "半导体", "波龙": "半导体",
            "新能源": "新能源", "光伏": "新能源", "风电": "新能源", "锂电": "新能源", "储能": "新能源",
            "英维克": "新能源", "高澜": "新能源",
            "白酒": "白酒与高端消费品", "茅台": "白酒与高端消费品", "五粮液": "白酒与高端消费品",
            "地产": "地产基建", "建筑": "地产基建", "基建": "地产基建", "平潭": "地产基建",
            "汽车": "汽车",
            "食品": "食品饮料", "饮料": "食品饮料", "乳": "食品饮料", "味业": "食品饮料", "调味": "食品饮料",
            "中炬": "食品饮料", "伊利": "食品饮料",
            "家电": "家电", "冰箱": "家电", "空调": "家电", "洗衣机": "家电",
            "通信": "通信", "电信": "通信", "联通": "通信", "卫星": "通信",
            "石油": "能源", "煤炭": "能源", "神华": "高股息公用事业",
            "电力": "高股息公用事业", "水电": "高股息公用事业",
            "黄金": "贵金属（黄金/铜）", "铜": "材料", "有色": "材料", "水泥": "材料",
            "化工": "化工", "化学": "化工",
            "AI": "科技（AI与数字经济）", "科技": "科技（AI与数字经济）", 
            "信息": "科技（AI与数字经济）", "数字": "科技（AI与数字经济）",
            "工业富联": "科技（AI与数字经济）", "浪潮": "科技（AI与数字经济）",
            "电子": "消费电子", "精密": "消费电子", "沪电": "消费电子",
            "安防": "安防与智能视觉", "海康": "安防与智能视觉",
            "机场": "交通运输", "港口": "交通运输", "航运": "交通运输", "海控": "交通运输",
            "旅游": "消费旅游", "中免": "消费旅游",
        }
        for keyword, industry in name_industry_map.items():
            if keyword in name:
                return industry
        
        return "其他"

    def _format_stock_entry(self, code: str, name: str = "") -> str:
        """Format a stock entry as 'code(name)' or 'code'."""
        if name:
            return f"{code}({name})"
        # Try to look up name from STOCK_NAMES or cache
        resolved = self._get_stock_name(code)
        if resolved and resolved != code:
            return f"{code}({resolved})"
        return code

    def _write_stock_pool_file(self, pool: Dict[str, List[Dict[str, str]]]) -> None:
        """Write the stock pool dict back to file, preserving comments and format."""
        # Read existing file to preserve comments
        existing_lines = []
        if self.stock_pool_file.exists():
            existing_lines = read_text_with_retry(self.stock_pool_file).splitlines()

        # Build output: preserve comment lines, replace data lines
        written_industries = set()
        output_lines = []

        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                output_lines.append(line)
                continue
            if ":" not in stripped:
                output_lines.append(line)
                continue
            industry = stripped.split(":", 1)[0].strip()
            if industry in pool:
                entries = [self._format_stock_entry(e["code"], e["name"]) for e in pool[industry]]
                output_lines.append(f"{industry}: {', '.join(entries)}")
                written_industries.add(industry)
            else:
                # User-added industry - keep as-is
                output_lines.append(line)

        # Append new industries not yet in file
        for industry, entries in pool.items():
            if industry not in written_industries:
                formatted = [self._format_stock_entry(e["code"], e["name"]) for e in entries]
                output_lines.append(f"{industry}: {', '.join(formatted)}")

        # Ensure trailing newline
        if output_lines and not output_lines[-1] == "":
            output_lines.append("")

        self.stock_pool_file.write_text("\n".join(output_lines), encoding="utf-8")

    def _sync_stock_pool_file(self, analyzed_stocks: List[Dict[str, Any]]) -> None:
        """Sync new stocks discovered by the agent back to the stock pool file.
        Only appends new stocks, never removes user-added stocks."""
        pool = self._read_stock_pool_file()

        # Build a lookup: code -> entry for quick dedup
        def _codes_in_pool(industry_entries):
            return {e["code"] for e in industry_entries}

        # Merge DEFAULT_STOCKS as base
        for industry, codes in DEFAULT_STOCKS.items():
            if industry not in pool:
                pool[industry] = []
            existing = _codes_in_pool(pool[industry])
            for code in codes:
                if code not in existing:
                    pool[industry].append({"code": code, "name": ""})
                    existing.add(code)

        # Add any stocks from analysis that aren't yet in the pool
        changed = False
        for stock in analyzed_stocks:
            code = stock.get("stock_code", "")
            industry = stock.get("industry", "")
            name = stock.get("stock_name", "")
            if not code or not industry:
                continue
            if industry not in pool:
                pool[industry] = []
                changed = True
            existing = _codes_in_pool(pool[industry])
            if code not in existing:
                pool[industry].append({"code": code, "name": name})
                changed = True

        if changed:
            self._write_stock_pool_file(pool)
            print(f"自选股票池已更新: {self.stock_pool_file}")

    # Stock name cache: code -> name
    _stock_name_cache: Dict[str, str] = {}

    # Known stock names (fallback when API fails)
    STOCK_NAMES = {
        "600519.SH": "贵州茅台", "002230.SZ": "科大讯飞", "300059.SZ": "东方财富",
        "688981.SH": "中芯国际", "002371.SZ": "北方华创", "688012.SH": "中微公司",
        "300750.SZ": "宁德时代", "002594.SZ": "比亚迪", "601012.SH": "隆基绿能",
        "300274.SZ": "阳光电源", "603259.SH": "药明康德", "600276.SH": "恒瑞医药",
        "300760.SZ": "迈瑞医疗", "601899.SH": "紫金矿业", "600547.SH": "山东黄金",
        "600900.SH": "长江电力", "601088.SH": "中国神华", "002475.SZ": "立讯精密",
        "002241.SZ": "歌尔股份", "600030.SH": "中信证券", "601318.SH": "中国平安",
        "600036.SH": "招商银行", "002142.SZ": "宁波银行", "601633.SH": "长城汽车",
        "600048.SH": "保利发展", "601668.SH": "中国建筑",
        "000858.SZ": "五粮液", "601888.SH": "中国中免", "603288.SH": "海天味业",
        "000333.SZ": "美的集团", "600887.SH": "伊利股份", "002415.SZ": "海康威视",
        "601919.SH": "中远海控", "300782.SZ": "卓胜微", "600584.SH": "长电科技",
        "600460.SH": "士兰微", "002049.SZ": "紫光国微", "600667.SH": "太极实业",
        "002156.SZ": "通富微电", "603986.SH": "兆易创新", "000001.SZ": "平安银行",
        "601939.SH": "建设银行", "601988.SH": "中国银行", "601998.SH": "中信银行",
        "601390.SH": "中国中铁", "600309.SH": "万华化学", "601728.SH": "中国电信",
        "601857.SH": "中国石油", "600690.SH": "海尔智家",
        # User-added from table
        "000592.SZ": "平潭发展", "000630.SZ": "铜陵有色", "002463.SZ": "沪电股份",
        "002837.SZ": "英维克", "002880.SZ": "卫光生物", "688177.SH": "百奥泰",
        "600118.SH": "中国卫星", "600585.SH": "海螺水泥", "600872.SH": "中炬高新",
        "688008.SH": "澜起科技", "301308.SZ": "江波龙", "000977.SZ": "浪潮信息",
        "300499.SZ": "高澜股份", "601138.SH": "工业富联", "600009.SH": "上海机场",
        "600050.SH": "中国联通",
        # HK stocks
        "09988.HK": "阿里巴巴", "0700.HK": "腾讯控股", "3690.HK": "美团",
        "01810.HK": "小米集团", "2269.HK": "药明生物", "6160.HK": "百济神州",
        "6862.HK": "海底捞", "2331.HK": "李宁", "300033.SZ": "同花顺",
        "00100.HK": "MINIMAX-W", "01109.HK": "华润置地", "01211.HK": "比亚迪股份",
        "02196.HK": "复星医药", "02208.HK": "金风科技", "02228.HK": "晶泰控股",
        "02359.HK": "药明康德", "02513.HK": "智谱", "02899.HK": "紫金矿业",
        # ETF
        "159326.SZ": "电网设备ETF华夏", "159559.SZ": "机器人ETF景顺",
        "159566.SZ": "储能电池ETF易方达", "513300.SH": "纳斯达克ETF华夏",
        "513380.SH": "恒生科技ETF广发", "513950.SH": "恒生红利ETF富国",
        "515080.SH": "中证红利ETF招商", "515850.SH": "证券ETF富国",
        "562550.SH": "绿电ETF华夏", "588080.SH": "科创50ETF易方达",
    }

    def _get_stock_name(self, stock_code: str) -> str:
        """Get real stock name from cache, local dict, or API."""
        # Check cache first
        if stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]

        # Check local dict
        if stock_code in self.STOCK_NAMES:
            return self.STOCK_NAMES[stock_code]

        # Try Sina API
        name = self._fetch_stock_name_from_sina(stock_code)
        if name:
            self._stock_name_cache[stock_code] = name
            return name

        # Fallback: return the code itself
        return stock_code

    def _fetch_stock_name_from_sina(self, stock_code: str) -> Optional[str]:
        """Fetch stock name from Sina Finance API."""
        try:
            pure_code = stock_code.split(".")[0]
            if stock_code.endswith(".HK"):
                prefix = "hk"
            elif pure_code.startswith("6"):
                prefix = "sh"
            elif pure_code.startswith("0") or pure_code.startswith("3"):
                prefix = "sz"
            else:
                prefix = "sh"

            url = f"https://hq.sinajs.cn/list={prefix}{pure_code}"
            resp = requests.get(url, timeout=5, headers={"Referer": "https://finance.sina.com.cn"})
            match = re.search(r'="([^,]+)', resp.text)
            if match:
                name = match.group(1)
                if name and name != "":
                    return name
        except Exception:
            pass
        return None

    def _resolve_stock_names(self, stock_list: List[Dict[str, Any]]) -> None:
        """Replace placeholder stock names with real names in-place."""
        for stock in stock_list:
            current_name = stock.get("stock_name", "")
            if "代表股" in current_name or current_name == "" or current_name.startswith("自选股") or current_name.startswith("雪球提及"):
                real_name = self._get_stock_name(stock["stock_code"])
                if real_name and real_name != stock["stock_code"]:
                    stock["stock_name"] = real_name

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                return {"raw_response": response}
        except json.JSONDecodeError:
            return {"raw_response": response}

    # ================================================================
    # 三维评分融合方法
    # ================================================================

    def _fuse_dimension_scores(
        self, dimension_comprehensive: Dict, llm_dimension_scores: Dict
    ) -> Dict[str, Any]:
        """融合量化评分和LLM定性评分

        融合策略：60%量化 + 40%LLM定性
        子维度评分：优先使用量化引擎的子维度评分（可追溯、可验证）
        """
        fused = {}

        for dim_name in ["company_quality", "trend", "valuation"]:
            quant_dim = dimension_comprehensive.get(dim_name, {})
            quant_score = quant_dim.get("score", 0) if isinstance(quant_dim, dict) else 0
            llm_score = llm_dimension_scores.get(dim_name, {}).get("score", 0)

            # 加权融合
            fused_score = quant_score * 0.6 + llm_score * 0.4

            # 从量化引擎提取子维度评分（遍历所有子维度dict）
            sub_scores = {}
            if isinstance(quant_dim, dict):
                for key, value in quant_dim.items():
                    if isinstance(value, dict) and "score" in value:
                        sub_scores[key] = value["score"]

            # 保留量化评分的详细信息
            fused[dim_name] = {
                "score": round(fused_score, 1),
                "quant_score": quant_score,
                "llm_score": llm_score,
                "reasoning": quant_dim.get("reasoning", "") if isinstance(quant_dim, dict) else "",
                "sub_scores": sub_scores
            }

            # 如果是好公司维度，基于实际子维度评分重新计算时间的朋友
            if dim_name == "company_quality":
                biz = sub_scores.get("business_model", 0)
                cul = sub_scores.get("corporate_culture", 0)
                und = sub_scores.get("understandability", 0)
                # 时间的朋友定义: 商业模式>=5, 企业文化>=4, 可理解性>=5
                fused[dim_name]["is_friend_of_time"] = (
                    biz >= 5 and cul >= 4 and und >= 5
                )

        return fused

    def _compute_dimension_based_bull_bear_score(
        self, dimension_comprehensive: Dict, final_summary: Dict
    ) -> Dict[str, Any]:
        """基于三维评分计算牛熊评分

        替代原有的 RATING_BASE_SCORE × CONFIDENCE_MULTIPLIER 查表逻辑
        直接使用量化引擎计算的三维评分
        """
        bull_bear_score = dimension_comprehensive.get("bull_bear_score", 0)

        # 根据三维评分确定投资评级和信心水平
        score = bull_bear_score

        if score >= 7:
            investment_rating = "强烈买入"
            confidence_level = "高" if score >= 8 else "中"
        elif score >= 3:
            investment_rating = "买入"
            confidence_level = "中"
        elif score >= 0:
            investment_rating = "持有"
            confidence_level = "中"
        elif score >= -5:
            investment_rating = "卖出"
            confidence_level = "中"
        else:
            investment_rating = "强烈卖出"
            confidence_level = "高" if score <= -8 else "中"

        return {
            "bull_bear_score": round(score, 1),
            "investment_rating": investment_rating,
            "confidence_level": confidence_level,
            "dimension_breakdown": {
                "company_quality": dimension_comprehensive.get("company_quality", {}).get("score", 0),
                "trend": dimension_comprehensive.get("trend", {}).get("score", 0),
                "valuation": dimension_comprehensive.get("valuation", {}).get("score", 0),
                "weights_used": dimension_comprehensive.get("weights_used", {}),
                "veto_triggered": dimension_comprehensive.get("veto_triggered", False)
            }
        }


def run_daily_stock_selection(
    api_key: Optional[str] = None,
    industries: Optional[List[str]] = None,
    custom_stocks: Optional[List[str]] = None
):
    agent = DailyStockSelectionAgent(api_key=api_key)
    return agent.run_daily_selection(industries=industries, custom_stocks=custom_stocks)
