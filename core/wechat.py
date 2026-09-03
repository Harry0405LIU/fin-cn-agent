#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信Webhook推送模块
统一所有模块的企业微信消息发送功能
"""

import json
import re
import ssl
import urllib.request
from typing import List, Optional

from config.settings import settings


class WeChatPusher:
    """企业微信Webhook推送器"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    def send_markdown(self, content: str) -> bool:
        """发送单条Markdown消息到企业微信Webhook"""
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {"content": content}
        }, ensure_ascii=False).encode("utf-8")
        
        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("errcode") != 0:
                    print(f"  [!] 推送失败: {result}")
                    return False
                return True
        except Exception as e:
            print(f"  [!] 推送异常: {e}")
            return False
    
    def send_markdown_message(self, content: str) -> bool:
        """send_markdown的别名"""
        return self.send_markdown(content)
    
    @staticmethod
    def simplify_for_wecom(text: str) -> str:
        """将Markdown简化为企业微信Webhook支持的格式(不支持表格)"""
        lines = text.split("\n")
        result = []
        in_table = False
        table_headers = []
        
        for line in lines:
            if re.match(r'^\|[\s\-|:]+\|$', line.strip()):
                in_table = True
                continue
            
            table_match = re.match(r'^\|(.+)\|$', line.strip())
            if table_match:
                cells = [c.strip() for c in table_match.group(1).split("|")]
                if not in_table:
                    table_headers = cells
                    in_table = True
                else:
                    if table_headers:
                        row_parts = []
                        for i, cell in enumerate(cells):
                            if i < len(table_headers) and cell and cell != "-":
                                header = table_headers[i]
                                row_parts.append(f"{header}: {cell}")
                        if row_parts:
                            result.append("> " + " | ".join(row_parts))
                continue
            else:
                in_table = False
                table_headers = []
            
            result.append(line)
        
        cleaned = []
        for line in result:
            if line.strip() == "---":
                if cleaned and cleaned[-1].strip() != "---":
                    cleaned.append(line)
            else:
                cleaned.append(line)
        
        return "\n".join(cleaned)
    
    def split_and_send(self, report_text: str, max_bytes: int = None) -> bool:
        """将报告自动分段发送到企业微信"""
        if max_bytes is None:
            max_bytes = settings.MAX_CONTENT_BYTES
        """将报告自动分段发送到企业微信"""
        messages = self._split_report(report_text, max_bytes)
        total = len(messages)
        success_count = 0
        
        for i, msg in enumerate(messages):
            if total > 1:
                msg = f"**[{i+1}/{total}]**\n\n" + msg
            size = len(msg.encode("utf-8"))
            print(f"  推送第 {i+1}/{total} 段 ({size} bytes)...")
            if self.send_markdown(msg):
                success_count += 1
            else:
                print(f"  [!] 第 {i+1} 段推送失败")
        
        print(f"  推送完成: {success_count}/{total} 段成功")
        return success_count == total
    
    def _split_report(self, text: str, max_bytes: int) -> List[str]:
        """按二级标题(##)分割报告，确保每段不超限"""
        parts = re.split(r'\n(?=## )', text)
        messages = []
        current_msg = ""
        
        for part in parts:
            simplified = self.simplify_for_wecom(part.strip())
            if not simplified:
                continue
            
            candidate = (current_msg + "\n\n" + simplified).strip() if current_msg else simplified
            
            if len(candidate.encode("utf-8")) > max_bytes:
                if current_msg:
                    messages.append(current_msg.strip())
                if len(simplified.encode("utf-8")) > max_bytes:
                    sub_msgs = self._split_long_section(simplified, max_bytes)
                    messages.extend(sub_msgs)
                    current_msg = ""
                else:
                    current_msg = simplified
            else:
                current_msg = candidate
        
        if current_msg:
            messages.append(current_msg.strip())
        
        return messages
    
    def _split_long_section(self, text: str, max_bytes: int) -> List[str]:
        """将超长段落按三级标题或换行进一步拆分"""
        parts = re.split(r'\n(?=### )', text)
        messages = []
        current = ""
        
        for part in parts:
            candidate = (current + "\n\n" + part).strip() if current else part
            if len(candidate.encode("utf-8")) > max_bytes:
                if current:
                    messages.append(current.strip())
                if len(part.encode("utf-8")) > max_bytes:
                    line_msgs = self._split_by_lines(part, max_bytes)
                    messages.extend(line_msgs)
                    current = ""
                else:
                    current = part
            else:
                current = candidate
        
        if current:
            messages.append(current.strip())
        
        return messages
    
    def _split_by_lines(self, text: str, max_bytes: int) -> List[str]:
        """按行拆分超长文本"""
        lines = text.split("\n")
        messages = []
        current = ""
        
        for line in lines:
            candidate = (current + "\n" + line).strip() if current else line
            if len(candidate.encode("utf-8")) > max_bytes:
                if current:
                    messages.append(current.strip())
                current = line
            else:
                current = candidate
        
        if current:
            messages.append(current.strip())
        
        return messages
