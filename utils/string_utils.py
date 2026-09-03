#!/usr/bin/env python3
"""
字符串处理工具函数
"""

import re
from typing import List


def truncate(text: str, max_length: int, suffix: str = '...') -> str:
    """截断字符串"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def truncate_text(text: str, max_length: int, suffix: str = '...') -> str:
    """截断字符串（别名）"""
    return truncate(text, max_length, suffix)


def clean_whitespace(text: str) -> str:
    """清理多余空白"""
    return ' '.join(text.split())


def extract_numbers(text: str) -> List[float]:
    """提取文本中的数字"""
    numbers = re.findall(r'-?\d+\.?\d*', text)
    return [float(n) for n in numbers]


def contains_chinese(text: str) -> bool:
    """判断是否包含中文"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def slugify(text: str) -> str:
    """转换为URL友好的字符串"""
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text
