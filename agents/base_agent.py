#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 基类
所有 Agent 应该继承此基类，确保接口一致性
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from datetime import datetime

from core.logger import get_logger


class BaseAgent(ABC):
    """所有 Agent 的基类"""

    def __init__(self, name: str, config: Optional[Dict] = None):
        """
        初始化 Agent

        Args:
            name: Agent 名称
            config: 配置字典
        """
        self.name = name
        self.config = config or {}
        self.logger = get_logger(name)
        self._initialized = False
        self._last_run_time = None
        self._last_status = "idle"

    # ============================================================
    # 抽象方法 - 子类必须实现
    # ============================================================

    @abstractmethod
    def run(self, *args, **kwargs) -> Dict:
        """
        执行 Agent 的主逻辑

        Returns:
            执行结果字典，至少包含:
            - success: bool - 是否成功
            - message: str - 执行消息
            - data: Any - 返回的数据（可选）
            - timestamp: str - 执行时间
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """
        验证配置是否有效

        Returns:
            配置是否有效
        """
        pass

    # ============================================================
    # 状态管理
    # ============================================================

    def get_status(self) -> Dict:
        """
        获取 Agent 运行状态

        Returns:
            状态字典
        """
        return {
            "name": self.name,
            "status": self._last_status,
            "last_run_time": self._last_run_time,
            "initialized": self._initialized,
            "config_keys": list(self.config.keys()) if self.config else []
        }

    def is_initialized(self) -> bool:
        """返回 Agent 是否已初始化"""
        return self._initialized

    def initialize(self) -> bool:
        """
        初始化 Agent

        Returns:
            初始化是否成功
        """
        try:
            if not self.validate_config():
                self.logger.error(f"{self.name}: 配置验证失败")
                return False

            self._initialized = True
            self.logger.info(f"{self.name}: 初始化成功")
            return True
        except Exception as e:
            self.logger.error(f"{self.name}: 初始化失败 - {e}")
            return False

    # ============================================================
    # 执行管理
    # ============================================================

    def execute(self, *args, **kwargs) -> Dict:
        """
        执行 Agent（带状态管理）

        Returns:
            执行结果
        """
        if not self._initialized:
            self.initialize()

        self._last_status = "running"
        self.logger.info(f"{self.name}: 开始执行")

        try:
            result = self.run(*args, **kwargs)

            # 确保结果包含标准字段
            if "timestamp" not in result:
                result["timestamp"] = datetime.now().isoformat()
            if "success" not in result:
                result["success"] = True

            self._last_status = "completed" if result["success"] else "failed"
            self._last_run_time = result["timestamp"]

            self.logger.info(f"{self.name}: 执行完成 - {self._last_status}")

            return result

        except Exception as e:
            self._last_status = "error"
            self._last_run_time = datetime.now().isoformat()
            self.logger.error(f"{self.name}: 执行出错 - {e}", exc_info=True)

            return {
                "success": False,
                "message": f"执行出错: {str(e)}",
                "error": str(e),
                "timestamp": self._last_run_time
            }

    # ============================================================
    # 配置管理
    # ============================================================

    def get_config(self, key: str, default: Any = None) -> Any:
        """
        获取配置值

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        """
        设置配置值

        Args:
            key: 配置键
            value: 配置值
        """
        self.config[key] = value

    def update_config(self, config: Dict) -> None:
        """
        更新配置

        Args:
            config: 配置字典
        """
        self.config.update(config)

    # ============================================================
    # 日志辅助
    # ============================================================

    def log_info(self, message: str) -> None:
        """记录信息日志"""
        self.logger.info(message)

    def log_warning(self, message: str) -> None:
        """记录警告日志"""
        self.logger.warning(message)

    def log_error(self, message: str, exc_info: bool = False) -> None:
        """记录错误日志"""
        self.logger.error(message, exc_info=exc_info)

    def log_debug(self, message: str) -> None:
        """记录调试日志"""
        self.logger.debug(message)


class AgentConfig:
    """Agent 配置管理类"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.configs = {}

        if config_path:
            self.load_from_file(config_path)

    def load_from_file(self, filepath: str) -> Dict:
        """
        从文件加载配置

        Args:
            filepath: 配置文件路径

        Returns:
            加载的配置字典
        """
        import json
        from pathlib import Path

        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {filepath}")

        with open(path, "r", encoding="utf-8") as f:
            self.configs = json.load(f)

        return self.configs

    def save_to_file(self, filepath: str) -> None:
        """
        保存配置到文件

        Args:
            filepath: 配置文件路径
        """
        import json

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.configs, f, ensure_ascii=False, indent=2)

    def get_agent_config(self, agent_name: str) -> Dict:
        """
        获取特定 Agent 的配置

        Args:
            agent_name: Agent 名称

        Returns:
            Agent 配置字典
        """
        return self.configs.get(agent_name, {})

    def set_agent_config(self, agent_name: str, config: Dict) -> None:
        """
        设置特定 Agent 的配置

        Args:
            agent_name: Agent 名称
            config: 配置字典
        """
        self.configs[agent_name] = config
