#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
艾略特波浪分析 Agent
基于波浪理论分析市场走势，生成多时间框架的波浪预测报告
"""

import os
import re
import json
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from datetime import datetime

import pandas as pd
import akshare as ak

from config.settings import settings

from ..base_agent import BaseAgent
from services import WebhookService
from elliott.signals import _check_signal_with_weight


class ElliottWaveAgent(BaseAgent):
    """艾略特波浪分析 Agent"""

    # 默认指数配置
    DEFAULT_INDICES = {
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
        "阿里巴巴-SW": {
            "symbol": "09988",
            "source": "hk_stock",
            "timeframes": {
                "yearly": {
                    "label": "年线",
                    "scenarios": [
                        {
                            "name": "新一轮推动浪第三浪运行中",
                            "probability": 25,
                            "key_support": 80,
                            "key_resistance": 130,
                            "wave_position": "浪3子浪(i)或(ii)中",
                            "target": "180-250",
                            "confirm_signals": ["突破130持续创新高", "回调不跌破80", "浪3延伸突破150"],
                            "deny_signals": ["跌破80且无法收复", "130附近形成双顶", "量价背离明显"],
                        },
                        {
                            "name": "大型ABC调整B浪反弹61.8%",
                            "probability": 45,
                            "key_support": 80,
                            "key_resistance": 130,
                            "wave_position": "B浪末期,反弹接近61.8%回撤位",
                            "target": "C浪下跌目标<60",
                            "confirm_signals": ["130附近形成顶部", "跌破80持续下行", "C浪5浪推动结构下行"],
                            "deny_signals": ["强势突破130上攻180+", "低点不断抬高", "突破200(B浪假设失效)"],
                        },
                        {
                            "name": "扩张平台调整完成V浪启动",
                            "probability": 30,
                            "key_support": 70,
                            "key_resistance": 130,
                            "wave_position": "V浪初期,底部确认阶段",
                            "target": "200-300",
                            "confirm_signals": ["持续突破130向200推进", "回调低点不断抬高", "V浪5浪推动结构上行"],
                            "deny_signals": ["130反复受阻双顶", "跌破70调整未结束", "需要更低低点确认IV完成"],
                        },
                    ],
                },
                "monthly": {
                    "label": "月线",
                    "scenarios": [
                        {
                            "name": "月线浪3子浪(i)运行中",
                            "probability": 25,
                            "key_support": 80,
                            "key_resistance": 130,
                            "wave_position": "浪3子浪(i)运行中",
                            "target": "150-200",
                            "confirm_signals": ["突破130", "持续创新高", "回调不跌破80"],
                            "deny_signals": ["跌破80且无法收复", "130附近形成顶部", "反弹动能衰竭"],
                        },
                        {
                            "name": "月线B浪反弹接近关键阻力",
                            "probability": 45,
                            "key_support": 80,
                            "key_resistance": 130,
                            "wave_position": "B浪接近61.8%回撤位",
                            "target": "C浪下跌目标<60",
                            "confirm_signals": ["130附近形成双顶", "跌破80持续下行", "C浪5浪推动下行"],
                            "deny_signals": ["强势突破130上攻180+", "低点不断抬高", "突破200(B浪假设失效)"],
                        },
                        {
                            "name": "月线V浪初期启动",
                            "probability": 30,
                            "key_support": 70,
                            "key_resistance": 130,
                            "wave_position": "V浪初期启动中",
                            "target": "200-300",
                            "confirm_signals": ["持续突破130", "回调低点抬高", "V浪5浪推动结构上行"],
                            "deny_signals": ["130反复受阻", "跌破70", "需要更低低点确认IV完成"],
                        },
                    ],
                },
                "weekly": {
                    "label": "周线",
                    "scenarios": [
                        {
                            "name": "周线反弹浪运行中",
                            "probability": 30,
                            "key_support": 95,
                            "key_resistance": 120,
                            "wave_position": "反弹浪运行中",
                            "target": "130-150",
                            "confirm_signals": ["突破120", "放量上行", "回调不破95"],
                            "deny_signals": ["跌破95", "120受阻", "量价背离"],
                        },
                        {
                            "name": "周线调整浪C运行中",
                            "probability": 35,
                            "key_support": 80,
                            "key_resistance": 115,
                            "wave_position": "调整浪C下行中",
                            "target": "60-75",
                            "confirm_signals": ["115受阻回落", "跌破80", "5浪下行结构"],
                            "deny_signals": ["突破115创新高", "低点不断抬高", "跌破60"],
                        },
                        {
                            "name": "周线底部构筑中",
                            "probability": 35,
                            "key_support": 85,
                            "key_resistance": 120,
                            "wave_position": "底部构筑中",
                            "target": "130+",
                            "confirm_signals": ["85支撑有效", "120压力突破", "放量上攻"],
                            "deny_signals": ["跌破85", "120反复受阻", "量能萎缩"],
                        },
                    ],
                },
            },
        },
    }


    def __init__(self, config: Optional[Dict] = None):
        """
        初始化艾略特波浪 Agent

        Config 可选参数:
        - report_dir: 报告输出目录
        - chart_dir: 图表输出目录
        - state_file: 状态文件路径
        - webhook_url: 企业微信 Webhook URL（可选）
        - indices: 自定义指数配置
        """
        config = config or {}

        super().__init__("ElliottWave", config)

        self.report_dir = Path(config.get(
            "report_dir",
            str(settings.BASE_DIR / "波浪预测" / "每日更新")
        ))
        self.chart_dir = Path(config.get(
            "chart_dir",
            str(settings.BASE_DIR / "波浪预测" / "波浪预测图形")
        ))
        self.state_file = Path(config.get("state_file", ".elliott_state.json"))

        # 指数配置
        self.indices = config.get("indices", self.DEFAULT_INDICES)

        # Webhook 服务（可选）
        webhook_url = config.get("webhook_url")
        self.webhook_service = WebhookService(webhook_url) if webhook_url else None

        # 加载状态
        self.state = self._load_state()

        # 确保目录存在
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.chart_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 配置验证
    # ============================================================

    def validate_config(self) -> bool:
        """验证配置"""
        if not self.indices:
            self.log_error("未配置任何指数")
            return False

        return True

    # ============================================================
    # 主执行逻辑
    # ============================================================

    def run(
        self,
        index_names: Optional[List[str]] = None,
        push_report: bool = True,
        generate_charts: bool = True
    ) -> Dict:
        """
        执行波浪分析

        Args:
            index_names: 指定分析的指数列表（None表示全部）
            push_report: 是否推送报告
            generate_charts: 是否生成图表

        Returns:
            执行结果
        """
        # 确定要分析的指数
        if index_names:
            indices_to_analyze = {k: v for k, v in self.indices.items() if k in index_names}
        else:
            indices_to_analyze = self.indices

        self.log_info(f"开始分析 {len(indices_to_analyze)} 个指数")

        # 1. 获取数据
        data = self._fetch_all_data(indices_to_analyze)
        if not data:
            return {
                "success": False,
                "message": "所有指数数据获取失败",
                "data": {"analyzed": 0}
            }

        # 2. 迁移旧状态格式
        self._migrate_state()

        # 3. 生成报告
        report_text, data_date_str = self._generate_report(data, self.state)

        # 4. 保存报告
        report_path = self.report_dir / f"波浪预测日报_{data_date_str}.md"
        report_path.write_text(report_text, encoding="utf-8")
        self.log_info(f"报告已保存: {report_path}")

        # 5. 保存状态
        self._save_state()

        # 6. 生成图表
        chart_results = {}
        if generate_charts:
            chart_results = self._generate_charts(data)
            self.log_info(f"生成 {len(chart_results)} 个图表")

        # 7. 推送报告
        if push_report and self.webhook_service:
            response = self.webhook_service.send_markdown(report_text)
            self.log_info(f"推送结果: {'成功' if response['success'] else '失败'}")

        return {
            "success": True,
            "message": f"波浪分析完成，数据日期: {data_date_str}",
            "data": {
                "analyzed_count": len(data),
                "report_path": str(report_path),
                "charts_count": len(chart_results),
                "pushed": push_report and self.webhook_service is not None
            }
        }

    # ============================================================
    # 数据获取
    # ============================================================

    def _fetch_all_data(self, indices: Dict) -> Dict:
        """
        获取所有指数数据

        Args:
            indices: 指数配置字典

        Returns:
            数据字典
        """
        results = {}

        for name, cfg in indices.items():
            symbol = cfg["symbol"]
            source = cfg["source"]
            self.log_info(f"获取 {name} ({symbol}) 数据...")

            try:
                if source == "a":
                    df = self._fetch_a_share_data(symbol)
                elif source == "hk_stock":
                    df = self._fetch_hk_stock_data(symbol)
                else:
                    df = self._fetch_hk_data(symbol)

                if df is None or df.empty:
                    self.log_warning(f"{name} 数据获取失败")
                    continue

                # 计算涨跌幅
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) >= 2 else last
                close = float(last["close"])
                prev_close = float(prev["close"])
                change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0

                # 重采样
                df_monthly = self._resample_to_monthly(df)
                df_weekly = self._resample_to_weekly(df)

                results[name] = {
                    "df": df,
                    "df_monthly": df_monthly,
                    "df_weekly": df_weekly,
                    "latest_date": last["date"],
                    "close": close,
                    "open": float(last["open"]),
                    "high": float(last["high"]),
                    "low": float(last["low"]),
                    "volume": float(last.get("volume", 0)) if pd.notna(last.get("volume", 0)) else 0,
                    "prev_close": prev_close,
                    "change_pct": change_pct,
                }

                self.log_info(f"  收盘: {close:.2f}, 涨跌幅: {change_pct:+.2f}%")

            except Exception as e:
                self.log_error(f"{name} 数据获取异常: {e}")

        return results

    def _fetch_a_share_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取A股指数日线数据"""
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                return None

            # 统一列名
            df = df.rename(columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            })
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            self.log_error(f"获取A股数据失败 {symbol}: {e}")
            return None

    def _fetch_hk_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取港股指数日线数据"""
        try:
            df = ak.stock_hk_index_daily_sina(symbol=symbol)
            if df is None or df.empty:
                return None

            # 统一列名
            col_map = {}
            for col in df.columns:
                col_lower = col.lower().strip()
                if col_lower == "date":
                    col_map[col] = "date"
                elif col_lower == "open":
                    col_map[col] = "open"
                elif col_lower == "high":
                    col_map[col] = "high"
                elif col_lower == "low":
                    col_map[col] = "low"
                elif col_lower == "close":
                    col_map[col] = "close"
                elif "vol" in col_lower:
                    col_map[col] = "volume"

            df = df.rename(columns=col_map)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            self.log_error(f"获取港股数据失败 {symbol}: {e}")
            return None

    def _fetch_hk_stock_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取港股个股日线数据"""
        try:
            df = ak.stock_hk_hist(symbol=symbol, period="daily", adjust="hfq")
            if df is None or df.empty:
                return None

            # 统一列名
            col_map = {}
            for col in df.columns:
                col_lower = col.lower().strip()
                if col_lower == "日期":
                    col_map[col] = "date"
                elif col_lower == "开盘":
                    col_map[col] = "open"
                elif col_lower == "最高":
                    col_map[col] = "high"
                elif col_lower == "最低":
                    col_map[col] = "low"
                elif col_lower == "收盘":
                    col_map[col] = "close"
                elif "成交" in col:
                    col_map[col] = "volume"

            df = df.rename(columns=col_map)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            self.log_error(f"获取港股个股数据失败 {symbol}: {e}")
            return None

    # ============================================================
    # 数据重采样
    # ============================================================

    def _resample_to_monthly(self, df: pd.DataFrame, months: int = 60) -> pd.DataFrame:
        """将日线数据重采样为月线"""
        if df is None or df.empty:
            return pd.DataFrame()

        try:
            if not pd.api.types.is_datetime64_any_dtype(df['date']):
                df = df.copy()
                df['date'] = pd.to_datetime(df['date'])

            df_m = df.set_index('date').resample('ME').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna().reset_index()

            return df_m.tail(months) if len(df_m) > months else df_m
        except Exception as e:
            self.log_error(f"月线重采样失败: {e}")
            return pd.DataFrame()

    def _resample_to_weekly(self, df: pd.DataFrame, weeks: int = 104) -> pd.DataFrame:
        """将日线数据重采样为周线"""
        if df is None or df.empty:
            return pd.DataFrame()

        try:
            if not pd.api.types.is_datetime64_any_dtype(df['date']):
                df = df.copy()
                df['date'] = pd.to_datetime(df['date'])

            df_w = df.set_index('date').resample('W-FRI').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna().reset_index()

            return df_w.tail(weeks) if len(df_w) > weeks else df_w
        except Exception as e:
            self.log_error(f"周线重采样失败: {e}")
            return pd.DataFrame()

    # ============================================================
    # 信号检测
    # ============================================================

    def _check_signals(
        self,
        scenario: Dict,
        close: float,
        volume: float,
        prev_volume: float,
        prev_close: float
    ) -> Tuple[List[str], List[str]]:
        """
        基于关键词的信号检测（使用权重评分系统）

        Returns:
            (已确认信号列表, 已否认信号列表)
        """
        confirmed = []
        denied = []

        for sig in scenario["confirm_signals"]:
            triggered, _ = _check_signal_with_weight(sig, close, volume, prev_volume, prev_close, scenario)
            if triggered:
                confirmed.append(sig)

        for sig in scenario["deny_signals"]:
            triggered, _ = _check_signal_with_weight(sig, close, volume, prev_volume, prev_close, scenario)
            if triggered:
                denied.append(sig)

        return confirmed, denied

    # ============================================================
    # 状态管理
    # ============================================================

    def _load_state(self) -> Dict:
        """加载信号状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self) -> None:
        """保存信号状态"""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_error(f"保存状态失败: {e}")

    def _update_state(
        self,
        data_date_str: str,
        level: str,
        index_name: str,
        scenario_name: str,
        confirmed: List[str],
        denied: List[str]
    ) -> List[str]:
        """更新信号状态，返回新确认的信号"""
        key = f"{level}|{index_name}|{scenario_name}"
        if key not in self.state:
            self.state[key] = {}

        prev = self.state[key].get("confirmed", [])
        new_confirmed = [s for s in confirmed if s not in prev]

        self.state[key] = {
            "date": data_date_str,
            "confirmed": confirmed,
            "denied": denied,
            "new_confirmed": new_confirmed,
        }

        return new_confirmed

    def _migrate_state(self) -> None:
        """迁移旧格式状态键"""
        migrated = {}
        for key, val in self.state.items():
            if '|' in key and not key.startswith(('daily|', 'yearly|', 'monthly|', 'weekly|')):
                new_key = f"daily|{key}"
                migrated[new_key] = val
            else:
                migrated[key] = val

        if len(migrated) != len(self.state):
            self.state = migrated
            self._save_state()

    # ============================================================
    # 报告生成
    # ============================================================

    def _generate_report(self, data: Dict, state: Dict) -> Tuple[str, str]:
        """
        生成 Markdown 格式报告

        Returns:
            (报告文本, 数据日期)
        """
        # 确定数据日期
        all_dates = [v["latest_date"] for v in data.values()]
        data_date = max(all_dates)
        data_date_str = data_date.strftime("%Y-%m-%d")

        lines = [
            f"# 波浪预测日报 {data_date_str}",
            "",
            f"> 数据日期: {data_date_str} | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "## 📊 指数总览",
            "",
            "| 指数 | 收盘 | 涨跌幅 | 最高 | 最低 |",
            "|------|------|--------|------|------|",
        ]

        # 总览表
        for name in self.indices:
            if name not in data:
                lines.append(f"| {name} | N/A | N/A | N/A | N/A |")
                continue

            d = data[name]
            arrow = "+" if d["change_pct"] >= 0 else ""
            lines.append(
                f"| {name} | {d['close']:,.2f} | {arrow}{d['change_pct']:.2f}% "
                f"| {d['high']:,.2f} | {d['low']:,.2f} |"
            )

        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ])

        # 各指数详细分析
        for name, cfg in self.indices.items():
            if name not in data:
                lines.extend([f"## 🔍 {name}", "", "> 数据获取失败,跳过分析", ""])
                continue

            d = data[name]
            close = d["close"]
            cfg_indices = cfg.get("timeframes", {})

            # 获取各时间框架数据
            tf_data = self._get_timeframe_data(d)

            lines.extend([
                f"## 🔍 {name}",
                "",
                f"**收盘**: {close:,.2f} | **涨跌幅**: {d['change_pct']:+.2f}% | "
                f"**最高**: {d['high']:,.2f} | **最低**: {d['low']:,.2f}",
                ""
            ])

            # 各时间级别分析
            for level_key, label_key in [
                ("daily", "📈 日线级别（当日趋势）"),
                ("yearly", "🕐 年线级别（长期趋势）"),
                ("monthly", "📅 月线级别（中期趋势）"),
                ("weekly", "📆 周线级别（短期趋势）")
            ]:
                tf = cfg_indices.get(level_key)
                if tf is None:
                    continue

                lines.extend([f"### {label_key}", "", "---", ""])

                tf_close, tf_volume, tf_prev_volume, tf_prev_close = tf_data[level_key]

                for scenario in tf["scenarios"]:
                    confirmed, denied = self._check_signals(
                        scenario, tf_close, tf_volume, tf_prev_volume, tf_prev_close
                    )

                    new_confirmed = self._update_state(
                        state, data_date_str, level_key, name,
                        scenario["name"], confirmed, denied
                    )

                    prob = scenario["probability"]
                    status_icon, status = self._get_scenario_status(confirmed, denied)

                    lines.extend([
                        f"**{scenario['name']}** [{prob}%] {status_icon}{status}",
                        "",
                        f"> 波浪位置: {scenario['wave_position']}",
                        f"> 关键支撑: **{scenario['key_support']:,.0f}** | "
                        f"关键阻力: **{scenario['key_resistance']:,.0f}** | "
                        f"目标: **{scenario['target']}**",
                        ""
                    ])

                    # 信号状态
                    if confirmed:
                        conf_text = "、".join(confirmed)
                        new_tag = f" 🆕新增: {'、'.join(new_confirmed)}" if new_confirmed else ""
                        lines.append(f"- ✅ **已确认**: {conf_text}{new_tag}")
                    else:
                        lines.append("- ✅ **已确认**: 无")

                    if denied:
                        lines.append(f"- ❌ **已否认**: {'、'.join(denied)}")
                    else:
                        lines.append("- ❌ **已否认**: 无")

                    lines.append("")

        # 免责声明
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "*免责声明: 本报告仅为技术分析参考,不构成投资建议。市场有风险,投资需谨慎。*",
            ""
        ])

        return "\n".join(lines), data_date_str

    def _get_timeframe_data(self, data: Dict) -> Dict:
        """获取各时间框架的数据"""
        df = data["df"]
        df_m = data.get("df_monthly")
        df_w = data.get("df_weekly")

        # 日线数据
        daily_volume = data["volume"]
        daily_prev_volume = float(df.iloc[-2].get("volume", 0)) if len(df) >= 2 else 0
        daily_prev_close = data["prev_close"]

        # 月线数据
        if df_m is not None and len(df_m) >= 2:
            m_last = df_m.iloc[-1]
            m_prev = df_m.iloc[-2]
            m_close = float(m_last["close"])
            m_prev_close = float(m_prev["close"])
            m_volume = float(m_last.get("volume", 0)) if pd.notna(m_last.get("volume", 0)) else 0
            m_prev_volume = float(m_prev.get("volume", 0)) if pd.notna(m_prev.get("volume", 0)) else 0
        else:
            m_close = m_prev_close = data["close"]
            m_volume = m_prev_volume = 0

        # 周线数据
        if df_w is not None and len(df_w) >= 2:
            w_last = df_w.iloc[-1]
            w_prev = df_w.iloc[-2]
            w_close = float(w_last["close"])
            w_prev_close = float(w_prev["close"])
            w_volume = float(w_last.get("volume", 0)) if pd.notna(w_last.get("volume", 0)) else 0
            w_prev_volume = float(w_prev.get("volume", 0)) if pd.notna(w_prev.get("volume", 0)) else 0
        else:
            w_close = w_prev_close = data["close"]
            w_volume = w_prev_volume = 0

        return {
            "daily": (data["close"], daily_volume, daily_prev_volume, daily_prev_close),
            "yearly": (data["close"], daily_volume, daily_prev_volume, daily_prev_close),
            "monthly": (m_close, m_volume, m_prev_volume, m_prev_close),
            "weekly": (w_close, w_volume, w_prev_volume, w_prev_close),
        }

    def _get_scenario_status(self, confirmed: List, denied: List) -> Tuple[str, str]:
        """获取场景状态图标和文字"""
        if denied and not confirmed:
            return "🔴", "可能性降低"
        elif confirmed and not denied:
            return "🟢", "可能性增强"
        elif confirmed and denied:
            return "🟡", "信号矛盾,需观察"
        else:
            return "⚪", "信号未触发"

    # ============================================================
    # 图表生成
    # ============================================================

    def _generate_charts(self, data: Dict) -> Dict[str, str]:
        """生成波浪图表"""
        results = {}

        # 这里应该调用图表生成模块
        # 暂时返回空字典
        self.log_info("图表生成功能待实现")

        return results

    # ============================================================
    # ETF 波浪分析
    # ============================================================

    def analyze_etf(self, etf_code: str, etf_name: str = "", validate: bool = True) -> Dict[str, Any]:
        """
        对ETF进行艾略特波浪分析并评分

        基于多时间框架价格数据，检测波浪位置，
        根据后续上涨可能性给出评分。

        评分逻辑:
        - 推动浪第3浪中（最强主升浪）= 8
        - 推动浪第1浪（启动阶段）= 6
        - 推动浪第5浪（趋势末期）= 4
        - 调整浪末端（接近底部）= 4
        - 调整浪中段 = -2
        - 推动浪末端+顶背离 = -5

        Args:
            etf_code: ETF代码 (e.g. "515850.SH")
            etf_name: ETF名称
            validate: 是否对波浪标注进行规则验证 (默认True)

        Returns:
            波浪分析结果，包含评分和验证报告(若validate=True)
        """
        from datetime import datetime, timedelta

        try:
            # 1. 获取ETF日线数据
            df = self._fetch_etf_data(etf_code)
            if df is None or len(df) < 60:
                return {
                    "etf_code": etf_code,
                    "etf_name": etf_name,
                    "elliott_score": 0,
                    "wave_position": "数据不足",
                    "description": "数据量不足，无法进行波浪分析",
                    "error": "insufficient_data",
                }

            # 2. 计算技术指标辅助判断
            df = self._calculate_wave_indicators(df)

            # 3. 多时间框架分析
            df_weekly = self._resample_to_weekly(df)

            # 4. 获取长周期周线数据，判断大浪级别
            major_wave = {"major_wave_available": False}
            try:
                df_weekly_long = self._fetch_weekly_data(etf_code, years=8)
                if df_weekly_long is not None:
                    latest = df.iloc[-1]
                    current_price = float(latest['close'])
                    major_wave = self._detect_major_wave(df_weekly_long, current_price)
                    if major_wave.get("major_wave_available"):
                        print(f"    大浪级别: {major_wave.get('major_position', 'N/A')} (方向: {major_wave.get('major_direction', '?')})")
                        # Cross-check: weekly data may lag behind daily data.
                        # If daily extremes extend beyond weekly zigzag pivots,
                        # update abs_low/abs_high and the last wave 5 endpoint.
                        self._cross_check_daily_extremes(df, major_wave)
            except Exception as e:
                self.log_error(f"大浪级别分析失败 {etf_code}: {e}")

            # 5. 波浪位置判断（日线级别）
            wave_analysis = self._detect_wave_position(df, df_weekly)

            # 6. 用大浪级别修正日线浪型标注
            wave_analysis = self._apply_major_wave_correction(wave_analysis, major_wave)

            # 7. 基于上涨概率评分
            score, score_rationale = self._wave_score(wave_analysis)

            # 8. 波浪标注验证 (基于Elliott铁律和指导规则)
            validation = None
            if validate:
                try:
                    from .elliott_validator import ElliottWaveValidator
                    validator = ElliottWaveValidator()
                    current_price = float(df.iloc[-1]['close'])
                    validation = validator.validate(wave_analysis, current_price=current_price)
                    # 如果存在铁律违反，降低评分并在rationale中说明
                    if validation.has_iron_violations:
                        iron_ids = ",".join(v.rule_id for v in validation.iron_rule_violations)
                        violation_desc = "; ".join(v.description for v in validation.iron_rule_violations)
                        score_rationale += f" [警告:铁律违反{iron_ids}({violation_desc})]"
                except Exception as e:
                    self.log_error(f"波浪验证异常 {etf_code}: {e}")

            # Extract key price levels for buy/sell point generation
            indicators = wave_analysis.get("indicators", {})
            latest_row = df.iloc[-1] if df is not None and len(df) > 0 else {}
            high_60 = float(latest_row.get("high_60", 0)) if "high_60" in latest_row.index else 0
            low_60 = float(latest_row.get("low_60", 0)) if "low_60" in latest_row.index else 0

            result = {
                "etf_code": etf_code,
                "etf_name": etf_name,
                "elliott_score": score,
                "wave_position": wave_analysis["position"],
                "wave_detail": wave_analysis["detail"],
                "upside_probability": wave_analysis["upside_prob"],
                "score_rationale": score_rationale,
                "description": wave_analysis["description"],
                "indicators": indicators,
                "high_60": round(high_60, 3) if high_60 else 0,
                "low_60": round(low_60, 3) if low_60 else 0,
                "analysis_time": datetime.now().isoformat(),
            }
            if validation is not None:
                result["validation"] = validation.to_dict()
            return result

        except Exception as e:
            return {
                "etf_code": etf_code,
                "etf_name": etf_name,
                "elliott_score": 0,
                "wave_position": "分析失败",
                "description": f"波浪分析异常: {str(e)[:100]}",
                "error": str(e),
            }

    def _fetch_etf_data(self, etf_code: str, days: int = 1000) -> Optional[pd.DataFrame]:
        """获取ETF日线数据（默认请求约5.5年，足够覆盖大部分ETF的完整上市历史）"""
        from core.multi_source_fetcher import fetch_stock_data
        from datetime import datetime, timedelta

        end_date = datetime.now().strftime('%Y-%m-%d')
        # days * 2 将 trading days 扩展为日历天数，确保覆盖足够历史
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y-%m-%d')

        try:
            df = fetch_stock_data(etf_code, start_date, end_date)
            if df is not None and len(df) >= 60:
                return df
        except Exception as e:
            self.log_error(f"获取ETF数据失败 {etf_code}: {e}")

        # Fallback: try akshare
        try:
            pure_code = etf_code.split(".")[0]
            df = ak.fund_etf_hist_sina(symbol=pure_code)
            if df is not None and len(df) >= 60:
                col_map = {}
                for col in df.columns:
                    col_lower = col.lower().strip()
                    if col_lower in ("date", "日期"):
                        col_map[col] = "date"
                    elif col_lower in ("open", "开盘"):
                        col_map[col] = "open"
                    elif col_lower in ("high", "最高"):
                        col_map[col] = "high"
                    elif col_lower in ("low", "最低"):
                        col_map[col] = "low"
                    elif col_lower in ("close", "收盘"):
                        col_map[col] = "close"
                    elif "vol" in col_lower or "成交" in col:
                        col_map[col] = "volume"
                df = df.rename(columns=col_map)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df.tail(days)
        except Exception as e:
            self.log_error(f"akshare获取ETF数据也失败 {etf_code}: {e}")

        return None

    def _fetch_weekly_data(self, stock_code: str, years: int = 8) -> Optional[pd.DataFrame]:
        """获取长周期周线数据（用于大浪级别判断）

        周线数据可在400条内覆盖8年行情，足以识别大浪结构。
        优先使用baostock（支持周线频率，仅A股），港股和其他市场回退到日线重采样。
        """
        from datetime import datetime, timedelta

        # Determine market type and whether baostock supports it
        parts = stock_code.split(".")
        market = parts[1].lower() if len(parts) == 2 else ""
        baostock_ok = market in ("sh", "sz", "ssa", "sse")

        # Try baostock for native weekly data (A-shares only)
        if baostock_ok:
            try:
                import baostock as bs
                lg = bs.login()

                pure_code = parts[0]
                if market in ("sh", "ssa"):
                    bs_code = f"sh.{pure_code}"
                else:
                    bs_code = f"sz.{pure_code}"

                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=years*365)).strftime('%Y-%m-%d')

                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="w",
                    adjustflag="2"  # 前复权
                )
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                bs.logout()

                if data:
                    df = pd.DataFrame(data, columns=["date", "open", "high", "low", "close", "volume"])
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)

                    if len(df) >= 30:
                        return df
            except Exception as e:
                self.log_error(f"baostock获取周线数据失败 {stock_code}: {e}")

        # Fallback: fetch long-term daily data and resample to weekly
        # This handles HK stocks, US stocks, and any baostock failures
        try:
            from core.multi_source_fetcher import fetch_stock_data
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=years*365)).strftime('%Y-%m-%d')
            df = fetch_stock_data(stock_code, start_date, end_date)
            if df is not None and len(df) >= 120:
                return self._resample_to_weekly(df)
        except Exception as e:
            self.log_error(f"回退方案获取周线数据也失败 {stock_code}: {e}")

        return None

    def _detect_major_wave(self, df_weekly_long: pd.DataFrame, current_price: float) -> Dict[str, Any]:
        """基于长周期周线数据判断大浪级别结构
        
        返回大浪级别信息，用于修正日线浪型标注。
        关键判断：当前处于大浪的哪个阶段（5浪下跌中？5浪完成后ABC反弹？上升5浪中？）
        
        使用较粗的zigzag阈值(0.25)确保只捕捉主要转折点。
        """
        if df_weekly_long is None or len(df_weekly_long) < 30:
            return {"major_wave_available": False}

        try:
            # Use coarse threshold for major wave structure
            # Try 0.25 first (fewer pivots = clearer major structure)
            pivots = self._detect_zigzag(df_weekly_long, threshold=0.25)
            if not pivots or len(pivots) < 3:
                # Fallback to 0.15
                pivots = self._detect_zigzag(df_weekly_long, threshold=0.15)
            
            if not pivots or len(pivots) < 3:
                return {"major_wave_available": False}

            # Label the major wave structure
            wave_result = self._label_waves(pivots, current_price)
            
            position = wave_result.get("position", "")
            wave_points = wave_result.get("wave_points", [])
            direction = wave_result.get("detail", {}).get("direction", "")
            description = wave_result.get("description", "")
            
            # Check key indicators for major wave classification
            # 1. Does the wave labeling include a completed 5-wave impulse?
            impulse_labels = [wp.get("label", "") for wp in wave_points]
            has_w5_bottom = any("浪5底" in label for label in impulse_labels)
            has_w5_top = any("浪5顶" in label for label in impulse_labels)
            has_abc = any("调整" in label for label in impulse_labels)
            
            has_5wave_down = has_w5_bottom and direction == "下跌"
            has_5wave_up = has_w5_top and direction == "上升"
            in_abc_after_5wave = has_5wave_down and has_abc
            
            # 2. Simple price-based check: if current price has bounced significantly
            # from a major low, and the overall decline is very large (>50%),
            # we may be in a post-decline correction even if wave labeling
            # hasn't identified all 5 waves

            # Find abs_high and abs_low from raw pivots (NOT from wave labels,
            # because "起点" is the low point in an uptrend and the high point in a downtrend)
            high_pivots = [p for p in pivots if p["type"] == "HIGH"]
            low_pivots = [p for p in pivots if p["type"] == "LOW"]
            abs_high = max(high_pivots, key=lambda p: p["price"]) if high_pivots else None
            abs_low = min(low_pivots, key=lambda p: p["price"]) if low_pivots else None
            
            # IMPORTANT: Find the TRUE all-time low in the data (not just labeled wave5 bottom)
            # The wave labeling may mark an intermediate low as "浪5底" when the actual
            # lowest point comes later (e.g., in an extended decline after ABC)
            all_time_low = None
            low_pivots_all = [p for p in pivots if p["type"] == "LOW"]
            if low_pivots_all:
                all_time_low = min(low_pivots_all, key=lambda p: p["price"])
            # Also check if abs_low from wave points is truly the lowest
            if all_time_low and abs_low and all_time_low["price"] < abs_low["price"]:
                abs_low = all_time_low
            
            # If there's a massive decline (>50%) and current price has bounced >20% from low,
            # and the wave position is "下跌推动浪第N浪" with N >= 3,
            # then we may be in an ABC correction after the decline
            # CRITICAL: Only valid when abs_high comes BEFORE abs_low (actual downtrend).
            # If abs_low came first (uptrend), this is measuring the rise, not a decline.
            price_based_correction = False
            if abs_high and abs_low:
                abs_high_date = abs_high.get("date", "")
                abs_low_date = abs_low.get("date", "")
                is_downtrend_sequence = (
                    abs_high_date and abs_low_date and abs_high_date < abs_low_date
                )
                total_decline = abs_high["price"] - abs_low["price"]
                if total_decline > 0 and abs_low["price"] > 0 and is_downtrend_sequence:
                    decline_pct = total_decline / abs_high["price"]
                    bounce_from_low = (current_price - abs_low["price"]) / abs_low["price"]

                    if decline_pct > 0.50 and bounce_from_low > 0.15:
                        # Large decline + significant bounce = likely post-decline ABC
                        price_based_correction = True

            return {
                "major_wave_available": True,
                "major_position": position,
                "major_direction": direction,
                "major_description": description,
                "major_wave_points": wave_points,
                "has_5wave_down": has_5wave_down,
                "has_5wave_up": has_5wave_up,
                "in_abc_after_5wave": in_abc_after_5wave,
                "price_based_correction": price_based_correction,
                "abs_high": abs_high,
                "abs_low": abs_low,
                "major_upside_prob": wave_result.get("upside_prob", 50),
            }
        except Exception as e:
            self.log_error(f"大浪级别判断失败: {e}")
            return {"major_wave_available": False}

    def _cross_check_daily_extremes(
        self, df_daily: pd.DataFrame, major_wave: Dict[str, Any]
    ) -> None:
        """用日线数据校验大浪级别的极限价格。

        周线数据可能滞后于日线（如周五收盘后的周一新低/新高），
        若日线极限超出周线zigzag的abs_low/abs_high，更新大浪拐点。
        """
        if df_daily is None or df_daily.empty:
            return

        daily_low = float(df_daily['low'].min())
        daily_high = float(df_daily['high'].max())
        daily_low_date = df_daily.loc[df_daily['low'].idxmin(), 'date']
        daily_high_date = df_daily.loc[df_daily['high'].idxmax(), 'date']

        abs_low = major_wave.get('abs_low')
        abs_high = major_wave.get('abs_high')
        wave_points = major_wave.get('major_wave_points', [])

        # Check if daily low extends below abs_low (weekly zigzag missed a lower low)
        if abs_low and daily_low < abs_low['price']:
            abs_low['price'] = daily_low
            abs_low['date'] = str(daily_low_date)[:10]
            # Extend the last 浪5底 to the daily low
            for wp in reversed(wave_points):
                if '浪5底' in wp.get('label', ''):
                    wp['price'] = daily_low
                    wp['date'] = str(daily_low_date)[:10]
                    break

        # Check if daily high extends above abs_high (weekly zigzag missed a higher high)
        if abs_high and daily_high > abs_high['price']:
            abs_high['price'] = daily_high
            abs_high['date'] = str(daily_high_date)[:10]
            for wp in reversed(wave_points):
                if '浪5顶' in wp.get('label', ''):
                    wp['price'] = daily_high
                    wp['date'] = str(daily_high_date)[:10]
                    break

    def _apply_major_wave_correction(self, wave_analysis: Dict[str, Any], major_wave: Dict[str, Any]) -> Dict[str, Any]:
        """用大浪级别结论修正日线浪型标注
        
        核心逻辑：
        - 如果大浪级别显示已完成5浪下跌，但日线标注为"下跌推动浪第3浪"，
          说明日线只看到了大浪5底后的局部走势，应修正为ABC调整浪。
        - 如果大浪级别显示上升5浪中，日线不应标注为下跌推动浪。
        - 大浪级别的ABC位置应覆盖日线级别的推动浪标注。
        """
        if not major_wave.get("major_wave_available"):
            return wave_analysis

        position = wave_analysis.get("position", "")
        detail = wave_analysis.get("detail", {})
        description = wave_analysis.get("description", "")
        upside_prob = wave_analysis.get("upside_prob", 50)
        
        major_position = major_wave.get("major_position", "")
        major_direction = major_wave.get("major_direction", "")
        major_description = major_wave.get("major_description", "")
        major_upside_prob = major_wave.get("major_upside_prob", 50)
        has_5wave_down = major_wave.get("has_5wave_down", False)
        has_5wave_up = major_wave.get("has_5wave_up", False)
        in_abc_after_5wave = major_wave.get("in_abc_after_5wave", False)
        major_wave_points = major_wave.get("major_wave_points", [])

        corrections = []
        needs_correction = False

        price_based_correction = major_wave.get("price_based_correction", False)
        abs_high = major_wave.get("abs_high")
        abs_low = major_wave.get("abs_low")

        # Case 0: Price-based major wave correction
        # When there's a massive decline (>50%) and significant bounce (>20% from low),
        # but wave labeling hasn't identified all 5 waves (e.g., only labeled 3 waves so far),
        # the daily "downtrend impulse" is likely a fragment of a larger ABC correction.
        if price_based_correction and abs_high and abs_low and ("推动浪第" in position and "下跌" in position):
            total_decline = abs_high["price"] - abs_low["price"]
            bounce_from_low = (detail.get("current_price", 0) or 0) - abs_low["price"]
            bounce_pct = bounce_from_low / abs_low["price"] * 100 if abs_low["price"] > 0 else 0
            decline_pct = total_decline / abs_high["price"] * 100
            
            # Determine ABC phase based on bounce magnitude
            if bounce_pct > 50:
                new_position = "下跌5浪后C浪反弹"
                new_prob = 45
            elif bounce_pct > 30:
                new_position = "下跌5浪后A浪反弹"
                new_prob = 50
            else:
                new_position = "下跌5浪后A浪反弹末端"
                new_prob = 40
            
            wave_analysis["position"] = new_position
            wave_analysis["upside_prob"] = new_prob
            wave_analysis["description"] = (
                f"大浪级别: {abs_high['price']:.3f}({abs_high.get('date', '?')})→"
                f"{abs_low['price']:.3f}({abs_low.get('date', '?')})下跌{decline_pct:.0f}%，"
                f"当前反弹{bounce_pct:.0f}%，处于ABC调整阶段；"
                f"日线局部: {description}"
            )
            detail["major_wave_context"] = (
                f"大级别下跌{decline_pct:.0f}%后反弹{bounce_pct:.0f}%，"
                f"日线'下跌推动浪'实为ABC调整浪的一部分"
            )
            detail["major_position"] = major_position
            detail["major_description"] = major_description
            needs_correction = True

        # Case 1: Major wave shows completed 5-wave downtrend, but daily labels it as new downtrend impulse
        # This means daily is only seeing a fragment of the post-5-wave ABC correction
        # Skip if Case 0 (price-based correction) already applied
        if not needs_correction and has_5wave_down and ("推动浪第" in position and "下跌" in position):
            # Daily labeled it as a new downtrend impulse (e.g., "下跌推动浪第3浪")
            # But major wave shows the entire 5-wave downtrend is complete
            # → This should be relabeled as ABC correction after the 5-wave downtrend
            
            # Find the major wave's last impulse point (大浪5底) and current ABC phase
            if in_abc_after_5wave:
                # Major wave already has ABC labels - use them
                wave_analysis["position"] = major_position
                wave_analysis["upside_prob"] = major_upside_prob
                wave_analysis["description"] = (
                    f"大浪级别: {major_description}；"
                    f"日线级别: {description}（大浪5底后的局部走势）"
                )
                detail["major_wave_context"] = f"大浪5浪下跌已完成，当前处于ABC调整阶段"
                detail["major_position"] = major_position
                detail["major_description"] = major_description
            else:
                # Major wave shows completed 5-wave, but ABC hasn't been labeled yet
                # Find major wave 5 bottom
                w5_bottom = None
                w5_top = None
                for wp in major_wave_points:
                    if "浪5底" in wp.get("label", ""):
                        w5_bottom = wp
                    if "浪5顶" in wp.get("label", ""):
                        w5_top = wp
                
                if w5_bottom:
                    # Determine ABC phase from daily data relative to major wave 5 bottom
                    current_price = detail.get("current_price", 0)
                    if current_price > 0 and w5_bottom["price"] > 0:
                        bounce_pct = (current_price - w5_bottom["price"]) / w5_bottom["price"] * 100
                        
                        # Find the highest point after major wave 5 bottom in weekly data
                        # to determine A浪顶
                        w5_idx = None
                        for i, wp in enumerate(major_wave_points):
                            if wp is w5_bottom:
                                w5_idx = i
                                break
                        
                        a_wave_top = None
                        if w5_idx is not None and w5_idx + 1 < len(major_wave_points):
                            next_pt = major_wave_points[w5_idx + 1]
                            if next_pt["type"] == "HIGH" and next_pt["price"] > w5_bottom["price"]:
                                a_wave_top = next_pt
                        
                        if a_wave_top:
                            if current_price >= a_wave_top["price"]:
                                new_position = "下跌5浪后C浪反弹"
                                new_prob = 45
                            elif bounce_pct > 30:
                                new_position = "下跌5浪后A浪反弹"
                                new_prob = 50
                            else:
                                new_position = "下跌5浪后A浪反弹末端"
                                new_prob = 40
                        else:
                            new_position = "下跌5浪后A浪反弹"
                            new_prob = 50
                        
                        wave_analysis["position"] = new_position
                        wave_analysis["upside_prob"] = new_prob
                        wave_analysis["description"] = (
                            f"大浪级别: 5浪下跌完成(大浪5底{w5_bottom['price']:.3f})，"
                            f"当前处于ABC调整阶段；"
                            f"日线局部: {description}"
                        )
                        detail["major_wave_context"] = f"大浪5浪下跌已完成(浪5底{w5_bottom['price']:.3f})，当前处于ABC调整"
                        detail["major_position"] = major_position
                        detail["major_description"] = major_description

            needs_correction = True

        # Case 2: Major wave shows ABC after 5-wave downtrend, daily shows similar ABC
        # This is consistent - just add context
        elif in_abc_after_5wave and "5浪后" in position:
            detail["major_wave_context"] = f"大浪级别确认: {major_position}"
            detail["major_position"] = major_position
            detail["major_description"] = major_description

        # Case 3: Major wave shows uptrend, daily shows downtrend impulse
        # Daily may be seeing a correction within a larger uptrend
        elif major_direction == "上升" and "下跌" in position and "推动浪" in position:
            # Find the major uptrend wave point closest to current price
            detail["major_wave_context"] = f"大浪级别为上升趋势({major_position})，日线下跌可能为大浪调整"
            detail["major_position"] = major_position
            detail["major_description"] = major_description

        # Case 4: Daily shows early uptrend impulse, but major wave shows near cycle top
        # The "浪1顶" on daily may actually be a major cycle top (浪3顶/浪5顶 of larger degree)
        # This happens when MAX_ZIGZAG_BARS truncates the view, making a long uptrend fragment
        # appear as a brand new impulse wave 1
        is_uptrend_impulse = (
            ("推动浪第" in position and "下跌" not in position)
            or "新一轮上升" in position
        )
        if not needs_correction and is_uptrend_impulse and abs_high is not None:
            daily_wave_points = wave_analysis.get("wave_points", [])
            w1_top = None
            origin = None
            for wp in daily_wave_points:
                label = wp.get("label", "")
                if "浪1顶" in label:
                    w1_top = wp
                if "起点" in label or "前高" in label:
                    if origin is None or "起点" in label:
                        origin = wp  # prefer "起点" over "前高" if both present

            if w1_top and origin:
                w1_top_price = w1_top.get("price", 0)
                origin_price = origin.get("price", 0)
                abs_high_price = abs_high.get("price", 0)

                # Check if daily "浪1顶" is close to the major cycle high
                if abs_high_price > 0 and w1_top_price > 0:
                    distance_from_high = abs(w1_top_price - abs_high_price) / abs_high_price
                    w1_gain_pct = (w1_top_price - origin_price) / origin_price if origin_price > 0 else 0

                    # Heuristic: if daily浪1顶 is within 15% of major abs_high AND
                    # the 浪1 gain is >50% (unusually large for a wave 1),
                    # then 浪1顶 is likely a major cycle top, not a true wave 1
                    near_major_high = distance_from_high < 0.15
                    oversized_w1 = w1_gain_pct > 0.50

                    # Also check: has_5wave_up means major wave labels show completed 5-wave
                    if has_5wave_up and (near_major_high or oversized_w1):
                        # Daily "浪1顶" aligns with major cycle top → relabel
                        current_price_val = detail.get("current_price", 0) or 0
                        retrace_from_high = (
                            (abs_high_price - current_price_val) / abs_high_price
                            if abs_high_price > 0 and current_price_val > 0 else 0
                        )

                        if retrace_from_high > 0.30:
                            new_position = "大浪5浪上升后ABC调整"
                            new_prob = 35
                            phase_desc = f"已从高点回撤{retrace_from_high*100:.0f}%，处于ABC调整中"
                        elif retrace_from_high > 0.15:
                            new_position = "大浪5浪上升末期(顶部确认)"
                            new_prob = 30
                            phase_desc = f"从高点回撤{retrace_from_high*100:.0f}%，可能进入大级别调整"
                        else:
                            new_position = "大浪5浪上升末期"
                            new_prob = 40
                            phase_desc = "接近大级别顶部区域"

                        wave_analysis["position"] = new_position
                        wave_analysis["upside_prob"] = new_prob
                        wave_analysis["description"] = (
                            f"大浪级别: {major_position}（{major_description}）；"
                            f"日线标注的'浪1顶'{w1_top_price:.3f}实为大浪顶部区域"
                            f"（距大浪高点{abs_high_price:.3f}仅{distance_from_high*100:.0f}%），"
                            f"{phase_desc}；"
                            f"日线局部: {description}"
                        )
                        detail["major_wave_context"] = (
                            f"大浪5浪上升已完成，日线'浪1顶'({w1_top_price:.3f})实际接近大浪顶部"
                            f"({abs_high_price:.3f})，日线上升推动浪为大浪5浪末端或ABC反弹"
                        )
                        detail["major_position"] = major_position
                        detail["major_description"] = major_description
                        needs_correction = True

                    elif not has_5wave_up and oversized_w1 and near_major_high:
                        # Even without explicit 5-wave labeling, the oversized wave 1
                        # near a major high suggests this is a late-cycle move.
                        # If the signal is very strong (浪1顶 = all-time high, gain > 50%),
                        # relabel the position even without has_5wave_up.
                        current_price_val = detail.get("current_price", 0) or 0
                        retrace_from_high = (
                            (abs_high_price - current_price_val) / abs_high_price
                            if abs_high_price > 0 and current_price_val > 0 else 0
                        )
                        very_strong_signal = (
                            distance_from_high < 0.03 and w1_gain_pct > 0.50
                        )

                        if very_strong_signal:
                            # Daily "浪1顶" IS the all-time high → must be a cycle top
                            if retrace_from_high > 0.30:
                                new_position = "大浪顶部后ABC调整"
                                new_prob = 30
                            elif retrace_from_high > 0.15:
                                new_position = "大浪顶部后A浪下跌"
                                new_prob = 25
                            else:
                                new_position = "大浪上升末期(顶部确认)"
                                new_prob = 35

                            wave_analysis["position"] = new_position
                            wave_analysis["upside_prob"] = new_prob
                            wave_analysis["description"] = (
                                f"大浪级别: {major_position}（{major_description}）；"
                                f"日线标注的'浪1顶'{w1_top_price:.3f}即为近8年最高点"
                                f"({abs_high_price:.3f}, {abs_high.get('date', '?')})，"
                                f"涨幅{w1_gain_pct*100:.0f}%异常偏大，"
                                f"当前从高点回撤{retrace_from_high*100:.0f}%，"
                                f"日线'上升推动浪'实为大浪末端或ABC反弹；"
                                f"日线局部: {description}"
                            )
                            detail["major_wave_context"] = (
                                f"日线'浪1顶'({w1_top_price:.3f})即为近8年最高点，"
                                f"涨幅{w1_gain_pct*100:.0f}%不可能为浪1，"
                                f"应为大浪5浪顶或B浪顶，当前{new_position}"
                            )
                            detail["major_position"] = major_position
                            detail["major_description"] = major_description
                            needs_correction = True
                        else:
                            detail["major_wave_context"] = (
                                f"大浪上升趋势中，日线'浪1顶'({w1_top_price:.3f})接近大浪高点"
                                f"({abs_high_price:.3f})，涨幅{w1_gain_pct*100:.0f}%异常偏大，"
                                f"疑为大浪第5浪末端而非新上升浪的起点"
                            )
                            detail["major_position"] = major_position
                            detail["major_description"] = major_description

        if needs_correction or detail.get("major_wave_context"):
            # Re-score based on corrected position
            score, score_rationale = self._wave_score(wave_analysis)
            wave_analysis["detail"]["major_wave_score"] = score
        
        return wave_analysis

    def _calculate_wave_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算波浪判断所需的技术指标"""
        df = df.copy()

        # 均线
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()

        # RSI (14日)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.001)
        df['RSI'] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_hist'] = df['MACD'] - df['MACD_signal']

        # 价格相对于近期高低点的位置
        df['high_60'] = df['high'].rolling(window=60).max()
        df['low_60'] = df['low'].rolling(window=60).min()
        df['price_position'] = (
            (df['close'] - df['low_60']) /
            (df['high_60'] - df['low_60']).replace(0, 1)
        )

        return df

    def _detect_zigzag(self, df: pd.DataFrame, threshold: float = 0.08) -> List[Dict[str, Any]]:
        """
        Zigzag转折点检测：识别价格的重要高点和低点

        Args:
            df: 日线数据（需含 date, high, low, close 列）
            threshold: 反转阈值（8%表示只有8%以上的反向波动才算转折点）

        Returns:
            转折点列表，每项包含 date, price, type('HIGH'/'LOW'), idx
        """
        if len(df) < 30:
            return []

        highs = df['high'].values.astype(float)
        lows = df['low'].values.astype(float)
        dates = df['date'].values if 'date' in df.columns else df.index.values

        pivots = []  # list of (idx, price, type)
        direction = None  # 'up' or 'down'
        last_pivot_idx = 0
        last_pivot_price = float(df.iloc[0]['close'])

        for i in range(1, len(df)):
            h = highs[i]
            l = lows[i]

            if direction is None:
                if h > last_pivot_price:
                    direction = 'up'
                    last_pivot_price = h
                    last_pivot_idx = i
                elif l < last_pivot_price:
                    direction = 'down'
                    last_pivot_price = l
                    last_pivot_idx = i
            elif direction == 'up':
                if h > last_pivot_price:
                    last_pivot_price = h
                    last_pivot_idx = i
                elif l < last_pivot_price * (1 - threshold):
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 'HIGH'})
                    direction = 'down'
                    last_pivot_price = l
                    last_pivot_idx = i
            elif direction == 'down':
                if l < last_pivot_price:
                    last_pivot_price = l
                    last_pivot_idx = i
                elif h > last_pivot_price * (1 + threshold):
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 'LOW'})
                    direction = 'up'
                    last_pivot_price = h
                    last_pivot_idx = i

        # Add the last pivot
        if direction == 'up':
            pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 'HIGH'})
        elif direction == 'down':
            pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 'LOW'})

        # Enrich with dates
        for p in pivots:
            p['date'] = str(dates[p['idx']])[:10]

        return pivots

    def _label_waves(self, pivots: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
        """
        根据Zigzag转折点标注Elliott波浪结构

        自动判断趋势方向：
        - 上升趋势：从最低点开始，标注上升推动浪1-5 + ABC调整
        - 下降趋势：从最高点开始，标注下跌推动浪1-5 + ABC反弹

        Args:
            pivots: Zigzag转折点列表
            current_price: 当前收盘价

        Returns:
            波浪结构信息，包含各浪高点/低点、当前位置、上涨概率等
        """
        if len(pivots) < 3:
            return {
                "position": "数据不足",
                "upside_prob": 50,
                "wave_points": [],
                "description": "转折点不足，无法标注波浪",
                "detail": {"signal": "数据不足"},
            }

        # Find extreme points
        lows = [p for p in pivots if p['type'] == 'LOW']
        highs = [p for p in pivots if p['type'] == 'HIGH']

        if not lows or not highs:
            return {
                "position": "数据不足",
                "upside_prob": 50,
                "wave_points": [],
                "description": "无法识别高低点",
                "detail": {"signal": "数据不足"},
            }

        abs_low = min(lows, key=lambda p: p['price'])
        abs_high = max(highs, key=lambda p: p['price'])

        # === Determine trend direction ===
        # Heuristic: chronological order of extremes + current price position
        # If the highest point comes after the lowest point, likely uptrend
        # If the lowest point comes after the highest point, likely downtrend
        high_after_low = abs_high['idx'] > abs_low['idx']
        low_after_high = abs_low['idx'] > abs_high['idx']

        # Price position relative to extremes
        price_range = abs_high['price'] - abs_low['price']
        if price_range > 0:
            price_pct_from_low = (current_price - abs_low['price']) / price_range
        else:
            price_pct_from_low = 0.5

        # Determine direction: chronological order is the primary signal
        # (which extreme came last defines the current trend direction)
        # Price position is secondary confirmation
        if low_after_high and not high_after_low:
            # Low came after high → downtrend (unless price has bounced back above midpoint)
            is_downtrend = price_pct_from_low < 0.6
        elif high_after_low and not low_after_high:
            # High came after low → uptrend (unless price has fallen below midpoint)
            is_downtrend = price_pct_from_low < 0.3
        else:
            # Ambiguous: use price position
            is_downtrend = price_pct_from_low < 0.4

        # Try both directions and pick the one with fewer Elliott iron rule violations.
        # This handles cases like Alibaba where the historical low forms a valid
        # 5-wave uptrend even though the high preceded it chronologically.
        downward = self._label_downward_waves(pivots, current_price, abs_high, abs_low)
        upward = self._label_upward_waves(pivots, current_price, abs_low, abs_high)

        # P0 #1 + P1 #4: Also try ABC correction labeling (four-way comparison)
        abc_up = self._label_abc_correction(pivots, current_price, abs_low, abs_high, prior_trend='down')
        abc_down = self._label_abc_correction(pivots, current_price, abs_low, abs_high, prior_trend='up')

        # Calculate prior trend magnitudes
        prior_decline_pct = 0.0
        prior_rise_pct = 0.0
        if abs_high['idx'] < abs_low['idx']:
            prior_decline_pct = (abs_high['price'] - abs_low['price']) / abs_high['price'] * 100
        elif abs_low['idx'] < abs_high['idx']:
            prior_rise_pct = (abs_high['price'] - abs_low['price']) / abs_low['price'] * 100

        from .elliott_rules import (
            extract_wave_structure,
            check_R1_wave2_retracement,
            check_R2_wave3_not_shortest,
            check_R3_wave4_no_overlap_wave1,
        )
        def _count_violations(result):
            wps = result.get("wave_points", [])
            if len(wps) < 3:
                return 999
            try:
                ws = extract_wave_structure(result)
            except Exception:
                return 998
            v = 0
            if check_R1_wave2_retracement(ws): v += 1
            if check_R2_wave3_not_shortest(ws): v += 1
            if check_R3_wave4_no_overlap_wave1(ws): v += 1

            # Also check 新 and 续 impulse groups.
            # The standard rule checker only validates the main 浪1-5 labels,
            # missing violations in later impulse structures.
            for prefix, is_downtrend in [('新', None), ('续', None)]:
                prefixed = [wp for wp in wps
                           if wp.get('label', '').startswith(prefix)]
                if len(prefixed) < 3:
                    continue
                # Detect direction from label pattern
                if is_downtrend is None:
                    has_w1d = any(prefix + '1底' in wp['label'] for wp in prefixed)
                    has_w1t = any(prefix + '1顶' in wp['label'] for wp in prefixed)
                    is_downtrend = has_w1d and not has_w1t
                if is_downtrend:
                    origin = next((wp for wp in wps
                                  if wp['label'] in (prefix + '起点', '新C浪顶')),
                                  None)
                    w1b = next((wp for wp in prefixed
                               if prefix + '1底' in wp['label']), None)
                    w2t = next((wp for wp in prefixed
                               if prefix + '2顶' in wp['label']), None)
                    w4t = next((wp for wp in prefixed
                               if prefix + '4顶' in wp['label']), None)
                    # R1: wave 2 top must not exceed origin
                    if origin and w2t and w2t['price'] > origin['price']:
                        v += 1
                    # R3: wave 4 top must not exceed wave 1 bottom
                    if w1b and w4t and w4t['price'] > w1b['price']:
                        v += 1
                else:
                    origin = next((wp for wp in wps
                                  if wp['label'] in (prefix + '起点', '新C浪底')),
                                  None)
                    w1t = next((wp for wp in prefixed
                               if prefix + '1顶' in wp['label']), None)
                    w2b = next((wp for wp in prefixed
                               if prefix + '2底' in wp['label']), None)
                    w4b = next((wp for wp in prefixed
                               if prefix + '4底' in wp['label']), None)
                    # R1: wave 2 bottom must not go below origin
                    if origin and w2b and w2b['price'] < origin['price']:
                        v += 1
                    # R3: wave 4 bottom must not go below wave 1 top
                    if w1t and w4b and w4b['price'] < w1t['price']:
                        v += 1
            return v

        dn_v = _count_violations(downward)
        up_v = _count_violations(upward)

        # P0 #1 + P1 #4: Enhanced selection logic with ABC option
        # 1. Check if ABC is more appropriate (prior major decline + deep retracement)
        abc_preferred = False
        abc_result = None

        # P1 #4: 前期大级别下跌/上涨时默认偏ABC
        if prior_decline_pct > 30 and current_price < abs_high['price'] * 0.85:
            abc_preferred = True
            abc_result = abc_up

        # P0 #1: Check wave 2 retracement depth - if >80%, ABC is more likely
        w1_top = next((wp for wp in upward.get('wave_points', [])
                       if wp.get('label') == '浪1顶'), None)
        if w1_top and prior_decline_pct > 30:
            w2_bottom = next((wp for wp in upward.get('wave_points', [])
                             if wp.get('label') == '浪2底'), None)
            if w2_bottom:
                w1_range = w1_top['price'] - abs_low['price']
                if w1_range > 0:
                    w2_retrace_pct = (w1_top['price'] - w2_bottom['price']) / w1_range
                    if w2_retrace_pct > 0.8:
                        abc_preferred = True
                        abc_result = abc_up

        # 2. Count violations and consider ABC options
        # ABC gets a "confidence-adjusted violations" score:
        # lower confidence = effectively more violations
        abc_up_conf = abc_up.get('confidence', 1.0)
        abc_down_conf = abc_down.get('confidence', 1.0)
        if abc_up_conf > 0:
            abc_up_v = 3 + int((1.0 - abc_up_conf) * 5)  # lower confidence → higher effective violations
        else:
            abc_up_v = 999
        if abc_down_conf > 0:
            abc_down_v = 3 + int((1.0 - abc_down_conf) * 5)
        else:
            abc_down_v = 999

        # 3. Select best option
        all_options = [
            (up_v, 'upward', upward),
            (dn_v, 'downward', downward),
            (abc_up_v, 'abc_up', abc_up),
            (abc_down_v, 'abc_down', abc_down),
        ]
        all_options.sort(key=lambda x: x[0])

        best_v, best_name, best_result = all_options[0]

        # 4. When push浪 has ≥2 violations and ABC is viable, prefer ABC
        if not abc_preferred:
            if best_name in ('upward', 'downward') and best_v >= 2:
                abc_opt = next((opt for opt in all_options if opt[1].startswith('abc')), None)
                if abc_opt and abc_opt[0] <= 5:
                    best_v, best_name, best_result = abc_opt
                    abc_preferred = True

        # 5. If ABC is explicitly preferred and not far worse, use ABC
        if abc_preferred and not best_name.startswith('abc'):
            abc_opt = next((opt for opt in all_options if opt[1].startswith('abc')), None)
            if abc_opt and abc_opt[0] <= best_v + 2:
                best_result = abc_opt[2]

        return best_result

    def _label_upward_waves(self, pivots: List[Dict[str, Any]], current_price: float,
                             abs_low: Dict, abs_high: Dict) -> Dict[str, Any]:
        """
        上升趋势浪型标注：从最低点开始，标注上升推动浪1-5 + ABC调整浪

        Args:
            pivots: Zigzag转折点列表
            current_price: 当前收盘价
            abs_low: 全局最低点
            abs_high: 全局最高点
        """
        uptrend_pivots = [p for p in pivots if p['idx'] >= abs_low['idx']]

        # Identify the prior structure (decline from highest HIGH before abs_low)
        prior_pivots = [p for p in pivots if p['idx'] < abs_low['idx']]
        prior_structure = ""
        prior_high = None
        if prior_pivots:
            prior_highs = [p for p in prior_pivots if p['type'] == 'HIGH']
            if prior_highs:
                prior_high = max(prior_highs, key=lambda p: p['price'])
                decline_pct = (abs_low['price'] - prior_high['price']) / prior_high['price'] * 100
                n_prior_swings = len(prior_pivots)
                if n_prior_swings >= 4:
                    prior_structure = f"前段: {prior_high['price']:.3f}({prior_high['date']})→{abs_low['price']:.3f}({abs_low['date']})，下跌{decline_pct:.1f}%，{n_prior_swings}段转折"
                elif n_prior_swings >= 2:
                    prior_structure = f"前段: {prior_high['price']:.3f}({prior_high['date']})→{abs_low['price']:.3f}({abs_low['date']})，下跌{decline_pct:.1f}%"
                else:
                    prior_structure = f"前段高点: {prior_high['price']:.3f}({prior_high['date']})→低点{abs_low['price']:.3f}，下跌{decline_pct:.1f}%"
                if decline_pct < -20:
                    if n_prior_swings >= 5:
                        prior_structure += "（疑似5浪下跌）"
                    elif n_prior_swings >= 3:
                        prior_structure += "（ABC调整）"
                    else:
                        prior_structure += "（单段下跌）"

        if len(uptrend_pivots) < 2:
            return {
                "position": "数据不足",
                "upside_prob": 50,
                "wave_points": [],
                "description": "上升段转折点不足",
                "detail": {"signal": "数据不足"},
            }

        # Label waves: alternating HIGH/LOW from the LOW origin
        wave_points = []
        # Add prior high as context point
        if prior_high:
            wave_points.append({
                'label': '前高',
                'date': prior_high['date'],
                'price': prior_high['price'],
                'type': 'HIGH',
            })

        impulse_phase = True
        wave_num = 1
        correction_label = 'A'
        large_single_wave_count = 0  # P1 #2: track waves >50% without sub-division

        for i, p in enumerate(uptrend_pivots):
            if i == 0:
                wave_points.append({
                    'label': '起点',
                    'date': p['date'],
                    'price': p['price'],
                    'type': 'LOW',
                })
                continue

            if impulse_phase:
                if p['type'] == 'HIGH':
                    # P1 #2: 检测大涨幅单浪——超过50%涨幅的单一浪可能内含子浪
                    wave_gain_pct = 0
                    origin_price = uptrend_pivots[0]['price']
                    if origin_price > 0:
                        wave_gain_pct = (p['price'] - origin_price) / origin_price * 100
                    wp_entry = {
                        'label': f'浪{wave_num}顶',
                        'date': p['date'],
                        'price': p['price'],
                        'type': 'HIGH',
                    }
                    if wave_num in (1, 5) and wave_gain_pct > 50:
                        wp_entry['detail'] = {
                            'sub_wave_warning': True,
                            'gain_pct': round(wave_gain_pct, 1),
                            'note': f'单浪涨幅{wave_gain_pct:.1f}%>50%，可能内含子浪未细分',
                        }
                        large_single_wave_count += 1
                    wave_points.append(wp_entry)
                elif p['type'] == 'LOW':
                    correction_num = wave_num + 1
                    if correction_num <= 4:
                        # P1 #3: 检测浪2深度回撤（>85%可能是B浪而非浪2）
                        deep_retrace_flag = False
                        if correction_num == 2:  # 浪2底
                            w1_top_price = next((wp['price'] for wp in wave_points
                                                 if wp.get('label') == '浪1顶'), None)
                            if w1_top_price:
                                origin_price = uptrend_pivots[0]['price']
                                w1_range = w1_top_price - origin_price
                                if w1_range > 0:
                                    retrace_pct = (w1_top_price - p['price']) / w1_range
                                    if retrace_pct > 0.85:
                                        wave_points.append({
                                            'label': '浪2底(疑似B浪)',
                                            'date': p['date'],
                                            'price': p['price'],
                                            'type': 'LOW',
                                            'detail': {
                                                'retrace_pct': round(retrace_pct, 3),
                                                'warning': '深回撤>85%，可能是B浪而非浪2',
                                            },
                                        })
                                        deep_retrace_flag = True
                        if not deep_retrace_flag:
                            wave_points.append({
                                'label': f'浪{correction_num}底',
                                'date': p['date'],
                                'price': p['price'],
                                'type': 'LOW',
                            })
                        wave_num += 2
                    else:
                        wave_points.append({
                            'label': '调整A浪底',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'LOW',
                        })
                        impulse_phase = False
                        correction_label = 'B'
            else:
                # Post-impulse ABC correction (decline after uptrend)
                # CRITICAL: B浪顶 must NOT go above 浪5顶.
                # If a HIGH is found above 浪5顶, the advance has extended —
                # extend 浪5顶 to this new high and restart ABC.
                if p['type'] == 'HIGH':
                    w5_top = next(
                        (wp for wp in wave_points if wp.get('label') == '浪5顶'), None
                    )
                    # Only extend 浪5顶 if the correction hasn't completed yet
                    # (correction_label <= 'C'). If ABC is already done, a high
                    # above 浪5顶 is a NEW post-correction impulse, not an extension.
                    if w5_top and p['price'] > w5_top['price'] and correction_label <= 'C':
                        # B浪顶 broke above 浪5顶 → advance extended
                        # Remove the entire prior correction (浪5顶 + all 调整* labels) and extend
                        wave_points = [
                            wp for wp in wave_points
                            if not wp.get('label', '').startswith('调整') and wp.get('label') != '浪5顶'
                        ]
                        wave_points.append({
                            'label': '浪5顶',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'HIGH',
                        })
                        impulse_phase = True
                        wave_num = 5
                    else:
                        if correction_label <= 'C':
                            wave_points.append({
                                'label': f'调整{correction_label}浪顶',
                                'date': p['date'],
                                'price': p['price'],
                                'type': 'HIGH',
                            })
                            correction_label = chr(ord(correction_label) + 1)
                        # 不重新开始推动浪——保持在修正阶段。
                        # 如果后续高点突破浪5顶，上面的扩展逻辑会自动延长浪5顶。
                elif p['type'] == 'LOW':
                    if correction_label <= 'C':
                        wave_points.append({
                            'label': f'调整{correction_label}浪底',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'LOW',
                        })
                        correction_label = chr(ord(correction_label) + 1)
                    # 同理：不重新开始推动浪，保持在修正阶段

        # ============================================================
        # Post-ABC Classification: compound correction vs new impulse
        # After ABC completes (correction_label > 'C'), remaining pivots
        # are NOT discarded — they signal either:
        #   1. 联合调整浪 (W-X-Y): adjustment continues, no trend reversal
        #   2. 新推动浪: C endpoint becomes new wave-1 origin
        # Decision uses B浪顶突破 + retracement depth + pivot count
        # ============================================================
        if not impulse_phase and correction_label > 'C':
            # Find C浪底 in wave_points
            c_idx = next((i for i, wp in enumerate(wave_points)
                         if '调整C浪底' in wp.get('label', '')), None)

            if c_idx is not None:
                c_point = wave_points[c_idx]
                # Locate C浪底 in uptrend_pivots to find remaining pivots after it
                c_pivot_idx = None
                for pi, p in enumerate(uptrend_pivots):
                    if (p['type'] == 'LOW' and
                            abs(p['price'] - c_point['price']) / max(abs(c_point['price']), 0.01) < 0.01):
                        c_pivot_idx = pi
                        break

                if c_pivot_idx is not None and c_pivot_idx + 1 < len(uptrend_pivots):
                    remaining = uptrend_pivots[c_pivot_idx + 1:]

                    if remaining:
                        # --- Classify: compound correction or new impulse? ---
                        b_top = next((wp for wp in wave_points
                                     if '调整B浪顶' in wp.get('label', '')), None)
                        w4_bottom = next((wp for wp in wave_points
                                         if wp.get('label') == '浪4底'), None)
                        first_pivot = remaining[0]  # always HIGH (zigzag alternation)

                        signals = {}

                        # Signal 1: Break above B浪顶 → strong new impulse
                        if b_top and first_pivot['price'] > b_top['price']:
                            signals['break_b_top'] = 3.0
                        # Signal 2: Break above 浪4底 → moderate new impulse
                        if w4_bottom and first_pivot['price'] > w4_bottom['price']:
                            signals['break_w4'] = 1.5
                        # Signal 3: Stays below B浪顶 → compound correction
                        if b_top and first_pivot['price'] <= b_top['price']:
                            signals['below_b_top'] = 2.0
                        # Signal 4: Retracement depth from C底 toward B顶
                        if c_point and b_top:
                            abc_range = b_top['price'] - c_point['price']
                            if abc_range > 0:
                                bounce_pct = (first_pivot['price'] - c_point['price']) / abc_range
                                if bounce_pct > 0.618:
                                    signals['strong_bounce'] = 2.0
                                elif bounce_pct > 0.382:
                                    signals['moderate_bounce'] = 1.0
                                else:
                                    signals['weak_bounce'] = 1.0
                        # Signal 5: Multiple alternating pivots → compound pattern
                        if len(remaining) >= 3:
                            signals['multi_pivot'] = 1.5

                        compound_score = sum(w for k, w in signals.items()
                                            if k in ('below_b_top', 'weak_bounce', 'multi_pivot'))
                        impulse_score = sum(w for k, w in signals.items()
                                           if k in ('break_b_top', 'break_w4', 'strong_bounce'))

                        if impulse_score >= 3.5:
                            classification = 'new_impulse'
                        elif compound_score >= 2.0:
                            classification = 'compound'
                        elif impulse_score > 0:
                            classification = 'new_impulse'
                        else:
                            classification = 'compound'

                        # --- Label remaining pivots ---
                        if classification == 'new_impulse':
                            # C浪底 is the origin of new impulse; restart labeling
                            wave_points.append({
                                'label': '新起点',
                                'date': c_point['date'],
                                'price': c_point['price'],
                                'type': 'LOW',
                            })
                            new_impulse_phase = True
                            new_wave_num = 1
                            new_correction_label = 'A'

                            for p in remaining:
                                if new_impulse_phase is True:
                                    if p['type'] == 'HIGH':
                                        wave_points.append({
                                            'label': f'新{new_wave_num}顶',
                                            'date': p['date'],
                                            'price': p['price'],
                                            'type': 'HIGH',
                                        })
                                    elif p['type'] == 'LOW':
                                        corr_num = new_wave_num + 1
                                        if corr_num <= 4:
                                            wave_points.append({
                                                'label': f'新{corr_num}底',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'LOW',
                                            })
                                            new_wave_num += 2
                                        else:
                                            wave_points.append({
                                                'label': '新A浪底',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'LOW',
                                            })
                                            new_impulse_phase = False
                                            new_correction_label = 'B'
                                elif new_impulse_phase is False:
                                    if new_correction_label <= 'C':
                                        if p['type'] == 'HIGH':
                                            wave_points.append({
                                                'label': f'新{new_correction_label}浪顶',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'HIGH',
                                            })
                                            new_correction_label = chr(ord(new_correction_label) + 1)
                                        elif p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': f'新{new_correction_label}浪底',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'LOW',
                                            })
                                            new_correction_label = chr(ord(new_correction_label) + 1)
                                    else:
                                        # ABC completed → start continuation impulse
                                        new_impulse_phase = 'impulse2'
                                        new_wnum = 1
                                        if p['type'] == 'HIGH':
                                            wave_points.append({
                                                'label': f'续{new_wnum}顶',
                                                'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                            })
                                        elif p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': '续2底',
                                                'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                            })
                                            new_wnum += 2
                                elif new_impulse_phase == 'impulse2':
                                    if p['type'] == 'HIGH':
                                        wave_points.append({
                                            'label': f'续{new_wnum}顶',
                                            'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                        })
                                    elif p['type'] == 'LOW':
                                        cn = new_wnum + 1
                                        if cn <= 4:
                                            wave_points.append({
                                                'label': f'续{cn}底',
                                                'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                            })
                                            new_wnum += 2
                                        else:
                                            wave_points.append({
                                                'label': '续A浪底',
                                                'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                            })
                                            new_impulse_phase = 'correction2'
                                            new_clabel = 'B'
                                elif new_impulse_phase == 'correction2':
                                    if new_clabel <= 'C':
                                        if p['type'] == 'HIGH':
                                            wave_points.append({
                                                'label': f'续{new_clabel}浪顶',
                                                'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                            })
                                            new_clabel = chr(ord(new_clabel) + 1)
                                        elif p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': f'续{new_clabel}浪底',
                                                'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                            })
                                            new_clabel = chr(ord(new_clabel) + 1)

                            # Elliott iron-rule validation for new impulse
                            new_origin = next((wp for wp in wave_points
                                              if wp['label'] == '新起点'), None)
                            new_w2 = next((wp for wp in wave_points
                                          if '新2底' in wp.get('label', '')), None)
                            new_w1 = next((wp for wp in wave_points
                                          if '新1顶' in wp.get('label', '')), None)
                            new_w4 = next((wp for wp in wave_points
                                          if '新4底' in wp.get('label', '')), None)
                            r1_violation = False
                            if new_origin and new_w2 and new_w2['price'] < new_origin['price']:
                                # R1 violation: wave 2 breaks below origin →
                                # fundamentally invalid impulse, must revert
                                r1_violation = True
                            if new_w1 and new_w4 and new_w4['price'] < new_w1['price']:
                                # R3 violation: wave 4 overlaps wave 1 territory.
                                # Keep all labels — the iron rule counter already
                                # tracks this for bidirectional comparison.
                                pass
                            if r1_violation:
                                # Remove all 新-prefixed labels
                                wave_points = [wp for wp in wave_points
                                              if not wp.get('label', '').startswith('新')]
                                classification = 'compound'

                        if classification == 'compound':
                            # Label compound correction W-X-Y(-Z) after ABC
                            # After C浪底(LOW) in uptrend: HIGH=X浪顶, LOW=Y浪底, HIGH=Y浪顶, LOW=Z浪底
                            wxy_labels = [
                                ('X', 'HIGH', '顶'),   # connector bounce
                                ('Y', 'LOW', '底'),   # second decline
                                ('Y', 'HIGH', '顶'),   # Y internal bounce
                                ('Z', 'LOW', '底'),   # triple zigzag (rare)
                            ]
                            consumed = 0
                            for i, p in enumerate(remaining):
                                if i >= len(wxy_labels):
                                    break
                                char, expected_type, pos = wxy_labels[i]
                                if p['type'] == expected_type:
                                    wave_points.append({
                                        'label': f'联合调整{char}浪{pos}',
                                        'date': p['date'],
                                        'price': p['price'],
                                        'type': p['type'],
                                    })
                                    consumed = i + 1

                            # Handle excess remaining pivots after W-X-Y-Z
                            excess = remaining[consumed:]
                            if excess:
                                # Check for trend reversal signal:
                                # After Z浪底(LOW), a new uptrend may be starting
                                # Signal: HIGH breaks above the last compound high (Y浪顶 or Z predecessor)
                                z_point = next((wp for wp in reversed(wave_points)
                                               if 'Z' in wp.get('label', '')), None)
                                y_top = next((wp for wp in wave_points
                                             if '联合调整Y浪顶' in wp.get('label', '')), None)
                                ref_high = z_point or y_top

                                reversal_signals = {}
                                for p in excess:
                                    if p['type'] == 'HIGH' and ref_high and p['price'] > ref_high['price']:
                                        reversal_signals['break_compound_high'] = 3.0

                                compound_score = sum(w for k, w in reversal_signals.items()
                                                    if 'break' not in k) if reversal_signals else 1.0
                                reversal_score = sum(w for k, w in reversal_signals.items()
                                                     if 'break' in k) if reversal_signals else 0.0

                                if reversal_score >= 2.0 and len(excess) >= 2:
                                    # Trend reversal: label as new UPTREND impulse
                                    # First excess pivot after Z浪底(LOW) is HIGH → 新1顶
                                    new_phase = True
                                    new_wnum = 1
                                    new_clabel = 'A'
                                    for p in excess:
                                        if new_phase is True:
                                            if p['type'] == 'HIGH':
                                                wave_points.append({
                                                    'label': f'新{new_wnum}顶',
                                                    'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                })
                                            elif p['type'] == 'LOW':
                                                cn = new_wnum + 1
                                                if cn <= 4:
                                                    wave_points.append({
                                                        'label': f'新{cn}底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_wnum += 2
                                                else:
                                                    wave_points.append({
                                                        'label': '新A浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_phase = False
                                                    new_clabel = 'B'
                                        elif new_phase is False:
                                            if new_clabel <= 'C':
                                                if p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'新{new_clabel}浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                                elif p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'新{new_clabel}浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                            else:
                                                # Correction completed → restart impulse for remaining pivots
                                                new_phase = 'impulse2'
                                                new_wnum = 1
                                                new_clabel = 'A'
                                                if p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'续{new_wnum}顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                elif p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': '续2底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_wnum += 2
                                        elif new_phase == 'impulse2':
                                            if p['type'] == 'HIGH':
                                                wave_points.append({
                                                    'label': f'续{new_wnum}顶',
                                                    'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                })
                                            elif p['type'] == 'LOW':
                                                cn = new_wnum + 1
                                                if cn <= 4:
                                                    wave_points.append({
                                                        'label': f'续{cn}底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_wnum += 2
                                                else:
                                                    wave_points.append({
                                                        'label': '续A浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_phase = 'correction2'
                                                    new_clabel = 'B'
                                        elif new_phase == 'correction2':
                                            if new_clabel <= 'C':
                                                if p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'续{new_clabel}浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                                elif p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'续{new_clabel}浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                    # Validate new uptrend: R1+R3
                                    nw2 = next((wp for wp in wave_points if '新2底' in wp.get('label', '')), None)
                                    nw1t = next((wp for wp in wave_points if '新1顶' in wp.get('label', '')), None)
                                    nw4 = next((wp for wp in wave_points if '新4底' in wp.get('label', '')), None)
                                    # R1: 新2底 > 新1起点 (first LOW before 新1顶 or the preceding Z)
                                    prev_low = next((wp for wp in reversed(wave_points)
                                                    if wp['type'] == 'LOW' and '新' not in wp.get('label', '')), None)
                                    if prev_low and nw2 and nw2['price'] < prev_low['price']:
                                        # R1 violation: structure fundamentally invalid → remove all 新 labels
                                        wave_points = [wp for wp in wave_points
                                                      if not wp.get('label', '').startswith('新')]
                                    elif nw1t and nw4 and nw4['price'] < nw1t['price']:
                                        # R3 violation: wave 4 overlaps wave 1.
                                        # Keep all labels — the iron rule counter already
                                        # tracks this violation for bidirectional comparison.
                                        pass
                                    # Validate 续 labels: if R2 fails (wave 3 shorter than wave 1),
                                    # the structure is not an impulse → convert to compound correction
                                    xu_labels = [wp for wp in wave_points if wp.get('label', '').startswith('续')]
                                    if xu_labels:
                                        xu_origin = next((wp for wp in wave_points if '新C浪底' in wp.get('label', '')), None)
                                        xu_w1t = next((wp for wp in xu_labels if '续1顶' in wp.get('label', '')), None)
                                        xu_w2b = next((wp for wp in xu_labels if '续2底' in wp.get('label', '')), None)
                                        xu_w3t = next((wp for wp in xu_labels if '续3顶' in wp.get('label', '')), None)
                                        r2_fail = False
                                        if xu_w1t and xu_w2b and xu_w3t and xu_origin:
                                            w1_len = abs(xu_w1t['price'] - xu_origin['price'])
                                            w3_len = abs(xu_w3t['price'] - xu_w2b['price'])
                                            if w3_len < w1_len:
                                                r2_fail = True
                                        # Also check: wave 3 top must exceed wave 1 top (uptrend)
                                        if xu_w1t and xu_w3t and xu_w3t['price'] < xu_w1t['price']:
                                            r2_fail = True
                                        if r2_fail:
                                            # Before converting to compound correction,
                                            # check: if the compound HIGH exceeds the
                                            # prior impulse top, the uptrend continued —
                                            # extend the prior top instead of converting.
                                            prior_impulse_top = next((wp for wp in wave_points if '新5顶' in wp.get('label', '')), None)
                                            if not prior_impulse_top:
                                                prior_impulse_top = next((wp for wp in wave_points if '新3顶' in wp.get('label', '')), None)
                                            if not prior_impulse_top:
                                                prior_impulse_top = next((wp for wp in wave_points if '浪5顶' in wp.get('label', '')), None)
                                            if xu_w1t and prior_impulse_top and xu_w1t['price'] > prior_impulse_top['price']:
                                                # 续1顶 exceeds prior impulse top —
                                                # the uptrend extended. Don't convert.
                                                pass
                                            else:
                                                # Convert 续 impulse to compound correction labels
                                                label_map = {}
                                                for wp in xu_labels:
                                                    lbl = wp['label']
                                                    if '续1顶' in lbl:
                                                        label_map[lbl] = '联合调整续X浪顶'
                                                    elif '续2底' in lbl:
                                                        label_map[lbl] = '联合调整续X浪底'
                                                    elif '续3顶' in lbl:
                                                        label_map[lbl] = '联合调整续Y浪顶'
                                                    elif '续4底' in lbl:
                                                        label_map[lbl] = '联合调整续Y浪底'
                                                    elif '续A' in lbl and '顶' in lbl:
                                                        label_map[lbl] = '联合调整续Z浪顶'
                                                    elif '续A' in lbl and '底' in lbl:
                                                        label_map[lbl] = '联合调整续Z浪底'
                                                    elif '续B' in lbl:
                                                        label_map[lbl] = '联合调整续XX浪' + ('顶' if '顶' in lbl else '底')
                                                    elif '续C' in lbl:
                                                        label_map[lbl] = '联合调整续XY浪' + ('顶' if '顶' in lbl else '底')
                                                for wp in xu_labels:
                                                    if wp['label'] in label_map:
                                                        wp['label'] = label_map[wp['label']]
                                else:
                                    # No reversal: extend compound pattern XXXY-XXZ etc
                                    extended_labels = [
                                        ('XX', 'HIGH', '顶'), ('XX', 'LOW', '底'),
                                        ('XY', 'HIGH', '顶'), ('XY', 'LOW', '底'),
                                        ('XZ', 'HIGH', '顶'), ('XZ', 'LOW', '底'),
                                    ]
                                    for i, p in enumerate(excess):
                                        if i >= len(extended_labels):
                                            break
                                        char, expected_type, pos = extended_labels[i]
                                        if p['type'] == expected_type:
                                            wave_points.append({
                                                'label': f'联合调整{char}浪{pos}',
                                                'date': p['date'], 'price': p['price'], 'type': p['type'],
                                            })

        # ============================================================
        # Elliott Rule Validation: Wave 3 cannot be the shortest
        # impulse wave (of waves 1, 3, 5). If Wave 3 is shorter
        # than Wave 1, the zigzag detected too many minor pivots.
        # Correct interpretation: the rise to the highest point is
        # an extended Wave 1, and the deep drop is Wave 2.
        # Result: keep 浪1顶(extend to highest), then 浪2底(lowest)
        # ============================================================
        w1_top = [wp for wp in wave_points if wp.get('label') == '浪1顶']
        w2_bottom = [wp for wp in wave_points if wp.get('label') == '浪2底']
        w3_top = [wp for wp in wave_points if wp.get('label') == '浪3顶']
        start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), None)

        if w1_top and w2_bottom and w3_top and start_pt:
            w1_gain = (w1_top[0]['price'] - start_pt['price']) / start_pt['price']
            w3_gain = (w3_top[0]['price'] - w2_bottom[0]['price']) / w2_bottom[0]['price']
            if w3_gain < w1_gain:
                # Wave 3 is shorter than Wave 1 — violates Elliott rule.
                # Usually this means zigzag over-detected minor pivots, so we
                # merge into extended Wave 1 + Wave 2.
                # BUT: if the structure has already been extended with compound
                # corrections (联合调整) or new impulses (新), the initial
                # "浪1-浪5" were really a correction pattern (ABC/WXY) mislabeled
                # as impulse. Don't collapse — keep the extended structure.
                extended_labels = [wp for wp in wave_points if wp.get('label', '').startswith('新') or '联合调整' in wp.get('label', '') or wp.get('label', '').startswith('续')]
                if not extended_labels:
                    all_after_start = wave_points[1:]  # Skip 起点
                    high_points = [wp for wp in all_after_start if wp['type'] == 'HIGH']
                    if high_points:
                        # Extended Wave 1 top = highest HIGH point
                        w1_extended = max(high_points, key=lambda wp: wp['price'])
                        w1_ext_idx = wave_points.index(w1_extended)
                        # Wave 2 bottom = lowest LOW point after extended Wave 1
                        after_w1 = wave_points[w1_ext_idx + 1:]
                        low_after_w1 = [wp for wp in after_w1 if wp['type'] == 'LOW']
                        w2_new = min(low_after_w1, key=lambda wp: wp['price']) if low_after_w1 else None
                        # Build new wave_points: 起点 → 浪1顶 → 浪2底
                        start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                        new_wave_points = [start_pt]
                        new_wave_points.append({
                            'label': '浪1顶',
                            'date': w1_extended['date'],
                            'price': w1_extended['price'],
                            'type': 'HIGH',
                        })
                        if w2_new:
                            new_wave_points.append({
                                'label': '浪2底',
                                'date': w2_new['date'],
                                'price': w2_new['price'],
                                'type': 'LOW',
                            })
                        wave_points = new_wave_points

        # ============================================================
        # B-Wave Overextension Validation: If the labeled B-wave top
        # exceeds the labeled Wave-5 top by >10%, the zigzag misidentified
        # internal Wave-5 subdivisions as separate waves (浪5顶- A浪底- B浪顶).
        # Correct: the highest point after 浪4底 IS the real 浪5顶,
        # and everything after it is an ABC correction.
        # ============================================================
        w5_pt = [wp for wp in wave_points if wp.get('label') == '浪5顶']
        b_top_pt = [wp for wp in wave_points if wp.get('label') == '调整B浪顶']
        if w5_pt and b_top_pt:
            w5_price = w5_pt[0]['price']
            b_price = b_top_pt[0]['price']
            if b_price > w5_price * 1.10:
                # B-wave is >10% above Wave-5 - relabel
                w4_pt = [wp for wp in wave_points if wp.get('label') == '浪4底']
                w4_idx_in_wp = wave_points.index(w4_pt[0]) if w4_pt else -1
                after_w4 = wave_points[w4_idx_in_wp + 1:] if w4_idx_in_wp >= 0 else wave_points
                affected = [wp for wp in after_w4 if wp['type'] == 'HIGH']
                real_w5 = max(affected, key=lambda wp: wp['price']) if affected else b_top_pt[0]

                # Rebuild: keep up to 浪4底, add real 浪5顶, then relabel remaining as ABC
                new_wave_points = wave_points[:w4_idx_in_wp + 1] if w4_idx_in_wp >= 0 else [wave_points[0]]
                new_wave_points.append({
                    'label': '浪5顶',
                    'date': real_w5['date'],
                    'price': real_w5['price'],
                    'type': 'HIGH',
                })
                # Find the real 浪5顶 in original wave_points to get remaining points
                real_w5_orig_idx = None
                for i, wp in enumerate(wave_points):
                    if wp.get('date') == real_w5['date'] and abs(wp.get('price', 0) - real_w5['price']) < 0.01:
                        real_w5_orig_idx = i
                        break
                if real_w5_orig_idx is not None:
                    remaining = wave_points[real_w5_orig_idx + 1:]
                    abc_labels = ['A', 'B', 'C']
                    abc_idx = 0
                    for wp in remaining:
                        if abc_idx >= len(abc_labels):
                            break
                        wp_type = wp['type']
                        if wp_type == 'LOW' and abc_idx == 0:
                            new_wave_points.append({
                                'label': f'调整{abc_labels[abc_idx]}浪底',
                                'date': wp['date'], 'price': wp['price'], 'type': 'LOW',
                            })
                            abc_idx += 1
                        elif wp_type == 'HIGH' and abc_idx == 1:
                            new_wave_points.append({
                                'label': f'调整{abc_labels[abc_idx]}浪顶',
                                'date': wp['date'], 'price': wp['price'], 'type': 'HIGH',
                            })
                            abc_idx += 1
                        elif wp_type == 'LOW' and abc_idx == 2:
                            new_wave_points.append({
                                'label': f'调整{abc_labels[abc_idx]}浪底',
                                'date': wp['date'], 'price': wp['price'], 'type': 'LOW',
                            })
                            abc_idx += 1
                wave_points = new_wave_points

        # Determine current wave position
        last_pivot = uptrend_pivots[-1]

        # Count impulse and correction waves
        impulse_waves = [wp for wp in wave_points if '浪' in wp.get('label', '') and '顶' in wp.get('label', '') and '调整' not in wp.get('label', '') and '联合' not in wp.get('label', '') and not wp.get('label', '').startswith('新')]
        correction_waves = [wp for wp in wave_points if '底' in wp.get('label', '') and '调整' not in wp.get('label', '') and '联合' not in wp.get('label', '') and not wp.get('label', '').startswith('新')]
        abc_points = [wp for wp in wave_points if '调整' in wp.get('label', '') and '联合' not in wp.get('label', '')]
        compound_points = [wp for wp in wave_points if '联合调整' in wp.get('label', '')]
        new_impulse_points = [wp for wp in wave_points if wp.get('label', '').startswith('新')]

        position = "未知"
        upside_prob = 50
        description = ""
        detail = {"direction": "上升"}

        n_impulse = len(impulse_waves)
        n_correction = len(correction_waves)
        in_abc = len(abc_points) > 0
        in_compound = len(compound_points) > 0
        has_new_impulse = len(new_impulse_points) > 0

        if has_new_impulse:
            # New impulse cycle detected after ABC completion
            new_tops = [wp for wp in new_impulse_points if '顶' in wp.get('label', '')]
            new_bottoms = [wp for wp in new_impulse_points if '底' in wp.get('label', '')]
            n_new_tops = len(new_tops)

            if n_new_tops >= 3:
                position = "新一轮推动浪第5浪"
                upside_prob = 35
                description = f"ABC调整结束后启动新一轮上升推动浪，已运行至第5浪"
            elif n_new_tops == 2:
                position = "新一轮推动浪第3浪"
                upside_prob = 70
                description = f"新一轮推动浪进行中：新1顶{new_tops[0]['price']:.3f}"
            elif n_new_tops == 1:
                w1_new = new_tops[0]
                if new_bottoms:
                    position = "新一轮推动浪第3浪"
                    upside_prob = 75
                    description = f"新推动浪浪2完成后进入浪3，当前{current_price:.3f}"
                else:
                    position = "新一轮推动浪第1浪"
                    upside_prob = 55
                    description = f"ABC调整结束，新推动浪第1浪：{w1_new['price']:.3f}"
            else:
                position = "新一轮推动浪启动"
                upside_prob = 55
                description = "ABC调整结束，新一轮推动浪启动中"

        elif in_compound:
            # Compound correction (W-X-Y) after ABC
            last_comp = compound_points[-1]
            clabel = last_comp['label']

            if 'X浪顶' in clabel:
                if current_price > last_comp['price']:
                    position = "联合调整浪X浪"
                    upside_prob = 30
                    description = f"ABC调整结束后进入联合调整，X浪反弹进行中{current_price:.3f}"
                else:
                    position = "联合调整浪X浪末端"
                    upside_prob = 25
                    description = f"联合调整X浪反弹后回落至{current_price:.3f}，Y浪下跌风险"
            elif 'Y浪底' in clabel:
                position = "联合调整浪Y浪末端"
                upside_prob = 40
                description = f"联合调整Y浪底{last_comp['price']:.3f}，调整可能结束"
            elif 'Y浪顶' in clabel:
                position = "联合调整浪Y浪"
                upside_prob = 30
                description = f"联合调整Y浪反弹中{current_price:.3f}"
            elif 'Z' in clabel:
                position = "联合调整浪Z浪末端"
                upside_prob = 45
                description = f"三重联合调整接近尾声，当前{current_price:.3f}"
            else:
                position = "联合调整浪"
                upside_prob = 30
                description = "ABC后进入联合调整阶段"

        elif in_abc:
            last_abc = abc_points[-1]
            abc_label = last_abc['label']

            if 'A浪底' in abc_label:
                if current_price > last_abc['price']:
                    position = "调整浪B浪反弹"
                    upside_prob = 35
                    pct = (current_price - last_abc['price']) / last_abc['price'] * 100
                    description = f"5浪完成，A浪底{last_abc['price']:.3f}→B浪反弹{current_price:.3f}({pct:+.1f}%)，注意C浪下跌"
                else:
                    position = "调整浪A浪"
                    upside_prob = 25
                    pct = (current_price - last_abc['price']) / last_abc['price'] * 100
                    description = f"5浪完成，A浪下跌中{pct:+.1f}%"
            elif 'B浪顶' in abc_label:
                position = "调整浪B浪反弹"
                upside_prob = 30
                description = f"5浪完成，B浪反弹高点{last_abc['price']:.3f}，C浪下跌风险大"
            elif 'C浪底' in abc_label:
                # C浪调整已到底，检查是否突破B浪顶
                b_top = [wp for wp in abc_points if 'B浪顶' in wp.get('label', '')]
                # Check if new impulse waves have started after C浪底
                c_bottom = last_abc
                post_c_impulse = [wp for wp in impulse_waves
                                  if wp.get('date', '') > c_bottom.get('date', '')]
                if b_top and current_price > b_top[0]['price']:
                    # 突破B浪顶 → 新一轮上升推动浪开始
                    position = "新一轮上升推动浪第1浪"
                    upside_prob = 70
                    pct_above = (current_price - b_top[0]['price']) / b_top[0]['price'] * 100
                    description = f"ABC调整结束，价格突破B浪顶{b_top[0]['price']:.3f}至{current_price:.3f}({pct_above:+.1f}%)，新一轮上升推动浪启动"
                elif post_c_impulse and current_price > c_bottom['price']:
                    # New impulse waves already labeled after C浪底 → new cycle confirmed
                    position = "新一轮上升推动浪第1浪"
                    upside_prob = 65
                    pct = (current_price - c_bottom['price']) / c_bottom['price'] * 100
                    description = f"ABC调整完成(C浪底{c_bottom['price']:.3f})，新一轮推动浪启动，当前{current_price:.3f}(+{pct:.1f}%)"
                elif current_price > last_abc['price']:
                    position = "调整浪C浪末端"
                    upside_prob = 50
                    pct = (current_price - last_abc['price']) / last_abc['price'] * 100
                    description = f"5浪完成，C浪底{last_abc['price']:.3f}，可能开始新推动浪"
                else:
                    position = "调整浪C浪"
                    upside_prob = 25
                    description = f"5浪完成，C浪下跌中{current_price:.3f}"
            else:
                position = "调整浪"
                upside_prob = 30
                description = "5浪结构完成，调整浪中"

            w5_top = impulse_waves[-1] if impulse_waves else None
            if w5_top:
                a_bottom = [wp for wp in abc_points if 'A浪底' in wp.get('label', '')]
                if a_bottom:
                    detail["5浪高点"] = f"{w5_top['price']:.3f}({w5_top['date']})"
                    detail["A浪低点"] = f"{a_bottom[0]['price']:.3f}({a_bottom[0]['date']})"

        elif n_impulse >= 3 and n_correction >= 2:
            position = "推动浪第5浪"
            upside_prob = 35
            w5 = impulse_waves[-1]
            pct = (current_price / w5['price'] - 1) * 100 if w5['price'] > 0 else 0
            description = f"浪5进行中: 顶{w5['price']:.3f}，当前{current_price:.3f}({pct:+.1f}%)，趋势末期"

        elif n_impulse >= 2 and n_correction >= 1:
            w3 = [wp for wp in impulse_waves if '浪3顶' in wp.get('label', '')]
            w4 = [wp for wp in correction_waves if '浪4底' in wp.get('label', '')]

            if w3 and w4:
                position = "推动浪第5浪"
                upside_prob = 35
                l4 = w4[0]
                pct = (current_price - l4['price']) / l4['price'] * 100
                description = f"浪5进行中: {l4['price']:.3f}→{current_price:.3f}({pct:+.1f}%)，趋势末期风险增加"
            elif w3 and not w4:
                position = "推动浪第4浪调整"
                upside_prob = 45
                h3 = w3[0]
                pct = (current_price - h3['price']) / h3['price'] * 100
                description = f"浪3顶{h3['price']:.3f}后回调，当前{current_price:.3f}({pct:+.1f}%)"
            else:
                position = "推动浪第3浪"
                upside_prob = 70
                description = "浪3上升中"

        elif n_impulse >= 2 and n_correction == 0:
            position = "推动浪第3浪"
            upside_prob = 70
            w1 = [wp for wp in impulse_waves if '浪1顶' in wp.get('label', '')]
            w3 = [wp for wp in impulse_waves if '浪3顶' in wp.get('label', '')]
            if w1 and w3:
                start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                description = f"浪1: {start['price']:.3f}→{w1[0]['price']:.3f}, 浪3上升中→{w3[0]['price']:.3f}"

        elif n_impulse == 1 and n_correction == 1:
            w2_low = [wp for wp in correction_waves if '浪2底' in wp.get('label', '')]
            w1_high = [wp for wp in impulse_waves if '浪1顶' in wp.get('label', '')]

            # === Sanity check: in uptrend, current price must be above Wave 2 bottom ===
            # If current_price < w2_low, the "Wave 2 bottom" is stale — the correction
            # continued past that point. Need to find the actual lowest LOW.
            if w2_low and current_price < w2_low[0]['price']:
                # Wave 2 bottom is stale — the correction continued past the labeled point.
                # Use uptrend_pivots (raw zigzag pivots) instead of wave_points
                # because wave_points only contains labeled pivots and may miss lower dips.
                w1_high_pt = w1_high[0] if w1_high else wave_points[1] if len(wave_points) > 1 else None
                if w1_high_pt:
                    # Find Wave 1 top's index in uptrend_pivots by matching date
                    w1_idx_in_pivots = None
                    for i, p in enumerate(uptrend_pivots):
                        if p.get('date') == w1_high_pt.get('date') and p['type'] == 'HIGH':
                            w1_idx_in_pivots = i
                            break
                    # If not found by date, try by price proximity
                    if w1_idx_in_pivots is None:
                        for i, p in enumerate(uptrend_pivots):
                            if p['type'] == 'HIGH' and abs(p['price'] - w1_high_pt['price']) / max(w1_high_pt['price'], 0.01) < 0.005:
                                w1_idx_in_pivots = i
                                break

                    # Find all LOW pivots after Wave 1 top in raw pivots
                    actual_w2_bottom = None
                    if w1_idx_in_pivots is not None:
                        after_w1 = uptrend_pivots[w1_idx_in_pivots + 1:]
                        low_after_w1 = [p for p in after_w1 if p['type'] == 'LOW']
                        if low_after_w1:
                            actual_w2_bottom = min(low_after_w1, key=lambda p: p['price'])

                    # Also check current_price as a potential low
                    if actual_w2_bottom is None or current_price < actual_w2_bottom['price']:
                        actual_w2_bottom = {'price': current_price, 'date': None, 'type': 'LOW'}

                    # Check if this is a trend reversal (decline > 61.8% of rise)
                    start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0] if wave_points else None)
                    if start_pt:
                        rise = w1_high_pt['price'] - start_pt['price']
                        if rise > 0:
                            decline_pct = (w1_high_pt['price'] - current_price) / rise
                            if decline_pct > 0.618:
                                # Strong decline → likely trend reversal
                                position = "新一轮下跌推动浪第1浪"
                                upside_prob = 35
                                description = f"上升后回调强劲，回撤{decline_pct*100:.0f}%超过61.8%，价格{current_price:.3f}跌破浪2底，趋势反转信号"
                                detail["reversal_detected"] = True
                            else:
                                # Update Wave 2 bottom to actual lowest point from raw pivots
                                for wp in wave_points:
                                    if wp.get('label') == '浪2底':
                                        wp['price'] = actual_w2_bottom['price']
                                        if actual_w2_bottom.get('date'):
                                            wp['date'] = actual_w2_bottom['date']

                                if current_price < actual_w2_bottom['price']:
                                    position = "推动浪第2浪调整"
                                    upside_prob = 35
                                    description = f"价格{current_price:.3f}持续低于浪2底{actual_w2_bottom['price']:.3f}，调整加深"
                                else:
                                    position = "推动浪第3浪"
                                    upside_prob = 75
                                    w1_pct = (w1_high_pt['price'] - start_pt['price']) / start_pt['price'] * 100
                                    w2_pct = (actual_w2_bottom['price'] - w1_high_pt['price']) / w1_high_pt['price'] * 100
                                    w3_pct = (current_price - actual_w2_bottom['price']) / actual_w2_bottom['price'] * 100
                                    description = (f"浪1: {start_pt['price']:.3f}→{w1_high_pt['price']:.3f}({w1_pct:+.1f}%), "
                                                 f"浪2: {w1_high_pt['price']:.3f}→{actual_w2_bottom['price']:.3f}({w2_pct:+.1f}%), "
                                                 f"浪3进行中: {actual_w2_bottom['price']:.3f}→{current_price:.3f}({w3_pct:+.1f}%)")
                                    detail = {"direction": "上升", "wave1_pct": round(w1_pct, 1), "wave2_pct": round(w2_pct, 1), "wave3_pct": round(w3_pct, 1)}
                        else:
                            position = "推动浪第2浪调整"
                            upside_prob = 40
                            description = f"浪1顶{w1_high_pt['price']:.3f}后回调持续中"
                    else:
                        position = "推动浪第2浪调整"
                        upside_prob = 40
                        description = f"浪1顶后回调持续中"
                else:
                    position = "推动浪第2浪调整"
                    upside_prob = 40
                    description = "回调中，价格低于浪2底"
            elif w2_low and last_pivot['type'] == 'LOW':
                position = "推动浪第3浪"
                upside_prob = 75
                start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                h1 = w1_high[0] if w1_high else wave_points[1]
                l2 = w2_low[0]
                w1_pct = (h1['price'] - start['price']) / start['price'] * 100
                w2_pct = (l2['price'] - h1['price']) / h1['price'] * 100
                w3_pct = (current_price - l2['price']) / l2['price'] * 100
                description = (f"浪1: {start['price']:.3f}→{h1['price']:.3f}({w1_pct:+.1f}%), "
                             f"浪2: {h1['price']:.3f}→{l2['price']:.3f}({w2_pct:+.1f}%), "
                             f"浪3进行中: {l2['price']:.3f}→{current_price:.3f}({w3_pct:+.1f}%)")
                detail = {"direction": "上升", "wave1_pct": round(w1_pct, 1), "wave2_pct": round(w2_pct, 1), "wave3_pct": round(w3_pct, 1)}
            elif w2_low and last_pivot['type'] == 'HIGH':
                position = "推动浪第3浪"
                upside_prob = 70
                description = "浪2底部确认后上升，浪3进行中"
            else:
                position = "推动浪第2浪调整"
                upside_prob = 45
                if w1_high:
                    description = f"浪1顶{w1_high[0]['price']:.3f}后回调中"

        elif n_impulse == 1 and n_correction == 0:
            position = "推动浪第1浪"
            upside_prob = 55
            start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
            w1 = impulse_waves[0]
            pct = (w1['price'] - start['price']) / start['price'] * 100
            # P1 #2: 大涨幅单浪可能内含子浪，降低可信度
            if pct > 50:
                description = f"浪1上升中: {start['price']:.3f}({start['date']})→{w1['price']:.3f}({w1['date']}), 涨幅{pct:+.1f}%（大涨幅单浪，可能内含子浪未细分）"
                upside_prob = 50
            else:
                description = f"浪1上升中: {start['price']:.3f}({start['date']})→{w1['price']:.3f}({w1['date']}), 涨幅{pct:+.1f}%"

        else:
            position = "推动浪第1浪"
            upside_prob = 55
            description = "从低点起步，推动浪第1浪进行中"

        # Price above last HIGH pivot → extending impulse wave
        if last_pivot['type'] == 'HIGH' and current_price > last_pivot['price']:
            if position in ("推动浪第5浪", "调整浪B浪反弹", "调整浪A浪"):
                if n_impulse >= 3 or in_abc:
                    position = "推动浪第3浪延伸"
                    upside_prob = 65
                    description = f"价格突破前高{last_pivot['price']:.3f}至{current_price:.3f}，可能进入新一轮上升"

        # Price below last LOW pivot → deepening correction
        if last_pivot['type'] == 'LOW' and current_price < last_pivot['price']:
            if position in ("推动浪第2浪调整", "推动浪第4浪调整"):
                upside_prob = max(20, upside_prob - 10)
                description += "，调整加深"

        # Build position reasoning — explain WHY this position, not alternatives
        reasoning = self._build_position_reasoning(
            direction="上升", position=position, n_impulse=n_impulse,
            n_correction=n_correction, in_abc=in_abc, wave_points=wave_points,
            abc_points=abc_points, current_price=current_price, last_pivot=last_pivot,
            compound_points=compound_points, new_impulse_points=new_impulse_points
        )
        detail["position_reasoning"] = reasoning

        # Add prior structure context
        if prior_structure:
            detail["prior_structure"] = prior_structure
            description = f"{prior_structure}；{description}"

        # P1 #2: 大涨幅单浪降低可信度
        confidence = 1.0
        if large_single_wave_count > 0:
            confidence *= 0.8  # 每个未细分的单浪降低20%可信度
            detail["large_single_wave_count"] = large_single_wave_count

        return {
            "position": position,
            "upside_prob": upside_prob,
            "wave_points": wave_points,
            "description": description,
            "detail": detail,
            "confidence": round(confidence, 2),
        }

    def _build_position_reasoning(self, direction: str, position: str, n_impulse: int,
                                   n_correction: int, in_abc: bool, wave_points: list,
                                   abc_points: list, current_price: float,
                                   last_pivot: dict,
                                   compound_points: list = None,
                                   new_impulse_points: list = None) -> str:
        """构建波浪位置判断依据，解释为什么是此位置而非其他位置"""
        reasons = []
        dir_label = "上升" if direction == "上升" else "下跌"
        in_compound = len(compound_points) > 0 if compound_points else False
        has_new_impulse = len(new_impulse_points) > 0 if new_impulse_points else False

        # 1. 趋势方向判断依据
        reasons.append(f"判定为{dir_label}趋势")

        # 2. 已识别的浪型数量
        reasons.append(f"识别到{n_impulse}个推动浪转折点、{n_correction}个调整浪转折点")

        # 3. 具体位置判断逻辑
        if has_new_impulse:
            new_labels = [wp.get('label', '') for wp in new_impulse_points]
            reasons.append(f"ABC调整结束后检测到新一轮推动浪（{', '.join(new_labels)}）")
            new_origin = next((wp for wp in new_impulse_points if wp['label'] == '新起点'), None)
            if new_origin:
                reasons.append(f"新推动浪起点{new_origin['price']:.3f}（原C浪终点），未跌破该点则新推动浪有效")
            # Elliott rule reference
            reasons.append("依据波浪铁律：新2浪不破新起点则确认推动浪归属，避免将调整浪误判为推动浪")

        elif in_compound:
            compound_labels = [wp.get('label', '') for wp in compound_points]
            reasons.append(f"ABC调整完成后进入联合调整阶段（{', '.join(compound_labels)}）")
            reasons.append("联合调整W-X-Y是Elliott波浪常见的复合修正形态，通常出现在趋势延续前的最后整理阶段")
            last_comp = compound_points[-1]
            if 'Y浪底' in last_comp.get('label', '') or 'Z浪底' in last_comp.get('label', ''):
                reasons.append(f"联合调整已触及{last_comp['label']}{last_comp['price']:.3f}，关注调整结束信号")

        elif in_abc:
            # ABC调整阶段
            abc_labels = [wp.get('label', '') for wp in abc_points]
            reasons.append(f"5浪推动结构已完成，进入ABC调整阶段（{', '.join(abc_labels)}）")

            if '趋势反转' in position:
                # 反转 vs 反弹的关键区分
                reasons.append("判定为趋势反转而非普通反弹，依据：")
                # Add specific reversal reasons from detail
                start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0] if wave_points else None)
                w5_pt = [wp for wp in wave_points if '浪5底' in wp.get('label', '')]
                if not w5_pt:
                    w5_pt = [wp for wp in wave_points if '浪4底' in wp.get('label', '')]
                w4_top_pt = [wp for wp in wave_points if '浪4顶' in wp.get('label', '')]
                if start_pt and w5_pt:
                    decline = start_pt['price'] - w5_pt[0]['price']
                    if decline > 0:
                        retracement = (current_price - w5_pt[0]['price']) / decline
                        reasons.append(f"回撤幅度{retracement*100:.0f}%{'（超过61.8%关键位）' if retracement > 0.618 else ''}")
                if w4_top_pt and current_price > w4_top_pt[0]['price']:
                    reasons.append(f"价格突破浪4顶{w4_top_pt[0]['price']:.3f}，这是反转的关键确认信号")
                a_top_pt = [wp for wp in abc_points if 'A浪顶' in wp.get('label', '')]
                if a_top_pt and current_price > a_top_pt[0]['price']:
                    reasons.append(f"价格突破A浪顶{a_top_pt[0]['price']:.3f}，反弹力度远超普通ABC修正")
                reasons.append("若仅为反弹，C浪通常不会突破A浪顶或浪4顶")
            elif '新一轮' in position:
                if direction == "上升":
                    b_top = [wp for wp in abc_points if 'B浪顶' in wp.get('label', '')]
                    if b_top:
                        reasons.append(f"价格{current_price:.3f}突破B浪顶{b_top[0]['price']:.3f}，确认ABC调整结束、新一轮上升推动浪启动（而非继续C浪下跌）")
                else:
                    b_bottom = [wp for wp in abc_points if 'B浪底' in wp.get('label', '')]
                    if b_bottom:
                        reasons.append(f"价格{current_price:.3f}跌破B浪底{b_bottom[0]['price']:.3f}，确认ABC反弹结束、新一轮下跌推动浪启动（而非继续C浪反弹）")
            elif 'C浪' in position and '末端' in position:
                reasons.append(f"当前处于C浪末端而非B浪，因为最后一个ABC转折点为{abc_points[-1].get('label', '')}，且价格已低于/高于该点")
                # Mention that if reversal signals appear, this could be a reversal
                w4_top_pt = [wp for wp in wave_points if '浪4顶' in wp.get('label', '')]
                if w4_top_pt and current_price < w4_top_pt[0]['price']:
                    reasons.append(f"价格未突破浪4顶{w4_top_pt[0]['price']:.3f}，暂判定为反弹而非反转")
            elif 'B浪' in position:
                reasons.append(f"当前处于B浪而非A浪延续，因为已确认A浪转折点，且价格反向运动")
            elif 'A浪' in position:
                reasons.append(f"当前处于A浪而非5浪延伸，因为5浪推动结构已完整（{n_impulse}个推动浪转折点），5浪后应为ABC调整")

        elif n_impulse >= 3 and n_correction >= 2:
            # 5浪已识别
            reasons.append(f"5浪推动结构已完整（3个推动浪+2个调整浪转折点），判定为第5浪而非3浪延伸")
            if direction == "上升":
                reasons.append(f"若为3浪延伸，则不应出现浪4底和浪5顶转折点")
            else:
                reasons.append(f"若为3浪延伸，则不应出现浪4顶和浪5底转折点")

        elif n_impulse >= 2 and n_correction >= 1:
            # 浪3或浪4或浪5
            if direction == "上升":
                w3 = [wp for wp in wave_points if '浪3顶' in wp.get('label', '')]
                w4 = [wp for wp in wave_points if '浪4底' in wp.get('label', '')]
            else:
                w3 = [wp for wp in wave_points if '浪3底' in wp.get('label', '')]
                w4 = [wp for wp in wave_points if '浪4顶' in wp.get('label', '')]

            if w3 and w4:
                reasons.append(f"浪3和浪4转折点均已确认，判定为第5浪而非3浪延伸")
            elif w3 and not w4:
                reasons.append(f"浪3转折点已确认但浪4未确认，判定为第4浪调整而非5浪开始")
                reasons.append(f"若为5浪，则应先出现浪4调整转折点")
            else:
                reasons.append(f"浪2后的下跌/上升已突破浪1极值，判定为浪3而非浪1延伸")

        elif n_impulse >= 2 and n_correction == 0:
            reasons.append(f"已确认2个推动浪转折点但无调整浪转折点，判定为浪3进行中")
            reasons.append(f"若为浪1延伸，则不应出现浪2调整和浪3推动转折点")

        elif n_impulse == 1 and n_correction == 1:
            if direction == "上升":
                w2_low = [wp for wp in wave_points if '浪2底' in wp.get('label', '')]
                if w2_low and last_pivot.get('type') == 'LOW':
                    reasons.append(f"浪2底已确认（{w2_low[0]['price']:.3f}），当前价格{current_price:.3f}高于浪2底，判定为浪3上升而非浪2调整延续")
                elif w2_low and last_pivot.get('type') == 'HIGH':
                    reasons.append(f"浪2底已确认后出现新高点，判定为浪3进行中")
                else:
                    reasons.append(f"浪1后出现回调，判定为浪2调整，浪1顶{[wp for wp in wave_points if '浪1顶' in wp.get('label', '')][0]['price']:.3f}" if [wp for wp in wave_points if '浪1顶' in wp.get('label', '')] else "浪1后出现回调，判定为浪2调整")
            else:
                w2_high = [wp for wp in wave_points if '浪2顶' in wp.get('label', '')]
                if w2_high and last_pivot.get('type') == 'HIGH':
                    reasons.append(f"浪2顶已确认（{w2_high[0]['price']:.3f}），当前价格{current_price:.3f}低于浪2顶，判定为浪3下跌而非浪2反弹延续")
                elif w2_high and last_pivot.get('type') == 'LOW':
                    reasons.append(f"浪2顶已确认后出现新低点，判定为浪3进行中")
                else:
                    reasons.append(f"浪1后出现反弹，判定为浪2反弹")

        elif n_impulse == 1 and n_correction == 0:
            reasons.append(f"仅识别到1个推动浪转折点，判定为浪1进行中")
            reasons.append(f"若为更高级别的浪3或浪5，应存在更多浪型转折点")

        else:
            reasons.append(f"浪型转折点不足，判定为趋势初期")

        # 4. 最后一个转折点的影响
        if last_pivot:
            pivot_desc = f"最近转折点为{last_pivot.get('label', last_pivot.get('type', ''))}({last_pivot['price']:.3f})"
            if current_price > last_pivot['price'] and last_pivot.get('type') == 'HIGH':
                pivot_desc += "，当前价格已突破该高点"
            elif current_price < last_pivot['price'] and last_pivot.get('type') == 'LOW':
                pivot_desc += "，当前价格已跌破该低点"
            reasons.append(pivot_desc)

        return "；".join(reasons)

    def _label_downward_waves(self, pivots: List[Dict[str, Any]], current_price: float,
                               abs_high: Dict, abs_low: Dict) -> Dict[str, Any]:
        """
        下降趋势浪型标注：从最高点开始，标注下跌推动浪1-5 + ABC反弹

        下跌推动浪结构：
        - 浪1底: 从高点下跌的第1段
        - 浪2顶: 第1段下跌后的反弹
        - 浪3底: 主跌段
        - 浪4顶: 主跌后的反弹
        - 浪5底: 下跌末段
        - 调整A浪顶~B浪底~C浪顶: 下跌完成后的反弹调整

        Args:
            pivots: Zigzag转折点列表
            current_price: 当前收盘价
            abs_high: 全局最高点
            abs_low: 全局最低点
        """
        downtrend_pivots = [p for p in pivots if p['idx'] >= abs_high['idx']]

        # Identify prior structure (rise before abs_high)
        prior_pivots = [p for p in pivots if p['idx'] < abs_high['idx']]
        prior_structure = ""
        prior_low = None
        if prior_pivots:
            prior_lows = [p for p in prior_pivots if p['type'] == 'LOW']
            if prior_lows:
                prior_low = min(prior_lows, key=lambda p: p['price'])
                rise_pct = (abs_high['price'] - prior_low['price']) / prior_low['price'] * 100
                n_prior_swings = len(prior_pivots)
                if n_prior_swings >= 4:
                    prior_structure = f"前段: {prior_low['price']:.3f}({prior_low['date']})→{abs_high['price']:.3f}({abs_high['date']})，上涨{rise_pct:.1f}%，{n_prior_swings}段转折"
                elif n_prior_swings >= 2:
                    prior_structure = f"前段: {prior_low['price']:.3f}({prior_low['date']})→{abs_high['price']:.3f}({abs_high['date']})，上涨{rise_pct:.1f}%"
                else:
                    prior_structure = f"前段低点: {prior_low['price']:.3f}({prior_low['date']})→高点{abs_high['price']:.3f}，上涨{rise_pct:.1f}%"
                if rise_pct > 20:
                    if n_prior_swings >= 5:
                        prior_structure += "（疑似5浪上涨）"
                    elif n_prior_swings >= 3:
                        prior_structure += "（ABC反弹）"
                    else:
                        prior_structure += "（单段上涨）"

        if len(downtrend_pivots) < 2:
            return {
                "position": "数据不足",
                "upside_prob": 50,
                "wave_points": [],
                "description": "下降段转折点不足",
                "detail": {"signal": "数据不足"},
            }

        # Label downward waves: alternating LOW/HIGH from the HIGH origin
        # Wave 1 = down to LOW, Wave 2 = up to HIGH, Wave 3 = down to LOW, etc.
        wave_points = []
        # Add prior low as context point
        if prior_low:
            wave_points.append({
                'label': '前低',
                'date': prior_low['date'],
                'price': prior_low['price'],
                'type': 'LOW',
            })

        impulse_phase = True
        wave_num = 1  # Current impulse wave (1,3,5) — all are DOWN
        correction_label = 'A'
        large_single_wave_count = 0  # P1 #2: track waves >50% without sub-division

        for i, p in enumerate(downtrend_pivots):
            if i == 0:
                wave_points.append({
                    'label': '起点',
                    'date': p['date'],
                    'price': p['price'],
                    'type': 'HIGH',
                })
                continue

            if impulse_phase:
                if p['type'] == 'LOW':
                    # P1 #2: 检测大跌幅单浪——超过50%跌幅的单一浪可能内含子浪
                    wave_decline_pct = 0
                    origin_price = downtrend_pivots[0]['price']
                    if origin_price > 0:
                        wave_decline_pct = (origin_price - p['price']) / origin_price * 100
                    wp_entry = {
                        'label': f'浪{wave_num}底',
                        'date': p['date'],
                        'price': p['price'],
                        'type': 'LOW',
                    }
                    if wave_num in (1, 5) and wave_decline_pct > 50:
                        wp_entry['detail'] = {
                            'sub_wave_warning': True,
                            'decline_pct': round(wave_decline_pct, 1),
                            'note': f'单浪跌幅{wave_decline_pct:.1f}%>50%，可能内含子浪未细分',
                        }
                        large_single_wave_count += 1
                    wave_points.append(wp_entry)
                elif p['type'] == 'HIGH':
                    # Upward correction within downtrend (wave 2, 4 top)
                    correction_num = wave_num + 1
                    if correction_num <= 4:
                        wave_points.append({
                            'label': f'浪{correction_num}顶',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'HIGH',
                        })
                        wave_num += 2
                    else:
                        # After Wave 5, this is A-wave bounce top
                        wave_points.append({
                            'label': '调整A浪顶',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'HIGH',
                        })
                        impulse_phase = False
                        correction_label = 'B'
            else:
                # Post-impulse ABC correction (bounce after decline)
                # CRITICAL: B浪底 must NOT go below 浪5底.
                # If a LOW is found below 浪5底, the decline has extended —
                # extend 浪5底 to this new low and restart ABC.
                if p['type'] == 'LOW':
                    w5_bottom = next(
                        (wp for wp in wave_points if wp.get('label') == '浪5底'), None
                    )
                    # Only extend 浪5底 if the correction hasn't completed yet
                    # (correction_label <= 'C'). If ABC is done, a low below
                    # 浪5底 is a NEW post-correction impulse, not an extension.
                    if w5_bottom and p['price'] < w5_bottom['price'] and correction_label <= 'C':
                        # B浪底 broke below 浪5底 → decline extended
                        # Remove the entire prior correction (浪5底 + all 调整* labels) and extend
                        wave_points = [
                            wp for wp in wave_points
                            if not wp.get('label', '').startswith('调整') and wp.get('label') != '浪5底'
                        ]
                        wave_points.append({
                            'label': '浪5底',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'LOW',
                        })
                        # Stay in impulse phase — next HIGH will be A浪顶
                        impulse_phase = True
                        wave_num = 5
                    else:
                        if correction_label <= 'C':
                            wave_points.append({
                                'label': f'调整{correction_label}浪底',
                                'date': p['date'],
                                'price': p['price'],
                                'type': 'LOW',
                            })
                            correction_label = chr(ord(correction_label) + 1)
                        # 不重新开始推动浪——保持在修正阶段。
                        # 如果后续低点跌破浪5底，上面的扩展逻辑（line 3108-3123）
                        # 会自动延长浪5底。这样就不会把延长浪5内的子浪误标为新序列。
                elif p['type'] == 'HIGH':
                    if correction_label <= 'C':
                        wave_points.append({
                            'label': f'调整{correction_label}浪顶',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'HIGH',
                        })
                        correction_label = chr(ord(correction_label) + 1)
                    # 同理：不重新开始推动浪，保持在修正阶段

        # ============================================================
        # Post-ABC Classification: compound correction vs new impulse
        # After ABC completes (correction_label > 'C'), remaining pivots
        # signal either compound correction or new downtrend impulse.
        # Mirror of uptrend logic with HIGH/LOW types swapped.
        # ============================================================
        if not impulse_phase and correction_label > 'C':
            c_idx = next((i for i, wp in enumerate(wave_points)
                         if '调整C浪顶' in wp.get('label', '')), None)

            if c_idx is not None:
                c_point = wave_points[c_idx]
                c_pivot_idx = None
                for pi, p in enumerate(downtrend_pivots):
                    if (p['type'] == 'HIGH' and
                            abs(p['price'] - c_point['price']) / max(abs(c_point['price']), 0.01) < 0.01):
                        c_pivot_idx = pi
                        break

                if c_pivot_idx is not None and c_pivot_idx + 1 < len(downtrend_pivots):
                    remaining = downtrend_pivots[c_pivot_idx + 1:]

                    if remaining:
                        b_bottom = next((wp for wp in wave_points
                                        if '调整B浪底' in wp.get('label', '')), None)
                        w4_top = next((wp for wp in wave_points
                                      if wp.get('label') == '浪4顶'), None)
                        first_pivot = remaining[0]  # always LOW (zigzag alternation)

                        signals = {}

                        if b_bottom and first_pivot['price'] < b_bottom['price']:
                            signals['break_b_bottom'] = 3.0
                        if w4_top and first_pivot['price'] < w4_top['price']:
                            signals['break_w4'] = 1.5
                        if b_bottom and first_pivot['price'] >= b_bottom['price']:
                            signals['above_b_bottom'] = 2.0
                        if c_point and b_bottom:
                            abc_range = c_point['price'] - b_bottom['price']
                            if abc_range > 0:
                                drop_pct = (c_point['price'] - first_pivot['price']) / abc_range
                                if drop_pct > 0.618:
                                    signals['strong_drop'] = 2.0
                                elif drop_pct > 0.382:
                                    signals['moderate_drop'] = 1.0
                                else:
                                    signals['weak_drop'] = 1.0
                        if len(remaining) >= 3:
                            signals['multi_pivot'] = 1.5

                        compound_score = sum(w for k, w in signals.items()
                                            if k in ('above_b_bottom', 'weak_drop', 'multi_pivot'))
                        impulse_score = sum(w for k, w in signals.items()
                                           if k in ('break_b_bottom', 'break_w4', 'strong_drop'))

                        if impulse_score >= 3.5:
                            classification = 'new_impulse'
                        elif compound_score >= 2.0:
                            classification = 'compound'
                        elif impulse_score > 0:
                            classification = 'new_impulse'
                        else:
                            classification = 'compound'

                        if classification == 'new_impulse':
                            wave_points.append({
                                'label': '新起点',
                                'date': c_point['date'],
                                'price': c_point['price'],
                                'type': 'HIGH',
                            })
                            new_impulse_phase = True
                            new_wave_num = 1
                            new_correction_label = 'A'

                            for p in remaining:
                                if new_impulse_phase is True:
                                    if p['type'] == 'LOW':
                                        wave_points.append({
                                            'label': f'新{new_wave_num}底',
                                            'date': p['date'],
                                            'price': p['price'],
                                            'type': 'LOW',
                                        })
                                    elif p['type'] == 'HIGH':
                                        corr_num = new_wave_num + 1
                                        if corr_num <= 4:
                                            wave_points.append({
                                                'label': f'新{corr_num}顶',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'HIGH',
                                            })
                                            new_wave_num += 2
                                        else:
                                            wave_points.append({
                                                'label': '新A浪顶',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'HIGH',
                                            })
                                            new_impulse_phase = False
                                            new_correction_label = 'B'
                                elif new_impulse_phase is False:
                                    if new_correction_label <= 'C':
                                        if p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': f'新{new_correction_label}浪底',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'LOW',
                                            })
                                            new_correction_label = chr(ord(new_correction_label) + 1)
                                        elif p['type'] == 'HIGH':
                                            wave_points.append({
                                                'label': f'新{new_correction_label}浪顶',
                                                'date': p['date'],
                                                'price': p['price'],
                                                'type': 'HIGH',
                                            })
                                            new_correction_label = chr(ord(new_correction_label) + 1)
                                    else:
                                        # ABC completed → start continuation impulse (downtrend)
                                        new_impulse_phase = 'impulse2'
                                        new_wnum = 1
                                        if p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': f'续{new_wnum}底',
                                                'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                            })
                                        elif p['type'] == 'HIGH':
                                            wave_points.append({
                                                'label': '续2顶',
                                                'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                            })
                                            new_wnum += 2
                                elif new_impulse_phase == 'impulse2':
                                    if p['type'] == 'LOW':
                                        wave_points.append({
                                            'label': f'续{new_wnum}底',
                                            'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                        })
                                    elif p['type'] == 'HIGH':
                                        cn = new_wnum + 1
                                        if cn <= 4:
                                            wave_points.append({
                                                'label': f'续{cn}顶',
                                                'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                            })
                                            new_wnum += 2
                                        else:
                                            wave_points.append({
                                                'label': '续A浪顶',
                                                'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                            })
                                            new_impulse_phase = 'correction2'
                                            new_clabel = 'B'
                                elif new_impulse_phase == 'correction2':
                                    if new_clabel <= 'C':
                                        if p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': f'续{new_clabel}浪底',
                                                'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                            })
                                            new_clabel = chr(ord(new_clabel) + 1)
                                        elif p['type'] == 'HIGH':
                                            wave_points.append({
                                                'label': f'续{new_clabel}浪顶',
                                                'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                            })
                                            new_clabel = chr(ord(new_clabel) + 1)

                            # Elliott iron-rule validation for new downtrend impulse
                            new_origin = next((wp for wp in wave_points
                                              if wp['label'] == '新起点'), None)
                            new_w2 = next((wp for wp in wave_points
                                          if '新2顶' in wp.get('label', '')), None)
                            new_w1 = next((wp for wp in wave_points
                                          if '新1底' in wp.get('label', '')), None)
                            new_w4 = next((wp for wp in wave_points
                                          if '新4顶' in wp.get('label', '')), None)
                            r1_violation = False
                            if new_origin and new_w2 and new_w2['price'] > new_origin['price']:
                                # R1 violation: wave 2 breaks above origin →
                                # fundamentally invalid impulse, must revert
                                r1_violation = True
                            if new_w1 and new_w4 and new_w4['price'] > new_w1['price']:
                                # R3 violation: wave 4 overlaps wave 1 territory.
                                # Keep all labels — the iron rule counter already
                                # tracks this for bidirectional comparison.
                                pass
                            if r1_violation:
                                wave_points = [wp for wp in wave_points
                                              if not wp.get('label', '').startswith('新')]
                                classification = 'compound'

                        if classification == 'compound':
                            # After C浪顶(HIGH) in downtrend: LOW=X浪底, HIGH=Y浪顶, LOW=Y浪底, HIGH=Z浪顶
                            wxy_labels = [
                                ('X', 'LOW', '底'),
                                ('Y', 'HIGH', '顶'),
                                ('Y', 'LOW', '底'),
                                ('Z', 'HIGH', '顶'),
                            ]
                            consumed = 0
                            for i, p in enumerate(remaining):
                                if i >= len(wxy_labels):
                                    break
                                char, expected_type, pos = wxy_labels[i]
                                if p['type'] == expected_type:
                                    wave_points.append({
                                        'label': f'联合调整{char}浪{pos}',
                                        'date': p['date'],
                                        'price': p['price'],
                                        'type': p['type'],
                                    })
                                    consumed = i + 1

                            # Handle excess remaining pivots after W-X-Y-Z
                            excess = remaining[consumed:]
                            if excess:
                                # After Z浪顶(HIGH) in downtrend correction:
                                # Natural continuation = new DOWNTEND impulse
                                # Reversal signal = breaks above Z浪顶 → UPTREND
                                z_point = next((wp for wp in reversed(wave_points)
                                               if 'Z' in wp.get('label', '')), None)
                                last_compound_low = next((wp for wp in reversed(wave_points)
                                                         if '联合调整' in wp.get('label', '') and '底' in wp.get('label', '')), None)

                                reversal_signals = {}
                                for p in excess:
                                    if p['type'] == 'HIGH' and z_point and p['price'] > z_point['price']:
                                        reversal_signals['break_z_top'] = 3.0
                                    if p['type'] == 'LOW' and last_compound_low and p['price'] < last_compound_low['price']:
                                        reversal_signals['break_compound_low'] = 3.0

                                reversal_score = sum(w for k, w in reversal_signals.items()
                                                     if 'break_z_top' in k)
                                continuation_score = sum(w for k, w in reversal_signals.items()
                                                        if 'break_compound_low' in k)

                                if reversal_score >= 2.0 and len(excess) >= 2:
                                    # UPTREND reversal after compound correction
                                    # After Z浪顶(HIGH): LOW=新起点, HIGH=新1顶, LOW=新2底, ...
                                    rev_phase = 'origin'
                                    rev_wnum = 1
                                    rev_clabel = 'A'
                                    for p in excess:
                                        if rev_phase == 'origin' and p['type'] == 'LOW':
                                            wave_points.append({
                                                'label': '新起点', 'date': p['date'],
                                                'price': p['price'], 'type': 'LOW',
                                            })
                                            rev_phase = 'impulse'
                                        elif rev_phase == 'impulse':
                                            if p['type'] == 'HIGH':
                                                wave_points.append({
                                                    'label': f'新{rev_wnum}顶',
                                                    'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                })
                                            elif p['type'] == 'LOW':
                                                cn = rev_wnum + 1
                                                if cn <= 4:
                                                    wave_points.append({
                                                        'label': f'新{cn}底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_wnum += 2
                                                else:
                                                    wave_points.append({
                                                        'label': '新A浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_phase = 'correction'
                                                    rev_clabel = 'B'
                                        elif rev_phase == 'correction':
                                            if rev_clabel <= 'C':
                                                if p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'新{rev_clabel}浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    rev_clabel = chr(ord(rev_clabel) + 1)
                                                elif p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'新{rev_clabel}浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_clabel = chr(ord(rev_clabel) + 1)
                                            else:
                                                # Correction completed → restart impulse for remaining pivots
                                                rev_phase = 'impulse2'
                                                rev_wnum = 1
                                                rev_clabel = 'A'
                                                if p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'续{rev_wnum}顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                elif p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': '续2底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_wnum += 2
                                        elif rev_phase == 'impulse2':
                                            if p['type'] == 'HIGH':
                                                wave_points.append({
                                                    'label': f'续{rev_wnum}顶',
                                                    'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                })
                                            elif p['type'] == 'LOW':
                                                cn = rev_wnum + 1
                                                if cn <= 4:
                                                    wave_points.append({
                                                        'label': f'续{cn}底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_wnum += 2
                                                else:
                                                    wave_points.append({
                                                        'label': '续A浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_phase = 'correction2'
                                                    rev_clabel = 'B'
                                        elif rev_phase == 'correction2':
                                            if rev_clabel <= 'C':
                                                if p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'续{rev_clabel}浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    rev_clabel = chr(ord(rev_clabel) + 1)
                                                elif p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'续{rev_clabel}浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    rev_clabel = chr(ord(rev_clabel) + 1)
                                    # Validate new uptrend: R1+R3
                                    n_origin = next((wp for wp in wave_points if wp['label'] == '新起点'), None)
                                    n_w2 = next((wp for wp in wave_points if '新2底' in wp.get('label', '')), None)
                                    n_w1t = next((wp for wp in wave_points if '新1顶' in wp.get('label', '')), None)
                                    n_w4 = next((wp for wp in wave_points if '新4底' in wp.get('label', '')), None)
                                    if n_origin and n_w2 and n_w2['price'] < n_origin['price']:
                                        # R1 violation: structure fundamentally invalid → remove all 新 labels
                                        wave_points = [wp for wp in wave_points
                                                      if not wp.get('label', '').startswith('新')]
                                    elif n_w1t and n_w4 and n_w4['price'] < n_w1t['price']:
                                        # R3 violation: wave 4 overlaps wave 1.
                                        # Keep all labels — the iron rule counter already
                                        # tracks this for bidirectional comparison.
                                        pass
                                    # Validate 续 labels: if R2 fails, convert to compound correction
                                    xu_labels = [wp for wp in wave_points if wp.get('label', '').startswith('续')]
                                    if xu_labels:
                                        xu_w1t = next((wp for wp in xu_labels if '续1顶' in wp.get('label', '')), None)
                                        xu_w1b = next((wp for wp in xu_labels if '续1底' in wp.get('label', '')), None)
                                        xu_w2b = next((wp for wp in xu_labels if '续2底' in wp.get('label', '')), None)
                                        xu_w2t = next((wp for wp in xu_labels if '续2顶' in wp.get('label', '')), None)
                                        xu_w3t = next((wp for wp in xu_labels if '续3顶' in wp.get('label', '')), None)
                                        xu_w3b = next((wp for wp in xu_labels if '续3底' in wp.get('label', '')), None)
                                        r2_fail = False
                                        if xu_w1t and xu_w2b and xu_w3t:
                                            xu_origin = next((wp for wp in wave_points if '新C浪底' in wp.get('label', '')), None)
                                            if xu_origin:
                                                w1_len = abs(xu_w1t['price'] - xu_origin['price'])
                                                w3_len = abs(xu_w3t['price'] - xu_w2b['price'])
                                                if w3_len < w1_len:
                                                    r2_fail = True
                                            if xu_w3t['price'] < xu_w1t['price']:
                                                r2_fail = True
                                        elif xu_w1b and xu_w2t and xu_w3b:
                                            xu_origin = next((wp for wp in wave_points if '新C浪顶' in wp.get('label', '')), None)
                                            if xu_origin:
                                                w1_len = abs(xu_w1b['price'] - xu_origin['price'])
                                                w3_len = abs(xu_w3b['price'] - xu_w2t['price'])
                                                if w3_len < w1_len:
                                                    r2_fail = True
                                            if xu_w3b['price'] > xu_w1b['price']:
                                                r2_fail = True
                                        if r2_fail:
                                            # Check: if the compound LOW goes below the
                                            # prior impulse bottom, the downtrend extended —
                                            # don't convert.
                                            xu_w1b = next((wp for wp in xu_labels if '续1底' in wp.get('label', '')), None)
                                            prior_impulse_bottom = next((wp for wp in wave_points if '新5底' in wp.get('label', '')), None)
                                            if not prior_impulse_bottom:
                                                prior_impulse_bottom = next((wp for wp in wave_points if '新3底' in wp.get('label', '')), None)
                                            if not prior_impulse_bottom:
                                                prior_impulse_bottom = next((wp for wp in wave_points if '浪5底' in wp.get('label', '')), None)
                                            if xu_w1b and prior_impulse_bottom and xu_w1b['price'] < prior_impulse_bottom['price']:
                                                pass
                                            else:
                                                label_map = {}
                                                for wp in xu_labels:
                                                    lbl = wp['label']
                                                    mapping = {
                                                        '续1顶': '联合调整续X浪顶', '续2底': '联合调整续X浪底',
                                                        '续3顶': '联合调整续Y浪顶', '续4底': '联合调整续Y浪底',
                                                        '续1底': '联合调整续X浪底', '续2顶': '联合调整续X浪顶',
                                                        '续3底': '联合调整续Y浪底', '续4顶': '联合调整续Y浪顶',
                                                        '续A浪底': '联合调整续Z浪底', '续A浪顶': '联合调整续Z浪顶',
                                                        '续B浪底': '联合调整续XX浪底', '续B浪顶': '联合调整续XX浪顶',
                                                        '续C浪底': '联合调整续XY浪底', '续C浪顶': '联合调整续XY浪顶',
                                                    }
                                                    for _k, _v in mapping.items():
                                                        if _k in lbl:
                                                            label_map[lbl] = _v
                                                            break
                                                for wp in xu_labels:
                                                    if wp['label'] in label_map:
                                                        wp['label'] = label_map[wp['label']]
                                elif continuation_score >= 2.0 and len(excess) >= 2:
                                    # DOWNTEND continuation after compound correction
                                    # New downtrend impulse starting from Z浪顶
                                    new_phase = True
                                    new_wnum = 1
                                    new_clabel = 'A'
                                    for p in excess:
                                        if new_phase is True:
                                            if p['type'] == 'LOW':
                                                wave_points.append({
                                                    'label': f'新{new_wnum}底',
                                                    'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                })
                                            elif p['type'] == 'HIGH':
                                                cn = new_wnum + 1
                                                if cn <= 4:
                                                    wave_points.append({
                                                        'label': f'新{cn}顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_wnum += 2
                                                else:
                                                    wave_points.append({
                                                        'label': '新A浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_phase = False
                                                    new_clabel = 'B'
                                        elif new_phase is False:
                                            if new_clabel <= 'C':
                                                if p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'新{new_clabel}浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                                elif p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'新{new_clabel}浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                            else:
                                                # Correction completed → restart impulse for remaining pivots
                                                new_phase = 'impulse2'
                                                new_wnum = 1
                                                new_clabel = 'A'
                                                if p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'续{new_wnum}底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                elif p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': '续2顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_wnum += 2
                                        elif new_phase == 'impulse2':
                                            if p['type'] == 'LOW':
                                                wave_points.append({
                                                    'label': f'续{new_wnum}底',
                                                    'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                })
                                            elif p['type'] == 'HIGH':
                                                cn = new_wnum + 1
                                                if cn <= 4:
                                                    wave_points.append({
                                                        'label': f'续{cn}顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_wnum += 2
                                                else:
                                                    wave_points.append({
                                                        'label': '续A浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_phase = 'correction2'
                                                    new_clabel = 'B'
                                        elif new_phase == 'correction2':
                                            if new_clabel <= 'C':
                                                if p['type'] == 'LOW':
                                                    wave_points.append({
                                                        'label': f'续{new_clabel}浪底',
                                                        'date': p['date'], 'price': p['price'], 'type': 'LOW',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                                elif p['type'] == 'HIGH':
                                                    wave_points.append({
                                                        'label': f'续{new_clabel}浪顶',
                                                        'date': p['date'], 'price': p['price'], 'type': 'HIGH',
                                                    })
                                                    new_clabel = chr(ord(new_clabel) + 1)
                                    # Validate R1+R3 for downtrend
                                    nw2 = next((wp for wp in wave_points if '新2顶' in wp.get('label', '')), None)
                                    nw1b = next((wp for wp in wave_points if '新1底' in wp.get('label', '')), None)
                                    nw4 = next((wp for wp in wave_points if '新4顶' in wp.get('label', '')), None)
                                    if z_point and nw2 and nw2['price'] > z_point['price']:
                                        # R1 violation: structure fundamentally invalid → remove all 新 labels
                                        wave_points = [wp for wp in wave_points
                                                      if not wp.get('label', '').startswith('新')]
                                    elif nw1b and nw4 and nw4['price'] > nw1b['price']:
                                        # R3 violation: wave 4 overlaps wave 1.
                                        # Keep all labels — the iron rule counter already
                                        # tracks this violation for bidirectional comparison.
                                        pass
                                    # Validate 续 labels: if R2 fails, convert to compound correction
                                    xu_labels = [wp for wp in wave_points if wp.get('label', '').startswith('续')]
                                    if xu_labels:
                                        xu_w1t = next((wp for wp in xu_labels if '续1顶' in wp.get('label', '')), None)
                                        xu_w1b = next((wp for wp in xu_labels if '续1底' in wp.get('label', '')), None)
                                        xu_w2b = next((wp for wp in xu_labels if '续2底' in wp.get('label', '')), None)
                                        xu_w2t = next((wp for wp in xu_labels if '续2顶' in wp.get('label', '')), None)
                                        xu_w3t = next((wp for wp in xu_labels if '续3顶' in wp.get('label', '')), None)
                                        xu_w3b = next((wp for wp in xu_labels if '续3底' in wp.get('label', '')), None)
                                        r2_fail = False
                                        if xu_w1t and xu_w2b and xu_w3t:
                                            xu_origin = next((wp for wp in wave_points if '新C浪底' in wp.get('label', '')), None)
                                            if xu_origin:
                                                w1_len = abs(xu_w1t['price'] - xu_origin['price'])
                                                w3_len = abs(xu_w3t['price'] - xu_w2b['price'])
                                                if w3_len < w1_len:
                                                    r2_fail = True
                                            if xu_w3t['price'] < xu_w1t['price']:
                                                r2_fail = True
                                        elif xu_w1b and xu_w2t and xu_w3b:
                                            xu_origin = next((wp for wp in wave_points if '新C浪顶' in wp.get('label', '')), None)
                                            if xu_origin:
                                                w1_len = abs(xu_w1b['price'] - xu_origin['price'])
                                                w3_len = abs(xu_w3b['price'] - xu_w2t['price'])
                                                if w3_len < w1_len:
                                                    r2_fail = True
                                            if xu_w3b['price'] > xu_w1b['price']:
                                                r2_fail = True
                                        if r2_fail:
                                            # Guard: don't convert if the compound label
                                            # would exceed the prior impulse extreme
                                            xu_w1t_3 = next((wp for wp in xu_labels if '续1顶' in wp.get('label', '')), None)
                                            xu_w1b_3 = next((wp for wp in xu_labels if '续1底' in wp.get('label', '')), None)
                                            skip_convert = False
                                            if xu_w1t_3:
                                                pit = next((wp for wp in wave_points if '新5顶' in wp.get('label', '')), None) or \
                                                      next((wp for wp in wave_points if '新3顶' in wp.get('label', '')), None) or \
                                                      next((wp for wp in wave_points if '浪5顶' in wp.get('label', '')), None)
                                                if pit and xu_w1t_3['price'] > pit['price']:
                                                    skip_convert = True
                                            if xu_w1b_3:
                                                pib = next((wp for wp in wave_points if '新5底' in wp.get('label', '')), None) or \
                                                      next((wp for wp in wave_points if '新3底' in wp.get('label', '')), None) or \
                                                      next((wp for wp in wave_points if '浪5底' in wp.get('label', '')), None)
                                                if pib and xu_w1b_3['price'] < pib['price']:
                                                    skip_convert = True
                                            if not skip_convert:
                                                label_map = {}
                                                for wp in xu_labels:
                                                    lbl = wp['label']
                                                    mapping = {
                                                        '续1顶': '联合调整续X浪顶', '续2底': '联合调整续X浪底',
                                                        '续3顶': '联合调整续Y浪顶', '续4底': '联合调整续Y浪底',
                                                        '续1底': '联合调整续X浪底', '续2顶': '联合调整续X浪顶',
                                                        '续3底': '联合调整续Y浪底', '续4顶': '联合调整续Y浪顶',
                                                        '续A浪底': '联合调整续Z浪底', '续A浪顶': '联合调整续Z浪顶',
                                                        '续B浪底': '联合调整续XX浪底', '续B浪顶': '联合调整续XX浪顶',
                                                        '续C浪底': '联合调整续XY浪底', '续C浪顶': '联合调整续XY浪顶',
                                                    }
                                                    for _k, _v in mapping.items():
                                                        if _k in lbl:
                                                            label_map[lbl] = _v
                                                            break
                                                for wp in xu_labels:
                                                    if wp['label'] in label_map:
                                                        wp['label'] = label_map[wp['label']]
                                else:
                                    # No clear signal: extend compound pattern
                                    extended_labels = [
                                        ('XX', 'LOW', '底'), ('XX', 'HIGH', '顶'),
                                        ('XY', 'LOW', '底'), ('XY', 'HIGH', '顶'),
                                        ('XZ', 'LOW', '底'), ('XZ', 'HIGH', '顶'),
                                    ]
                                    for i, p in enumerate(excess):
                                        if i >= len(extended_labels):
                                            break
                                        char, expected_type, pos = extended_labels[i]
                                        if p['type'] == expected_type:
                                            wave_points.append({
                                                'label': f'联合调整{char}浪{pos}',
                                                'date': p['date'], 'price': p['price'], 'type': p['type'],
                                            })

        # ============================================================
        # Elliott Rule Validation: Wave 3 cannot be the shortest
        # impulse wave. For downtrend, if Wave 3 decline is smaller
        # than Wave 1, merge into extended Wave 1 + Wave 2 bounce.
        # ============================================================
        w1_bottom = [wp for wp in wave_points if wp.get('label') == '浪1底']
        w2_top = [wp for wp in wave_points if wp.get('label') == '浪2顶']
        w3_bottom = [wp for wp in wave_points if wp.get('label') == '浪3底']
        start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), None)

        if w1_bottom and w2_top and w3_bottom and start_pt:
            w1_decline = (start_pt['price'] - w1_bottom[0]['price']) / start_pt['price']
            w3_decline = (w2_top[0]['price'] - w3_bottom[0]['price']) / w2_top[0]['price']
            if w3_decline < w1_decline:
                # Wave 3 decline is smaller than Wave 1 — violates Elliott rule.
                # Only merge if the structure hasn't already been extended with
                # compound corrections or new impulses (same guard as uptrend).
                extended_labels = [wp for wp in wave_points if wp.get('label', '').startswith('新') or '联合调整' in wp.get('label', '') or wp.get('label', '').startswith('续')]
                if not extended_labels:
                    all_after_start = wave_points[1:]  # Skip 起点
                    low_points = [wp for wp in all_after_start if wp['type'] == 'LOW']
                    if low_points:
                        # Extended Wave 1 bottom = lowest LOW point
                        w1_extended = min(low_points, key=lambda wp: wp['price'])
                        w1_ext_idx = wave_points.index(w1_extended)
                        # Wave 2 top = highest HIGH point after extended Wave 1
                        after_w1 = wave_points[w1_ext_idx + 1:]
                        high_after_w1 = [wp for wp in after_w1 if wp['type'] == 'HIGH']
                        w2_new = max(high_after_w1, key=lambda wp: wp['price']) if high_after_w1 else None
                        # Build new wave_points: 起点 → 浪1底 → 浪2顶
                        start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                        new_wave_points = [start_pt]
                        new_wave_points.append({
                            'label': '浪1底',
                            'date': w1_extended['date'],
                            'price': w1_extended['price'],
                            'type': 'LOW',
                        })
                        if w2_new:
                            new_wave_points.append({
                                'label': '浪2顶',
                                'date': w2_new['date'],
                                'price': w2_new['price'],
                                'type': 'HIGH',
                            })
                        wave_points = new_wave_points

        # Determine current wave position
        last_pivot = downtrend_pivots[-1]

        # Count downward impulse waves (wave bottoms) and upward corrections (wave tops)
        impulse_waves = [wp for wp in wave_points if '浪' in wp.get('label', '') and '底' in wp.get('label', '') and '调整' not in wp.get('label', '') and '联合' not in wp.get('label', '') and not wp.get('label', '').startswith('新')]
        correction_waves = [wp for wp in wave_points if '顶' in wp.get('label', '') and '调整' not in wp.get('label', '') and '联合' not in wp.get('label', '') and not wp.get('label', '').startswith('新')]
        abc_points = [wp for wp in wave_points if '调整' in wp.get('label', '') and '联合' not in wp.get('label', '')]
        compound_points = [wp for wp in wave_points if '联合调整' in wp.get('label', '')]
        new_impulse_points = [wp for wp in wave_points if wp.get('label', '').startswith('新')]

        position = "未知"
        upside_prob = 50
        description = ""
        detail = {"direction": "下跌"}

        n_impulse = len(impulse_waves)
        n_correction = len(correction_waves)
        in_abc = len(abc_points) > 0
        in_compound = len(compound_points) > 0
        has_new_impulse = len(new_impulse_points) > 0

        if has_new_impulse:
            # New downtrend impulse cycle detected after ABC completion
            new_bottoms = [wp for wp in new_impulse_points if '底' in wp.get('label', '')]
            new_tops = [wp for wp in new_impulse_points if '顶' in wp.get('label', '')]
            n_new_bottoms = len(new_bottoms)

            if n_new_bottoms >= 3:
                position = "新一轮下跌推动浪第5浪"
                upside_prob = 65
                description = f"ABC反弹结束后启动新一轮下跌推动浪，已运行至第5浪"
            elif n_new_bottoms == 2:
                position = "新一轮下跌推动浪第3浪"
                upside_prob = 30
                description = f"新一轮下跌推动浪进行中：新1底{new_bottoms[0]['price']:.3f}"
            elif n_new_bottoms == 1:
                if new_tops:
                    position = "新一轮下跌推动浪第3浪"
                    upside_prob = 25
                    description = f"新推动浪浪2反弹完成后进入浪3，当前{current_price:.3f}"
                else:
                    position = "新一轮下跌推动浪第1浪"
                    upside_prob = 45
                    description = f"ABC反弹结束，新下跌推动浪第1浪至{new_bottoms[0]['price']:.3f}"
            else:
                position = "新一轮下跌推动浪启动"
                upside_prob = 45
                description = "ABC反弹结束，新一轮下跌推动浪启动中"

        elif in_compound:
            last_comp = compound_points[-1]
            clabel = last_comp['label']

            if 'X浪底' in clabel:
                if current_price < last_comp['price']:
                    position = "联合调整浪X浪"
                    upside_prob = 70
                    description = f"ABC反弹结束后进入联合调整，X浪下跌进行中{current_price:.3f}"
                else:
                    position = "联合调整浪X浪末端"
                    upside_prob = 75
                    description = f"联合调整X浪下跌后反弹至{current_price:.3f}，Y浪反弹可能"
            elif 'Y浪顶' in clabel:
                position = "联合调整浪Y浪末端"
                upside_prob = 60
                description = f"联合调整Y浪顶{last_comp['price']:.3f}，调整可能结束"
            elif 'Y浪底' in clabel:
                position = "联合调整浪Y浪"
                upside_prob = 70
                description = f"联合调整Y浪下跌中{current_price:.3f}"
            elif 'Z' in clabel:
                position = "联合调整浪Z浪末端"
                upside_prob = 55
                description = f"三重联合调整接近尾声，当前{current_price:.3f}"
            else:
                position = "联合调整浪"
                upside_prob = 70
                description = "ABC后进入联合调整阶段"

        elif in_abc:
            # Downward 5-wave complete, in ABC bounce
            # ============================================================
            # KEY DISTINCTION: 反弹 vs 反转
            # After a 5-wave downtrend, ABC can be either:
            #   - 反弹 (bounce/correction): ABC retraces <61.8% of 5-wave
            #     decline, doesn't break above 浪4顶 → trend continues down
            #   - 反转 (reversal): ABC retraces >61.8%, or price breaks
            #     above 浪4顶 → new uptrend starting
            # ============================================================

            last_abc = abc_points[-1]
            abc_label = last_abc['label']

            # --- Reversal detection ---
            # Calculate retracement ratio of current bounce vs 5-wave decline
            reversal_score = 0  # 0-3 scale
            reversal_reasons = []

            start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0] if wave_points else None)
            w5_bottom_pt = impulse_waves[-1] if impulse_waves else None
            w4_top_pt = [wp for wp in correction_waves if '浪4顶' in wp.get('label', '')]

            if start_pt and w5_bottom_pt:
                decline = start_pt['price'] - w5_bottom_pt['price']  # 5-wave decline
                if decline > 0:
                    # Retracement = how much of the decline has been recovered
                    retracement = (current_price - w5_bottom_pt['price']) / decline
                    detail["retracement_ratio"] = round(retracement, 3)

                    if retracement > 0.786:
                        reversal_score += 2
                        reversal_reasons.append(f"回撤{retracement*100:.0f}%超过78.6%，接近完全收复5浪跌幅")
                    elif retracement > 0.618:
                        reversal_score += 1.5
                        reversal_reasons.append(f"回撤{retracement*100:.0f}%超过61.8%关键位")
                    elif retracement > 0.5:
                        reversal_score += 0.5
                        reversal_reasons.append(f"回撤{retracement*100:.0f}%超过50%")

            # Price breaking above 浪4顶 is a strong reversal signal
            if w4_top_pt and current_price > w4_top_pt[0]['price']:
                reversal_score += 2
                reversal_reasons.append(f"价格{current_price:.3f}突破浪4顶{w4_top_pt[0]['price']:.3f}，趋势反转信号")

            # C浪突破A浪顶 (in ABC: C exceeds A) also indicates reversal
            a_top_pt = [wp for wp in abc_points if 'A浪顶' in wp.get('label', '')]
            if a_top_pt and current_price > a_top_pt[0]['price']:
                reversal_score += 1
                reversal_reasons.append(f"价格突破A浪顶{a_top_pt[0]['price']:.3f}，反弹力度强于一般ABC")

            detail["reversal_score"] = reversal_score
            if reversal_reasons:
                detail["reversal_reasons"] = reversal_reasons

            # Determine position based on ABC sub-wave + reversal detection
            is_reversal = reversal_score >= 2.5  # Strong reversal signals

            if 'A浪顶' in abc_label:
                if current_price < last_abc['price']:
                    if is_reversal:
                        # B浪浅回踩后反转
                        position = "下跌5浪后趋势反转"
                        upside_prob = 65
                        description = f"下跌5浪完成，A浪反弹后B浪浅回踩{current_price:.3f}，{'；'.join(reversal_reasons)}，趋势反转概率大"
                    else:
                        position = "下跌5浪后B浪回落"
                        upside_prob = 30
                        pct = (current_price - last_abc['price']) / last_abc['price'] * 100
                        description = f"下跌5浪完成，A浪反弹顶{last_abc['price']:.3f}→B浪回落{current_price:.3f}({pct:+.1f}%)，注意C浪反弹后可能继续下跌"
                else:
                    if is_reversal:
                        position = "下跌5浪后趋势反转"
                        upside_prob = 65
                        description = f"下跌5浪完成，A浪反弹持续走强{current_price:.3f}，{'；'.join(reversal_reasons)}，趋势反转概率大"
                    else:
                        position = "下跌5浪后A浪反弹"
                        upside_prob = 40
                        pct = (current_price - last_abc['price']) / last_abc['price'] * 100
                        description = f"下跌5浪完成，A浪反弹中{pct:+.1f}%"
            elif 'B浪底' in abc_label:
                if current_price > last_abc['price']:
                    if is_reversal:
                        position = "下跌5浪后趋势反转"
                        upside_prob = 70
                        description = f"下跌5浪完成，C浪强势反弹{current_price:.3f}，{'；'.join(reversal_reasons)}，趋势反转信号强"
                    else:
                        position = "下跌5浪后C浪反弹"
                        upside_prob = 45
                        pct = (current_price - last_abc['price']) / last_abc['price'] * 100
                        description = f"下跌5浪完成，B浪底{last_abc['price']:.3f}→C浪反弹{current_price:.3f}({pct:+.1f}%)"
                else:
                    position = "下跌5浪后B浪回落"
                    upside_prob = 25
                    description = f"下跌5浪完成，B浪回落中{current_price:.3f}，可能进入C浪反弹"
            elif 'C浪顶' in abc_label:
                # C浪反弹已到顶，检查反转 vs 继续下跌
                b_bottom = [wp for wp in abc_points if 'B浪底' in wp.get('label', '')]
                if is_reversal and current_price > last_abc['price'] * 0.9:
                    # C浪后价格仍维持高位 + 反转信号 → 趋势反转
                    position = "下跌5浪后趋势反转"
                    upside_prob = 65
                    description = f"下跌5浪完成，C浪反弹后价格{current_price:.3f}维持高位，{'；'.join(reversal_reasons)}，趋势反转"
                elif b_bottom and current_price < b_bottom[0]['price']:
                    # 跌破B浪底 → 新一轮下跌推动浪开始
                    position = "新一轮下跌推动浪第1浪"
                    upside_prob = 20
                    pct_below = (current_price - b_bottom[0]['price']) / b_bottom[0]['price'] * 100
                    description = f"ABC反弹结束，价格跌破B浪底{b_bottom[0]['price']:.3f}至{current_price:.3f}({pct_below:+.1f}%)，新一轮下跌推动浪启动"
                elif b_bottom and current_price < last_abc['price'] * 0.95:
                    # 接近B浪底，C浪反弹接近结束
                    position = "下跌5浪后C浪反弹末端"
                    upside_prob = 30
                    description = f"下跌5浪完成，C浪反弹高点{last_abc['price']:.3f}，已回落至{current_price:.3f}，接近B浪底{b_bottom[0]['price']:.3f}，反弹即将结束"
                else:
                    position = "下跌5浪后C浪反弹末端"
                    upside_prob = 35
                    description = f"下跌5浪完成，C浪反弹高点{last_abc['price']:.3f}，反弹可能结束"
            else:
                position = "下跌调整浪"
                upside_prob = 30
                description = "下跌5浪结构完成，反弹调整中"

            w5_bottom = impulse_waves[-1] if impulse_waves else None
            if w5_bottom:
                a_top = [wp for wp in abc_points if 'A浪顶' in wp.get('label', '')]
                if a_top:
                    detail["5浪低点"] = f"{w5_bottom['price']:.3f}({w5_bottom['date']})"
                    detail["A浪高点"] = f"{a_top[0]['price']:.3f}({a_top[0]['date']})"

        elif n_impulse >= 3 and n_correction >= 2:
            # All 5 downward impulse waves identified
            position = "下跌推动浪第5浪"
            upside_prob = 25
            w5 = impulse_waves[-1]
            pct = (current_price / w5['price'] - 1) * 100 if w5['price'] > 0 else 0
            description = f"下跌浪5进行中: 底{w5['price']:.3f}，当前{current_price:.3f}({pct:+.1f}%)，下跌趋势末期"

        elif n_impulse >= 2 and n_correction >= 1:
            w3 = [wp for wp in impulse_waves if '浪3底' in wp.get('label', '')]
            w4 = [wp for wp in correction_waves if '浪4顶' in wp.get('label', '')]

            if w3 and w4:
                position = "下跌推动浪第5浪"
                upside_prob = 25
                h4 = w4[0]
                pct = (current_price - h4['price']) / h4['price'] * 100
                description = f"下跌浪5进行中: {h4['price']:.3f}→{current_price:.3f}({pct:+.1f}%)，下跌趋势末期"
            elif w3 and not w4:
                position = "下跌推动浪第4浪反弹"
                upside_prob = 35
                l3 = w3[0]
                pct = (current_price - l3['price']) / l3['price'] * 100
                description = f"下跌浪3底{l3['price']:.3f}后反弹，当前{current_price:.3f}({pct:+.1f}%)"
            else:
                position = "下跌推动浪第3浪"
                upside_prob = 15
                description = "下跌浪3进行中（主跌段）"

        elif n_impulse >= 2 and n_correction == 0:
            position = "下跌推动浪第3浪"
            upside_prob = 15
            w1 = [wp for wp in impulse_waves if '浪1底' in wp.get('label', '')]
            w3 = [wp for wp in impulse_waves if '浪3底' in wp.get('label', '')]
            if w1 and w3:
                start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                description = f"下跌浪1: {start['price']:.3f}→{w1[0]['price']:.3f}, 下跌浪3进行中→{w3[0]['price']:.3f}"

        elif n_impulse == 1 and n_correction == 1:
            w2_high = [wp for wp in correction_waves if '浪2顶' in wp.get('label', '')]
            w1_low = [wp for wp in impulse_waves if '浪1底' in wp.get('label', '')]

            # === Sanity check: in downtrend, current price must be below Wave 2 top ===
            # If current_price > w2_high, the "Wave 2 top" is wrong — the bounce
            # continued past that point. Need to either:
            #   1. Extend Wave 2 to the actual highest HIGH pivot after Wave 1 bottom
            #   2. Reclassify as uptrend if the bounce is too strong
            if w2_high and current_price > w2_high[0]['price']:
                # Wave 2 top is stale — the bounce continued past the labeled point.
                # Use downtrend_pivots (raw zigzag pivots) instead of wave_points
                # because wave_points only contains labeled pivots and may miss higher bounces.
                w1_low_pt = w1_low[0] if w1_low else wave_points[1] if len(wave_points) > 1 else None
                if w1_low_pt:
                    # Find Wave 1 bottom's index in downtrend_pivots by matching date
                    w1_idx_in_pivots = None
                    for i, p in enumerate(downtrend_pivots):
                        if p.get('date') == w1_low_pt.get('date') and p['type'] == 'LOW':
                            w1_idx_in_pivots = i
                            break
                    # If not found by date, try by price proximity
                    if w1_idx_in_pivots is None:
                        for i, p in enumerate(downtrend_pivots):
                            if p['type'] == 'LOW' and abs(p['price'] - w1_low_pt['price']) / max(w1_low_pt['price'], 0.01) < 0.005:
                                w1_idx_in_pivots = i
                                break

                    # Find all HIGH pivots after Wave 1 bottom in raw pivots
                    actual_w2_top = None
                    if w1_idx_in_pivots is not None:
                        after_w1 = downtrend_pivots[w1_idx_in_pivots + 1:]
                        high_after_w1 = [p for p in after_w1 if p['type'] == 'HIGH']
                        if high_after_w1:
                            actual_w2_top = max(high_after_w1, key=lambda p: p['price'])

                    # Also check current_price as a potential high
                    if actual_w2_top is None or current_price > actual_w2_top['price']:
                        actual_w2_top = {'price': current_price, 'date': None, 'type': 'HIGH'}

                    # Check if this is actually a reversal (bounce > 61.8% of decline)
                    start_pt = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0] if wave_points else None)
                    if start_pt:
                        decline = start_pt['price'] - w1_low_pt['price']
                        if decline > 0:
                            retracement = (current_price - w1_low_pt['price']) / decline
                            if retracement > 0.618:
                                # Strong bounce → likely trend reversal, classify as uptrend
                                position = "新一轮上升推动浪第1浪"
                                upside_prob = 60
                                description = f"下跌后反弹强劲，回撤{retracement*100:.0f}%超过61.8%，价格{current_price:.3f}突破前浪2顶，趋势反转信号"
                                detail["reversal_detected"] = True
                                detail["retracement_ratio"] = round(retracement, 3)
                            else:
                                # Update Wave 2 top to the actual highest point from raw pivots
                                for wp in wave_points:
                                    if wp.get('label') == '浪2顶':
                                        wp['price'] = actual_w2_top['price']
                                        if actual_w2_top.get('date'):
                                            wp['date'] = actual_w2_top['date']

                                # Now recheck with corrected Wave 2 top
                                if current_price > actual_w2_top['price']:
                                    # Still above corrected w2 top → likely reversal
                                    position = "下跌推动浪第2浪反弹"
                                    upside_prob = 45
                                    description = f"价格{current_price:.3f}持续高于浪2顶{actual_w2_top['price']:.3f}，反弹加强中"
                                else:
                                    position = "下跌推动浪第3浪"
                                    upside_prob = 15
                                    w1_pct = (w1_low_pt['price'] - start_pt['price']) / start_pt['price'] * 100
                                    w2_pct = (actual_w2_top['price'] - w1_low_pt['price']) / w1_low_pt['price'] * 100
                                    w3_pct = (current_price - actual_w2_top['price']) / actual_w2_top['price'] * 100
                                    description = (f"下跌浪1: {start_pt['price']:.3f}→{w1_low_pt['price']:.3f}({w1_pct:+.1f}%), "
                                                 f"反弹浪2: {w1_low_pt['price']:.3f}→{actual_w2_top['price']:.3f}({w2_pct:+.1f}%), "
                                                 f"下跌浪3进行中: {actual_w2_top['price']:.3f}→{current_price:.3f}({w3_pct:+.1f}%)")
                                    detail = {"direction": "下跌", "wave1_pct": round(w1_pct, 1), "wave2_pct": round(w2_pct, 1), "wave3_pct": round(w3_pct, 1)}
                        else:
                            position = "下跌推动浪第2浪反弹"
                            upside_prob = 40
                            description = f"下跌浪1底{w1_low_pt['price']:.3f}后反弹持续中"
                    else:
                        position = "下跌推动浪第2浪反弹"
                        upside_prob = 40
                        description = f"下跌浪1底后反弹持续中，价格突破前浪2顶"
                else:
                    position = "下跌推动浪第2浪反弹"
                    upside_prob = 40
                    description = "反弹中，价格高于浪2顶"
            elif w2_high and last_pivot['type'] == 'HIGH':
                position = "下跌推动浪第3浪"
                upside_prob = 15
                start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                l1 = w1_low[0] if w1_low else wave_points[1]
                h2 = w2_high[0]
                w1_pct = (l1['price'] - start['price']) / start['price'] * 100
                w2_pct = (h2['price'] - l1['price']) / l1['price'] * 100
                w3_pct = (current_price - h2['price']) / h2['price'] * 100
                description = (f"下跌浪1: {start['price']:.3f}→{l1['price']:.3f}({w1_pct:+.1f}%), "
                             f"反弹浪2: {l1['price']:.3f}→{h2['price']:.3f}({w2_pct:+.1f}%), "
                             f"下跌浪3进行中: {h2['price']:.3f}→{current_price:.3f}({w3_pct:+.1f}%)")
                detail = {"direction": "下跌", "wave1_pct": round(w1_pct, 1), "wave2_pct": round(w2_pct, 1), "wave3_pct": round(w3_pct, 1)}
            elif w2_high and last_pivot['type'] == 'LOW':
                position = "下跌推动浪第3浪"
                upside_prob = 20
                description = "反弹浪2顶部确认后下跌，浪3进行中"
            else:
                position = "下跌推动浪第2浪反弹"
                upside_prob = 40
                if w1_low:
                    description = f"下跌浪1底{w1_low[0]['price']:.3f}后反弹中"

        elif n_impulse == 1 and n_correction == 0:
            position = "下跌推动浪第1浪"
            upside_prob = 30
            start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
            w1 = impulse_waves[0]
            pct = (w1['price'] - start['price']) / start['price'] * 100
            # P1 #2: 大跌幅单浪可能内含子浪，降低可信度
            if abs(pct) > 50:
                description = f"下跌浪1进行中: {start['price']:.3f}({start['date']})→{w1['price']:.3f}({w1['date']}), 跌幅{pct:+.1f}%（大跌幅单浪，可能内含子浪未细分）"
                upside_prob = 35
            else:
                description = f"下跌浪1进行中: {start['price']:.3f}({start['date']})→{w1['price']:.3f}({w1['date']}), 跌幅{pct:+.1f}%"

        else:
            position = "下跌推动浪第1浪"
            upside_prob = 30
            description = "从高点起步，下跌推动浪第1浪进行中"

        # Price below last LOW pivot → extending downward impulse
        if last_pivot['type'] == 'LOW' and current_price < last_pivot['price']:
            if position in ("下跌推动浪第5浪", "下跌5浪后A浪反弹", "下跌5浪后B浪回落"):
                if n_impulse >= 3 or in_abc:
                    position = "下跌推动浪第3浪延伸"
                    upside_prob = 10
                    description = f"价格跌破前低{last_pivot['price']:.3f}至{current_price:.3f}，下跌趋势加速"

        # Price above last HIGH pivot → deepening bounce in downtrend
        if last_pivot['type'] == 'HIGH' and current_price > last_pivot['price']:
            if position in ("下跌推动浪第2浪反弹", "下跌推动浪第4浪反弹"):
                upside_prob = min(50, upside_prob + 5)
                description += "，反弹加强"

        # Build position reasoning — explain WHY this position, not alternatives
        reasoning = self._build_position_reasoning(
            direction="下跌", position=position, n_impulse=n_impulse,
            n_correction=n_correction, in_abc=in_abc, wave_points=wave_points,
            abc_points=abc_points, current_price=current_price, last_pivot=last_pivot,
            compound_points=compound_points, new_impulse_points=new_impulse_points
        )
        detail["position_reasoning"] = reasoning

        # Add prior structure context
        if prior_structure:
            detail["prior_structure"] = prior_structure
            description = f"{prior_structure}；{description}"

        # P1 #2: 大跌幅单浪降低可信度
        confidence = 1.0
        if large_single_wave_count > 0:
            confidence *= 0.8
            detail["large_single_wave_count"] = large_single_wave_count

        return {
            "position": position,
            "upside_prob": upside_prob,
            "wave_points": wave_points,
            "description": description,
            "detail": detail,
            "confidence": round(confidence, 2),
        }

        # Find the starting point for wave labeling:
        # Look for the lowest LOW point from which a sustained uptrend began
        # We search from the end backwards to find the most recent uptrend

        # First, find all LOW points
        lows = [p for p in pivots if p['type'] == 'LOW']
        highs = [p for p in pivots if p['type'] == 'HIGH']

        if not lows or not highs:
            return {
                "position": "数据不足",
                "upside_prob": 50,
                "wave_points": [],
                "description": "无法识别高低点",
                "detail": {"signal": "数据不足"},
            }

        # Find the absolute lowest point - this is our wave origin
        abs_low = min(lows, key=lambda p: p['price'])

        # Collect pivots from abs_low onwards
        uptrend_pivots = [p for p in pivots if p['idx'] >= abs_low['idx']]

        if len(uptrend_pivots) < 2:
            return {
                "position": "数据不足",
                "upside_prob": 50,
                "wave_points": [],
                "description": "上升段转折点不足",
                "detail": {"signal": "数据不足"},
            }

        # Label waves: alternating HIGH/LOW starting from the LOW origin
        # LOW→HIGH = impulse wave (1,3,5)
        # HIGH→LOW = correction wave (2,4)
        wave_points = []
        wave_num = 1  # current impulse wave number
        for i, p in enumerate(uptrend_pivots):
            if i == 0:
                # Starting LOW point
                wave_points.append({
                    'label': '起点',
                    'date': p['date'],
                    'price': p['price'],
                    'type': 'LOW',
                })
                continue

            if p['type'] == 'HIGH':
                wave_points.append({
                    'label': f'浪{wave_num}顶',
                    'date': p['date'],
                    'price': p['price'],
                    'type': 'HIGH',
                })
            elif p['type'] == 'LOW':
                if wave_num <= 5:
                    correction_num = wave_num + 1  # Wave 2 after Wave 1, Wave 4 after Wave 3
                    if correction_num > 4:
                        # After Wave 5, this is an ABC correction
                        wave_points.append({
                            'label': '调整浪A低',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'LOW',
                        })
                    else:
                        wave_points.append({
                            'label': f'浪{correction_num}底',
                            'date': p['date'],
                            'price': p['price'],
                            'type': 'LOW',
                        })
                    wave_num += 2  # Skip to next impulse (1→3→5)

        # Determine current position
        last_pivot = uptrend_pivots[-1]
        second_last = uptrend_pivots[-2] if len(uptrend_pivots) >= 2 else None

        # Count completed impulse waves
        impulse_count = sum(1 for wp in wave_points if '浪' in wp.get('label', '') and '顶' in wp.get('label', ''))
        correction_count = sum(1 for wp in wave_points if '浪' in wp.get('label', '') and '底' in wp.get('label', ''))

        position = "未知"
        upside_prob = 50
        description = ""
        detail = {}

        if impulse_count == 0:
            position = "推动浪第1浪"
            upside_prob = 55
            description = "从低点起步，推动浪第1浪进行中"
        elif impulse_count == 1 and correction_count == 0:
            # Just completed wave 1 high, still rising
            position = "推动浪第1浪"
            upside_prob = 55
            w1 = [wp for wp in wave_points if wp['label'] == '浪1顶'][0]
            start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
            pct = (w1['price'] - start['price']) / start['price'] * 100
            description = f"浪1上升中: {start['price']:.3f}({start['date']}) → {w1['price']:.3f}({w1['date']}), 涨幅{pct:+.1f}%"
        elif impulse_count == 1 and correction_count == 1:
            # Wave 1 done, Wave 2 correction done or in progress
            w2_low = [wp for wp in wave_points if wp['label'] == '浪2底']
            w1_high = [wp for wp in wave_points if wp['label'] == '浪1顶']

            if last_pivot['type'] == 'LOW' and w2_low:
                # Wave 2 completed, now in Wave 3
                position = "推动浪第3浪"
                upside_prob = 75
                start = next((wp for wp in wave_points if wp['label'] == '起点'), wave_points[0])
                h1 = w1_high[0] if w1_high else wave_points[1]
                l2 = w2_low[0]
                w1_pct = (h1['price'] - start['price']) / start['price'] * 100
                w2_pct = (l2['price'] - h1['price']) / h1['price'] * 100
                w3_pct = (current_price - l2['price']) / l2['price'] * 100
                description = (f"浪1: {start['price']:.3f}→{h1['price']:.3f}({w1_pct:+.1f}%), "
                             f"浪2: {h1['price']:.3f}→{l2['price']:.3f}({w2_pct:+.1f}%), "
                             f"浪3进行中: {l2['price']:.3f}→{current_price:.3f}({w3_pct:+.1f}%)")
                detail = {"wave1_pct": round(w1_pct, 1), "wave2_pct": round(w2_pct, 1), "wave3_pct": round(w3_pct, 1)}
            elif last_pivot['type'] == 'HIGH':
                # Still in Wave 2 or Wave 1 hasn't corrected yet
                position = "推动浪第2浪调整"
                upside_prob = 45
                description = "浪1完成后回调中，等待浪2底部确认"
        elif impulse_count >= 2 and correction_count == 1:
            # Wave 3 high reached, in Wave 4 correction
            w4_low = [wp for wp in wave_points if wp['label'] == '浪4底']
            w3_high = [wp for wp in wave_points if wp['label'] == '浪3顶']

            if last_pivot['type'] == 'LOW' and w4_low:
                # Wave 4 done, in Wave 5
                position = "推动浪第5浪"
                upside_prob = 35
                l4 = w4_low[0]
                w5_pct = (current_price - l4['price']) / l4['price'] * 100
                description = f"浪5进行中: {l4['price']:.3f}→{current_price:.3f}({w5_pct:+.1f}%)，趋势末期风险增加"
            elif last_pivot['type'] == 'HIGH' and w3_high:
                # Wave 3 high, now correcting
                position = "推动浪第4浪调整"
                upside_prob = 45
                h3 = w3_high[0]
                desc_pct = (current_price - h3['price']) / h3['price'] * 100
                description = f"浪3顶{h3['price']:.3f}后回调中，当前{current_price:.3f}({desc_pct:+.1f}%)"
            else:
                position = "推动浪第3浪"
                upside_prob = 70
                description = "浪3上升中"
        elif impulse_count >= 2 and correction_count >= 2:
            # 5-wave structure likely complete, in ABC correction
            if last_pivot['type'] == 'HIGH' and second_last and second_last['type'] == 'LOW':
                # B wave bounce
                position = "调整浪B浪反弹"
                upside_prob = 35
                description = "5浪结构完成后的B浪反弹，整体偏空"
            elif last_pivot['type'] == 'LOW':
                if impulse_count >= 3:
                    position = "调整浪"
                    upside_prob = 30
                    description = "5浪结构完成，进入ABC调整浪"
                else:
                    # Could be Wave 5 in progress
                    position = "推动浪第5浪"
                    upside_prob = 35
                    description = "浪5进行中，趋势末期"
            else:
                position = "调整浪"
                upside_prob = 35
                description = "5浪结构可能完成，进入调整"

        # Special case: current price above last HIGH pivot → still in impulse wave
        if last_pivot['type'] == 'HIGH' and current_price > last_pivot['price']:
            # Extending the last impulse wave
            if position in ("推动浪第5浪调整", "调整浪", "调整浪B浪反弹"):
                # The "last high" might have been surpassed
                if impulse_count >= 2 and correction_count >= 2:
                    # Check if this could be a new Wave 3 extension
                    position = "推动浪第3浪延伸"
                    upside_prob = 70
                    description = f"价格突破前高{last_pivot['price']:.3f}至{current_price:.3f}，浪3可能延伸"

        # Special case: current price below last LOW pivot → extending correction
        if last_pivot['type'] == 'LOW' and current_price < last_pivot['price']:
            if position in ("推动浪第2浪调整", "推动浪第4浪调整"):
                upside_prob = max(20, upside_prob - 10)
                description += "，调整加深"

        return {
            "position": position,
            "upside_prob": upside_prob,
            "wave_points": wave_points,
            "description": description,
            "detail": detail,
            "confidence": 1.0,
        }

    def _label_abc_correction(self, pivots: List[Dict[str, Any]], current_price: float,
                               abs_low: Dict, abs_high: Dict,
                               prior_trend: str = 'down') -> Dict[str, Any]:
        """
        标注ABC调整浪结构（P0 #1修复）。

        适用场景：前期有大级别下跌/上涨后的反弹/回调，
        且反弹/回调不符合推动浪特征（如浪2回撤过深、铁律违反过多）。

        Args:
            pivots: zigzag转折点
            current_price: 当前价格
            abs_low: 全局最低点
            abs_high: 全局最高点
            prior_trend: 'down' = 前期下跌后的ABC反弹, 'up' = 前期上涨后的ABC回调
        """
        is_down_prior = (prior_trend == 'down')

        # 从极值点开始选取转折点
        if is_down_prior:
            # 下跌后的ABC反弹：从最低点开始
            origin_point = abs_low
            correction_pivots = [p for p in pivots if p['idx'] >= abs_low['idx']]
        else:
            # 上涨后的ABC回调：从最高点开始
            origin_point = abs_high
            correction_pivots = [p for p in pivots if p['idx'] >= abs_high['idx']]

        if len(correction_pivots) < 4:
            return {
                "position": "数据不足" if is_down_prior else "数据不足",
                "upside_prob": 45 if is_down_prior else 55,
                "wave_points": [],
                "description": "转折点不足，无法标注ABC调整",
                "detail": {"signal": "数据不足", "abc_specific": True,
                           "prior_trend": prior_trend},
                "confidence": 0.3,
            }

        # 计算前期趋势幅度
        prior_decline_pct = 0.0
        prior_rise_pct = 0.0
        if is_down_prior and abs_high['idx'] < abs_low['idx']:
            prior_decline_pct = (abs_high['price'] - abs_low['price']) / abs_high['price'] * 100
        elif not is_down_prior and abs_low['idx'] < abs_high['idx']:
            prior_rise_pct = (abs_high['price'] - abs_low['price']) / abs_low['price'] * 100

        # A-B-C phase labeling
        wave_points = []
        # Add prior extreme as context
        context_point = abs_high if is_down_prior else abs_low
        wave_points.append({
            'label': '前高' if is_down_prior else '前低',
            'date': context_point['date'],
            'price': context_point['price'],
            'type': context_point['type'],
        })

        # Mark origin
        wave_points.append({
            'label': 'A起点',
            'date': origin_point['date'],
            'price': origin_point['price'],
            'type': origin_point['type'],
        })

        phase = 'A'
        a_top = None
        b_bottom = None

        for i, p in enumerate(correction_pivots):
            if i == 0:
                continue  # skip origin (already added)

            if phase == 'A':
                expect_type = 'HIGH' if is_down_prior else 'LOW'
                if p['type'] == expect_type:
                    label = 'A浪顶' if is_down_prior else 'A浪底'
                    wave_points.append({
                        'label': label, 'date': p['date'],
                        'price': p['price'], 'type': p['type'],
                    })
                    a_top = p
                    phase = 'B'
                # else: 同类型转折，可能是更大的A浪，继续等待反向
            elif phase == 'B':
                expect_type = 'LOW' if is_down_prior else 'HIGH'
                if p['type'] == expect_type:
                    label = 'B浪底' if is_down_prior else 'B浪顶'
                    wave_points.append({
                        'label': label, 'date': p['date'],
                        'price': p['price'], 'type': p['type'],
                    })
                    b_bottom = p
                    phase = 'C'
            elif phase == 'C':
                expect_type = 'HIGH' if is_down_prior else 'LOW'
                if p['type'] == expect_type:
                    label = 'C浪顶' if is_down_prior else 'C浪底'
                    wave_points.append({
                        'label': label, 'date': p['date'],
                        'price': p['price'], 'type': p['type'],
                    })
                    # After C, subsequent pivots may signal C extension or new structure
                    phase = 'post-C'

        # 确定ABC合理的条件:
        # 1. B浪不能超过A起点 (对于下跌后的ABC: B浪底 > A起点价)
        # 2. C浪幅度合理
        abc_valid = True
        abc_warnings = []

        if is_down_prior and b_bottom:
            if b_bottom['price'] < origin_point['price'] * 0.98:
                abc_warnings.append("B浪跌破A起点，可能不是ABC调整")
                abc_valid = False
        elif not is_down_prior and b_bottom:
            if b_bottom['price'] > origin_point['price'] * 1.02:
                abc_warnings.append("B浪升破A起点，可能不是ABC调整")
                abc_valid = False

        # C浪幅度检查
        if a_top and len([wp for wp in wave_points if 'C浪' in wp.get('label', '')]) > 0:
            c_points = [wp for wp in wave_points if 'C浪' in wp.get('label', '')]
            if c_points:
                c_extreme = c_points[-1]
                a_range = abs(a_top['price'] - origin_point['price'])
                c_range = abs(c_extreme['price'] - (b_bottom['price'] if b_bottom else origin_point['price']))
                if a_range > 0 and c_range > a_range * 2.5:
                    abc_warnings.append("C浪远超A浪2.5倍，可能非ABC而是新推动浪")

        # 计算C浪子浪细分
        c_sub = ""
        if a_top and b_bottom and len([wp for wp in wave_points if 'C浪' in wp.get('label', '')]) > 0:
            c_points = [wp for wp in wave_points if 'C浪' in wp.get('label', '')]
            a_range = abs(a_top['price'] - origin_point['price'])
            if c_points:
                c_extreme = c_points[-1]
                c_range = abs(c_extreme['price'] - (b_bottom['price'] if b_bottom else origin_point['price']))
                if a_range > 0 and c_range > a_range * 1.5:
                    c_sub = "(C浪延伸，内部可能含5浪子结构)"

        # 确定上涨概率
        if is_down_prior:
            if phase >= 'C':
                upside_prob = 40  # C浪进行中/结束，反弹后可能回落
            elif phase == 'B':
                upside_prob = 45  # B浪回调中
            else:
                upside_prob = 50  # A浪进行中
        else:
            if phase >= 'C':
                upside_prob = 60  # C浪下跌进行中/结束
            elif phase == 'B':
                upside_prob = 55
            else:
                upside_prob = 50

        # 构建position和description
        if is_down_prior:
            position = "ABC调整反弹"
            phase_desc = {
                'A': 'A浪反弹进行中',
                'B': 'B浪回调中',
                'C': f'C浪反弹{"中" if phase == "C" else "后"}{c_sub}',
                'post-C': f'C浪已结束{c_sub}',
            }.get(phase, 'ABC调整')
            description = f"前期{'下跌' + str(round(prior_decline_pct, 1)) + '%' if prior_decline_pct > 0 else '趋势'}后的ABC调整反弹，{phase_desc}"
            if abc_warnings:
                description += "（⚠️ " + "; ".join(abc_warnings) + "）"
        else:
            position = "ABC调整回调"
            phase_desc = {
                'A': 'A浪回调进行中',
                'B': 'B浪反弹中',
                'C': f'C浪回调{"中" if phase == "C" else "后"}{c_sub}',
                'post-C': f'C浪已结束{c_sub}',
            }.get(phase, 'ABC调整')
            description = f"前期{'上涨' + str(round(prior_rise_pct, 1)) + '%' if prior_rise_pct > 0 else '趋势'}后的ABC调整回调，{phase_desc}"
            if abc_warnings:
                description += "（⚠️ " + "; ".join(abc_warnings) + "）"

        # 可信度：基于ABC结构完整性
        confidence = 1.0
        if not abc_valid:
            confidence *= 0.4
        if len(abc_warnings) > 0:
            confidence *= 0.7
        if prior_decline_pct > 40 and is_down_prior:
            confidence *= 0.9  # 大跌后ABC更可信

        return {
            "position": position,
            "upside_prob": upside_prob,
            "wave_points": wave_points,
            "description": description,
            "detail": {
                "direction": "调整",
                "prior_trend": prior_trend,
                "abc_valid": abc_valid,
                "abc_warnings": abc_warnings,
                "abc_specific": True,
                "prior_decline_pct": round(prior_decline_pct, 2) if is_down_prior else 0,
                "prior_rise_pct": round(prior_rise_pct, 2) if not is_down_prior else 0,
            },
            "confidence": round(confidence, 2),
        }

    def _validate_wave_count(self, coarse: Dict[str, Any], fine: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        验证并选择最佳的浪型标注

        Elliott波浪理论三条铁律：
        1. 浪2不能超过浪1起点（100%回撤）
        2. 浪3不能是最短的推动浪（1、3、5中最短）
        3. 浪4不能进入浪1的价格区域

        如果细粒度的浪型违反铁律，而粗粒度合规，则使用粗粒度。
        如果细粒度中浪3比浪1短，则可能是延伸浪3的子浪结构。

        Args:
            coarse: 粗粒度(15%阈值)浪型标注
            fine: 细粒度(8%阈值)浪型标注
            current_price: 当前价格

        Returns:
            验证后的最佳浪型标注
        """
        def check_elliott_rules(wave_result):
            """检查Elliott铁律（使用最新规则引擎，覆盖R1/R2/R3），返回(合规, 违规描述)"""
            from .elliott_rules import (
                extract_wave_structure,
                check_R1_wave2_retracement,
                check_R2_wave3_not_shortest,
                check_R3_wave4_no_overlap_wave1,
            )

            wps = wave_result.get("wave_points", [])
            if len(wps) < 3:
                return True, ""

            try:
                ws = extract_wave_structure(wave_result)
            except Exception:
                return True, ""

            violations = []

            # R1: 浪2回撤不能超过浪1的100%（铁律）
            v = check_R1_wave2_retracement(ws)
            if v:
                violations.append(v.description)

            # R2: 浪3不能是最短的推动浪（铁律）
            v = check_R2_wave3_not_shortest(ws)
            if v:
                violations.append(v.description)

            # R3: 浪4不能进入浪1的价格区域（铁律）
            v = check_R3_wave4_no_overlap_wave1(ws)
            if v:
                violations.append(v.description)

            # 额外启发式检测：浪3明显短于浪1 → zigzag可能检测到了延伸浪的子浪
            # 这不构成铁律违反，但标记后优先使用粗粒度浪型
            origin = ws.get('起点')
            w1_top = ws.get('浪1顶')
            w2_bottom = ws.get('浪2底')
            w3_top = ws.get('浪3顶')
            if origin and w1_top and w2_bottom and w3_top:
                w1_len = abs(w1_top.price - origin.price)
                w3_len = abs(w3_top.price - w2_bottom.price)
                if w1_len > 0 and w3_len > 0 and w3_len < w1_len * 0.5:
                    violations.append(
                        f"浪3({w3_len:.3f})明显短于浪1({w1_len:.3f})，可能是延伸浪3的子浪"
                    )

            return len(violations) == 0, "; ".join(violations)

        fine_valid, fine_violations = check_elliott_rules(fine)
        coarse_valid, coarse_violations = check_elliott_rules(coarse)

        # If fine-grained has violations and coarse-grained is valid, use coarse
        if not fine_valid and coarse_valid:
            # Fine-grained may be showing sub-waves of an extended Wave 3
            result = coarse.copy()
            # Add sub-wave info from fine-grained analysis
            fine_wps = fine.get("wave_points", [])
            if fine_wps:
                sub_wave_strs = [f"{wp['label']}:{wp['price']:.3f}" for wp in fine_wps]
                result["detail"]["sub_waves"] = " → ".join(sub_wave_strs)
                result["detail"]["note"] = f"细粒度浪型违反Elliott规则({fine_violations})，已切换到粗粒度主浪结构"
            return result

        # If fine has sub-wave suspicion (浪3明显短于浪1，可能是延伸浪3的子浪)
        # This is not a hard violation but zigzag likely detected sub-waves of an extended wave.
        # Prefer coarse for the main structure, keep fine as sub-wave detail.
        if "浪3" in fine_violations and "子浪" in fine_violations:
            result = coarse.copy()
            fine_wps = fine.get("wave_points", [])
            if fine_wps:
                sub_wave_strs = [f"{wp['label']}:{wp['price']:.3f}" for wp in fine_wps]
                result["detail"]["sub_waves"] = " → ".join(sub_wave_strs)
                result["detail"]["note"] = "细粒度浪型中浪3短于浪1，可能为延伸浪3的子浪结构"
            return result

        # If coarse has significantly more structural wave points than fine,
        # fine's zigzag picked up too many minor pivots and the Elliott rule
        # validation collapsed them into a meaningless simplified structure.
        # Prefer coarse when it captures a more complete wave picture.
        # Note: mild Elliott rule violations in coarse (e.g.,浪4进入浪1区域)
        # are common in real markets and should not disqualify a structurally
        # superior wave count over a collapsed fine-grained one.
        coarse_n = len(coarse.get("wave_points", []))
        fine_n = len(fine.get("wave_points", []))
        if coarse_n >= 5 and fine_n <= 3:
            result = coarse.copy()
            result["detail"]["note"] = f"细粒度浪型仅{int(fine_n)}个节点(结构不完整)，已切换到粗粒度完整结构({int(coarse_n)}个节点)"
            return result

        # Default: use fine-grained (more detail)
        if fine_valid:
            return fine

        # Last resort: if both are invalid, return coarse (simpler = fewer violations)
        if coarse.get("wave_points"):
            return coarse

        return fine

    def _detect_wave_position(self, df: pd.DataFrame, df_weekly: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """
        检测波浪位置（基于Zigzag浪型识别 + 指标辅助修正）

        两步走：
        1. Zigzag转折点识别 → 浪型标注 → 基础上涨概率
        2. 技术指标（MA/RSI/MACD）微调概率，避免悬崖效应
        """
        latest = df.iloc[-1]
        close = float(latest['close'])
        ma20 = float(latest.get('MA20', 0))
        ma60 = float(latest.get('MA60', 0))
        rsi = float(latest.get('RSI', 50))
        macd_hist = float(latest.get('MACD_hist', 0))
        price_pos = float(latest.get('price_position', 0.5))

        # 近期趋势
        if len(df) >= 20:
            recent_close = df['close'].tail(20).values
            recent_trend = "up" if recent_close[-1] > recent_close[0] else "down"
            trend_strength = abs(recent_close[-1] - recent_close[0]) / recent_close[0] * 100
        else:
            recent_trend = "neutral"
            trend_strength = 0

        # 周线趋势
        weekly_bullish = False
        if df_weekly is not None and len(df_weekly) >= 5:
            w_latest = df_weekly.iloc[-1]
            w_close = float(w_latest['close'])
            w_ma10 = float(w_latest.get('MA20', w_close))
            weekly_bullish = w_close > w_ma10

        # === Step 1: Multi-level Zigzag wave structure detection ===
        # 限制zigzag分析窗口：日线波浪应聚焦近1-2年走势，长周期由周线大浪负责
        # 超过500条日线时只取尾部，避免跨年度点位混入日线浪型标注
        MAX_ZIGZAG_BARS = 500
        df_zigzag = df.tail(MAX_ZIGZAG_BARS) if len(df) > MAX_ZIGZAG_BARS else df
        # Use coarse threshold for major wave structure, fine for sub-waves
        pivots_fine = self._detect_zigzag(df_zigzag, threshold=0.08)
        pivots_coarse = self._detect_zigzag(df_zigzag, threshold=0.15)

        # Try coarse-grained first (major waves), then validate with Elliott rules
        wave_result_coarse = self._label_waves(pivots_coarse, close)
        wave_result_fine = self._label_waves(pivots_fine, close)

        # Validate and choose the better wave count
        wave_result = self._validate_wave_count(wave_result_coarse, wave_result_fine, close)

        base_prob = wave_result["upside_prob"]
        position = wave_result["position"]
        wave_points = wave_result.get("wave_points", [])
        description = wave_result["description"]
        detail = wave_result.get("detail", {})

        # === Step 2: Indicator-based adjustments (continuous, no cliff effects) ===
        prob_adjustment = 0.0

        # Check if this is a reversal position (different scoring rules apply)
        is_reversal = "趋势反转" in position

        # MA alignment adjustment
        if ma20 > 0 and ma60 > 0:
            ma_diff_pct = (ma20 - ma60) / ma60 * 100
            if is_reversal:
                # For reversal: MA alignment is a strong confirmation signal
                # Bullish MA (MA20 > MA60) → +5, Bearish MA → only -1 (don't kill reversal)
                ma_adj = max(-1, min(5, ma_diff_pct * 5))
                prob_adjustment += ma_adj
            else:
                # Normal: +3 for bullish, -3 for bearish, linear in between
                ma_adj = max(-3, min(3, ma_diff_pct * 3))
                prob_adjustment += ma_adj

        # Trend direction from wave analysis
        is_downtrend = detail.get("direction") == "下跌"

        # RSI adjustment
        if rsi > 60:
            if is_reversal:
                # For reversal: high RSI = momentum, not overbought → positive signal
                rsi_adj = min(3, (rsi - 60) / 25 * 3)  # +0 to +3
                prob_adjustment += rsi_adj
            else:
                # Normal: RSI > 60 is caution (potential overbought)
                rsi_adj = -(rsi - 60) / 25 * 8
                rsi_adj = max(-8, min(0, rsi_adj))
                prob_adjustment += rsi_adj
        elif rsi < 40:
            if is_reversal:
                # For reversal: low RSI means reversal just starting, room to run
                rsi_adj = (40 - rsi) / 40 * 3  # max +3
                prob_adjustment += rsi_adj
            elif is_downtrend:
                # In downtrend, oversold can persist — less bullish signal
                if rsi < 20:
                    rsi_adj = (20 - rsi) / 20 * 2
                    prob_adjustment += rsi_adj
            else:
                # In uptrend, oversold can be bullish for reversals: gradual +0 to +4
                rsi_adj = (40 - rsi) / 40 * 4
                prob_adjustment += rsi_adj

        # MACD momentum adjustment
        if macd_hist > 0:
            if is_reversal:
                macd_adj = min(4, macd_hist / close * 100 * 20)  # stronger for reversal
            else:
                macd_adj = min(2, macd_hist / close * 100 * 10)
            prob_adjustment += macd_adj
        elif macd_hist < 0:
            if is_reversal:
                macd_adj = max(-1, macd_hist / close * 100 * 5)  # less penalty for reversal
            else:
                macd_adj = max(-2, macd_hist / close * 100 * 10)
            prob_adjustment += macd_adj

        # Weekly confirmation
        if is_downtrend:
            if is_reversal:
                # For reversal: weekly bullish is strong confirmation
                if weekly_bullish:
                    prob_adjustment += 5
                else:
                    # Weekly not yet bullish — early reversal, don't penalize too much
                    prob_adjustment -= 1
            else:
                if not weekly_bullish:
                    prob_adjustment -= 3
                elif weekly_bullish:
                    prob_adjustment += 1
        else:
            if weekly_bullish and base_prob > 40:
                prob_adjustment += 3
            elif not weekly_bullish and base_prob < 50:
                prob_adjustment -= 3

        # Apply adjustment, clamped to [10, 90]
        final_prob = max(10, min(90, round(base_prob + prob_adjustment)))

        # Update description with wave structure details
        if wave_points:
            point_strs = []
            for wp in wave_points:
                point_strs.append(f"{wp['label']}:{wp['price']:.3f}({wp['date']})")
            if len(point_strs) <= 8:
                detail["wave_structure"] = " → ".join(point_strs)
            else:
                # Show last 6 points
                detail["wave_structure"] = "... → " + " → ".join(point_strs[-6:])
            detail["current_price"] = round(close, 3)

        # Build indicators dict
        indicators = {
            "close": round(close, 3),
            "ma20": round(ma20, 3),
            "ma60": round(ma60, 3),
            "rsi": round(rsi, 1),
            "macd_hist": round(macd_hist, 4),
            "price_position": round(price_pos, 2),
            "trend_strength": round(trend_strength, 1),
        }

        # Fallback: if zigzag didn't produce useful results, use indicator-only
        if position == "数据不足" or not wave_points:
            # Use the old indicator-only logic as fallback
            position, base_prob, description, detail = self._detect_wave_position_by_indicators(
                close, ma20, ma60, rsi, macd_hist, price_pos,
                ma20 > ma60, close > ma20, close > ma60,
                recent_trend, trend_strength
            )
            final_prob = max(10, min(90, round(base_prob + prob_adjustment)))

        detail.update(indicators)

        return {
            "position": position,
            "detail": detail,
            "wave_points": wave_points,
            "upside_prob": final_prob,
            "description": description,
            "indicators": indicators,
        }

    def _detect_wave_position_by_indicators(
        self, close, ma20, ma60, rsi, macd_hist, price_pos,
        ma_bullish, above_ma20, above_ma60, recent_trend, trend_strength
    ) -> Tuple[str, int, str, Dict]:
        """Fallback: indicator-only wave position detection (used when zigzag fails)."""
        position = "未知"
        upside_prob = 50
        detail = {}
        description = ""

        if ma_bullish and above_ma20 and above_ma60:
            if macd_hist > 0 and recent_trend == "up" and trend_strength > 3:
                position = "推动浪第3浪"
                upside_prob = 75
                description = f"主升浪进行中，MA多头排列+MACD红柱+趋势强度{trend_strength:.1f}%"
            elif macd_hist > 0:
                position = "推动浪第1浪/第3浪"
                upside_prob = 60
                description = "多头排列+MACD红柱，推动浪初期或中期"
            else:
                position = "推动浪调整浪"
                upside_prob = 55
                description = "多头排列但MACD绿柱，上升浪回调"
        elif not above_ma60 and not above_ma20:
            if rsi < 30:
                position = "下跌推动浪末端/超卖"
                upside_prob = 40
                description = f"RSI={rsi:.0f}超卖，空头排列，下跌推动浪末端"
            elif recent_trend == "down" and price_pos < 0.3:
                position = "下跌推动浪第3浪"
                upside_prob = 15
                description = "空头排列+趋势下行，下跌推动浪主跌段"
            elif recent_trend == "down":
                position = "下跌推动浪"
                upside_prob = 25
                description = "空头排列，下跌推动浪进行中"
            else:
                position = "调整浪"
                upside_prob = 40
                description = "空头排列，调整浪中"
        elif above_ma60 and not above_ma20:
            if rsi < 40:
                position = "调整浪末端"
                upside_prob = 55
                description = "MA60上方回调，可能是调整浪末端"
            else:
                position = "推动浪第2/4浪调整"
                upside_prob = 45
                description = "上升浪回调中"
        elif not above_ma60 and above_ma20:
            if macd_hist > 0 and recent_trend == "up":
                position = "推动浪第1浪（反转）"
                upside_prob = 55
                description = "突破MA20，推动浪第1浪可能启动"
            else:
                position = "下跌推动浪第2/4浪反弹"
                upside_prob = 35
                description = "下跌浪反弹中"
        else:
            position = "推动浪第1浪（萌芽期）"
            upside_prob = 50
            description = "上升趋势萌芽"

        return position, upside_prob, description, detail

    def _wave_score(self, wave_analysis: Dict[str, Any]) -> tuple:
        """
        根据波浪位置和上涨概率计算评分（连续渐变）

        评分公式：基于上涨概率线性插值
        - upside_prob 90 → +8
        - upside_prob 70 → +6
        - upside_prob 50 → 0
        - upside_prob 30 → -4
        - upside_prob 10 → -8

        Returns:
            (score, rationale): 评分和评分理由
        """
        prob = wave_analysis.get("upside_prob", 50)
        position = wave_analysis.get("position", "未知")

        # Continuous linear interpolation
        if prob >= 50:
            # 50 → 0, 90 → +10
            score = (prob - 50) / 40 * 10.0
        else:
            # 50 → 0, 10 → -10
            score = -(50 - prob) / 40 * 10.0

        score = round(score, 1)
        score = max(-10.0, min(10.0, score))

        # Label
        if score >= 7.5:
            label = "强烈看多"
        elif score >= 5:
            label = "看多"
        elif score >= 2.5:
            label = "偏多"
        elif score >= -1.5:
            label = "中性"
        elif score >= -4:
            label = "偏空"
        else:
            label = "看空"

        rationale = f"波浪位置「{position}」→ 上涨概率{prob}% → 评分{score:+.1f}({label})"
        return score, rationale


# 便捷函数
def run_elliott_analysis(
    webhook_url: str = "",
    index_names: Optional[List[str]] = None
) -> Dict:
    """
    便捷函数：运行艾略特波浪分析

    Args:
        webhook_url: 企业微信 Webhook URL
        index_names: 指定分析的指数列表

    Returns:
        执行结果
    """
    config = {"webhook_url": webhook_url}
    agent = ElliottWaveAgent(config)
    return agent.execute(index_names=index_names)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="艾略特波浪分析 Agent")
    parser.add_argument("--webhook", "-w", type=str, help="企业微信 Webhook URL")
    parser.add_argument("--indices", "-i", nargs="+", help="指定分析的指数列表")
    parser.add_argument("--no-push", action="store_true", help="不推送报告")
    parser.add_argument("--no-chart", action="store_true", help="不生成图表")

    args = parser.parse_args()

    config = {"webhook_url": args.webhook}
    agent = ElliottWaveAgent(config)

    result = agent.execute(
        index_names=args.indices,
        push_report=not args.no_push,
        generate_charts=not args.no_chart
    )

    print(result["message"])
