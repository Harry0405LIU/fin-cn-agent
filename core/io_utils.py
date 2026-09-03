#!/usr/bin/env python3
"""
IO 工具：云盘目录（OneDrive/iCloud）下的文件读写重试。

OneDrive/iCloud 等云盘在同步期间会对文件加锁，瞬时读写可能抛出
OSError(errno=EDEADLK, "Resource deadlock avoided")。该错误是瞬时的，
稍等重试即可成功，不应让调用方把缓存/股票池读成空或写失败。
"""

import errno
import json
import time
from pathlib import Path
from typing import Any, Optional

# 瞬时文件锁相关 errno（macOS 下 EDEADLK=11, EBUSY=16, EAGAIN=35）
_TRANSIENT_ERRNOS = {errno.EDEADLK, errno.EBUSY, errno.EAGAIN}

DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_BASE_DELAY = 1.0


def _is_transient_os_error(e: OSError) -> bool:
    return e.errno in _TRANSIENT_ERRNOS or "Resource deadlock" in str(e)


def read_text_with_retry(
    path, encoding: str = "utf-8",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> str:
    """读取文本文件，遇临时文件锁错误时退避重试。"""
    last_err = None
    for attempt in range(max_attempts):
        try:
            return Path(path).read_text(encoding=encoding)
        except OSError as e:
            last_err = e
            if not _is_transient_os_error(e) or attempt >= max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise last_err


def write_text_with_retry(
    path, content: str, encoding: str = "utf-8",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> None:
    """写文本文件，遇临时文件锁错误时退避重试。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(max_attempts):
        try:
            path.write_text(content, encoding=encoding)
            return
        except OSError as e:
            last_err = e
            if not _is_transient_os_error(e) or attempt >= max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise last_err


def read_json_with_retry(
    path,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> Any:
    """读取 JSON 文件，遇临时文件锁错误时退避重试。"""
    last_err = None
    for attempt in range(max_attempts):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            last_err = e
            if not _is_transient_os_error(e) or attempt >= max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise last_err


def write_json_with_retry(
    path, data,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    indent: Optional[int] = 2,
    ensure_ascii: bool = False,
) -> None:
    """写 JSON 文件，遇临时文件锁错误时退避重试。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(max_attempts):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
            return
        except OSError as e:
            last_err = e
            if not _is_transient_os_error(e) or attempt >= max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
    raise last_err
