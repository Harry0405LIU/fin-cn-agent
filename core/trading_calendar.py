#!/usr/bin/env python3
"""
交易日历服务 - 支持A股和港股
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Union
import akshare as ak


class TradingCalendar:
    """交易日历管理器"""
    
    def __init__(self, cache_dir: str = None):
        """
        初始化交易日历
        
        Args:
            cache_dir: 日历缓存目录
        """
        if cache_dir is None:
            project_root = Path(__file__).parent.parent
            cache_dir = project_root / "data" / "cache"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 日历缓存文件
        self._a_share_calendar: Optional[List[str]] = None
        self._hk_calendar: Optional[List[str]] = None
    
    def _get_calendar_cache_path(self, market: str, year: int) -> Path:
        """获取日历缓存文件路径"""
        return self.cache_dir / f"trading_calendar_{market}_{year}.json"
    
    def _load_calendar_from_cache(self, market: str, year: int) -> Optional[List[str]]:
        """从缓存加载日历"""
        cache_path = self._get_calendar_cache_path(market, year)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 检查缓存是否过期（超过7天）
                    cached_time = datetime.fromisoformat(data.get('cached_at', '2000-01-01'))
                    if datetime.now() - cached_time < timedelta(days=7):
                        return data.get('dates', [])
            except Exception:
                pass
        return None
    
    def _save_calendar_to_cache(self, market: str, year: int, dates: List[str]):
        """保存日历到缓存"""
        cache_path = self._get_calendar_cache_path(market, year)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'cached_at': datetime.now().isoformat(),
                    'market': market,
                    'year': year,
                    'dates': dates
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存日历缓存失败: {e}")
    
    def _fetch_a_share_calendar(self, year: int) -> List[str]:
        """获取A股交易日历"""
        # 先尝试缓存
        cached = self._load_calendar_from_cache('a', year)
        if cached:
            return cached
        
        try:
            # 使用akshare获取交易日历
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                # 筛选指定年份
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                df = df[df['trade_date'].dt.year == year]
                dates = df['trade_date'].dt.strftime('%Y-%m-%d').tolist()
                
                # 保存缓存
                self._save_calendar_to_cache('a', year, dates)
                return dates
        except Exception as e:
            print(f"获取A股交易日历失败: {e}")
        
        # 失败时返回基于规则的估算
        return self._generate_default_calendar(year)
    
    def _fetch_hk_calendar(self, year: int) -> List[str]:
        """获取港股交易日历"""
        # 先尝试缓存
        cached = self._load_calendar_from_cache('hk', year)
        if cached:
            return cached
        
        try:
            # 尝试使用akshare获取港股交易日历
            df = ak.stock_hk_trade_date()
            if df is not None and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                df = df[df['trade_date'].dt.year == year]
                dates = df['trade_date'].dt.strftime('%Y-%m-%d').tolist()
                
                self._save_calendar_to_cache('hk', year, dates)
                return dates
        except Exception as e:
            print(f"获取港股交易日历失败，使用简化规则: {e}")
        
        # 港股与A股类似，但有一些差异（如圣诞节、复活节等）
        # 这里使用简化版：周一到周五，排除部分已知假期
        return self._generate_hk_calendar(year)
    
    def _generate_default_calendar(self, year: int) -> List[str]:
        """生成默认交易日历（周一到周五）"""
        dates = []
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31)
        
        current = start_date
        while current <= end_date:
            # 0=周一, 6=周日
            if current.weekday() < 5:
                dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        return dates
    
    def _generate_hk_calendar(self, year: int) -> List[str]:
        """生成港股交易日历（简化版）"""
        dates = self._generate_default_calendar(year)
        
        # 港股特有假期（简化处理）
        hk_holidays = [
            f"{year}-01-01",  # 元旦
            f"{year}-12-25",  # 圣诞节
            f"{year}-12-26",  # 圣诞节后第一个周日
        ]
        
        # 移除假期
        dates = [d for d in dates if d not in hk_holidays]
        
        return dates
    
    def is_trading_day(self, date: Union[str, datetime] = None, market: str = 'a') -> bool:
        """
        判断是否为交易日
        
        Args:
            date: 日期，默认为今天
            market: 'a' 或 'hk'
            
        Returns:
            bool
        """
        if date is None:
            date = datetime.now()
        
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d')
        
        date_str = date.strftime('%Y-%m-%d')
        year = date.year
        
        if market == 'a':
            if self._a_share_calendar is None:
                self._a_share_calendar = self._fetch_a_share_calendar(year)
            return date_str in self._a_share_calendar
        elif market == 'hk':
            if self._hk_calendar is None:
                self._hk_calendar = self._fetch_hk_calendar(year)
            return date_str in self._hk_calendar
        else:
            raise ValueError(f"不支持的市场: {market}")
    
    def get_trading_dates(
        self, 
        start: Union[str, datetime], 
        end: Union[str, datetime], 
        market: str = 'a'
    ) -> List[str]:
        """
        获取日期范围内的交易日列表
        
        Args:
            start: 开始日期
            end: 结束日期
            market: 'a' 或 'hk'
            
        Returns:
            交易日列表
        """
        if isinstance(start, str):
            start = datetime.strptime(start, '%Y-%m-%d')
        if isinstance(end, str):
            end = datetime.strptime(end, '%Y-%m-%d')
        
        # 获取涉及的所有年份
        years = range(start.year, end.year + 1)
        
        all_dates = []
        for year in years:
            if market == 'a':
                calendar = self._fetch_a_share_calendar(year)
            else:
                calendar = self._fetch_hk_calendar(year)
            all_dates.extend(calendar)
        
        # 过滤日期范围
        start_str = start.strftime('%Y-%m-%d')
        end_str = end.strftime('%Y-%m-%d')
        
        return [d for d in all_dates if start_str <= d <= end_str]
    
    def get_last_trading_day(self, date: Union[str, datetime] = None, market: str = 'a') -> str:
        """
        获取最近一个交易日
        
        Args:
            date: 参考日期，默认为今天
            market: 'a' 或 'hk'
            
        Returns:
            最近交易日字符串
        """
        if date is None:
            date = datetime.now()
        
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d')
        
        # 向前查找交易日
        current = date
        while True:
            if self.is_trading_day(current, market):
                return current.strftime('%Y-%m-%d')
            current -= timedelta(days=1)
            
            # 防止无限循环
            if (date - current).days > 30:
                return date.strftime('%Y-%m-%d')
    
    def get_next_trading_day(self, date: Union[str, datetime] = None, market: str = 'a') -> str:
        """
        获取下一个交易日
        
        Args:
            date: 参考日期，默认为今天
            market: 'a' 或 'hk'
            
        Returns:
            下一交易日字符串
        """
        if date is None:
            date = datetime.now()
        
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d')
        
        # 向后查找交易日
        current = date + timedelta(days=1)
        while True:
            if self.is_trading_day(current, market):
                return current.strftime('%Y-%m-%d')
            current += timedelta(days=1)
            
            if (current - date).days > 30:
                return current.strftime('%Y-%m-%d')


# 导入pandas用于类型提示
import pandas as pd


# 全局日历实例
_calendar = None

def get_calendar() -> TradingCalendar:
    """获取全局日历实例"""
    global _calendar
    if _calendar is None:
        _calendar = TradingCalendar()
    return _calendar


def is_trading_day(date: Union[str, datetime] = None, market: str = 'a') -> bool:
    """便捷函数：判断是否为交易日"""
    return get_calendar().is_trading_day(date, market)


def get_trading_dates(
    start: Union[str, datetime], 
    end: Union[str, datetime], 
    market: str = 'a'
) -> List[str]:
    """便捷函数：获取交易日列表"""
    return get_calendar().get_trading_dates(start, end, market)
