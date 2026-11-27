"""向量化接口桩。

真实实现应由检索服务调用嵌入模型；本单只需要一个**确定性**向量，
使向量检索链路可以离线、可复现地测通，且不引入任何外部服务依赖。

做法：字符 1-gram / 2-gram 带权哈希到固定维度后 L2 归一化。
相同文本距离 0；共享词素的文本距离明显小于无关文本——
足以验证「向量检索的排序与阈值逻辑」以及「过滤是否前置施加」。
"""

from __future__ import annotations

import hashlib
import re

from kb.models import EMBEDDING_DIM

_NORMALIZE_RE = re.compile(r"[\s\u3000]+")
_UNIGRAM_WEIGHT = 1.0
_BIGRAM_WEIGHT = 1.6


def _grams(text: str) -> list[tuple[str, float]]:
    clean = _NORMALIZE_RE.sub("", text).lower()
    grams: list[tuple[str, float]] = []
    for ch in clean:
        grams.append((ch, _UNIGRAM_WEIGHT))
    for i in range(len(clean) - 1):
        grams.append((clean[i : i + 2], _BIGRAM_WEIGHT))
    return grams


def _bucket(gram: str) -> int:
    digest = hashlib.md5(gram.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % EMBEDDING_DIM


def embed(text: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    for gram, weight in _grams(text or ""):
        vec[_bucket(gram)] += weight
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine_distance(a: list[float], b: list[float]) -> float:
    """测试用：与应用侧的距离口径保持一致（1 - cos）。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)
