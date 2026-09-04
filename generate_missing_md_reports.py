#!/usr/bin/env python3
"""
从JSON文件生成缺失的每日选股MD报告
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings


def _extract_chan_signal(chan_analysis):
    """提取缠论买卖点或走势信息（增强版+多级别）"""
    if not chan_analysis or not isinstance(chan_analysis, dict):
        return "N/A"

    # 取数失败（网络/数据源问题）：明确标记、建议重跑（区别于合法的 success=True 但无中枢）
    if chan_analysis.get("success") is False and "数据获取失败" in str(chan_analysis.get("error", "")):
        return "⚠️取数失败·建议重跑"

    # 优先使用多级别分析结果
    multi_level = chan_analysis.get("multi_level", {})
    if multi_level:
        tf30_state = multi_level.get("tf30_state", "")
        daily_state = multi_level.get("daily_state")
        combined_dir = multi_level.get("combined_direction", "")

        # 构建多级别显示
        if tf30_state:
            result = f"**{tf30_state}**"
            if daily_state:
                # 简写日线状态
                daily_short = daily_state.replace("中枢", "")
                result += f" 日:{daily_short}"
            if combined_dir:
                result += f" →{combined_dir}"
            return result

    # 使用增强版分析器
    try:
        from chanlun.enhanced_pivot_analyzer import extract_enhanced_chan_signal
        current_price = chan_analysis.get('current_price', 0)
        enhanced_result = extract_enhanced_chan_signal(chan_analysis, current_price)
        if enhanced_result and enhanced_result != "N/A" and "**中枢扩张**" in enhanced_result:
            return enhanced_result
    except Exception:
        pass

    # 原始逻辑作为后备
    from datetime import datetime, timedelta

    buy_points = chan_analysis.get("active_buys", [])
    sell_points = chan_analysis.get("active_sells", [])

    # 显示最近20个交易日内出现的买卖点
    cutoff_date = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')

    recent_buys = [bp for bp in buy_points if bp.get("date", "") >= cutoff_date]
    recent_sells = [sp for sp in sell_points if sp.get("date", "") >= cutoff_date]

    if recent_buys or recent_sells:
        # 有买卖点，显示买卖点信息
        parts = []
        if recent_buys:
            # 按类型分组，取最高置信度
            buy_by_type = {}
            conf_priority = {"high": 3, "medium": 2, "low": 1, "N/A": 0}
            conf_code_map = {"high": "h", "medium": "m", "low": "l", "N/A": ""}
            for bp in recent_buys:
                btype = bp.get("type", 0)
                conf = bp.get("confidence", "N/A")
                priority = conf_priority.get(conf, 0)
                code = conf_code_map.get(conf, "")
                # 同类型取最高置信度（priority越大越高）
                if btype not in buy_by_type or priority > buy_by_type[btype][0]:
                    buy_by_type[btype] = (priority, code)
            buy_types = sorted(buy_by_type.keys())
            # 高亮显示买点
            buy_signal = ",".join(f"买{t}({buy_by_type[t][1]})" for t in buy_types)
            parts.append(f"**{buy_signal}**")  # 加粗买点
        if recent_sells:
            sell_by_type = {}
            conf_priority = {"high": 3, "medium": 2, "low": 1, "N/A": 0}
            conf_code_map = {"high": "h", "medium": "m", "low": "l", "N/A": ""}
            for sp in recent_sells:
                stype = sp.get("type", 0)
                conf = sp.get("confidence", "N/A")
                priority = conf_priority.get(conf, 0)
                code = conf_code_map.get(conf, "")
                if stype not in sell_by_type or priority > sell_by_type[stype][0]:
                    sell_by_type[stype] = (priority, code)
            sell_types = sorted(sell_by_type.keys())
            parts.append(",".join(f"卖{t}({sell_by_type[t][1]})" for t in sell_types))

        return ",".join(parts) if parts else "—"

    # 无买卖点，根据中枢位置判断走势（增强版：支持中枢扩张检测）
    last_pivot = chan_analysis.get("last_pivot", {})
    current_price = chan_analysis.get("current_price", 0)

    if last_pivot and current_price > 0:
        zg = last_pivot.get("ZG", 0)  # 中枢上沿
        zd = last_pivot.get("ZD", 0)  # 中枢下沿
        has_expansion = last_pivot.get("has_expansion", False)
        overlap_prev_width = last_pivot.get("overlap_prev_width", 0)
        expansion_ratio_prev = last_pivot.get("expansion_ratio_prev", 0)

        if zg > 0 and zd > 0:
            # 构建扩张后缀
            expansion_suffix = ""
            if has_expansion and expansion_ratio_prev > 0:
                expansion_suffix = (
                    f" | **中枢扩张** (重叠{overlap_prev_width:.2f}元, "
                    f"比例{expansion_ratio_prev:.1%})"
                )

            if current_price > zg:
                result = "**中枢上方**"
                return result + expansion_suffix
            elif current_price < zd:
                result = "**中枢下方**"
                return result + expansion_suffix if has_expansion else "中枢下方"
            else:
                if has_expansion:
                    return f"**中枢扩张** (区间[{zd:.2f}, {zg:.2f}])" + expansion_suffix
                return "中枢震荡"

    # 如果没有中枢信息，返回中性
    return "—"

def _color_score(score, threshold_high=7, threshold_low=2):
    """根据评分添加标记，去除emoji圆饼"""
    if isinstance(score, str):
        return score  # 如果是字符串（如'N/A'），直接返回

    score_rounded = round(score, 1)

    if score_rounded >= threshold_high:
        # 高分：加粗+↑标记
        return f'**{score_rounded:.1f}↑**'
    elif score_rounded <= threshold_low:
        # 低分：加粗+↓标记
        return f'**{score_rounded:.1f}↓**'
    else:
        # 中等分数：普通显示
        return f'{score_rounded:.1f}'


def _extract_company_subscores(cq):
    """从 company_quality 提取子分数值 {key: number}，兼容新/旧数据结构。

    新结构(CompanyQualityScorer 当前输出): cq.<key> = {'score': N, 'details':..., 'reasoning':...}
        键为 business_model / corporate_culture / understandability（顶层）
    旧结构: cq.sub_scores = {<key>: N | {'score': N}}

    只返回含有数值的项。
    """
    if not isinstance(cq, dict):
        return {}
    result = {}
    keys = ('business_model', 'corporate_culture', 'understandability',
            'corporate_governance', 'innovation_capability',
            'financial_health', 'profitability', 'competitiveness', 'competitive_barrier')
    # 新结构：cq 顶层键，值为 dict 含 score
    for key in keys:
        v = cq.get(key)
        if isinstance(v, dict) and isinstance(v.get('score'), (int, float)):
            result[key] = v['score']
        elif isinstance(v, (int, float)):
            result[key] = v
    # 旧结构回退：cq.sub_scores
    sub = cq.get('sub_scores', {})
    if isinstance(sub, dict):
        for key, v in sub.items():
            if key in result:
                continue
            if isinstance(v, dict) and isinstance(v.get('score'), (int, float)):
                result[key] = v['score']
            elif isinstance(v, (int, float)):
                result[key] = v
    return result


def _validate_iron_rules(wave_points):
    """对当前波浪计数做艾略特三条铁律校验。

    铁律：① 2浪不破1浪起点 ② 3浪不是1/3/5浪中最短的 ③ 4浪不进入1浪价格区间。
    若 wave_points 不足以提取完整推动浪(浪1~浪5)，返回 None（结构进行中或调整浪）。
    """
    if not isinstance(wave_points, list) or len(wave_points) < 6:
        return None

    prices = {}
    for wp in wave_points:
        if not isinstance(wp, dict):
            continue
        lbl = wp.get('label', '')
        pr = wp.get('price', 0)
        if lbl and isinstance(pr, (int, float)):
            prices[lbl] = pr

    start = prices.get('起点')
    if start is None:
        return None

    w1_up = prices.get('浪1顶')
    w1_dn = prices.get('浪1底')
    if w1_up is not None and w1_up > start:
        up = True
        w1, w2, w3, w4, w5 = w1_up, prices.get('浪2底'), prices.get('浪3顶'), prices.get('浪4底'), prices.get('浪5顶')
        label = "上升推动浪"
    elif w1_dn is not None and w1_dn < start:
        up = False
        w1, w2, w3, w4, w5 = w1_dn, prices.get('浪2顶'), prices.get('浪3底'), prices.get('浪4顶'), prices.get('浪5底')
        label = "下跌推动浪"
    else:
        return None

    if any(v is None for v in (w1, w2, w3, w4, w5)):
        return None

    results = []
    # 规则1：2浪不破起点
    if up:
        ok1 = w2 > start
        detail1 = f"2浪底({w2:.2f}) > 起点({start:.2f})"
    else:
        ok1 = w2 < start
        detail1 = f"2浪顶({w2:.2f}) < 起点({start:.2f})"
    results.append(("① 2浪不破起点", ok1, detail1))

    # 规则2：3浪不最短
    len1, len3, len5 = abs(w1 - start), abs(w3 - w2), abs(w5 - w4)
    ok2 = len3 >= len1 and len3 >= len5
    detail2 = f"3浪({len3:.2f}) ≥ 1浪({len1:.2f}) 且 ≥ 5浪({len5:.2f})"
    results.append(("② 3浪不最短", ok2, detail2))

    # 规则3：4浪不入1浪区间
    if up:
        ok3 = w4 > w1
        detail3 = f"4浪底({w4:.2f}) > 1浪顶({w1:.2f})"
    else:
        ok3 = w4 < w1
        detail3 = f"4浪顶({w4:.2f}) < 1浪底({w1:.2f})"
    results.append(("③ 4浪不入1浪区间", ok3, detail3))

    all_ok = all(r[1] for r in results)
    return {'direction': label, 'results': results, 'all_ok': all_ok}


def _render_elliott_detail(elliott_analysis):
    """渲染个股波浪分析详情（对标指数波浪分析报告的完整结构）。

    从 get_elliott_for_selection 的输出中提取：波浪定位、浪型结构、多级别共振、
    情景推演（概率/支撑/阻力/目标/确认否定信号）、斐波那契关键位、评分依据。
    """
    if not isinstance(elliott_analysis, dict) or 'error' in elliott_analysis:
        return []
    lines = ["**波浪分析详情**:"]

    # 1. 波浪定位 + 趋势
    wave_position = elliott_analysis.get('wave_position', '')
    trend = elliott_analysis.get('trend', '')
    if wave_position:
        pos = f"- 波浪定位：{wave_position}"
        if trend:
            pos += f"（趋势：{trend}）"
        lines.append(pos)

    # 2. 浪型结构 + 位置判断依据
    wave_detail = elliott_analysis.get('wave_detail', {})
    if isinstance(wave_detail, dict):
        structure = wave_detail.get('wave_structure', '')
        reasoning = wave_detail.get('position_reasoning', '')
        if structure:
            lines.append(f"- 浪型结构：{structure}")
        if reasoning:
            lines.append(f"- 位置判断：{reasoning}")

    # 2.5 铁律校验（对完整推动浪做三条铁律校验）
    iron = _validate_iron_rules(elliott_analysis.get('wave_points'))
    if iron:
        verdict = "✅ 三条铁律全部通过" if iron['all_ok'] else "⚠️ 存在铁律违反"
        lines.append("")
        lines.append(f"**铁律校验**（{iron['direction']}，{verdict}）:")
        for name, ok, detail in iron['results']:
            mark = "✓" if ok else "✗"
            lines.append(f"- {mark} {name}：{detail}")
        lines.append("")

    # 3. 多级别共振
    resonance = elliott_analysis.get('resonance', {})
    if isinstance(resonance, dict):
        icon = resonance.get('icon', '')
        direction = resonance.get('direction', '')
        details = resonance.get('details', '')
        warnings = resonance.get('warnings', [])
        if direction or details:
            line = f"- 多级别共振：{icon} {direction}"
            if details:
                line += f"（{details}）"
            lines.append(line)
        if warnings:
            lines.append(f"- 共振警示：{'；'.join(str(w) for w in warnings)}")

    # 4. 情景推演
    scenarios = elliott_analysis.get('scenarios', [])
    if scenarios:
        lines.append("")
        lines.append("**情景推演**:")
        lines.append("| 情景 | 概率 | 支撑 | 阻力 | 目标 |")
        lines.append("|---|---|---|---|---|")
        for s in scenarios[:4]:
            name = s.get('name', '')
            prob = s.get('probability', '')
            support = s.get('key_support', '')
            resistance = s.get('key_resistance', '')
            target = s.get('target', '')
            prob_txt = f"{prob}%" if isinstance(prob, (int, float)) else str(prob)
            lines.append(f"| {name} | {prob_txt} | {support} | {resistance} | {target} |")
        lines.append("")
        for s in scenarios[:3]:
            confirm = s.get('confirm_signals', [])
            deny = s.get('deny_signals', [])
            if confirm or deny:
                parts = []
                if confirm:
                    parts.append(f"确认：{'、'.join(str(x) for x in confirm)}")
                if deny:
                    parts.append(f"否定：{'、'.join(str(x) for x in deny)}")
                lines.append(f"- 「{s.get('name', '')}」{'；'.join(parts)}")

    # 5. 斐波那契关键位
    fib = elliott_analysis.get('fib_levels', {})
    if isinstance(fib, dict) and fib:
        items = [(k, v) for k, v in fib.items() if isinstance(v, (int, float))]
        if items:
            fib_txt = '  '.join(f"{k}: {v:.2f}" for k, v in items)
            lines.append("")
            lines.append(f"- 斐波那契关键位：{fib_txt}")

    # 5.5 量价信号
    tech_signals = elliott_analysis.get('tech_signals')
    breakout_status = elliott_analysis.get('breakout_status')
    if isinstance(tech_signals, dict):
        parts = []
        if isinstance(tech_signals.get('momentum'), (int, float)):
            mom = tech_signals['momentum']
            parts.append(f"动量{'强' if mom > 0.15 else '弱' if mom < -0.15 else '中性'}({mom:+.2f})")
        if isinstance(tech_signals.get('volume'), (int, float)):
            vol = tech_signals['volume']
            parts.append(f"量能{'放大' if vol > 0.3 else '萎缩' if vol < -0.3 else '平稳'}({vol:+.2f})")
        if isinstance(tech_signals.get('breakout'), (int, float)):
            brk = tech_signals['breakout']
            parts.append(f"突破{'倾向' if brk > 0 else '承压'}({brk:+.2f})")
        if parts:
            lines.append("")
            lines.append(f"- 量价信号：{'；'.join(parts)}")
    if isinstance(breakout_status, dict):
        ups = breakout_status.get('breakouts', [])
        downs = breakout_status.get('breakdowns', [])
        if ups:
            lines.append(f"- 突破信号：{'、'.join(str(u) for u in ups)}")
        if downs:
            lines.append(f"- 跌破信号：{'、'.join(str(d) for d in downs)}")

    # 5.8 操作要点（从情景支撑/阻力/目标推导）
    if scenarios:
        supports = [s.get('key_support') for s in scenarios if isinstance(s.get('key_support'), (int, float))]
        resistances = [s.get('key_resistance') for s in scenarios if isinstance(s.get('key_resistance'), (int, float))]
        targets = [s.get('target') for s in scenarios if s.get('target') and s.get('_bullish')]
        supports = sorted(set(supports))
        resistances = sorted(set(resistances))
        cur = elliott_analysis.get('current_price')
        ops = []
        if supports:
            # 取当前价下方的最近支撑 + 下方更深支撑
            below = [s for s in supports if isinstance(cur, (int, float)) and s < cur]
            nearest = below[-1] if below else (supports[0] if supports else None)
            ops.append(f"支撑带：{', '.join(f'{s:.2f}' for s in supports)}")
        if resistances:
            above = [r for r in resistances if isinstance(cur, (int, float)) and r > cur]
            nearest_r = above[0] if above else (resistances[-1] if resistances else None)
            ops.append(f"阻力带：{', '.join(f'{r:.2f}' for r in resistances)}")
        if targets:
            ops.append(f"目标位：{' / '.join(str(t) for t in targets[:2])}")
        if supports:
            # 失效位 = 最下方支撑（跌破则结构失效）
            ops.append(f"失效位：{min(supports):.2f}（跌破则当前计数失效）")
        if ops:
            lines.append("")
            lines.append(f"- 操作要点：{'；'.join(ops)}")

    # 6. 评分依据
    rationale = elliott_analysis.get('score_rationale', '')
    if rationale:
        lines.append(f"- 评分依据：{rationale}")

    lines.append("")
    return lines


def _generate_wave_chart_html(stock_name: str, stock_code: str, elliott_analysis) -> str:
    """生成个股波浪分析的自包含 HTML 图表（ECharts，月线 + 周线双图）。

    可视化：月线/周线收盘价曲线 + 波浪转折点标注 + 斐波那契/支撑/阻力/现价水平线。
    """
    if not isinstance(elliott_analysis, dict) or 'error' in elliott_analysis:
        return None

    def _series(series):
        return [m for m in (series or [])
                if isinstance(m, dict) and isinstance(m.get('close'), (int, float)) and m.get('date')]

    def _wave_points(points):
        return [w for w in (points or [])
                if isinstance(w, dict) and isinstance(w.get('price'), (int, float)) and w.get('date')]

    monthly = _series(elliott_analysis.get('monthly_series'))
    monthly_wave = _wave_points(elliott_analysis.get('wave_points'))
    weekly = _series(elliott_analysis.get('weekly_series'))
    weekly_wave = _wave_points(elliott_analysis.get('weekly_wave_points'))
    if not (monthly or weekly or monthly_wave or weekly_wave):
        return None

    fib_items = [(k, v) for k, v in (elliott_analysis.get('fib_levels') or {}).items() if isinstance(v, (int, float))]
    scenarios = elliott_analysis.get('scenarios', [])
    supports = sorted(set(s.get('key_support') for s in scenarios if isinstance(s.get('key_support'), (int, float))))
    resistances = sorted(set(s.get('key_resistance') for s in scenarios if isinstance(s.get('key_resistance'), (int, float))))
    current = elliott_analysis.get('current_price')

    data = {
        'title': f"{stock_name} ({stock_code}) 波浪结构",
        'monthly': monthly,
        'monthly_wave': monthly_wave,
        'weekly': weekly,
        'weekly_wave': weekly_wave,
        'fib': fib_items,
        'supports': supports,
        'resistances': resistances,
        'current': current,
    }

    return '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>body{{margin:0;font-family:-apple-system,"PingFang SC",sans-serif;background:#fafafa;}} h2{{text-align:center;margin:8px 0 4px;font-size:16px;}} .panel{{width:100vw;height:44vh;}}</style>
</head>
<body>
<h2>{title}</h2>
<div id="chartM" class="panel"></div>
<div id="chartW" class="panel"></div>
<script>
const data = {data_json};
const T = function(d) {{ return new Date(d).getTime(); }};

const fibLines = [];
data.fib.forEach(function(it) {{
    fibLines.push({{yAxis: it[1], lineStyle: {{type: 'dashed', color: '#999999'}}, label: {{formatter: it[0] + ' ' + it[1].toFixed(2), position: 'insideStartTop', fontSize: 9, color: '#666'}}}});
}});
const srLines = [];
data.supports.forEach(function(v) {{
    srLines.push({{yAxis: v, lineStyle: {{color: '#2e7d32'}}, label: {{formatter: '支撑 ' + v.toFixed(2), position: 'insideEndTop', fontSize: 9, color: '#2e7d32'}}}});
}});
data.resistances.forEach(function(v) {{
    srLines.push({{yAxis: v, lineStyle: {{color: '#c62828'}}, label: {{formatter: '阻力 ' + v.toFixed(2), position: 'insideEndTop', fontSize: 9, color: '#c62828'}}}});
}});
if (data.current != null) {{
    srLines.push({{yAxis: data.current, lineStyle: {{color: '#ef6c00'}}, label: {{formatter: '现价 ' + data.current.toFixed(2), position: 'insideEndTop', fontSize: 9, color: '#ef6c00'}}}});
}}

function buildOption(subtitle, series, wavePts) {{
    return {{
        title: {{text: subtitle, left: 'center', textStyle: {{fontSize: 13, color: '#555'}}}},
        tooltip: {{
            trigger: 'axis',
            axisPointer: {{type: 'cross'}},
            formatter: function(params) {{
                const lines = [];
                params.forEach(function(p) {{
                    if (p.seriesType === 'line' && p.value && p.value.length) {{
                        lines.push(new Date(p.value[0]).toISOString().slice(0,10) + ' 收盘: ' + p.value[1].toFixed(2));
                    }}
                    if (p.seriesType === 'scatter' && p.value) {{
                        lines.push(p.name + ' @ ' + p.value[1].toFixed(2));
                    }}
                }});
                return lines.join('<br/>');
            }}
        }},
        legend: {{data: ['收盘', '波浪转折点'], top: 22}},
        grid: {{left: 60, right: 50, top: 52, bottom: 48}},
        xAxis: {{type: 'time'}},
        yAxis: {{type: 'value', scale: true}},
        dataZoom: [
            {{type: 'inside', xAxisIndex: 0}},
            {{type: 'slider', xAxisIndex: 0, bottom: 4, height: 16}},
        ],
        series: [
            {{
                name: '收盘',
                type: 'line',
                data: series.map(function(m) {{ return [T(m.date), m.close]; }}),
                showSymbol: false,
                lineStyle: {{color: '#90a4ae', width: 1.5}},
                markLine: {{symbol: 'none', data: fibLines.concat(srLines), label: {{position: 'insideEndTop'}}}},
            }},
            {{
                name: '波浪转折点',
                type: 'scatter',
                data: wavePts.map(function(w) {{ return {{name: w.label, value: [T(w.date), w.price]}}; }}),
                symbolSize: 10,
                itemStyle: {{color: '#1e88e5'}},
                label: {{show: true, position: 'top', formatter: function(p) {{ return p.name; }}, fontSize: 10, color: '#333'}},
                labelLayout: {{hideOverlap: true}},
            }}
        ]
    }};
}}

const chartM = echarts.init(document.getElementById('chartM'));
chartM.setOption(buildOption('月线（大级别趋势）', data.monthly, data.monthly_wave));
const chartW = echarts.init(document.getElementById('chartW'));
chartW.setOption(buildOption('周线（中长期趋势）', data.weekly, data.weekly_wave));
window.addEventListener('resize', function() {{ chartM.resize(); chartW.resize(); }});
</script>
</body>
</html>'''.format(title=data['title'], data_json=json.dumps(data, ensure_ascii=False))


def _save_wave_chart(stock_name: str, stock_code: str, elliott_analysis, out_dir: Path) -> str:
    """保存个股波浪分析 HTML 图表，返回相对链接路径。"""
    html = _generate_wave_chart_html(stock_name, stock_code, elliott_analysis)
    if html is None:
        return None
    chart_dir = out_dir / "波浪图"
    chart_dir.mkdir(parents=True, exist_ok=True)
    safe_code = stock_code.replace('.', '_')
    chart_file = chart_dir / f"{safe_code}.html"
    chart_file.write_text(html, encoding='utf-8')
    return f"波浪图/{safe_code}.html"


def generate_md_report(json_file: Path):
    """从JSON文件生成MD报告"""
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    selection_date = data.get('selection_date', json_file.stem.split('_')[-1])
    generation_time = data.get('generation_time', '')

    favorable_industries = data.get('favorable_industries', [])
    recommendations = data.get('recommendations', [])
    summary = data.get('summary', {})

    # ETF数据
    etf_recommendations = data.get('etf_recommendations', [])
    etf_list = data.get('etf_list', [])

    # 底部资产数据
    bottom_assets = data.get('bottom_assets', {})

    md_lines = []

    # 标题
    md_lines.extend([
        f"# 每日选股报告 - {selection_date}",
        "",
        f"**生成时间**: {generation_time}",
        f"**分析日期**: {selection_date}",
        "",
    ])

    # 利好行业
    md_lines.extend([
        "## 📈 今日利好行业",
        ""
    ])

    for ind in favorable_industries:
        md_lines.extend([
            f"### {ind['name']} (权重: {ind.get('weight', 0):.2f})",
            "",
            f"{ind.get('reason', '')}",
            ""
        ])

    # 推荐股票
    if recommendations:
        md_lines.extend([
            "---",
            "",
            "## 📊 推荐股票",
            "",
        ])

        # 统计
        buy_count = len([r for r in recommendations if r.get('rating') in ['买入', '强烈推荐']])
        hold_count = len([r for r in recommendations if r.get('rating') == '持有'])
        total = len(recommendations)

        md_lines.extend([
            f"**总计**: {total}只股票 | 买入: {buy_count}只 | 持有: {hold_count}只",
            ""
        ])

        # 详细表格 - 优化格式显示层级关系（去掉微观买卖点评分）
        # 预先计算所有股票的新综合评分并排序
        for rec in recommendations:
            tech_analysis = rec.get('technical_analysis', {})
            tech_score = tech_analysis.get('score', 'N/A')

            elliott_analysis = rec.get('elliott_analysis', {})
            elliott_score = elliott_analysis.get('elliott_score', 'N/A')

            # 计算技术分析总分
            if tech_score != 'N/A' and elliott_score != 'N/A':
                technical_total = round(tech_score * 0.40 + elliott_score * 0.60, 1)
            elif tech_score != 'N/A':
                technical_total = round(tech_score, 1)
            else:
                technical_total = 'N/A'

            # 提取价值评分
            bb = rec.get('bull_bear_analysis', {})
            value_score = 'N/A'
            if 'dimension_bull_bear_score' in bb:
                dim_bb = bb['dimension_bull_bear_score']
                value_raw = dim_bb.get('bull_bear_score', 'N/A')
                value_score = round(value_raw, 1) if value_raw != 'N/A' else 'N/A'

            # Always try to get FOT and compute fallback value_score from dimension_scores
            if 'dimension_scores' in bb:
                dim_scores = bb['dimension_scores']
                if isinstance(dim_scores, dict):
                    company = dim_scores.get('company_quality', {})
                    trend = dim_scores.get('trend', {})
                    valuation = dim_scores.get('valuation', {})

                    is_friend_of_time = company.get('is_friend_of_time', False) if isinstance(company, dict) else False
                    # 保存时间的朋友标记
                    rec['is_friend_of_time'] = is_friend_of_time

                    # Fallback: compute value_score from dimension_scores if not already set
                    if value_score == 'N/A':
                        company_raw = company.get('score', 'N/A') if isinstance(company, dict) else 'N/A'
                        company_score = round(company_raw, 1) if company_raw != 'N/A' else 'N/A'
                        trend_raw = trend.get('score', 'N/A') if isinstance(trend, dict) else 'N/A'
                        trend_score_dim = round(trend_raw, 1) if trend_raw != 'N/A' else 'N/A'
                        valuation_raw = valuation.get('score', 'N/A') if isinstance(valuation, dict) else 'N/A'
                        valuation_score = round(valuation_raw, 1) if valuation_raw != 'N/A' else 'N/A'
                        if company_score != 'N/A' and trend_score_dim != 'N/A' and valuation_score != 'N/A':
                            dim_total = round(company_score * 0.45 + trend_score_dim * 0.3 + valuation_score * 0.25, 1)
                            value_score = dim_total

            # 计算新的综合评分（技术40% + 价值60%）
            if technical_total != 'N/A' and value_score != 'N/A':
                combined_new = round(technical_total * 0.40 + value_score * 0.60, 1)
            elif technical_total != 'N/A':
                combined_new = round(technical_total, 1)
            else:
                combined_new = 'N/A'

            # 保存新计算的综合评分
            rec['_new_combined_score'] = combined_new

            # 根据新的综合评分重新计算评级
            if combined_new != 'N/A':
                tech_positive = tech_score > 0 if tech_score != 'N/A' else False
                bull_positive = value_score > 1.5 if value_score != 'N/A' else False
                both_positive = tech_positive and bull_positive

                if combined_new >= 7.0 and both_positive:
                    new_rating = "强烈推荐"
                elif combined_new >= 5.0:
                    new_rating = "推荐"
                elif combined_new >= 0.0:
                    new_rating = "中性"
                elif combined_new >= -4.0:
                    new_rating = "不推荐"
                else:
                    new_rating = "强烈不推荐"

                # Elliott强烈看空时限制最高评级为"中性"
                if elliott_score != 'N/A' and elliott_score <= -6:
                    rating_order = {"强烈推荐": 0, "推荐": 1, "中性": 2, "不推荐": 3, "强烈不推荐": 4}
                    if rating_order.get(new_rating, 2) < rating_order["中性"]:
                        new_rating = "中性"

                rec['_new_rating'] = new_rating
            else:
                rec['_new_rating'] = rec.get('rating', 'N/A')

        # 按新的综合评分排序（从高到低）
        recommendations.sort(key=lambda x: (
            x.get('_new_combined_score', 'N/A') if isinstance(x.get('_new_combined_score', 'N/A'), (int, float)) else -999
        ), reverse=True)

        md_lines.extend([
            "### 📊 综合评分排行榜",
            "",
            "**📈 评分体系结构**：",
            "```",
            "综合评分100%",
            "├── 🔬 技术分析40%",
            "│   ├── 📊 短期时机40%",
            "│   └── 📈 中期趋势60%",
            "└── 💼 价值分析60%",
            "    ├── 🏢 好公司45%",
            "    ├── 📊 趋势30%",
            "    └── 💰 估值25%",
            "```",
            "",
            "**💡 符号说明**：⏰=时间的朋友（长期优质企业） **数字↑**=高分(≥7) **数字↓**=低分(≤2) 普通=中等(2-7)",
            "",
            "| # | 名称 | 代码 | 综合100% | 🔬技术40% | 💼价值60% | 📊短期40% | 📈中期60% | 🔄缠论走势 | 🏢好公司45% | 📊趋势30% | 💰估值25% | 评级 |",
            "|:--|:------|:------|:---------:|:---------:|:---------:|:---------:|:---------:|:---------:|:----------:|:----------:|:---------:|:------|",
        ])

        for i, rec in enumerate(recommendations, 1):
            name = rec.get('stock_name', 'N/A')
            code = rec.get('stock_code', 'N/A')
            combined = rec.get('_new_combined_score', 'N/A')  # 使用新计算的综合评分
            rating = rec.get('_new_rating', rec.get('rating', 'N/A'))  # 使用新计算的评级
            is_friend = rec.get('is_friend_of_time', False)

            # 高亮时间的朋友
            if is_friend:
                name = f"**⏰{name}**"

            tech_analysis = rec.get('technical_analysis', {})
            tech_score = tech_analysis.get('score', 'N/A')

            elliott_analysis = rec.get('elliott_analysis', {})
            elliott_score = elliott_analysis.get('elliott_score', 'N/A')

            chan_analysis = rec.get('chan_analysis', {})
            chan_score = chan_analysis.get('chan_score', 'N/A')

            # 计算技术分析总分（去掉微观买卖点）
            if tech_score != 'N/A' and elliott_score != 'N/A':
                technical_total = round(tech_score * 0.40 + elliott_score * 0.60, 1)
            elif tech_score != 'N/A':
                technical_total = round(tech_score, 1)
            else:
                technical_total = 'N/A'

            # 提取缠论买卖点/走势信息
            chan_analysis = rec.get('chan_analysis', {})
            chan_info = _extract_chan_signal(chan_analysis)

            # 提取价值评分详情（原三维评分）
            bb = rec.get('bull_bear_analysis', {})
            value_score = 'N/A'
            company_score = 'N/A'
            trend_score = 'N/A'
            valuation_score = 'N/A'

            # Get bull_bear_score from dimension_bull_bear_score (if available)
            if 'dimension_bull_bear_score' in bb:
                dim_bb = bb['dimension_bull_bear_score']
                value_raw = dim_bb.get('bull_bear_score', 'N/A')
                value_score = round(value_raw, 1) if value_raw != 'N/A' else 'N/A'

            # Get company/trend/valuation breakdown from dimension_scores (always try this)
            if 'dimension_scores' in bb:
                dim_scores = bb['dimension_scores']
                if isinstance(dim_scores, dict):
                    company = dim_scores.get('company_quality', {})
                    trend = dim_scores.get('trend', {})
                    valuation = dim_scores.get('valuation', {})

                    company_raw = company.get('score', 'N/A') if isinstance(company, dict) else 'N/A'
                    company_score = round(company_raw, 1) if company_raw != 'N/A' else 'N/A'
                    trend_raw = trend.get('score', 'N/A') if isinstance(trend, dict) else 'N/A'
                    trend_score = round(trend_raw, 1) if trend_raw != 'N/A' else 'N/A'
                    valuation_raw = valuation.get('score', 'N/A') if isinstance(valuation, dict) else 'N/A'
                    valuation_score = round(valuation_raw, 1) if valuation_raw != 'N/A' else 'N/A'

                    # 计算综合价值评分 (fallback if value_score still N/A)
                    if value_score == 'N/A' and company_score != 'N/A' and trend_score != 'N/A' and valuation_score != 'N/A':
                        dim_total = round(company_score * 0.45 + trend_score * 0.3 + valuation_score * 0.25, 1)
                        value_score = dim_total

            # 重新计算综合评分（使用新的权重）
            if technical_total != 'N/A' and value_score != 'N/A':
                combined_new = round(technical_total * 0.50 + value_score * 0.50, 1)
            elif technical_total != 'N/A':
                combined_new = round(technical_total, 1)
            else:
                combined_new = 'N/A'

            # 应用标记
            combined_colored = _color_score(combined_new)
            tech_total_colored = _color_score(technical_total)
            value_colored = _color_score(value_score)
            tech_colored = _color_score(tech_score)
            elliott_colored = _color_score(elliott_score)
            company_colored = _color_score(company_score)
            trend_colored = _color_score(trend_score)
            valuation_colored = _color_score(valuation_score)

            # Markdown表格数据行（缠论信号不使用颜色标记）
            md_lines.append(
                f"| {i} | {name} | {code} | {combined_colored} | {tech_total_colored} | {value_colored} | {tech_colored} | {elliott_colored} | {chan_info} | {company_colored} | {trend_colored} | {valuation_colored} | {rating} |"
            )

        md_lines.append("")

        # 时间的朋友评估汇总（从recommendations读取，包含完整bull_bear_analysis数据）
        friend_of_time_count = 0
        for r in recommendations:
            bb_check = r.get('bull_bear_analysis', {})
            ds_check = bb_check.get('dimension_scores', {})
            cq_check = ds_check.get('company_quality', {})
            if isinstance(cq_check, dict) and cq_check.get('is_friend_of_time'):
                friend_of_time_count += 1

        fot_total = len(recommendations)

        # Build FOT data map from recommendations (which have full dimension_scores)
        stock_fot_map = {}
        for r in recommendations:
            bb = r.get('bull_bear_analysis', {})
            ds = bb.get('dimension_scores', {}) if isinstance(bb, dict) else {}
            cq = ds.get('company_quality', {}) if isinstance(ds, dict) else {}
            stock_fot_map[r.get('stock_code', '')] = {
                'is_friend': cq.get('is_friend_of_time', False) if isinstance(cq, dict) else False,
                'sub_scores': cq.get('sub_scores', {}) if isinstance(cq, dict) else {},
                'reasoning': cq.get('reasoning', '') if isinstance(cq, dict) else '',
            }

        for rec in recommendations:
            code = rec.get('stock_code', '')
            if code in stock_fot_map:
                rec['is_friend_of_time'] = stock_fot_map[code]['is_friend']
                rec['_fot_data'] = stock_fot_map[code]

        md_lines.extend([
            "",
            "### ⏰ 时间的朋友评估",
            "",
            f"**时间的朋友通过率**: {friend_of_time_count}/{fot_total} ({friend_of_time_count/fot_total*100:.0f}%)" if fot_total > 0 else "",
            "",
            "**判断标准**（三项同时满足）：",
            "- 💼 **商业模式穿越周期** ≥ 5分（权重40%）：ROE均值与稳定性、现金流质量、毛利率稳定性、资本开支效率",
            "- 🏛️ **企业文化抵御人性** ≥ 4分（权重30%）：分红回购比例、研发投入、商誉占比、管理层诚信",
            "- 🧠 **可理解性/能力圈** ≥ 5分（权重30%）：业务集中度、业务复杂度、盈利可预测性",
            "",
            "> 表中 ⏰ 标记即表示该企业同时满足以上三项标准，具备长期复利增长的基础特质。",
            "",
        ])

        # 时间的朋友通过/未通过清单（从recommendations读取完整数据）
        fot_stocks = []
        non_fot_stocks = []

        for r in recommendations:
            bb = r.get('bull_bear_analysis', {})
            if not isinstance(bb, dict):
                continue
            ds = bb.get('dimension_scores', {})
            if not isinstance(ds, dict):
                continue
            cq = ds.get('company_quality', {})
            if not isinstance(cq, dict):
                continue
            is_fot = cq.get('is_friend_of_time', True)
            sub = _extract_company_subscores(cq)
            entry = {
                'name': r.get('stock_name', 'N/A'),
                'code': r.get('stock_code', 'N/A'),
                'score': cq.get('score', 'N/A'),
                'business_model': sub.get('business_model', 'N/A'),
                'corporate_culture': sub.get('corporate_culture', sub.get('corporate_governance', 'N/A')),
                'understandability': sub.get('understandability', 'N/A'),
                'reasoning': cq.get('reasoning', ''),
                'rating': bb.get('investment_rating', 'N/A'),
            }
            if is_fot:
                fot_stocks.append(entry)
            else:
                non_fot_stocks.append(entry)

        # Sort FOT stocks by score descending (best first)
        fot_stocks.sort(key=lambda x: x['score'] if isinstance(x['score'], (int, float)) else -99, reverse=True)
        # Sort non-FOT by score descending (best first)
        non_fot_stocks.sort(key=lambda x: x['score'] if isinstance(x['score'], (int, float)) else -99, reverse=True)

        # FOT passing table (show specific scores)
        if fot_stocks:
            md_lines.extend([
                "",
                "### ✅ 通过时间的朋友筛选的股票",
                "",
                "以下股票同时满足三项标准：",
                "",
                "| # | 名称 | 代码 | 公司质量分 | 综合评级 | 💼商业模式(≥5) | 🏛️企业文化(≥4) | 🧠可理解性(≥5) |",
                "|:--|:------|:------|:----:|:--------:|:-------------:|:-------------:|:-------------:|",
            ])
            for i, s in enumerate(fot_stocks, 1):
                def _fmt_fot(val):
                    if isinstance(val, (int, float)):
                        return _color_score(round(val, 1))
                    return '—'
                score_str = _color_score(round(s['score'], 1)) if isinstance(s['score'], (int, float)) else 'N/A'
                md_lines.append(
                    f"| {i} | {s['name']} | {s['code']} | {score_str} | {s['rating']} | "
                    f"{_fmt_fot(s['business_model'])} | {_fmt_fot(s['corporate_culture'])} | "
                    f"{_fmt_fot(s['understandability'])} |"
                )
            md_lines.append("")

        # Non-FOT table
        if non_fot_stocks:
            md_lines.extend([
                "",
                "### ⚠️ 未通过时间的朋友筛选的股票",
                "",
                "以下股票未同时满足三项标准：",
                "",
                "| # | 名称 | 代码 | 公司质量分 | 综合评级 | 💼商业模式(≥5) | 🏛️企业文化(≥4) | 🧠可理解性(≥5) | 未通过原因 |",
                "|:--|:------|:------|:----:|:--------:|:-------------:|:-------------:|:-------------:|:----------|",
            ])
            for i, s in enumerate(non_fot_stocks, 1):
                def _fmt_sub(val):
                    if isinstance(val, (int, float)):
                        return _color_score(round(val, 1))
                    return '—'  # Use dash instead of N/A for missing
                bm = _fmt_sub(s['business_model'])
                cc = _fmt_sub(s['corporate_culture'])
                ud = _fmt_sub(s['understandability'])
                # Truncate reasoning only if excessively long (>300 chars)
                reason = s['reasoning']
                if len(reason) > 300:
                    reason = reason[:300] + '...'
                score_str = _color_score(round(s['score'], 1)) if isinstance(s['score'], (int, float)) else 'N/A'
                md_lines.append(
                    f"| {i} | {s['name']} | {s['code']} | {score_str} | {s['rating']} | {bm} | {cc} | {ud} | {reason} |"
                )
            md_lines.append("")
        else:
            md_lines.extend([
                "",
                "> ✅ 所有推荐股票均通过了时间的朋友筛选。",
                "",
            ])

        # 详细分析部分
        md_lines.extend([
            "---",
            "",
            "### 🎯 详细分析",
            ""
        ])

        for i, rec in enumerate(recommendations[:20], 1):  # 显示前20只
            name = rec.get('stock_name', 'N/A')
            code = rec.get('stock_code', 'N/A')
            combined = rec.get('_new_combined_score', 'N/A')  # 使用新计算的综合评分
            rating = rec.get('_new_rating', rec.get('rating', 'N/A'))  # 使用新计算的评级

            tech_analysis = rec.get('technical_analysis', {})
            tech_score_raw = tech_analysis.get('score', 'N/A')
            try:
                tech_score = float(tech_score_raw)
            except (TypeError, ValueError):
                tech_score = tech_score_raw if tech_score_raw == 'N/A' else 0.0

            elliott_analysis = rec.get('elliott_analysis', {})
            elliott_score_raw = elliott_analysis.get('elliott_score', 'N/A')
            try:
                elliott_score = float(elliott_score_raw)
            except (TypeError, ValueError):
                elliott_score = elliott_score_raw if elliott_score_raw == 'N/A' else 0.0

            chan_analysis = rec.get('chan_analysis', {})
            chan_score = chan_analysis.get('chan_score', 'N/A')

            bb_analysis = rec.get('bull_bear_analysis', {})

            # 生成技术分析解读
            tech_situation = tech_analysis.get("situation", {})
            tech_type = tech_situation.get("type", "")
            tech_description = tech_situation.get("description", "")

            tech_interpretations = {
                "情况4": "日线级别股价强势，量能萎缩，筹码锁定良好",
                "情况3": "日线级别股价强势且量能放大，波段机会明显",
                "情况2": "日线级别股价突破且量价齐升，短线动能较强",
                "情况1": "日线级别股价弱势且量能不足，短期缺乏机会",
            }
            tech_text = tech_interpretations.get(tech_type, tech_description)

            # 生成中期趋势解读
            if elliott_analysis and isinstance(elliott_analysis, dict):
                wave_position = elliott_analysis.get("wave_position", "")
                wave_trend = elliott_analysis.get("trend", "")

                trend_interpretations = {
                    "主升浪": "处于主升浪阶段，中期上涨趋势明确",
                    "ABC调整反弹": "处于ABC调整反弹阶段，中期趋势不明",
                    "调整浪": "处于调整浪阶段，中期偏弱",
                }
                trend_text = trend_interpretations.get(wave_position, f"波浪位置：{wave_position}")
                if wave_trend:
                    trend_text += f"，趋势：{wave_trend}"
            else:
                trend_text = "无波浪分析数据"

            # 生成缠论信号解读
            if chan_analysis and isinstance(chan_analysis, dict):
                # JSON数据中实际的字段名是 active_buys 和 active_sells
                chan_buy_points = chan_analysis.get("active_buys", [])
                chan_sell_points = chan_analysis.get("active_sells", [])

                if chan_buy_points:
                    chan_text = f"30分钟级别检测到{len(chan_buy_points)}个买点，微观结构偏向买方"
                elif chan_sell_points:
                    chan_text = f"30分钟级别检测到{len(chan_sell_points)}个卖点，微观结构偏向卖方"
                else:
                    # 无买卖点，根据中枢位置判断走势
                    last_pivot = chan_analysis.get("last_pivot", {})
                    current_price = chan_analysis.get("current_price", 0)

                    if last_pivot and current_price > 0:
                        zg = last_pivot.get("ZG", 0)  # 中枢上沿
                        zd = last_pivot.get("ZD", 0)  # 中枢下沿

                        if zg > 0 and zd > 0:
                            if current_price > zg:
                                chan_text = f"30分钟级别价格在中枢上方（{zg:.2f}），可能向上突破"
                            elif current_price < zd:
                                chan_text = f"30分钟级别价格在中枢下方（{zd:.2f}），可能向下调整"
                            else:
                                chan_text = f"30分钟级别价格在中枢内[{zd:.2f},{zg:.2f}]盘整"
                        else:
                            chan_text = "30分钟级别无明显买卖点，微观结构中性"
                    else:
                        chan_text = "30分钟级别无明显买卖点，微观结构中性"
            else:
                chan_text = "无缠论分析数据"

            # 生成整体解读
            overall_parts = []
            if isinstance(tech_score, (int, float)):
                if tech_score >= 5:
                    overall_parts.append("短期技术面强势")
                elif tech_score <= 2:
                    overall_parts.append("短期技术面偏弱")

            if isinstance(elliott_score, (int, float)):
                if elliott_score >= 5:
                    overall_parts.append("中期趋势向上")
                elif elliott_score <= -3:
                    overall_parts.append("中期趋势偏弱")
                else:
                    overall_parts.append("中期处于震荡整理")
            else:
                overall_parts.append("中期处于震荡整理")

            # 使用正确的字段名检查买卖点
            if chan_analysis and isinstance(chan_analysis, dict):
                active_buys = chan_analysis.get("active_buys", [])
                if active_buys:
                    overall_parts.append("微观层面有明确买点")

            if isinstance(tech_score, (int, float)) and isinstance(elliott_score, (int, float)):
                if tech_score >= 5 and elliott_score >= 0:
                    overall_parts.append("技术面整体向好")
                elif tech_score <= 2 and elliott_score <= -3:
                    overall_parts.append("技术面整体偏弱")

            overall_text = "；".join(overall_parts) if overall_parts else "技术面多空交织"

            # 格式化评分并添加颜色
            tech_score_rounded = round(tech_score, 1) if isinstance(tech_score, (int, float)) else 'N/A'
            elliott_score_rounded = round(elliott_score, 1) if isinstance(elliott_score, (int, float)) else 'N/A'

            tech_colored = _color_score(tech_score_rounded)
            elliott_colored = _color_score(elliott_score_rounded)

            md_lines.extend([
                f"**{i}. {name} ({code})** - {rating}",
                "",
                f"**技术分析详情**:",
                f"- 短期时机评分 {tech_colored}：{tech_text}",
                f"- 中期趋势评分 {elliott_colored}：{trend_text}",
                f"- 缠论信号：{chan_text}",
                f"- **解读**：{overall_text}。",
                ""
            ])

            # 波浪分析详情（对标指数波浪分析报告的完整结构）
            md_lines.extend(_render_elliott_detail(elliott_analysis))

            # 波浪分析可视化 HTML 图 + 链接
            chart_link = _save_wave_chart(name, code, elliott_analysis, json_file.parent)
            if chart_link:
                md_lines.append(f"- 📈 [查看波浪结构图]({chart_link})")
                md_lines.append("")

            # 价值评分详情（原三维评分）
            if 'dimension_bull_bear_score' in bb_analysis:
                dim_bb = bb_analysis['dimension_bull_bear_score']
                breakdown = dim_bb.get('dimension_breakdown', {})

                value_raw = dim_bb.get('bull_bear_score', 'N/A')
                value_rounded = round(value_raw, 1) if value_raw != 'N/A' else 'N/A'
                company_raw = breakdown.get('company_quality', 'N/A')
                company_rounded = round(company_raw, 1) if company_raw != 'N/A' else 'N/A'
                trend_raw = breakdown.get('trend', 'N/A')
                trend_rounded = round(trend_raw, 1) if trend_raw != 'N/A' else 'N/A'
                valuation_raw = breakdown.get('valuation', 'N/A')
                valuation_rounded = round(valuation_raw, 1) if valuation_raw != 'N/A' else 'N/A'

                value_colored = _color_score(value_rounded)
                company_colored = _color_score(company_rounded)
                trend_colored = _color_score(trend_rounded)
                valuation_colored = _color_score(valuation_rounded)

                md_lines.extend([
                    f"**价值评分详情**:",
                    f"- 价值评分 {value_colored} (好公司: {company_colored}, 趋势: {trend_colored}, 估值: {valuation_colored})",
                    f"- 信心水平: {dim_bb.get('confidence_level', 'N/A')}",
                    ""
                ])
            elif 'dimension_scores' in bb_analysis:
                dim_scores = bb_analysis['dimension_scores']

                # 提取各维度评分
                company_quality = dim_scores.get('company_quality', {})
                trend = dim_scores.get('trend', {})
                valuation = dim_scores.get('valuation', {})

                company_raw = company_quality.get('score', 'N/A') if isinstance(company_quality, dict) else 'N/A'
                company_score = round(company_raw, 1) if company_raw != 'N/A' else 'N/A'
                trend_raw = trend.get('score', 'N/A') if isinstance(trend, dict) else 'N/A'
                trend_score_dim = round(trend_raw, 1) if trend_raw != 'N/A' else 'N/A'
                valuation_raw = valuation.get('score', 'N/A') if isinstance(valuation, dict) else 'N/A'
                valuation_score = round(valuation_raw, 1) if valuation_raw != 'N/A' else 'N/A'

                # 计算综合价值评分
                if company_score != 'N/A' and trend_score_dim != 'N/A' and valuation_score != 'N/A':
                    dim_total = round(company_score * 0.45 + trend_score_dim * 0.3 + valuation_score * 0.25, 1)
                else:
                    dim_total = 'N/A'

                # 应用颜色高亮
                value_colored = _color_score(dim_total)
                company_colored = _color_score(company_score)
                trend_colored = _color_score(trend_score_dim)
                valuation_colored = _color_score(valuation_score)

                md_lines.extend([
                    f"**价值评分详情**:",
                    f"- 价值评分 {value_colored}",
                    f"  - 🏢 好公司 {company_colored}：{company_quality.get('reasoning', '')[:80] if isinstance(company_quality, dict) else ''}...",
                    f"  - 📈 趋势 {trend_colored}：{trend.get('reasoning', '')[:80] if isinstance(trend, dict) else ''}...",
                    f"  - 💰 估值 {valuation_colored}：{valuation.get('reasoning', '')[:80] if isinstance(valuation, dict) else ''}...",
                ])

                # 显示时间的朋友评估详情
                if isinstance(company_quality, dict):
                    is_fot = company_quality.get('is_friend_of_time', False)
                    sub_scores = _extract_company_subscores(company_quality)
                    if is_fot:
                        md_lines.append(f"  - ✅ 时间的朋友：**是**（三项标准全部达标）")
                    else:
                        md_lines.append(f"  - ❌ 时间的朋友：**否**（未同时满足三项标准）")

                    # 显示子维度评分（如果存在）
                    if sub_scores:
                        sub_labels = {
                            'business_model': '💼 商业模式',
                            'corporate_culture': '🏛️ 企业文化',
                            'understandability': '🧠 可理解性',
                            'corporate_governance': '🏛️ 公司治理',
                            'innovation_capability': '💡 创新能力',
                            'financial_health': '💰 财务健康',
                            'profitability': '📊 盈利能力',
                            'competitiveness': '🏆 竞争力',
                            'competitive_barrier': '🛡️ 竞争壁垒',
                        }
                        sub_parts = []
                        for key, val in sub_scores.items():
                            label = sub_labels.get(key, key)
                            sub_colored = _color_score(round(val, 1))
                            sub_parts.append(f"{label}: {sub_colored}")
                        if sub_parts:
                            md_lines.append(f"    评分组成: {' | '.join(sub_parts)}")
                    md_lines.append(f"    综合判断: {company_quality.get('reasoning', 'N/A')[:120]}")

                # 显示一票否决
                if isinstance(company_quality, dict) and company_quality.get('veto_triggered'):
                    md_lines.append(f"  - 🚨 一票否决：触发 - {company_quality.get('veto_reason', '')}")

                md_lines.append("")

            # 综合评分说明
            combined_rounded = round(combined, 1) if combined != 'N/A' else 'N/A'
            combined_colored_final = _color_score(combined_rounded)
            md_lines.extend([
                f"**综合评分**: {combined_colored_final} = 技术分析50% + 价值分析50%",
                ""
            ])

    # ETF基金
    if etf_recommendations:
        md_lines.extend([
            "---",
            "",
            "## 📈 ETF基金推荐",
            ""
        ])

        for i, etf in enumerate(etf_recommendations, 1):
            name = etf.get('stock_name', 'N/A')
            code = etf.get('stock_code', 'N/A')
            rating = etf.get('rating', 'N/A')
            combined = etf.get('combined_score', 'N/A')

            md_lines.extend([
                f"**{i}. {name} ({code})** - {rating}",
                f"- 综合评分: {combined:.2f}",
                ""
            ])

    elif etf_list:
        md_lines.extend([
            "---",
            "",
            "## ETF基金（仅列表）",
            "",
            "| # | 名称 | 代码 |",
            "|---|------|------|",
        ])

        for i, etf in enumerate(etf_list, 1):
            md_lines.append(
                f"| {i} | {etf.get('stock_name', 'N/A')} | {etf['stock_code']} |"
            )

        md_lines.append("")

    # 底部资产
    if bottom_assets and bottom_assets.get('ranked_assets'):
        md_lines.extend([
            "---",
            "",
            "## 🔍 周金涛底部资产筛选",
            ""
        ])

        ranked = bottom_assets.get('ranked_assets', [])
        for i, asset in enumerate(ranked[:10], 1):
            name = asset.get('name', 'N/A')
            code = asset.get('code', 'N/A')
            change_pct = asset.get('gain_pct', 'N/A')
            score = asset.get('composite_score', 'N/A')
            rating = asset.get('rating', 'N/A')
            industry = asset.get('industry', 'N/A')

            md_lines.extend([
                f"{i}. **{name} ({code})** - {rating}",
                f"   - 行业: {industry} | 相对2019底部: {change_pct}% | 综合评分: {score}",
                ""
            ])

    # 汇总统计
    chan_fetch_failed = len([
        r for r in recommendations
        if isinstance(r.get('chan_analysis'), dict)
        and r.get('chan_analysis', {}).get('success') is False
        and '数据获取失败' in str(r.get('chan_analysis', {}).get('error', ''))
    ])
    md_lines.extend([
        "---",
        "",
        "## 📊 汇总统计",
        "",
        f"- 分析股票: {len(recommendations)}只",
        f"- 推荐买入: {summary.get('total_recommended', 0)}只",
        f"- 平均评分: {summary.get('avg_score', 0):.2f}",
    ])
    if chan_fetch_failed > 0:
        md_lines.append(
            f"- ⚠️ 缠论取数失败: {chan_fetch_failed}只（多为港股网络波动），建议重跑以补全中枢数据"
        )
    md_lines.append("")

    # 评分体系说明
    md_lines.extend([
        "---",
        "",
        "## 📝 新评分体系说明",
        "",
        "### 🎨 颜色标记说明",
        "",
        "- 🟢 **绿色**：高分（≥7.0分）- 表现优秀",
        "- 🟡 **黄色**：中等分数（2.0-7.0分）- 表现一般",
        "- 🔴 **红色**：低分（≤2.0分）- 表现较差",
        "",
        "### 综合评分构成（技术分析50% + 价值分析50%）",
        "",
        "**综合评分 = 技术分析 × 50% + 价值分析 × 50%**",
        "",
        "### 技术分析维度（50%）",
        "",
        "**技术分析 = 短期时机 × 40% + 中期趋势 × 60%**",
        "",
        "- **短期时机评分**（原技术评分）：基于25日均线和成交量分析（0-10分）",
        "  - 量价时空四维融合：价35% + 量25% + 时20% + 空20%",
        "  - 量价共振加成：价+量同时看多时+1.5分",
        "",
        "- **中期趋势评分**（原波浪评分）：基于艾略特波浪理论（-10到+10分）",
        "  - 波浪位置识别：主升浪、调整浪、ABC反弹等",
        "  - 趋势判断：上涨、下跌、震荡",
        "  - 市场共振：强共振、弱共振、无共振",
        "  - EMA平滑处理：70%当前 + 30%历史",
        "",
        "- **缠论信号**（不参与评分，仅作参考）：基于缠论买卖点分析",
        "  - 基于30分钟K线分析",
        "  - 买卖点识别：一买、二买、三买等",
        "  - 背驰信号：顶背驰、底背驰",
        "  - 中枢位置和突破方向",
        "  - 无买卖点时显示走势：上升/下降/震荡",
        "",
        "### 价值分析维度（50%）",
        "",
        "**价值分析 = 好公司 × 45% + 趋势 × 30% + 估值 × 25%**",
        "",
        "- **好公司评分**：商业模式(40%) + 公司治理(30%) + 财务实力(30%)",
        "- **趋势评分**：行业周期(40%) + 公司增长(40%) + 市场情绪(20%)",
        "- **估值评分**：绝对估值(35%) + 相对估值(35%) + 安全边际(30%)",
        "",
        "### 评分体系关系",
        "",
        "1. **技术分析**（短期时机 + 中期趋势）→ 判断买卖时机",
        "2. **价值分析**（好公司 + 趋势 + 估值）→ 判断投资价值",
        "3. **缠论信号**（买卖点/走势）→ 微观层面参考，不参与评分",
        "4. **综合评分** = 技术50% + 价值50% → 最终排序推荐",
        "",
        "### 投资评级标准",
        "",
        "- **强烈推荐**: 综合评分 ≥ 7分 + 技术面和基本面双看好",
        "- **推荐**: 综合评分 5-7分",
        "- **中性**: 综合评分 0-5分",
        "- **不推荐**: 综合评分 -4到0分",
        "- **强烈不推荐**: 综合评分 < -4分",
        "",
        "### 特殊限制机制",
        "",
        "- 中期趋势强烈看空时（波浪评分 ≤ -6分），限制最高评级为'中性'",
        "- 一票否决机制：非质量公司直接否决",
        "",
        "---",
        "",
        "## ⚠️ 免责声明",
        "",
        "- 本报告基于技术分析、价值分析和多维度数据综合生成",
        "- 投资需谨慎，请结合其他因素综合判断",
        "- 历史表现不代表未来收益，请根据自身风险承受能力投资",
        ""
    ])

    # 保存MD文件
    md_file = json_file.parent / f"{json_file.stem}.md"
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_lines))

    print(f"✅ 已生成: {md_file.name}")
    return True


def main():
    """主函数"""
    print("=" * 60)
    print("生成缺失的MD报告")
    print("=" * 60)
    print()

    daily_dir = settings.BASE_DIR / "每日选股"

    # 需要生成MD报告的日期
    dates_to_generate = ['2026-05-30', '2026-05-31', '2026-06-01']

    for date in dates_to_generate:
        json_file = daily_dir / f'每日选股_{date}.json'

        if not json_file.exists():
            print(f"⚠️ {date} - JSON文件不存在，跳过")
            continue

        print(f"📄 处理 {date}...")
        try:
            generate_md_report(json_file)
        except Exception as e:
            print(f"❌ {date} - 生成失败: {e}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 60)
    print("✅ MD报告生成完成")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    main()
