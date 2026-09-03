#!/usr/bin/env python3
"""
数据获取模块 - 带缓存、重试、限流机制
"""

import time
import functools
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Any
import akshare as ak
import pandas as pd
import yfinance as yf

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
        """等待直到可以发送下一个请求"""
        if self.last_request_time is not None:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()


# 全局频率限制器
_rate_limiter = RateLimiter(min_interval=0.5)


def retry_with_backoff(max_retries: int = 3, backoff_factor: float = 1.0):
    """
    重试装饰器 - 指数退避
    
    Args:
        max_retries: 最大重试次数
        backoff_factor: 退避基数 (1s, 2s, 4s...)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries:
                        raise e
                    wait_time = backoff_factor * (2 ** attempt)
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator


class DataFetcher:
    """统一数据获取器"""
    
    def __init__(self):
        self.cache = DataCache()
        self.calendar = TradingCalendar()
        
        # 本地缓存目录（作为最终后备）
        self.local_cache_dir = settings.BASE_DIR / "数据缓存"
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"本地缓存目录: {self.local_cache_dir}")
    
    @retry_with_backoff(max_retries=3, backoff_factor=1.0)
    def _fetch_with_rate_limit(self, fetch_func: Callable, *args, **kwargs) -> Any:
        """带频率限制的数据获取"""
        _rate_limiter.wait()
        return fetch_func(*args, **kwargs)
    
    def fetch_a_share_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_refresh: bool = False,
        period: str = 'daily'
    ) -> pd.DataFrame:
        """
        获取A股数据（带缓存和增强异常处理）

        Args:
            symbol: 股票代码 (如 'sh000001')
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            force_refresh: 强制刷新缓存
            period: 数据周期 ('daily', '30min', '60min' 等)

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        cache_key = f"{symbol}_{period}_share"
        
        print(f"获取A股数据: {symbol}")
        
        # 尝试从缓存读取
        if not force_refresh:
            try:
                cached_df = self.cache.get(cache_key)
                if cached_df is not None and not cached_df.empty:
                    # 获取缓存日期范围
                    last_date = cached_df['date'].max()
                    first_date = cached_df['date'].min()

                    # 缓存覆盖不足（请求起始早于缓存最早）→ 全量刷新
                    if start_date is not None and start_date < first_date:
                        print(f"  缓存最早日期({first_date})晚于请求起始({start_date})，触发全量刷新...")
                    else:
                        # 缓存覆盖请求起始 → 增量获取新数据
                        print(f"  使用缓存数据（最新日期: {last_date}）")
                        new_start = (pd.to_datetime(last_date) + timedelta(days=1)).strftime('%Y%m%d')
                        new_end = end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')

                        if new_start <= new_end:
                            try:
                                print(f"  获取增量数据: {new_start} 至 {new_end}")
                                if period == '30min':
                                    new_df = self._fetch_a_share_30min(symbol, new_start, new_end)
                                else:
                                    new_df = self._fetch_a_share_fresh(symbol, new_start, new_end)
                                if not new_df.empty:
                                    combined = pd.concat([cached_df, new_df], ignore_index=True)
                                    combined = combined.drop_duplicates(subset=['date'], keep='last')
                                    combined = combined.sort_values('date').reset_index(drop=True)
                                    self.cache.set(cache_key, combined)
                                    if start_date:
                                        combined = combined[combined['date'] >= start_date]
                                    if end_date:
                                        combined = combined[combined['date'] <= end_date]
                                    print(f"  ✓ 缓存更新成功: {len(combined)} 条数据")
                                    return combined
                            except Exception as e:
                                print(f"  获取增量数据失败: {e}")

                        # 无需新数据，直接返回缓存（过滤日期范围）
                        result = cached_df.copy()
                        if start_date:
                            result = result[result['date'] >= start_date]
                        if end_date:
                            result = result[result['date'] <= end_date]
                        print(f"  ✓ 使用缓存数据（无需更新）")
                        return result
            except Exception as e:
                print(f"  缓存读取失败: {e}")
        
        # 全量获取
        print(f"  全量获取数据...")
        start_fmt = start_date.replace('-', '') if start_date else '20000101'
        end_fmt = end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')

        # 尝试获取新数据
        try:
            if period == '30min':
                df = self._fetch_a_share_30min(symbol, start_fmt, end_fmt)
            else:
                df = self._fetch_a_share_fresh(symbol, start_fmt, end_fmt)

            if not df.empty:
                self.cache.set(cache_key, df)
                print(f"  ✓ 数据获取成功并缓存: {len(df)} 条数据")
                return df
            else:
                print(f"  ✗ API返回空数据")
                # API返回空，尝试本地缓存
                cached_df = self._get_local_cache(symbol, start_fmt, end_fmt, period)
                if not cached_df.empty:
                    print(f"  ✓ 从本地缓存恢复: {len(cached_df)} 条数据")
                    return cached_df
                return df

        except Exception as api_error:
            print(f"  ✗ API调用失败: {str(api_error)[:100]}")
            # API失败，尝试本地缓存作为后备
            print(f"  尝试本地缓存作为后备...")
            cached_df = self._get_local_cache(symbol, start_fmt, end_fmt, period)
            if not cached_df.empty:
                print(f"  ✓ 从本地缓存恢复: {len(cached_df)} 条数据")
                return cached_df
            else:
                raise Exception(f"无法获取A股数据 {symbol}: API失败且无本地缓存")
    
    def _fetch_a_share_fresh(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """从API获取A股数据（原始格式）- 增强调试版"""
        df = None
        error_msg = ""
        
        # 尝试主数据源
        try:
            print(f"  调用 ak.stock_zh_index_daily(symbol={symbol})...")
            df = self._fetch_with_rate_limit(
                ak.stock_zh_index_daily,
                symbol=symbol
            )
            print(f"  ✓ 主数据源返回")
            print(f"  - 返回类型: {type(df)}")
            print(f"  - 是否为空: {df.empty if hasattr(df, 'empty') else 'N/A'}")
            if hasattr(df, 'columns'):
                print(f"  - 列名: {list(df.columns)}")
        except Exception as e:
            error_msg += f"主数据源失败: {str(e)[:100]}; "
            print(f"  {error_msg}")
        
        # 如果主数据源失败，尝试备用数据源
        if df is None or df.empty:
            try:
                code = symbol.replace('sh', '').replace('sz', '')
                print(f"  调用 ak.index_zh_a_hist(symbol={code}, period='daily')...")
                df = self._fetch_with_rate_limit(
                    ak.index_zh_a_hist,
                    symbol=code,
                    period="daily",
                    start_date=start,
                    end_date=end
                )
                print(f"  ✓ 备用数据源返回")
                print(f"  - 返回类型: {type(df)}")
                if hasattr(df, 'columns'):
                    print(f"  - 列名: {list(df.columns)}")
            except Exception as e2:
                error_msg += f"备用数据源失败: {str(e2)[:100]}"
                print(f"  {error_msg}")
        
        # 如果所有API都失败，返回空DataFrame
        if df is None or df.empty:
            print(f"  ✗ 所有数据源失败")
            raise Exception(f"A股数据获取失败: {error_msg}")
        
        # 框准化列名
        print(f"  标准化列名（force=True）...")
        df = self._normalize_columns(df, force=True)
        
        # 验证标准化结果
        print(f"  - 标准化后列名: {list(df.columns)}")
        print(f"  - 数据量: {len(df)}")
        
        # 过滤日期范围
        try:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            df = df[(df['date'] >= f"{start[:4]}-{start[4:6]}-{start[6:8]}") & 
                    (df['date'] <= f"{end[:4]}-{end[4:6]}-{end[6:8]}")]
            print(f"  - 日期过滤后数据量: {len(df)}")
        except Exception as e:
            print(f"  ✗ 日期过滤失败: {e}")
            return pd.DataFrame()
        
        # 保存到本地缓存
        if len(df) > 0:
            self._save_to_local_cache(df, symbol)

        return df.reset_index(drop=True)

    def _fetch_a_share_30min(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """
        获取A股30分钟数据

        Args:
            symbol: 股票代码 (如 'sh000001')
            start: 开始日期 (YYYYMMDD)
            end: 结束日期 (YYYYMMDD)

        Returns:
            标准化后的DataFrame
        """
        # 30分钟数据通常只有最近几个月，计算实际需要的日期范围
        end_date = datetime.strptime(end, '%Y%m%d') if len(end) == 8 else datetime.now()
        start_date = datetime.strptime(start, '%Y%m%d') if len(start) == 8 else (end_date - timedelta(days=180))
        start_fmt = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_fmt = end_date.strftime('%Y-%m-%d %H:%M:%S')

        try:
            print(f"  调用 ak.stock_zh_a_minute(symbol={symbol}, period='30')...")
            df = self._fetch_with_rate_limit(
                ak.stock_zh_a_minute,
                symbol=symbol,  # 30分钟数据需要完整格式如 sh600519
                period='30',
                adjust=''
            )
            print(f"  ✓ 30分钟数据源返回")
        except Exception as e:
            error_msg = f"30分钟数据源失败: {str(e)[:100]}"
            print(f"  {error_msg}")
            return pd.DataFrame()

        if df is None or df.empty:
            print(f"  ✗ 30分钟数据为空")
            return pd.DataFrame()

        # 标准化列名
        df = self._normalize_columns(df)

        # 30分钟数据的day列需要映射为date
        if 'day' in df.columns:
            df = df.rename(columns={'day': 'date'})

        # 确保有 date 列
        if 'date' not in df.columns:
            print(f"  ✗ 30分钟数据缺少date列")
            return pd.DataFrame()

        # 过滤日期范围
        df['date'] = pd.to_datetime(df['date'])
        df = df[(df['date'] >= pd.to_datetime(start_fmt)) &
                (df['date'] <= pd.to_datetime(end_fmt))]

        # 格式化date为字符串
        df['date'] = df['date'].dt.strftime('%Y-%m-%d %H:%M:%S')

        # 确保数值列是正确的类型
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        print(f"  - 过滤后30分钟数据量: {len(df)}")

        # 保存到本地缓存（带period标记）
        if len(df) > 0:
            self._save_to_local_cache(df, symbol, period='30min')

        return df.reset_index(drop=True)

    def fetch_hk_data(
        self, 
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        获取港股数据（带缓存）
        
        Args:
            symbol: 港股代码 (如 'HSI')
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            force_refresh: 强制刷新缓存
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        cache_key = f"{symbol}_hk"
        
        # 尝试从缓存读取
        if not force_refresh:
            cached_df = self.cache.get(cache_key)
            if cached_df is not None and not cached_df.empty:
                last_date = cached_df['date'].max()
                first_date = cached_df['date'].min()

                # 缓存覆盖不足（请求起始远早于缓存最早，差距>3年）→ 全量刷新
                # 差距<=3年通常是股票上市时间限制，缓存已完整
                if start_date is not None and start_date < first_date:
                    first_dt = pd.to_datetime(first_date)
                    start_dt = pd.to_datetime(start_date)
                    if (first_dt - start_dt).days > 1095:
                        print(f"  缓存最早日期({first_date})远晚于请求起始({start_date})，触发全量刷新...")
                    else:
                        # 缓存已覆盖可用数据（差距<=3年多为上市时间限制）
                        result = cached_df.copy()
                        if start_date:
                            result = result[result['date'] >= start_date]
                        if end_date:
                            result = result[result['date'] <= end_date]
                        # 仍尝试增量获取最新数据
                        new_start = (pd.to_datetime(last_date) + timedelta(days=1)).strftime('%Y%m%d')
                        new_end = end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')
                        if new_start <= new_end:
                            try:
                                new_df = self._fetch_hk_fresh(symbol, new_start, new_end)
                                if not new_df.empty:
                                    combined = pd.concat([cached_df, new_df], ignore_index=True)
                                    combined = combined.drop_duplicates(subset=['date'], keep='last')
                                    combined = combined.sort_values('date').reset_index(drop=True)
                                    self.cache.set(cache_key, combined)
                                    combined = combined[combined['date'] >= start_date] if start_date else combined
                                    combined = combined[combined['date'] <= end_date] if end_date else combined
                                    return combined
                            except Exception:
                                pass
                        return result
                elif start_date is None or start_date <= last_date:
                    new_start = (pd.to_datetime(last_date) + timedelta(days=1)).strftime('%Y%m%d')
                    new_end = end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')

                    if new_start <= new_end:
                        try:
                            new_df = self._fetch_hk_fresh(symbol, new_start, new_end)
                            if not new_df.empty:
                                combined = pd.concat([cached_df, new_df], ignore_index=True)
                                combined = combined.drop_duplicates(subset=['date'], keep='last')
                                combined = combined.sort_values('date').reset_index(drop=True)
                                self.cache.set(cache_key, combined)

                                if start_date:
                                    combined = combined[combined['date'] >= start_date]
                                if end_date:
                                    combined = combined[combined['date'] <= end_date]
                                return combined
                        except Exception as e:
                            print(f"获取增量数据失败，使用缓存: {e}")

                    # 无需新数据，直接返回缓存（过滤日期范围）
                    result = cached_df.copy()
                    if start_date:
                        result = result[result['date'] >= start_date]
                    if end_date:
                        result = result[result['date'] <= end_date]
                    return result
        
        # 全量获取
        start_fmt = start_date.replace('-', '') if start_date else '20000101'
        end_fmt = end_date.replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')
        
        df = self._fetch_hk_fresh(symbol, start_fmt, end_fmt)
        
        if not df.empty:
            self.cache.set(cache_key, df)
        
        return df
    
    def _fetch_hk_fresh(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """从API获取港股数据（原始格式）"""
        # 多源 fallback：akshare 日线 → akshare 日线(东财) → yfinance 日线
        # akshare 用 5 位补零代码
        hk_code = symbol.replace('.HK', '').replace('.hk', '').zfill(5)
        start_iso = f"{start[:4]}-{start[4:6]}-{start[6:]}"
        end_iso = f"{end[:4]}-{end[4:6]}-{end[6:]}"

        df = pd.DataFrame()

        # 主源：akshare stock_hk_daily（新浪/腾讯源）
        try:
            df = self._fetch_with_rate_limit(ak.stock_hk_daily, symbol=hk_code, adjust='qfq')
        except Exception as e:
            print(f"akshare(stock_hk_daily)获取港股失败: {e}")

        # 备1：akshare stock_hk_hist（东方财富源）
        if df is None or df.empty:
            try:
                df = self._fetch_with_rate_limit(
                    ak.stock_hk_hist, symbol=hk_code, period="daily",
                    start_date=start, end_date=end, adjust="qfq"
                )
            except Exception as e:
                print(f"akshare(stock_hk_hist)获取港股失败: {e}")

        # 备2：yfinance 日线
        # 修旧 bug：原硬编码 symbol.replace('9988.HK','01880.HK') + interval='30m'(触发730天限制)
        if df is None or df.empty:
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol)  # yfinance 接受 0700.HK 原样
                hist = ticker.history(start=start_iso, end=end_iso, interval='1d', auto_adjust=False)
                if hist is None or hist.empty:
                    print(f"yfinance获取港股数据为空: {symbol}")
                    df = pd.DataFrame()
                else:
                    df = pd.DataFrame({
                        'date': hist.index.strftime('%Y-%m-%d'),
                        'open': hist['Open'].values,
                        'high': hist['High'].values,
                        'low': hist['Low'].values,
                        'close': hist['Close'].values,
                        'volume': hist['Volume'].values
                    })
                    print(f"yfinance成功获取港股日线数据: {len(df)} 条")
            except Exception as e:
                print(f"yfinance获取港股失败: {e}")
                df = pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        # 标准化列名
        df = self._normalize_columns(df)

        # 确保有 date 列
        if not any(c.lower() == 'date' for c in df.columns):
            return pd.DataFrame()

        # 过滤日期范围
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df[(df['date'] >= start_iso) & (df['date'] <= end_iso)]

        return df.reset_index(drop=True)
    
    def _normalize_columns(self, df: pd.DataFrame, force: bool = False) -> pd.DataFrame:
        """标准化DataFrame列名 - 增强版"""
        if df is None or df.empty:
            return df
        
        # 优先处理已知的列名映射（支持多种格式）
        column_mapping = {
            # 中文
            '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close', '成交量': 'volume',
            # 英文小写
            'date': 'date', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume',
            # 英文大写
            'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume',
        }
        
        # 首先重命名已知的列名（无论大小写）
        for old_name, new_name in column_mapping.items():
            for col in list(df.columns):
                if col.lower() == old_name.lower():
                    df = df.rename(columns={col: new_name})
        
        # 强制处理：如果启用force，处理所有剩余列
        if force:
            required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
            
            # 检查每个必需列是否存在（不区分大小写）
            missing_cols = []
            for col in required_cols:
                if col not in [c.lower() for c in df.columns]:
                    missing_cols.append(col)
            
            if missing_cols:
                print(f"警告: 缺少必要列 {missing_cols}, 可用列: {list(df.columns)}")
                return pd.DataFrame()
        
        return df
    
    def _get_local_cache(self, symbol: str, start: str, end: str, period: str = 'daily') -> pd.DataFrame:
        """从本地缓存获取数据

        兼容多种缓存文件名格式（本模块与 multi_source_fetcher 写入格式并存）：
          - {symbol}_{period}_cache.json   本模块写入格式
          - {symbol}_cache.json            multi_source_fetcher 写入格式(symbol 含 .SZ/.SH 后缀)
          - {symbol}*_cache.json           glob 兜底(symbol='600519' 可命中 '600519.SH_cache.json')
        """
        candidates = [
            self.local_cache_dir / f"{symbol}_{period}_cache.json",
            self.local_cache_dir / f"{symbol}_cache.json",
        ]
        # glob 兜底：兼容 symbol 不带后缀但缓存文件带后缀的情况
        for hit in sorted(self.local_cache_dir.glob(f"{symbol}*_cache.json")):
            if hit in candidates:
                continue
            fname = hit.name
            # 跳过其它周期文件(如 _30min_cache.json)，仅当请求的就是该周期时才接受
            other_periods = ('30min', '60min', 'weekly', 'monthly')
            if any(f"_{p}_" in fname or fname.endswith(f"_{p}_cache.json") for p in other_periods) and period not in fname:
                continue
            candidates.append(hit)

        cache_file = next((c for c in candidates if c.exists()), None)
        if cache_file is None:
            return pd.DataFrame()

        try:
            import json
            cached = read_json_with_retry(cache_file)

            if not cached.get('data') or not cached.get('symbol'):
                return pd.DataFrame()

            # 检查缓存是否在请求范围内
            cache_date = cached.get('cached_date', '')
            if not cache_date:
                return pd.DataFrame()

            # 简单比较（YYYYMMDD格式）
            cache_start = cache_date
            cache_end = cache_date

            request_start = start.replace('-', '')
            request_end = end.replace('-', '')

            if cache_end < request_start or cache_start > request_end:
                print(f"  缓存数据不在范围内，跳过")
                return pd.DataFrame()

            df = pd.DataFrame(cached['data'])
            print(f"  ✓ 从本地缓存加载: {len(df)} 条数据")
            return df

        except Exception as e:
            print(f"  缓存读取失败: {e}")
            return pd.DataFrame()

    def _save_to_local_cache(self, df: pd.DataFrame, symbol: str, period: str = 'daily'):
        """保存数据到本地缓存"""
        cache_file = self.local_cache_dir / f"{symbol}_{period}_cache.json"

        try:
            import json
            data_dict = df.to_dict('records')
            cached = {
                'symbol': symbol,
                'period': period,
                'cached_date': df['date'].max() if len(df) > 0 else '',
                'cached_at': datetime.now().isoformat(),
                'count': len(df),
                'data': data_dict
            }

            write_json_with_retry(cache_file, cached)

            print(f"  ✓ 已保存到本地缓存: {len(df)} 条数据")

        except Exception as e:
            print(f"  缓存保存失败: {e}")
    
    def invalidate_local_cache(self, symbol: str):
        """清除本地缓存"""
        cache_file = self.local_cache_dir / f"{symbol}_cache.json"
        if cache_file.exists():
            cache_file.unlink()
            print(f"  ✓ 已清除本地缓存: {symbol}")
    
    def invalidate_cache(self, symbol: str, market: str = 'a', period: str = 'daily'):
        """清除指定缓存"""
        cache_key = f"{symbol}_{period}_share"
        self.cache.invalidate(cache_key)


# 全局数据获取器实例
_fetcher = None

def get_fetcher() -> DataFetcher:
    """获取全局数据获取器实例"""
    global _fetcher
    if _fetcher is None:
        _fetcher = DataFetcher()
    return _fetcher


def fetch_a_share_data(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force_refresh: bool = False,
    period: str = 'daily'
) -> pd.DataFrame:
    """便捷函数：获取A股数据"""
    return get_fetcher().fetch_a_share_data(symbol, start_date, end_date, force_refresh, period)


def fetch_hk_data(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force_refresh: bool = False
) -> pd.DataFrame:
    """便捷函数：获取港股数据"""
    return get_fetcher().fetch_hk_data(symbol, start_date, end_date, force_refresh)


def resample_to_monthly(df: pd.DataFrame, months: int = 240) -> pd.DataFrame:
    """将日线数据重采样为月线数据"""
    if df.empty:
        return df

    # 确保索引是日期类型
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    # 按月重采样，取每个月的最后一天数据
    df_monthly = df.resample('ME').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    # 只返回最近N个月的数据
    return df_monthly.tail(months)


def resample_to_weekly(df: pd.DataFrame, weeks: int = 520) -> pd.DataFrame:
    """将日线数据重采样为周线数据"""
    if df.empty:
        return df

    # 确保索引是日期类型
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    # 按周重采样，取每周的最后一天数据（周五）
    df_weekly = df.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    # 只返回最近N周的数据
    return df_weekly.tail(weeks)
