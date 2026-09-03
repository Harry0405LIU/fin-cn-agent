#!/usr/bin/env python3
"""
统一数据缓存层 - 使用Parquet格式存储
"""

import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd


class DataCache:
    """数据缓存管理器"""
    
    def __init__(self, cache_dir: str = None):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录路径，默认使用项目data/cache/
        """
        if cache_dir is None:
            # 默认缓存目录：项目根目录下的 data/cache/
            project_root = Path(__file__).parent.parent
            cache_dir = project_root / "data" / "cache"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 元数据文件
        self.meta_file = self.cache_dir / "cache_meta.json"
        self._meta = self._load_meta()
    
    def _load_meta(self) -> Dict[str, Any]:
        """加载缓存元数据"""
        if self.meta_file.exists():
            try:
                with open(self.meta_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _save_meta(self):
        """保存缓存元数据"""
        with open(self.meta_file, 'w', encoding='utf-8') as f:
            json.dump(self._meta, f, ensure_ascii=False, indent=2)
    
    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        # 使用MD5哈希避免文件名非法字符
        key_hash = hashlib.md5(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{key_hash}.parquet"
    
    def get(self, key: str) -> Optional[pd.DataFrame]:
        """
        从缓存获取数据
        
        Args:
            key: 缓存键（如 'sh000001_a_share'）
            
        Returns:
            DataFrame or None
        """
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            return None
        
        try:
            df = pd.read_parquet(cache_path)
            # 更新访问时间
            if key in self._meta:
                self._meta[key]['last_accessed'] = datetime.now().isoformat()
                self._save_meta()
            return df
        except Exception as e:
            print(f"读取缓存失败 {key}: {e}")
            return None
    
    def set(self, key: str, df: pd.DataFrame, metadata: Dict = None):
        """
        保存数据到缓存
        
        Args:
            key: 缓存键
            df: 要缓存的DataFrame
            metadata: 额外的元数据
        """
        cache_path = self._get_cache_path(key)
        
        try:
            # 保存Parquet文件
            df.to_parquet(cache_path, index=False, compression='snappy')
            
            # 更新元数据
            self._meta[key] = {
                'created_at': datetime.now().isoformat(),
                'last_accessed': datetime.now().isoformat(),
                'rows': len(df),
                'columns': list(df.columns),
                'file_size': cache_path.stat().st_size,
                **(metadata or {})
            }
            self._save_meta()
            
        except Exception as e:
            print(f"写入缓存失败 {key}: {e}")
    
    def invalidate(self, key: str):
        """
        清除指定缓存
        
        Args:
            key: 缓存键
        """
        cache_path = self._get_cache_path(key)
        
        if cache_path.exists():
            try:
                cache_path.unlink()
            except Exception as e:
                print(f"删除缓存文件失败 {key}: {e}")
        
        if key in self._meta:
            del self._meta[key]
            self._save_meta()
    
    def clear_all(self):
        """清除所有缓存"""
        for f in self.cache_dir.glob("*.parquet"):
            try:
                f.unlink()
            except Exception as e:
                print(f"删除缓存文件失败 {f}: {e}")
        
        self._meta = {}
        self._save_meta()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_size = 0
        total_rows = 0
        
        for meta in self._meta.values():
            total_size += meta.get('file_size', 0)
            total_rows += meta.get('rows', 0)
        
        return {
            'cache_dir': str(self.cache_dir),
            'total_files': len(self._meta),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2),
            'total_rows': total_rows,
            'keys': list(self._meta.keys())
        }
    
    def get_cache_info(self, key: str) -> Optional[Dict]:
        """获取指定缓存的元数据"""
        return self._meta.get(key)
