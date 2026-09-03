
#!/usr/bin/env python3
"""
报告导出模块
支持Markdown、PDF、Excel格式导出
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd

from core.logger import get_logger

logger = get_logger('report')


class ReportExporter:
    """报告导出器"""
    
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def export_markdown(
        self,
        content: str,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """导出Markdown报告"""
        filepath = self.output_dir / f"{filename}.md"
        
        # 添加元数据头部
        if metadata:
            header = "---\n"
            for key, value in metadata.items():
                header += f"{key}: {value}\n"
            header += "---\n\n"
            content = header + content
        
        filepath.write_text(content, encoding='utf-8')
        logger.info(f"Markdown报告已导出: {filepath}")
        return str(filepath)
    
    def export_excel(
        self,
        data: Dict[str, pd.DataFrame],
        filename: str,
        sheet_names: Optional[Dict[str, str]] = None
    ) -> str:
        """导出Excel报告"""
        filepath = self.output_dir / f"{filename}.xlsx"
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            for key, df in data.items():
                sheet_name = sheet_names.get(key, key) if sheet_names else key
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        logger.info(f"Excel报告已导出: {filepath}")
        return str(filepath)
    
    def export_json(
        self,
        data: Dict[str, Any],
        filename: str
    ) -> str:
        """导出JSON报告"""
        filepath = self.output_dir / f"{filename}.json"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"JSON报告已导出: {filepath}")
        return str(filepath)


def generate_elliott_report(
    index_name: str,
    data: pd.DataFrame,
    indicators: Dict[str, Any],
    output_dir: str = "reports"
) -> Dict[str, str]:
    """生成艾略特波浪分析报告"""
    exporter = ReportExporter(output_dir)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Markdown报告
    md_content = f"""# {index_name} 艾略特波浪分析报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 价格数据

最新收盘价: {indicators.get('price', 'N/A')}

## 技术指标

| 指标 | 数值 |
|------|------|
| MA5 | {indicators.get('ma5', 'N/A')} |
| MA20 | {indicators.get('ma20', 'N/A')} |
| RSI(14) | {indicators.get('rsi', 'N/A')} |
| MACD | {indicators.get('macd', 'N/A')} |
| K | {indicators.get('k', 'N/A')} |
| D | {indicators.get('d', 'N/A')} |

## 交易信号

{chr(10).join(['- ' + s for s in indicators.get('signals', [])])}

## 数据详情

共 {len(data)} 条记录
日期范围: {data['date'].min()} ~ {data['date'].max()}
"""
    
    md_file = exporter.export_markdown(
        md_content,
        f"{index_name}_{timestamp}",
        metadata={
            'title': f"{index_name} 分析报告",
            'date': datetime.now().strftime('%Y-%m-%d'),
            'type': 'elliott_wave'
        }
    )
    
    # Excel报告
    excel_file = exporter.export_excel(
        {'price_data': data},
        f"{index_name}_{timestamp}"
    )
    
    # JSON报告
    json_file = exporter.export_json(
        {
            'index': index_name,
            'timestamp': timestamp,
            'indicators': indicators,
            'data_summary': {
                'count': len(data),
                'date_range': [data['date'].min(), data['date'].max()]
            }
        },
        f"{index_name}_{timestamp}"
    )
    
    return {
        'markdown': md_file,
        'excel': excel_file,
        'json': json_file
    }
