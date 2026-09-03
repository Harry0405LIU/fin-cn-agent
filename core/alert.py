#!/usr/bin/env python3
"""
智能预警系统
基于规则的价格和指标预警
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from pathlib import Path

from config.settings import settings
from core.logger import get_logger

logger = get_logger('alert')


@dataclass
class AlertRule:
    """预警规则"""
    id: str
    name: str
    code: str
    condition: str
    threshold: float
    enabled: bool = True
    last_triggered: Optional[str] = None
    trigger_count: int = 0


@dataclass
class Alert:
    """预警记录"""
    id: str
    rule_id: str
    code: str
    message: str
    level: str
    created_at: str
    data: Dict


class AlertManager:
    """预警管理器"""
    
    def __init__(self):
        self.rules: List[AlertRule] = []
        self.alerts: List[Alert] = []
        self.handlers: List[Callable] = []
        self.rules_file = settings.DATA_DIR / 'alert_rules.json'
        self.alerts_file = settings.DATA_DIR / 'alerts.json'
        self._load_rules()
    
    def _load_rules(self):
        """加载规则"""
        if self.rules_file.exists():
            with open(self.rules_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.rules = [AlertRule(**r) for r in data.get('rules', [])]
        else:
            # 创建默认规则
            self._create_default_rules()
    
    def _create_default_rules(self):
        """创建默认预警规则"""
        default_rules = [
            AlertRule(
                id='rsi_oversold_sh',
                name='上证指数RSI超卖预警',
                code='sh000001',
                condition='RSI < 30',
                threshold=30
            ),
            AlertRule(
                id='rsi_overbought_sh',
                name='上证指数RSI超买预警',
                code='sh000001',
                condition='RSI > 70',
                threshold=70
            ),
            AlertRule(
                id='macd_golden_sh',
                name='上证指数MACD金叉预警',
                code='sh000001',
                condition='MACD金叉',
                threshold=0
            ),
        ]
        self.rules = default_rules
        self.save_rules()
    
    def save_rules(self):
        """保存规则"""
        data = {
            'rules': [asdict(r) for r in self.rules],
            'updated_at': datetime.now().isoformat()
        }
        with open(self.rules_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def add_rule(self, rule: AlertRule):
        """添加规则"""
        self.rules.append(rule)
        self.save_rules()
        logger.info(f"添加预警规则: {rule.name}")
    
    def remove_rule(self, rule_id: str):
        """删除规则"""
        self.rules = [r for r in self.rules if r.id != rule_id]
        self.save_rules()
    
    def add_handler(self, handler: Callable):
        """添加预警处理器"""
        self.handlers.append(handler)
    
    def check_rules(self, code: str, data: Dict) -> List[Alert]:
        """检查规则并生成预警"""
        triggered = []
        
        for rule in self.rules:
            if not rule.enabled or rule.code != code:
                continue
            
            alert = self._check_rule(rule, data)
            if alert:
                triggered.append(alert)
                self.alerts.append(alert)
                self._notify_handlers(alert)
        
        return triggered
    
    def _check_rule(self, rule: AlertRule, data: Dict) -> Optional[Alert]:
        """检查单个规则"""
        # 防止重复触发（1小时内不重复）
        if rule.last_triggered:
            last = datetime.fromisoformat(rule.last_triggered)
            if datetime.now() - last < timedelta(hours=1):
                return None
        
        condition_met = False
        message = ""
        level = "info"
        
        # RSI超卖
        if 'RSI <' in rule.condition and 'RSI' in data:
            if data['RSI'] < rule.threshold:
                condition_met = True
                message = f"{rule.code} RSI超卖: {data['RSI']:.2f} < {rule.threshold}"
                level = "warning"
        
        # RSI超买
        elif 'RSI >' in rule.condition and 'RSI' in data:
            if data['RSI'] > rule.threshold:
                condition_met = True
                message = f"{rule.code} RSI超买: {data['RSI']:.2f} > {rule.threshold}"
                level = "warning"
        
        # MACD金叉
        elif 'MACD金叉' in rule.condition:
            if data.get('MACD', 0) > data.get('MACD_Signal', 0):
                # 检查前一天
                condition_met = True
                message = f"{rule.code} MACD金叉信号"
                level = "info"
        
        if condition_met:
            rule.last_triggered = datetime.now().isoformat()
            rule.trigger_count += 1
            self.save_rules()
            
            alert = Alert(
                id=f"alert_{datetime.now().strftime('%Y%m%d%H%M%S')}_{rule.id}",
                rule_id=rule.id,
                code=rule.code,
                message=message,
                level=level,
                created_at=datetime.now().isoformat(),
                data=data
            )
            
            logger.warning(f"预警触发: {message}")
            return alert
        
        return None
    
    def _notify_handlers(self, alert: Alert):
        """通知所有处理器"""
        for handler in self.handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"预警处理器错误: {e}")
    
    def get_recent_alerts(self, hours: int = 24) -> List[Alert]:
        """获取最近预警"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            a for a in self.alerts
            if datetime.fromisoformat(a.created_at) > cutoff
        ]
    
    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            'total_rules': len(self.rules),
            'enabled_rules': sum(1 for r in self.rules if r.enabled),
            'total_alerts': len(self.alerts),
            'recent_alerts': len(self.get_recent_alerts(24)),
            'rules': [{'id': r.id, 'name': r.name, 'trigger_count': r.trigger_count} for r in self.rules]
        }


# 全局预警管理器
alert_manager = AlertManager()
