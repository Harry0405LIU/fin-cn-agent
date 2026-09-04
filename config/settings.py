#!/usr/bin/env python3
"""
全局配置管理 - 支持环境变量和 .env 文件
"""

import os
from pathlib import Path
from typing import Dict, Any


def _load_dotenv():
    """从 .env 文件加载环境变量（仅在未设置时加载，不依赖 python-dotenv）。

    查找优先级（先找到的优先，后面的不加载）：
    1. FINAGENT_ENV_FILE 环境变量显式指定的路径
    2. ~/.finagent.env            —— 项目文件夹之外的本地密钥文件（推荐）
    3. ~/.config/fin-agent/.env
    4. 项目根目录 .env            —— 本地开发兜底
    """
    candidates = []

    explicit = os.environ.get("FINAGENT_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    candidates.append(Path.home() / ".finagent.env")
    candidates.append(Path.home() / ".config" / "fin-agent" / ".env")
    candidates.append(Path(__file__).parent.parent / ".env")
    candidates.append(Path(__file__).parent.parent.parent / ".env")

    env_file = None
    for candidate in candidates:
        if candidate.exists():
            env_file = candidate
            break

    if env_file is None:
        return

    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


# 在模块加载时自动读取 .env
_load_dotenv()


class Settings:
    """应用配置 - 支持环境变量覆盖"""

    def __init__(self):
        # 项目根目录
        self.PROJECT_ROOT = Path(__file__).parent.parent

        # 报告输出根目录：优先 FINAGENT_BASE_DIR 环境变量，默认 ~/fin-agent-output
        self.BASE_DIR = Path(
            os.getenv('FINAGENT_BASE_DIR', '') or str(Path.home() / "fin-agent-output")
        )

        # 数据目录（项目内，不受 BASE_DIR 影响）
        self.DATA_DIR = self.PROJECT_ROOT / "data"
        self.CACHE_DIR = self.DATA_DIR / "cache"
        self.LOG_DIR = self.DATA_DIR / "logs"

        # 确保目录存在
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 艾略特波浪配置
        self.ELLIOTT_REPORT_DIR = self.BASE_DIR / "波浪预测" / "每日更新"
        self.ELLIOTT_CHART_DIR = self.BASE_DIR / "波浪预测" / "波浪预测图形"

        # 多空辩论分析配置
        self.DEBATE_REPORT_DIR = self.BASE_DIR / "研报" / "个股分析"
        self.DEBATE_REPORT_DIR.mkdir(parents=True, exist_ok=True)

        # 缠论配置
        self.CHANLUN_REPORT_DIR = self.BASE_DIR / "缠论分析" / "每日更新"
        self.CHANLUN_CHART_DIR = self.BASE_DIR / "缠论分析" / "图表"
        self.CHANLUN_TIMEFRAME = os.getenv('FINAGENT_CHANLUN_TIMEFRAME', '30min')
        self.CHANLUN_DATA_MONTHS = int(os.getenv('FINAGENT_CHANLUN_DATA_MONTHS', '6'))

        # 企业微信Webhook
        self.WEBHOOK_URL = os.getenv('FINAGENT_WEBHOOK_URL') or os.getenv('ELLIOTT_WEBHOOK_URL')
        
        # 数据获取配置（支持环境变量覆盖）
        self.DATA_FETCH_TIMEOUT = int(os.getenv('FINAGENT_DATA_TIMEOUT', '30'))
        self.DATA_FETCH_RETRIES = int(os.getenv('FINAGENT_DATA_RETRIES', '3'))
        self.DATA_FETCH_RATE_LIMIT = float(os.getenv('FINAGENT_RATE_LIMIT', '0.5'))
        
        # 缓存配置
        self.CACHE_EXPIRE_DAYS = int(os.getenv('FINAGENT_CACHE_EXPIRE_DAYS', '7'))
        
        # 日志配置
        self.LOG_LEVEL = os.getenv('FINAGENT_LOG_LEVEL', 'INFO')

        # 企业微信配置
        self.MAX_CONTENT_BYTES = 3800  # 企业微信单条消息上限
        
    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            'PROJECT_ROOT': str(self.PROJECT_ROOT),
            'DATA_DIR': str(self.DATA_DIR),
            'CACHE_DIR': str(self.CACHE_DIR),
            'LOG_DIR': str(self.LOG_DIR),
            'ELLIOTT_REPORT_DIR': str(self.ELLIOTT_REPORT_DIR),
            'ELLIOTT_CHART_DIR': str(self.ELLIOTT_CHART_DIR),
            'DATA_FETCH_TIMEOUT': self.DATA_FETCH_TIMEOUT,
            'DATA_FETCH_RETRIES': self.DATA_FETCH_RETRIES,
            'DATA_FETCH_RATE_LIMIT': self.DATA_FETCH_RATE_LIMIT,
            'CACHE_EXPIRE_DAYS': self.CACHE_EXPIRE_DAYS,
            'LOG_LEVEL': self.LOG_LEVEL,
        }


# 全局配置实例
settings = Settings()
