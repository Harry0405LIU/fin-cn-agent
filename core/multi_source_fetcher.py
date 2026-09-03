#!/usr/bin/env python3
"""
统一数据获取器 - 多数据源支持
支持数据源（按优先级排序）：
1. tencent  - 腾讯财经API，免费无需注册，支持A股+港股
2. sina     - 新浪财经API，免费无需注册，支持A股
3. efinance - 东方财富数据源，免费无需注册
4. baostock - 证券宝数据源，免费A股数据，稳定
5. akshare  - 国内数据源，功能全面但网络不稳定
6. yfinance - Yahoo Finance，国际数据源，可能被限速
7. iTick API - REST API，需要API Key
8. Longport  - 长桥OpenAPI SDK，需要APP_KEY/SECRET/TOKEN
9. 本地JSON缓存 - 最终后备
"""

import os
import re
import time
import json
import functools
import requests
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Callable, Any
import pandas as pd

# 尝试导入不同的数据源
AKSHARE_AVAILABLE = False
YFINANCE_AVAILABLE = False
EFINANCE_AVAILABLE = False
BAOSTOCK_AVAILABLE = False
LONGPORT_AVAILABLE = False

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    pass

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    pass

try:
    import efinance as ef
    EFINANCE_AVAILABLE = True
except ImportError:
    pass

try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
except ImportError:
    pass

try:
    from longport.openapi import QuoteContext, Config as LongportConfig, Period, AdjustType
    LONGPORT_AVAILABLE = True
except ImportError:
    pass

# Tencent / Sina / iTick 只需要 requests，无需额外安装
TENCENT_AVAILABLE = True
SINA_AVAILABLE = True
ITICK_AVAILABLE = True

from .data_cache import DataCache
from .trading_calendar import TradingCalendar
from .io_utils import read_json_with_retry, write_json_with_retry
from config.settings import settings


class RateLimiter:
    """请求频率限制器"""
    
    def __init__(self, min_interval: float = 0.5):
        self.min_interval = min_interval
        self.last_request_time: Optional[float] = None
    
    def wait(self):
        if self.last_request_time is not None:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()


_rate_limiter = RateLimiter(min_interval=0.5)


def retry_with_backoff(max_retries: int = 3, backoff_factor: float = 2.0):
    """重试装饰器 - 指数退避"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'rate limit' in error_msg or 'too many' in error_msg:
                        wait_time = backoff_factor * (2 ** attempt) * 3
                    else:
                        wait_time = backoff_factor * (2 ** attempt)
                    
                    if attempt == max_retries:
                        raise e
                    print(f"  第{attempt+1}次重试，等待 {wait_time:.1f}s...")
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator


class MultiSourceDataFetcher:
    """多数据源数据获取器 - 支持 iTick/Longport/baostock/efinance/Tencent/Sina 等"""
    
    def __init__(self):
        self.cache = DataCache()
        self.calendar = TradingCalendar()
        
        # 本地缓存目录
        self.local_cache_dir = settings.BASE_DIR / "数据缓存"
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # iTick API 配置
        self.itick_api_key = os.environ.get('ITICK_API_KEY', '')
        
        # Longport 配置
        self.longport_app_key = os.environ.get('LONGPORT_APP_KEY', '')
        self.longport_app_secret = os.environ.get('LONGPORT_APP_SECRET', '')
        self.longport_access_token = os.environ.get('LONGPORT_ACCESS_TOKEN', '')
        
        # 数据源配置（按优先级排序）
        self.data_sources = []
        self.source_health = {}
        
        priority = 0
        
        # Tencent - 腾讯财经，免费稳定，支持A股+港股
        if TENCENT_AVAILABLE:
            priority += 1
            self.data_sources.append('tencent')
            self.source_health['tencent'] = 'unknown'
            print(f"  数据源: tencent (优先级: {priority})")
        
        # Sina - 新浪财经，免费，支持A股
        if SINA_AVAILABLE:
            priority += 1
            self.data_sources.append('sina')
            self.source_health['sina'] = 'unknown'
            print(f"  数据源: sina (优先级: {priority})")
        
        # efinance - 东方财富
        if EFINANCE_AVAILABLE:
            priority += 1
            self.data_sources.append('efinance')
            self.source_health['efinance'] = 'unknown'
            print(f"  数据源: efinance (优先级: {priority})")
        
        # baostock - 证券宝，免费A股
        if BAOSTOCK_AVAILABLE:
            priority += 1
            self.data_sources.append('baostock')
            self.source_health['baostock'] = 'unknown'
            print(f"  数据源: baostock (优先级: {priority})")
        
        # akshare - 国内数据源
        if AKSHARE_AVAILABLE:
            priority += 1
            self.data_sources.append('akshare')
            self.source_health['akshare'] = 'unknown'
            print(f"  数据源: akshare (优先级: {priority})")
        
        # yfinance - Yahoo Finance
        if YFINANCE_AVAILABLE:
            priority += 1
            self.data_sources.append('yfinance')
            self.source_health['yfinance'] = 'unknown'
            print(f"  数据源: yfinance (优先级: {priority})")
        
        # iTick API - REST API
        if ITICK_AVAILABLE and self.itick_api_key:
            priority += 1
            self.data_sources.append('itick')
            self.source_health['itick'] = 'unknown'
            print(f"  数据源: iTick API (优先级: {priority})")
        elif ITICK_AVAILABLE and not self.itick_api_key:
            print("  数据源: iTick API (未配置 ITICK_API_KEY 环境变量，跳过)")
        
        # Longport - 长桥OpenAPI
        if LONGPORT_AVAILABLE and self.longport_app_key:
            priority += 1
            self.data_sources.append('longport')
            self.source_health['longport'] = 'unknown'
            print(f"  数据源: Longport (优先级: {priority})")
        elif LONGPORT_AVAILABLE and not self.longport_app_key:
            print("  数据源: Longport (未配置 LONGPORT_APP_KEY 等环境变量，跳过)")
        elif not LONGPORT_AVAILABLE:
            print("  数据源: Longport (未安装 longport 包，pip install longport)")
        
        print(f"  共 {len(self.data_sources)} 个数据源可用")
    
    def fetch_stock_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        统一的股票数据获取接口
        
        Args:
            symbol: 股票代码 (如 '600519.SH', '9988.HK', '0700.HK')
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            force_refresh: 强制刷新缓存
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        print(f"\n{'='*60}")
        print(f"获取股票数据: {symbol}")
        print(f"{'='*60}")
        
        # 检测市场类型
        market = self._detect_market(symbol)
        print(f"市场类型: {market}")
        
        # 格式化日期
        start_fmt = start_date.replace('-', '') if start_date else '20240101'
        end_fmt = end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')
        
        # 尝试从内存缓存读取
        if not force_refresh:
            cached_df = self._try_get_cache(symbol, start_date, end_date)
            if cached_df is not None and not cached_df.empty:
                print(f"  使用缓存数据: {len(cached_df)} 条")
                return cached_df
        
        # 按优先级尝试数据源
        for i, source in enumerate(self.data_sources):
            print(f"\n--- 尝试数据源: {source} ({i+1}/{len(self.data_sources)}) ---")
            
            try:
                df = self._fetch_from_source(source, symbol, start_fmt, end_fmt, market)
                
                if df is not None and not df.empty:
                    # 标准化列名
                    df = self._normalize_columns(df, force=True)
                    
                    # 验证标准化结果
                    required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                    missing = [col for col in required_cols if col not in df.columns]
                    if missing:
                        print(f"  标准化后缺少必要列: {missing}")
                        continue
                    
                    # 确保数据类型正确
                    df = self._ensure_dtypes(df)
                    
                    if df.empty:
                        print(f"  数据源 {source} 数据清洗后为空")
                        continue

                    # 数据完整性检查：如果返回数据远晚于请求起始日期，
                    # 说明该源可能缺少历史数据，尝试下一数据源
                    if start_fmt and i < len(self.data_sources) - 1:
                        try:
                            requested_start = datetime.strptime(start_fmt, '%Y%m%d')
                            actual_start = pd.to_datetime(df['date'].min()).to_pydatetime()
                            gap_days = (actual_start - requested_start).days
                            if gap_days > 180:
                                print(f"  数据源 {source} 覆盖不完整 "
                                      f"(请求{start_fmt}, 实际从{actual_start.strftime('%Y%m%d')}), "
                                      f"尝试下一数据源")
                                continue
                        except Exception:
                            pass
                    
                    # 保存到缓存
                    self._save_to_cache(df, symbol)
                    self._save_to_local_cache(df, symbol)
                    
                    self.source_health[source] = 'healthy'
                    print(f"  数据源 {source} 成功! 数据量: {len(df)} 条")
                    print(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
                    return df
                else:
                    print(f"  数据源 {source} 返回空数据")
                    
            except Exception as e:
                error_msg = str(e)
                if 'rate limit' in error_msg.lower() or 'too many' in error_msg.lower():
                    print(f"  频率限制: {error_msg[:100]}")
                    self.source_health[source] = 'rate_limited'
                elif 'connection' in error_msg.lower() or 'remote' in error_msg.lower() or 'timeout' in error_msg.lower():
                    print(f"  网络错误: {error_msg[:100]}")
                    self.source_health[source] = 'connection_error'
                else:
                    print(f"  错误: {error_msg[:100]}")
                    self.source_health[source] = 'error'
                continue
        
        # 所有数据源都失败，尝试本地缓存作为后备
        print(f"\n--- 所有在线数据源失败，尝试本地缓存 ---")
        
        df = self._get_local_cache(symbol, start_fmt, end_fmt)
        
        if df is not None and not df.empty:
            print(f"  从本地缓存恢复: {len(df)} 条数据 (注意：数据可能不是最新的)")
            return df
        else:
            raise Exception(
                f"无法获取股票数据 {symbol}: 所有数据源均失败，且无本地缓存。\n"
                f"建议：\n"
                f"  1. 配置 ITICK_API_KEY 环境变量以使用 iTick API\n"
                f"  2. 配置 LONGPORT_APP_KEY/LONGPORT_APP_SECRET/LONGPORT_ACCESS_TOKEN 以使用 Longport\n"
                f"  3. 检查网络连接"
            )
    
    def _fetch_from_source(
        self,
        source: str,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """根据数据源名称调用对应的获取方法"""
        if source == 'tencent':
            return self._fetch_with_tencent(symbol, start_date, end_date, market)
        elif source == 'sina':
            return self._fetch_with_sina(symbol, start_date, end_date, market)
        elif source == 'efinance':
            return self._fetch_with_efinance(symbol, start_date, end_date, market)
        elif source == 'baostock':
            return self._fetch_with_baostock(symbol, start_date, end_date, market)
        elif source == 'akshare':
            return self._fetch_with_akshare(symbol, start_date, end_date, market)
        elif source == 'yfinance':
            return self._fetch_with_yfinance(symbol, start_date, end_date, market)
        elif source == 'itick':
            return self._fetch_with_itick(symbol, start_date, end_date, market)
        elif source == 'longport':
            return self._fetch_with_longport(symbol, start_date, end_date, market)
        else:
            print(f"  未知数据源: {source}")
            return None
    
    # ============================================================
    # 数据源 1: Tencent (腾讯财经)
    # ============================================================
    def _fetch_with_tencent(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用腾讯财经API获取数据（免费，支持A股+港股）"""
        print(f"    调用 腾讯财经API...")
        
        try:
            if market == 'a':
                # A股：600519.SH -> sh600519
                code = symbol.replace('.SH', '').replace('.SZ', '')
                if symbol.endswith('.SH'):
                    tq_code = f"sh{code}"
                elif symbol.endswith('.SZ'):
                    tq_code = f"sz{code}"
                else:
                    tq_code = f"sh{code}"
            elif market == 'hk':
                # 港股：9988.HK -> hk09988
                code = symbol.replace('.HK', '')
                tq_code = f"hk{code.zfill(5)}"
            else:
                return None
            
            # 日期格式转换：20240101 -> 2024-01-01
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            
            # 腾讯财经K线API — 不传日期限制，获取全部可用历史
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tq_code},day,,,2000,qfq"  # 不传日期限制，用大limit获取全部历史
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer': 'https://gu.qq.com/'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                raise Exception(f"腾讯API返回 {response.status_code}")
            
            data = response.json()
            
            # 解析数据 - 腾讯返回格式: {data: {code: {qfqday: [...]}}}
            code_data = data.get('data', {}).get(tq_code, {})
            
            # 优先使用前复权数据
            klines = code_data.get('qfqday', [])
            if not klines:
                klines = code_data.get('day', [])
            
            if not klines:
                return None
            
            rows = []
            for item in klines:
                if isinstance(item, (list, tuple)) and len(item) >= 6:
                    rows.append({
                        'date': str(item[0]),
                        'open': float(item[1]),
                        'close': float(item[2]),
                        'high': float(item[3]),
                        'low': float(item[4]),
                        'volume': int(float(item[5])),
                    })
            
            if not rows:
                return None
            
            df = pd.DataFrame(rows)
            print(f"    腾讯API 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            raise Exception(f"腾讯财经获取失败: {e}")
    
    # ============================================================
    # 数据源 2: Sina (新浪财经)
    # ============================================================
    def _fetch_with_sina(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用新浪财经API获取数据（免费，支持A股）"""
        print(f"    调用 新浪财经API...")
        
        try:
            if market == 'a':
                code = symbol.replace('.SH', '').replace('.SZ', '')
                if symbol.endswith('.SH'):
                    sina_code = f"sh{code}"
                elif symbol.endswith('.SZ'):
                    sina_code = f"sz{code}"
                else:
                    sina_code = f"sh{code}"
            elif market == 'hk':
                # 新浪港股K线API格式不同
                code = symbol.replace('.HK', '')
                sina_code = f"hk{code.zfill(5)}"
            else:
                return None
            
            # 计算需要的数据条数（大约）
            start_dt = datetime.strptime(start_date, '%Y%m%d')
            end_dt = datetime.strptime(end_date, '%Y%m%d')
            datalen = min((end_dt - start_dt).days, 2000)
            
            # 新浪财经K线API (scale=240 表示日K)
            if market == 'a':
                url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/callback/CN_MarketDataService.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={datalen}"
            else:
                url = f"https://quotes.sina.cn/hk/api/jsonp_v2.php/callback/HK_MarketDataService.getKLineData?symbol={code.zfill(5)}&scale=240&ma=no&datalen={datalen}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer': 'https://finance.sina.com.cn/'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                raise Exception(f"新浪API返回 {response.status_code}")
            
            # 从JSONP中提取JSON
            data_match = re.search(r'callback\((.*)\)', response.text, re.DOTALL)
            if not data_match:
                raise Exception("新浪API返回格式异常")
            
            data = json.loads(data_match.group(1))
            
            # 检查错误
            if isinstance(data, dict) and data.get('__ERROR'):
                raise Exception(f"新浪API错误: {data.get('__ERRORMSG', 'Unknown')}")
            
            if not isinstance(data, list) or not data:
                return None
            
            rows = []
            for item in data:
                rows.append({
                    'date': item.get('day', ''),
                    'open': float(item.get('open', 0)),
                    'high': float(item.get('high', 0)),
                    'low': float(item.get('low', 0)),
                    'close': float(item.get('close', 0)),
                    'volume': int(float(item.get('volume', 0))),
                })
            
            if not rows:
                return None
            
            df = pd.DataFrame(rows)
            
            # 过滤日期范围
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            df = df[(df['date'] >= start_fmt) & (df['date'] <= end_fmt)]
            
            print(f"    新浪API 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            raise Exception(f"新浪财经获取失败: {e}")
    
    # ============================================================
    # 数据源 3: efinance (东方财富)
    # ============================================================
    def _fetch_with_efinance(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用 efinance 获取数据（东方财富数据源）"""
        print(f"    调用 efinance...")
        
        try:
            if market == 'a':
                code = symbol.replace('.SH', '').replace('.SZ', '')
                if symbol.endswith('.SH'):
                    ef_code = f"SH{code}"
                elif symbol.endswith('.SZ'):
                    ef_code = f"SZ{code}"
                else:
                    ef_code = code
                
                df = ef.stock.get_quote_history(
                    ef_code,
                    beg=start_date,
                    end=end_date,
                    klt=101,  # 日K
                    fqt=1     # 前复权
                )
            elif market == 'hk':
                code = symbol.replace('.HK', '')
                ef_code = code.zfill(5)
                df = ef.stock.get_quote_history(
                    ef_code,
                    beg=start_date,
                    end=end_date,
                    klt=101,
                    fqt=1
                )
            else:
                return None
            
            if df is None or df.empty:
                return None
            
            print(f"    efinance 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            raise Exception(f"efinance 获取失败: {e}")
    
    # ============================================================
    # 数据源 4: baostock (证券宝)
    # ============================================================
    def _fetch_with_baostock(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用 baostock 获取数据（免费A股数据）"""
        print(f"    调用 baostock...")
        
        lg = None
        try:
            if market != 'a':
                print(f"    baostock 仅支持A股")
                return None
            
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"baostock 登录失败: {lg.error_msg}")
            
            code = symbol.replace('.SH', '').replace('.SZ', '')
            if symbol.endswith('.SH'):
                bs_code = f"sh.{code}"
            elif symbol.endswith('.SZ'):
                bs_code = f"sz.{code}"
            else:
                bs_code = f"sh.{code}"
            
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume",
                start_date=start_fmt,
                end_date=end_fmt,
                frequency="d",
                adjustflag="2"  # 前复权
            )
            
            if rs.error_code != '0':
                raise Exception(f"baostock 查询失败: {rs.error_msg}")
            
            data_list = []
            while (rs.error_code == '0') and rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return None
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            print(f"    baostock 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            raise Exception(f"baostock 获取失败: {e}")
        finally:
            if lg is not None:
                try:
                    bs.logout()
                except:
                    pass
    
    # ============================================================
    # 数据源 5: akshare
    # ============================================================
    def _fetch_with_akshare(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用 akshare 获取数据"""
        print(f"    调用 akshare...")
        
        try:
            if market == 'a':
                code = symbol.replace('.SH', '').replace('.SZ', '')
                df = self._fetch_with_rate_limit(
                    ak.stock_zh_a_hist,
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date
                )
            elif market == 'hk':
                code = symbol.replace('.HK', '')
                df = self._fetch_with_rate_limit(
                    ak.stock_hk_hist,
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date
                )
            else:
                return None
            
            if df is None or df.empty:
                return None
            
            print(f"    akshare 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            raise Exception(f"akshare 获取失败: {e}")
    
    # ============================================================
    # 数据源 6: yfinance (Yahoo Finance)
    # ============================================================
    def _fetch_with_yfinance(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用 yfinance 获取数据"""
        print(f"    调用 yfinance...")
        
        if market == 'a':
            code = symbol.replace('.SH', '.SS').replace('.SZ', '.SS')
        elif market == 'hk':
            code = symbol
        else:
            code = symbol
        
        try:
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            
            ticker = yf.Ticker(code)
            df = ticker.history(start=start_fmt, end=end_fmt, interval='1d')
            
            if df is None or df.empty:
                return None
            
            df = df.reset_index()
            print(f"    yfinance 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            raise Exception(f"yfinance 获取失败: {e}")
    
    # ============================================================
    # 数据源 7: iTick API (REST API)
    # ============================================================
    def _fetch_with_itick(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用 iTick API 获取数据 (REST API，需要 API Key)
        
        iTick API 参数说明:
        - 认证: token header
        - code: 股票代码 (如 9988, 600519)
        - region: HK/SH/SZ
        - kType: 5=小时K线(需聚合为日K)
        - 返回格式: [{"t": timestamp_ms, "o": open, "h": high, "l": low, "c": close, "v": volume}]
        """
        print(f"    调用 iTick API...")
        
        if not self.itick_api_key:
            raise Exception("iTick API Key 未配置 (设置 ITICK_API_KEY 环境变量)")
        
        try:
            # iTick 参数格式
            if market == 'a':
                code = symbol.replace('.SH', '').replace('.SZ', '')
                if symbol.endswith('.SH'):
                    region = 'SH'
                elif symbol.endswith('.SZ'):
                    region = 'SZ'
                else:
                    region = 'SH'
            elif market == 'hk':
                code = symbol.replace('.HK', '')
                region = 'HK'
            else:
                code = symbol
                region = 'HK'
            
            url = "https://api.itick.io/stock/kline"
            headers = {'token': self.itick_api_key}
            params = {
                'code': code,
                'region': region,
                'kType': '5',  # 小时K线，后续聚合为日K
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 401:
                raise Exception(f"iTick API 认证失败: {response.text}")
            elif response.status_code == 429:
                raise Exception(f"iTick API 频率限制: {response.text}")
            elif response.status_code != 200:
                raise Exception(f"iTick API 错误 {response.status_code}: {response.text[:200]}")
            
            data = response.json()
            
            # 检查API错误
            if data.get('code') != 0 and data.get('msg'):
                raise Exception(f"iTick API 错误: {data.get('msg')}")
            
            kline_data = data.get('data', [])
            if not kline_data:
                print(f"    iTick 返回数据为空")
                return None
            
            # 解析K线数据 - iTick返回小时级数据，需聚合为日K
            rows = []
            for item in kline_data:
                if isinstance(item, dict):
                    ts = item.get('t', 0)
                    if isinstance(ts, (int, float)) and ts > 0:
                        dt = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d')
                        rows.append({
                            'date': dt,
                            'open': float(item.get('o', 0)),
                            'high': float(item.get('h', 0)),
                            'low': float(item.get('l', 0)),
                            'close': float(item.get('c', 0)),
                            'volume': float(item.get('v', 0)),
                        })
            
            if not rows:
                return None
            
            # 聚合为日K线
            df = pd.DataFrame(rows)
            daily = df.groupby('date').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
            }).reset_index()
            
            # 过滤日期范围
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            daily = daily[(daily['date'] >= start_fmt) & (daily['date'] <= end_fmt)]
            
            # volume转为整数
            daily['volume'] = daily['volume'].astype(int)
            
            print(f"    iTick API 返回 {len(daily)} 条日K数据 (从 {len(rows)} 条小时数据聚合)")
            return daily
            
        except requests.exceptions.ConnectionError as e:
            raise Exception(f"iTick API 连接失败: {e}")
        except requests.exceptions.Timeout:
            raise Exception("iTick API 超时")
        except Exception as e:
            if 'iTick' in str(e):
                raise
            raise Exception(f"iTick API 获取失败: {e}")
    
    # ============================================================
    # 数据源 8: Longport (长桥OpenAPI)
    # ============================================================
    def _fetch_with_longport(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        market: str
    ) -> Optional[pd.DataFrame]:
        """使用 Longport SDK 获取数据"""
        print(f"    调用 Longport SDK...")
        
        if not LONGPORT_AVAILABLE:
            raise Exception("longport 包未安装 (pip install longport)")
        
        if not self.longport_app_key:
            raise Exception("Longport 未配置 (设置 LONGPORT_APP_KEY/SECRET/ACCESS_TOKEN 环境变量)")
        
        try:
            config = LongportConfig(
                app_key=self.longport_app_key,
                app_secret=self.longport_app_secret,
                access_token=self.longport_access_token,
            )
            
            ctx = QuoteContext(config)
            
            if market == 'a':
                code = symbol.replace('.SH', '').replace('.SZ', '')
                if symbol.endswith('.SH'):
                    lp_symbol = f"SH{code}"
                elif symbol.endswith('.SZ'):
                    lp_symbol = f"SZ{code}"
                else:
                    lp_symbol = f"SH{code}"
            elif market == 'hk':
                lp_symbol = symbol
            else:
                lp_symbol = symbol
            
            start_dt = date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:8]))
            end_dt = date(int(end_date[:4]), int(end_date[4:6]), int(end_date[6:8]))
            
            candlesticks = ctx.history_candlesticks_by_date(
                lp_symbol,
                Period.Day,
                AdjustType.NoAdjust,
                start_dt,
                end_dt
            )
            
            if not candlesticks:
                return None
            
            rows = []
            for cs in candlesticks:
                ts = cs.close_time if hasattr(cs, 'close_time') else cs.timestamp
                rows.append({
                    'date': str(ts.date()) if hasattr(ts, 'date') else str(ts).split(' ')[0],
                    'open': float(cs.open),
                    'high': float(cs.high),
                    'low': float(cs.low),
                    'close': float(cs.close),
                    'volume': int(cs.volume),
                })
            
            if not rows:
                return None
            
            df = pd.DataFrame(rows)
            print(f"    Longport 返回 {len(df)} 条数据")
            return df
            
        except Exception as e:
            if 'Longport' in str(e) or 'longport' in str(e):
                raise
            raise Exception(f"Longport 获取失败: {e}")
    
    # ============================================================
    # 通用方法
    # ============================================================
    
    @retry_with_backoff(max_retries=3, backoff_factor=1.0)
    def _fetch_with_rate_limit(self, fetch_func: Callable, *args, **kwargs) -> Any:
        """带频率限制的数据获取"""
        _rate_limiter.wait()
        return fetch_func(*args, **kwargs)
    
    def _detect_market(self, symbol: str) -> str:
        """检测市场类型"""
        if symbol.endswith('.HK'):
            return 'hk'
        elif symbol.endswith('.SH') or symbol.endswith('.SZ'):
            return 'a'
        else:
            return 'unknown'
    
    def _normalize_columns(self, df: pd.DataFrame, force: bool = False) -> pd.DataFrame:
        """标准化DataFrame列名"""
        if df is None or df.empty:
            return df
        
        column_mapping = {
            '日期': 'date', '开盘': 'open', '最高': 'high',
            '最低': 'low', '收盘': 'close', '成交量': 'volume',
            'Date': 'date', 'Open': 'open', 'High': 'high',
            'Low': 'low', 'Close': 'close', 'Volume': 'volume',
            'date': 'date', 'open': 'open', 'high': 'high',
            'low': 'low', 'close': 'close', 'volume': 'volume',
        }
        
        for col in list(df.columns):
            col_lower = col.lower() if isinstance(col, str) else str(col)
            for old_name, new_name in column_mapping.items():
                if col_lower == old_name.lower():
                    if col != new_name:
                        df = df.rename(columns={col: new_name})
                    break
        
        if force:
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            missing = [col for col in required_cols if col not in df.columns]
            if missing:
                print(f"    标准化后缺少列: {missing}, 当前列: {list(df.columns)}")
                return pd.DataFrame()
        
        keep_cols = [c for c in ['date', 'open', 'high', 'low', 'close', 'volume'] if c in df.columns]
        df = df[keep_cols]
        
        return df
    
    def _ensure_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """确保数据类型正确"""
        if 'date' in df.columns:
            df['date'] = df['date'].astype(str)
            df['date'] = df['date'].str[:10]
        
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(int)
        
        df = df.dropna(subset=['close'])
        
        return df.reset_index(drop=True)
    
    def _save_to_cache(self, df: pd.DataFrame, symbol: str):
        """保存数据到内存缓存"""
        try:
            cache_key = f"{symbol}_stock"
            self.cache.set(cache_key, df)
        except Exception:
            pass
    
    def _try_get_cache(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """尝试从缓存获取数据，同一天内的数据可复用"""
        try:
            cache_key = f"{symbol}_stock"
            cached_df = self.cache.get(cache_key)
            if cached_df is not None and not cached_df.empty:
                # Same-day cache validation: check if cached data is from today
                # by verifying the latest date in cache matches the requested end_date
                if end_date and 'date' in cached_df.columns:
                    cached_last_date = str(cached_df['date'].iloc[-1])[:10]
                    requested_date = end_date[:10] if len(end_date) >= 10 else end_date
                    # Cache is valid if it contains data up to the requested end date
                    if cached_last_date >= requested_date:
                        return cached_df
                    else:
                        return None  # Cache is stale, need to refresh
                else:
                    # No date validation possible, use cache as-is
                    return cached_df
        except Exception:
            pass
        return None
    
    def _get_local_cache(self, symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """从本地JSON缓存获取数据"""
        cache_file = self.local_cache_dir / f"{symbol}_cache.json"
        
        if not cache_file.exists():
            return None
        
        try:
            cached = read_json_with_retry(cache_file)
            
            if not cached.get('data') or not cached.get('symbol'):
                return None
            
            df = pd.DataFrame(cached['data'])
            print(f"    从本地JSON缓存加载: {len(df)} 条数据")
            
            df = self._normalize_columns(df, force=True)
            if df.empty:
                return None
            df = self._ensure_dtypes(df)
            
            return df
            
        except Exception as e:
            print(f"    本地缓存读取失败: {e}")
            return None
    
    def _save_to_local_cache(self, df: pd.DataFrame, symbol: str):
        """保存数据到本地JSON缓存"""
        cache_file = self.local_cache_dir / f"{symbol}_cache.json"
        
        try:
            data_dict = df.to_dict('records')
            cached = {
                'symbol': symbol,
                'cached_date': str(df['date'].max()) if len(df) > 0 else '',
                'cached_at': datetime.now().isoformat(),
                'count': len(df),
                'data': data_dict
            }
            
            write_json_with_retry(cache_file, cached)

            print(f"    已保存到本地JSON缓存: {len(df)} 条")
            
        except Exception as e:
            print(f"    本地缓存保存失败: {e}")
    
    def invalidate_local_cache(self, symbol: str):
        """清除本地缓存"""
        cache_file = self.local_cache_dir / f"{symbol}_cache.json"
        if cache_file.exists():
            cache_file.unlink()
            print(f"    已清除本地缓存: {symbol}")
    
    def get_source_status(self) -> dict:
        """获取所有数据源状态"""
        return {
            'available_sources': self.data_sources,
            'health': self.source_health,
            'itick_configured': bool(self.itick_api_key),
            'longport_configured': bool(self.longport_app_key),
        }


# 全局实例
_fetcher = None

def get_multi_source_fetcher() -> MultiSourceDataFetcher:
    """获取多数据源获取器实例"""
    global _fetcher
    if _fetcher is None:
        _fetcher = MultiSourceDataFetcher()
    return _fetcher


# 便捷函数
def fetch_stock_data(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force_refresh: bool = False
) -> pd.DataFrame:
    """便捷函数：获取股票数据"""
    return get_multi_source_fetcher().fetch_stock_data(symbol, start_date, end_date, force_refresh)
