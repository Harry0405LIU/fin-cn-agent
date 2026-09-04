# Fin-Agent · AI Buffett × Munger Debate Stock Selection

> Two AI analysts with distinct personas — **Buffett (the bear)** and **Munger (the bull)** — debate each stock, then the system synthesizes a three-dimensional score and buy/sell signals, generating a daily stock-selection report automatically.

*[中文文档](README.md) | [English](README.en.md)*

<p align="center">
  <a href="examples/demo_report.md"><b>📊 View a real daily stock-selection report sample →</b></a>
</p>

## Report Highlights

Every stock's detailed analysis includes a complete multi-school technical profile:

- 🌊 **Elliott Wave analysis**: wave positioning + wave structure + multi-timeframe resonance
- ⚖️ **Iron-rule validation**: validates complete impulse waves against the three iron rules (wave 2 must not break wave 1's start / wave 3 must not be the shortest / wave 4 must not enter wave 1's territory)
- 🎯 **Scenario projection**: multi-scenario probabilities + support/resistance/target + confirmation/invalidation signals
- 📉 **Fibonacci levels**: full 0% ~ 100% retracement grid
- 📊 **Volume-price signals + action points**: momentum/volume/breakout + support/resistance/target/invalidation levels
- 🧮 **Three-dimensional value score**: quality company 45% + trend 30% + valuation 25%
- 🕸️ **Chan theory buy/sell points**: pivot zones + type-1/2/3 buy & sell points

## Why it's interesting

- 🎭 **Multi-persona debate**: each stock is argued by a "Buffett" (bear) and a "Munger" (bull) persona over multiple rounds, producing balanced, sharp views instead of a single-model monologue.
- 🧮 **Quantitative value scoring**: quality company (45%) + trend (30%) + valuation (25%), computed by a rules engine — not model guessing.
- 📐 **Multi-school technicals**: Chan theory (pivots/buy-sell points) + Elliott Wave + moving-average volume-price, with multi-timeframe resonance.
- 📊 **Daily automated reports**: one command runs "favorable industries → stock pool → per-stock analysis → score ranking → report", outputting Markdown/JSON.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure an LLM key (recommended outside the repo, to avoid accidental commits)
cp .env.example ~/.finagent.env
# edit ~/.finagent.env and fill in ANTHROPIC_AUTH_TOKEN or DEEPSEEK_API_KEY, etc.

# 3. Run daily stock selection
python generate_daily_selection_md.py
```

Keys live in `~/.finagent.env` outside the repo and are loaded automatically at startup; the GitHub repo only contains the `.env.example` template — no real keys. To change the output directory:

```bash
export FINAGENT_BASE_DIR=./output
python generate_daily_selection_md.py
```

## Features

| Module | Description |
|---|---|
| Multi-persona debate | Buffett (bear) + Munger (bull), multi-round debate + final synthesis |
| Three-dimensional value score | quality 45% + trend 30% + valuation 25%, quantitative |
| Technical analysis | moving-average volume-price + Chan buy/sell points + Elliott Wave |
| Friend of time | long-term quality-stock flag ⏰ based on business model / culture / understandability |
| Daily report | Markdown (brief + detailed) + full JSON data |
| Stock pool | curated industry leaders + bottom-asset pool (configurable) |

## Scoring methodology

**Combined score = technical analysis × 50% + value analysis × 50%**

- **Technical analysis** = short-term timing × 40% + medium-term trend (wave) × 60%
- **Value analysis** = quality company × 45% + trend × 30% + valuation × 25%
- Chan signals do not contribute to the score; they are shown as buy/sell references only

Ratings: Strong Buy / Buy / Neutral / Sell / Strong Sell (thresholds in `agents/daily_selection_agent.py`).

## Project structure

```
fin-agent/
├── agents/            # analysis agents (debate/selection/technical)
│   ├── bull_agent.py      # Munger (bull)
│   ├── bear_agent.py      # Buffett (bear)
│   ├── debate_agent.py    # debate coordinator
│   └── daily_selection_agent.py  # main daily-selection pipeline
├── core/              # LLM client, data fetching, caching, IO utilities
├── config/settings.py # global config (.env / env vars)
├── chanlun/           # Chan theory analysis (fractals/strokes/pivots/buy-sell points)
├── elliott/           # Elliott Wave analysis (per stock)
├── skills/            # Buffett / Munger persona definitions
├── services/          # WeChat Work webhook push
├── scripts/           # launcher scripts (launchd schedule templates)
└── generate_daily_selection_md.py  # daily report entry point
```

## Configuration

All configuration is via environment variables (see `.env.example`). The key file is loaded in priority order — **first match wins**:

1. Path specified by `FINAGENT_ENV_FILE`
2. `~/.finagent.env` (**recommended**: outside the repo, won't be committed)
3. `~/.config/fin-agent/.env`
4. repo root `.env`

| Variable | Description |
|---|---|
| `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` | z.ai / Anthropic (default primary) |
| `DEEPSEEK_API_KEY` | DeepSeek (fallback) |
| `GLM_API_KEY` | Zhipu GLM (fallback) |
| `ITICK_API_KEY` | iTick data source (optional) |
| `FINAGENT_BASE_DIR` | report output root (default `~/fin-agent-output`) |
| `FINAGENT_WEBHOOK_URL` | WeChat Work push (optional) |

## FAQ

**Q: How do I switch LLM model/provider?**
`AUTO_DETECT_ORDER` in `core/llm_client.py` defines the priority, default z.ai > DeepSeek > Zhipu > OpenAI. Adjust it freely.

**Q: How do I trim the stock pool?**
Edit `DEFAULT_STOCKS` in `agents/daily_selection_agent.py`, or set `EXCLUDED_ANALYSIS_INDUSTRY_PREFIXES` to skip certain industries (e.g. the "bottom asset" series).

**Q: Does the debate run every time?**
No. Debate results are cached by financial-report period; they are reused unless a new report is published.

**Q: How do I schedule it?**
On macOS use `scripts/generate_daily_selection_md.sh` + launchd (see `config/schedules/`, which is removed from the repo and must be generated locally).

## Disclaimer

This project is for research and educational purposes only and does **not** constitute investment advice. Markets are risky; past performance does not guarantee future results. Please make independent decisions based on your own risk tolerance.

## License

MIT License (modify if you prefer another).
