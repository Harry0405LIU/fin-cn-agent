#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
艾略特波浪图表生成模块
为6大指数生成多种浪型综合对比图
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.family'] = ['PingFang HK', 'STHeiti', 'Heiti TC', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


# ============================================================
# 通用绘图函数
# ============================================================

def add_analysis_box(fig, rect, reason_text, confirm_text, deny_text, bg_color='#F5F5F5'):
    ax_text = fig.add_axes(rect)
    ax_text.set_xlim(0, 1)
    ax_text.set_ylim(0, 1)
    ax_text.axis('off')
    bg = plt.Rectangle((0, 0), 1, 1, facecolor=bg_color, edgecolor='#999',
                        linewidth=0.8, transform=ax_text.transAxes, zorder=0)
    ax_text.add_patch(bg)
    ax_text.text(0.01, 0.92, "[分析原因]", fontsize=12, fontweight='bold',
                 color='#1565C0', va='top', transform=ax_text.transAxes)
    ax_text.text(0.01, 0.72, reason_text, fontsize=11, color='#333',
                 va='top', linespacing=1.5, transform=ax_text.transAxes)
    ax_text.text(0.01, 0.40, "[确认信号]", fontsize=12, fontweight='bold',
                 color='#1B5E20', va='top', transform=ax_text.transAxes)
    ax_text.text(0.13, 0.40, confirm_text, fontsize=11, color='#1B5E20',
                 va='top', linespacing=1.5, transform=ax_text.transAxes)
    ax_text.text(0.01, 0.18, "[否认信号]", fontsize=12, fontweight='bold',
                 color='#C62828', va='top', transform=ax_text.transAxes)
    ax_text.text(0.13, 0.18, deny_text, fontsize=11, color='#C62828',
                 va='top', linespacing=1.5, transform=ax_text.transAxes)


def draw_wave(ax, xs, ys, color, lw=2.5, ls='-'):
    ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, zorder=3)


def label(ax, x, y, text, color, fs=12, offset=(0, 0)):
    ax.annotate(text, xy=(x, y), xytext=(x + offset[0], y + offset[1]),
                fontsize=fs, color=color, fontweight='bold', ha='center', va='bottom', zorder=5)


def setup_chart(ax, title, xlim, ylim, ylabel='指数点位'):
    ax.set_title(title, fontsize=14, fontweight='bold', color='#1A237E', pad=8)
    ax.set_xlabel('年份', fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.grid(True, alpha=0.2)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.tick_params(labelsize=9)


def add_current_line(ax, price, xlim_right, y_offset=0):
    ax.axhline(y=price, color='#E91E63', linestyle='-', alpha=0.3, linewidth=0.8)
    ax.text(xlim_right - 0.2, price + y_offset, f'当前 {price:,.0f}',
            fontsize=8, color='#E91E63', ha='center', va='bottom')


# ============================================================
# 各指数波浪定义 & 绘图
# ============================================================

def generate_sse_chart(current_price, current_year, output_dir):
    """上证指数"""
    n = 4  # 4种可能性
    ch, th, gap = 0.115, 0.095, 0.008
    top_m, bot_m = 0.04, 0.02
    fh = 56
    fig = plt.figure(figsize=(24, fh))

    fig.text(0.5, 0.98, '上证指数 - 艾略特波浪多种浪型综合对比',
             fontsize=20, fontweight='bold', ha='center', va='top', color='#1A237E')
    fig.text(0.5, 0.965, f'当前: {current_price:,.0f} | 数据截至: {current_year}',
             fontsize=12, ha='center', va='top', color='#666')

    # 历史关键点
    xk = [1994, 2001, 2005, 2007.8, 2008.1, 2008.1, 2009, 2013, 2015.5, 2016, 2018, 2019, 2021, 2022.4, 2024.2, 2024.9, 2025.9, current_year]
    yk = [325, 2245, 998, 6124, 5522, 1664, 3478, 1849, 5178, 2638, 3587, 2440, 3731, 2863, 2635, 3674, 3220, current_price]
    xlim = (1994, current_year + 1)
    ylim = (0, 7000)
    xr = xlim[1]

    scenarios = []

    # --- S1: 第五大浪启动 ---
    s1 = {}
    s1['chart_rect'] = [0.06, 0.89, 0.88, ch]
    s1['text_rect'] = [0.06, 0.89 - ch - gap - th, 0.88, th]
    s1['title'] = '可能性1: 第五大浪启动 [25%]'
    s1['bg'] = '#E8F5E9'
    s1['draw'] = lambda ax: _sse_s1(ax, xk, yk, current_price, current_year)
    s1['reason'] = '从1994年325点起完成完整4浪推动: I浪至2245, II浪至998, III浪至6124, IV浪至1664。此后进入大型V浪,目前处于V浪子浪3末端或子浪5初期。若V浪延伸,目标可达5000-6000区域。成交量放大和持续突破支持V浪判断。'
    s1['confirm'] = '突破3700前高并站稳; 成交量持续放大; 回调不跌破3400'
    s1['deny'] = '跌破3400且无法收复; 在3700附近形成双顶; 量价背离明显'
    scenarios.append(s1)

    # --- S2: 中级推动浪第三浪 ---
    s2 = {}
    s2['chart_rect'] = [0.06, 0.67, 0.88, ch]
    s2['text_rect'] = [0.06, 0.67 - ch - gap - th, 0.88, th]
    s2['title'] = '可能性2: 中级推动浪第三浪 [35%]'
    s2['bg'] = '#E8F5E9'
    s2['draw'] = lambda ax: _sse_s2(ax, xk, yk, current_price, current_year)
    s2['reason'] = '从2019年2440点起的新推动浪结构清晰: 浪1至3731, 浪2回调至2635(924行情起点), 浪3正在运行中。当前处于浪3的延伸阶段,若3浪为最长浪则符合规则,动能指标和量能配合支持3浪延伸判断。'
    s2['confirm'] = '突破4000后持续加速上行; 回调幅度小于前次; MACD零轴上方金叉'
    s2['deny'] = '上涨动能减弱出现顶背离; 回调跌破3700支撑; 第三浪长度短于第一浪'
    scenarios.append(s2)

    # --- S3: B浪反弹接近尾声 ---
    s3 = {}
    s3['chart_rect'] = [0.06, 0.45, 0.88, ch]
    s3['text_rect'] = [0.06, 0.45 - ch - gap - th, 0.88, th]
    s3['title'] = '可能性3: B浪反弹接近尾声 [25%]'
    s3['bg'] = '#FFF3E0'
    s3['draw'] = lambda ax: _sse_s3(ax, xk, yk, current_price, current_year)
    s3['reason'] = '从2015年5178点起处于大型A-B-C调整中。A浪至2440, 当前B浪反弹至4000+区域接近A浪50%回撤位(3809)。B浪呈现三浪结构,在3700-4100区间反复受阻,动能逐步衰竭,符合B浪末端特征。C浪下跌目标2500-2800。'
    s3['confirm'] = '在4100-4200形成明显顶部; 随后跌破3700; C浪以5浪结构下行'
    s3['deny'] = '强势突破4200创新高; 回调后低点不断抬高; 突破4500(B浪假设失效)'
    scenarios.append(s3)

    # --- S4: 大三角形D浪见顶 ---
    s4 = {}
    s4['chart_rect'] = [0.06, 0.23, 0.88, ch]
    s4['text_rect'] = [0.06, 0.23 - ch - gap - th, 0.88, th]
    s4['title'] = '可能性4: 大三角形D浪见顶 [15%]'
    s4['bg'] = '#FFF3E0'
    s4['draw'] = lambda ax: _sse_s4(ax, xk, yk, current_price, current_year)
    s4['reason'] = '从2008年以来形成大型上升三角形: A浪6124, B浪1664, C浪5178, D浪正在运行。三角形特征为波动率逐步收窄,高低点振幅递减。当前在4000附近接近三角形上轨,若D浪见顶则E浪回调至3200-3400区域。'
    s4['confirm'] = '在4000-4100受阻回落; 波动率持续收窄; E浪下探至3200附近'
    s4['deny'] = '强势突破4200打破三角形; 波动率突然放大向上突破; 跌破3500(非三角形特征)'
    scenarios.append(s4)

    _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr)
    path = os.path.join(output_dir, '上证指数_多种浪型综合对比.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def _sse_s1(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='blue')
    draw_wave(ax, [1994, 2001], [325, 2245], '#1E88E5')
    draw_wave(ax, [2001, 2005], [2245, 998], '#EF5350')
    draw_wave(ax, [2005, 2007.8], [998, 6124], '#1E88E5')
    draw_wave(ax, [2007.8, 2008.1], [6124, 1664], '#EF5350')
    draw_wave(ax, [2008.1, cy], [1664, cp], '#43A047')
    label(ax, 1997, 325, 'I', '#1E88E5', 11, (0, -300))
    label(ax, 2003, 998, 'II', '#EF5350', 11, (0, -300))
    label(ax, 2006.5, 6124, 'III', '#1E88E5', 11, (0, 300))
    label(ax, 2007.5, 1664, 'IV', '#EF5350', 11, (0, -300))
    label(ax, 2016, 1664, 'V', '#43A047', 13, (0, -400))
    ax.annotate('', xy=(cy + 0.7, 5500), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 5500, 'V目标\n5000-6000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


def _sse_s2(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='green')
    draw_wave(ax, [2019, 2021], [2440, 3731], '#1E88E5')
    draw_wave(ax, [2021, 2024.2], [3731, 2635], '#EF5350')
    draw_wave(ax, [2024.2, cy], [2635, cp], '#43A047')
    label(ax, 2020, 2440, '1', '#1E88E5', 12, (0, -300))
    label(ax, 2022.5, 2635, '2', '#EF5350', 12, (0, -300))
    label(ax, 2025, 3731, '3', '#43A047', 14, (0, 300))
    ax.annotate('(i)', xy=(2024.9, 3674), fontsize=9, color='#43A047', ha='center', va='bottom')
    ax.annotate('(ii)', xy=(2025.9, 3220), fontsize=9, color='#43A047', ha='center', va='bottom')
    ax.annotate('', xy=(cy + 0.7, 5500), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 5500, '浪3目标\n4500-5000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


def _sse_s3(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='orange')
    draw_wave(ax, [2015.5, 2019], [5178, 2440], '#EF5350')
    draw_wave(ax, [2019, cy], [2440, cp], '#FF9800')
    draw_wave(ax, [cy, cy + 0.5, cy + 1, cy + 1.5], [cp, 3000, 3200, 2500], '#D32F2F', 2.0, '--')
    label(ax, 2017, 5178, 'A', '#EF5350', 14, (0, 300))
    label(ax, 2021, 2440, 'B', '#FF9800', 14, (0, -300))
    ax.text(cy + 1.5, 2500, 'C目标\n2500-2800', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')
    ax.axhline(y=3809, color='#FF9800', ls='--', alpha=0.5, lw=0.8)
    ax.text(1994.5, 3809, '50%回撤=3809', fontsize=8, color='#FF9800', va='bottom')
    ax.axhspan(3800, 4200, alpha=0.06, color='red')
    ax.text(2010, 4200, 'B浪顶部区域', fontsize=9, color='#D32F2F', ha='center', va='bottom')


def _sse_s4(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='purple')
    # Triangle: A=6124, B=1664, C=5178, D=current area
    draw_wave(ax, [2007.8, 2008.1], [6124, 1664], '#7E57C2')
    draw_wave(ax, [2008.1, 2015.5], [1664, 5178], '#7E57C2')
    draw_wave(ax, [2015.5, cy], [5178, cp], '#7E57C2')
    # Triangle boundary lines
    draw_wave(ax, [2007.8, 2015.5, cy], [6124, 5178, cp], '#9C27B0', 1.5, ':')
    draw_wave(ax, [2008.1, 2019, cy], [1664, 2440, cp], '#9C27B0', 1.5, ':')
    label(ax, 2008, 6124, 'A', '#7E57C2', 12, (0, 300))
    label(ax, 2009, 1664, 'B', '#7E57C2', 12, (0, -300))
    label(ax, 2016, 5178, 'C', '#7E57C2', 12, (0, 300))
    label(ax, cy - 1, cp, 'D', '#7E57C2', 12, (0, 300))
    ax.text(2012, 4000, '收敛三角形', fontsize=11, color='#9C27B0', ha='center', fontweight='bold', alpha=0.7)
    draw_wave(ax, [cy, cy + 0.5], [cp, 3300], '#D32F2F', 2.0, '--')
    ax.text(cy + 0.5, 3300, 'E浪目标\n3200-3400', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')


# --- 深证成指 ---
def generate_szse_chart(current_price, current_year, output_dir):
    fh = 46
    fig = plt.figure(figsize=(24, fh))
    fig.text(0.5, 0.98, '深证成指 - 艾略特波浪多种浪型综合对比',
             fontsize=20, fontweight='bold', ha='center', va='top', color='#1A237E')
    fig.text(0.5, 0.965, f'当前: {current_price:,.0f} | 数据截至: {current_year}',
             fontsize=12, ha='center', va='top', color='#666')

    xk = [2005, 2007.8, 2008.1, 2009, 2013, 2015.5, 2016, 2019, 2021, 2022.4, 2024.2, 2024.9, 2025.9, current_year]
    yk = [2590, 19600, 5577, 14000, 6950, 18211, 8986, 8557, 16293, 10087, 7958, 11864, 10100, current_price]
    xlim = (2005, current_year + 1)
    ylim = (0, 22000)
    xr = xlim[1]

    scenarios = [
        {'chart_rect': [0.06, 0.89, 0.88, 0.115], 'text_rect': [0.06, 0.795, 0.88, 0.095],
         'title': '可能性1: 新一轮推动浪第三浪 [30%]', 'bg': '#E8F5E9',
         'draw': lambda ax: _szse_s1(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2019年8557起的新推动浪: 浪1至16293, 浪2回调至7958, 浪3正在运行。当前处于浪3延伸阶段,成交额放大和市场广度改善支持推动浪判断。目标16000-18000。',
         'confirm': '突破15000持续上攻; 回调不破13000; 成交额持续放大',
         'deny': '跌破13000支撑; 在15000形成双顶; 第三浪短于第一浪'},

        {'chart_rect': [0.06, 0.67, 0.88, 0.115], 'text_rect': [0.06, 0.575, 0.88, 0.095],
         'title': '可能性2: 大型ABC调整B浪反弹 [40%]', 'bg': '#FFF3E0',
         'draw': lambda ax: _szse_s2(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2015年18211起处于大型A-B-C调整。A浪至7958, 当前B浪反弹至15000+区域,接近A浪50%回撤位(13105)。B浪三浪结构逐渐完成,在15000-16000区间动能减弱,符合B浪末期特征。C浪目标9000-10000。',
         'confirm': '在15500-16000受阻; 跌破13500后加速下行; C浪5浪结构清晰',
         'deny': '突破16000创新高; 低点不断抬高; 突破18000(B浪假设失效)'},

        {'chart_rect': [0.06, 0.45, 0.88, 0.115], 'text_rect': [0.06, 0.355, 0.88, 0.095],
         'title': '可能性3: 扩张平台调整完成新周期 [30%]', 'bg': '#E3F2FD',
         'draw': lambda ax: _szse_s3(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2008年5577起的5浪推动: I至19600, II至6950, III至18211。IV浪为扩张平台: A(18211->8557), B(8557->16293), C(16293->7958)。C浪终点在III浪4区域,IV浪完成。当前V浪初期,目标18000-20000。',
         'confirm': '持续突破15000; 回调低点不断抬高; V浪5浪推动结构清晰',
         'deny': '在15000反复受阻; 跌破12000; 形成更低的高点'},
    ]

    _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr)
    path = os.path.join(output_dir, '深证成指_多种浪型综合对比.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path

def _szse_s1(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='green')
    draw_wave(ax, [2019, 2021], [8557, 16293], '#1E88E5')
    draw_wave(ax, [2021, 2024.2], [16293, 7958], '#EF5350')
    draw_wave(ax, [2024.2, cy], [7958, cp], '#43A047')
    label(ax, 2020, 8557, '1', '#1E88E5', 12, (0, -800))
    label(ax, 2022.5, 7958, '2', '#EF5350', 12, (0, -800))
    label(ax, 2025, 16293, '3', '#43A047', 14, (0, 600))
    ax.annotate('', xy=(cy + 0.7, 18000), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 18000, '浪3目标\n16000-18000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')

def _szse_s2(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='orange')
    draw_wave(ax, [2015.5, 2024.2], [18211, 7958], '#EF5350')
    draw_wave(ax, [2024.2, cy], [7958, cp], '#FF9800')
    draw_wave(ax, [cy, cy + 0.5, cy + 1, cy + 1.5], [cp, 11000, 12000, 9000], '#D32F2F', 2.0, '--')
    label(ax, 2019, 18211, 'A', '#EF5350', 14, (0, 600))
    label(ax, 2022, 7958, 'B', '#FF9800', 14, (0, -800))
    ax.text(cy + 1.5, 9000, 'C目标\n9000-10000', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')
    ax.axhline(y=13105, color='#FF9800', ls='--', alpha=0.5, lw=0.8)
    ax.text(2005.5, 13105, '50%回撤=13105', fontsize=8, color='#FF9800', va='bottom')

def _szse_s3(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='blue')
    draw_wave(ax, [2008.1, 2007.8], [5577, 19600], '#1E88E5', 2.0)
    draw_wave(ax, [2007.8, 2013], [19600, 6950], '#EF5350', 2.0)
    draw_wave(ax, [2013, 2015.5], [6950, 18211], '#1E88E5', 2.0)
    draw_wave(ax, [2015.5, 2019], [18211, 8557], '#7E57C2', 2.0)
    draw_wave(ax, [2019, 2021], [8557, 16293], '#7E57C2', 2.0)
    draw_wave(ax, [2021, 2024.2], [16293, 7958], '#7E57C2', 2.0)
    draw_wave(ax, [2024.2, cy], [7958, cp], '#43A047', 2.5)
    label(ax, 2007, 19600, 'I', '#1E88E5', 11, (0, 500))
    label(ax, 2010, 6950, 'II', '#EF5350', 11, (0, -800))
    label(ax, 2014, 18211, 'III', '#1E88E5', 11, (0, 500))
    label(ax, 2017, 18211, 'IV(扩张平台)', '#7E57C2', 10, (0, 800))
    label(ax, 2022, 7958, 'V', '#43A047', 13, (0, -800))
    ax.annotate('', xy=(cy + 0.7, 20000), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 20000, 'V目标\n18000-20000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


# --- 创业板指 ---
def generate_cyb_chart(current_price, current_year, output_dir):
    fh = 46
    fig = plt.figure(figsize=(24, fh))
    fig.text(0.5, 0.98, '创业板指 - 艾略特波浪多种浪型综合对比',
             fontsize=20, fontweight='bold', ha='center', va='top', color='#1A237E')
    fig.text(0.5, 0.965, f'当前: {current_price:,.0f} | 数据截至: {current_year}',
             fontsize=12, ha='center', va='top', color='#666')

    xk = [2012, 2014, 2015.5, 2016, 2018, 2019, 2021, 2022.4, 2024.2, 2024.9, 2025.9, current_year]
    yk = [585, 1500, 4037, 1783, 1184, 1400, 3558, 2122, 1516, 2576, 2000, current_price]
    xlim = (2012, current_year + 1)
    ylim = (0, 5000)
    xr = xlim[1]

    scenarios = [
        {'chart_rect': [0.06, 0.89, 0.88, 0.115], 'text_rect': [0.06, 0.795, 0.88, 0.095],
         'title': '可能性1: 新推动浪第三浪延伸 [25%]', 'bg': '#E8F5E9',
         'draw': lambda ax: _cyb_s1(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2018年1184起: 浪1至3558, 浪2回调至1516, 浪3正在延伸。当前处于浪3中期,科技股和新能源领涨。若浪3为最长浪则目标4000-4500。',
         'confirm': '突破3800持续上攻; 科技股领涨放量; 回调不破3200',
         'deny': '跌破3200支撑; 在3800形成顶部; 量能持续萎缩'},

        {'chart_rect': [0.06, 0.67, 0.88, 0.115], 'text_rect': [0.06, 0.575, 0.88, 0.095],
         'title': '可能性2: B浪反弹接近尾声 [45%]', 'bg': '#FFF3E0',
         'draw': lambda ax: _cyb_s2(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2021年3558起处于A-B-C调整。A浪至1516, 当前B浪反弹至3700+接近A浪61.8%回撤位(2536)已超。B浪呈现复杂三浪结构,在3700-3900动能减弱。C浪下跌目标1800-2200。',
         'confirm': '在3700-3900受阻; 跌破3300后加速下行; 新能源/医药领跌',
         'deny': '突破4000创新高; 低点不断抬高; 突破4500(B浪假设失效)'},

        {'chart_rect': [0.06, 0.45, 0.88, 0.115], 'text_rect': [0.06, 0.355, 0.88, 0.095],
         'title': '可能性3: 大型双底新牛市初期 [30%]', 'bg': '#E3F2FD',
         'draw': lambda ax: _cyb_s3(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '2018年1184与2024年1516形成大型双底。浪1(1184->3558)为完整5浪推动,当前浪2回调至2000-2500区域属正常(38.2%-50%回撤)。双底颈线3800,突破后进入主升浪3,目标4500-5000。',
         'confirm': '在3200-3300形成有效支撑; 突破3800确认双底; 浪3强势上攻',
         'deny': '跌破2800(双底失效); 长期横盘无法突破; 形成更低低点'},
    ]

    _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr)
    path = os.path.join(output_dir, '创业板指_多种浪型综合对比.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path

def _cyb_s1(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='green')
    draw_wave(ax, [2018, 2021], [1184, 3558], '#1E88E5')
    draw_wave(ax, [2021, 2024.2], [3558, 1516], '#EF5350')
    draw_wave(ax, [2024.2, cy], [1516, cp], '#43A047')
    label(ax, 2019.5, 1184, '1', '#1E88E5', 12, (0, -200))
    label(ax, 2022.5, 1516, '2', '#EF5350', 12, (0, -200))
    label(ax, 2025, 3558, '3', '#43A047', 14, (0, 300))
    ax.annotate('', xy=(cy + 0.7, 4500), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 4500, '浪3目标\n4000-4500', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')

def _cyb_s2(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='orange')
    draw_wave(ax, [2021, 2024.2], [3558, 1516], '#EF5350')
    draw_wave(ax, [2024.2, cy], [1516, cp], '#FF9800')
    draw_wave(ax, [cy, cy + 0.5, cy + 1, cy + 1.5], [cp, 2500, 2800, 1800], '#D32F2F', 2.0, '--')
    label(ax, 2022.5, 3558, 'A', '#EF5350', 14, (0, 300))
    label(ax, 2023, 1516, 'B', '#FF9800', 14, (0, -300))
    ax.text(cy + 1.5, 1800, 'C目标\n1800-2200', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')
    ax.axhline(y=2536, color='#FF9800', ls='--', alpha=0.5, lw=0.8)
    ax.text(2012.5, 2536, '61.8%回撤=2536', fontsize=8, color='#FF9800', va='bottom')

def _cyb_s3(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='blue')
    draw_wave(ax, [2018, 2021], [1184, 3558], '#1E88E5', 2.5)
    draw_wave(ax, [2021, cy], [3558, cp], '#7E57C2', 2.5)
    label(ax, 2019.5, 3558, '1', '#1E88E5', 14, (0, 300))
    label(ax, 2023, cp, '2', '#7E57C2', 14, (0, -300))
    ax.plot(2018, 1184, 'v', color='#E91E63', markersize=12, zorder=5)
    ax.plot(2024.2, 1516, 'v', color='#E91E63', markersize=12, zorder=5)
    ax.annotate('双底1\n1,184', xy=(2018, 1184), fontsize=9, color='#E91E63', ha='center', va='top', fontweight='bold')
    ax.annotate('双底2\n1,516', xy=(2024.2, 1516), fontsize=9, color='#E91E63', ha='center', va='top', fontweight='bold')
    ax.axhline(y=3800, color='#E91E63', ls='--', alpha=0.6, lw=1.0)
    ax.text(2012.5, 3800, '颈线位=3,800', fontsize=9, color='#E91E63', va='bottom')
    ax.annotate('', xy=(cy + 0.7, 4800), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 4800, '浪3目标\n4500-5000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


# --- 科创50 ---
def generate_kc50_chart(current_price, current_year, output_dir):
    fh = 46
    fig = plt.figure(figsize=(24, fh))
    fig.text(0.5, 0.98, '科创50 - 艾略特波浪多种浪型综合对比',
             fontsize=20, fontweight='bold', ha='center', va='top', color='#1A237E')
    fig.text(0.5, 0.965, f'当前: {current_price:,.0f} | 数据截至: {current_year}',
             fontsize=12, ha='center', va='top', color='#666')

    xk = [2020.2, 2021.7, 2022.4, 2024.2, 2024.9, 2025.9, current_year]
    yk = [853, 1639, 871, 656, 986, 900, current_price]
    xlim = (2020, current_year + 1)
    ylim = (0, 2000)
    xr = xlim[1]

    scenarios = [
        {'chart_rect': [0.06, 0.89, 0.88, 0.115], 'text_rect': [0.06, 0.795, 0.88, 0.095],
         'title': '可能性1: 第三推动浪运行中 [30%]', 'bg': '#E8F5E9',
         'draw': lambda ax: _kc_s1(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2024年656起: 浪1至1639, 浪2回调至656(双底), 浪3正在运行。当前处于浪3中期,半导体和AI板块推动。若浪3延伸目标1600-1800。',
         'confirm': '突破1500持续上攻; 半导体/AI板块领涨; 回调不破1200',
         'deny': '跌破1200支撑; 在1500形成顶部; 第三浪短于第一浪'},

        {'chart_rect': [0.06, 0.67, 0.88, 0.115], 'text_rect': [0.06, 0.575, 0.88, 0.095],
         'title': '可能性2: B浪反弹接近尾声 [40%]', 'bg': '#FFF3E0',
         'draw': lambda ax: _kc_s2(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2021年1639起处于A-B-C调整。A浪至656, 当前B浪反弹至1450+区域,接近A浪61.8%回撤位(1176)。B浪在1450-1500区间动能减弱,科技股分化明显。C浪下跌目标700-900。',
         'confirm': '在1450-1500受阻; 跌破1250后加速; 科技股集体回调',
         'deny': '突破1550创新高; 低点不断抬高; 突破1700(B浪假设失效)'},

        {'chart_rect': [0.06, 0.45, 0.88, 0.115], 'text_rect': [0.06, 0.355, 0.88, 0.095],
         'title': '可能性3: 大型底部形态确认新周期 [30%]', 'bg': '#E3F2FD',
         'draw': lambda ax: _kc_s3(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '871(2022)与656(2024)形成双底,底部支撑坚实。从656起的上升可解读为浪1(656->1639),当前浪2回调。突破1500确认底部,目标1800-2000。',
         'confirm': '在1200形成有效支撑; 突破1500确认底部; 5浪推动结构清晰',
         'deny': '跌破1000(底部失效); 长期横盘无法突破; 形成更低低点'},
    ]

    _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr)
    path = os.path.join(output_dir, '科创50_多种浪型综合对比.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path

def _kc_s1(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='green')
    draw_wave(ax, [2020.2, 2021.7], [853, 1639], '#1E88E5')
    draw_wave(ax, [2021.7, 2024.2], [1639, 656], '#EF5350')
    draw_wave(ax, [2024.2, cy], [656, cp], '#43A047')
    label(ax, 2021, 1639, '1', '#1E88E5', 12, (0, 80))
    label(ax, 2023, 656, '2', '#EF5350', 12, (0, -80))
    label(ax, 2025.5, 1639, '3', '#43A047', 14, (0, 80))
    ax.annotate('', xy=(cy + 0.5, 1800), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.5, 1800, '浪3目标\n1600-1800', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')

def _kc_s2(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='orange')
    draw_wave(ax, [2021.7, 2024.2], [1639, 656], '#EF5350')
    draw_wave(ax, [2024.2, cy], [656, cp], '#FF9800')
    draw_wave(ax, [cy, cy + 0.3, cy + 0.6, cy + 0.9], [cp, 1100, 1200, 750], '#D32F2F', 2.0, '--')
    label(ax, 2023, 1639, 'A', '#EF5350', 14, (0, 80))
    label(ax, 2024.5, 656, 'B', '#FF9800', 14, (0, -80))
    ax.text(cy + 0.9, 750, 'C目标\n700-900', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')
    ax.axhline(y=1176, color='#FF9800', ls='--', alpha=0.5, lw=0.8)
    ax.text(2020.2, 1176, '61.8%=1176', fontsize=8, color='#FF9800', va='bottom')

def _kc_s3(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='blue')
    draw_wave(ax, [2024.2, 2024.9], [656, 986], '#1E88E5', 2.5)
    draw_wave(ax, [2024.9, cy], [986, cp], '#7E57C2', 2.5)
    label(ax, 2024.5, 986, '1', '#1E88E5', 14, (0, 80))
    label(ax, cy - 0.3, cp, '2', '#7E57C2', 14, (0, -80))
    ax.plot(2022.4, 871, 'v', color='#E91E63', markersize=10, zorder=5)
    ax.plot(2024.2, 656, 'v', color='#E91E63', markersize=10, zorder=5)
    ax.annotate('双底1\n871', xy=(2022.4, 871), fontsize=9, color='#E91E63', ha='center', va='top')
    ax.annotate('双底2\n656', xy=(2024.2, 656), fontsize=9, color='#E91E63', ha='center', va='top')
    ax.annotate('', xy=(cy + 0.5, 1800), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.5, 1800, '浪3目标\n1800-2000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


# --- 恒生指数 ---
def generate_hsi_chart(current_price, current_year, output_dir):
    fh = 46
    fig = plt.figure(figsize=(24, fh))
    fig.text(0.5, 0.98, '恒生指数 - 艾略特波浪多种浪型综合对比',
             fontsize=20, fontweight='bold', ha='center', va='top', color='#1A237E')
    fig.text(0.5, 0.965, f'当前: {current_price:,.0f} | 数据截至: {current_year}',
             fontsize=12, ha='center', va='top', color='#666')

    xk = [2003.3, 2007.8, 2008.8, 2010.5, 2015.3, 2018, 2020.2, 2021.1, 2022.8, 2024, 2024.9, 2025.9, 2026.1, current_year]
    yk = [8331, 31958, 10676, 22000, 28588, 33484, 21139, 31183, 14559, 14787, 22000, 19260, 28056, current_price]
    xlim = (2003, current_year + 1)
    ylim = (5000, 44000)
    xr = xlim[1]

    scenarios = [
        {'chart_rect': [0.06, 0.89, 0.88, 0.115], 'text_rect': [0.06, 0.795, 0.88, 0.095],
         'title': '可能性1: 新一轮推动浪第三浪运行中 [25%]', 'bg': '#E8F5E9',
         'draw': lambda ax: _hsi_s1(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2022年10月低点14,559起,恒指形成5浪推动结构。浪1至22,700,浪2回调至14,787,浪3正在运行中。子浪(3)延伸至28,056,子浪(4)回调至24,203,当前可能在(5)中。浪3延伸符合第三浪最长规则,目标33,484+。',
         'confirm': '突破28,056持续创新高; 浪3延伸至33,484以上; 回调不跌破24,203',
         'deny': '跌破24,203且无法收复; 在28,056附近形成双顶; 浪3长度短于浪1'},

        {'chart_rect': [0.06, 0.67, 0.88, 0.115], 'text_rect': [0.06, 0.575, 0.88, 0.095],
         'title': '可能性2: 大型ABC调整B浪反弹61.8% [45%]', 'bg': '#FFF3E0',
         'draw': lambda ax: _hsi_s2(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2018年1月高点33,484起,恒指可能处于大型A-B-C调整。A浪从33,484跌至14,559(跌幅56%),B浪反弹至26,000+恰在A浪61.8%回撤位(26,255)。B浪呈现复杂三浪结构,动能逐步衰竭,符合B浪末端特征。C浪目标<14,559。',
         'confirm': '在26,255-28,056形成顶部; 跌破24,203持续下行; C浪5浪推动结构下行',
         'deny': '强势突破28,056上攻30,000+; 低点不断抬高; 突破33,484(B浪假设失效)'},

        {'chart_rect': [0.06, 0.45, 0.88, 0.115], 'text_rect': [0.06, 0.355, 0.88, 0.095],
         'title': '可能性3: 扩张平台调整完成第五大浪启动 [30%]', 'bg': '#E3F2FD',
         'draw': lambda ax: _hsi_s3(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2003年8,331起的5浪推动: I至31,958, II至10,676, III至33,484。IV浪为扩张平台: A(33,484->21,139), B(21,139->31,183超过A起点), C(31,183->14,559)。IV浪完成,V浪初期,目标35,000-42,000。',
         'confirm': '持续突破28,056向33,484推进; 回调幅度有限低点抬高; V浪5浪推动结构上行',
         'deny': '在28,000反复受阻双顶; 跌破22,000调整未结束; 需要更低低点确认IV完成'},
    ]

    _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr)
    path = os.path.join(output_dir, '恒生指数_多种浪型综合对比.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path

def _hsi_s1(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='green')
    draw_wave(ax, [2022.8, 2024, 2024.9, 2025.9, 2026.1, cy], [14559, 14787, 22000, 19260, 28056, cp], '#43A047')
    label(ax, 2023, 14559, '1', '#1E88E5', 11, (0, -1200))
    label(ax, 2024, 14787, '2', '#EF5350', 11, (0, -1200))
    label(ax, 2025.5, 28056, '3', '#43A047', 14, (0, 800))
    ax.annotate('(i)', xy=(2024.9, 22000), fontsize=9, color='#43A047', ha='center', va='bottom')
    ax.annotate('(iii)', xy=(2026.1, 28056), fontsize=9, color='#43A047', ha='center', va='top')
    ax.annotate('', xy=(cy + 0.7, 36000), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 36000, '浪3目标\n33,484+', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')

def _hsi_s2(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='orange')
    draw_wave(ax, [2018, 2020.2, 2021.1, 2022.8], [33484, 21139, 31183, 14559], '#EF5350')
    draw_wave(ax, [2022.8, 2024.9, 2025.9, 2026.1, cy], [14559, 22000, 19260, 28056, cp], '#FF9800')
    draw_wave(ax, [cy, cy + 0.5, cy + 1, cy + 1.5], [cp, 20000, 22000, 12000], '#D32F2F', 2.0, '--')
    label(ax, 2020, 33484, 'A', '#EF5350', 14, (0, 800))
    label(ax, 2024, 14559, 'B', '#FF9800', 14, (0, -1200))
    ax.text(cy + 1.5, 12000, 'C目标\n<14,559', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')
    ax.axhline(y=26255, color='#FF9800', ls='--', alpha=0.5, lw=0.8)
    ax.text(2003.5, 26255, '61.8%=26,255', fontsize=8, color='#FF9800', va='bottom')
    ax.axhspan(26000, 28500, alpha=0.06, color='red')
    ax.text(2010, 28500, 'B浪顶部区域', fontsize=9, color='#D32F2F', ha='center', va='bottom')

def _hsi_s3(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='blue')
    draw_wave(ax, [2003.3, 2007.8], [8331, 31958], '#1E88E5', 2.0)
    draw_wave(ax, [2007.8, 2008.8], [31958, 10676], '#EF5350', 2.0)
    draw_wave(ax, [2008.8, 2018], [10676, 33484], '#1E88E5', 2.0)
    draw_wave(ax, [2018, 2020.2, 2021.1, 2022.8], [33484, 21139, 31183, 14559], '#7E57C2', 2.0)
    draw_wave(ax, [2022.8, 2026.1, cy], [14559, 28056, cp], '#43A047', 2.5)
    label(ax, 2005.5, 8331, 'I', '#1E88E5', 11, (0, -1200))
    label(ax, 2008.3, 10676, 'II', '#EF5350', 11, (0, -1200))
    label(ax, 2013, 33484, 'III', '#1E88E5', 11, (0, 800))
    label(ax, 2020.5, 33484, 'IV(扩张平台)', '#7E57C2', 10, (0, 800))
    label(ax, 2024.5, 14559, 'V', '#43A047', 13, (0, -1200))
    ax.annotate('', xy=(cy + 0.7, 42000), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.7, 42000, 'V目标\n35,000-42,000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


# --- 恒生科技指数 ---
def generate_hstech_chart(current_price, current_year, output_dir):
    fh = 46
    fig = plt.figure(figsize=(24, fh))
    fig.text(0.5, 0.98, '恒生科技指数 - 艾略特波浪多种浪型综合对比',
             fontsize=20, fontweight='bold', ha='center', va='top', color='#1A237E')
    fig.text(0.5, 0.965, f'当前: {current_price:,.0f} | 数据截至: {current_year}',
             fontsize=12, ha='center', va='top', color='#666')

    xk = [2020.07, 2021.02, 2022.03, 2022.8, 2023.01, 2024.01, 2024.09, 2024.12, 2025.03, 2025.09, 2025.12, 2026.01, 2026.03, current_year]
    yk = [7000, 10001, 3463, 2720, 4800, 2984, 5451, 4100, 6195, 5200, 5800, 6715, 4620, current_price]
    xlim = (2020, current_year + 1)
    ylim = (0, 12000)
    xr = xlim[1]

    scenarios = [
        {'chart_rect': [0.06, 0.89, 0.88, 0.115], 'text_rect': [0.06, 0.795, 0.88, 0.095],
         'title': '可能性1: 新推动浪第三浪运行中 [25%]', 'bg': '#E8F5E9',
         'draw': lambda ax: _hstech_s1(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2022年10月低点2,720起: 浪1至4,800, 浪2深度回调至2,984(双底), 浪3从2,984启动。子浪(iii)延伸至6,715, 子浪(iv)回调至4,620, 当前可能在(v)中。浪3延伸符合第三浪最长规则,目标8,000-10,001。',
         'confirm': '从4,620反弹突破5,500; 浪4回调不破4,620; 浪5突破6,715创新高',
         'deny': '跌破4,620且无法收复; 在5,500-6,000形成明显顶部; 浪3长度短于浪1'},

        {'chart_rect': [0.06, 0.67, 0.88, 0.115], 'text_rect': [0.06, 0.575, 0.88, 0.095],
         'title': '可能性2: 大型ABC调整B浪反弹接近关键阻力 [40%]', 'bg': '#FFF3E0',
         'draw': lambda ax: _hstech_s2(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '从2021年2月高点10,001起: A浪暴跌至2,720(跌幅73%), B浪反弹至6,715已达到A浪50%回撤位(6,361)附近。2025年4月关税冲击单日暴跌17%,随后反弹力度减弱,符合B浪末期动能衰竭。C浪目标<2,720。',
         'confirm': '在6,715附近形成双顶或头肩顶; 跌破4,600持续下行; C浪5浪推动下破2,720',
         'deny': '强势突破6,715上攻7,500+; 低点不断抬高; 突破8,000(B浪假设需修正)'},

        {'chart_rect': [0.06, 0.45, 0.88, 0.115], 'text_rect': [0.06, 0.355, 0.88, 0.095],
         'title': '可能性3: 双底形态确认新一轮牛市启动 [35%]', 'bg': '#E3F2FD',
         'draw': lambda ax: _hstech_s3(ax, xk, yk, cp=current_price, cy=current_year),
         'reason': '2,720(2022.10)与2,984(2024.01)形成大型双底。从2,720起的上升结构: 浪1(2,720->6,715)为5浪推动,当前浪2回调中。浪2回撤至浪1的38.2%-50%区域(4,200-4,750)属正常。双底颈线5,500,突破后进入主升浪3,目标8,000-11,000。',
         'confirm': '在4,600-4,800有效支撑反弹; 突破5,500颈线确认双底; 浪3强势突破6,715',
         'deny': '跌破2,984(双底失效); 5,000-5,500长期横盘无法突破; 形成更低高点和更低低点'},
    ]

    _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr)
    path = os.path.join(output_dir, '恒生科技指数_多种浪型综合对比.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path

def _hstech_s1(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='green')
    draw_wave(ax, [2022.8, 2023.01], [2720, 4800], '#1E88E5', 2.0)
    draw_wave(ax, [2023.01, 2024.01], [4800, 2984], '#EF5350', 2.0)
    draw_wave(ax, [2024.01, 2024.09, 2024.12, 2025.03, 2026.01, 2026.03, cy],
              [2984, 5451, 4100, 6195, 6715, 4620, cp], '#43A047', 2.5)
    label(ax, 2023, 4800, '1', '#1E88E5', 11, (0, 300))
    label(ax, 2024, 2984, '2', '#EF5350', 11, (0, -400))
    label(ax, 2025.5, 6715, '3', '#43A047', 14, (0, 400))
    ax.annotate('(i)', xy=(2024.09, 5451), fontsize=8, color='#43A047', ha='center', va='bottom')
    ax.annotate('(iii)', xy=(2026.01, 6715), fontsize=8, color='#43A047', ha='center', va='top')
    ax.annotate('(iv)', xy=(2026.03, 4620), fontsize=8, color='#43A047', ha='center', va='bottom')
    ax.annotate('', xy=(cy + 0.5, 10000), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.5, 10000, '浪5目标\n8,000-10,001', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')

def _hstech_s2(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='orange')
    draw_wave(ax, [2021.02, 2022.03, 2022.8], [10001, 3463, 2720], '#EF5350', 2.5)
    draw_wave(ax, [2022.8, 2024.09, 2024.12, 2026.01, 2026.03, cy], [2720, 5451, 4100, 6715, 4620, cp], '#FF9800', 2.5)
    draw_wave(ax, [cy, cy + 0.3, cy + 0.6, cy + 0.9], [cp, 3500, 4200, 1500], '#D32F2F', 2.0, '--')
    label(ax, 2021.5, 10001, 'A', '#EF5350', 14, (0, 400))
    label(ax, 2024, 2720, 'B', '#FF9800', 14, (0, -600))
    ax.text(cy + 0.9, 1500, 'C目标\n<2,720', fontsize=10, color='#D32F2F', fontweight='bold', ha='center', va='top')
    ax.axhline(y=6361, color='#FF9800', ls='--', alpha=0.5, lw=0.8)
    ax.text(2020.1, 6361, '50%=6,361', fontsize=8, color='#FF9800', va='bottom')

def _hstech_s3(ax, xk, yk, cp, cy):
    ax.plot(xk, yk, color='#333', lw=1, alpha=0.4, zorder=1)
    ax.fill_between(xk, yk, alpha=0.04, color='blue')
    draw_wave(ax, [2022.8, 2024.01, 2024.09, 2024.12, 2025.03, 2026.01],
              [2720, 2984, 5451, 4100, 6195, 6715], '#1E88E5', 2.5)
    draw_wave(ax, [2026.01, 2026.03, cy], [6715, 4620, cp], '#7E57C2', 2.5)
    label(ax, 2024.5, 6715, '1', '#1E88E5', 14, (0, 400))
    label(ax, 2026.1, 4620, '2', '#7E57C2', 14, (0, -400))
    ax.plot(2022.8, 2720, 'v', color='#E91E63', markersize=10, zorder=5)
    ax.plot(2024.01, 2984, 'v', color='#E91E63', markersize=10, zorder=5)
    ax.annotate('双底1\n2,720', xy=(2022.8, 2720), fontsize=9, color='#E91E63', ha='center', va='top', fontweight='bold')
    ax.annotate('双底2\n2,984', xy=(2024.01, 2984), fontsize=9, color='#E91E63', ha='center', va='top', fontweight='bold')
    ax.axhline(y=5500, color='#E91E63', ls='--', alpha=0.6, lw=1.0)
    ax.text(2020.1, 5500, '颈线=5,500', fontsize=9, color='#E91E63', va='bottom')
    ax.annotate('', xy=(cy + 0.5, 10500), xytext=(cy, cp),
               arrowprops=dict(arrowstyle='->', color='#43A047', lw=2, ls='--'))
    ax.text(cy + 0.5, 10500, '浪3目标\n8,000-11,000', fontsize=10, color='#43A047', fontweight='bold', ha='center', va='bottom')


# ============================================================
# 渲染通用框架
# ============================================================

def _render_scenarios(fig, scenarios, xlim, ylim, current_price, xr):
    for s in scenarios:
        ax = fig.add_axes(s['chart_rect'])
        s['draw'](ax)
        setup_chart(ax, s['title'], xlim, ylim)
        add_current_line(ax, current_price, xr)
        add_analysis_box(fig, s['text_rect'], s['reason'], s['confirm'], s['deny'], s['bg'])


# ============================================================
# 批量生成入口
# ============================================================

def generate_all_charts(prices, output_dir):
    """
    生成所有6个指数的图表
    prices: dict, key=指数名称, value=最新收盘价
    output_dir: 图表保存目录
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    # 获取数据年份
    import datetime
    current_year = datetime.date.today().year + (datetime.date.today().month - 1) / 12 + (datetime.date.today().day - 1) / 365

    generators = {
        '上证指数': generate_sse_chart,
        '深证成指': generate_szse_chart,
        '创业板指': generate_cyb_chart,
        '科创50': generate_kc50_chart,
        '恒生指数': generate_hsi_chart,
        '恒生科技指数': generate_hstech_chart,
    }

    for name, gen_func in generators.items():
        price = prices.get(name)
        if price is None:
            print(f"  [!] {name} 无数据,跳过图表生成")
            continue
        print(f"  生成 {name} 图表...")
        try:
            path = gen_func(price, current_year, output_dir)
            results[name] = path
            print(f"    -> {path}")
        except Exception as e:
            print(f"    [!] 生成失败: {e}")

    return results


# ============================================================
# 月线和周线级别图表（数据驱动）
# ============================================================

def _get_tf_scenarios(index_name, level):
    """从INDICES配置中获取指定时间级别的场景数据"""
    try:
        from elliott.daily_update import INDICES
    except ImportError:
        return []
    cfg = INDICES.get(index_name, {})
    timeframes = cfg.get("timeframes", {})
    tf = timeframes.get(level, {})
    return tf.get("scenarios", [])


def generate_monthly_chart(name, df_monthly, current_price, output_dir):
    """
    生成月线级别图表
    - 绘制最近36个月收盘价折线
    - 添加支撑/阻力水平线
    - 添加场景标签和概率
    - 添加当前价格线
    - 包含紧凑分析文本区
    """
    scenarios = _get_tf_scenarios(name, "monthly")
    if not scenarios:
        print(f"  [!] {name} 无月线场景配置,跳过")
        return None

    # 准备数据：最近36个月
    df_plot = df_monthly.tail(36).copy()
    if df_plot.empty:
        return None

    dates = df_plot["date"]
    closes = df_plot["close"]

    n_scenarios = len(scenarios)
    fig_height = 6 + n_scenarios * 1.5
    fig, axes = plt.subplots(n_scenarios + 1, 1, figsize=(16, fig_height),
                              gridspec_kw={'height_ratios': [3] + [1] * n_scenarios})

    if n_scenarios == 0:
        plt.close(fig)
        return None

    # 主图：价格折线 + 支撑/阻力
    ax_main = axes[0]
    ax_main.plot(dates, closes, color='#1565C0', linewidth=1.8, zorder=3, label='月线收盘')
    ax_main.fill_between(dates, closes, alpha=0.08, color='#1565C0')

    # 当前价格线
    ax_main.axhline(y=current_price, color='#E91E63', linestyle='-', alpha=0.5, linewidth=1.0)
    ax_main.text(dates.iloc[-1], current_price, f' 当前 {current_price:,.0f}',
                 fontsize=9, color='#E91E63', va='bottom', fontweight='bold')

    # 为每个场景添加支撑/阻力线
    colors = ['#43A047', '#FF9800', '#7E57C2', '#00BCD4']
    for i, scenario in enumerate(scenarios):
        color = colors[i % len(colors)]
        support = scenario['key_support']
        resistance = scenario['key_resistance']
        prob = scenario['probability']
        ax_main.axhline(y=support, color=color, linestyle='--', alpha=0.6, linewidth=0.8)
        ax_main.axhline(y=resistance, color=color, linestyle='-', alpha=0.6, linewidth=0.8)
        ax_main.text(dates.iloc[0], support, f' 支撑{support:,.0f} [{prob}%]',
                     fontsize=7, color=color, va='top', alpha=0.8)
        ax_main.text(dates.iloc[0], resistance, f' 阻力{resistance:,.0f}',
                     fontsize=7, color=color, va='bottom', alpha=0.8)

    ax_main.set_title(f'{name} - 月线级别分析', fontsize=14, fontweight='bold', color='#1A237E', pad=8)
    ax_main.set_ylabel('指数点位', fontsize=10)
    ax_main.grid(True, alpha=0.2)
    ax_main.tick_params(labelsize=8)

    # 各场景分析文本
    for i, scenario in enumerate(scenarios):
        ax_text = axes[i + 1]
        ax_text.set_xlim(0, 1)
        ax_text.set_ylim(0, 1)
        ax_text.axis('off')

        prob = scenario['probability']
        bg_color = '#E8F5E9' if prob >= 35 else '#FFF3E0'
        bg = plt.Rectangle((0, 0), 1, 1, facecolor=bg_color, edgecolor='#999',
                            linewidth=0.5, transform=ax_text.transAxes, zorder=0)
        ax_text.add_patch(bg)

        title_text = f"{scenario['name']} [{prob}%]"
        info_text = (f"位置: {scenario['wave_position']} | "
                     f"支撑: {scenario['key_support']:,.0f} | "
                     f"阻力: {scenario['key_resistance']:,.0f} | "
                     f"目标: {scenario['target']}")
        confirm_text = "确认: " + "; ".join(scenario['confirm_signals'][:2])
        deny_text = "否认: " + "; ".join(scenario['deny_signals'][:2])

        ax_text.text(0.01, 0.85, title_text, fontsize=10, fontweight='bold',
                     color='#1A237E', va='top', transform=ax_text.transAxes)
        ax_text.text(0.01, 0.55, info_text, fontsize=8, color='#333',
                     va='top', transform=ax_text.transAxes)
        ax_text.text(0.01, 0.25, confirm_text, fontsize=8, color='#1B5E20',
                     va='top', transform=ax_text.transAxes)
        ax_text.text(0.5, 0.25, deny_text, fontsize=8, color='#C62828',
                     va='top', transform=ax_text.transAxes)

    plt.tight_layout()
    path = os.path.join(output_dir, f'{name}_月线.png')
    fig.savefig(path, dpi=120, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def generate_weekly_chart(name, df_weekly, current_price, output_dir):
    """
    生成周线级别图表
    - 绘制最近52周收盘价折线
    - 添加支撑/阻力水平线
    - 添加场景标签和概率
    - 添加当前价格线
    - 包含紧凑分析文本区
    """
    scenarios = _get_tf_scenarios(name, "weekly")
    if not scenarios:
        print(f"  [!] {name} 无周线场景配置,跳过")
        return None

    # 准备数据：最近52周
    df_plot = df_weekly.tail(52).copy()
    if df_plot.empty:
        return None

    dates = df_plot["date"]
    closes = df_plot["close"]

    n_scenarios = len(scenarios)
    fig_height = 6 + n_scenarios * 1.5
    fig, axes = plt.subplots(n_scenarios + 1, 1, figsize=(16, fig_height),
                              gridspec_kw={'height_ratios': [3] + [1] * n_scenarios})

    if n_scenarios == 0:
        plt.close(fig)
        return None

    # 主图：价格折线 + 支撑/阻力
    ax_main = axes[0]
    ax_main.plot(dates, closes, color='#1565C0', linewidth=1.8, zorder=3, label='周线收盘')
    ax_main.fill_between(dates, closes, alpha=0.08, color='#1565C0')

    # 当前价格线
    ax_main.axhline(y=current_price, color='#E91E63', linestyle='-', alpha=0.5, linewidth=1.0)
    ax_main.text(dates.iloc[-1], current_price, f' 当前 {current_price:,.0f}',
                 fontsize=9, color='#E91E63', va='bottom', fontweight='bold')

    # 为每个场景添加支撑/阻力线
    colors = ['#43A047', '#FF9800', '#7E57C2', '#00BCD4']
    for i, scenario in enumerate(scenarios):
        color = colors[i % len(colors)]
        support = scenario['key_support']
        resistance = scenario['key_resistance']
        prob = scenario['probability']
        ax_main.axhline(y=support, color=color, linestyle='--', alpha=0.6, linewidth=0.8)
        ax_main.axhline(y=resistance, color=color, linestyle='-', alpha=0.6, linewidth=0.8)
        ax_main.text(dates.iloc[0], support, f' 支撑{support:,.0f} [{prob}%]',
                     fontsize=7, color=color, va='top', alpha=0.8)
        ax_main.text(dates.iloc[0], resistance, f' 阻力{resistance:,.0f}',
                     fontsize=7, color=color, va='bottom', alpha=0.8)

    ax_main.set_title(f'{name} - 周线级别分析', fontsize=14, fontweight='bold', color='#1A237E', pad=8)
    ax_main.set_ylabel('指数点位', fontsize=10)
    ax_main.grid(True, alpha=0.2)
    ax_main.tick_params(labelsize=8)

    # 各场景分析文本
    for i, scenario in enumerate(scenarios):
        ax_text = axes[i + 1]
        ax_text.set_xlim(0, 1)
        ax_text.set_ylim(0, 1)
        ax_text.axis('off')

        prob = scenario['probability']
        bg_color = '#E8F5E9' if prob >= 35 else '#FFF3E0'
        bg = plt.Rectangle((0, 0), 1, 1, facecolor=bg_color, edgecolor='#999',
                            linewidth=0.5, transform=ax_text.transAxes, zorder=0)
        ax_text.add_patch(bg)

        title_text = f"{scenario['name']} [{prob}%]"
        info_text = (f"位置: {scenario['wave_position']} | "
                     f"支撑: {scenario['key_support']:,.0f} | "
                     f"阻力: {scenario['key_resistance']:,.0f} | "
                     f"目标: {scenario['target']}")
        confirm_text = "确认: " + "; ".join(scenario['confirm_signals'][:2])
        deny_text = "否认: " + "; ".join(scenario['deny_signals'][:2])

        ax_text.text(0.01, 0.85, title_text, fontsize=10, fontweight='bold',
                     color='#1A237E', va='top', transform=ax_text.transAxes)
        ax_text.text(0.01, 0.55, info_text, fontsize=8, color='#333',
                     va='top', transform=ax_text.transAxes)
        ax_text.text(0.01, 0.25, confirm_text, fontsize=8, color='#1B5E20',
                     va='top', transform=ax_text.transAxes)
        ax_text.text(0.5, 0.25, deny_text, fontsize=8, color='#C62828',
                     va='top', transform=ax_text.transAxes)

    plt.tight_layout()
    path = os.path.join(output_dir, f'{name}_周线.png')
    fig.savefig(path, dpi=120, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


def generate_multi_tf_charts(data, output_dir):
    """生成月线和周线级别图表"""
    results = {}
    for name, d in data.items():
        df_m = d.get("df_monthly")
        df_w = d.get("df_weekly")
        close = d.get("close", 0)
        if df_m is not None and not df_m.empty:
            print(f"  生成 {name} 月线图表...")
            try:
                path = generate_monthly_chart(name, df_m, close, output_dir)
                if path:
                    results[f"{name}_月线"] = path
                    print(f"    -> {path}")
            except Exception as e:
                print(f"    [!] 月线图表生成失败: {e}")
        if df_w is not None and not df_w.empty:
            print(f"  生成 {name} 周线图表...")
            try:
                path = generate_weekly_chart(name, df_w, close, output_dir)
                if path:
                    results[f"{name}_周线"] = path
                    print(f"    -> {path}")
            except Exception as e:
                print(f"    [!] 周线图表生成失败: {e}")
    return results
