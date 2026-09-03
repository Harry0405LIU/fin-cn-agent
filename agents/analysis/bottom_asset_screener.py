#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周金涛底部资产筛选Agent (Bottom Asset Screener)

基于周金涛2019年资产大底假设，筛选相对2019年涨幅最小/价位更低的优质资产。
三重筛选：行业需求未永久萎缩 + 估值历史低位 + 催化因素明确
三重排除：流动性陷阱 + 政策强压 + 技术替代
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import akshare as ak
import pandas as pd
import requests

try:
    from core.llm_client import LLMClient
except ImportError:
    LLMClient = None

from core.io_utils import (
    read_text_with_retry,
    read_json_with_retry,
    write_text_with_retry,
    write_json_with_retry,
)
from config.settings import settings

# ---- 常量定义 ----

BOTTOM_PERIOD = {
    "start": "20181001",
    "end": "20191231",
}

KEY_BOTTOM_DATES = {
    "A股": [
        "2018-10-19",
        "2019-01-04",
        "2019-05-06",
        "2019-08-06",
    ],
    "港股": [
        "2018-10-30",
        "2019-01-03",
        "2019-06-04",
        "2019-08-15",
    ],
}

CANDIDATE_THRESHOLDS = {
    "max_gain_pct": 50,
    "min_gain_pct": -80,
    "a_stock_min_market_cap": 100_0000_0000,
    "hk_stock_min_market_cap": 200_0000_0000,
    "etf_min_scale": 5_0000_0000,
    "max_candidates_per_market": 100,
}

BOTTOM_ASSET_WEIGHTS = {
    "price_gap": 0.15,
    "valuation_safety": 0.25,
    "catalyst": 0.30,
    "industry_momentum": 0.30,
}

EXCLUSION_RULES = {
    "liquidity": {
        "min_daily_volume_a": 50_000_000,
        "min_daily_volume_hk": 100_000_000,
        "exclude_st": True,
        "exclude_delisting_risk": True,
    },
    "policy_suppressed": [
        "教培", "博彩", "高污染", "房地产投机",
    ],
    "tech_replaced": [
        "传统燃油车", "传统零售(非新消费)", "传统媒体", "煤炭火电(纯火电)",
    ],
}

CACHE_CONFIG = {
    "2019_bottom_price": {"file": "2019_bottom_prices.json", "ttl_days": 30},
    "current_price": {"file": "current_prices.json", "ttl_days": 1},
    "candidates_snapshot": {"file": "candidates_snapshot.json", "ttl_days": 1},
    "industry_data": {"file": "industry_data.json", "ttl_days": 30},
    "fundamentals_data": {"file": "fundamentals_data.json", "ttl_days": 7},
}

POLICY_SUPPRESSED_KEYWORDS = {
    "教培": ["教育", "培训", "K12", "学科"],
    "博彩": ["博彩", "彩票", "赌场"],
    "高污染": ["钢铁", "水泥", "化工", "造纸", "印染", "火电"],
    "房地产投机": ["房地产", "房产", "地产开发", "地产", "置地"],
}

TECH_REPLACED_KEYWORDS = {
    "传统燃油车": ["燃油车", "传统汽车", "内燃机"],
    "传统零售(非新消费)": ["百货", "超市", "传统零售"],
    "传统媒体": ["报纸", "出版", "电视广播", "传统媒体"],
    "煤炭火电(纯火电)": ["火电", "煤电", "煤炭发电"],
}

DECLINING_INDUSTRY_KEYWORDS = [
    "煤炭", "火电", "传统燃油", "报纸", "出版", "传呼",
    "房地产", "地产开发", "钢铁", "水泥", "平板玻璃", "造船",
]

INDUSTRY_DEMAND_PROMPT = """你是一位资深行业分析师。请分析以下行业的当前需求状况，判断需求是否"永久萎缩"。

行业：{industry}
当前股票：{stock_name}（{stock_code}）

请从以下维度分析：
1. 行业营收/利润趋势（近3年）
2. 出口/全球份额趋势
3. 产业转移/升级方向
4. 是否符合全球产业趋势（AI、新能源、半导体等）

请用JSON格式回复：
{{
    "demand_status": "增长" | "稳定" | "缓慢萎缩" | "永久萎缩",
    "score": 0-10,
    "reason": "简短理由"
}}
"""

CATALYST_PROMPT = """你是一位宏观策略分析师。请分析当前对{stock_name}（{stock_code}）的催化因素。

该股票所属行业：{industry}
当前涨幅相对2019年底部：{gain_pct}%

请从以下维度分析催化因素：
1. 美联储降息时间表及影响
2. 国家政策支持（十五五等）
3. 全球资金流向与配置
4. 行业自身催化（新品周期、产能扩张等）

请用JSON格式回复：
{{
    "catalyst_score": 0-10,
    "catalyst_factors": ["因素1", "因素2"],
    "timing": "短期(3个月内)" | "中期(3-12个月)" | "长期(1年以上)" | "不确定",
    "reason": "简短理由"
}}
"""

INDUSTRY_CATALYST_PROMPT = """你是一位宏观策略分析师。请分析以下行业当前的催化因素。

行业：{industry}

请从以下维度分析催化因素：
1. 美联储降息时间表及对该行业的影响
2. 国家政策支持（十五五、产业政策等）
3. 全球资金流向与配置对该行业的影响
4. 行业自身催化（新品周期、产能扩张、技术突破等）

请用JSON格式回复：
{{
    "catalyst_score": 0-10,
    "catalyst_factors": ["因素1", "因素2"],
    "timing": "短期(3个月内)" | "中期(3-12个月)" | "长期(1年以上)" | "不确定",
    "reason": "简短理由"
}}
"""

BATCH_EVALUATION_SYSTEM_PROMPT = """你是周金涛康波周期资产筛选助手。基于2019年资产大底假设，请对以下候选资产逐一评估。

## 排除标准（满足任一即排除）

1. **行业需求永久萎缩**：传统燃油车、煤炭火电、报纸出版等夕阳行业，需求不可逆下滑
2. **行业逻辑崩塌且无修复基础**：如地产链中高杠杆(资产负债率>80%)+销售持续下滑+无转型能力的个体
3. **基本面持续恶化**：营收/利润连续多期同比下滑，ROE趋势向下且无改善迹象，资产负债率>85%且持续恶化
4. **政策强压行业**：教培、博彩等受政策严厉限制的行业
5. **技术替代明确**：传统燃油车、传统零售、传统媒体等被新技术替代的领域
6. **流动性不足**：ST/*ST/退市风险股，或日均成交额过低的个股

## 评分维度（仅对通过的资产评分，各0-10分）

- **price_gap**：涨幅偏离度。相对2019年底部涨幅越低(甚至下跌)，分数越高。gain_pct<-20%=10分, <0%=8分, <30%=6分, <50%=4分
- **valuation_safety**：估值安全性。结合PE分位数、股息率、基本面趋势综合判断，警惕"越跌越贵"的价值陷阱。低PE分位数(历史低位)+稳定ROE+合理负债率=高分；PE高位+盈利恶化=低分
  - 9-10分：PE分位数<10% + 盈利稳定/改善 + 股息率>3%
  - 7-8分：PE分位数<20% + 盈利稳定 + 负债率<60%
  - 5-6分：估值合理或盈利有波动但可控
  - 3-4分：PE偏高或盈利趋势不明
  - 1-2分：PE高位+盈利恶化（价值陷阱）
- **catalyst**：催化因素。从宏观、政策、行业、公司四个层面综合评估
  - 9-10分：多重催化叠加（降息+行业政策利好+公司重大产品获批/放量/回购）
  - 7-8分：至少两个催化层面明确（如降息受益+行业景气触底回升），或单一强催化（创新药获批、重磅合作、行业拐点确认）
  - 5-6分：至少一个催化层面明确（宏观降息周期、行业政策支持、公司边际改善等）
  - 3-4分：催化不明确或极远期，无明显短期驱动因素
  - 1-2分：无催化甚至面临利空压制
- **industry_momentum**：行业动能。从需求趋势、竞争格局、政策环境三个角度评估
  - 9-10分：行业需求高增长(>15%)+竞争格局优(龙头集中)+政策大力支持
  - 7-8分：行业需求稳定增长(5-15%)或触底回升+格局良好+政策中性或偏友好
  - 5-6分：需求平稳(0-5%)或竞争激烈但公司有差异化优势
  - 3-4分：需求温和下滑或竞争恶化但行业尚未崩塌
  - 1-2分：需求持续下滑，无改善迹象

## 重要提示

- 地产链资产需逐只仔细甄别：国企背景+低杠杆+有转型(如物业/商业运营)的可以保留，高杠杆+纯开发+销售崩盘的必须排除
- 基本面恶化的资产不能仅因"价格便宜"而通过，必须判断是否有反转迹象
- ETF跳过基本面检查，重点关注行业趋势和估值
- **稳健型资产不可低估**：公用事业、医药、消费等防御性行业，即使缺乏短期爆发性催化剂，只要需求稳定(5-15%增速)、竞争格局清晰、估值处于历史低位，catalyst和industry_momentum不应低于6分。美联储降息周期本身就是这类资产的核心催化，低利率环境将提升其估值中枢
- **ETF的catalyst和industry_momentum评分应参考其跟踪指数的底层资产行业前景**，而非仅看ETF本身的交易属性

## CRITICAL: 代码准确性

- **只评估输入JSON中EXACTLY出现的股票代码，不得添加、删除或修改任何代码**
- **evaluations数组的长度必须等于输入资产的数量，一一对应**
- **不得编造输入中不存在的股票代码（如不要添加记忆中存在的但输入中没有的代码）**
- 每个资产的code字段必须与输入JSON中的code字段完全一致

请用JSON格式回复，包含所有候选资产的评估结果：
{
  "evaluations": [
    {
      "code": "股票代码",
      "status": "passed" | "excluded",
      "exclude_reason": "排除原因(仅status=excluded时)",
      "exclude_category": "行业需求永久萎缩" | "行业逻辑崩塌" | "基本面恶化" | "政策强压" | "技术替代" | "流动性" | "",
      "scores": {
        "price_gap": 0-10,
        "valuation_safety": 0-10,
        "catalyst": 0-10,
        "industry_momentum": 0-10
      },
      "analysis": "一句话分析(必填)"
    }
  ]
}"""


class BottomAssetScreener:
    """周金涛底部资产筛选Agent

    基于2019年资产大底假设，筛选相对2019年涨幅最小/价位更低的优质资产。
    三重筛选：行业需求未永久萎缩 + 估值历史低位 + 催化因素明确
    三重排除：流动性陷阱 + 政策强压 + 技术替代
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.model = self.config.get("model", "claude-3-5-sonnet-20241022")
        self.use_llm = self.config.get("use_llm", False)  # 默认关闭LLM，使用规则筛选

        if LLMClient is not None:
            self.llm_client = LLMClient(model=self.model)
        else:
            self.llm_client = None

        self.base_dir = settings.BASE_DIR
        self.tech_dir = self.base_dir / "技术分析"
        self.tech_dir.mkdir(parents=True, exist_ok=True)
        self.stock_pool_file = self.base_dir / "自选股票池.md"

        self.cache_dir = Path(__file__).resolve().parent.parent.parent / "data" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._bottom_price_cache: Dict[str, Dict] = {}
        self._current_price_cache: Dict[str, float] = {}
        self._industry_cache: Dict[str, str] = {}
        self._fundamentals_cache: Dict[str, Dict] = {}
        self._spot_data_cache: Optional[pd.DataFrame] = None  # A股实时行情缓存
        self._etf_category_cache: Optional[pd.DataFrame] = None  # ETF分类+行情缓存

        self._load_cache()

    # ================================================================
    # AKShare 重试机制
    # ================================================================

    def _call_ak_with_retry(self, func, max_retries: int = 3, delay: float = 2.0, **kwargs):
        """调用akshare函数，带重试机制"""
        retryable_keywords = [
            "Expecting value", "JSONDecodeError",
            "NoneType",
            "Connection aborted", "RemoteDisconnected",
            "timed out", "Timeout",
            "Server disconnected",
        ]
        for attempt in range(max_retries):
            try:
                result = func(**kwargs)
                if result is not None:
                    return result
                if attempt < max_retries - 1:
                    wait = delay * (attempt + 1)
                    time.sleep(wait)
            except Exception as e:
                error_msg = str(e)
                is_retryable = any(kw in error_msg for kw in retryable_keywords)
                if is_retryable and attempt < max_retries - 1:
                    wait = delay * (attempt + 1)
                    print(f"    API重试({attempt+1}/{max_retries}) {type(e).__name__}: {error_msg[:60]}...")
                    time.sleep(wait)
                else:
                    raise
        return None

    # ================================================================
    # 主入口
    # ================================================================

    def run(self) -> Dict[str, Any]:
        """主入口：执行完整筛选Pipeline"""
        return self.screen_bottom_assets()

    def screen_bottom_assets(self) -> Dict[str, Any]:
        """Pipeline主流程"""
        print(f"\n{'='*60}")
        print(f"周金涛底部资产筛选 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}\n")

        # 加载磁盘缓存
        has_snapshot, cached_candidates = self._load_cache()

        if has_snapshot and cached_candidates:
            print("=== Step 1+2: 使用缓存候选资产（跳过扫描） ===")
            candidates = cached_candidates
            print(f"  缓存候选: {len(candidates)} 只（已筛选涨幅<50%）")
            for c in candidates[:10]:
                print(f"    {c.get('code')} {c.get('name')}: {c.get('gain_pct', 0):.1f}%")
        else:
            print("=== Step 1: 候选资产扫描 ===")
            candidates = self._scan_candidates()
            print(f"  扫描得到 {len(candidates)} 只候选资产")
            self._save_cache()

            print("\n=== Step 2: 涨幅偏离度排序 ===")
            candidates.sort(key=lambda x: x.get("gain_pct", 999))
            candidates = [c for c in candidates if c.get("gain_pct", 999) < CANDIDATE_THRESHOLDS["max_gain_pct"]]
            candidates = [c for c in candidates if c.get("gain_pct", -99) > CANDIDATE_THRESHOLDS["min_gain_pct"]]
            etf_count = len([c for c in candidates if c.get("market") == "ETF"])
            print(f"  涨幅<50%的底部候选: {len(candidates)} 只 (其中ETF: {etf_count} 只)")
            for c in candidates[:10]:
                print(f"    {c.get('code')} {c.get('name')}: {c.get('gain_pct', 0):.1f}%")
            # 保存候选快照（后续运行跳过Steps 1+2）
            self._save_cache(candidates=candidates)

            # Step 2.5: 数据补全（LLM模式也需要行业和基本面信息）
            print("\n=== Step 2.5: 数据补全 ===")
            candidates = self._enrich_industries(candidates)
            candidates = self._enrich_fundamentals(candidates)
            # 更新快照（含enrichment数据）
            self._save_cache(candidates=candidates)

        # Step 3+4: 筛选评估
        if self.use_llm and self.llm_client and self.llm_client.is_available():
            print("\n=== Step 3+4: LLM统一评估 ===")
            final_candidates, excluded = self._llm_batch_evaluate(candidates)
            print(f"  通过: {len(final_candidates)} 只, 排除: {len(excluded)} 只")
            for e in excluded[:10]:
                print(f"    排除: {e.get('code')} {e.get('name')} - {e.get('exclude_reason', '')}")
        else:
            print("\n=== Step 3: 三重筛选（规则模式） ===")
            passed_demand = self._filter_demand(candidates)
            print(f"  3a. 行业需求验证通过: {len(passed_demand)} 只")

            passed_valuation = self._filter_valuation(passed_demand)
            print(f"  3b. 估值低位验证通过: {len(passed_valuation)} 只")

            passed_catalyst = self._filter_catalyst(passed_valuation)
            print(f"  3c. 催化因素验证通过: {len(passed_catalyst)} 只")

            print("\n=== Step 4: 三重排除 ===")
            final_candidates, excluded = self._exclude_false_opportunities(passed_catalyst)
            print(f"  排除 {len(excluded)} 只，剩余 {len(final_candidates)} 只")

        print("\n=== Step 5: 多维评分排序 ===")
        ranked = self._score_and_rank(final_candidates)
        recommend_count = len([r for r in ranked if r.get('rating') in ('强烈推荐', '推荐')])
        print(f"  最终推荐 {len(ranked)} 只底部资产（其中强烈推荐+推荐: {recommend_count}）")

        print("\n=== Step 6: 生成报告并同步股票池 ===")
        report_path = self._generate_report(ranked, excluded)
        print(f"  报告已生成: {report_path}")

        a_stock_assets = [r for r in ranked if r.get("market") == "A股"]
        hk_assets = [r for r in ranked if r.get("market") == "港股"]
        etf_assets = [r for r in ranked if r.get("market") == "ETF"]

        # 生成精选ETF列表（板块去重，每板块仅流动性最优的1只）
        curated = self._generate_curated_picks(ranked)
        curated_etfs = curated.get("curated_etfs", [])

        self._sync_stock_pool(a_stock_assets, hk_assets, curated_etfs)
        self._save_cache()

        return {
            "success": True,
            "message": f"筛选完成，推荐{len(ranked)}只底部资产",
            "data": {
                "ranked_assets": ranked,
                "excluded": excluded,
                "report_path": str(report_path),
                "a_stock": a_stock_assets,
                "hk": hk_assets,
                "etf": etf_assets,
            },
            "timestamp": datetime.now().isoformat(),
        }

    # ================================================================
    # Step 1: 候选资产扫描
    # ================================================================

    def _scan_candidates(self) -> List[Dict]:
        """数据驱动的候选资产扫描"""
        candidates = []

        # Phase 1: A股扫描
        print("  [Phase 1] 扫描A股指数成分...")
        a_stock_universe = self._get_index_constituents(
            ["000300", "000905", "000852", "399006", "000688"]
        )
        print(f"    A股候选池: {len(a_stock_universe)} 只（去重后）")
        for i, stock in enumerate(a_stock_universe):
            if (i + 1) % 200 == 0:
                print(f"      进度: {i+1}/{len(a_stock_universe)}")
            bottom_info = self._get_2019_bottom_price(stock["code"])
            price_now = self._get_current_price(stock["code"])
            if bottom_info and price_now and bottom_info["bottom_price"] > 0:
                gain_pct = (price_now - bottom_info["bottom_price"]) / bottom_info["bottom_price"] * 100
                candidates.append({
                    "code": stock["code"],
                    "name": stock["name"],
                    "market": "A股",
                    "industry": stock.get("industry", ""),
                    "price_2019": bottom_info["bottom_price"],
                    "price_2019_date": bottom_info["bottom_date"],
                    "price_now": price_now,
                    "gain_pct": round(gain_pct, 2),
                    "is_anomalous": bottom_info.get("is_anomalous", False),
                })

        # Phase 2: 港股扫描
        print("  [Phase 2] 扫描港股指数成分...")
        hk_universe = self._get_hk_index_constituents(["HSI", "HSTECH", "HSCEI"])
        print(f"    港股候选池: {len(hk_universe)} 只（去重后）")
        for i, stock in enumerate(hk_universe):
            if (i + 1) % 50 == 0:
                print(f"      进度: {i+1}/{len(hk_universe)}")
            bottom_info = self._get_2019_bottom_price(stock["code"])
            price_now = self._get_current_price(stock["code"])
            if bottom_info and price_now and bottom_info["bottom_price"] > 0:
                gain_pct = (price_now - bottom_info["bottom_price"]) / bottom_info["bottom_price"] * 100
                candidates.append({
                    "code": stock["code"],
                    "name": stock["name"],
                    "market": "港股",
                    "industry": stock.get("industry", ""),
                    "price_2019": bottom_info["bottom_price"],
                    "price_2019_date": bottom_info["bottom_date"],
                    "price_now": price_now,
                    "gain_pct": round(gain_pct, 2),
                    "is_anomalous": bottom_info.get("is_anomalous", False),
                })

        # Phase 3: ETF扫描
        print("  [Phase 3] 扫描ETF...")
        etf_universe = self._get_etf_universe()
        print(f"    ETF候选池: {len(etf_universe)} 只（去重后）")
        etf_no_bottom = 0
        etf_no_current = 0
        etf_added = 0
        for i, etf in enumerate(etf_universe):
            if (i + 1) % 30 == 0:
                print(f"      进度: {i+1}/{len(etf_universe)} (已添加: {etf_added})")
            code = etf["code"]
            # ETF 2019底价：跳过不稳定的Sina源，直接用East Money（带重试+退避）
            bottom_info = self._get_2019_bottom_price(code)
            # ETF当前价：用Sina源（fund_etf_category_sina），避免East Money限流
            price_now = self._get_current_etf_nav(code)
            if bottom_info and price_now and bottom_info.get("bottom_price", 0) > 0:
                gain_pct = (price_now - bottom_info["bottom_price"]) / bottom_info["bottom_price"] * 100
                candidates.append({
                    "code": code,
                    "name": etf["name"],
                    "market": "ETF",
                    "industry": etf.get("industry", ""),
                    "price_2019": bottom_info["bottom_price"],
                    "price_2019_date": bottom_info.get("bottom_date", "2019-01-04"),
                    "price_now": price_now,
                    "gain_pct": round(gain_pct, 2),
                })
                etf_added += 1
            elif not bottom_info:
                etf_no_bottom += 1
            elif not price_now:
                etf_no_current += 1
            # East Money限流严格，每次请求间隔0.3s
            time.sleep(0.3)

        print(f"    ETF扫描完成: 添加 {etf_added} 只, 无底价 {etf_no_bottom} 只, 无现价 {etf_no_current} 只")
        return candidates

    # ================================================================
    # 指数成分获取
    # ================================================================

    def _get_index_constituents(self, index_codes: List[str]) -> List[Dict]:
        """获取A股指数成分股列表

        AKShare index_stock_cons_csindex 返回列：
        日期, 指数代码, 指数名称, 指数英文名称,
        成分券代码, 成分券名称, 成分券英文名称, 交易所, 交易所英文名称
        交易所值为 "上海证券交易所" 或 "深圳证券交易所" 或 "北京证券交易所"
        """
        all_stocks = []
        seen = set()

        # 交易所 -> 后缀映射
        exchange_map = {
            "上海证券交易所": "SH",
            "深圳证券交易所": "SZ",
            "北京证券交易所": "BJ",
            "Shanghai Stock Exchange": "SH",
            "Shenzhen Stock Exchange": "SZ",
            "Beijing Stock Exchange": "BJ",
        }

        for idx_code in index_codes:
            try:
                df = self._call_ak_with_retry(
                    ak.index_stock_cons_csindex, symbol=idx_code
                )
                if df is None or df.empty:
                    print(f"    指数 {idx_code} 成分数据为空")
                    continue

                for _, row in df.iterrows():
                    raw_code = str(row.get("成分券代码", ""))
                    if not raw_code:
                        continue
                    exchange = str(row.get("交易所", ""))

                    suffix = "SH"  # 默认上海
                    for ex_key, ex_suffix in exchange_map.items():
                        if ex_key in exchange:
                            suffix = ex_suffix
                            break

                    # 也通过代码判断交易所
                    if suffix == "SH" and (raw_code.startswith("0") or raw_code.startswith("3") or raw_code.startswith("2")):
                        suffix = "SZ"

                    std_code = f"{raw_code}.{suffix}"

                    if std_code not in seen:
                        seen.add(std_code)
                        all_stocks.append({
                            "code": std_code,
                            "name": str(row.get("成分券名称", "")),
                            "industry": "",
                        })
            except Exception as e:
                print(f"    获取指数 {idx_code} 成分失败: {e}")
                continue

        return all_stocks

    def _get_hk_index_constituents(self, index_codes: List[str]) -> List[Dict]:
        """获取港股候选池

        多数据源融合（按优先级）：
        1. eniu.com 全量港股列表 — ~250只，独立于 Sina/East Money，稳定可靠
        2. Sina stock_hk_spot — 恒生指数成分蓝筹股（~60只，含实时价格）
        3. East Money stock_hk_ggt_components_em — 港股通全部成分（~600只，可能被限流）
        4. East Money stock_hk_hot_rank_em — 热门港股（~100只）

        最终去重合并。
        index_codes 参数保留以兼容接口。
        """
        all_stocks = []
        seen = set()

        def add_sina_stock(symbol, name, lasttrade=None):
            """添加Sina来源的港股"""
            std_code = f"{str(symbol).zfill(5)}.HK"
            if std_code in seen:
                return
            seen.add(std_code)
            if lasttrade:
                try:
                    price = float(lasttrade)
                    if price > 0:
                        self._current_price_cache[f"current_{std_code}"] = price
                except (ValueError, TypeError):
                    pass
            all_stocks.append({
                "code": std_code,
                "name": str(name),
                "industry": "",
            })

        # Source 0 (NEW - PRIMARY): eniu.com 全量港股列表 (~250只)
        eniu_codes = []
        try:
            eniu_url = "https://eniu.com/static/data/stock_list.json"
            resp = requests.get(eniu_url, timeout=15)
            if resp.status_code == 200:
                all_data = resp.json()
                hk_data = [s for s in all_data if s.get('stock_id', '').startswith('hk')]
                for s in hk_data:
                    number = str(s.get('stock_number', ''))
                    # 过滤指数（3位代码如 hsi/hscei）和无效代码
                    if len(number) != 5 or not number.isdigit():
                        continue
                    std_code = f"{number}.HK"
                    if std_code in seen:
                        continue
                    seen.add(std_code)
                    name = s.get('stock_name', '')
                    all_stocks.append({
                        "code": std_code,
                        "name": name,
                        "industry": "",
                    })
                    eniu_codes.append(number)
                print(f"    eniu.com全列表: {len(eniu_codes)} 只")
        except Exception as e:
            print(f"    eniu.com获取失败: {type(e).__name__}")

        # Source 1: Sina stock_hk_spot (HSI blue chips, always reliable, provides real-time prices)
        try:
            df_sina = ak.stock_hk_spot()
            if df_sina is not None and not df_sina.empty:
                sina_added = 0
                for _, row in df_sina.iterrows():
                    symbol = str(row.get("symbol", ""))
                    std_code = f"{symbol.zfill(5)}.HK"
                    if std_code not in seen:
                        sina_added += 1
                    add_sina_stock(
                        symbol,
                        row.get("name", ""),
                        row.get("lasttrade"),
                    )
                print(f"    Sina蓝筹: {len(df_sina)} 只 (新增 {sina_added})")
        except Exception as e:
            print(f"    Sina蓝筹获取失败: {e}")

        # Batch-fetch current prices for eniu stocks via Sina real-time API
        if eniu_codes:
            self._fetch_hk_prices_sina_batch(eniu_codes)

        # Source 2: East Money GGT components (comprehensive, ~600 stocks)
        try:
            df_ggt = self._call_ak_with_retry(ak.stock_hk_ggt_components_em)
            if df_ggt is not None and not df_ggt.empty:
                ggt_added = 0
                for _, row in df_ggt.iterrows():
                    raw_code = str(row.get("代码", ""))
                    if not raw_code:
                        continue
                    std_code = f"{raw_code.zfill(5)}.HK"
                    if std_code in seen:
                        continue
                    seen.add(std_code)
                    try:
                        price = float(row.get("最新价", 0))
                        if price > 0:
                            self._current_price_cache[f"current_{std_code}"] = price
                    except (ValueError, TypeError):
                        pass
                    all_stocks.append({
                        "code": std_code,
                        "name": str(row.get("名称", "")),
                        "industry": "",
                    })
                    ggt_added += 1
                print(f"    港股通成分: {ggt_added} 只（新增）")
        except Exception as e:
            print(f"    港股通成分获取失败(限流): {type(e).__name__}")

        # Source 3: Hot rank (best effort, 100 most active)
        try:
            df_hot = ak.stock_hk_hot_rank_em()
            if df_hot is not None and not df_hot.empty:
                hot_added = 0
                for _, row in df_hot.iterrows():
                    raw_code = str(row.get("代码", ""))
                    if not raw_code:
                        continue
                    std_code = f"{raw_code.zfill(5)}.HK"
                    if std_code in seen:
                        continue
                    seen.add(std_code)
                    try:
                        price = float(row.get("最新价", 0))
                        if price > 0:
                            self._current_price_cache[f"current_{std_code}"] = price
                    except (ValueError, TypeError):
                        pass
                    all_stocks.append({
                        "code": std_code,
                        "name": str(row.get("股票名称", "")),
                        "industry": "",
                    })
                    hot_added += 1
                print(f"    港股热门: {hot_added} 只（新增）")
        except Exception as e:
            print(f"    港股热门获取失败: {type(e).__name__}")

        return all_stocks

    def _fetch_single_hk_price_sina(self, pure_code: str) -> Optional[float]:
        """通过新浪实时行情API获取单只港股当前价格。

        比 stock_hk_daily() 快得多（单次HTTP vs 下载完整历史K线）。
        返回最新价(float)或None。
        """
        try:
            headers = {"Referer": "https://finance.sina.com.cn"}
            resp = requests.get(
                f"http://hq.sinajs.cn/list=hk{pure_code}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            resp.encoding = 'gbk'
            # var hq_str_hk00700="NAME,...,price,...";
            text = resp.text.strip()
            if '"' not in text:
                return None
            fields = text.split('"')[1].split(",")
            if len(fields) < 7:
                return None
            price = float(fields[6])
            return price if price > 0 else None
        except Exception:
            return None

    def _fetch_hk_stocks_from_eniu(self) -> List[tuple]:
        """从 eniu.com 获取全部港股列表，返回 [(code_5digit, name), ...]。

        不依赖 Sina 或 East Money，作为独立的第三数据源。
        """
        try:
            resp = requests.get(
                "https://eniu.com/static/data/stock_list.json",
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            all_data = resp.json()
            result = []
            for s in all_data:
                if not s.get('stock_id', '').startswith('hk'):
                    continue
                number = str(s.get('stock_number', ''))
                if len(number) != 5 or not number.isdigit():
                    continue  # 过滤指数(3位)和无效代码
                result.append((number, s.get('stock_name', '')))
            return result
        except Exception:
            return []

    def _fetch_hk_prices_sina_batch(self, codes: List[str]) -> None:
        """通过新浪实时行情API批量获取港股当前价格。

        每次最多50只（URL长度限制），写入 self._current_price_cache。
        Sina字段: 0=英文名,1=中文名,2=今开,3=昨收,4=最高,5=最低,6=最新价,...
        """
        if not codes:
            return

        batch_size = 50
        headers = {"Referer": "https://finance.sina.com.cn"}
        total_updated = 0

        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            symbols = ",".join(f"hk{c}" for c in batch)
            try:
                resp = requests.get(
                    f"http://hq.sinajs.cn/list={symbols}",
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code != 200:
                    continue
                resp.encoding = 'gbk'
                for line in resp.text.strip().split("\n"):
                    if not line.strip() or "=" not in line:
                        continue
                    try:
                        # var hq_str_hk00700="NAME,中文名,...,price,...";
                        code_part = line.split("=")[0].strip()
                        hk_code = code_part.replace("var hq_str_hk", "").strip()
                        data_part = line.split('"')[1] if '"' in line else ""
                        if not data_part:
                            continue
                        fields = data_part.split(",")
                        if len(fields) < 7:
                            continue
                        price = float(fields[6])  # 最新价
                        if price > 0:
                            std_code = f"{hk_code.zfill(5)}.HK"
                            self._current_price_cache[f"current_{std_code}"] = price
                            total_updated += 1
                    except (ValueError, IndexError, KeyError):
                        continue
            except Exception:
                continue

        if total_updated > 0:
            print(f"    Sina批量价格: {total_updated} 只")

    # ================================================================
    # 2019年底部价格获取
    # ================================================================

    def _get_2019_bottom_price(self, code: str) -> Optional[Dict]:
        """获取2019年底部区间的最低收盘价（后复权）

        A股使用 ak.stock_zh_a_daily，港股使用 ak.stock_hk_daily，
        避免依赖不稳定的 East Money 源。
        """
        cache_key = f"bottom_{code}"
        if cache_key in self._bottom_price_cache:
            return self._bottom_price_cache[cache_key]

        pure_code = code.split(".")[0]

        try:
            if code.endswith(".HK"):
                df = self._call_ak_with_retry(
                    ak.stock_hk_daily,
                    symbol=pure_code,
                    adjust="qfq",
                )
                key_dates = KEY_BOTTOM_DATES["港股"]
            else:
                # ETF/基金代码识别：SH所有5开头(50-59)都是基金，SZ的15/16/18开头是基金
                # SH A股为600-603/605/688，所以5xxxxx.SH全部是基金
                _is_etf = (
                    (code.endswith(".SH") and pure_code.startswith("5"))
                    or (code.endswith(".SZ") and pure_code[:2] in ("15", "16", "18"))
                )
                if _is_etf:
                    # ETF: 直接用Sina qfq计算(East Money常被限流不可靠)
                    df = self._compute_etf_qfq_daily(code)
                    if df is None:
                        return None
                    key_dates = KEY_BOTTOM_DATES["A股"]
                else:
                    # stock_zh_a_daily 需要带前缀
                    if code.endswith(".SH"):
                        ak_sym = f"sh{pure_code}"
                    elif code.endswith(".SZ"):
                        ak_sym = f"sz{pure_code}"
                    elif code.endswith(".BJ"):
                        ak_sym = f"bj{pure_code}"
                    else:
                        ak_sym = f"sh{pure_code}"

                    df = self._call_ak_with_retry(
                        ak.stock_zh_a_daily,
                        symbol=ak_sym,
                        start_date=BOTTOM_PERIOD["start"],
                        end_date=BOTTOM_PERIOD["end"],
                        adjust="qfq",
                    )
                    key_dates = KEY_BOTTOM_DATES["A股"]
        except Exception as e:
            # 东方财富源失败，尝试备选源
            if not code.endswith(".HK"):
                # Fallback 1: East Money direct API
                df = self._fetch_daily_from_eastmoney(code, BOTTOM_PERIOD["start"], BOTTOM_PERIOD["end"], "qfq")
                if df is not None and not df.empty:
                    key_dates = KEY_BOTTOM_DATES["A股"]
                else:
                    # Fallback 2: Sina K线 + qfq.js (完全独立的第三数据源)
                    df = self._fetch_a_stock_qfq_daily_from_sina(code)
                    if df is not None and not df.empty:
                        key_dates = KEY_BOTTOM_DATES["A股"]
                    else:
                        print(f"    获取 {code} 历史价格失败: {type(e).__name__}")
                        return None
            else:
                print(f"    获取 {code} 历史价格失败: {type(e).__name__}")
                return None

        if df is None or df.empty:
            # 东方财富源返回空，尝试备选源
            if not code.endswith(".HK"):
                df = self._fetch_daily_from_eastmoney(code, BOTTOM_PERIOD["start"], BOTTOM_PERIOD["end"], "qfq")
                if df is not None and not df.empty:
                    key_dates = KEY_BOTTOM_DATES["A股"]
                elif not _is_etf:
                    # 非ETF的个股: 尝试Sina K线 + qfq.js
                    df = self._fetch_a_stock_qfq_daily_from_sina(code)
                    if df is not None and not df.empty:
                        key_dates = KEY_BOTTOM_DATES["A股"]
                    else:
                        return None
                else:
                    return None
            else:
                return None

        # 过滤到底部区间
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            mask = (df["date"] >= BOTTOM_PERIOD["start"]) & (df["date"] <= BOTTOM_PERIOD["end"])
            df = df[mask]
        elif "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"])
            mask = (df["日期"] >= BOTTOM_PERIOD["start"]) & (df["日期"] <= BOTTOM_PERIOD["end"])
            df = df[mask]
        elif df.index.name in ("date", "日期") or isinstance(df.index, pd.DatetimeIndex):
            # _compute_etf_qfq_daily 返回DatetimeIndex的DataFrame
            mask = (df.index >= BOTTOM_PERIOD["start"]) & (df.index <= BOTTOM_PERIOD["end"])
            df = df[mask]

        if df.empty:
            return None

        # 统一列名
        close_col = "close" if "close" in df.columns else (
            "qfq_close" if "qfq_close" in df.columns else "收盘"
        )
        date_col = "date" if "date" in df.columns else (
            "日期" if "日期" in df.columns else df.index.name
        )

        if close_col not in df.columns:
            return None

        # 若date列为索引, 重置以便提取日期字符串
        if date_col and date_col not in df.columns:
            df = df.reset_index()

        try:
            min_idx = df[close_col].idxmin()
            bottom_price = float(df.loc[min_idx, close_col])
            bottom_date = str(df.loc[min_idx, date_col])[:10]
            period_high = float(df[close_col].max())
        except Exception:
            return None

        is_anomalous = True
        try:
            bottom_dt = pd.Timestamp(bottom_date)
            for key_date in key_dates:
                key_dt = pd.Timestamp(key_date)
                if abs((bottom_dt - key_dt).days) <= 40:
                    is_anomalous = False
                    break
        except Exception:
            pass

        result = {
            "bottom_price": bottom_price,
            "bottom_date": bottom_date,
            "bottom_period_high": period_high,
            "bottom_period_low": bottom_price,
            "is_anomalous": is_anomalous,
        }
        self._bottom_price_cache[cache_key] = result
        return result

    # ================================================================
    # 当前价格获取
    # ================================================================

    def _get_current_price(self, code: str) -> Optional[float]:
        """获取股票当前价格

        A股使用 ak.stock_zh_a_spot()（非 East Money 源），
        港股优先使用 Sina 实时API（快），回退 daily（慢但可靠）。
        """
        cache_key = f"current_{code}"
        if cache_key in self._current_price_cache:
            return self._current_price_cache[cache_key]

        pure_code = code.split(".")[0]

        try:
            if code.endswith(".HK"):
                # 港股：优先 Sina 实时API（快速，支持任意港股）
                price = self._fetch_single_hk_price_sina(pure_code)
                if price is not None:
                    self._current_price_cache[cache_key] = price
                    return price

                # 回退：daily 数据的最新收盘价（慢但可靠）
                df = self._call_ak_with_retry(
                    ak.stock_hk_daily, symbol=pure_code, adjust=""
                )
                if df is not None and not df.empty:
                    close_col = "close" if "close" in df.columns else "收盘"
                    if close_col in df.columns:
                        price = float(df.iloc[-1][close_col])
                        self._current_price_cache[cache_key] = price
                        return price
                return None
            else:
                # A股：使用 stock_zh_a_spot (代码格式: sh600519, sz000858, bj920000)
                if self._spot_data_cache is None:
                    self._spot_data_cache = self._call_ak_with_retry(ak.stock_zh_a_spot)
                df = self._spot_data_cache
                if df is None or df.empty:
                    return None
                # 构造带前缀的代码
                suffix_to_prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}
                suffix = code.split(".")[-1].upper() if "." in code else "SH"
                prefix = suffix_to_prefix.get(suffix, "sh")
                lookup_code = f"{prefix}{pure_code}"
                row = df[df["代码"] == lookup_code]
                if not row.empty:
                    price = float(row.iloc[0]["最新价"])
                    self._current_price_cache[cache_key] = price
                    return price
                # spot数据不包含ETF，回退到East Money获取最新收盘价
                if not code.endswith(".HK"):
                    price = self._fetch_current_from_eastmoney(code)
                    if price is not None:
                        self._current_price_cache[cache_key] = price
                        return price
                return None
        except Exception as e:
            print(f"    获取 {code} 当前价格失败: {type(e).__name__}")
            return None

    def _fetch_daily_from_eastmoney(self, code: str, start: str, end: str, adjust: str) -> Optional[pd.DataFrame]:
        """从East Money获取日线数据（Sina源不可用时的fallback）

        adjust: 'qfq'=前复权, ''=不复权, 'hfq'=后复权
        """
        import requests
        pure_code = code.split(".")[0]
        suffix = code.split(".")[-1].upper() if "." in code else "SH"
        market = "1" if suffix == "SH" else "0"
        fqt = {"qfq": "1", "hfq": "2"}.get(adjust, "0")

        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={market}.{pure_code}"
            f"&fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt={fqt}&beg={start}&end={end}&lmt=500"
        )
        for attempt in range(2):
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                data = r.json()
                klines = data.get("data", {}).get("klines", [])
                if not klines:
                    return None
                rows = []
                for line in klines:
                    parts = line.split(",")
                    rows.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "amount": float(parts[6]),
                    })
                return pd.DataFrame(rows)
            except Exception:
                if attempt < 1:
                    time.sleep(0.5)
        return None

    def _fetch_etf_qfq_factors(self, code: str) -> Optional[List[Dict]]:
        """获取ETF的前复权因子（从Sina qfq.js接口）

        返回按日期升序排列的调整事件列表，每个事件包含:
          date, split_ratio(f), cumulative_factor(s), dividend_per_share(u)
        """
        import requests as req
        pure_code = code.split(".")[0]
        suffix = "sh" if code.endswith(".SH") else "sz"
        try:
            r = req.get(
                f"https://finance.sina.com.cn/realstock/company/{suffix}{pure_code}/qfq.js",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            match = re.search(r'=\s*(\{.+\})', r.text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group(1))
            return data.get("data", [])
        except Exception:
            return None

    def _compute_etf_qfq_daily(self, code: str) -> Optional[pd.DataFrame]:
        """使用Sina数据+前复权因子计算ETF的qfq日线数据

        步骤:
        1. fund_etf_hist_sina 获取不复权日线
        2. Sina qfq.js 获取前复权因子(拆分+分红)
        3. 向后遍历分红事件,计算累积调整后的qfq价格
        """
        pure_code = code.split(".")[0]
        suffix = "sh" if code.endswith(".SH") else "sz"

        # 1. 获取不复权日线
        try:
            df = self._call_ak_with_retry(
                ak.fund_etf_hist_sina,
                symbol=f"{suffix}{pure_code}",
            )
            if df is None or df.empty:
                return None
        except Exception:
            return None

        # 统一日期列
        date_col = "date" if "date" in df.columns else "日期"
        close_col = "close" if "close" in df.columns else "收盘"
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
        df.index.name = "date"
        df = df.sort_index()

        # 2. 获取前复权因子
        factors = self._fetch_etf_qfq_factors(code)
        if not factors:
            return None

        base_entry = [e for e in factors if e["d"] == "1900-01-01"]
        if not base_entry:
            return None
        split_ratio = float(base_entry[0]["s"])

        # 提取所有非base事件(拆分+分红), 按日期升序
        all_events = sorted(
            [e for e in factors if e["d"] != "1900-01-01"],
            key=lambda x: x["d"],
        )

        # 3. 计算qfq价格
        df["qfq_close"] = df[close_col].astype(float)

        # 拆分调整: 第一个事件之前的日期除以拆分比例
        # (修复: 之前用div_events(仅u>0)做条件, ETF纯拆分(u=0)时整个跳过)
        if split_ratio > 1.0 and all_events:
            first_event_date = pd.Timestamp(all_events[0]["d"])
            mask = df.index < first_event_date
            df.loc[mask, "qfq_close"] = df.loc[mask, "qfq_close"] / split_ratio

        # 分红调整: 向后遍历, 每个除权日之前的日期乘以(收盘-分红)/收盘
        for event in all_events:
            dividend = float(event["u"])
            if dividend <= 0:
                continue
            event_date = pd.Timestamp(event["d"])
            if event_date in df.index:
                close_on_event = float(df.loc[event_date, "qfq_close"])
            else:
                m = df.index <= event_date
                if m.any():
                    close_on_event = float(df[m].iloc[-1]["qfq_close"])
                else:
                    continue
            if close_on_event > 0:
                adj = (close_on_event - dividend) / close_on_event
                mask2 = df.index < event_date
                df.loc[mask2, "qfq_close"] = df.loc[mask2, "qfq_close"] * adj

        # 整理列: 删除原不复权close/收盘, 将qfq_close重命名为close
        if close_col != "close":
            df = df.drop(columns=[close_col])
        if "close" in df.columns:
            df = df.drop(columns=["close"])
        df = df.rename(columns={"qfq_close": "close"})

        return df

    def _fetch_a_stock_qfq_daily_from_sina(self, code: str) -> Optional[pd.DataFrame]:
        """使用Sina K线+前复权因子计算个股A股的qfq日线数据

        步骤:
        1. Sina CN_MarketData.getKLineData 获取K线(原始价格)
        2. Sina qfq.js 获取前复权因子(拆分+分红)
        3. 应用前复权转换，使历史价格与当前价格可比
        """
        pure_code = code.split(".")[0]
        suffix = "sh" if code.endswith(".SH") else "sz"

        # 1. 获取原始K线数据
        try:
            url = (
                f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"CN_MarketData.getKLineData?symbol={suffix}{pure_code}&scale=240&ma=no&datalen=5000"
            )
            resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=15)
            if resp.status_code != 200:
                return None
            raw_data = resp.json()
            if not raw_data:
                return None
        except Exception:
            return None

        rows = []
        for d in raw_data:
            rows.append({
                "date": pd.Timestamp(d["day"]),
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
                "volume": float(d["volume"]),
            })
        df = pd.DataFrame(rows)
        df = df.set_index("date").sort_index()

        # 2. 获取前复权因子
        try:
            r = requests.get(
                f"https://finance.sina.com.cn/realstock/company/{suffix}{pure_code}/qfq.js",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            match = re.search(r'=\s*(\{.+\})', r.text, re.DOTALL)
            if not match:
                return None
            qfq_data = json.loads(match.group(1))
            factors = qfq_data.get("data", [])
            if not factors:
                return df  # no adjustments needed, raw data is fine
        except Exception:
            return df  # can't get factors, use raw data

        # 3. Apply 前复权: raw_close / factor_for_that_date = qfq_close
        # Build factor timeline: each factor entry applies from its date until next factor date
        sorted_factors = sorted(factors, key=lambda x: x["d"])
        # The factor for a given date = the factor whose date <= trade_date
        # (the factor applies from that date forward)

        df["qfq_factor"] = 1.0
        for i, entry in enumerate(sorted_factors):
            factor_date = pd.Timestamp(entry["d"])
            factor_val = float(entry["f"])
            next_date = pd.Timestamp(sorted_factors[i + 1]["d"]) if i + 1 < len(sorted_factors) else pd.Timestamp("2099-01-01")
            mask = (df.index >= factor_date) & (df.index < next_date)
            df.loc[mask, "qfq_factor"] = factor_val

        df["qfq_close"] = df["close"] / df["qfq_factor"]
        df["qfq_open"] = df["open"] / df["qfq_factor"]
        df["qfq_high"] = df["high"] / df["qfq_factor"]
        df["qfq_low"] = df["low"] / df["qfq_factor"]

        # Replace original columns with qfq-adjusted values
        df["close"] = df["qfq_close"]
        df["open"] = df["qfq_open"]
        df["high"] = df["qfq_high"]
        df["low"] = df["qfq_low"]
        df = df.drop(columns=["qfq_close", "qfq_open", "qfq_high", "qfq_low", "qfq_factor"])

        return df

    def _fetch_current_from_eastmoney(self, code: str) -> Optional[float]:
        """从East Money获取最新收盘价（ETF在stock_zh_a_spot中不存在时的fallback）"""
        import requests
        pure_code = code.split(".")[0]
        suffix = code.split(".")[-1].upper() if "." in code else "SH"
        market = "1" if suffix == "SH" else "0"
        today = datetime.now().strftime("%Y%m%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={market}.{pure_code}"
            f"&fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=1&beg={week_ago}&end={today}&lmt=5"
        )
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            data = r.json()
            klines = data.get("data", {}).get("klines", [])
            if klines:
                return float(klines[-1].split(",")[2])
        except Exception:
            time.sleep(0.5)
        return None

    # ================================================================
    # ETF相关
    # ================================================================

    def _normalize_etf_code(self, raw_code: str) -> str:
        """标准化ETF代码格式

        fund_etf_category_sina 返回的代码格式如 'sz159998' → '159998.SZ'
        """
        code = str(raw_code).strip().lower()
        if code.startswith("sz"):
            return f"{code[2:]}.SZ"
        elif code.startswith("sh"):
            return f"{code[2:]}.SH"
        elif code.startswith("bj"):
            return f"{code[2:]}.BJ"
        # 已经是标准格式
        if "." in code:
            return code.upper()
        # 纯数字，根据首位判断
        if len(code) == 6:
            if code.startswith("5"):
                return f"{code}.SH"
            elif code.startswith(("15", "16", "18")):
                return f"{code}.SZ"
        return f"{code}.SH"

    def _get_etf_universe(self) -> List[Dict]:
        """获取ETF候选池"""
        etfs = []
        seen = set()

        # 来源1：自选股票池中已有的ETF
        pool_etfs = self._read_stock_pool_etfs()
        for etf in pool_etfs:
            code = self._normalize_etf_code(etf["code"])
            if code not in seen:
                seen.add(code)
                etfs.append({"code": code, "name": etf["name"], "industry": ""})

        # 来源2：RECOMMENDED_ETFS
        try:
            from .etf_fundamental import RECOMMENDED_ETFS
            for etf_info in RECOMMENDED_ETFS:
                code = self._normalize_etf_code(etf_info.get("code", ""))
                if code and code not in seen:
                    seen.add(code)
                    etfs.append({
                        "code": code,
                        "name": etf_info.get("name", ""),
                        "industry": etf_info.get("industry", ""),
                    })
        except ImportError:
            pass

        # 来源3：全市场ETF（fund_etf_category_sina），按成交额筛选（≥5000万，流动性过滤）
        try:
            df = self._call_ak_with_retry(ak.fund_etf_category_sina, symbol="ETF基金")
            if df is not None and not df.empty:
                # 缓存到 _etf_category_cache，避免 _get_current_etf_nav 重复调用
                self._etf_category_cache = df
                # 按成交额筛选（替代"规模"列）
                if "成交额" in df.columns:
                    df["成交额_num"] = pd.to_numeric(df["成交额"], errors="coerce")
                    df = df[df["成交额_num"] > 5_000_000]  # 成交额 > 5000万
                for _, row in df.iterrows():
                    raw_code = str(row.get("代码", ""))
                    if not raw_code:
                        continue
                    code = self._normalize_etf_code(raw_code)
                    if code and code not in seen:
                        seen.add(code)
                        etfs.append({
                            "code": code,
                            "name": str(row.get("名称", "")),
                            "industry": "",
                        })
        except Exception as e:
            print(f"    获取全市场ETF列表失败: {e}")

        return etfs

    def _get_etf_nav_at_date(self, code: str, date_str: str) -> Optional[float]:
        """获取ETF在指定日期的净值

        优先使用 fund_etf_hist_sina（Sina 源），失败时尝试 fund_etf_hist_em。
        """
        pure_code = code.split(".")[0]

        # 方式1：fund_etf_hist_sina（Sina 源）
        try:
            df = self._call_ak_with_retry(
                ak.fund_etf_hist_sina,
                symbol=pure_code,
            )
            if df is not None and not df.empty:
                date_col = "date" if "date" in df.columns else "日期"
                close_col = "close" if "close" in df.columns else "收盘"
                if date_col in df.columns:
                    df[date_col] = pd.to_datetime(df[date_col])
                    target_date = pd.Timestamp(date_str)
                    mask = df[date_col] <= target_date
                    if mask.any():
                        closest = df[mask].iloc[-1]
                        return float(closest[close_col])
        except Exception:
            pass

        # 方式2：fund_etf_hist_em（East Money，可能不稳定）
        try:
            df = self._call_ak_with_retry(
                ak.fund_etf_hist_em,
                symbol=pure_code,
                start_date="20190101",
                end_date="20190131",
            )
            if df is not None and not df.empty:
                target_date = pd.Timestamp(date_str)
                if "日期" in df.columns:
                    df["日期"] = pd.to_datetime(df["日期"])
                closest_idx = (df["日期"] - target_date).abs().argsort().iloc[0]
                return float(df.iloc[closest_idx]["收盘"])
        except Exception:
            pass

        return None

    def _get_current_etf_nav(self, code: str) -> Optional[float]:
        """获取ETF当前净值

        使用 fund_etf_category_sina（Sina 源，含实时价格）。
        """
        pure_code = code.split(".")[0]

        # 从 fund_etf_category_sina 获取
        try:
            if self._etf_category_cache is None:
                self._etf_category_cache = self._call_ak_with_retry(
                    ak.fund_etf_category_sina, symbol="ETF基金"
                )
            df = self._etf_category_cache
            if df is not None and not df.empty and "代码" in df.columns:
                for try_code in [f"sz{pure_code}", f"sh{pure_code}", pure_code]:
                    row = df[df["代码"] == try_code]
                    if not row.empty:
                        return float(row.iloc[0]["最新价"])
        except Exception:
            pass

        return None

    def _read_stock_pool_etfs(self) -> List[Dict]:
        """从自选股票池读取ETF条目"""
        etfs = []
        if not self.stock_pool_file.exists():
            return etfs

        try:
            content = read_text_with_retry(self.stock_pool_file)
            in_etf_section = False
            for line in content.split("\n"):
                if "ETF基金" in line or "etf" in line.lower():
                    in_etf_section = True
                    continue
                if in_etf_section and line.startswith("##"):
                    in_etf_section = False
                    continue
                if in_etf_section:
                    m = re.match(r'-\s*(.+?)\s*\((\d+\.?(?:SH|SZ)?)\)', line.strip())
                    if m:
                        name = m.group(1).strip()
                        code = m.group(2).strip()
                        if "." not in code:
                            if code.startswith("5"):
                                code = f"{code}.SH"
                            else:
                                code = f"{code}.SZ"
                        etfs.append({"code": code, "name": name})
        except Exception:
            pass

        return etfs

    # ================================================================
    # Step 2.5a: 行业分类 enrichment
    # ================================================================

    def _enrich_industries(self, candidates: List[Dict]) -> List[Dict]:
        """为候选资产补全行业分类信息。

        A股：调用 ak.stock_individual_info_em 获取东方财富行业分类
        港股：尝试 ak.stock_hk_spot_em（含行业字段），回退标记为"港股-未分类"
        ETF：使用 etf_fundamental.py 中的映射
        """
        enriched = 0
        for i, c in enumerate(candidates):
            if c.get("industry") and c["industry"] != "":
                continue  # 已有行业信息，跳过

            code = c["code"]
            cache_key = f"industry_{code}"
            if cache_key in self._industry_cache:
                c["industry"] = self._industry_cache[cache_key]
                enriched += 1
                continue

            if i % 100 == 0 and i > 0:
                print(f"    行业进度: {i}/{len(candidates)}")

            try:
                if c.get("market") == "ETF":
                    industry = self._get_etf_industry(c["name"])
                elif c.get("market") == "港股":
                    industry = self._get_hk_industry(code)
                else:
                    industry = self._get_a_share_industry(code)
            except Exception:
                industry = ""

            if industry:
                c["industry"] = industry
                self._industry_cache[cache_key] = industry
                enriched += 1

            time.sleep(0.15)  # rate limiting

        print(f"    行业分类补全: {enriched}/{len(candidates)} 只")
        self._save_cache()
        return candidates

    def _get_a_share_industry(self, code: str) -> str:
        """获取A股行业分类"""
        pure_code = code.split(".")[0]
        try:
            df = self._call_ak_with_retry(
                ak.stock_individual_info_em, symbol=pure_code, max_retries=1
            )
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    item = str(row.get("item", ""))
                    if "行业" in item:
                        return str(row.get("value", ""))
        except Exception:
            pass
        return ""

    def _get_hk_industry(self, code: str) -> str:
        """获取港股行业分类。通过 stock_hk_spot_em 或标记为未分类。"""
        pure_code = code.zfill(5) if len(code) < 5 else code
        pure_code = pure_code.split(".")[0]
        try:
            df = self._call_ak_with_retry(ak.stock_hk_spot_em, max_retries=1)
            if df is not None and not df.empty:
                for try_code in [pure_code, pure_code[-4:], pure_code.zfill(5)]:
                    row = df[df["代码"] == try_code]
                    if not row.empty:
                        for col in ["行业", "sector", "industry", "板块", "所属行业"]:
                            if col in df.columns:
                                val = str(row.iloc[0][col])
                                if val and val != "nan":
                                    return val
                        # 部分HK spot数据有"分类"字段
                        if "分类" in df.columns:
                            val = str(row.iloc[0]["分类"])
                            if val and val != "nan":
                                return val
        except Exception:
            pass
        return "港股-未分类"

    def _get_etf_industry(self, name: str) -> str:
        """根据ETF名称推断行业"""
        try:
            from .etf_fundamental import ETF_NAME_INDUSTRY_MAP
            for etf_name, industry in ETF_NAME_INDUSTRY_MAP.items():
                if etf_name in name:
                    return industry
        except ImportError:
            pass

        # 关键词启发式匹配
        kw_map = {
            "恒生科技": "科技", "科创": "科技", "半导体": "半导体",
            "芯片": "半导体", "新能源": "新能源", "光伏": "新能源",
            "医药": "医药", "医疗": "医药", "创新药": "医药",
            "消费": "消费", "食品": "消费", "白酒": "消费",
            "证券": "金融", "银行": "金融", "保险": "金融",
            "军工": "军工", "黄金": "贵金属", "有色": "有色",
            "地产": "房地产", "房地产": "房地产",
        }
        for kw, ind in kw_map.items():
            if kw in name:
                return ind
        return ""

    def _assign_etf_sector(self, name: str) -> str:
        """将ETF名称映射到标准化的板块/概念分类（用于去重）。"""
        # 先尝试 ETF_NAME_INDUSTRY_MAP 精确匹配
        try:
            from .etf_fundamental import ETF_NAME_INDUSTRY_MAP
            for etf_name, industry in ETF_NAME_INDUSTRY_MAP.items():
                if etf_name in name:
                    return industry
        except ImportError:
            pass

        # 扩展的关键词→板块映射（按优先级排列，长关键词优先）
        sector_map = [
            # 宽基指数
            ("上证指数", "宽基-A股"), ("深证成指", "宽基-A股"), ("沪深300", "宽基-A股"),
            ("中证500", "宽基-A股"), ("中证1000", "宽基-A股"), ("创业板", "宽基-A股"),
            ("科创50", "宽基-A股"), ("科创板", "宽基-A股"), ("A50", "宽基-A股"),
            ("恒生", "宽基-港股"), ("H股", "宽基-港股"), ("港股通", "宽基-港股"),
            # 海外
            ("纳指", "海外"), ("纳斯达克", "海外"), ("标普", "海外"), ("道琼斯", "海外"),
            ("日经", "海外"), ("德国", "海外"), ("印度", "海外"), ("越南", "海外"),
            ("中概互联", "海外-中概"), ("中国互联", "海外-中概"),
            # 行业ETF
            ("医药", "医药生物"), ("医疗", "医药生物"), ("创新药", "医药生物"), ("生物医药", "医药生物"),
            ("消费", "消费"), ("食品", "消费"), ("白酒", "消费"), ("饮料", "消费"),
            ("科技", "科技"), ("人工智能", "科技"), ("AI", "科技"), ("5G", "科技"),
            ("半导体", "半导体"), ("芯片", "半导体"),
            ("新能源", "新能源"), ("光伏", "新能源"), ("锂电", "新能源"), ("绿电", "新能源"),
            ("证券", "金融-证券"), ("券商", "金融-证券"),
            ("银行", "金融-银行"),
            ("保险", "金融-保险"),
            ("金融", "金融"),
            ("军工", "军工"), ("国防", "军工"),
            ("有色", "有色"), ("黄金", "贵金属"), ("稀土", "有色"), ("矿产", "有色"),
            ("煤炭", "能源"), ("能源", "能源"), ("石油", "能源"), ("电力", "公用事业"),
            ("地产", "房地产"), ("房地产", "房地产"),
            ("农业", "农业"), ("畜牧", "农业"), ("养殖", "农业"),
            ("传媒", "传媒"), ("游戏", "传媒"), ("影视", "传媒"),
            ("汽车", "汽车"), ("新能源车", "汽车"),
            # 策略/风格ETF
            ("红利", "红利"), ("高股息", "红利"), ("低波", "红利"),
            ("债券", "债券"), ("国债", "债券"), ("转债", "债券"), ("信用债", "债券"),
            ("城投债", "债券"), ("地方债", "债券"), ("政金债", "债券"),
            # 商品
            ("豆粕", "商品"), ("原油", "商品"), ("有色", "商品"),
        ]
        for kw, sector in sector_map:
            if kw in name:
                return sector
        return "其他"

    _etf_volume_cache: Dict[str, float] = {}

    def _get_etf_volume(self, code: str) -> float:
        """获取ETF的日均成交额（万元），用于流动性比较。"""
        if code in self._etf_volume_cache:
            return self._etf_volume_cache[code]

        pure_code = code.split(".")[0]
        try:
            df = self._call_ak_with_retry(ak.fund_etf_category_sina, symbol="ETF基金", max_retries=1)
            if df is not None and not df.empty:
                for try_code in [f"sz{pure_code}", f"sh{pure_code}", pure_code]:
                    row = df[df["代码"] == try_code]
                    if not row.empty and "成交额" in df.columns:
                        try:
                            vol = float(row.iloc[0]["成交额"]) / 10000  # 元→万元
                            self._etf_volume_cache[code] = vol
                            return vol
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
        return 0.0

    MONEY_MARKET_ETF_KEYWORDS = [
        "银华日利", "华宝添益", "货币", "添益", "日利", "理财金", "保证金",
        "建信添益", "易方达货币", "博时货币", "南方理财", "招商快线", "国寿货币",
        "广发货币", "华夏货币", "富国货币", "天弘货币", "汇添富货币",
        "短融", "场内货币", "交易货币", "融通货币", "嘉实货币", "工银货币",
        "鹏华货币", "景顺货币", "鑫元货币", "国泰货币", "海富通货币",
        "债券ETF", "国债ETF", "城投债", "转债ETF", "可转债", "地方债", "政金债",
        "国开债", "农发债", "口行债", "利率债", "信用债", "公司债", "中期票据",
    ]

    def _generate_curated_picks(self, ranked: List[Dict]) -> Dict:
        """生成精选名单：top股票 + 板块去重后的最优ETF（保留流动性最高的）"""
        stocks = [r for r in ranked if r.get("market") != "ETF"]
        etfs = [r for r in ranked if r.get("market") == "ETF"]

        # --- 股票精选：评分最高的20只（至少推荐以上） ---
        top_stocks = [s for s in stocks if s.get("rating") in ("强烈推荐", "推荐")][:20]

        # --- ETF精选：按板块去重，每个板块只保留流动性最高的 ---
        # 先过滤掉货币/理财/债券类ETF（不属于底部资产投资范畴）
        etfs = [e for e in etfs if not any(
            kw in e.get("name", "") for kw in self.MONEY_MARKET_ETF_KEYWORDS
        )]

        # 给每只ETF分配板块并获取流动性
        etf_with_sector = []
        for e in etfs:
            name = e.get("name", "")
            sector = self._assign_etf_sector(name)
            volume = self._get_etf_volume(e.get("code", ""))
            e["etf_sector"] = sector
            e["etf_volume"] = volume
            etf_with_sector.append(e)

        # 按 sector 分组，每组保留 volume 最高的那只
        sector_best: Dict[str, Dict] = {}
        for e in etf_with_sector:
            sector = e["etf_sector"]
            if sector not in sector_best or e["etf_volume"] > sector_best[sector]["etf_volume"]:
                sector_best[sector] = e

        # 按评分排序
        curated_etfs = sorted(sector_best.values(), key=lambda x: x.get("composite_score", 0), reverse=True)

        return {
            "top_stocks": top_stocks,
            "curated_etfs": curated_etfs,
            "total_sectors": len(sector_best),
        }

    # ================================================================
    # Step 2.5b: 基本面数据 enrichment
    # ================================================================

    def _enrich_fundamentals(self, candidates: List[Dict]) -> List[Dict]:
        """为候选资产补全基本面数据。

        A股：调用 ak.stock_financial_abstract 提取营收/利润趋势、ROE、资产负债率
        港股：调用 ak.stock_financial_hk_analysis_indicator_em 提取基本面指标
        ETF：跳过
        """
        enriched = 0
        for i, c in enumerate(candidates):
            if c.get("market") == "ETF":
                c["revenue_trend"] = "N/A"
                c["profit_trend"] = "N/A"
                c["roe_latest"] = None
                c["debt_ratio"] = None
                continue

            code = c["code"]
            cache_key = f"fund_{code}"
            if cache_key in self._fundamentals_cache:
                cached = self._fundamentals_cache[cache_key]
                for k, v in cached.items():
                    c[k] = v
                enriched += 1
                continue

            if i % 100 == 0 and i > 0:
                print(f"    基本面进度: {i}/{len(candidates)}")

            try:
                if c.get("market") == "港股":
                    fund_data = self._get_hk_fundamentals(code)
                else:
                    fund_data = self._get_a_share_fundamentals(code)
            except Exception:
                fund_data = {"revenue_trend": "未知", "profit_trend": "未知",
                             "roe_latest": None, "debt_ratio": None}

            for k, v in fund_data.items():
                c[k] = v
            self._fundamentals_cache[cache_key] = fund_data
            enriched += 1

            time.sleep(0.15)

        print(f"    基本面数据补全: {enriched}/{len(candidates)} 只")
        self._save_cache()
        return candidates

    def _get_a_share_fundamentals(self, code: str) -> Dict:
        """获取A股基本面数据"""
        pure_code = code.split(".")[0]
        result = {"revenue_trend": "未知", "profit_trend": "未知",
                  "roe_latest": None, "debt_ratio": None}

        try:
            df = self._call_ak_with_retry(
                ak.stock_financial_abstract, symbol=pure_code, max_retries=1
            )
            if df is None or df.empty:
                return result

            # df 行是指标名，列是报告期（如"20260331"）
            indicator_col = df.columns[0]
            df_indexed = df.set_index(indicator_col) if indicator_col in df.columns else df

            # 提取最近3期的营收和净利润
            for indicator_name in ["营业总收入", "营业收入", "营业总收入(万元)", "营业收入(万元)"]:
                if indicator_name in df_indexed.index:
                    row = df_indexed.loc[indicator_name]
                    result["revenue_trend"] = self._calc_trend(row)
                    break

            for indicator_name in ["归母净利润", "净利润", "净利润(万元)", "归属于母公司所有者的净利润"]:
                if indicator_name in df_indexed.index:
                    row = df_indexed.loc[indicator_name]
                    result["profit_trend"] = self._calc_trend(row)
                    break

            if "净资产收益率" in df_indexed.index:
                row = df_indexed.loc["净资产收益率"]
                vals = pd.to_numeric(row, errors="coerce").dropna()
                if len(vals) > 0:
                    result["roe_latest"] = round(float(vals.iloc[0]), 2)

            if "资产负债率" in df_indexed.index:
                row = df_indexed.loc["资产负债率"]
                vals = pd.to_numeric(row, errors="coerce").dropna()
                if len(vals) > 0:
                    result["debt_ratio"] = round(float(vals.iloc[0]), 2)

        except Exception:
            pass
        return result

    def _get_hk_fundamentals(self, code: str) -> Dict:
        """获取港股基本面数据"""
        pure_code = code.split(".")[0].zfill(5)  # analysis_indicator_em 需 5 位补零
        result = {"revenue_trend": "未知", "profit_trend": "未知",
                  "roe_latest": None, "debt_ratio": None}

        try:
            # stock_financial_hk_analysis_indicator_em：旧 stock_hk_financial_indicator
            # 在 akshare≥1.16 已不存在，导致港股基本面长期拿不到。
            df = self._call_ak_with_retry(
                ak.stock_financial_hk_analysis_indicator_em, symbol=pure_code, max_retries=1
            )
            if df is None or df.empty:
                return result

            # ROE（ROE_AVG，序列最近在前）
            for col in ["ROE_AVG", "ROE_YEARLY"]:
                if col in df.columns:
                    vals = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(vals) > 0:
                        result["roe_latest"] = round(float(vals.iloc[0]), 2)
                    break

            # 资产负债率（DEBT_ASSET_RATIO）
            if "DEBT_ASSET_RATIO" in df.columns:
                vals = pd.to_numeric(df["DEBT_ASSET_RATIO"], errors="coerce").dropna()
                if len(vals) > 0:
                    result["debt_ratio"] = round(float(vals.iloc[0]), 2)

            # 营收/利润趋势（绝对值序列，最近在前，与 _calc_trend 约定一致）
            for col, key in [("OPERATE_INCOME", "revenue_trend"), ("HOLDER_PROFIT", "profit_trend")]:
                if col in df.columns:
                    vals = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(vals) >= 2:
                        result[key] = self._calc_trend(vals)

        except Exception:
            pass
        return result

    def _calc_trend(self, series) -> str:
        """从数值序列计算趋势标签"""
        vals = pd.to_numeric(series, errors="coerce").dropna()
        if len(vals) < 3:
            if len(vals) >= 2:
                return "改善" if vals.iloc[0] > vals.iloc[-1] else "恶化"
            return "未知"
        recent = vals.iloc[:3]
        if len(recent) < 3:
            return "未知"
        changes = []
        for j in range(len(recent) - 1):
            if recent.iloc[j + 1] == 0:
                changes.append(0)
            else:
                changes.append((recent.iloc[j] - recent.iloc[j + 1]) / abs(recent.iloc[j + 1]))
        avg_change = sum(changes) / len(changes)
        if avg_change > 0.15:
            return "大幅增长"
        elif avg_change > 0.05:
            return "增长"
        elif avg_change > -0.05:
            return "稳定"
        elif avg_change > -0.15:
            return "下滑"
        else:
            return "大幅下滑"

    # ================================================================
    # Step 3a: 行业需求验证
    # ================================================================

    def _filter_demand(self, candidates: List[Dict]) -> List[Dict]:
        """行业需求验证。LLM模式下按行业批量调用，避免逐只调用。"""
        passed = []

        # 收集所有行业
        industries = set(c.get("industry", "") for c in candidates if c.get("industry"))
        unknown = [c for c in candidates if not c.get("industry")]

        # 对无行业信息的谨慎处理（score=3 而非默认通过）
        for c in unknown:
            c["demand_score"] = 3
            c["demand_reason"] = "无行业信息，保守评分"
            passed.append(c)

        # 按行业批量LLM验证（如果启用）
        industry_status = {}
        if self.use_llm and self.llm_client and self.llm_client.is_available():
            print(f"     LLM批量验证 {len(industries)} 个行业...")
            for i, industry in enumerate(sorted(industries)):
                if i % 20 == 0:
                    print(f"       行业进度: {i}/{len(industries)}")
                try:
                    prompt = INDUSTRY_DEMAND_PROMPT.format(
                        industry=industry, stock_name="", stock_code=""
                    )
                    response = self.llm_client.chat(
                        system_prompt="你是一位资深行业分析师，请用JSON格式回复。",
                        user_prompt=prompt,
                    )
                    result = self._parse_json_response(response)
                    industry_status[industry] = result
                except Exception as e:
                    if i < 3:  # 只有前3个错误才打印
                        print(f"      LLM验证失败({industry}): {e}")

        # 按行业结果筛选
        for c in [c for c in candidates if c.get("industry")]:
            industry = c.get("industry", "")
            if industry in industry_status:
                result = industry_status[industry]
                if result.get("demand_status") != "永久萎缩":
                    c["demand_score"] = result.get("score", 5)
                    c["demand_reason"] = result.get("reason", "")
                    passed.append(c)
                    continue
                # 永久萎缩的不通过（不加入passed）
            elif not self._is_industry_declining(industry):
                c["demand_score"] = 5
                c["demand_reason"] = "规则判断：行业非永久萎缩"
                passed.append(c)

        print(f"     (其中LLM验证 {len(industry_status)} 个行业, 规则判断 {len(industries) - len(industry_status)} 个)")
        return passed

    def _check_industry_demand_llm(self, candidate: Dict) -> Dict:
        prompt = INDUSTRY_DEMAND_PROMPT.format(
            industry=candidate.get("industry", "未知"),
            stock_name=candidate.get("name", ""),
            stock_code=candidate.get("code", ""),
        )
        response = self.llm_client.chat(
            system_prompt="你是一位资深行业分析师，请用JSON格式回复。",
            user_prompt=prompt,
        )
        return self._parse_json_response(response)

    def _is_industry_declining(self, industry: str) -> bool:
        return any(kw in industry for kw in DECLINING_INDUSTRY_KEYWORDS)

    # ================================================================
    # Step 3b: 估值低位验证
    # ================================================================

    def _filter_valuation(self, candidates: List[Dict]) -> List[Dict]:
        """估值低位验证 + 基础基本面检查"""
        passed = []
        for c in candidates:
            # 基本面排除：资产负债率>85%且利润持续恶化
            debt = c.get("debt_ratio")
            profit_trend = c.get("profit_trend", "")
            roe = c.get("roe_latest")
            if debt is not None and debt > 85 and profit_trend in ("大幅下滑", "恶化"):
                continue  # 高杠杆+利润恶化 = 价值陷阱，排除

            # ROE连续为负且无改善迹象
            if roe is not None and roe < 0 and profit_trend in ("大幅下滑", "恶化", "下滑"):
                continue

            pe_percentile = self._get_pe_percentile(c["code"])
            if pe_percentile is not None:
                c["pe_percentile"] = pe_percentile
                if pe_percentile >= 70:
                    continue

            dv = self._get_dividend_yield(c["code"])
            if dv is not None:
                c["dividend_yield"] = dv

            passed.append(c)
        return passed

    def _get_pe_percentile(self, code: str, years: int = 10) -> Optional[float]:
        """用价格分位数近似PE分位数"""
        try:
            pure_code = code.split(".")[0]
            if code.endswith(".HK"):
                df = self._call_ak_with_retry(
                    ak.stock_hk_daily, symbol=pure_code, adjust="qfq", max_retries=1
                )
                date_col = "date"
                close_col = "close"
            else:
                if code.endswith(".SH"):
                    ak_sym = f"sh{pure_code}"
                elif code.endswith(".SZ"):
                    ak_sym = f"sz{pure_code}"
                else:
                    ak_sym = f"sh{pure_code}"
                df = self._call_ak_with_retry(
                    ak.stock_zh_a_daily, symbol=ak_sym, adjust="qfq", max_retries=1
                )
                date_col = "date"
                close_col = "close"

            if df is None or df.empty:
                return None

            # 统一列名
            if date_col not in df.columns:
                date_col = "日期"
            if close_col not in df.columns:
                close_col = "收盘"

            df[date_col] = pd.to_datetime(df[date_col])
            cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
            recent = df[df[date_col] >= cutoff]
            if recent.empty:
                return None

            current_close = float(recent.iloc[-1][close_col])
            percentile = (recent[close_col] < current_close).mean() * 100
            return round(float(percentile), 1)
        except Exception:
            return None

    def _get_dividend_yield(self, code: str) -> Optional[float]:
        try:
            pure_code = code.split(".")[0]
            if code.endswith(".HK"):
                return self._get_hk_dividend_yield(pure_code)
            df = self._call_ak_with_retry(
                ak.stock_financial_abstract, symbol=pure_code, max_retries=1
            )

            if df is None or df.empty:
                return None

            for col in ["股息率", "dividend_yield", "股息率(%)"]:
                if col in df.columns:
                    val = df.iloc[0][col]
                    if val and not pd.isna(val):
                        return float(val)
            return None
        except Exception:
            return None

    def _get_hk_dividend_yield(self, pure_code: str) -> Optional[float]:
        """港股股息率TTM：fhpx 近1年分红 ÷ stock_hk_daily 最新收盘。

        旧 stock_hk_financial_indicator 在 akshare≥1.16 不存在，导致港股股息率拿不到。
        """
        import re
        from datetime import datetime, timedelta
        try:
            code5 = pure_code.zfill(5)
            hk_code_4 = code5[1:] if code5[0] == "0" else code5  # 同花顺用 4 位
            df = self._call_ak_with_retry(ak.stock_hk_fhpx_detail_ths, symbol=hk_code_4, max_retries=1)
            if df is None or len(df) == 0:
                return None
            completed = df[df["进度"] == "实施完成"] if "进度" in df.columns else df
            ex_dates = []
            for _, row in completed.iterrows():
                ex_date = str(row.get("除净日", ""))
                if not ex_date or ex_date in ("NaT", "nan"):
                    continue
                try:
                    ex_dt = datetime.strptime(ex_date[:10], "%Y-%m-%d")
                except ValueError:
                    continue
                plan = str(row.get("方案", ""))
                m = re.search(r"每股[^\d]*([\d.]+)", plan)
                if not m:
                    continue
                amount = float(m.group(1))
                if "美元" in plan:
                    amount *= 7.8  # USD/HKD 联系汇率
                ex_dates.append((ex_dt, amount))
            if not ex_dates:
                return None
            ex_dates.sort(key=lambda x: x[0], reverse=True)
            cutoff = ex_dates[0][0] - timedelta(days=365)
            total_div = sum(a for d, a in ex_dates if d >= cutoff)
            if total_div <= 0:
                return None
            # 现价：stock_hk_daily 最新收盘
            hist = self._call_ak_with_retry(ak.stock_hk_daily, symbol=code5, adjust="qfq", max_retries=1)
            if hist is None or getattr(hist, "empty", True):
                return None
            price = hist.iloc[-1]["close"]
            if not price or float(price) <= 0:
                return None
            yield_pct = round(total_div / float(price) * 100, 2)
            return yield_pct if 0 < yield_pct <= 15 else None
        except Exception:
            return None
        except Exception:
            return None

    # ================================================================
    # Step 3c: 催化因素验证
    # ================================================================

    def _filter_catalyst(self, candidates: List[Dict]) -> List[Dict]:
        """催化因素验证。LLM模式下按行业批量调用，避免逐只调用。"""
        passed = []

        # 收集所有行业
        industries = set(c.get("industry", "") for c in candidates if c.get("industry"))
        unknown = [c for c in candidates if not c.get("industry")]

        # 对无行业信息的默认评分
        for c in unknown:
            c["catalyst_score"] = 5
            c["catalyst_factors"] = ["宏观降息周期"]
            c["catalyst_timing"] = "不确定"
            c["catalyst_reason"] = "无行业信息，默认评分"
            passed.append(c)

        # 按行业批量LLM验证（如果启用）
        industry_status = {}
        if self.use_llm and self.llm_client and self.llm_client.is_available():
            print(f"     LLM批量验证 {len(industries)} 个行业的催化因素...")
            for i, industry in enumerate(sorted(industries)):
                if i % 20 == 0:
                    print(f"       行业进度: {i}/{len(industries)}")
                try:
                    prompt = INDUSTRY_CATALYST_PROMPT.format(industry=industry)
                    response = self.llm_client.chat(
                        system_prompt="你是一位宏观策略分析师，请用JSON格式回复。",
                        user_prompt=prompt,
                    )
                    result = self._parse_json_response(response)
                    industry_status[industry] = result
                except Exception as e:
                    if i < 3:
                        print(f"      LLM验证失败({industry}): {e}")

        # 按行业结果评分
        for c in [c for c in candidates if c.get("industry")]:
            industry = c.get("industry", "")
            if industry in industry_status:
                result = industry_status[industry]
                c["catalyst_score"] = result.get("catalyst_score", 5)
                c["catalyst_factors"] = result.get("catalyst_factors", ["宏观降息周期"])
                c["catalyst_timing"] = result.get("timing", "不确定")
                c["catalyst_reason"] = result.get("reason", "")
            else:
                c["catalyst_score"] = 5
                c["catalyst_factors"] = ["宏观降息周期"]
                c["catalyst_timing"] = "不确定"
                c["catalyst_reason"] = "规则判断：宏观降息周期利好底部资产"
            passed.append(c)

        print(f"     (其中LLM验证 {len(industry_status)} 个行业, 规则判断 {len(industries) - len(industry_status)} 个)")
        return passed

    def _check_catalyst_llm(self, candidate: Dict) -> Dict:
        prompt = CATALYST_PROMPT.format(
            stock_name=candidate.get("name", ""),
            stock_code=candidate.get("code", ""),
            industry=candidate.get("industry", "未知"),
            gain_pct=candidate.get("gain_pct", 0),
        )
        response = self.llm_client.chat(
            system_prompt="你是一位宏观策略分析师，请用JSON格式回复。",
            user_prompt=prompt,
        )
        return self._parse_json_response(response)

    # ================================================================
    # Step 4: 三重排除
    # ================================================================

    def _exclude_false_opportunities(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        final = []
        excluded = []
        for c in candidates:
            issue = self._check_liquidity_exclusion(c)
            if issue:
                c["exclude_reason"] = issue
                c["exclude_category"] = "流动性"
                excluded.append(c)
                continue

            issue = self._check_policy_exclusion(c)
            if issue:
                c["exclude_reason"] = issue
                c["exclude_category"] = "政策强压"
                excluded.append(c)
                continue

            issue = self._check_tech_exclusion(c)
            if issue:
                c["exclude_reason"] = issue
                c["exclude_category"] = "技术替代"
                excluded.append(c)
                continue

            final.append(c)
        return final, excluded

    def _check_liquidity_exclusion(self, candidate: Dict) -> Optional[str]:
        code = candidate.get("code", "")
        name = candidate.get("name", "")
        if "ST" in name or "*ST" in name:
            return "ST/*ST股，流动性风险"
        if "退" in name:
            return "退市风险股"

        daily_volume = self._get_daily_volume(code)
        if daily_volume is not None:
            if code.endswith(".HK"):
                if daily_volume < EXCLUSION_RULES["liquidity"]["min_daily_volume_hk"]:
                    return f"港股日均成交额不足({daily_volume/1e8:.1f}亿)"
            else:
                if daily_volume < EXCLUSION_RULES["liquidity"]["min_daily_volume_a"]:
                    return f"A股日均成交额不足({daily_volume/1e8:.1f}亿)"
        return None

    def _check_policy_exclusion(self, candidate: Dict) -> Optional[str]:
        industry = candidate.get("industry", "")
        name = candidate.get("name", "")
        for policy_cat, keywords in POLICY_SUPPRESSED_KEYWORDS.items():
            for kw in keywords:
                if kw in industry or kw in name:
                    return f"政策强压行业: {policy_cat}"
        return None

    def _check_tech_exclusion(self, candidate: Dict) -> Optional[str]:
        industry = candidate.get("industry", "")
        name = candidate.get("name", "")
        for tech_cat, keywords in TECH_REPLACED_KEYWORDS.items():
            for kw in keywords:
                if kw in industry or kw in name:
                    return f"技术替代明确: {tech_cat}"
        return None

    def _get_daily_volume(self, code: str) -> Optional[float]:
        try:
            pure_code = code.split(".")[0]
            if code.endswith(".HK"):
                df = self._call_ak_with_retry(
                    ak.stock_hk_daily, symbol=pure_code, adjust="", max_retries=1
                )
                date_col, vol_col, close_col, amt_col = "date", "volume", "close", "amount"
            else:
                if code.endswith(".SH"):
                    ak_sym = f"sh{pure_code}"
                elif code.endswith(".SZ"):
                    ak_sym = f"sz{pure_code}"
                else:
                    ak_sym = f"sh{pure_code}"
                df = self._call_ak_with_retry(
                    ak.stock_zh_a_daily, symbol=ak_sym, adjust="", max_retries=1
                )
                date_col, vol_col, close_col, amt_col = "date", "volume", "close", "amount"

            if df is None or df.empty:
                return None

            # 统一列名
            if vol_col not in df.columns:
                vol_col = "成交量"
            if close_col not in df.columns:
                close_col = "收盘"
            if amt_col not in df.columns:
                amt_col = "成交额"

            recent = df.tail(20)
            if amt_col in df.columns:
                return float(recent[amt_col].mean())
            elif vol_col in df.columns:
                avg_vol = recent[vol_col].mean()
                close = recent[close_col].mean()
                return float(avg_vol * close)
        except Exception:
            pass
        return None

    # ================================================================
    # Step 3+4 (LLM模式): 统一评估（替代三重筛选+三重排除）
    # ================================================================

    def _llm_batch_evaluate(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """使用LLM统一评估所有候选资产，一次性完成筛选+排除+评分。

        分批处理：每批最多300只，避免单次调用token溢出。
        """
        batch_size = 30  # 每批30只，留足token余量防止截断
        all_passed = []
        all_excluded = []

        for batch_start in range(0, len(candidates), batch_size):
            batch = candidates[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (len(candidates) + batch_size - 1) // batch_size
            print(f"  LLM评估批次 {batch_num}/{total_batches} ({len(batch)} 只)...")

            # 构建候选资产摘要
            assets_summary = self._build_assets_summary(batch)
            user_prompt = f"以下是{len(batch)}只候选底部资产的数据，请逐一评估：\n\n```json\n{json.dumps(assets_summary, ensure_ascii=False, indent=2)}\n```"

            try:
                response = self.llm_client.chat(
                    system_prompt=BATCH_EVALUATION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=32000,
                )
                result = self._parse_batch_response(response)
            except Exception as e:
                print(f"    批次 {batch_num} LLM调用失败: {e}，该批次回退到规则")
                bp, be = self._fallback_rule_evaluate(batch)
                all_passed.extend(bp)
                all_excluded.extend(be)
                continue

            if not result or "evaluations" not in result:
                print(f"    批次 {batch_num} LLM返回解析失败 (长度: {len(response)})，该批次回退到规则")
                bp, be = self._fallback_rule_evaluate(batch)
                all_passed.extend(bp)
                all_excluded.extend(be)
                continue

            # 应用评估结果
            passed, excluded = self._apply_llm_evaluations(batch, result["evaluations"])
            all_passed.extend(passed)
            all_excluded.extend(excluded)
            print(f"    批次 {batch_num}: 通过 {len(passed)}, 排除 {len(excluded)}")

        return all_passed, all_excluded

    def _build_assets_summary(self, candidates: List[Dict]) -> List[Dict]:
        """构建候选资产摘要（发送给LLM的精简格式）"""
        summary = []
        for c in candidates:
            summary.append({
                "code": c.get("code", ""),
                "name": c.get("name", ""),
                "market": c.get("market", ""),
                "industry": c.get("industry", ""),
                "gain_pct": c.get("gain_pct", 0),
                "price_2019": c.get("price_2019", 0),
                "price_now": c.get("price_now", 0),
                "revenue_trend": c.get("revenue_trend", "未知"),
                "profit_trend": c.get("profit_trend", "未知"),
                "roe": c.get("roe_latest"),
                "debt_ratio": c.get("debt_ratio"),
                "pe_percentile": c.get("pe_percentile"),
                "dividend_yield": c.get("dividend_yield"),
            })
        return summary

    def _repair_json_text(self, text: str) -> str:
        """修复常见的LLM JSON格式错误：控制字符、尾随逗号、省略号等。"""
        # 1. 移除JSON中不允许的控制字符（保留 \n \r \t）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        # 2. 移除尾随逗号（对象和数组中）：,"  → "   ,}  → }   ,]  → ]
        text = re.sub(r',\s*(")', r'\1', text)  # ," → " (下个元素是字符串)
        text = re.sub(r',\s*(})', r'\1', text)   # ,} → }
        text = re.sub(r',\s*(\])', r'\1', text)  # ,] → ]
        # 3. 移除 ... 省略号占位（LLM有时会加）
        text = re.sub(r'"\.\.\."', '""', text)
        text = re.sub(r'\.\.\.', '', text)
        return text

    def _parse_batch_response(self, response: str) -> Dict:
        """解析LLM批量评估响应，处理多种格式。"""
        if not response:
            return {}
        clean = response.strip()
        errors = []  # 收集各策略的错误信息用于诊断

        def try_parse(text: str) -> Dict:
            """尝试多种方式解析JSON文本"""
            # 直接解析
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            # 修复后直接解析
            try:
                return json.loads(self._repair_json_text(text))
            except json.JSONDecodeError:
                pass
            # bracket-depth 提取
            result = self._extract_json_by_depth(text)
            if result and "evaluations" in result:
                return result
            # raw_decode
            result = self._raw_decode_json(text)
            if result and "evaluations" in result:
                return result
            # 修复截断
            result = self._fix_truncated_json(text)
            if result and "evaluations" in result:
                return result
            return {}

        # 方式1：直接解析全文
        result = try_parse(clean)
        if result and "evaluations" in result:
            return result

        # 方式2：提取 ```json ... ``` 代码块
        block_start_m = re.search(r'```(?:json)?\s*\n?', clean)
        if block_start_m:
            content_start = block_start_m.end()
            block_end = clean.rfind('```')
            if block_end > content_start:
                inner = clean[content_start:block_end].strip()
                result = try_parse(inner)
                if result and "evaluations" in result:
                    return result

        # 诊断输出
        print(f"    [解析诊断] 所有策略失败，响应长度: {len(response)}, 有代码块: {'```' in response}")
        print(f"    响应前200字符: {response[:200]}")

        return {}

    def _extract_json_by_depth(self, text: str) -> Dict:
        """通过跟踪括号深度提取最外层JSON对象（处理字符串内的括号和转义）。"""
        start = text.find('{')
        if start < 0:
            return {}
        depth = 0
        in_string = False
        escape_next = False
        end = -1
        for j in range(start, len(text)):
            ch = text[j]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {}

    def _raw_decode_json(self, text: str) -> Dict:
        """使用 raw_decode 解析JSON，自动跳过尾部无关内容。"""
        try:
            decoder = json.JSONDecoder()
            result, _ = decoder.raw_decode(text)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            # 尝试跳过 ```json 前缀
            m = re.search(r'```(?:json)?\s*\n?', text)
            if m:
                try:
                    decoder = json.JSONDecoder()
                    result, _ = decoder.raw_decode(text[m.end():])
                    return result if isinstance(result, dict) else {}
                except json.JSONDecodeError:
                    pass
        return {}

    def _fix_truncated_json(self, text: str) -> Dict:
        """尝试修复被截断的JSON：补齐缺失的 } ] 和字符串引号。"""
        # 先提取 ```json 代码块内容
        m = re.search(r'```(?:json)?\s*\n?(.*?)$', text, re.DOTALL)
        if m:
            content = m.group(1).strip()
        else:
            content = text.strip()

        # 找到第一个 {
        start = content.find('{')
        if start < 0:
            return {}
        content = content[start:]

        # 追踪括号深度，找到截断位置
        depth_brace = 0
        depth_bracket = 0
        in_string = False
        escape_next = False
        last_valid = 0
        for i, ch in enumerate(content):
            if escape_next:
                escape_next = False
                last_valid = i + 1
                continue
            if ch == '\\':
                escape_next = True
                last_valid = i + 1
                continue
            if ch == '"':
                in_string = not in_string
                last_valid = i + 1
                continue
            if in_string:
                last_valid = i + 1
                continue
            if ch == '{':
                depth_brace += 1
            elif ch == '}':
                depth_brace -= 1
            elif ch == '[':
                depth_bracket += 1
            elif ch == ']':
                depth_bracket -= 1
            if depth_brace >= 0:
                last_valid = i + 1

        # 如果截断在字符串中间，去掉不完整的字符串
        fixed = content[:last_valid]
        if in_string:
            fixed = fixed + '"'

        # 补齐缺失的括号
        fixed = fixed + ']' * depth_bracket + '}' * depth_brace

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {}

    def _apply_llm_evaluations(self, candidates: List[Dict], evaluations: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """将LLM评估结果应用到候选资产上"""
        passed = []
        excluded = []
        eval_map = {e.get("code", ""): e for e in evaluations}

        for c in candidates:
            code = c.get("code", "")
            ev = eval_map.get(code, {})

            if not ev:
                # LLM未返回此代码的评估，默认通过并给中性分
                c["demand_score"] = 5
                c["catalyst_score"] = 5
                c["catalyst_factors"] = ["宏观降息周期"]
                c["catalyst_timing"] = "不确定"
                passed.append(c)
                continue

            status = ev.get("status", "passed")
            if status == "excluded":
                c["exclude_reason"] = ev.get("exclude_reason", "LLM判断排除")
                c["exclude_category"] = ev.get("exclude_category", "综合")
                excluded.append(c)
            else:
                scores = ev.get("scores", {})
                c["demand_score"] = scores.get("industry_momentum", 5)
                c["catalyst_score"] = scores.get("catalyst", 5)
                c["catalyst_factors"] = ev.get("catalyst_factors", [])
                c["catalyst_timing"] = ev.get("timing", "不确定")
                c["catalyst_reason"] = ev.get("analysis", "")
                # 保存LLM评分用于后续 composite scoring
                c["llm_price_score"] = scores.get("price_gap")
                c["llm_val_score"] = scores.get("valuation_safety")
                c["llm_catalyst_score"] = scores.get("catalyst")
                c["llm_demand_score"] = scores.get("industry_momentum")
                c["llm_analysis"] = ev.get("analysis", "")
                passed.append(c)

        return passed, excluded

    def _fallback_rule_evaluate(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """LLM不可用时的规则回退"""
        print("    使用规则筛选模式...")
        passed = self._filter_demand(candidates)
        passed = self._filter_valuation(passed)
        passed = self._filter_catalyst(passed)
        return self._exclude_false_opportunities(passed)

    # ================================================================
    # Step 5: 多维评分排序
    # ================================================================

    def _score_and_rank(self, candidates: List[Dict]) -> List[Dict]:
        for c in candidates:
            # 优先使用LLM评分，否则使用规则评分
            if "llm_price_score" in c and c["llm_price_score"] is not None:
                price_score = c["llm_price_score"]
                val_score = c.get("llm_val_score", 5)
                catalyst_score = c.get("llm_catalyst_score", 5)
                demand_score = c.get("llm_demand_score", 5)
            else:
                gain_pct = c.get("gain_pct", 0)
                if gain_pct < -20:
                    price_score = 10
                elif gain_pct < 0:
                    price_score = 8
                elif gain_pct < 30:
                    price_score = 6
                elif gain_pct < 50:
                    price_score = 4
                else:
                    price_score = 2

                pe_pct = c.get("pe_percentile")
                if pe_pct is not None:
                    if pe_pct < 10:
                        val_score = 10
                    elif pe_pct < 20:
                        val_score = 8
                    elif pe_pct < 30:
                        val_score = 6
                    elif pe_pct < 50:
                        val_score = 4
                    elif pe_pct < 70:
                        val_score = 2
                    else:
                        val_score = 0
                else:
                    val_score = 5

                catalyst_score = c.get("catalyst_score", 5)
                demand_score = c.get("demand_score", 5)

            composite = (
                price_score * BOTTOM_ASSET_WEIGHTS["price_gap"]
                + val_score * BOTTOM_ASSET_WEIGHTS["valuation_safety"]
                + catalyst_score * BOTTOM_ASSET_WEIGHTS["catalyst"]
                + demand_score * BOTTOM_ASSET_WEIGHTS["industry_momentum"]
            )

            c["price_score"] = price_score
            c["val_score"] = val_score
            c["composite_score"] = round(composite, 2)

            if composite >= 7:
                c["rating"] = "强烈推荐"
            elif composite >= 5:
                c["rating"] = "推荐"
            else:
                c["rating"] = "关注"

        candidates.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        return candidates

    # ================================================================
    # Step 6: 报告生成
    # ================================================================

    def _generate_report(self, ranked: List[Dict], excluded: List[Dict]) -> Path:
        date_str = datetime.now().strftime("%Y%m%d")
        report_path = self.tech_dir / f"周金涛底部资产筛选_{date_str}.md"

        lines = []
        lines.append("# 周金涛底部资产筛选报告\n")
        lines.append(f"> 基于周金涛2019年资产大底假设 | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

        # ---- 一、筛选概要 ----
        lines.append("## 一、筛选概要\n")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 通过筛选 | {len(ranked)} |")
        lines.append(f"| 排除伪机会 | {len(excluded)} |")
        lines.append(f"| 强烈推荐 | {len([r for r in ranked if r.get('rating') == '强烈推荐'])} |")
        lines.append(f"| 推荐 | {len([r for r in ranked if r.get('rating') == '推荐'])} |")
        lines.append(f"| 关注 | {len([r for r in ranked if r.get('rating') == '关注'])} |")
        lines.append("")

        # ---- 二、精选名单 ----
        curated = self._generate_curated_picks(ranked)
        lines.append("## 二、精选名单\n")
        lines.append("> 股票精选：评分最高的前20只 | ETF精选：同一板块仅保留流动性最优的1只，避免重复配置\n")

        # 2a. 精选股票
        lines.append("### 2.1 精选股票（Top 20）\n")
        lines.append("| 排名 | 代码 | 名称 | 市场 | 涨幅 | 评分 | 评级 | LLM分析 |")
        lines.append("|------|------|------|------|------|------|------|------|")
        for i, s in enumerate(curated["top_stocks"], 1):
            analysis = (s.get('llm_analysis', '') or '')[:80]
            lines.append(
                f"| {i} | {s.get('code','')} | {s.get('name','')} | {s.get('market','')} "
                f"| {s.get('gain_pct',0):.1f}% | {s.get('composite_score',0):.1f} "
                f"| {s.get('rating','')} | {analysis} |"
            )
        lines.append("")

        # 2b. 精选ETF（板块去重，每板块仅1只）
        lines.append(f"### 2.2 精选ETF（{curated['total_sectors']}个板块，每板块1只）\n")
        lines.append("| 板块 | 代码 | 名称 | 涨幅 | 评分 | 评级 | 日均成交额(万) | LLM分析 |")
        lines.append("|------|------|------|------|------|------|------|------|")
        for e in curated["curated_etfs"]:
            vol = e.get("etf_volume", 0) or 0
            analysis = (e.get('llm_analysis', '') or '')[:60]
            lines.append(
                f"| {e.get('etf_sector','')} | {e.get('code','')} | {e.get('name','')} "
                f"| {e.get('gain_pct',0):.1f}% | {e.get('composite_score',0):.1f} "
                f"| {e.get('rating','')} | {vol:.0f} | {analysis} |"
            )
        lines.append("")

        # ---- 三、全部资产名单 ----
        lines.append("## 三、全部资产名单（按综合评分排序）\n")
        lines.append("| 排名 | 代码 | 名称 | 市场 | 2019年价 | 当前价 | 涨幅 | 评分 | 评级 | 行业 | LLM分析 |")
        lines.append("|------|------|------|------|---------|--------|------|------|------|------|------|")
        for i, r in enumerate(ranked, 1):
            p19 = r.get('price_2019', 0) or 0
            pnow = r.get('price_now', 0) or 0
            analysis = (r.get('llm_analysis', '') or '')[:50]
            lines.append(
                f"| {i} | {r.get('code','')} | {r.get('name','')} | {r.get('market','')} "
                f"| {p19:.2f} | {pnow:.2f} "
                f"| {r.get('gain_pct',0):.1f}% | {r.get('composite_score',0):.1f} "
                f"| {r.get('rating','')} | {r.get('industry','')} | {analysis} |"
            )
        lines.append("")

        # ---- 四、风险提示 ----
        lines.append("## 四、风险提示\n")
        lines.append("1. 周金涛周期理论为宏观假设，非精确预测")
        lines.append("2. 底部资产可能长期维持低位（\"价值陷阱\"）")
        lines.append("3. 催化因素时间不确定")
        lines.append("4. 建议分批建仓，控制单标的仓位≤10%")
        lines.append("")

        write_text_with_retry(report_path, "\n".join(lines))
        return report_path

    # ================================================================
    # 自选股票池同步
    # ================================================================

    def _sync_stock_pool(self, a_stocks: List[Dict], hk_stocks: List[Dict], curated_etfs: List[Dict]) -> None:
        """同步所有筛选通过的个股和精选ETF到自选股票池。"""
        if not self.stock_pool_file.exists():
            print("  自选股票池文件不存在，跳过同步")
            return

        content = read_text_with_retry(self.stock_pool_file)

        marker = "## 周金涛底部资产"
        if marker in content:
            content = content[:content.index(marker)].rstrip()

        new_section = f"\n\n{marker}\n"
        new_section += "# 基于周金涛2019年资产大底假设筛选，相对2019年涨幅最小/价位更低的优质资产\n"
        new_section += "# 三重筛选：行业需求未永久萎缩 + 估值历史低位 + 催化因素明确\n"
        new_section += "# 三重排除：流动性陷阱 + 政策强压 + 技术替代\n"
        new_section += f"# 更新时间：{datetime.now().strftime('%Y-%m-%d')}（由 BottomAssetScreener 自动维护）\n#\n"

        if a_stocks:
            a_str = ", ".join(f'{a["code"]}({a["name"]})' for a in a_stocks)
            new_section += f"周金涛底部-A股: {a_str}\n"

        if hk_stocks:
            hk_str = ", ".join(f'{a["code"]}({a["name"]})' for a in hk_stocks)
            new_section += f"周金涛底部-港股: {hk_str}\n"

        if curated_etfs:
            etf_str = ", ".join(f'{e["code"]}({e["name"]})' for e in curated_etfs)
            new_section += f"周金涛底部-ETF: {etf_str}\n"

        write_text_with_retry(self.stock_pool_file, content + new_section)
        print(f"  已同步 {len(a_stocks) + len(hk_stocks)} 只个股 + {len(curated_etfs)} 只精选ETF 到自选股票池")

    # ================================================================
    # 缓存管理
    # ================================================================

    def _load_cache(self) -> Tuple[bool, Optional[List[Dict]]]:
        """加载所有磁盘缓存。返回 (是否有有效候选快照, 候选列表或None)。"""
        candidates = None
        has_valid_snapshot = False
        for cache_name, cache_info in CACHE_CONFIG.items():
            cache_path = self.cache_dir / cache_info["file"]
            if not cache_path.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
                if (datetime.now() - mtime).days < cache_info["ttl_days"]:
                    data = read_json_with_retry(cache_path)
                    if cache_name == "2019_bottom_price":
                        self._bottom_price_cache = data
                        print(f"  加载缓存: {cache_name} ({len(data)} 条)")
                    elif cache_name == "current_price":
                        self._current_price_cache = data
                        print(f"  加载缓存: {cache_name} ({len(data)} 条)")
                    elif cache_name == "candidates_snapshot":
                        candidates = data
                        has_valid_snapshot = True
                        print(f"  加载缓存: {cache_name} ({len(data)} 条)")
                    elif cache_name == "industry_data":
                        self._industry_cache = data
                        print(f"  加载缓存: {cache_name} ({len(data)} 条)")
                    elif cache_name == "fundamentals_data":
                        self._fundamentals_cache = data
                        print(f"  加载缓存: {cache_name} ({len(data)} 条)")
            except Exception as e:
                print(f"  缓存加载失败 {cache_name}: {e}")
        return has_valid_snapshot, candidates

    def _save_cache(self, candidates: Optional[List[Dict]] = None) -> None:
        for cache_name, cache_info in CACHE_CONFIG.items():
            if cache_name == "2019_bottom_price" and self._bottom_price_cache:
                data = self._bottom_price_cache
            elif cache_name == "current_price" and self._current_price_cache:
                data = self._current_price_cache
            elif cache_name == "candidates_snapshot" and candidates:
                data = candidates
            elif cache_name == "industry_data" and self._industry_cache:
                data = self._industry_cache
            elif cache_name == "fundamentals_data" and self._fundamentals_cache:
                data = self._fundamentals_cache
            else:
                continue
            cache_path = self.cache_dir / cache_info["file"]
            try:
                write_json_with_retry(cache_path, data)
            except Exception as e:
                print(f"  保存缓存失败 {cache_name}: {e}")

    # ================================================================
    # 工具方法
    # ================================================================

    def _parse_json_response(self, response: str) -> Dict:
        if not response:
            return {}
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        m = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {}

    def validate_config(self) -> bool:
        return True
