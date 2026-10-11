# -*- coding: utf-8 -*-
"""
Server酱3 发送提醒服务

职责：
1. 通过 Server酱3 API 发送 Server酱3 消息
"""
import logging
from typing import Optional
import requests
from datetime import datetime
import re

from src.config import Config
from src.formatters import chunk_content_by_max_bytes, strip_hidden_markdown_metadata


logger = logging.getLogger(__name__)

# Conservative payload budget for SC3 and compatible Turbo endpoints.
# This is a transport budget, not a claimed official SC3 maximum.
SERVERCHAN_MAX_BYTES = 30_000


class Serverchan3Sender:
    
    def __init__(self, config: Config):
        """
        初始化 Server酱3 配置

        Args:
            config: 配置对象
        """
        self._serverchan3_sendkey = getattr(config, 'serverchan3_sendkey', None)
        
    def send_to_serverchan3(
        self,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Send to every configured key; one failure does not skip other recipients."""
        keys = list(dict.fromkeys(
            key for key in re.split(r"[,\s]+", self._serverchan3_sendkey or "") if key
        ))
        if not keys:
            logger.warning("Server酱3 SendKey 未配置，跳过推送")
            return False
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        chunks = chunk_content_by_max_bytes(sanitized_content, SERVERCHAN_MAX_BYTES)
        base_title = title if title is not None else f"📈 股票分析报告 - {datetime.now():%Y-%m-%d}"
        results = []
        for recipient_index, key in enumerate(keys, 1):
            for part_index, chunk in enumerate(chunks, 1):
                part_title = (
                    f"{base_title} ({part_index}/{len(chunks)})"
                    if len(chunks) > 1 else base_title
                )
                success = self._send_to_serverchan3_key(
                    key, chunk, part_title, timeout_seconds=timeout_seconds,
                )
                logger.info(
                    "Server酱3 目标 %d 分段 %d/%d (%d bytes): %s",
                    recipient_index, part_index, len(chunks), len(chunk.encode("utf-8")),
                    "成功" if success else "失败",
                )
                results.append(success)
        return all(results)

    def _send_to_serverchan3_key(
        self,
        sendkey: str,
        content: str,
        title: Optional[str] = None,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """
        推送消息到 Server酱3

        Server酱3 API 格式：
        POST https://sctapi.ftqq.com/{sendkey}.send
        或
        POST https://{num}.push.ft07.com/send/{sendkey}.send
        {
            "title": "消息标题",
            "desp": "消息内容",
            "options": {}
        }

        Server酱3 特点：
        - 国内推送服务，支持多家国产系统推送通道，可无后台推送
        - 简单易用的 API 接口

        Args:
            content: 消息内容（Markdown 格式）
            title: 消息标题（可选）

        Returns:
            是否发送成功
        """
        if not self._serverchan3_sendkey:
            logger.warning("Server酱3 SendKey 未配置，跳过推送")
            return False

        # 处理消息标题
        if title is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            title = f"📈 股票分析报告 - {date_str}"
        sanitized_content = content

        try:
            # 根据 sendkey 格式构造 URL
            if sendkey.startswith('sctp'):
                match = re.match(r'sctp(\d+)t', sendkey)
                if match:
                    num = match.group(1)
                    url = f"https://{num}.push.ft07.com/send/{sendkey}.send"
                else:
                    logger.error("Invalid sendkey format for sctp")
                    return False
            else:
                url = f"https://sctapi.ftqq.com/{sendkey}.send"

            # 构建请求参数
            params = {
                'title': title,
                'desp': sanitized_content,
                'options': {}
            }

            # 发送请求
            headers = {
                'Content-Type': 'application/json;charset=utf-8'
            }
            response = requests.post(url, json=params, headers=headers, timeout=timeout_seconds or 10)

            if response.status_code == 200:
                result = response.json()
                if result.get('code') != 0:
                    logger.error("Server酱3 返回业务错误，未确认送达")
                    return False
                logger.info("Server酱3 消息发送成功")
                return True
            else:
                logger.error(f"Server酱3 请求失败: HTTP {response.status_code}")
                return False

        except Exception as e:
            logger.error("发送 Server酱3 消息失败: %s", type(e).__name__)
            return False
