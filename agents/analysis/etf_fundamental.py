#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF行业基本面分析器
基于行业前景、政策支持、经典理论对ETF进行基本面评分
"""

import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

try:
    from core.llm_client import LLMClient
except ImportError:
    LLMClient = None


# 行业ETF基本面评分规则（基于经典理论）
# 每个行业包含：政策支持度、行业周期位置、成长性、防御性
INDUSTRY_FUNDAMENTAL_PROFILES = {
    "科技（AI与数字经济）": {
        "policy_support": 9,       # 政策大力支持
        "cycle_position": "成长期",  # 行业周期
        "growth": 9,               # 成长性
        "defensiveness": 3,        # 防御性
        "base_score": 8,
    },
    "半导体": {
        "policy_support": 9,
        "cycle_position": "成长期",
        "growth": 8,
        "defensiveness": 3,
        "base_score": 7,
    },
"新能源": {
    "policy_support": 8,
    "cycle_position": "成长期调整",
    "growth": 7,
    "defensiveness": 4,
    "base_score": 5,
},
"医药生物": {
    "policy_support": 7,
    "cycle_position": "成长期",
    "growth": 7,
    "defensiveness": 7,
    "base_score": 7,
},
    "消费电子": {
        "policy_support": 6,
        "cycle_position": "成熟期",
        "growth": 6,
        "defensiveness": 4,
        "base_score": 5,
    },
    "贵金属（黄金/铜）": {
        "policy_support": 5,
        "cycle_position": "繁荣期",
        "growth": 5,
        "defensiveness": 9,
        "base_score": 7,
    },
    "金融": {
        "policy_support": 6,
        "cycle_position": "复苏期",
        "growth": 4,
        "defensiveness": 7,
        "base_score": 5,
    },
    "证券": {
        "policy_support": 6,
        "cycle_position": "复苏期",
        "growth": 5,
        "defensiveness": 4,
        "base_score": 5,
    },
"高股息公用事业": {
    "policy_support": 7,
    "cycle_position": "成熟期",
    "growth": 3,
    "defensiveness": 9,
    "base_score": 6,
},
    "电力设备": {
        "policy_support": 8,
        "cycle_position": "成长期",
        "growth": 7,
        "defensiveness": 5,
        "base_score": 6,
    },
    "机器人": {
        "policy_support": 9,
        "cycle_position": "导入期",
        "growth": 9,
        "defensiveness": 2,
        "base_score": 7,
    },
"储能": {
    "policy_support": 8,
    "cycle_position": "成长期",
    "growth": 8,
    "defensiveness": 3,
    "base_score": 7,
},
"电网设备": {
    "policy_support": 8,
    "cycle_position": "成长期",
    "growth": 7,
    "defensiveness": 5,
    "base_score": 7,
},
    "绿电": {
        "policy_support": 8,
        "cycle_position": "成长期",
        "growth": 6,
        "defensiveness": 6,
        "base_score": 6,
    },
    "新能源车": {
        "policy_support": 9,
        "cycle_position": "成长期",
        "growth": 8,
        "defensiveness": 3,
        "base_score": 7,
    },
    "有色金属": {
        "policy_support": 6,
        "cycle_position": "复苏期",
        "growth": 6,
        "defensiveness": 4,
        "base_score": 5,
    },
"科创": {
    "policy_support": 9,
    "cycle_position": "成长期",
    "growth": 8,
    "defensiveness": 3,
    "base_score": 7,
},
"纳斯达克": {
    "policy_support": 5,
    "cycle_position": "成熟期",
    "growth": 7,
    "defensiveness": 4,
    "base_score": 6,
},
    "恒生科技": {
        "policy_support": 6,
        "cycle_position": "复苏期",
        "growth": 7,
        "defensiveness": 3,
        "base_score": 5,
    },
"红利": {
    "policy_support": 6,
    "cycle_position": "成熟期",
    "growth": 3,
    "defensiveness": 9,
    "base_score": 6,
},
"消费": {
    "policy_support": 6,
    "cycle_position": "复苏期",
    "growth": 5,
    "defensiveness": 6,
    "base_score": 5.5,
},
    "地产基建": {
        "policy_support": 5,
        "cycle_position": "调整期",
        "growth": 2,
        "defensiveness": 5,
        "base_score": 2,
    },
}

# ETF名称到行业的映射（常见ETF）
ETF_NAME_INDUSTRY_MAP = {
    # 证券类
    "证券ETF": "证券",
    "券商ETF": "证券",
    # 绿电类
    "绿电ETF": "绿电",
    # 科创类
    "科创50ETF": "科创",
    "科创ETF": "科创",
    # 电网设备类
    "电网设备ETF": "电网设备",
    # 机器人类
    "机器人ETF": "机器人",
    # 储能类
    "储能电池ETF": "储能",
    "储能ETF": "储能",
    # 纳斯达克类
    "纳斯达克ETF": "纳斯达克",
    # 恒生科技类
    "恒生科技ETF": "恒生科技",
    # 红利类
    "恒生红利ETF": "红利",
    "中证红利ETF": "红利",
    "红利ETF": "红利",
    # 半导体类
    "半导体ETF": "半导体",
    "芯片ETF": "半导体",
    # 医药类
    "医药ETF": "医药生物",
    "医疗ETF": "医药生物",
    "创新药ETF": "医药生物",
    # 消费类
    "消费ETF": "消费",
    "白酒ETF": "消费",
    # 新能源类
    "新能源ETF": "新能源",
    "光伏ETF": "新能源",
    "新能源车ETF": "新能源",
    "新能源车LOF": "新能源车",
    "智能汽车LOF": "新能源车",
    # 有色金属/工业金属类
    "有色金属ETF": "有色金属",
    "工业金属ETF": "有色金属",
    "稀有金属ETF": "有色金属",
    # 价值/现金流类
    "价值100ETF": "金融",
    "价值ETF": "金融",
    "自由现金流ETF": "金融",
    "现金流ETF": "金融",
    # AI/科技类
    "创业板人工智能ETF": "科技（AI与数字经济）",
    # 黄金类
    "黄金ETF": "贵金属（黄金/铜）",
    # 金融类
    "银行ETF": "金融",
    "保险ETF": "金融",
    # 科技类
    "科技ETF": "科技（AI与数字经济）",
    "人工智能ETF": "科技（AI与数字经济）",
    "5GETF": "科技（AI与数字经济）",
    # 电力类
    "电力ETF": "高股息公用事业",
}


class ETFFundamentalAnalyzer:
    """ETF行业基本面分析器"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def analyze(
        self,
        etf_code: str,
        etf_name: str,
        favorable_industries: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        分析ETF基本面，给出评分

        Args:
            etf_code: ETF代码 (e.g. "515850.SH")
            etf_name: ETF名称 (e.g. "证券ETF富国")
            favorable_industries: 当日利好行业列表（来自第1步分析）

        Returns:
            基本面分析结果，包含评分
        """
        # 1. 识别ETF所属行业
        industry = self._identify_industry(etf_name)

        # 2. 获取行业基本面画像
        profile = self._get_industry_profile(industry)

        # 3. 计算基本面评分
        score = self._calculate_score(profile, favorable_industries)

        # 4. 生成分析描述
        description = self._generate_description(industry, profile, score, favorable_industries)

        return {
            "etf_code": etf_code,
            "etf_name": etf_name,
            "industry": industry,
            "fundamental_score": score,
            "industry_profile": profile,
            "description": description,
            "analysis_time": datetime.now().isoformat(),
        }

    def _identify_industry(self, etf_name: str) -> str:
        """从ETF名称识别所属行业"""
        # 去掉基金公司后缀（如"富国"、"华夏"等）
        clean_name = etf_name.replace("ETF", "").strip()
        # 也去掉常见基金公司名
        fund_companies = ["富国", "华夏", "易方达", "广发", "招商", "景顺", "华泰柏瑞", "南方", "嘉实"]
        for company in fund_companies:
            clean_name = clean_name.replace(company, "").strip()

        # 先尝试完整名称匹配
        for key, industry in ETF_NAME_INDUSTRY_MAP.items():
            if key in etf_name:
                return industry

        # 再尝试去掉公司名后匹配
        for key, industry in ETF_NAME_INDUSTRY_MAP.items():
            if key.replace("ETF", "") in clean_name:
                return industry

        # 默认归为"消费"类
        return "消费"

    def _get_industry_profile(self, industry: str) -> Dict[str, Any]:
        """获取行业基本面画像"""
        # 精确匹配
        if industry in INDUSTRY_FUNDAMENTAL_PROFILES:
            return INDUSTRY_FUNDAMENTAL_PROFILES[industry]

        # 模糊匹配：行业名称包含关键字
        for key, profile in INDUSTRY_FUNDAMENTAL_PROFILES.items():
            if key in industry or industry in key:
                return profile

        # 默认画像
        return {
            "policy_support": 5,
            "cycle_position": "未知",
            "growth": 5,
            "defensiveness": 5,
            "base_score": 4,
        }

    def _calculate_score(
        self,
        profile: Dict[str, Any],
        favorable_industries: Optional[List[Dict]] = None,
    ) -> float:
        """
        计算基本面评分

        评分逻辑：
        - 基础分 = 行业画像的base_score (映射到 -5~8)
        - 利好行业加成 = 如果当前行业在利好行业列表中，加1~3分
        - 最终分数范围: -5 到 8
        """
        base = profile.get("base_score", 4)

        # 将base_score (1-10) 映射到 (-5, 8) 范围
        # base_score 1->-5, 5->0, 10->8
        score = (base - 5) * 1.3 + 0  # base 1->-5.2, 5->0, 10->6.5

        # 利好行业加成
        if favorable_industries:
            for fav in favorable_industries:
                fav_name = fav.get("name", "")
                weight = fav.get("weight", 0.5)
                # 检查行业名称是否匹配
                if self._industry_match(fav_name, profile):
                    # 利好行业加成：0.5~1.5分（基于权重）
                    bonus = weight * 1.5
                    score += bonus
                    break

        # Clamp to [-5, 8]
        score = max(-5, min(8, score))

        return round(score, 1)

    def _industry_match(self, fav_name: str, profile: Dict[str, Any]) -> bool:
        """检查利好行业名称是否匹配当前行业画像"""
        # 常见行业名称映射关系
        aliases = {
            "科技（AI与数字经济）": ["科技", "AI", "数字经济", "信息技术"],
            "半导体": ["芯片", "集成电路"],
            "新能源": ["光伏", "风电", "新能源车"],
            "医药生物": ["医药", "医疗", "生物", "创新药"],
            "贵金属（黄金/铜）": ["黄金", "贵金属", "有色金属"],
            "高股息公用事业": ["公用事业", "电力", "高股息"],
            "金融": ["银行", "证券", "保险", "券商"],
            "消费电子": ["消费", "电子"],
        }

        for key, alias_list in aliases.items():
            if fav_name == key or fav_name in alias_list:
                return True

        return False

    def _generate_description(
        self,
        industry: str,
        profile: Dict[str, Any],
        score: float,
        favorable_industries: Optional[List[Dict]] = None,
    ) -> str:
        """生成基本面分析描述"""
        parts = []

        # 行业周期
        cycle = profile.get("cycle_position", "未知")
        parts.append(f"行业周期处于{cycle}")

        # 政策支持
        policy = profile.get("policy_support", 5)
        if policy >= 8:
            parts.append("政策支持力度强")
        elif policy >= 6:
            parts.append("政策有一定支持")
        else:
            parts.append("政策支持一般")

        # 利好行业
        if favorable_industries:
            for fav in favorable_industries:
                if self._industry_match(fav.get("name", ""), profile):
                    parts.append(f"属于当日利好行业({fav.get('name', '')})")
                    break

        # 评分说明
        if score >= 6:
            parts.append("基本面前景良好")
        elif score >= 3:
            parts.append("基本面前景中性偏正")
        elif score >= 0:
            parts.append("基本面前景中性")
        else:
            parts.append("基本面前景偏弱")

        return "，".join(parts)


# 预设的热门ETF推荐列表（按行业分类）
RECOMMENDED_ETFS = [
    # 科技/AI
    {"name": "人工智能ETF", "code": "515070.SH", "industry": "科技（AI与数字经济）"},
    {"name": "科技ETF", "code": "515000.SH", "industry": "科技（AI与数字经济）"},
    # 半导体
    {"name": "半导体ETF", "code": "512480.SH", "industry": "半导体"},
    {"name": "芯片ETF", "code": "159995.SZ", "industry": "半导体"},
    # 新能源
    {"name": "新能源ETF", "code": "516160.SH", "industry": "新能源"},
    {"name": "光伏ETF", "code": "515790.SH", "industry": "新能源"},
    {"name": "新能源车LOF", "code": "161028.SZ", "industry": "新能源车"},
    # 有色金属/工业金属
    {"name": "有色金属ETF天弘", "code": "159157.SZ", "industry": "有色金属"},
    # 医药
    {"name": "创新药ETF", "code": "515120.SH", "industry": "医药生物"},
    {"name": "医药ETF", "code": "512010.SH", "industry": "医药生物"},
    # 贵金属
    {"name": "黄金ETF", "code": "518880.SH", "industry": "贵金属（黄金/铜）"},
    # 金融
    {"name": "银行ETF", "code": "512800.SH", "industry": "金融"},
    # 高股息/红利
    {"name": "红利ETF", "code": "510880.SH", "industry": "红利"},
    # 恒生科技
    {"name": "恒生科技ETF", "code": "513180.SH", "industry": "恒生科技"},
    # 消费
    {"name": "消费ETF", "code": "159928.SZ", "industry": "消费"},
]
