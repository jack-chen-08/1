"""日志脱敏：兜底过滤器。

约定上 provider 只打事件名与内部错误码；本过滤器做第二道保险：
把疑似令牌（t-/u-/a- 前缀长串）、Bearer 头、以及注册过的密钥值统一替换为 ***。
"""

from __future__ import annotations

import logging
import re

_TOKEN_LIKE = re.compile(r"\b[tua]-[A-Za-z0-9_\-]{8,}")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}")
_PATTERNS = (_TOKEN_LIKE, _BEARER)


class RedactionFilter(logging.Filter):
    def __init__(self, extra_secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._extra = tuple(s for s in extra_secrets if s and len(s) >= 4)

    def redact(self, text: str) -> str:
        for pattern in _PATTERNS:
            text = pattern.sub("***", text)
        for secret in self._extra:
            text = text.replace(secret, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = self.redact(message)
        record.args = ()
        return True
