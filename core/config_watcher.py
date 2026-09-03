#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置热更新模块
监控配置文件变化，自动重新加载
敏感配置迁移至 .env 文件
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATA_DIR, PROJECT_DIR

# .env 文件路径
ENV_FILE = os.path.join(PROJECT_DIR, ".env")

# 配置文件修改时间缓存
_config_mtimes = {}
_config_reloaders = {}


def load_env_file(filepath=None):
    """
    加载 .env 文件中的环境变量
    不覆盖已有的环境变量

    Args:
        filepath: .env文件路径，默认项目根目录下的 .env
    """
    if filepath is None:
        filepath = ENV_FILE

    if not os.path.exists(filepath):
        return

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            # 不覆盖已有环境变量
            if key not in os.environ:
                os.environ[key] = value


def get_env(key: str, default=None):
    """
    获取环境变量（优先从 .env 加载）

    Args:
        key: 环境变量名
        default: 默认值
    """
    if not os.environ.get(key):
        load_env_file()
    return os.environ.get(key, default)


def register_config_watcher(config_path: str, reloader):
    """
    注册配置文件变更监听器

    Args:
        config_path: 配置文件路径
        reloader: 重新加载函数，签名为 reloader() -> None
    """
    _config_reloaders[config_path] = reloader
    if os.path.exists(config_path):
        _config_mtimes[config_path] = os.path.getmtime(config_path)


def check_config_changes():
    """
    检查配置文件是否有变更，如有则调用重新加载函数

    Returns:
        list: 已变更的配置文件列表
    """
    changed = []
    for config_path, reloader in _config_reloaders.items():
        if not os.path.exists(config_path):
            continue

        current_mtime = os.path.getmtime(config_path)
        last_mtime = _config_mtimes.get(config_path, 0)

        if current_mtime > last_mtime:
            _config_mtimes[config_path] = current_mtime
            try:
                reloader()
                changed.append(config_path)
                print(f"  [配置热更新] {config_path} 已重新加载")
            except Exception as e:
                print(f"  [配置热更新] {config_path} 重新加载失败: {e}")

    return changed


def create_env_template():
    """创建 .env 模板文件"""
    template = """# FinAgent 环境变量配置
# 复制此文件为 .env 并填入实际值

# 企业微信 Webhook URLs（如需覆盖 settings.py 中的默认值）
# ELLIOTT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY
# XUEQIU_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY
# STOCK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY

# SMTP 邮件配置（stock模块周报使用）
# SMTP_HOST=smtp.example.com
# SMTP_PORT=465
# SMTP_USER=your_email@example.com
# SMTP_PASSWORD=your_password
# EMAIL_FROM=your_email@example.com
# EMAIL_TO=recipient@example.com

# 日志级别
# LOG_LEVEL=INFO
"""
    env_path = os.path.join(PROJECT_DIR, ".env.example")
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(template)
        print(f"已创建 .env 模板: {env_path}")
    return env_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FinAgent 配置管理")
    parser.add_argument("--init-env", action="store_true", help="创建 .env 模板文件")
    parser.add_argument("--check", action="store_true", help="检查配置变更")
    args = parser.parse_args()

    if args.init_env:
        create_env_template()
    elif args.check:
        changed = check_config_changes()
        if changed:
            print(f"已变更配置: {changed}")
        else:
            print("无配置变更")
    else:
        load_env_file()
        print("环境变量已加载")
