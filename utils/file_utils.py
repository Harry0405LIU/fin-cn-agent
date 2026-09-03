#!/usr/bin/env python3
"""
文件操作工具函数
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def ensure_dir(path: str) -> Path:
    """确保目录存在"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_json(filepath: str) -> Optional[Dict]:
    """读取JSON文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def write_json(filepath: str, data: Dict, indent: int = 2) -> bool:
    """写入JSON文件"""
    try:
        ensure_dir(Path(filepath).parent)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return True
    except Exception:
        return False


def read_text(filepath: str) -> Optional[str]:
    """读取文本文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def write_text(filepath: str, content: str) -> bool:
    """写入文本文件"""
    try:
        ensure_dir(Path(filepath).parent)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception:
        return False
