# Fin-Agent · AI 巴菲特 × 芒格 多空辩论选股

> 让两个不同人格的 AI 分析师——**巴菲特（空头）** 和 **芒格（多头）**——就一只股票激烈交锋，再综合给出三维评分与买卖点建议，每日自动生成选股报告。

*[中文](README.md) | [English](README.en.md)*

<p align="center">
  <a href="examples/demo_report.md"><b>📊 查看一份真实的每日选股报告样例 →</b></a>
</p>

## 报告亮点

每只股票的详细分析都包含一套完整的多流派技术画像：

- 🌊 **艾略特波浪分析**：波浪定位 + 浪型结构 + 多级别共振
- ⚖️ **铁律校验**：对完整推动浪做三条铁律校验（2浪不破起点 / 3浪不最短 / 4浪不入1浪区间）
- 🎯 **情景推演**：多情景概率 + 支撑/阻力/目标位 + 确认/否定信号
- 📉 **斐波那契关键位**：0% ~ 100% 全档回撤位
- 📊 **量价信号 + 操作要点**：动量/量能/突破 + 支撑带/阻力带/目标/失效位
- 🧮 **三维价值评分**：好公司 45% + 趋势 30% + 估值 25%
- 🕸️ **缠论买卖点**：中枢位置 + 一/二/三类买卖点

## 为什么值得关注

- 🎭 **多空辩论**：每只股票由「巴菲特」和「芒格」两个 persona 各持一方、多轮辩论，输出平衡而尖锐的观点，而不是单一模型的自说自话。
- 🧮 **三维价值评分**：好公司（45%）+ 趋势（30%）+ 估值（25%）——量化引擎计算，不靠模型拍脑袋。
- 📐 **多流派技术面**：缠论（中枢/买卖点）+ 艾略特波浪 + 均线量价，多级别共振。
- 📊 **每日自动报告**：一键跑完「利好行业 → 选股池 → 逐股分析 → 评分排序 → 报告」，输出 Markdown/JSON。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM Key（推荐放到项目文件夹之外，避免误提交）
cp .env.example ~/.finagent.env
# 编辑 ~/.finagent.env，填入 ANTHROPIC_AUTH_TOKEN 或 DEEPSEEK_API_KEY 等

# 3. 运行每日选股
python generate_daily_selection_md.py
```

密钥放在项目外的 `~/.finagent.env`，代码启动时自动加载；GitHub 仓库里只有 `.env.example` 模板、没有任何真实密钥。想换个输出目录：

```bash
export FINAGENT_BASE_DIR=./output
python generate_daily_selection_md.py
```

## 功能特性

| 模块 | 说明 |
|---|---|
| 多空辩论 | 巴菲特（空头）+ 芒格（多头），多轮交锋 + 最终综合结论 |
| 三维价值评分 | 好公司 45% + 趋势 30% + 估值 25%，量化计算 |
| 技术分析 | 均线量价 + 缠论买卖点 + 艾略特波浪 |
| 时间的朋友 | 基于商业模式/企业文化/可理解性的长期优质股标记 ⏰ |
| 每日报告 | Markdown（简版 + 详细版）+ JSON 全量数据 |
| 股票池 | 精选行业龙头 + 底部资产池（可配置，见下文） |

## 评分方法论

**综合评分 = 技术分析 × 50% + 价值分析 × 50%**

- **技术分析** = 短期时机 × 40% + 中期趋势（波浪）× 60%
- **价值分析** = 好公司 × 45% + 趋势 × 30% + 估值 × 25%
- 缠论信号不参与评分，仅作买卖点参考

投资评级：强烈推荐 / 推荐 / 中性 / 不推荐 / 强烈不推荐（阈值见 `agents/daily_selection_agent.py`）。

## 项目结构

```
fin-agent/
├── agents/            # 各分析 Agent（辩论/选股/技术面）
│   ├── bull_agent.py      # 芒格（多头）
│   ├── bear_agent.py      # 巴菲特（空头）
│   ├── debate_agent.py    # 辩论协调器
│   └── daily_selection_agent.py  # 每日选股主流程
├── core/              # LLM 客户端、数据获取、缓存、IO 工具
├── config/settings.py # 全局配置（支持 .env / 环境变量）
├── chanlun/           # 缠论分析（分型/笔/中枢/买卖点/背驰）
├── elliott/           # 艾略特波浪分析（个股）
├── skills/            # 巴菲特 / 芒格 persona 定义
├── services/          # 企业微信 Webhook 推送
├── scripts/           # 启动脚本（launchd 定时任务模板）
└── generate_daily_selection_md.py  # 每日报告入口
```

## 配置

所有配置通过环境变量设置（模板见 `.env.example`）。密钥文件按以下优先级自动加载，**先找到的优先**：

1. `FINAGENT_ENV_FILE` 指定的路径
2. `~/.finagent.env`（**推荐**：项目文件夹之外，不会误提交）
3. `~/.config/fin-agent/.env`
4. 项目根目录 `.env`

| 变量 | 说明 |
|---|---|
| `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` | z.ai / Anthropic（默认首选） |
| `DEEPSEEK_API_KEY` | DeepSeek（备选） |
| `GLM_API_KEY` | 智谱（备选） |
| `ITICK_API_KEY` | iTick 数据源（可选） |
| `FINAGENT_BASE_DIR` | 报告输出根目录（默认 `~/Documents/Harry's Vault`） |
| `FINAGENT_WEBHOOK_URL` | 企业微信推送（可选） |

## FAQ

**Q: 怎么换 LLM 模型/供应商？**
`core/llm_client.py` 中 `AUTO_DETECT_ORDER` 决定优先级，默认 z.ai > DeepSeek > 智谱 > OpenAI，可自行调整。

**Q: 股票池怎么精简？**
编辑 `agents/daily_selection_agent.py` 的 `DEFAULT_STOCKS`，或修改 `EXCLUDED_ANALYSIS_INDUSTRY_PREFIXES` 跳过某些行业（如「周金涛底部」系列）。

**Q: 辩论每次都跑吗？**
不。辩论结果按「财报期」缓存，财报期没变就直接复用，只有新财报发布才重跑。

**Q: 怎么定时运行？**
macOS 上可用 `scripts/generate_daily_selection_md.sh` + launchd（参考 `config/schedules/`，已从仓库移除，需本地生成）。

## 免责声明

本项目仅供学习研究使用，**不构成任何投资建议**。股市有风险，历史表现不代表未来收益，请结合自身风险承受能力独立决策。

## License

MIT License（如更换，请修改此处）。
