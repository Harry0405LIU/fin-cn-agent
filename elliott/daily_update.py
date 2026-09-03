#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
艾略特波浪每日预测更新脚本
- 从akshare获取6大指数日线数据
- 分析波浪信号状态
- 生成Markdown日报
- 生成波浪图表PNG
- 推送企业微信Webhook
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from core.wechat import WeChatPusher
from core.data_fetcher import fetch_a_share_data, fetch_hk_data, resample_to_monthly, resample_to_weekly
from core.utils import is_trading_day
from elliott.signals import (
    check_signals, check_signals_weighted, update_state, migrate_state,
    load_state, save_state, auto_adjust_scenario, analyze_multi_timeframe_correlation,
    generate_breakout_scenario,
)

# ============================================================
# 指数配置：代码、数据源、多时间框架波浪场景
# ============================================================

INDICES = {
    "上证指数": {
        "symbol": "sh000001",
        "source": "a",  # a=A股, hk=港股
        "timeframes": {
            "yearly": {
                "label": "年线",
                "scenarios": [
                    {
                        "name": "第五大浪启动",
                        "probability": 25,
                        "key_support": 3400,
                        "key_resistance": 3700,
                        "wave_position": "V浪子浪3末端或子浪5初期",
                        "target": "5000-6000",
                        "confirm_signals": ["突破3700", "放量上攻", "回调不跌破3400"],
                        "deny_signals": ["跌破3400且无法收复", "3700附近双顶", "量价背离明显"],
                    },
                    {
                        "name": "中级推动浪第三浪",
                        "probability": 35,
                        "key_support": 3700,
                        "key_resistance": 4000,
                        "wave_position": "浪3延伸阶段",
                        "target": "4500-5000",
                        "confirm_signals": ["突破4000后持续加速上行", "回调幅度小于前次", "MACD零轴上方金叉"],
                        "deny_signals": ["上涨动能减弱出现顶背离", "回调跌破3700支撑", "第三浪长度短于第一浪"],
                    },
                    {
                        "name": "B浪反弹接近尾声",
                        "probability": 25,
                        "key_support": 3400,
                        "key_resistance": 4200,
                        "wave_position": "B浪末端,3700-4100区间反复受阻",
                        "target": "C浪下跌目标2500-2800",
                        "confirm_signals": ["4100-4200形成明显顶部", "随后跌破3700", "C浪以5浪结构下行"],
                        "deny_signals": ["强势突破4200创新高", "回调后低点不断抬高", "突破4500(B浪假设失效)"],
                    },
                    {
                        "name": "大三角形D浪见顶",
                        "probability": 15,
                        "key_support": 3500,
                        "key_resistance": 4100,
                        "wave_position": "D浪接近三角形上轨4000附近",
                        "target": "E浪回调至3200-3400",
                        "confirm_signals": ["4000-4100受阻回落", "波动率持续收窄", "E浪下探至3200附近"],
                        "deny_signals": ["强势突破4200打破三角形", "波动率突然放大向上突破", "跌破3500(非三角形特征)"],
                    },
                ],
            },
            "monthly": {
                "label": "月线",
                "scenarios": [
                    {
                        "name": "月线第三浪延伸",
                        "probability": 35,
                        "key_support": 3900,
                        "key_resistance": 4300,
                        "wave_position": "从2635低点起浪3延伸中",
                        "target": "4500-4800",
                        "confirm_signals": ["突破4300", "放量上攻", "回调不跌破3900"],
                        "deny_signals": ["跌破3900且无法收复", "4300附近受阻回落", "量价背离明显"],
                    },
                    {
                        "name": "月线B浪反弹末端",
                        "probability": 30,
                        "key_support": 3800,
                        "key_resistance": 4200,
                        "wave_position": "从2635反弹为B浪,接近末端",
                        "target": "C浪下跌目标3200-3500",
                        "confirm_signals": ["4200附近形成顶部", "跌破3800", "C浪5浪结构下行"],
                        "deny_signals": ["突破4200创新高", "低点不断抬高", "突破4500(B浪假设失效)"],
                    },
                    {
                        "name": "月线突破回踩确认",
                        "probability": 35,
                        "key_support": 3900,
                        "key_resistance": 4200,
                        "wave_position": "突破3700后回踩确认中",
                        "target": "4500+",
                        "confirm_signals": ["3900形成有效支撑", "突破4200确认", "放量上攻"],
                        "deny_signals": ["跌破3700(突破失效)", "长期横盘无法突破", "形成更低低点"],
                    },
                ],
            },
            "weekly": {
                "label": "周线",
                "scenarios": [
                    {
                        "name": "周线第五浪上行",
                        "probability": 30,
                        "key_support": 4050,
                        "key_resistance": 4200,
                        "wave_position": "短期第五浪上行中",
                        "target": "4300-4400",
                        "confirm_signals": ["突破4200", "放量上行", "回调不跌破4050"],
                        "deny_signals": ["跌破4050", "4200附近受阻", "量价背离"],
                    },
                    {
                        "name": "周线锯齿形调整中",
                        "probability": 35,
                        "key_support": 3950,
                        "key_resistance": 4150,
                        "wave_position": "锯齿形调整浪运行中",
                        "target": "3800-3900",
                        "confirm_signals": ["4150受阻回落", "跌破3950", "5浪下行结构"],
                        "deny_signals": ["突破4150创新高", "低点不断抬高", "跌破3800"],
                    },
                    {
                        "name": "周线平台整理",
                        "probability": 35,
                        "key_support": 3950,
                        "key_resistance": 4200,
                        "wave_position": "3950-4200区间平台整理",
                        "target": "突破方向待定",
                        "confirm_signals": ["3950支撑有效", "4200压力明显", "波动率收窄"],
                        "deny_signals": ["跌破3950", "突破4200", "波动率突然放大"],
                    },
                ],
            },
        },
    },
    "深证成指": {
        "symbol": "sz399001",
        "source": "a",
        "timeframes": {
            "yearly": {
                "label": "年线",
                "scenarios": [
                    {
                        "name": "新一轮推动浪第三浪",
                        "probability": 30,
                        "key_support": 13000,
                        "key_resistance": 15000,
                        "wave_position": "浪3延伸阶段",
                        "target": "16000-18000",
                        "confirm_signals": ["突破15000持续上攻", "回调不破13000", "成交额持续放大"],
                        "deny_signals": ["跌破13000支撑", "在15000形成双顶", "第三浪短于第一浪"],
                    },
                    {
                        "name": "大型ABC调整B浪反弹",
                        "probability": 40,
                        "key_support": 13000,
                        "key_resistance": 16000,
                        "wave_position": "B浪末期,15000-16000区间动能减弱",
                        "target": "C浪下跌目标9000-10000",
                        "confirm_signals": ["15500-16000受阻", "跌破13500后加速下行", "C浪5浪结构清晰"],
                        "deny_signals": ["突破16000创新高", "低点不断抬高", "突破18000(B浪假设失效)"],
                    },
                    {
                        "name": "扩张平台调整完成新周期",
                        "probability": 30,
                        "key_support": 12000,
                        "key_resistance": 15000,
                        "wave_position": "V浪初期",
                        "target": "18000-20000",
                        "confirm_signals": ["持续突破15000", "回调低点不断抬高", "V浪5浪推动结构清晰"],
                        "deny_signals": ["在15000反复受阻", "跌破12000", "形成更低的高点"],
                    },
                ],
            },
            "monthly": {
                "label": "月线",
                "scenarios": [
                    {
                        "name": "月线推动浪第三浪",
                        "probability": 35,
                        "key_support": 14000,
                        "key_resistance": 16000,
                        "wave_position": "从7958起浪3延伸中",
                        "target": "17000-19000",
                        "confirm_signals": ["突破16000", "放量上攻", "回调不跌破14000"],
                        "deny_signals": ["跌破14000", "16000附近受阻", "第三浪短于第一浪"],
                    },
                    {
                        "name": "月线B浪反弹末端",
                        "probability": 30,
                        "key_support": 14000,
                        "key_resistance": 16000,
                        "wave_position": "反弹为B浪,接近末端",
                        "target": "C浪下跌目标10000-12000",
                        "confirm_signals": ["16000附近形成顶部", "跌破14000", "C浪5浪结构下行"],
                        "deny_signals": ["突破16000创新高", "低点不断抬高", "突破18000(B浪假设失效)"],
                    },
                    {
                        "name": "月线扩张平台完成",
                        "probability": 35,
                        "key_support": 13000,
                        "key_resistance": 16000,
                        "wave_position": "IV浪完成,V浪启动中",
                        "target": "18000-20000",
                        "confirm_signals": ["持续突破15000", "回调低点抬高", "V浪5浪结构清晰"],
                        "deny_signals": ["在15000反复受阻", "跌破12000", "形成更低高点"],
                    },
                ],
            },
            "weekly": {
                "label": "周线",
                "scenarios": [
                    {
                        "name": "周线浪(v)延伸",
                        "probability": 30,
                        "key_support": 14800,
                        "key_resistance": 15600,
                        "wave_position": "浪(v)延伸上行中",
                        "target": "16000-16500",
                        "confirm_signals": ["突破15600", "放量上行", "回调不破14800"],
                        "deny_signals": ["跌破14800", "15600受阻", "量价背离"],
                    },
                    {
                        "name": "周线调整浪4运行中",
                        "probability": 35,
                        "key_support": 14500,
                        "key_resistance": 15500,
                        "wave_position": "调整浪4回调中",
                        "target": "14000-14300",
                        "confirm_signals": ["15500受阻回落", "跌破14500", "3浪调整结构"],
                        "deny_signals": ["突破15500创新高", "低点不断抬高", "跌破14000"],
                    },
                    {
                        "name": "周线平台整理",
                        "probability": 35,
                        "key_support": 14500,
                        "key_resistance": 15500,
                        "wave_position": "14500-15500区间平台整理",
                        "target": "突破方向待定",
                        "confirm_signals": ["14500支撑有效", "15500压力明显", "波动率收窄"],
                        "deny_signals": ["跌破14500", "突破15500", "波动率突然放大"],
                    },
                ],
            },
        },
    },
    "创业板指": {
        "symbol": "sz399006",
        "source": "a",
        "timeframes": {
            "yearly": {
                "label": "年线",
                "scenarios": [
                    {
                        "name": "新推动浪第三浪延伸",
                        "probability": 25,
                        "key_support": 3200,
                        "key_resistance": 3800,
                        "wave_position": "浪3中期",
                        "target": "4000-4500",
                        "confirm_signals": ["突破3800持续上攻", "科技股领涨放量", "回调不破3200"],
                        "deny_signals": ["跌破3200支撑", "在3800形成顶部", "量能持续萎缩"],
                    },
                    {
                        "name": "B浪反弹接近尾声",
                        "probability": 45,
                        "key_support": 3300,
                        "key_resistance": 3900,
                        "wave_position": "B浪末期,3700-3900动能减弱",
                        "target": "C浪下跌目标1800-2200",
                        "confirm_signals": ["3700-3900受阻", "跌破3300后加速下行", "新能源/医药领跌"],
                        "deny_signals": ["突破4000创新高", "低点不断抬高", "突破4500(B浪假设失效)"],
                    },
                    {
                        "name": "大型双底新牛市初期",
                        "probability": 30,
                        "key_support": 2800,
                        "key_resistance": 3800,
                        "wave_position": "双底颈线3800待突破,主升浪3蓄势",
                        "target": "4500-5000",
                        "confirm_signals": ["3200-3300形成有效支撑", "突破3800确认双底", "浪3强势上攻"],
                        "deny_signals": ["跌破2800(双底失效)", "长期横盘无法突破", "形成更低低点"],
                    },
                ],
            },
            "monthly": {
                "label": "月线",
                "scenarios": [
                    {
                        "name": "月线第三浪延伸",
                        "probability": 30,
                        "key_support": 3400,
                        "key_resistance": 3900,
                        "wave_position": "从1516起浪3延伸中",
                        "target": "4200-4500",
                        "confirm_signals": ["突破3900", "科技股领涨放量", "回调不跌破3400"],
                        "deny_signals": ["跌破3400", "3900附近受阻", "量能萎缩"],
                    },
                    {
                        "name": "月线B浪反弹末端",
                        "probability": 40,
                        "key_support": 3300,
                        "key_resistance": 3900,
                        "wave_position": "B浪反弹接近末端",
                        "target": "C浪下跌目标2200-2600",
                        "confirm_signals": ["3900附近形成顶部", "跌破3300", "C浪5浪结构下行"],
                        "deny_signals": ["突破3900创新高", "低点不断抬高", "突破4500(B浪假设失效)"],
                    },
                    {
                        "name": "月线双底突破确认",
                        "probability": 30,
                        "key_support": 3200,
                        "key_resistance": 3800,
                        "wave_position": "双底突破确认中",
                        "target": "4200-5000",
                        "confirm_signals": ["3200形成有效支撑", "突破3800确认双底", "浪3强势上攻"],
                        "deny_signals": ["跌破2800(双底失效)", "长期横盘无法突破", "形成更低低点"],
                    },
                ],
            },
            "weekly": {
                "label": "周线",
                "scenarios": [
                    {
                        "name": "周线第五浪上行",
                        "probability": 25,
                        "key_support": 3600,
                        "key_resistance": 3900,
                        "wave_position": "第五浪上行中",
                        "target": "4000-4200",
                        "confirm_signals": ["突破3900", "放量上行", "回调不破3600"],
                        "deny_signals": ["跌破3600", "3900受阻", "量价背离"],
                    },
                    {
                        "name": "周线调整浪4回调",
                        "probability": 40,
                        "key_support": 3500,
                        "key_resistance": 3800,
                        "wave_position": "调整浪4回调中",
                        "target": "3200-3400",
                        "confirm_signals": ["3800受阻回落", "跌破3500", "3浪调整结构"],
                        "deny_signals": ["突破3800创新高", "低点不断抬高", "跌破3200"],
                    },
                    {
                        "name": "周线收敛形态",
                        "probability": 35,
                        "key_support": 3500,
                        "key_resistance": 3900,
                        "wave_position": "3500-3900区间收敛整理",
                        "target": "突破方向待定",
                        "confirm_signals": ["3500支撑有效", "3900压力明显", "波动率收窄"],
                        "deny_signals": ["跌破3500", "突破3900", "波动率突然放大"],
                    },
                ],
            },
        },
    },
    "科创50": {
        "symbol": "sh000688",
        "source": "a",
        "timeframes": {
            "yearly": {
                "label": "年线",
                "scenarios": [
                    {
                        "name": "第三推动浪运行中",
                        "probability": 30,
                        "key_support": 1200,
                        "key_resistance": 1500,
                        "wave_position": "浪3中期",
                        "target": "1600-1800",
                        "confirm_signals": ["突破1500持续上攻", "半导体/AI板块领涨", "回调不破1200"],
                        "deny_signals": ["跌破1200支撑", "在1500形成顶部", "第三浪短于第一浪"],
                    },
                    {
                        "name": "B浪反弹接近尾声",
                        "probability": 40,
                        "key_support": 1250,
                        "key_resistance": 1500,
                        "wave_position": "B浪末期,1450-1500区间动能减弱",
                        "target": "C浪下跌目标700-900",
                        "confirm_signals": ["1450-1500受阻", "跌破1250后加速", "科技股集体回调"],
                        "deny_signals": ["突破1550创新高", "低点不断抬高", "突破1700(B浪假设失效)"],
                    },
                    {
                        "name": "大型底部形态确认新周期",
                        "probability": 30,
                        "key_support": 1000,
                        "key_resistance": 1500,
                        "wave_position": "底部确认中,突破1500为新周期信号",
                        "target": "1800-2000",
                        "confirm_signals": ["1200形成有效支撑", "突破1500确认底部", "5浪推动结构清晰"],
                        "deny_signals": ["跌破1000(底部失效)", "长期横盘无法突破", "形成更低低点"],
                    },
                ],
            },
            "monthly": {
                "label": "月线",
                "scenarios": [
                    {
                        "name": "月线第三浪延伸",
                        "probability": 30,
                        "key_support": 1300,
                        "key_resistance": 1550,
                        "wave_position": "从656起浪3延伸中",
                        "target": "1700-1900",
                        "confirm_signals": ["突破1550", "半导体/AI板块领涨", "回调不跌破1300"],
                        "deny_signals": ["跌破1300", "1550附近受阻", "第三浪短于第一浪"],
                    },
                    {
                        "name": "月线B浪反弹末端",
                        "probability": 35,
                        "key_support": 1200,
                        "key_resistance": 1500,
                        "wave_position": "B浪反弹接近末端",
                        "target": "C浪下跌目标700-900",
                        "confirm_signals": ["1500附近形成顶部", "跌破1200", "科技股集体回调"],
                        "deny_signals": ["突破1550创新高", "低点不断抬高", "突破1700(B浪假设失效)"],
                    },
                    {
                        "name": "月线底部确认新周期",
                        "probability": 35,
                        "key_support": 1100,
                        "key_resistance": 1500,
                        "wave_position": "底部确认中",
                        "target": "1800-2000",
                        "confirm_signals": ["1100形成有效支撑", "突破1500确认底部", "5浪推动结构清晰"],
                        "deny_signals": ["跌破1000(底部失效)", "长期横盘无法突破", "形成更低低点"],
                    },
                ],
            },
            "weekly": {
                "label": "周线",
                "scenarios": [
                    {
                        "name": "周线第五浪上行",
                        "probability": 25,
                        "key_support": 1380,
                        "key_resistance": 1520,
                        "wave_position": "第五浪上行中",
                        "target": "1600-1700",
                        "confirm_signals": ["突破1520", "放量上行", "回调不破1380"],
                        "deny_signals": ["跌破1380", "1520受阻", "量价背离"],
                    },
                    {
                        "name": "周线调整浪回调",
                        "probability": 40,
                        "key_support": 1350,
                        "key_resistance": 1500,
                        "wave_position": "调整浪回调中",
                        "target": "1200-1300",
                        "confirm_signals": ["1500受阻回落", "跌破1350", "3浪调整结构"],
                        "deny_signals": ["突破1500创新高", "低点不断抬高", "跌破1200"],
                    },
                    {
                        "name": "周线三角形整理",
                        "probability": 35,
                        "key_support": 1350,
                        "key_resistance": 1500,
                        "wave_position": "1350-1500区间三角形整理",
                        "target": "突破方向待定",
                        "confirm_signals": ["1350支撑有效", "1500压力明显", "波动率收窄"],
                        "deny_signals": ["跌破1350", "突破1500", "波动率突然放大"],
                    },
                ],
            },
        },
    },
    "恒生指数": {
        "symbol": "HSI",
        "source": "hk",
        "timeframes": {
            "yearly": {
                "label": "年线",
                "scenarios": [
                    {
                        "name": "新一轮推动浪第三浪运行中",
                        "probability": 25,
                        "key_support": 24203,
                        "key_resistance": 28056,
                        "wave_position": "浪3子浪(5)中",
                        "target": "33484+",
                        "confirm_signals": ["突破28056持续创新高", "浪3延伸至33484以上", "回调不跌破24203"],
                        "deny_signals": ["跌破24203且无法收复", "28056附近形成双顶", "浪3长度短于浪1"],
                    },
                    {
                        "name": "大型ABC调整B浪反弹61.8%",
                        "probability": 45,
                        "key_support": 24203,
                        "key_resistance": 28056,
                        "wave_position": "B浪末期,26255-28056区域动能衰竭",
                        "target": "C浪下跌目标<14559",
                        "confirm_signals": ["26255-28056形成顶部", "跌破24203持续下行", "C浪5浪推动结构下行"],
                        "deny_signals": ["强势突破28056上攻30000+", "低点不断抬高", "突破33484(B浪假设失效)"],
                    },
                    {
                        "name": "扩张平台调整完成第五大浪启动",
                        "probability": 30,
                        "key_support": 22000,
                        "key_resistance": 28056,
                        "wave_position": "V浪初期",
                        "target": "35000-42000",
                        "confirm_signals": ["持续突破28056向33484推进", "回调幅度有限低点抬高", "V浪5浪推动结构上行"],
                        "deny_signals": ["28000反复受阻双顶", "跌破22000调整未结束", "需要更低低点确认IV完成"],
                    },
                ],
            },
            "monthly": {
                "label": "月线",
                "scenarios": [
                    {
                        "name": "月线浪3子浪(v)运行中",
                        "probability": 25,
                        "key_support": 24000,
                        "key_resistance": 28000,
                        "wave_position": "浪3子浪(v)运行中",
                        "target": "30000-33500",
                        "confirm_signals": ["突破28000", "持续创新高", "回调不跌破24000"],
                        "deny_signals": ["跌破24000且无法收复", "28000附近形成双顶", "浪3短于浪1"],
                    },
                    {
                        "name": "月线B浪反弹接近61.8%",
                        "probability": 45,
                        "key_support": 24000,
                        "key_resistance": 28000,
                        "wave_position": "B浪接近61.8%回撤位",
                        "target": "C浪下跌目标<14559",
                        "confirm_signals": ["28000附近形成顶部", "跌破24000持续下行", "C浪5浪推动结构下行"],
                        "deny_signals": ["强势突破28000上攻30000+", "低点不断抬高", "突破33484(B浪假设失效)"],
                    },
                    {
                        "name": "月线V浪初期启动",
                        "probability": 30,
                        "key_support": 22000,
                        "key_resistance": 28000,
                        "wave_position": "V浪初期启动中",
                        "target": "33000-42000",
                        "confirm_signals": ["持续突破28000", "回调低点抬高", "V浪5浪推动结构上行"],
                        "deny_signals": ["28000反复受阻", "跌破22000", "需要更低低点确认IV完成"],
                    },
                ],
            },
            "weekly": {
                "label": "周线",
                "scenarios": [
                    {
                        "name": "周线反弹浪运行中",
                        "probability": 30,
                        "key_support": 25500,
                        "key_resistance": 27000,
                        "wave_position": "反弹浪运行中",
                        "target": "28000-29000",
                        "confirm_signals": ["突破27000", "放量上行", "回调不破25500"],
                        "deny_signals": ["跌破25500", "27000受阻", "量价背离"],
                    },
                    {
                        "name": "周线调整浪C运行中",
                        "probability": 35,
                        "key_support": 24000,
                        "key_resistance": 26500,
                        "wave_position": "调整浪C下行中",
                        "target": "22000-23000",
                        "confirm_signals": ["26500受阻回落", "跌破24000", "5浪下行结构"],
                        "deny_signals": ["突破26500创新高", "低点不断抬高", "跌破22000"],
                    },
                    {
                        "name": "周线底部构筑中",
                        "probability": 35,
                        "key_support": 25000,
                        "key_resistance": 27000,
                        "wave_position": "底部构筑中",
                        "target": "28000+",
                        "confirm_signals": ["25000支撑有效", "27000压力突破", "放量上攻"],
                        "deny_signals": ["跌破25000", "27000反复受阻", "量能萎缩"],
                    },
                ],
            },
        },
    },
    "恒生科技指数": {
        "symbol": "HSTECH",
        "source": "hk",
        "timeframes": {
            "yearly": {
                "label": "年线",
                "scenarios": [
                    {
                        "name": "新推动浪第三浪运行中",
                        "probability": 25,
                        "key_support": 4620,
                        "key_resistance": 6715,
                        "wave_position": "浪3子浪(v)中",
                        "target": "8000-10001",
                        "confirm_signals": ["从4620反弹突破5500", "浪4回调不破4620", "浪5突破6715创新高"],
                        "deny_signals": ["跌破4620且无法收复", "5500-6000形成明显顶部", "浪3长度短于浪1"],
                    },
                    {
                        "name": "大型ABC调整B浪反弹接近关键阻力",
                        "probability": 40,
                        "key_support": 4600,
                        "key_resistance": 6715,
                        "wave_position": "B浪末期,6715附近动能衰竭",
                        "target": "C浪下跌目标<2720",
                        "confirm_signals": ["6715附近形成双顶或头肩顶", "跌破4600持续下行", "C浪5浪推动下破2720"],
                        "deny_signals": ["强势突破6715上攻7500+", "低点不断抬高", "突破8000(B浪假设需修正)"],
                    },
                    {
                        "name": "双底形态确认新一轮牛市启动",
                        "probability": 35,
                        "key_support": 4600,
                        "key_resistance": 5500,
                        "wave_position": "双底颈线5500待突破,主升浪3蓄势",
                        "target": "8000-11000",
                        "confirm_signals": ["4600-4800有效支撑反弹", "突破5500颈线确认双底", "浪3强势突破6715"],
                        "deny_signals": ["跌破2984(双底失效)", "5000-5500长期横盘无法突破", "形成更低高点和更低低点"],
                    },
                ],
            },
            "monthly": {
                "label": "月线",
                "scenarios": [
                    {
                        "name": "月线浪3子浪(v)",
                        "probability": 25,
                        "key_support": 4600,
                        "key_resistance": 5500,
                        "wave_position": "浪3子浪(v)运行中",
                        "target": "6000-8000",
                        "confirm_signals": ["突破5500", "持续创新高", "回调不跌破4600"],
                        "deny_signals": ["跌破4600且无法收复", "5500附近形成顶部", "浪3短于浪1"],
                    },
                    {
                        "name": "月线B浪反弹接近关键阻力",
                        "probability": 40,
                        "key_support": 4600,
                        "key_resistance": 5500,
                        "wave_position": "B浪接近关键阻力区",
                        "target": "C浪下跌目标<2720",
                        "confirm_signals": ["5500附近形成双顶", "跌破4600持续下行", "C浪5浪推动下行"],
                        "deny_signals": ["强势突破5500上攻7500+", "低点不断抬高", "突破8000(B浪假设需修正)"],
                    },
                    {
                        "name": "月线双底形态确认",
                        "probability": 35,
                        "key_support": 4600,
                        "key_resistance": 5500,
                        "wave_position": "双底形态确认中",
                        "target": "7000-10000",
                        "confirm_signals": ["4600有效支撑反弹", "突破5500确认双底", "浪3强势突破6715"],
                        "deny_signals": ["跌破2984(双底失效)", "长期横盘无法突破", "形成更低高点和更低低点"],
                    },
                ],
            },
            "weekly": {
                "label": "周线",
                "scenarios": [
                    {
                        "name": "周线反弹浪运行",
                        "probability": 25,
                        "key_support": 4800,
                        "key_resistance": 5200,
                        "wave_position": "反弹浪运行中",
                        "target": "5500-6000",
                        "confirm_signals": ["突破5200", "放量上行", "回调不破4800"],
                        "deny_signals": ["跌破4800", "5200受阻", "量价背离"],
                    },
                    {
                        "name": "周线调整浪延续",
                        "probability": 40,
                        "key_support": 4600,
                        "key_resistance": 5100,
                        "wave_position": "调整浪延续下行中",
                        "target": "4000-4400",
                        "confirm_signals": ["5100受阻回落", "跌破4600", "5浪下行结构"],
                        "deny_signals": ["突破5100创新高", "低点不断抬高", "跌破4000"],
                    },
                    {
                        "name": "周线底部整理",
                        "probability": 35,
                        "key_support": 4600,
                        "key_resistance": 5200,
                        "wave_position": "底部整理中",
                        "target": "5500+",
                        "confirm_signals": ["4600支撑有效", "5200压力突破", "放量上攻"],
                        "deny_signals": ["跌破4600", "5200反复受阻", "量能萎缩"],
                    },
                ],
            },
        },
    },
}


# ============================================================
# 数据获取
# ============================================================

def fetch_all_data():
    """获取所有指数的最新数据,返回 {指数名: {df, df_monthly, df_weekly, latest_date, close, open, high, low, volume, prev_close, change_pct}}"""
    results = {}
    for name, cfg in INDICES.items():
        symbol = cfg["symbol"]
        source = cfg["source"]
        print(f"  获取 {name} ({symbol}) ...")
        if source == "a":
            df = fetch_a_share_data(symbol)
        else:
            df = fetch_hk_data(symbol)
        if df is None or df.empty:
            print(f"  [!] {name} 数据获取失败,跳过")
            continue
        # 取最后两行用于计算涨跌幅
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        close = float(last["close"])
        prev_close = float(prev["close"])
        change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0

        # 确保日期是datetime对象
        last_date = last["date"]
        if isinstance(last_date, str):
            from datetime import datetime
            last_date = datetime.strptime(last_date, '%Y-%m-%d')

        # 重采样为月线和周线
        df_monthly = resample_to_monthly(df)
        df_weekly = resample_to_weekly(df)

        results[name] = {
            "df": df,
            "df_monthly": df_monthly,
            "df_weekly": df_weekly,
            "latest_date": last_date,
            "close": close,
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "volume": float(last.get("volume", 0)) if pd.notna(last.get("volume", 0)) else 0,
            "prev_close": prev_close,
            "change_pct": change_pct,
        }
        print(f"    最新日期: {last_date.strftime('%Y-%m-%d')}, 收盘: {close:,.2f}, 涨跌幅: {change_pct:+.2f}%")
    return results


# ============================================================
# 报告生成
# ============================================================

def generate_report(data, state):
    """
    生成Markdown格式日报
    返回 (report_text, data_date_str)
    """
    # 确定报告日期: 使用数据中最大的日期
    all_dates = [v["latest_date"] for v in data.values()]
    data_date = max(all_dates)
    data_date_str = data_date.strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# 波浪预测日报 {data_date_str}")
    lines.append("")
    lines.append(f"> 数据日期: {data_date_str} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # 总览表
    lines.append("## 📊 指数总览")
    lines.append("")
    lines.append("| 指数 | 收盘 | 涨跌幅 | 最高 | 最低 |")
    lines.append("|------|------|--------|------|------|")
    for name in INDICES:
        if name not in data:
            lines.append(f"| {name} | N/A | N/A | N/A | N/A |")
            continue
        d = data[name]
        arrow = "+" if d["change_pct"] >= 0 else ""
        lines.append(
            f"| {name} | {d['close']:,.2f} | {arrow}{d['change_pct']:.2f}% "
            f"| {d['high']:,.2f} | {d['low']:,.2f} |"
        )
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # 各指数详细分析
    for name, cfg in INDICES.items():
        if name not in data:
            lines.append(f"## 🔍 {name}")
            lines.append("")
            lines.append("> 数据获取失败,跳过分析")
            lines.append("")
            continue

        d = data[name]
        close = d["close"]

        # 日线数据（用于年线级别）
        daily_volume = d["volume"]
        df = d["df"]
        if len(df) >= 2:
            daily_prev_volume = float(df.iloc[-2].get("volume", 0)) if pd.notna(df.iloc[-2].get("volume", 0)) else 0
        else:
            daily_prev_volume = 0

        # 月线数据（用于月线级别）
        df_m = d.get("df_monthly")
        if df_m is not None and len(df_m) >= 2:
            m_last = df_m.iloc[-1]
            m_prev = df_m.iloc[-2]
            m_close = float(m_last["close"])
            m_prev_close = float(m_prev["close"])
            m_volume = float(m_last.get("volume", 0)) if pd.notna(m_last.get("volume", 0)) else 0
            m_prev_volume = float(m_prev.get("volume", 0)) if pd.notna(m_prev.get("volume", 0)) else 0
        else:
            m_close = close
            m_prev_close = close
            m_volume = 0
            m_prev_volume = 0

        # 周线数据（用于周线级别）
        df_w = d.get("df_weekly")
        if df_w is not None and len(df_w) >= 2:
            w_last = df_w.iloc[-1]
            w_prev = df_w.iloc[-2]
            w_close = float(w_last["close"])
            w_prev_close = float(w_prev["close"])
            w_volume = float(w_last.get("volume", 0)) if pd.notna(w_last.get("volume", 0)) else 0
            w_prev_volume = float(w_prev.get("volume", 0)) if pd.notna(w_prev.get("volume", 0)) else 0
        else:
            w_close = close
            w_prev_close = close
            w_volume = 0
            w_prev_volume = 0

        lines.append(f"## 🔍 {name}")
        lines.append("")
        lines.append(f"**收盘**: {close:,.2f} | **涨跌幅**: {d['change_pct']:+.2f}% | **最高**: {d['high']:,.2f} | **最低**: {d['low']:,.2f}")
        lines.append("")

        # 各时间级别分析 + 收集多级别结果用于关联分析
        timeframes = cfg.get("timeframes", {})
        tf_labels = {
            "yearly": "🕐 年线级别（长期趋势）",
            "monthly": "📅 月线级别（中期趋势）",
            "weekly": "📆 周线级别（短期趋势）",
        }
        # 收集每个级别的信号汇总（用于多级别关联分析）
        tf_signal_summary = {}

        for level_key in ["yearly", "monthly", "weekly"]:
            tf = timeframes.get(level_key)
            if tf is None:
                continue

            lines.append(f"### {tf_labels.get(level_key, tf['label'] + '级别')}")
            lines.append("")
            lines.append("---")
            lines.append("")

            # 选择对应时间级别的数据
            if level_key == "yearly":
                tf_close = close
                tf_volume = daily_volume
                tf_prev_volume = daily_prev_volume
                tf_prev_close = d["prev_close"]
            elif level_key == "monthly":
                tf_close = m_close
                tf_volume = m_volume
                tf_prev_volume = m_prev_volume
                tf_prev_close = m_prev_close
            else:  # weekly
                tf_close = w_close
                tf_volume = w_volume
                tf_prev_volume = w_prev_volume
                tf_prev_close = w_prev_close

            # 该级别的累计信号分数
            level_confirm_score = 0.0
            level_deny_score = 0.0
            level_confirmed = []
            level_denied = []

            # 各场景分析
            for scenario in tf["scenarios"]:
                # v1.2: 自动调整场景（价格突破关键位时）
                adjusted = auto_adjust_scenario(scenario, tf_close)
                if adjusted.get("_auto_adjusted"):
                    lines.append(f"> 🔄 场景自动调整: {scenario['name']}")
                    if "_auto_adjusted_resistance" in adjusted:
                        adj = adjusted["_auto_adjusted_resistance"]
                        lines.append(f">   阻力位 {adj['from']:,.0f} → {adj['to']:,.0f} ({adj['reason']})")
                    if "_auto_adjusted_support" in adjusted:
                        adj = adjusted["_auto_adjusted_support"]
                        lines.append(f">   支撑位 {adj['from']:,.0f} → {adj['to']:,.0f} ({adj['reason']})")
                    lines.append("")

                # v1.2: 使用带权重的信号检测
                confirmed, denied, confirm_score, deny_score = check_signals_weighted(
                    adjusted, tf_close, tf_volume, tf_prev_volume, tf_prev_close
                )
                level_confirm_score += confirm_score
                level_deny_score += deny_score
                level_confirmed.extend(confirmed)
                level_denied.extend(denied)

                new_confirmed = update_state(
                    state, data_date_str, level_key, name, adjusted["name"], confirmed, denied
                )

                prob = adjusted["probability"]
                # v1.2: 使用综合评分替代简单判断
                net_score = confirm_score - deny_score
                if denied and not confirmed:
                    status = "可能性降低"
                    status_icon = "🔴"
                elif confirmed and not denied:
                    if net_score >= 2.0:
                        status = "可能性大幅增强"
                        status_icon = "🟢🟢"
                    else:
                        status = "可能性增强"
                        status_icon = "🟢"
                elif confirmed and denied:
                    if net_score > 0:
                        status = "信号偏多,需观察"
                        status_icon = "🟡↗"
                    elif net_score < 0:
                        status = "信号偏空,需观察"
                        status_icon = "🟡↘"
                    else:
                        status = "信号矛盾,需观察"
                        status_icon = "🟡"
                else:
                    status = "信号未触发"
                    status_icon = "⚪"

                lines.append(f"**{adjusted['name']}** [{prob}%] {status_icon}{status}")
                lines.append("")
                lines.append(f"> 波浪位置: {adjusted['wave_position']}")
                lines.append(f"> 关键支撑: **{adjusted['key_support']:,.0f}** | 关键阻力: **{adjusted['key_resistance']:,.0f}** | 目标: **{adjusted['target']}**")
                # v1.2: 显示信号权重分数
                if confirmed or denied:
                    lines.append(f"> 信号评分: 确认 {confirm_score:.1f} | 否认 {deny_score:.1f} | 净分 {net_score:+.1f}")
                lines.append("")

                # 信号状态
                if confirmed:
                    conf_text = "、".join(confirmed)
                    new_tag = ""
                    if new_confirmed:
                        new_tag = f" 🆕新增: {'、'.join(new_confirmed)}"
                    lines.append(f"- ✅ **已确认**: {conf_text}{new_tag}")
                else:
                    lines.append(f"- ✅ **已确认**: 无")

                if denied:
                    deny_text = "、".join(denied)
                    lines.append(f"- ❌ **已否认**: {deny_text}")
                else:
                    lines.append(f"- ❌ **已否认**: 无")

                lines.append("")

            # 记录该级别的信号汇总
            tf_signal_summary[level_key] = {
                "confirmed": level_confirmed,
                "denied": level_denied,
                "confirm_score": level_confirm_score,
                "deny_score": level_deny_score,
            }

        # v1.2: 多级别关联分析
        if tf_signal_summary:
            correlation = analyze_multi_timeframe_correlation(name, tf_signal_summary)
            lines.append("### 🎯 多级别共振分析")
            lines.append("")
            lines.append(f"**{correlation['resonance_icon']} {correlation['resonance']}** | 方向: **{correlation['direction']}**")
            lines.append(f"> {correlation['details']}")
            lines.append("")

    # 免责声明
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("*免责声明: 本报告仅为技术分析参考,不构成投资建议。市场有风险,投资需谨慎。*")
    lines.append("")

    return "\n".join(lines), data_date_str


# ============================================================
# 图表生成
# ============================================================

def generate_charts(data):
    """调用elliott.charts模块生成图表"""
    try:
        from elliott.charts import generate_all_charts, generate_multi_tf_charts
    except ImportError:
        print("[!] 无法导入elliott.charts模块,跳过图表生成")
        return {}

    prices = {}
    for name, d in data.items():
        prices[name] = d["close"]

    os.makedirs(settings.ELLIOTT_CHART_DIR, exist_ok=True)

    # 年线图表（已有功能）
    results = generate_all_charts(prices, settings.ELLIOTT_CHART_DIR)

    # 月线和周线图表（新增）
    multi_tf_results = generate_multi_tf_charts(data, settings.ELLIOTT_CHART_DIR)
    results.update(multi_tf_results)

    return results


# ============================================================
# 报告保存
# ============================================================

def save_report(report_text, data_date_str):
    """将报告保存为Markdown文件"""
    os.makedirs(settings.ELLIOTT_REPORT_DIR, exist_ok=True)
    filename = f"波浪预测日报_{data_date_str}.md"
    filepath = os.path.join(settings.ELLIOTT_REPORT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"  报告已保存: {filepath}")
    return filepath


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="艾略特波浪每日预测更新")
    parser.add_argument("--force", action="store_true", help="强制运行,忽略交易日检查")
    parser.add_argument("--no-push", action="store_true", help="不推送企业微信")
    parser.add_argument("--no-chart", action="store_true", help="不生成图表")
    args = parser.parse_args()

    print("=" * 60)
    print("艾略特波浪每日预测更新")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 交易日判断
    if not is_trading_day(market="a", force=args.force):
        sys.exit(0)

    # 2. 获取数据
    print("\n[1/5] 获取指数数据...")
    data = fetch_all_data()
    if not data:
        print("[!] 所有指数数据获取失败,退出")
        sys.exit(1)

    # 3. 加载状态
    print("\n[2/5] 加载信号状态...")
    state = load_state()

    # 迁移旧格式状态键
    migrated = migrate_state(state)
    migrated_count = len([k for k in migrated if k not in state])
    if migrated_count > 0:
        print(f"  迁移了 {migrated_count} 个旧格式状态键")
        state = migrated

    # 4. 生成报告
    print("\n[3/5] 生成分析报告...")
    report_text, data_date_str = generate_report(data, state)

    # 5. 保存报告
    print("\n[4/5] 保存报告与图表...")
    report_path = save_report(report_text, data_date_str)

    # 保存状态(在生成报告时已更新)
    save_state(state)

    # 6. 生成图表
    if not args.no_chart:
        print("  生成波浪图表...")
        chart_results = generate_charts(data)
        if chart_results:
            for name, path in chart_results.items():
                print(f"    {name}: {path}")
        else:
            print("  [!] 图表生成失败或无结果")
    else:
        print("  跳过图表生成 (--no-chart)")

    # 7. 推送企业微信
    print("\n[5/5] 推送企业微信...")
    if not args.no_push:
        pusher = WeChatPusher(settings.WEBHOOK_URL)
        push_success = pusher.split_and_send(report_text)
        if not push_success:
            print("[!] 部分消息推送失败")
    else:
        print("  跳过推送 (--no-push)")

    print("\n" + "=" * 60)
    print(f"日报更新完成! 数据日期: {data_date_str}")
    print(f"报告路径: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
