#!/usr/bin/env python3
"""
多数据源支持模块
统一接口支持 akshare、东方财富、Tushare Pro 等数据源
"""

import pandas as pd
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod


class DataSource(ABC):
    """数据源抽象基类"""
    
    @abstractmethod
    def fetch_daily_data(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str
    ) -> pd.DataFrame:
        """获取日线数据"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """获取数据源名称"""
        pass


class AkshareSource(DataSource):
    """akshare数据源"""
    
    def __init__(self):
        import akshare as ak
        self.ak = ak
    
    def get_name(self) -> str:
        return "akshare"
    
    def fetch_daily_data(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str
    ) -> pd.DataFrame:
        """获取A股日线数据"""
        df = self.ak.stock_zh_index_daily(symbol=symbol)
        df = df.rename(columns={
            'date': 'date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        })
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df[(df['date'] >= start_date) & (df['date'] <= end_date)]


class EastmoneySource(DataSource):
    """东方财富数据源"""
    
    def get_name(self) -> str:
        return "eastmoney"
    
    def fetch_daily_data(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str
    ) -> pd.DataFrame:
        """通过akshare的东方财富接口获取数据"""
        import akshare as ak
        
        # 转换代码格式
        code = symbol.replace('sh', '').replace('sz', '')
        
        df = ak.index_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', '')
        )
        
        df = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume'
        })
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        return df


class DataSourceManager:
    """数据源管理器"""
    
    def __init__(self):
        self.sources: Dict[str, DataSource] = {}
        self._register_default_sources()
    
    def _register_default_sources(self):
        """注册默认数据源"""
        self.register('akshare', AkshareSource())
        self.register('eastmoney', EastmoneySource())
    
    def register(self, name: str, source: DataSource):
        """注册数据源"""
        self.sources[name] = source
    
    def get(self, name: str) -> Optional[DataSource]:
        """获取数据源"""
        return self.sources.get(name)
    
    def fetch_with_fallback(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str,
        priority: list = ['akshare', 'eastmoney']
    ) -> pd.DataFrame:
        """
        按优先级获取数据，自动降级
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            priority: 数据源优先级列表
            
        Returns:
            DataFrame
        """
        for source_name in priority:
            source = self.get(source_name)
            if source:
                try:
                    df = source.fetch_daily_data(symbol, start_date, end_date)
                    if not df.empty:
                        return df
                except Exception as e:
                    print(f"  {source_name} 失败: {e}")
                    continue
        
        raise Exception("所有数据源均失败")


# 全局管理器实例
_manager = None

def get_manager() -> DataSourceManager:
    """获取全局数据源管理器"""
    global _manager
    if _manager is None:
        _manager = DataSourceManager()
    return _manager
