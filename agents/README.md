# Fin-Agent Agents

Fin-Agent 系统中的核心 Agent 模块。

## 可用 Agents

### 分析类 Agents

| Agent | 文件 | 功能 |
|-------|------|------|
| ElliottWaveAgent | analysis/elliott_agent.py | 指数/ETF 艾略特波浪分析 |
| EnhancedElliottAnalyzer | analysis/enhanced_elliott.py | 个股动态波浪分析 |
| ETFAnalyzer | analysis/etf_analyzer.py | ETF 基本面分析 |

### 核心业务 Agents

| Agent | 文件 | 功能 |
|-------|------|------|
| BullAgent | bull_agent.py | 唱多分析 |
| BearAgent | bear_agent.py | 唱空分析 |
| DebateAgent | debate_agent.py | 多空辩论协调 |
| TechnicalAgent | technical_analyzer.py | 技术指标分析 |
| DailySelectionAgent | daily_selection_agent.py | 每日选股 |

### 数据类 Agents

| Agent | 文件 | 功能 |
|-------|------|------|
| FinancialDataFetcher | financial_data_fetcher.py | 财务数据获取 |

## 使用示例

### 增强版波浪分析
```python
from agents.analysis.enhanced_elliott import EnhancedElliottAnalyzer

analyzer = EnhancedElliottAnalyzer()
result = analyzer.analyze_stock('sh688008', '澜起科技', years=3)
print(f"波浪评分: {result['elliott_score']}")
print(f"波浪位置: {result['wave_position']}")
```

### 每日选股
```python
from agents.daily_selection_agent import DailyStockSelectionAgent

agent = DailyStockSelectionAgent()
result = agent.run_daily_selection()
```

### 技术分析
```python
from agents.technical_analyzer import TechnicalAgent

agent = TechnicalAgent()
result = agent.analyze('sh600519')
print(f"技术评分: {result['score']}")
print(f"建议: {result['recommendation']}")
```

## 基础架构

所有业务 Agent 继承自 `BaseAgent` 基类，提供统一的标准接口。