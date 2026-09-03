#!/usr/bin/env python3
"""
艾略特波浪理论完整规则引擎

包含四大类规则：
  A. 铁律 (Iron Rules)    — 违反则浪型标注无效
  B. 强指导 (Guidelines)   — 违反则置信度显著降低
  C. 弱指导 (Soft Guides)  — 用于质量评分
  D. 形态识别 (Patterns)   — 调整浪形态分类

所有规则均基于 Elliott Wave Principle (Frost & Prechter) 的标准定义。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any, Tuple
from enum import Enum


# ============================================================
# 基础数据结构
# ============================================================

class Severity(Enum):
    ERROR = "error"       # 铁律违反
    WARNING = "warning"   # 指导违反
    INFO = "info"         # 弱指导违反/提示


class RuleCategory(Enum):
    IRON = "iron_rule"
    GUIDELINE = "guideline"
    SOFT = "soft_guide"
    PATTERN = "pattern"


@dataclass
class WavePoint:
    """标准化波浪点位"""
    label: str          # e.g. "浪1顶", "浪2底", "调整A浪底"
    price: float
    date: str
    type: str           # "HIGH" or "LOW"


@dataclass
class WaveSegment:
    """波浪段 (一次推动或调整)"""
    label: str          # e.g. "浪1", "浪2", "浪3", "调整A"
    start: WavePoint
    end: WavePoint
    direction: str      # "up" or "down"
    pct_change: float   # 涨跌幅百分比，如 +15.2 或 -8.5
    is_impulse: bool    # 推动浪 or 调整浪


@dataclass
class WaveStructure:
    """
    标准化波浪结构 — 从各种输出格式中提取

    支持三种来源:
    1. 自动zigzag标注结果 (elliott_agent._label_waves 输出)
    2. 预定义场景 (DEFAULT_INDICES scenarios)
    3. ETF分析结果 (analyze_etf 输出)
    """
    source: str = ""                # e.g. "zigzag_auto", "scenario", "etf_analysis"
    wave_points: List[WavePoint] = field(default_factory=list)
    segments: List[WaveSegment] = field(default_factory=list)
    direction: str = "up"           # 整体趋势方向
    current_price: float = 0.0
    position: str = ""              # 当前波浪位置描述

    # 按标签索引的快捷访问
    _by_label: Dict[str, WavePoint] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._by_label = {wp.label: wp for wp in self.wave_points}

    def get(self, label: str) -> Optional[WavePoint]:
        return self._by_label.get(label)

    @property
    def num_impulse(self) -> int:
        """推动浪数量 (浪1~浪5)"""
        return len([wp for wp in self.wave_points
                    if '浪' in wp.label and '顶' in wp.label and '调整' not in wp.label])

    @property
    def num_correction(self) -> int:
        """调整浪数量 (浪2, 浪4)"""
        return len([wp for wp in self.wave_points
                    if '底' in wp.label and '调整' not in wp.label])

    @property
    def in_abc(self) -> bool:
        return any('调整' in wp.label for wp in self.wave_points)

    @property
    def has_5wave(self) -> bool:
        """是否至少有完整的5浪推动结构"""
        return self.num_impulse >= 3 and self.num_correction >= 2


@dataclass
class RuleViolation:
    """规则违反记录"""
    rule_id: str
    category: RuleCategory
    severity: Severity
    description: str
    detail: str = ""
    actual_value: Optional[float] = None
    expected_range: Optional[Tuple[float, float]] = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "description": self.description,
            "detail": self.detail,
            "actual_value": self.actual_value,
            "expected_range": self.expected_range,
        }


@dataclass
class ValidationReport:
    """验证报告"""
    source: str = ""
    timestamp: str = ""
    iron_rule_violations: List[RuleViolation] = field(default_factory=list)
    guideline_violations: List[RuleViolation] = field(default_factory=list)
    soft_guide_violations: List[RuleViolation] = field(default_factory=list)
    pattern_assessment: Dict[str, Any] = field(default_factory=dict)
    quality_score: int = 100  # 0-100
    summary: str = ""

    @property
    def has_iron_violations(self) -> bool:
        return len(self.iron_rule_violations) > 0

    @property
    def has_guideline_violations(self) -> bool:
        return len(self.guideline_violations) > 0

    @property
    def all_violations(self) -> List[RuleViolation]:
        return self.iron_rule_violations + self.guideline_violations + self.soft_guide_violations

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "timestamp": self.timestamp,
            "quality_score": self.quality_score,
            "iron_rule_violations": [v.to_dict() for v in self.iron_rule_violations],
            "guideline_violations": [v.to_dict() for v in self.guideline_violations],
            "soft_guide_violations": [v.to_dict() for v in self.soft_guide_violations],
            "pattern_assessment": self.pattern_assessment,
            "summary": self.summary,
        }


# ============================================================
# 波浪结构构建工具函数
# ============================================================

def _compute_segments(wave_points: List[WavePoint], current_price: float, direction: str) -> List[WaveSegment]:
    """从波浪点位构建波浪段（计算每段的涨跌幅）"""
    segments = []
    for i in range(len(wave_points) - 1):
        wp_a = wave_points[i]
        wp_b = wave_points[i + 1]

        if wp_a.price == 0:
            continue
        pct = (wp_b.price - wp_a.price) / wp_a.price * 100

        # 判断是否是推动浪
        label_a = wp_a.label
        label_b = wp_b.label
        is_impulse = (
            ('浪' in label_a and '顶' in label_a and '底' in label_b) or
            (label_a == '起点' and '顶' in label_b) or
            ('调整' not in label_a and '调整' not in label_b and
             '顶' in label_b and '底' in label_a)
        )

        # 段的方向
        if pct > 0:
            seg_dir = "up"
        elif pct < 0:
            seg_dir = "down"
        else:
            seg_dir = direction

        # 段标签
        seg_label = f"{wp_a.label}→{wp_b.label}"

        segments.append(WaveSegment(
            label=seg_label,
            start=wp_a,
            end=wp_b,
            direction=seg_dir,
            pct_change=round(pct, 2),
            is_impulse=is_impulse,
        ))

    # 最后一段：最后一个点位到当前价格
    if wave_points:
        last = wave_points[-1]
        if last.price > 0:
            final_pct = (current_price - last.price) / last.price * 100
            segments.append(WaveSegment(
                label=f"{last.label}→当前价",
                start=last,
                end=WavePoint(label="当前价", price=current_price, date="", type=""),
                direction="up" if final_pct > 0 else "down",
                pct_change=round(final_pct, 2),
                is_impulse=False,
            ))

    return segments


# 方向归一化映射表
# elliott_agent 使用中文 "上升"/"下跌"/"调整"，规则引擎内部统一用英文 "up"/"down"。
# 缺少此映射会导致所有依赖 ws.direction 的规则（R1/R3/G7/S4 等）永不触发。
_DIRECTION_MAP: Dict[str, str] = {
    "上升": "up", "上涨": "up", "上": "up", "看涨": "up", "bull": "up", "bullish": "up",
    "up": "up", "多头": "up",
    "下跌": "down", "下降": "down", "下": "down", "看跌": "down", "bear": "down", "bearish": "down",
    "down": "down", "空头": "down",
}


def _normalize_direction(raw: str, wave_points_raw: List[dict]) -> str:
    """
    将方向字段归一化为 "up" / "down"。

    1. 命中 _DIRECTION_MAP 的直接映射；
    2. 无法映射（如 "调整"/"震荡"）时，从波浪点位结构推断：
       若最后一个推动浪顶高于起点 → up，否则 → down；
    3. 兜底返回 "up"。
    """
    raw = str(raw or "").strip()
    if raw in _DIRECTION_MAP:
        return _DIRECTION_MAP[raw]

    # 结构推断：最后一个推动浪顶 vs 起点
    origin = next((p for p in wave_points_raw
                   if isinstance(p, dict) and p.get("label") == "起点"), None)
    impulse_tops = [p for p in wave_points_raw
                    if isinstance(p, dict) and "浪" in str(p.get("label", ""))
                    and "顶" in str(p.get("label", "")) and "调整" not in str(p.get("label", ""))]
    if origin is not None and impulse_tops:
        try:
            last_top_price = float(impulse_tops[-1].get("price", 0))
            origin_price = float(origin.get("price", 0))
            if origin_price > 0:
                return "up" if last_top_price >= origin_price else "down"
        except (TypeError, ValueError):
            pass
    return "up"


def extract_wave_structure(wave_result: dict, current_price: float = 0.0) -> WaveStructure:
    """
    从波浪分析结果中提取标准化 WaveStructure

    支持输入格式:
    1. elliott_agent._label_waves() 输出:
       {"position": ..., "wave_points": [...], "upside_prob": ..., "detail": {...}}
    2. elliott_agent.analyze_etf() 输出:
       {"wave_position": ..., "wave_detail": {"wave_points": [...]}, ...}
    3. 场景分析输出 (手动定义):
       {"position": ..., "wave_points": [...], ...}
    """
    # 尝试从不同路径提取 wave_points
    raw_points = wave_result.get("wave_points", [])
    if not raw_points:
        # 检查 wave_detail 或 detail 中的 wave_points
        for detail_key in ("wave_detail", "detail"):
            detail = wave_result.get(detail_key, {})
            if isinstance(detail, dict):
                raw_points = detail.get("wave_points", [])
                if raw_points:
                    break

    # 如果没有明确的wave_points，尝试从结构字符串中解析
    if not raw_points:
        for detail_key in ("wave_detail", "detail"):
            detail = wave_result.get(detail_key, {})
            if isinstance(detail, dict):
                structure_str = detail.get("wave_structure", "")
                if structure_str:
                    raw_points = _parse_structure_string(structure_str)
                    break

    # 推断方向（归一化为 up/down；elliott_agent 传入的是 "上升"/"下跌"/"调整"）
    raw_direction = ""
    for detail_key in ("detail", "wave_detail"):
        d = wave_result.get(detail_key, {})
        if isinstance(d, dict):
            dir_in_detail = d.get("direction", "")
            if dir_in_detail:
                raw_direction = dir_in_detail
                break
    direction = _normalize_direction(raw_direction, raw_points)

    # 如果当前价未提供，从wave_result中推断
    if current_price == 0.0:
        indicators = wave_result.get("indicators", {})
        if isinstance(indicators, dict):
            current_price = float(indicators.get("close", 0))

    position = wave_result.get("position", wave_result.get("wave_position", ""))

    # 转换为标准 WavePoint
    wave_points = []
    for wp in raw_points:
        if isinstance(wp, dict) and 'label' in wp and 'price' in wp:
            wave_points.append(WavePoint(
                label=wp['label'],
                price=float(wp['price']),
                date=str(wp.get('date', '')),
                type=str(wp.get('type', '')),
            ))

    structure = WaveStructure(
        source="auto",
        wave_points=wave_points,
        direction=direction,
        current_price=current_price,
        position=position,
    )

    # 计算段
    structure.segments = _compute_segments(wave_points, current_price, direction)

    return structure


def _parse_structure_string(s: str) -> List[dict]:
    """从描述字符串解析浪型结构，如 '起点:10.5(2023-01-01) → 浪1顶:12.0(2023-02-15) → ...'"""
    points = []
    parts = s.replace(" → ", "→").split("→")
    for part in parts:
        part = part.strip()
        if ":" not in part:
            continue
        label, rest = part.split(":", 1)
        label = label.strip()
        # 解析 price(date)
        import re
        m = re.match(r'([\d.]+)\(?(.*?)\)?$', rest.strip())
        if m:
            price = float(m.group(1))
            date = m.group(2) if m.group(2) else ""
            ptype = "HIGH" if "顶" in label and "底" not in label else "LOW"
            points.append({
                "label": label,
                "price": price,
                "date": date,
                "type": ptype,
            })
    return points


# ============================================================
# 工具函数：从 WaveStructure 中提取特定浪的信息
# ============================================================

def _get_impulse_tops(ws: WaveStructure) -> List[WavePoint]:
    """获取所有推动浪顶 (浪1顶, 浪3顶, 浪5顶)"""
    return [wp for wp in ws.wave_points
            if '浪' in wp.label and '顶' in wp.label and '调整' not in wp.label]


def _get_correction_bottoms(ws: WaveStructure) -> List[WavePoint]:
    """获取所有调整浪底 (浪2底, 浪4底)"""
    return [wp for wp in ws.wave_points
            if '底' in wp.label and '调整' not in wp.label]


def _get_abc_points(ws: WaveStructure) -> List[WavePoint]:
    """获取ABC调整浪的点位"""
    return [wp for wp in ws.wave_points if '调整' in wp.label]


def _get_origin(ws: WaveStructure) -> Optional[WavePoint]:
    """获取起点"""
    return ws.get('起点')


# ============================================================
# A. 铁律检查 (Iron Rules)
# ============================================================

def _looks_like_diagonal(ws: WaveStructure) -> bool:
    """
    粗判是否为【收缩斜纹浪】(楔形)。

    §6 收缩斜纹浪规则：浪4几乎总是在浪1价格区域内结束，且
    浪3比浪1短、浪4比浪2短、浪5比浪3短（通道收敛）。
    满足「浪4进浪1区 + 浪3≤浪1 + 浪4≤浪2(通道收敛)」时，更可能是
    合法斜纹浪而非无效推动浪，R3/R4 应豁免。

    注：扩散斜纹浪(浪3>浪1)不在本豁免范围，属已知限制。
    """
    w1 = ws.get('浪1顶')
    w2 = ws.get('浪2底')
    w3 = ws.get('浪3顶')
    w4 = ws.get('浪4底')
    origin = _get_origin(ws)
    if not all([w1, w2, w3, w4, origin]):
        return False

    # 必要条件：浪4已进入浪1价格区（这是 R3 本身要判定的重叠）
    if ws.direction == "down":
        overlap = w4.price > w1.price
    else:
        overlap = w4.price < w1.price
    if not overlap:
        return False

    try:
        # 收缩特征1：浪3不长于浪1
        w1_len = abs(w1.price - origin.price)
        w3_len = abs(w3.price - w2.price)
        if not (w1_len > 0 and w3_len <= w1_len):
            return False
        # 收缩特征2：浪4比浪2短 → 通道收敛
        #   上升趋势：回撤低点走高(w4底 > w2底)
        #   下降趋势：反弹高点走低(w4 < w2)
        if ws.direction == "down":
            return w4.price < w2.price
        return w4.price > w2.price
    except (TypeError, ValueError):
        return False



def check_R1_wave2_retracement(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    R1: 浪2回撤不能超过浪1的100%

    对于上升趋势：浪2底不能低于起点
    对于下降趋势：浪2顶不能高于起点
    """
    origin = _get_origin(ws)
    w1_top = ws.get('浪1顶')
    w2_bottom = ws.get('浪2底')

    if ws.direction == "up":
        if origin and w1_top and w2_bottom:
            # 浪2底 不能低于 起点
            if w2_bottom.price < origin.price:
                retrace_pct = abs(w2_bottom.price - w1_top.price) / (w1_top.price - origin.price) * 100
                return RuleViolation(
                    rule_id="R1",
                    category=RuleCategory.IRON,
                    severity=Severity.ERROR,
                    description="浪2回撤超过浪1的100%",
                    detail=f"起点={origin.price:.3f}, 浪1顶={w1_top.price:.3f}, 浪2底={w2_bottom.price:.3f} (回撤{retrace_pct:.0f}%)",
                    actual_value=retrace_pct,
                    expected_range=(0, 100),
                )
    elif ws.direction == "down":
        if origin and w1_top and w2_bottom:
            # 浪2顶 不能高于 起点
            if w2_bottom.price > origin.price:
                # In downtrend, w2_bottom is actually wave 2 top (rebound)
                retrace_pct = abs(w2_bottom.price - w1_top.price) / (origin.price - w1_top.price) * 100
                return RuleViolation(
                    rule_id="R1",
                    category=RuleCategory.IRON,
                    severity=Severity.ERROR,
                    description="浪2反弹超过浪1的100%(下跌趋势)",
                    detail=f"起点={origin.price:.3f}, 浪1底={w1_top.price:.3f}, 浪2顶={w2_bottom.price:.3f} (反弹{retrace_pct:.0f}%)",
                    actual_value=retrace_pct,
                    expected_range=(0, 100),
                )
    return None


def check_R2_wave3_not_shortest(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    R2: 浪3不能是推动浪(1,3,5)中最短的

    计算每段推动浪的长度百分比，验证浪3不是最短。
    注意：长度 = |浪顶价格 - 前一个底/起点的价格|
    """
    origin = _get_origin(ws)
    impulse_tops = _get_impulse_tops(ws)
    correction_bottoms = _get_correction_bottoms(ws)

    if len(impulse_tops) < 2:
        return None  # 尚无足够推动浪比较

    # 构建每段推动浪的长度
    wave_lengths = []  # [(wave_num, length_pct)]
    prev_low = origin.price if origin else None

    if prev_low is None:
        return None

    for i, top in enumerate(impulse_tops):
        length = abs(top.price - prev_low) / prev_low * 100 if prev_low > 0 else 0
        wave_num = 2 * i + 1  # 1, 3, 5
        wave_lengths.append((wave_num, length, top))

        # 找到下一个调整底
        expected_bottom_label = f'浪{wave_num + 1}底'
        matching = [b for b in correction_bottoms if b.label == expected_bottom_label]
        if matching:
            prev_low = matching[0].price

    if len(wave_lengths) >= 3:
        lengths = [wl[1] for wl in wave_lengths]
        w3_idx = 1  # Wave 3 is always the second impulse wave
        w3_len = wave_lengths[w3_idx][1] if w3_idx < len(wave_lengths) else 0

        if w3_len <= 0:
            return RuleViolation(
                rule_id="R2",
                category=RuleCategory.IRON,
                severity=Severity.ERROR,
                description="浪3长度非正数",
                detail=f"浪3长度={w3_len:.3f}",
                actual_value=w3_len,
                expected_range=(0.01, float('inf')),
            )
        # §6: 浪3永远不是最短的一浪 → 浪3 <= min(浪1, 浪5) 即违反（相等亦视为违反以警示等长罕见情形）
        elif w3_len <= min(lengths[0], lengths[-1]):
            return RuleViolation(
                rule_id="R2",
                category=RuleCategory.IRON,
                severity=Severity.ERROR,
                description="浪3是最短的推动浪",
                detail=f"浪1={lengths[0]:.2f}%, 浪3={w3_len:.2f}%, 浪5={lengths[-1]:.2f}%",
                actual_value=w3_len,
            )

    return None


def check_R3_wave4_no_overlap_wave1(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    R3: 浪4不能进入浪1的价格区域 (非终结楔形情况下)

    上升趋势：浪4底 >= 浪1顶
    下降趋势：浪4顶 <= 浪1底

    §6 斜纹浪中「浪4几乎总是在浪1的价格区域内结束」是合法的，
    因此先判定斜纹浪，若是则豁免。
    """
    # 斜纹浪豁免：合法斜纹浪允许浪4进入浪1区
    if _looks_like_diagonal(ws):
        return None

    w1_top = ws.get('浪1顶')
    w4_bottom = ws.get('浪4底')

    if not w1_top or not w4_bottom:
        return None  # 尚无浪4

    if ws.direction == "up":
        if w4_bottom.price < w1_top.price:
            overlap_pct = (w1_top.price - w4_bottom.price) / w1_top.price * 100
            return RuleViolation(
                rule_id="R3",
                category=RuleCategory.IRON,
                severity=Severity.ERROR,
                description="浪4底进入浪1价格区域(重叠)",
                detail=f"浪1顶={w1_top.price:.3f}, 浪4底={w4_bottom.price:.3f} (重叠{overlap_pct:.2f}%)",
                actual_value=w4_bottom.price,
                expected_range=(w1_top.price, float('inf')),
            )
    elif ws.direction == "down":
        if w4_bottom.price > w1_top.price:
            overlap_pct = (w4_bottom.price - w1_top.price) / w1_top.price * 100
            return RuleViolation(
                rule_id="R3",
                category=RuleCategory.IRON,
                severity=Severity.ERROR,
                description="浪4顶进入浪1价格区域(重叠,下跌趋势)",
                detail=f"浪1底={w1_top.price:.3f}, 浪4顶={w4_bottom.price:.3f} (重叠{overlap_pct:.2f}%)",
                actual_value=w4_bottom.price,
                expected_range=(0, w1_top.price),
            )

    return None


def check_R4_wave3_beyond_wave1(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    R4: 浪3总是运动过浪1的终点 (§6 推动浪铁律)

    上升趋势：浪3顶 > 浪1顶
    下降趋势：浪3底 < 浪1底

    斜纹浪中浪3可不超浪1终点（§6 斜纹浪：收缩斜纹浪浪3比浪1短），
    故先判定斜纹浪，若是则豁免。
    """
    # 斜纹浪豁免
    if _looks_like_diagonal(ws):
        return None

    w1 = ws.get('浪1顶')
    w3 = ws.get('浪3顶')

    if not w1 or not w3:
        return None  # 尚无浪3

    if ws.direction == "down":
        # 下降趋势：w1/w3 标签在数据模型中仍是「浪1顶/浪3顶」对应下降波的转折高点
        # 但下降趋势下推动浪向下，应比较低点。受当前数据模型限制，此处用反向逻辑。
        if w3.price >= w1.price:
            return RuleViolation(
                rule_id="R4",
                category=RuleCategory.IRON,
                severity=Severity.ERROR,
                description="浪3未超过浪1终点(下跌趋势)",
                detail=f"浪1转折点={w1.price:.3f}, 浪3转折点={w3.price:.3f}",
                actual_value=w3.price,
                expected_range=(0, w1.price),
            )
    else:
        if w3.price <= w1.price:
            return RuleViolation(
                rule_id="R4",
                category=RuleCategory.IRON,
                severity=Severity.ERROR,
                description="浪3未超过浪1终点(浪3顶≤浪1顶)",
                detail=f"浪1顶={w1.price:.3f}, 浪3顶={w3.price:.3f}",
                actual_value=w3.price,
                expected_range=(w1.price, float('inf')),
            )

    return None


# ============================================================
# B. 强指导检查 (Guidelines)
# ============================================================

# Fibonacci ratios
FIB_236 = 0.236
FIB_382 = 0.382
FIB_500 = 0.500
FIB_618 = 0.618
FIB_786 = 0.786
FIB_100 = 1.000
FIB_1618 = 1.618
FIB_2618 = 2.618


def check_G1_wave2_retracement_depth(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G1: 浪2通常回撤浪1的50%-61.8%，不应小于23.6%，不应大于78.6%
    """
    origin = _get_origin(ws)
    w1_top = ws.get('浪1顶')
    w2_bottom = ws.get('浪2底')

    if not origin or not w1_top or not w2_bottom:
        return None

    w1_len = abs(w1_top.price - origin.price)
    w2_len = abs(w1_top.price - w2_bottom.price)

    if w1_len == 0:
        return None

    retrace_ratio = w2_len / w1_len

    if retrace_ratio < FIB_236:
        return RuleViolation(
            rule_id="G1",
            category=RuleCategory.GUIDELINE,
            severity=Severity.WARNING,
            description="浪2回撤过浅(<23.6%)，可能不是完整的浪2",
            detail=f"回撤比例={retrace_ratio:.1%}，浪1长度={w1_len/w1_top.price*100:.1f}%",
            actual_value=retrace_ratio,
            expected_range=(FIB_236, FIB_786),
        )
    elif retrace_ratio > FIB_786:
        return RuleViolation(
            rule_id="G1",
            category=RuleCategory.GUIDELINE,
            severity=Severity.WARNING,
            description="浪2回撤过深(>78.6%)，接近趋势反转",
            detail=f"回撤比例={retrace_ratio:.1%}，浪1长度={w1_len/w1_top.price*100:.1f}%",
            actual_value=retrace_ratio,
            expected_range=(FIB_236, FIB_786),
        )

    return None


def check_G2_wave3_fib_extension(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G2: 浪3通常是浪1的1.618倍 (允许1.0-2.618范围)

    理想：浪3 ≈ 1.618 × 浪1
    可接受：1.0 × 浪1 ~ 2.618 × 浪1
    """
    origin = _get_origin(ws)
    w1_top = ws.get('浪1顶')
    w2_bottom = ws.get('浪2底')
    w3_top = ws.get('浪3顶')

    if not origin or not w1_top or not w2_bottom or not w3_top:
        return None

    w1_len = abs(w1_top.price - origin.price)
    w3_len = abs(w3_top.price - w2_bottom.price)

    if w1_len == 0:
        return None

    ratio = w3_len / w1_len

    if ratio < 1.0:
        return RuleViolation(
            rule_id="G2",
            category=RuleCategory.GUIDELINE,
            severity=Severity.WARNING,
            description=f"浪3不是最长的推动浪(浪3/浪1={ratio:.2f})，不符合常见模式",
            detail=f"浪1={w1_len/origin.price*100:.1f}%, 浪3={w3_len/w2_bottom.price*100:.1f}%, 比例={ratio:.2f}",
            actual_value=ratio,
            expected_range=(1.0, 2.618),
        )
    elif ratio > 2.618:
        return RuleViolation(
            rule_id="G2",
            category=RuleCategory.GUIDELINE,
            severity=Severity.WARNING,
            description=f"浪3/浪1比例过大({ratio:.2f})，可能浪1和浪3实际是一个扩展浪的不同子浪",
            detail=f"浪1={w1_len/origin.price*100:.1f}%, 浪3={w3_len/w2_bottom.price*100:.1f}%, 比例={ratio:.2f}",
            actual_value=ratio,
            expected_range=(1.0, 2.618),
        )

    return None


def check_G3_wave4_retracement_depth(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G3: 浪4通常回撤浪3的38.2%-50%

    可接受范围：23.6% - 61.8%
    """
    w2_bottom = ws.get('浪2底')
    w3_top = ws.get('浪3顶')
    w4_bottom = ws.get('浪4底')

    if not w2_bottom or not w3_top or not w4_bottom:
        return None

    w3_len = abs(w3_top.price - w2_bottom.price)
    w4_len = abs(w3_top.price - w4_bottom.price)

    if w3_len == 0:
        return None

    retrace_ratio = w4_len / w3_len

    if retrace_ratio > FIB_618:
        return RuleViolation(
            rule_id="G3",
            category=RuleCategory.GUIDELINE,
            severity=Severity.WARNING,
            description=f"浪4回撤过深({retrace_ratio:.1%})，超出常规范围",
            detail=f"浪3长度={w3_len/w2_bottom.price*100:.1f}%, 浪4回撤={retrace_ratio:.1%}",
            actual_value=retrace_ratio,
            expected_range=(FIB_236, FIB_618),
        )

    return None


def check_G4_wave5_equality(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G4: 浪5长度 ≈ 浪1长度，或 ≈ 0.618 × 净(Wave1→Wave3)

    当浪3没有延长时，浪5 ≈ 浪1
    当浪3延长时，浪5 ≈ 浪1 或 ≈ 0.618×(浪1→浪3)
    """
    origin = _get_origin(ws)
    w1_top = ws.get('浪1顶')
    w2_bottom = ws.get('浪2底')
    w3_top = ws.get('浪3顶')
    w4_bottom = ws.get('浪4底')
    w5_top = ws.get('浪5顶')

    if not origin or not w1_top or not w4_bottom or not w5_top:
        return None

    w1_len = abs(w1_top.price - origin.price)
    w5_len = abs(w5_top.price - w4_bottom.price)

    if w1_len == 0:
        return None

    ratio = w5_len / w1_len

    # 如果浪3延长，浪5通常较短
    if w2_bottom and w3_top:
        w3_len = abs(w3_top.price - w2_bottom.price)
        w3_extended = w3_len > w1_len * 1.5

        if w3_extended:
            # 浪3延长时，浪5 ≈ 浪1 或 浪5 ≈ 0.618 × net(浪1→浪3)
            net_1to3 = abs(w3_top.price - origin.price)
            if net_1to3 > 0:
                expected_w5 = net_1to3 * FIB_618
                ratio_to_net = w5_len / expected_w5 if expected_w5 > 0 else 0
                if ratio_to_net < 0.5 or ratio_to_net > 2.0:
                    return RuleViolation(
                        rule_id="G4",
                        category=RuleCategory.GUIDELINE,
                        severity=Severity.WARNING,
                        description=f"浪3延长但浪5长度偏离预期(浪5/预期={ratio_to_net:.2f})",
                        detail=f"浪1={w1_len/origin.price*100:.1f}%, 浪5={w5_len/w4_bottom.price*100:.1f}%",
                        actual_value=round(ratio_to_net, 2),
                    )

    # 浪3未延长，浪5 ≈ 浪1
    if ratio < 0.3 and ws.current_price > 0:
        return RuleViolation(
            rule_id="G4",
            category=RuleCategory.GUIDELINE,
            severity=Severity.WARNING,
            description=f"浪5长度明显短于浪1(比例={ratio:.2f})，可能的截断浪5",
            detail=f"浪1={w1_len/origin.price*100:.1f}%, 浪5={w5_len/w4_bottom.price*100:.1f}%",
            actual_value=ratio,
            expected_range=(0.618, 1.618),
        )

    return None


def check_G5_waveB_retracement_in_zigzag(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G5: 锯齿形调整浪中，B浪应回撤A浪的50%-78.6%
    """
    a_top = ws.get('调整A浪顶') or ws.get('调整A浪底')
    b_top = ws.get('调整B浪顶')
    b_bottom = ws.get('调整B浪底')

    if not b_top:
        return None

    # A浪的长度：从5浪顶到A浪底
    impulse_tops = _get_impulse_tops(ws)
    if impulse_tops:
        w5_top = impulse_tops[-1]
        a_bottom = ws.get('调整A浪底')
        if a_bottom and w5_top:
            a_len = abs(a_bottom.price - w5_top.price)
            b_len = abs(b_top.price - a_bottom.price)
            if a_len > 0:
                retrace_ratio = b_len / a_len
                if retrace_ratio > FIB_786:
                    return RuleViolation(
                        rule_id="G5",
                        category=RuleCategory.GUIDELINE,
                        severity=Severity.WARNING,
                        description=f"B浪回撤A浪过深({retrace_ratio:.1%})，可能不是锯齿形",
                        detail=f"A浪跌幅={a_len/w5_top.price*100:.1f}%, B浪反弹={b_len/a_bottom.price*100:.1f}%",
                        actual_value=retrace_ratio,
                        expected_range=(FIB_500, FIB_786),
                    )

    return None


def check_G6_waveC_equality_to_waveA(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G6: C浪 ≈ A浪 (锯齿形) 或 C浪 = 1.618×A浪 (扩展平台形)

    可接受范围：C/A ∈ [0.618, 1.618]
    """
    a_top = ws.get('调整A浪顶')
    a_bottom = ws.get('调整A浪底')
    b_top = ws.get('调整B浪顶')
    c_bottom = ws.get('调整C浪底')

    if not a_bottom or not c_bottom:
        return None

    # A浪长度
    impulse_tops = _get_impulse_tops(ws)
    w5_top = impulse_tops[-1] if impulse_tops else None

    if w5_top:
        a_len = abs(a_bottom.price - w5_top.price)
    elif a_top:
        a_len = abs(a_top.price - a_bottom.price)
    else:
        return None

    c_len = abs(c_bottom.price - (b_top.price if b_top else a_bottom.price))

    if a_len > 0:
        ratio = c_len / a_len
        if ratio < 0.5 and c_len > 0:
            return RuleViolation(
                rule_id="G6",
                category=RuleCategory.GUIDELINE,
                severity=Severity.WARNING,
                description=f"C浪明显短于A浪(比例={ratio:.2f})，可能C浪尚未完成",
                detail=f"A浪={a_len/w5_top.price*100:.1f}%, C浪={c_len/(b_top.price if b_top else 1)*100:.1f}%",
                actual_value=ratio,
                expected_range=(0.618, 1.618),
            )

    return None


def check_G7_waveB_not_exceed_waveA_origin(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G7: B浪不应超过A浪起点 (§6 锯齿形铁律：浪B永远不会运动过浪A的起点)

    说明：§6 中此条对【锯齿形】是铁律；但平台形/扩散平台形中 B 浪允许
    超过 A 浪起点(§6 平台形：浪B通常回撤浪A的100%～138%)。受当前数据模型
    限制无法 100% 确认子浪形态，故保留为「强指导」而非铁律，并对符合
    扩散平台形特征(B>A起点 且 C终点超过A终点)的结构豁免，避免误报。

    上升趋势：B浪顶超过前5浪顶(=A浪起点)
    下降趋势：B浪底超过前5浪底(=A浪起点)
    """
    impulse_tops = _get_impulse_tops(ws)
    b_top = ws.get('调整B浪顶')
    a_bottom = ws.get('调整A浪底')
    c_bottom = ws.get('调整C浪底')

    if not impulse_tops or not b_top:
        return None

    w5_top = impulse_tops[-1]  # A浪起点

    # 判定 B 是否越过 A 浪起点
    if ws.direction == "down":
        b_exceeds = b_top.price < w5_top.price
    else:
        b_exceeds = b_top.price > w5_top.price

    if not b_exceeds:
        return None  # B 未越过 A 起点，合规

    # 扩散平台形豁免：B>A起点 且 C终点超过A终点 → 合法扩散平台形(§6)
    if a_bottom and c_bottom:
        if ws.direction == "down":
            c_beyond_a = c_bottom.price > a_bottom.price
        else:
            c_beyond_a = c_bottom.price < a_bottom.price
        if c_beyond_a:
            return None  # 符合扩散平台形，B 越过 A 起点合法

    return RuleViolation(
        rule_id="G7",
        category=RuleCategory.GUIDELINE,
        severity=Severity.WARNING,
        description="B浪越过A浪起点，不可能是锯齿形(§6铁律)，应为平台形或新一轮推动浪",
        detail=f"A浪起点(5浪顶)={w5_top.price:.3f}, B浪顶={b_top.price:.3f}",
        actual_value=b_top.price,
        expected_range=(0, w5_top.price) if ws.direction != "down" else (w5_top.price, float('inf')),
    )


def check_G8_abc_retracement_depth(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    G8: 5浪推动后的ABC调整应回撤整个推动浪的38.2%-78.6%
    """
    origin = _get_origin(ws)
    impulse_tops = _get_impulse_tops(ws)
    c_bottom = ws.get('调整C浪底') or ws.get('调整A浪底')

    if not origin or len(impulse_tops) < 3 or not c_bottom:
        return None

    w5_top = impulse_tops[-1]
    total_rise = abs(w5_top.price - origin.price)
    retrace = abs(w5_top.price - c_bottom.price)

    if total_rise > 0:
        retrace_ratio = retrace / total_rise
        if retrace_ratio < FIB_382:
            return RuleViolation(
                rule_id="G8",
                category=RuleCategory.GUIDELINE,
                severity=Severity.WARNING,
                description=f"ABC调整回撤不足38.2%(仅{retrace_ratio:.1%})，调整可能尚未结束",
                detail=f"总涨幅={total_rise/origin.price*100:.1f}%, 回撤={retrace/w5_top.price*100:.1f}%",
                actual_value=retrace_ratio,
                expected_range=(FIB_382, FIB_786),
            )
        elif retrace_ratio > FIB_786:
            return RuleViolation(
                rule_id="G8",
                category=RuleCategory.GUIDELINE,
                severity=Severity.WARNING,
                description=f"ABC调整回撤超过78.6%({retrace_ratio:.1%})，可能趋势已反转",
                detail=f"总涨幅={total_rise/origin.price*100:.1f}%, 回撤={retrace/w5_top.price*100:.1f}%",
                actual_value=retrace_ratio,
                expected_range=(FIB_382, FIB_786),
            )

    return None


# ============================================================
# C. 弱指导检查 (Soft Guidelines)
# ============================================================

def check_S1_alternation(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    S1: 交替规则 — 浪2和浪4的形态应该不同

    如果浪2是急跌(sharp)，浪4应该是横盘(sideways)
    如果浪2是横盘，浪4应该是急跌

    简化判断：
    - 急跌：持续时间短，回撤幅度深(>50%)
    - 横盘：持续时间长，回撤幅度浅(<38.2%)
    """
    w1_top = ws.get('浪1顶')
    w2_bottom = ws.get('浪2底')
    w3_top = ws.get('浪3顶')
    w4_bottom = ws.get('浪4底')

    if not w1_top or not w2_bottom or not w3_top or not w4_bottom:
        return None

    # 浪2特征
    w2_retrace = abs(w1_top.price - w2_bottom.price) / abs(w1_top.price - (_get_origin(ws).price if _get_origin(ws) else 1)) if _get_origin(ws) else 0
    w2_is_sharp = w2_retrace > 0.5

    # 浪4特征
    w3_len = abs(w3_top.price - w2_bottom.price)
    w4_retrace = abs(w3_top.price - w4_bottom.price) / w3_len if w3_len > 0 else 0
    w4_is_sharp = w4_retrace > 0.5

    if w2_is_sharp == w4_is_sharp and ws.num_impulse >= 2:
        # 两者相同类型 — 可能违反交替规则
        wave2_type = "急跌" if w2_is_sharp else "横盘"
        wave4_type = "急跌" if w4_is_sharp else "横盘"
        return RuleViolation(
            rule_id="S1",
            category=RuleCategory.SOFT,
            severity=Severity.INFO,
            description=f"浪2和浪4形态相似(都是{wave2_type})，可能违反交替规则",
            detail=f"浪2回撤={w2_retrace:.1%}, 浪4回撤={w4_retrace:.1%}",
            actual_value=abs(w2_retrace - w4_retrace),
        )

    return None


def check_S2_channeling(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    S2: 通道规则 — 推动浪应沿平行通道运行

    简化检查：浪1底→浪3顶连线 和 浪1顶→浪4底连线 应大致平行。
    当前仅检查浪4底是否在由(起点, 浪2底)和(浪1顶, 浪3顶)构成的通道内。
    """
    origin = _get_origin(ws)
    w1_top = ws.get('浪1顶')
    w2_bottom = ws.get('浪2底')
    w3_top = ws.get('浪3顶')
    w4_bottom = ws.get('浪4底')

    if not origin or not w1_top or not w2_bottom or not w3_top or not w4_bottom:
        return None

    # 检查浪4底是否在预期的通道下轨附近
    # 连接浪2底和浪4底的线应该平行于连接起点和浪3顶的线
    # 简化：计算两个斜率
    slope_13 = (w3_top.price - origin.price) / (3) if w3_top.price > origin.price else 0  # 粗算
    slope_24 = (w4_bottom.price - w2_bottom.price) / (2) if w4_bottom.price > w2_bottom.price else 0

    if slope_13 > 0 and slope_24 > 0:
        ratio = slope_24 / slope_13
        if ratio < 0.3 or ratio > 3.0:
            return RuleViolation(
                rule_id="S2",
                category=RuleCategory.SOFT,
                severity=Severity.INFO,
                description=f"通道斜率不匹配(比例={ratio:.2f})，浪4可能不在预期通道内",
                actual_value=ratio,
            )

    return None


def check_S3_at_least_one_extended(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    S3: 推动浪中至少应有一浪延长 (长度明显大于其他浪)

    注意：这不是铁律，但极少数情况下三条推动浪等长。
    延长判断：某浪长度 > 其他两浪平均值的 1.5 倍
    """
    origin = _get_origin(ws)
    impulse_tops = _get_impulse_tops(ws)
    correction_bottoms = _get_correction_bottoms(ws)

    if len(impulse_tops) < 3 or not origin:
        return None

    # 计算三浪长度
    prev = origin.price
    lengths = []
    for i, top in enumerate(impulse_tops[:3]):
        w_len = abs(top.price - prev) / prev * 100 if prev > 0 else 0
        lengths.append(w_len)
        # 下一个修正底
        matching = [b for b in correction_bottoms if '底' in b.label and str(2*i+2) in b.label]
        if matching:
            prev = matching[0].price

    if len(lengths) < 3:
        return None

    avg_len = sum(lengths) / len(lengths)
    max_len = max(lengths)
    min_len = min(lengths)
    max_wave_idx = lengths.index(max_len) * 2 + 1  # 1, 3, 5

    # §6 铁律：浪1、3和5不会都是延长浪 — 三浪近乎等长(彼此差异<20%)即疑似同时延长
    if min_len > 0 and max_len / min_len < 1.2:
        return RuleViolation(
            rule_id="S3",
            category=RuleCategory.SOFT,
            severity=Severity.INFO,
            description=f"三浪近乎等长(max/min={max_len/min_len:.2f})，违反§6「浪1/3/5不会都延长」",
            detail=f"浪长: {', '.join(f'({2*i+1}){l:.2f}%' for i, l in enumerate(lengths))}",
            actual_value=round(max_len / min_len, 2),
        )

    if max_len < avg_len * 1.3:
        return RuleViolation(
            rule_id="S3",
            category=RuleCategory.SOFT,
            severity=Severity.INFO,
            description=f"推动浪没有明显延长(最长浪{max_wave_idx}仅超出均值{max_len/avg_len:.2f}倍)",
            detail=f"浪长: {', '.join(f'({2*i+1}){l:.2f}%' for i, l in enumerate(lengths))}",
            actual_value=max_len / avg_len if avg_len > 0 else 1.0,
        )

    return None


def check_S4_wave4_no_overlap_wave2(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    S4: 浪4不应回撤进入浪2的价格区域 (更强的区域约束)

    上升趋势：浪4底不应低于浪2顶
    下降趋势：浪4顶不应高于浪2底
    """
    w2_top = ws.get('浪2顶')
    w2_bottom = ws.get('浪2底')
    w4_bottom = ws.get('浪4底')

    if not w4_bottom:
        return None

    if ws.direction == "up" and w2_top:
        if w4_bottom.price < w2_top.price:
            return RuleViolation(
                rule_id="S4",
                category=RuleCategory.SOFT,
                severity=Severity.INFO,
                description=f"浪4底({w4_bottom.price:.3f})低于浪2顶({w2_top.price:.3f})，进入浪2区域",
                detail="这在常规推动浪中不常见，可能暗示楔形/三角形形态",
            )
    elif ws.direction == "down" and w2_bottom:
        if w4_bottom.price > w2_bottom.price:
            return RuleViolation(
                rule_id="S4",
                category=RuleCategory.SOFT,
                severity=Severity.INFO,
                description=f"浪4顶({w4_bottom.price:.3f})高于浪2底({w2_bottom.price:.3f})，进入浪2区域",
                detail="这在常规推动浪中不常见，可能暗示楔形/三角形形态",
            )

    return None


def check_S5_correction_not_impulsive(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    S5: 调整浪不应呈现5浪推动结构

    如果ABC段出现了类似5浪推动的价格结构，
    可能意味着调整尚未结束或趋势已反转。

    检查：ABC段内是否有明显的5个子浪 (检查wave_points中的子浪标签)
    """
    abc_points = _get_abc_points(ws)

    if len(abc_points) >= 5:
        return RuleViolation(
            rule_id="S5",
            category=RuleCategory.SOFT,
            severity=Severity.INFO,
            description=f"ABC调整段有{len(abc_points)}个转折点(疑似5浪结构)",
            detail="调整浪通常为3浪结构(A-B-C)，5浪结构可能意味着趋势反转或调整尚未完成",
        )

    return None


def check_S6_completeness(ws: WaveStructure) -> Optional[RuleViolation]:
    """
    S6: 波浪结构完整性检查

    如果浪型标注不完整（例如只有浪1顶没有浪2底），
    则浪型推断可能不准确。
    """
    issues = []

    if ws.get('浪1顶') and not ws.get('浪2底'):
        issues.append("有浪1顶但无浪2底")
    if ws.get('浪3顶') and not ws.get('浪4底') and ws.num_impulse >= 2:
        issues.append("有浪3顶但无浪4底")

    if issues:
        return RuleViolation(
            rule_id="S6",
            category=RuleCategory.SOFT,
            severity=Severity.INFO,
            description="浪型结构不完整: " + "; ".join(issues),
            detail="不完整的浪型标注可能导致误判当前位置",
        )

    return None


# ============================================================
# D. 形态识别
# ============================================================

def classify_pattern(ws: WaveStructure) -> Dict[str, Any]:
    """
    识别当前波浪形态

    根据wave_points的结构特征分类：
    - impulse_5wave: 标准5浪推动
    - zigzag: 锯齿形调整 (5-3-5)
    - flat: 平台形调整 (3-3-5)
    - triangle: 三角形调整
    - diagonal: 终结楔形
    - unknown: 无法识别
    """
    n_impulse = ws.num_impulse
    n_correction = ws.num_correction
    in_abc = ws.in_abc
    abc_points = _get_abc_points(ws)

    result = {
        "pattern": "unknown",
        "confidence": 0.0,
        "alternative": [],
        "notes": [],
    }

    # Check for 5-wave impulse
    if n_impulse >= 3 and n_correction >= 2 and not in_abc:
        result["pattern"] = "5浪推动"
        result["confidence"] = 0.85 if n_impulse >= 3 else 0.6
        result["notes"].append(f"识别为{n_impulse}波推动结构")

        # Check for diagonal
        w1_top = ws.get('浪1顶')
        w4_bottom = ws.get('浪4底')
        if w1_top and w4_bottom:
            if ws.direction == "up" and w4_bottom.price < w1_top.price:
                result["pattern"] = "终结楔形(diagonal)"
                result["confidence"] = 0.7
                result["notes"].append("浪4进入浪1区域，符合终结楔形特征")

    # Check for ABC correction
    if in_abc and abc_points:
        a_bottom = ws.get('调整A浪底')
        b_top = ws.get('调整B浪顶')
        c_bottom = ws.get('调整C浪底')

        if a_bottom:
            # Determine if zigzag or flat
            impulse_tops = _get_impulse_tops(ws)
            if impulse_tops:
                w5_top = impulse_tops[-1]
                a_decline = abs(a_bottom.price - w5_top.price) / w5_top.price * 100 if w5_top.price > 0 else 0

                if a_decline > 10:
                    result["pattern"] = "锯齿形调整(zigzag)"
                    result["confidence"] = 0.7
                    result["notes"].append(f"A浪跌幅{a_decline:.1f}%，形态较陡")
                else:
                    result["pattern"] = "平台形调整(flat)"
                    result["confidence"] = 0.6
                    result["notes"].append(f"A浪跌幅{a_decline:.1f}%，较为温和")

                if b_top:
                    b_retrace = abs(b_top.price - a_bottom.price) / abs(w5_top.price - a_bottom.price) * 100 if a_bottom.price != w5_top.price else 0
                    if b_retrace > 90:
                        result["pattern"] = "不规则平台形(irregular flat)"
                        result["confidence"] = 0.65
                        result["notes"].append(f"B浪回撤{b_retrace:.0f}%，接近A浪起点")

        if c_bottom and b_top:
            c_len = abs(c_bottom.price - b_top.price)
            a_len = abs(a_bottom.price - w5_top.price) if impulse_tops and a_bottom else 0
            if a_len > 0:
                c_a_ratio = c_len / a_len
                if c_a_ratio > 1.618:
                    result["notes"].append(f"C浪延长(C/A={c_a_ratio:.2f})")

    # Only 1-2 impulse waves → early stage
    if n_impulse <= 2 and n_correction <= 1 and not in_abc:
        result["pattern"] = "推动浪早期"
        result["confidence"] = 0.4
        result["notes"].append("浪型结构尚在发展初期，需更多数据确认")

    return result


# ============================================================
# 规则注册表
# ============================================================

# 铁律检查列表
IRON_RULES: List[Tuple[str, Callable]] = [
    ("R1", check_R1_wave2_retracement),
    ("R2", check_R2_wave3_not_shortest),
    ("R3", check_R3_wave4_no_overlap_wave1),
    ("R4", check_R4_wave3_beyond_wave1),
]

# 强指导检查列表
GUIDELINES: List[Tuple[str, Callable]] = [
    ("G1", check_G1_wave2_retracement_depth),
    ("G2", check_G2_wave3_fib_extension),
    ("G3", check_G3_wave4_retracement_depth),
    ("G4", check_G4_wave5_equality),
    ("G5", check_G5_waveB_retracement_in_zigzag),
    ("G6", check_G6_waveC_equality_to_waveA),
    ("G7", check_G7_waveB_not_exceed_waveA_origin),
    ("G8", check_G8_abc_retracement_depth),
]

# 弱指导检查列表
SOFT_GUIDES: List[Tuple[str, Callable]] = [
    ("S1", check_S1_alternation),
    ("S2", check_S2_channeling),
    ("S3", check_S3_at_least_one_extended),
    ("S4", check_S4_wave4_no_overlap_wave2),
    ("S5", check_S5_correction_not_impulsive),
    ("S6", check_S6_completeness),
]

# 所有规则说明
ALL_RULES_INFO = {
    # --- Iron Rules ---
    "R1": {"name": "浪2回撤限制", "category": "iron_rule",
           "description": "浪2回撤不能超过浪1的100%。在上升趋势中，浪2底不能低于起点；在下降趋势中，浪2顶不能高于起点。"},
    "R2": {"name": "浪3非最短", "category": "iron_rule",
           "description": "浪3不能是推动浪(1、3、5)中最短的一浪。浪3通常是最长的推动浪。"},
    "R3": {"name": "浪4不重叠浪1", "category": "iron_rule",
           "description": "浪4不能进入浪1的价格区域。上升趋势中浪4底>=浪1顶，下降趋势中浪4顶<=浪1底。终结楔形除外。"},
    "R4": {"name": "浪3超过浪1终点", "category": "iron_rule",
           "description": "浪3总是运动过浪1的终点。上升趋势中浪3顶>浪1顶，下降趋势中浪3底<浪1底。斜纹浪除外。"},

    # --- Strong Guidelines ---
    "G1": {"name": "浪2回撤深度", "category": "guideline",
           "description": "浪2通常回撤浪1的50%-61.8%，回撤过浅(<23.6%)或过深(>78.6%)应警惕。"},
    "G2": {"name": "浪3斐波那契延伸", "category": "guideline",
           "description": "浪3通常是浪1的1.618倍。可接受范围1.0~2.618倍。"},
    "G3": {"name": "浪4回撤深度", "category": "guideline",
           "description": "浪4通常回撤浪3的38.2%-50%，不应超过61.8%。"},
    "G4": {"name": "浪5长度关系", "category": "guideline",
           "description": "浪3未延长时浪5≈浪1；浪3延长时浪5≈浪1或≈0.618×净(浪1→浪3)。"},
    "G5": {"name": "锯齿形B浪回撤", "category": "guideline",
           "description": "锯齿形调整中，B浪回撤A浪的50%-78.6%。"},
    "G6": {"name": "C浪=A浪关系", "category": "guideline",
           "description": "C浪长度≈A浪(锯齿形)，或C浪=1.618×A浪(扩展平台形)，范围[0.618, 1.618]。"},
    "G7": {"name": "B浪不超A浪起点", "category": "guideline",
           "description": "§6锯齿形铁律：浪B永远不会运动过浪A的起点。B浪越过A起点→不可能是锯齿形(应为平台形/扩散平台形或新推动浪)。扩散平台形(B>A起点且C超A终点)豁免。"},
    "G8": {"name": "ABC回撤深度", "category": "guideline",
           "description": "5浪推动后的ABC调整应回撤整个推动浪的38.2%-78.6%。"},

    # --- Soft Guidelines ---
    "S1": {"name": "交替规则", "category": "soft_guide",
           "description": "浪2和浪4的形态应不同(急跌↔横盘)，以符合交替原则。"},
    "S2": {"name": "通道规则", "category": "soft_guide",
           "description": "推动浪应沿平行通道运行，浪4底应在预期通道下轨附近。"},
    "S3": {"name": "延长浪检查", "category": "soft_guide",
           "description": "推动浪中至少应有一浪延长(明显长于其他浪)。"},
    "S4": {"name": "浪4不重叠浪2", "category": "soft_guide",
           "description": "浪4不应回撤进入浪2的价格区域，否则暗示楔形/三角形。"},
    "S5": {"name": "调整浪结构检查", "category": "soft_guide",
           "description": "调整浪不应呈现5浪推动结构(锯齿形的A和C除外)。"},
    "S6": {"name": "结构完整性", "category": "soft_guide",
           "description": "浪型标注应完整(有浪顶应有对应的浪底)。"},
}
