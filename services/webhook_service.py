#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信 Webhook 推送服务
提供统一的 Webhook 消息推送接口，支持多种消息类型和自动分段
"""

import json
import ssl
import urllib.request
from typing import Dict, List, Optional, Union
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


class WebhookService:
    """企业微信 Webhook 推送服务"""

    def __init__(
        self,
        webhook_url: str,
        max_content_bytes: int = 3800,
        timeout: int = 15,
        verify_ssl: bool = True
    ):
        """
        初始化 Webhook 服务

        Args:
            webhook_url: 企业微信 Webhook URL
            max_content_bytes: 单条消息最大字节数（默认3800，企业微信限制）
            timeout: 请求超时时间（秒）
            verify_ssl: 是否验证SSL证书
        """
        self.webhook_url = webhook_url
        self.max_content_bytes = max_content_bytes
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session_headers = {
            "Content-Type": "application/json"
        }

    # ============================================================
    # 消息发送
    # ============================================================

    def send_markdown(self, content: str, split: bool = True) -> Dict:
        """
        发送 Markdown 消息

        Args:
            content: Markdown 格式内容
            split: 是否自动分段发送（超过字数限制时）

        Returns:
            发送结果: {"success": bool, "sent_count": int, "total_count": int, "errors": List[str]}
        """
        if split and len(content.encode("utf-8")) > self.max_content_bytes:
            messages = self.split_markdown_message(content)
        else:
            messages = [content]

        result = {
            "success": True,
            "sent_count": 0,
            "total_count": len(messages),
            "errors": []
        }

        for i, msg in enumerate(messages):
            # 添加分段标识
            if len(messages) > 1:
                msg = f"**[{i+1}/{len(messages)}]**\n\n{msg}"

            response = self._send_single_message({"msgtype": "markdown", "markdown": {"content": msg}})

            if response.get("errcode") == 0:
                result["sent_count"] += 1
                logger.info(f"消息推送成功 [{i+1}/{len(messages)}]")
            else:
                result["success"] = False
                error_msg = response.get("errmsg", "未知错误")
                result["errors"].append(f"消息[{i+1}]推送失败: {error_msg}")
                logger.error(f"消息推送失败 [{i+1}/{len(messages)}]: {error_msg}")

        return result

    def send_text(self, content: str, mentioned_list: Optional[List[str]] = None,
                  mentioned_mobile_list: Optional[List[str]] = None) -> Dict:
        """
        发送文本消息

        Args:
            content: 文本内容
            mentioned_list: @的User ID列表
            mentioned_mobile_list: @的手机号列表

        Returns:
            发送结果
        """
        message = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }

        if mentioned_list:
            message["text"]["mentioned_list"] = mentioned_list
        if mentioned_mobile_list:
            message["text"]["mentioned_mobile_list"] = mentioned_mobile_list

        response = self._send_single_message(message)

        return {
            "success": response.get("errcode") == 0,
            "response": response
        }

    def send_image(self, image_path: Union[str, Path]) -> Dict:
        """
        发送图片消息

        Args:
            image_path: 图片文件路径

        Returns:
            发送结果
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return {
                "success": False,
                "error": f"图片文件不存在: {image_path}"
            }

        # 企业微信图片需要先上传获取 media_id
        # 这里简化实现，实际需要调用素材上传接口
        return {
            "success": False,
            "error": "图片消息需要先上传素材，暂未实现"
        }

    def send_news(self, articles: List[Dict]) -> Dict:
        """
        发送图文消息

        Args:
            articles: 图文文章列表，每个包含 title, url, picurl, description

        Returns:
            发送结果
        """
        message = {
            "msgtype": "news",
            "news": {
                "articles": articles
            }
        }

        response = self._send_single_message(message)

        return {
            "success": response.get("errcode") == 0,
            "response": response
        }

    # ============================================================
    # 消息格式化与分段
    # ============================================================

    def split_markdown_message(self, content: str, delimiter: str = "## ") -> List[str]:
        """
        分割 Markdown 消息，确保每段不超过字数限制

        Args:
            content: Markdown 内容
            delimiter: 分段标记（默认为二级标题）

        Returns:
            分割后的消息列表
        """
        import re

        # 按标题分割
        parts = re.split(rf'\n(?={delimiter})', content)

        messages = []
        current_msg = ""

        for part in parts:
            # 简化 Markdown（移除表格等企业微信不支持的格式）
            simplified = self.simplify_markdown(part)

            if not simplified.strip():
                continue

            candidate = (current_msg + "\n\n" + simplified).strip() if current_msg else simplified

            if len(candidate.encode("utf-8")) > self.max_content_bytes:
                if current_msg:
                    messages.append(current_msg.strip())

                # 如果单个部分就超限，进一步拆分
                if len(simplified.encode("utf-8")) > self.max_content_bytes:
                    sub_msgs = self._split_long_section(simplified)
                    messages.extend(sub_msgs)
                    current_msg = ""
                else:
                    current_msg = simplified
            else:
                current_msg = candidate

        if current_msg:
            messages.append(current_msg.strip())

        return messages

    def simplify_markdown(self, text: str) -> str:
        """
        将 Markdown 简化为企业微信支持的格式
        主要处理：表格转列表、清理多余分隔线

        Args:
            text: 原始 Markdown 文本

        Returns:
            简化后的 Markdown
        """
        import re

        lines = text.split("\n")
        result = []
        in_table = False
        table_headers = []

        for line in lines:
            # 检测表格分隔行 |---|---|
            if re.match(r'^\|[\s\-|:]+\|$', line.strip()):
                in_table = True
                continue

            # 检测表格行
            table_match = re.match(r'^\|(.+)\|$', line.strip())
            if table_match:
                cells = [c.strip() for c in table_match.group(1).split("|")]
                if not in_table:
                    # 表头行
                    table_headers = cells
                    in_table = True
                else:
                    # 数据行
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

        # 移除过多的分隔线
        cleaned = []
        for line in result:
            if line.strip() == "---":
                if cleaned and cleaned[-1].strip() != "---":
                    cleaned.append(line)
            else:
                cleaned.append(line)

        return "\n".join(cleaned)

    def _split_long_section(self, text: str) -> List[str]:
        """将超长段落按三级标题或换行进一步拆分"""
        import re

        parts = re.split(r'\n(?=### )', text)
        messages = []
        current = ""

        for part in parts:
            candidate = (current + "\n\n" + part).strip() if current else part
            if len(candidate.encode("utf-8")) > self.max_content_bytes:
                if current:
                    messages.append(current.strip())
                # 按行进一步拆分
                if len(part.encode("utf-8")) > self.max_content_bytes:
                    line_msgs = self._split_by_lines(part)
                    messages.extend(line_msgs)
                    current = ""
                else:
                    current = part
            else:
                current = candidate

        if current:
            messages.append(current.strip())

        return messages

    def _split_by_lines(self, text: str) -> List[str]:
        """按行拆分超长文本"""
        lines = text.split("\n")
        messages = []
        current = ""

        for line in lines:
            candidate = (current + "\n" + line).strip() if current else line
            if len(candidate.encode("utf-8")) > self.max_content_bytes:
                if current:
                    messages.append(current.strip())
                current = line
            else:
                current = candidate

        if current:
            messages.append(current.strip())

        return messages

    # ============================================================
    # 私有方法
    # ============================================================

    def _send_single_message(self, message: Dict) -> Dict:
        """
        发送单条消息到企业微信

        Args:
            message: 消息字典

        Returns:
            API 响应
        """
        try:
            data = json.dumps(message, ensure_ascii=False).encode("utf-8")

            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers=self.session_headers
            )

            # 创建SSL上下文
            ctx = ssl.create_default_context()
            if not self.verify_ssl:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result

        except urllib.error.URLError as e:
            logger.error(f"Webhook 请求失败: {e}")
            return {"errcode": -1, "errmsg": str(e)}
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return {"errcode": -1, "errmsg": str(e)}

    # ============================================================
    # 静态工厂方法
    # ============================================================

    @staticmethod
    def from_config(config: Dict) -> "WebhookService":
        """
        从配置创建 Webhook 服务

        Args:
            config: 配置字典，包含 webhook_url, max_content_bytes, timeout, verify_ssl

        Returns:
            WebhookService 实例
        """
        return WebhookService(
            webhook_url=config.get("webhook_url", ""),
            max_content_bytes=config.get("max_content_bytes", 3800),
            timeout=config.get("timeout", 15),
            verify_ssl=config.get("verify_ssl", True)
        )


class MultiWebhookService:
    """多 Webhook 管理服务"""

    def __init__(self, webhook_urls: List[str]):
        """
        初始化多 Webhook 服务

        Args:
            webhook_urls: Webhook URL 列表
        """
        self.services = [WebhookService(url) for url in webhook_urls]

    def send_markdown_all(self, content: str) -> List[Dict]:
        """
        向所有 Webhook 发送 Markdown 消息

        Args:
            content: Markdown 内容

        Returns:
            每个 Webhook 的发送结果列表
        """
        results = []
        for i, service in enumerate(self.services):
            result = service.send_markdown(content)
            result["webhook_index"] = i
            result["webhook_url"] = service.webhook_url
            results.append(result)

        return results

    def send_markdown_one(self, content: str, index: int = 0) -> Dict:
        """
        向指定 Webhook 发送 Markdown 消息

        Args:
            content: Markdown 内容
            index: Webhook 索引

        Returns:
            发送结果
        """
        if index < 0 or index >= len(self.services):
            return {
                "success": False,
                "error": f"Webhook 索引 {index} 超出范围 (0-{len(self.services)-1})"
            }

        return self.services[index].send_markdown(content)
