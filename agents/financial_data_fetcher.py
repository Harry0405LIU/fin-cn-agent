#!/usr/bin/env python3
"""
Financial Data Fetcher - 财报和基本面数据获取模块
"""

import akshare as ak
import pandas as pd
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class FinancialDataFetcher:
    """财务数据获取器 - 支持三维评分（好公司/趋势/估值）"""

    def __init__(self):
        """初始化财务数据获取器"""
        self.hk_spot_cache = None
        self.a_share_list_cache = None  # A股列表缓存
        self.dividend_cache = {}  # 股息率缓存
        self.cape_cache = {}  # CAPE缓存
        # 港股历史财报多源缓存（实例级，避免 557 股批处理内重复请求）
        self.hk_indicator_cache = {}  # code -> stock_financial_hk_analysis_indicator_em DataFrame
        self.hk_report_cache = {}     # code -> {"cf": df, "inc": df, "bs": df}
        self.hk_dividend_cache = {}   # code -> stock_hk_fhpx_detail_ths DataFrame

    def _call_akshare_with_retry(self, func, max_retries: int = 3, delay: float = 2.0, **kwargs):
        """调用akshare API，带重试机制

        Args:
            func: akshare函数
            max_retries: 最大重试次数
            delay: 重试间隔(秒)，每次重试递增
            **kwargs: 传给akshare函数的参数

        可重试的错误:
            - akshare返回None（上游数据不可用/限流）
            - JSONDecodeError / Expecting value（API空响应/限流）
            - NoneType / TypeError（akshare内部对None数据操作）
            - ConnectionError（网络问题）
        """
        retryable_keywords = [
            "Expecting value", "JSONDecodeError",  # API空响应
            "NoneType",  # akshare内部None数据
            "Connection aborted", "RemoteDisconnected",  # 网络问题
            "timed out", "Timeout",  # 超时
        ]

        for attempt in range(max_retries):
            try:
                df = func(**kwargs)
                if df is not None:
                    return df
                # akshare返回None，可能是限流，等待后重试
                if attempt < max_retries - 1:
                    wait = delay * (attempt + 1)
                    print(f"  akshare返回None，{wait}秒后重试 ({attempt+1}/{max_retries})...")
                    time.sleep(wait)
            except Exception as e:
                error_msg = str(e)
                is_retryable = any(kw in error_msg for kw in retryable_keywords)
                if is_retryable and attempt < max_retries - 1:
                    wait = delay * (attempt + 1)
                    print(f"  API错误[{type(e).__name__}]，{wait}秒后重试 ({attempt+1}/{max_retries}): {error_msg[:80]}")
                    time.sleep(wait)
                else:
                    raise
        return None

    def get_stock_financial_data(
        self,
        stock_code: str,
        stock_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取股票的财务数据和基本面信息

        Args:
            stock_code: 股票代码（如 '000001' 或 'sh000001' 或 '9988.HK'）
            stock_name: 股票名称（可选）

        Returns:
            包含财务数据的字典
        """
        # 标准化股票代码
        code, is_hk = self._normalize_code(stock_code)

        financial_data = {
            "stock_code": code,
            "is_hk_stock": is_hk,
            "stock_name": stock_name,
            "fetch_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "income_statement": {},
            "balance_sheet": {},
            "cash_flow": {},
            "key_metrics": {},
            "business_overview": "",
            "recent_news": []
        }

        try:
            # 获取股票基本信息
            if stock_name is None:
                stock_name = self._get_stock_name(code, is_hk)
                # 如果获取不到名称，使用股票代码作为备用
                if stock_name is None or stock_name == "":
                    stock_name = code
            financial_data["stock_name"] = stock_name

            # 根据市场类型获取数据
            if is_hk:
                # 港股数据获取
                self._get_hk_financial_data(code, financial_data)
            else:
                # A股数据获取
                self._get_a_share_financial_data(code, financial_data)

        except Exception as e:
            print(f"获取财务数据时出错: {e}")
            financial_data["error"] = str(e)

        return financial_data

    def _normalize_code(self, stock_code: str) -> tuple[str, bool]:
        """
        标准化股票代码，并判断是否为港股

        Returns:
            (标准化后的代码, 是否为港股)
        """
        # 判断是否为港股
        is_hk = ".HK" in stock_code.upper() or len(stock_code.replace(".", "").replace("-", "")) == 5

        # 移除前缀和后缀（注意：先替换带点的后缀，避免残留点号）
        code = (stock_code.replace(".SH", "")
                      .replace(".SZ", "")
                      .replace(".BJ", "")
                      .replace(".HK", "")
                      .replace(".sh", "")
                      .replace(".sz", "")
                      .replace(".bj", "")
                      .replace(".hk", "")
                      .replace("sh", "")
                      .replace("sz", "")
                      .replace("SH", "")
                      .replace("SZ", "")
                      .replace("-", ""))

        # 港股代码补零到5位
        if is_hk and len(code) <= 5:
            code = code.zfill(5)

        return code, is_hk

    def _get_stock_name(self, code: str, is_hk: bool) -> Optional[str]:
        """获取股票名称"""
        if is_hk:
            return self._get_hk_stock_name(code)
        else:
            return self._get_a_share_stock_name(code)

    def _get_hk_stock_name(self, code: str) -> Optional[str]:
        """获取港股股票名称"""
        try:
            # 获取港股实时行情数据
            if self.hk_spot_cache is None:
                self.hk_spot_cache = self._call_akshare_with_retry(ak.stock_hk_spot)
                if self.hk_spot_cache is None:
                    self.hk_spot_cache = pd.DataFrame()

            # 查找对应股票
            if self.hk_spot_cache.empty:
                return None
            stock_row = self.hk_spot_cache[self.hk_spot_cache['symbol'] == code]
            if not stock_row.empty:
                return stock_row.iloc[0]['name']
        except Exception as e:
            print(f"获取港股名称失败: {e}")
        return None

    def _get_a_share_stock_name(self, code: str) -> Optional[str]:
        """获取A股股票名称"""
        # 方法1: 从股票列表缓存中查找（最可靠）
        try:
            if self.a_share_list_cache is None:
                print("  加载A股列表...")
                self.a_share_list_cache = self._call_akshare_with_retry(ak.stock_info_a_code_name)
                if self.a_share_list_cache is None:
                    self.a_share_list_cache = pd.DataFrame()

            if not self.a_share_list_cache.empty:
                matches = self.a_share_list_cache[self.a_share_list_cache['code'] == code]
                if not matches.empty:
                    return matches.iloc[0]['name']
        except Exception as e:
            print(f"从A股列表获取名称失败: {e}")

        return None

    def _get_hk_financial_data(self, code: str, financial_data: Dict[str, Any]):
        """获取港股财务数据"""
        # 获取实时行情数据作为基础数据
        try:
            if self.hk_spot_cache is None:
                self.hk_spot_cache = self._call_akshare_with_retry(ak.stock_hk_spot)
                if self.hk_spot_cache is None:
                    self.hk_spot_cache = pd.DataFrame()

            if self.hk_spot_cache.empty:
                return
            stock_row = self.hk_spot_cache[self.hk_spot_cache['symbol'] == code]
            if not stock_row.empty:
                row = stock_row.iloc[0]
                financial_data["key_metrics"] = {
                    "股票代码": row.get('symbol', code),
                    "股票名称": row.get('name', ''),
                    "英文名称": row.get('engname', ''),
                    "最新价": f"{row.get('lasttrade', 0):.2f}" if row.get('lasttrade') else 'N/A',
                    "昨收价": f"{row.get('prevclose', 0):.2f}" if row.get('prevclose') else 'N/A',
                    "开盘价": f"{row.get('open', 0):.2f}" if row.get('open') else 'N/A',
                    "最高价": f"{row.get('high', 0):.2f}" if row.get('high') else 'N/A',
                    "最低价": f"{row.get('low', 0):.2f}" if row.get('low') else 'N/A',
                    "成交量": f"{row.get('volume', 0):,.0f}" if row.get('volume') else 'N/A',
                    "成交额": f"{row.get('amount', 0):,.2f}" if row.get('amount') else 'N/A',
                    "涨跌额": f"{row.get('pricechange', 0):.2f}" if row.get('pricechange') else 'N/A',
                    "涨跌幅": f"{row.get('changepercent', 0):.2f}%" if row.get('changepercent') is not None else 'N/A',
                    "交易类型": row.get('tradetype', ''),
                    "更新时间": row.get('ticktime', ''),
                }

            # 获取港股历史数据
            try:
                hist_df = self._call_akshare_with_retry(ak.stock_hk_hist, symbol=code, period="daily", start_date="20230101", adjust="qfq")
                if hist_df is None:
                    print(f"获取港股历史数据: akshare返回None (code={code})")
                elif not hist_df.empty:
                    latest = hist_df.iloc[0]
                    financial_data["key_metrics"].update({
                        "市盈率": f"{latest.get('pe', 0):.2f}" if latest.get('pe') else 'N/A',
                        "市净率": f"{latest.get('pb', 0):.2f}" if latest.get('pb') else 'N/A',
                        "总市值": f"{latest.get('total_market_cap', 0):,.0f}" if latest.get('total_market_cap') else 'N/A',
                        "流通市值": f"{latest.get('circulating_market_cap', 0):,.0f}" if latest.get('circulating_market_cap') else 'N/A',
                    })
            except Exception as e:
                print(f"获取港股历史数据失败: {e}")

        except Exception as e:
            print(f"获取港股基础数据失败: {e}")

        # 尝试获取港股财报数据
        try:
            report_df = self._call_akshare_with_retry(
                ak.stock_financial_hk_report_em,
                stock=code, symbol="利润表", indicator="年度",
            )
            if report_df is None:
                print(f"获取港股财报: akshare返回None (code={code})")
            elif not report_df.empty:
                rev_by_year = self._pivot_hk_report(report_df, ["营业额", "营业收入", "营业总收入"], 1)
                np_by_year = self._pivot_hk_report(report_df, [
                    "股东应占溢利", "除税后溢利", "净利润",
                    "归属于母公司股东的净利润", "母公司股东享有的净利润",
                ], 1)
                financial_data["income_statement"] = {
                    "报告期": str(next(iter(rev_by_year.keys()), "") or next(iter(np_by_year.keys()), "") or "N/A"),
                    "营业收入": self._format_number(next(iter(rev_by_year.values()), None)),
                    "净利润": self._format_number(next(iter(np_by_year.values()), None)),
                }

                financial_data["business_overview"] = f"""
**港股 {code} 基础信息**

这是一个港股市场的股票。港股的财务数据结构与A股有所不同，目前提供的主要是：
- 实时行情数据
- 基本面指标（PE、PB等）
- 部分财报数据

如需更详细的财务分析，建议参考：
1. 香港交易所披露易
2. 公司官网的投资者关系页面
3. 专业金融数据终端
"""

        except Exception as e:
            print(f"获取港股财报数据失败: {e}")

    def _get_a_share_financial_data(self, code: str, financial_data: Dict[str, Any]):
        """获取A股财务数据 — 仅使用 stock_financial_abstract (最稳定的接口)"""
        abstract_data = self._get_financial_abstract_enriched(code)

        if abstract_data and "error" not in abstract_data:
            # 利润表数据
            financial_data["income_statement"] = abstract_data.get("income_statement", {})
            # 关键指标（ROE, EPS, ROA等）
            financial_data["key_metrics"].update(abstract_data.get("key_metrics", {}))
            # 资产负债表数据
            financial_data["balance_sheet"] = abstract_data.get("balance_sheet", {})
            # 现金流量表数据
            financial_data["cash_flow"] = abstract_data.get("cash_flow", {})

            if not financial_data["income_statement"] and not financial_data["key_metrics"]:
                print(f"  stock_financial_abstract 返回空数据 (code={code})，跳过")
        else:
            print(f"  stock_financial_abstract 不可用 (code={code})，跳过财务数据")

        # 获取业务概述
        overview = self._get_business_overview(code)
        if overview and overview != "无法获取业务概述信息":
            if financial_data.get("business_overview"):
                financial_data["business_overview"] += "\n\n" + overview
            else:
                financial_data["business_overview"] = overview

    def _get_financial_abstract_enriched(self, code: str) -> Dict[str, Any]:
        """从 stock_financial_abstract 提取完整的财务报表数据

        利用 stock_financial_abstract 提供的 80+ 指标（覆盖利润表、资产负债表、
        现金流量表、关键比率），完全替代已损坏的 _em 系列 API。
        """
        result = {}
        try:
            df = self._call_akshare_with_retry(ak.stock_financial_abstract, symbol=code)

            if df is None or df.empty or len(df.columns) < 3:
                print(f"  财务摘要: 无数据 (code={code})")
                return result

            # 最新报告期在第3列
            latest_col = df.columns[2]
            # 去年同期列(往前推4个季度)
            all_cols = list(df.columns[2:])  # 所有日期列

            def _get_val(indicator: str, col: str = None) -> float:
                """从DataFrame提取指定指标的值"""
                col = col or latest_col
                row = df[df["指标"] == indicator]
                if not row.empty:
                    val = row.iloc[0].get(col)
                    if pd.notna(val):
                        return float(val)
                return None

            def _fmt_num(val) -> str:
                if val is None: return "N/A"
                if abs(val) >= 1e8: return f"{val/1e8:.2f}亿"
                if abs(val) >= 1e4: return f"{val/1e4:.2f}万"
                return f"{val:.2f}"

            def _fmt_pct(val) -> str:
                if val is None: return "N/A"
                return f"{val:.2f}%"

            # === 利润表 ===
            income_statement = {}
            for k, label in [("营业总收入", "营业收入"), ("营业成本", "营业成本"),
                             ("净利润", "净利润"), ("归母净利润", "归母净利润"),
                             ("扣非净利润", "扣非净利润")]:
                v = _get_val(k)
                if v is not None:
                    income_statement[label] = _fmt_num(v)

            # 计算毛利率、净利率
            rev = _get_val("营业总收入")
            cost = _get_val("营业成本")
            profit = _get_val("净利润")
            if rev and rev > 0:
                if cost is not None:
                    income_statement["毛利率"] = _fmt_pct((rev - cost) / rev * 100)
                if profit is not None:
                    income_statement["净利率"] = _fmt_pct(profit / rev * 100)

            # === 关键指标 ===
            key_metrics = {}
            for k, label in [("净资产收益率(ROE)", "ROE"), ("总资产报酬率(ROA)", "ROA"),
                             ("基本每股收益", "每股收益"), ("每股净资产", "每股净资产"),
                             ("资产负债率", "资产负债率"), ("销售毛利率", "毛利率TTM"),
                             ("销售净利率", "净利率TTM"), ("每股经营现金流", "每股经营现金流")]:
                v = _get_val(k)
                if v is not None:
                    # ROE/ROA/毛利率/净利率/资产负债率是百分比
                    if k in ("净资产收益率(ROE)", "总资产报酬率(ROA)", "销售毛利率",
                             "销售净利率", "资产负债率"):
                        key_metrics[label] = _fmt_pct(v)
                    elif k == "基本每股收益":
                        key_metrics[label] = f"{v:.2f}元"
                    elif k == "每股净资产":
                        key_metrics[label] = f"{v:.2f}元"
                    else:
                        key_metrics[label] = _fmt_pct(v) if "率" in k else _fmt_num(v)

            # 股息率（从资产负债率等数据间接获取的能力有限,尝试计算）
            eps = _get_val("基本每股收益")
            bvps = _get_val("每股净资产")
            if eps and bvps and bvps > 0:
                key_metrics["EPS"] = f"{eps:.2f}"
                key_metrics["BVPS"] = f"{bvps:.2f}"

            # === 资产负债表 ===
            balance_sheet = {}
            for k, label in [("股东权益合计(净资产)", "股东权益"), ("总资产", "总资产"),
                             ("总负债", "总负债"), ("商誉", "商誉")]:
                v = _get_val(k)
                if v is not None:
                    balance_sheet[label] = _fmt_num(v)

            # === 现金流量表 ===
            cash_flow = {}
            for k, label in [("经营现金流量净额", "经营现金流"),
                             ("投资现金流量净额", "投资现金流"),
                             ("筹资现金流量净额", "筹资现金流")]:
                v = _get_val(k)
                if v is not None:
                    cash_flow[label] = _fmt_num(v)

            # === 历史数据（用于趋势分析） ===
            revenue_history = []
            profit_history = []
            roe_history = []
            for col in all_cols[:12]:  # 最近12个季度
                r = _get_val("营业总收入", col)
                p = _get_val("归母净利润", col)
                roe = _get_val("净资产收益率(ROE)", col)
                period = str(col)
                if r is not None:
                    revenue_history.append({"period": period, "value": r})
                if p is not None:
                    profit_history.append({"period": period, "value": p})
                if roe is not None:
                    roe_history.append({"period": period, "value": roe})

            result = {
                "income_statement": income_statement,
                "key_metrics": key_metrics,
                "balance_sheet": balance_sheet,
                "cash_flow": cash_flow,
                "报告期": str(latest_col) if latest_col else "N/A",
                "_history": {
                    "revenue_history": revenue_history,
                    "profit_history": profit_history,
                    "roe_history": roe_history,
                }
            }

        except Exception as e:
            print(f"  财务摘要异常: {e}")
            result["error"] = str(e)

        return result

    def _get_income_statement(self, code: str) -> Dict[str, Any]:
        """获取利润表数据"""
        result = {}
        try:
            # 获取最近几个季度的利润表
            df = self._call_akshare_with_retry(ak.stock_profit_sheet_by_yearly_em, symbol=code)

            if df is None:
                print(f"获取利润表: akshare返回None (code={code})")
            elif not df.empty:
                # 获取最新一年的数据
                latest = df.iloc[0] if len(df) > 0 else None
                if latest is not None:
                    result = {
                        "报告期": latest.get("报告日期", "N/A"),
                        "营业收入": self._format_number(latest.get("营业总收入")),
                        "营业成本": self._format_number(latest.get("营业总成本")),
                        "营业利润": self._format_number(latest.get("营业利润")),
                        "利润总额": self._format_number(latest.get("利润总额")),
                        "净利润": self._format_number(latest.get("净利润")),
                        "归母净利润": self._format_number(latest.get("归属于母公司所有者的净利润")),
                        "毛利率": self._format_percent(latest.get("销售毛利率")),
                        "净利率": self._format_percent(latest.get("销售净利率")),
                        "ROE": self._format_percent(latest.get("净资产收益率")),
                    }

                    # 计算同比增长（如果有两年的数据）
                    if len(df) > 1:
                        current = df.iloc[0]
                        previous = df.iloc[1]

                        if "营业总收入" in current.columns and "营业总收入" in previous.columns:
                            current_rev = current["营业总收入"]
                            prev_rev = previous["营业总收入"]
                            if prev_rev and prev_rev != 0:
                                revenue_growth = ((current_rev - prev_rev) / abs(prev_rev)) * 100
                                result["营收同比增长率"] = f"{revenue_growth:.2f}%"

                        if "净利润" in current.columns and "净利润" in previous.columns:
                            current_profit = current["净利润"]
                            prev_profit = previous["净利润"]
                            if prev_profit and prev_profit != 0:
                                profit_growth = ((current_profit - prev_profit) / abs(prev_profit)) * 100
                                result["净利润同比增长率"] = f"{profit_growth:.2f}%"

        except Exception as e:
            print(f"获取利润表失败: {e}")
            result["error"] = str(e)

        return result

    def _get_balance_sheet(self, code: str) -> Dict[str, Any]:
        """获取资产负债表数据"""
        result = {}
        try:
            df = self._call_akshare_with_retry(ak.stock_balance_sheet_by_yearly_em, symbol=code)

            if df is None:
                print(f"获取资产负债表: akshare返回None (code={code})")
            elif not df.empty:
                latest = df.iloc[0] if len(df) > 0 else None
                if latest is not None:
                    result = {
                        "报告期": latest.get("报告日期", "N/A"),
                        "总资产": self._format_number(latest.get("资产总计")),
                        "总负债": self._format_number(latest.get("负债合计")),
                        "股东权益": self._format_number(latest.get("股东权益合计")),
                        "资产负债率": self._format_percent(latest.get("资产负债率")),
                        "流动资产": self._format_number(latest.get("流动资产合计")),
                        "流动负债": self._format_number(latest.get("流动负债合计")),
                        "货币资金": self._format_number(latest.get("货币资金")),
                        "存货": self._format_number(latest.get("存货")),
                    }

                    # 计算流动比率
                    current_assets = latest.get("流动资产合计")
                    current_liabilities = latest.get("流动负债合计")
                    if current_assets and current_liabilities and current_liabilities != 0:
                        current_ratio = current_assets / current_liabilities
                        result["流动比率"] = f"{current_ratio:.2f}"

        except Exception as e:
            print(f"获取资产负债表失败: {e}")
            result["error"] = str(e)

        return result

    def _get_cash_flow(self, code: str) -> Dict[str, Any]:
        """获取现金流量表数据"""
        result = {}
        try:
            df = self._call_akshare_with_retry(ak.stock_cash_flow_sheet_by_yearly_em, symbol=code)

            if df is None:
                print(f"获取现金流量表: akshare返回None (code={code})")
            elif not df.empty:
                latest = df.iloc[0] if len(df) > 0 else None
                if latest is not None:
                    result = {
                        "报告期": latest.get("报告日期", "N/A"),
                        "经营活动现金流": self._format_number(latest.get("经营活动产生的现金流量净额")),
                        "投资活动现金流": self._format_number(latest.get("投资活动产生的现金流量净额")),
                        "筹资活动现金流": self._format_number(latest.get("筹资活动产生的现金流量净额")),
                        "现金及现金等价物净增加": self._format_number(latest.get("现金及现金等价物净增加额")),
                        "期末现金及现金等价物": self._format_number(latest.get("期末现金及现金等价物余额")),
                    }

        except Exception as e:
            print(f"获取现金流量表失败: {e}")
            result["error"] = str(e)

        return result

    def _get_key_metrics(self, code: str) -> Dict[str, Any]:
        """获取关键财务指标"""
        result = {}
        try:
            # 获取个股指标
            df = self._call_akshare_with_retry(ak.stock_a_indicator_lg, symbol=code)

            if df is None:
                print(f"获取关键指标: akshare返回None (code={code})")
            elif not df.empty:
                latest = df.iloc[-1] if len(df) > 0 else None
                if latest is not None:
                    result = {
                        "日期": str(latest.get("trade_date", "N/A")),
                        "市盈率PE": self._format_number(latest.get("pe")),
                        "市净率PB": self._format_number(latest.get("pb")),
                        "市销率PS": self._format_number(latest.get("ps")),
                        "总市值": self._format_number(latest.get("total_mv")),
                        "流通市值": self._format_number(latest.get("circ_mv")),
                        "换手率": self._format_percent(latest.get("turnover_rate")),
                        "股息率TTM": self._format_percent(latest.get("dv_ttm")),
                    }

        except Exception as e:
            print(f"获取关键指标失败: {e}")
            result["error"] = str(e)

        return result

    def _get_business_overview(self, code: str) -> str:
        """获取业务概述"""
        # stock_individual_info_em API currently has connection issues
        # Returning basic info from cached data instead
        try:
            if self.a_share_list_cache is not None and not self.a_share_list_cache.empty:
                matches = self.a_share_list_cache[self.a_share_list_cache['code'] == code]
                if not matches.empty:
                    name = matches.iloc[0]['name']
                    return f"**股票代码**: {code}\n**股票简称**: {name}"
        except Exception as e:
            print(f"获取基础信息失败: {e}")

        return f"**股票代码**: {code}"

    # ================================================================
    # 三维评分数据获取方法
    # ================================================================

    def get_historical_financial_indicators(
        self, stock_code: str, years: int = 5
    ) -> Dict[str, Any]:
        """获取历史财务指标数据，用于计算多维评分

        Args:
            stock_code: 股票代码
            years: 历史年数（默认5年）

        Returns:
            包含多年财务指标的字典
        """
        code, is_hk = self._normalize_code(stock_code)

        result = {
            "stock_code": stock_code,
            "years_requested": years,
            "roe_history": [],
            "roa_history": [],
            "gross_margin_history": [],
            "net_margin_history": [],
            "operating_cash_flow_history": [],
            "free_cash_flow_history": [],
            "dividend_history": [],
            "revenue_growth_history": [],
            "profit_growth_history": [],
            "total_assets_history": [],
            "total_debt_history": [],
            "shareholder_equity_history": []
        }

        if is_hk:
            # 港股数据获取（多源 fallback：指标端点 → 标准化报表 → 分红）
            self._fill_hk_history_with_fallback(code, result, years)
        else:
            # A股数据获取
            self._get_a_share_historical_data(code, result, years)

        return result

    def _get_a_share_historical_data(
        self, code: str, result: Dict[str, Any], years: int
    ):
        """获取A股历史财务数据 — 仅使用 stock_financial_abstract"""
        try:
            df = self._call_akshare_with_retry(
                ak.stock_financial_abstract, symbol=code
            )

            if df is None or df.empty:
                return

            # 只提取年报数据列(1231结尾), 避免季度波动影响增长率计算
            annual_cols = sorted(
                [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8 and str(c).endswith("1231")],
                reverse=True
            )[:years]
            # 年报数据不足时回退到全部年度数据列
            if len(annual_cols) < 3:
                annual_cols = sorted(
                    [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8 and str(c)[4:8] == "1231"],
                    reverse=True
                )[:years]
            year_cols = annual_cols if annual_cols else sorted(
                [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8],
                reverse=True
            )[:years]

            # 指标 → 历史字段映射（候选名列表：akshare 不同版本字段名会漂移，
            # 如毛利率旧用名「销售毛利率」现已改为「毛利率」，按优先级取首个命中）
            indicator_fields = {
                "roe_history": ["净资产收益率(ROE)"],
                "roa_history": ["总资产报酬率(ROA)"],
                "gross_margin_history": ["毛利率", "销售毛利率"],   # 修复：实际名为「毛利率」
                "net_margin_history": ["销售净利率", "净利率"],
                "revenue_growth_history": ["营业总收入", "营业收入"],
                "profit_growth_history": ["归母净利润", "净利润"],
                "operating_cash_flow_history": ["经营现金流量净额"],
                "shareholder_equity_history": ["股东权益合计(净资产)", "股东权益合计", "所有者权益合计"],
                "total_assets_history": ["资产总计", "总资产"],
                "total_debt_history": ["负债合计", "总负债"],
            }

            for field, candidates in indicator_fields.items():
                row_data = None
                for cand in candidates:
                    rows = df[df["指标"] == cand]
                    if not rows.empty:
                        row_data = rows.iloc[0]
                        break
                if row_data is None:
                    continue
                for col in year_cols:
                    try:
                        v = row_data.get(col)
                        if pd.isna(v): continue
                        val = float(v)
                        yr = int(str(col)[:4])
                        result[field].append({"year": yr, "value": val})
                    except (ValueError, TypeError, KeyError):
                        continue

            # 计算自由现金流(经营CF + 投资CF,从abstract获取)
            cf_rows = df[df["指标"] == "经营现金流量净额"]
            inv_rows = df[df["指标"] == "投资现金流量净额"]
            if not cf_rows.empty:
                cf_row = cf_rows.iloc[0]
                for col in year_cols:
                    try:
                        ocf_v = cf_row.get(col)
                        if pd.isna(ocf_v): continue
                        ocf = float(ocf_v)
                        # 简化FCF = 经营CF（投资CF通常为负,已在abstract中）
                        result["free_cash_flow_history"].append({
                            "year": int(str(col)[:4]), "value": ocf
                        })
                    except (ValueError, TypeError, KeyError):
                        continue

        except Exception as e:
            print(f"获取A股历史数据失败: {e}")

        # 分红历史(仍使用 stock_fhps_detail_em, 但优雅处理失败)
        try:
            div_df = self._call_akshare_with_retry(
                ak.stock_fhps_detail_em, symbol=code
            )
            if div_df is not None and not div_df.empty:
                implemented = div_df[div_df['方案进度'] == '实施分配']
                implemented = implemented.sort_values('最新公告日期', ascending=False).head(years)
                for _, row in implemented.iterrows():
                    period = str(row.get('报告期', ''))
                    if period and period[:4].isdigit():
                        year = int(period[:4])
                        div_ratio = row.get('现金分红-现金分红比例', 0)
                        if pd.notna(div_ratio) and div_ratio > 0:
                            result["dividend_history"].append({
                                "year": year,
                                "dividend_ratio": div_ratio / 10
                            })
        except Exception as e:
            print(f"获取分红历史失败: {e}")

    def _get_hk_historical_data(
        self, code: str, result: Dict[str, Any], years: int
    ) -> Dict[int, float]:
        """Tier1: stock_financial_hk_analysis_indicator_em（比率型历史指标，主源）。

        注意：该端点实际列名为 ROE_AVG/GROSS_PROFIT_RATIO/NET_PROFIT_RATIO/
        OPERATE_INCOME/HOLDER_PROFIT 等（旧代码误用 ROE/毛利率/... 导致全空）。
        返回 {year: BASIC_EPS} 供 Tier3 计算派息率。
        """
        eps_by_year: Dict[int, float] = {}
        try:
            if code in self.hk_indicator_cache:
                df = self.hk_indicator_cache[code]
            else:
                df = self._call_akshare_with_retry(
                    ak.stock_financial_hk_analysis_indicator_em, symbol=code
                )
                self.hk_indicator_cache[code] = df

            if df is None or df.empty:
                return eps_by_year

            for _, row in df.head(years).iterrows():
                report_date = str(row.get('REPORT_DATE', ''))
                if not (report_date and report_date[:4].isdigit()):
                    continue
                year = int(report_date[:4])

                roe = self._parse_number(row.get('ROE_AVG'))
                if roe is None:
                    roe = self._parse_number(row.get('ROE_YEARLY'))
                roa = self._parse_number(row.get('ROA'))
                gross_margin = self._parse_number(row.get('GROSS_PROFIT_RATIO'))
                net_margin = self._parse_number(row.get('NET_PROFIT_RATIO'))
                revenue = self._parse_number(row.get('OPERATE_INCOME'))
                profit = self._parse_number(row.get('HOLDER_PROFIT'))
                eps = self._parse_number(row.get('BASIC_EPS'))

                if pd.notna(roe):
                    result["roe_history"].append({"year": year, "value": roe})
                if pd.notna(roa):
                    result["roa_history"].append({"year": year, "value": roa})
                if pd.notna(gross_margin):
                    result["gross_margin_history"].append({"year": year, "value": gross_margin})
                if pd.notna(net_margin):
                    result["net_margin_history"].append({"year": year, "value": net_margin})
                if pd.notna(revenue):
                    result["revenue_growth_history"].append({"year": year, "value": revenue})
                if pd.notna(profit):
                    result["profit_growth_history"].append({"year": year, "value": profit})
                if pd.notna(eps):
                    eps_by_year[year] = eps

        except Exception as e:
            print(f"获取港股历史数据失败[{code}]: {e}")
        return eps_by_year

    def _pivot_hk_report(
        self, df, candidates, years: int
    ) -> Dict[int, float]:
        """将 report_em 长表（STD_ITEM_NAME/AMOUNT/REPORT_DATE）透视成 {year: value}。

        candidates 为有序候选科目名，按年取首个命中（应对不同发行人科目别名差异）。
        仅保留年度报告（DATE_TYPE_CODE=='001'），取最近 years 年。
        """
        by_year: Dict[int, float] = {}
        if df is None or getattr(df, "empty", True):
            return by_year
        if "STD_ITEM_NAME" not in df.columns or "AMOUNT" not in df.columns:
            return by_year
        if "DATE_TYPE_CODE" in df.columns:
            annual = df[df["DATE_TYPE_CODE"] == "001"]
            if not annual.empty:
                df = annual
        dates = sorted(df["REPORT_DATE"].dropna().unique(), reverse=True)[:years]
        for rd in dates:
            yr_str = str(rd)[:4]
            if not yr_str.isdigit():
                continue
            yr = int(yr_str)
            sub = df[df["REPORT_DATE"] == rd]
            for name in candidates:
                cell = sub.loc[sub["STD_ITEM_NAME"] == name, "AMOUNT"].dropna()
                if not cell.empty:
                    by_year[yr] = float(cell.iloc[0])
                    break
        return by_year

    def _get_hk_statement_history(
        self, code: str, result: Dict[str, Any], years: int
    ) -> Dict[int, float]:
        """Tier2: stock_financial_hk_report_em 三大报表补绝对值（仅填仍为空的 key）。

        参数名注意：stock=代码, symbol=报表类型(现金流量表/利润表/资产负债表), indicator=年度。
        补：绝对经营现金流、FCF(=OCF−Capex)、总资产/负债/权益；营收兜底；返回净利润序列。
        """
        netprofit_by_year: Dict[int, float] = {}
        try:
            cache = self.hk_report_cache.get(code)
            if cache is None:
                def _get(stmt):
                    return self._call_akshare_with_retry(
                        ak.stock_financial_hk_report_em,
                        stock=code, symbol=stmt, indicator="年度",
                    )
                cache = {
                    "cf": _get("现金流量表"),
                    "inc": _get("利润表"),
                    "bs": _get("资产负债表"),
                }
                self.hk_report_cache[code] = cache
            cf, inc, bs = cache["cf"], cache["inc"], cache["bs"]

            # 经营现金流（绝对值）+ FCF
            if not result["operating_cash_flow_history"]:
                ocf = self._pivot_hk_report(cf, [
                    "经营业务现金净额", "经营活动产生的现金流量净额",
                    "经营活动现金净流量", "经营产生现金",
                ], years)
                capex_fixed = self._pivot_hk_report(cf, [
                    "购建固定资产", "购置物业、厂房及设备",
                    "购建固定资产、无形资产和其他长期资产支付的现金",
                ], years)
                capex_intan = self._pivot_hk_report(cf, [
                    "购建无形资产及其他资产", "无形资产及其他长期资产投资支付的现金",
                ], years)
                for yr in sorted(ocf.keys(), reverse=True):
                    ocf_val = ocf[yr]
                    capex_val = abs(capex_fixed.get(yr, 0) or 0) + abs(capex_intan.get(yr, 0) or 0)
                    result["operating_cash_flow_history"].append({"year": yr, "value": ocf_val})
                    result["free_cash_flow_history"].append({"year": yr, "value": ocf_val - capex_val})

            # 净利润（供 Tier3 派息率参考）
            netprofit_by_year = self._pivot_hk_report(inc, [
                "股东应占溢利", "除税后溢利", "净利润",
                "归属于母公司股东的净利润", "母公司股东享有的净利润",
            ], years)

            # 营收兜底（indicator_em 为空时）
            if not result["revenue_growth_history"]:
                rev = self._pivot_hk_report(inc, ["营业额", "营业收入", "营业总收入"], years)
                for yr in sorted(rev.keys(), reverse=True):
                    result["revenue_growth_history"].append({"year": yr, "value": rev[yr]})

            # 资产负债（评分器当前未消费，顺手补全）
            if not result["total_assets_history"]:
                ta = self._pivot_hk_report(bs, ["总资产", "资产总计", "资产总额"], years)
                for yr in sorted(ta.keys(), reverse=True):
                    result["total_assets_history"].append({"year": yr, "value": ta[yr]})
            if not result["total_debt_history"]:
                td = self._pivot_hk_report(bs, ["总负债", "负债合计", "负债总额"], years)
                for yr in sorted(td.keys(), reverse=True):
                    result["total_debt_history"].append({"year": yr, "value": td[yr]})
            if not result["shareholder_equity_history"]:
                eq = self._pivot_hk_report(bs, [
                    "股东权益", "归属于母公司股东权益合计", "所有者权益合计", "净资产",
                ], years)
                for yr in sorted(eq.keys(), reverse=True):
                    result["shareholder_equity_history"].append({"year": yr, "value": eq[yr]})

        except Exception as e:
            print(f"获取港股报表历史失败[{code}]: {e}")
        return netprofit_by_year

    def _get_hk_dividend_history(
        self, code: str, result: Dict[str, Any],
        eps_by_year: Dict[int, float], netprofit_by_year: Dict[int, float],
        years: int,
    ):
        """Tier3: stock_hk_fhpx_detail_ths 历年分红 → 派息率（仅填仍为空的 dividend_history）。

        dividend_ratio = Σ每股分红 / EPS，clip 到 [0, 1.5]，与 A 股 0-1 派息率语义一致。
        """
        if result["dividend_history"]:
            return
        try:
            if code in self.hk_dividend_cache:
                df = self.hk_dividend_cache[code]
            else:
                # 同花顺用 4 位代码（去掉 5 位补零的前导 0）
                hk_code_4 = code[1:] if len(code) == 5 and code[0] == "0" else code
                df = self._call_akshare_with_retry(ak.stock_hk_fhpx_detail_ths, symbol=hk_code_4)
                self.hk_dividend_cache[code] = df
            if df is None or len(df) == 0:
                return
            if "进度" in df.columns:
                completed = df[df["进度"] == "实施完成"]
            else:
                completed = df
            import re
            div_by_year: Dict[int, float] = {}
            for _, row in completed.iterrows():
                ex_date = str(row.get("除净日", ""))
                if not ex_date or ex_date in ("NaT", "nan"):
                    continue
                try:
                    yr = int(str(ex_date)[:4])
                except ValueError:
                    continue
                plan = str(row.get("方案", ""))
                m = re.search(r"每股[^\d]*([\d.]+)", plan)
                if not m:
                    continue
                amount = float(m.group(1))
                if "美元" in plan:
                    amount = amount * 7.8  # USD/HKD 联系汇率
                div_by_year[yr] = div_by_year.get(yr, 0.0) + amount
            if not div_by_year:
                return
            for yr in sorted(div_by_year.keys(), reverse=True)[:years]:
                eps = eps_by_year.get(yr)
                if eps and eps > 0:
                    ratio = max(0.0, min(1.5, div_by_year[yr] / eps))
                    result["dividend_history"].append({"year": yr, "dividend_ratio": ratio})
        except Exception as e:
            print(f"获取港股分红历史失败[{code}]: {e}")

    def _fill_hk_history_with_fallback(
        self, code: str, result: Dict[str, Any], years: int
    ):
        """港股历史财报多源 fallback：Tier1 指标端点 → Tier2 标准化报表 → Tier3 分红。

        任一层失败均打印并继续，绝不中断 557 股批处理。
        """
        eps_by_year = self._get_hk_historical_data(code, result, years)
        netprofit_by_year = self._get_hk_statement_history(code, result, years)
        self._get_hk_dividend_history(code, result, eps_by_year, netprofit_by_year, years)
        filled = {
            k: len(result[k]) for k in (
                "roe_history", "roa_history", "gross_margin_history", "net_margin_history",
                "revenue_growth_history", "profit_growth_history", "operating_cash_flow_history",
                "free_cash_flow_history", "dividend_history", "total_assets_history",
                "total_debt_history", "shareholder_equity_history",
            ) if result.get(k)
        }
        if filled:
            print(f"  港股历史财报[{code}] 填充: {filled}")

    def get_valuation_percentiles(
        self, stock_code: str
    ) -> Dict[str, Any]:
        """获取估值指标的历史分位数

        Returns:
            {
                "pe_percentile_5y": 65.5,  # 5年PE分位数
                "pb_percentile_5y": 45.2,  # 5年PB分位数
                "ps_percentile_5y": 70.1,  # 5年PS分位数
                "current_pe": 25.3,
                "current_pb": 3.2,
                "current_ps": 5.1,
                "pe_5y_max": 45.6,
                "pe_5y_min": 12.3,
                "pe_5y_median": 28.5
            }
        """
        code, is_hk = self._normalize_code(stock_code)

        result = {
            "stock_code": stock_code,
            "pe_percentile_5y": None,
            "pb_percentile_5y": None,
            "ps_percentile_5y": None,
            "current_pe": None,
            "current_pb": None,
            "current_ps": None,
            "pe_5y_history": [],
            "pb_5y_history": [],
            "pe_5y_max": None,
            "pe_5y_min": None,
            "pe_5y_median": None
        }

        try:
            # 旧实现读 *_hist 的 pe/pb 列，但该端点不带 pe/pb → 全市场估值归零。
            # A股: stock_zh_valuation_baidu 直接给PE(TTM)/PB日序列；
            # 港股: stock_hk_daily 价格 × indicator_em 年度EPS/BPS 推算（baidu/eniu 在本环境不可用）。
            if is_hk:
                series = self._hk_valuation_from_price(code)
            else:
                series = self._a_share_valuation_baidu(code)
            pe_history, pb_history = series["pe"], series["pb"]

            if pe_history:
                current_pe = pe_history[-1]
                result["current_pe"] = round(current_pe, 2)
                result["pe_5y_max"] = round(max(pe_history), 2)
                result["pe_5y_min"] = round(min(pe_history), 2)
                result["pe_5y_median"] = round(float(pd.Series(pe_history).median()), 2)
                pct = len([x for x in pe_history if x <= current_pe]) / len(pe_history) * 100
                result["pe_percentile_5y"] = round(pct, 1)
                result["pe_5y_history"] = [{"date": "", "pe": v} for v in pe_history[-250:]]

            if pb_history:
                current_pb = pb_history[-1]
                result["current_pb"] = round(current_pb, 2)
                pct = len([x for x in pb_history if x <= current_pb]) / len(pb_history) * 100
                result["pb_percentile_5y"] = round(pct, 1)
                result["pb_5y_history"] = [{"date": "", "pb": v} for v in pb_history[-250:]]

        except Exception as e:
            print(f"获取估值分位数失败: {e}")
            result["error"] = str(e)

        return result

    def _a_share_valuation_baidu(self, code: str) -> Dict[str, list]:
        """A股估值：stock_zh_valuation_baidu 取5年PE(TTM)/PB日序列。

        返回 {"pe":[...], "pb":[...]}（按时间升序，末值为最新），已过滤异常值。
        """
        out: Dict[str, list] = {"pe": [], "pb": []}
        try:
            pe_df = self._call_akshare_with_retry(
                ak.stock_zh_valuation_baidu, symbol=code, indicator="市盈率(TTM)", period="近五年"
            )
            pb_df = self._call_akshare_with_retry(
                ak.stock_zh_valuation_baidu, symbol=code, indicator="市净率", period="近五年"
            )
            for key, dfx, cap in (("pe", pe_df, 500), ("pb", pb_df, 50)):
                if dfx is None or getattr(dfx, "empty", True) or "value" not in dfx.columns:
                    continue
                s = pd.to_numeric(dfx["value"], errors="coerce").dropna()
                out[key] = [v for v in s.tolist() if 0 < v < cap]
        except Exception as e:
            print(f"获取A股估值(百度)失败[{code}]: {e}")
        return out

    def _hk_valuation_from_price(self, code: str) -> Dict[str, list]:
        """港股估值：stock_hk_daily 收盘价 × indicator_em 年度EPS/BPS 推算PE/PB序列。

        返回 {"pe":[...], "pb":[...]}（按时间升序，末值为最新）。
        """
        out: Dict[str, list] = {"pe": [], "pb": []}
        try:
            price_df = self._call_akshare_with_retry(ak.stock_hk_daily, symbol=code, adjust="qfq")
            if price_df is None or getattr(price_df, "empty", True):
                # 备用：stock_hk_hist（东方财富）
                price_df = self._call_akshare_with_retry(
                    ak.stock_hk_hist, symbol=code, period="daily", start_date="20190101", adjust="qfq"
                )
            if price_df is None or getattr(price_df, "empty", True):
                return out
            close_col = "close" if "close" in price_df.columns else "收盘"
            date_col = "date" if "date" in price_df.columns else "日期"

            # 年度 EPS/BPS（来自 indicator_em，复用缓存）
            eps_by_year: Dict[int, float] = {}
            bps_by_year: Dict[int, float] = {}
            if code in self.hk_indicator_cache:
                ind = self.hk_indicator_cache[code]
            else:
                ind = self._call_akshare_with_retry(ak.stock_financial_hk_analysis_indicator_em, symbol=code)
                self.hk_indicator_cache[code] = ind
            if ind is not None and not ind.empty:
                for _, row in ind.iterrows():
                    rd = str(row.get("REPORT_DATE", ""))
                    if rd[:4].isdigit():
                        y = int(rd[:4])
                        eps = self._parse_number(row.get("BASIC_EPS"))
                        bps = self._parse_number(row.get("BPS"))
                        if eps and eps > 0:
                            eps_by_year[y] = eps
                        if bps and bps > 0:
                            bps_by_year[y] = bps
            if not (eps_by_year or bps_by_year):
                return out

            cur_year = datetime.now().year
            eps_years = sorted(eps_by_year)
            bps_years = sorted(bps_by_year)

            def _as_of(yr, mapping, years):
                cand = [y for y in years if y <= yr]
                return mapping[cand[-1]] if cand else None

            for _, row in price_df.iterrows():
                ystr = str(row.get(date_col))[:4]
                if not ystr.isdigit():
                    continue
                yr = int(ystr)
                if yr < cur_year - 5:  # 仅近5年
                    continue
                close = row.get(close_col)
                if not pd.notna(close) or close <= 0:
                    continue
                eps = _as_of(yr, eps_by_year, eps_years)
                bps = _as_of(yr, bps_by_year, bps_years)
                if eps:
                    pe = close / eps
                    if 0 < pe < 500:
                        out["pe"].append(pe)
                if bps:
                    pb = close / bps
                    if 0 < pb < 50:
                        out["pb"].append(pb)
        except Exception as e:
            print(f"获取港股估值(推算)失败[{code}]: {e}")
        return out

    def get_industry_comparison_data(
        self, stock_code: str, industry: str
    ) -> Dict[str, Any]:
        """获取行业对比数据

        Args:
            stock_code: 股票代码
            industry: 行业名称

        Returns:
            {
                "industry": "白酒",
                "industry_median_pe": 28.5,
                "industry_median_pb": 5.2,
                "industry_median_roe": 22.3,
                "stock_vs_industry_pe": "+15%",  # 相对于行业中位数
                "stock_vs_industry_pb": "-8%"
            }
        """
        result = {
            "stock_code": stock_code,
            "industry": industry,
            "industry_median_pe": None,
            "industry_median_pb": None,
            "industry_median_roe": None,
            "industry_avg_growth": None,
            "stock_vs_industry_pe": None,
            "stock_vs_industry_pb": None,
            "stock_vs_industry_roe": None
        }

        try:
            # 根据行业获取行业ETF或代表性股票
            industry_mapping = {
                "白酒与高端消费品": ["600519.SH", "000858.SZ"],
                "科技（AI与数字经济）": ["002230.SZ", "300059.SZ"],
                "半导体": ["688981.SH", "002371.SZ"],
                "新能源": ["300750.SZ", "002594.SZ"],
                "医药生物": ["603259.SH", "600276.SH"],
                "消费电子": ["002475.SZ", "002241.SZ"],
                "金融": ["600030.SH", "601318.SH"]
            }

            industry_stocks = industry_mapping.get(industry, [])
            if not industry_stocks:
                return result

            # 获取行业同业股票的估值指标
            industry_pe_list = []
            industry_pb_list = []
            industry_roe_list = []

            for peer_code in industry_stocks[:5]:  # 最多5只同行股票
                try:
                    peer_data = self.get_stock_financial_data(peer_code)
                    key_metrics = peer_data.get("key_metrics", {})

                    pe = self._parse_number(key_metrics.get("市盈率PE"))
                    pb = self._parse_number(key_metrics.get("市净率PB"))
                    roe = self._parse_number(key_metrics.get("ROE"))

                    if pd.notna(pe) and 0 < pe < 100:
                        industry_pe_list.append(pe)
                    if pd.notna(pb) and 0 < pb < 20:
                        industry_pb_list.append(pb)
                    if pd.notna(roe) and -50 < roe < 100:
                        industry_roe_list.append(roe)

                except Exception:
                    continue

            # 计算行业中位数
            if industry_pe_list:
                result["industry_median_pe"] = round(pd.Series(industry_pe_list).median(), 1)
            if industry_pb_list:
                result["industry_median_pb"] = round(pd.Series(industry_pb_list).median(), 1)
            if industry_roe_list:
                result["industry_median_roe"] = round(pd.Series(industry_roe_list).median(), 1)

            # 计算当前股票相对行业的差异
            stock_data = self.get_stock_financial_data(stock_code)
            stock_metrics = stock_data.get("key_metrics", {})

            stock_pe = self._parse_number(stock_metrics.get("市盈率PE"))
            stock_pb = self._parse_number(stock_metrics.get("市净率PB"))
            stock_roe = self._parse_number(stock_metrics.get("ROE"))

            if pd.notna(stock_pe) and result["industry_median_pe"]:
                diff_pct = ((stock_pe - result["industry_median_pe"]) / result["industry_median_pe"]) * 100
                result["stock_vs_industry_pe"] = f"{diff_pct:+.1f}%"

            if pd.notna(stock_pb) and result["industry_median_pb"]:
                diff_pct = ((stock_pb - result["industry_median_pb"]) / result["industry_median_pb"]) * 100
                result["stock_vs_industry_pb"] = f"{diff_pct:+.1f}%"

        except Exception as e:
            print(f"获取行业对比数据失败: {e}")
            result["error"] = str(e)

        return result

    def _parse_number(self, value: Any) -> Optional[float]:
        """解析数字值，处理各种格式"""
        if value is None or pd.isna(value):
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            # 移除百分号、单位等
            value = value.replace('%', '').replace('亿', '').replace('万', '').replace('元', '').strip()
            try:
                return float(value)
            except ValueError:
                return None

        return None

    def _format_number(self, value: Any) -> str:
        """格式化数字"""
        if value is None or pd.isna(value):
            return "N/A"
        try:
            num = float(value)
            if abs(num) >= 100000000:  # 亿
                return f"{num/100000000:.2f}亿"
            elif abs(num) >= 10000:  # 万
                return f"{num/10000:.2f}万"
            else:
                return f"{num:.2f}"
        except (ValueError, TypeError):
            return str(value)

    def _format_percent(self, value: Any) -> str:
        """格式化百分比"""
        if value is None or pd.isna(value):
            return "N/A"
        try:
            num = float(value)
            return f"{num:.2f}%"
        except (ValueError, TypeError):
            return str(value)


def get_financial_data(stock_code: str, stock_name: Optional[str] = None) -> Dict[str, Any]:
    """便捷函数：获取财务数据"""
    fetcher = FinancialDataFetcher()
    return fetcher.get_stock_financial_data(stock_code, stock_name)
