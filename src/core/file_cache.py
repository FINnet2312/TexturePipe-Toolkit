"""file_cache — FILE 槽加载缓存,避免重复读盘 + resize。

key = (str(path), float(mtime), str(token_name), (h, w), variant)
- mtime:文件修改时间,文件改了自动失效
- token:不同 token(R/G/B/A/INV_*/BLACK/WHITE)提取结果不同
- (h, w):目标尺寸,resize 后的结果不同

容量限制 64 项(简单 LRU),避免无限增长。
"""
from __future__ import annotations

import os
from collections import OrderedDict
from typing import Optional

import numpy as np


class FileCache:
    """基于 (path, mtime, token, size) 的 LRU 缓存。

    同时限制条目数和实际字节数，避免少数 8K/16K 数组把进程内存撑满。
    大于整个预算的单项会直接跳过缓存。
    """

    def __init__(self, max_size: int = 64, max_bytes: int = 512 * 1024**2):
        if max_size <= 0 or max_bytes <= 0:
            raise ValueError("缓存条目数和字节预算必须大于 0")
        self._max_size = max_size
        self._max_bytes = int(max_bytes)
        self._bytes = 0
        self._cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, path: str, token_name: str, h: int, w: int,
            variant: object = None) -> Optional[np.ndarray]:
        """命中 → 返回 ndarray + 移到末尾(MRU);未命中 → 返回 None。"""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            self.misses += 1
            return None
        key = (path, mtime, token_name, (h, w), variant)
        if key in self._cache:
            self._cache.move_to_end(key)
            self.hits += 1
            return self._cache[key]
        self.misses += 1
        return None

    def put(self, path: str, token_name: str, h: int, w: int,
            value: np.ndarray, variant: object = None) -> None:
        """写入缓存,容量满时丢最久未用的。"""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        key = (path, mtime, token_name, (h, w), variant)
        value = np.asarray(value)
        value_bytes = int(value.nbytes)
        if value_bytes > self._max_bytes:
            return
        previous = self._cache.pop(key, None)
        if previous is not None:
            self._bytes -= int(previous.nbytes)
        self._cache[key] = value
        self._bytes += value_bytes
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size or self._bytes > self._max_bytes:
            _old_key, old_value = self._cache.popitem(last=False)
            self._bytes -= int(old_value.nbytes)

    def clear(self) -> None:
        self._cache.clear()
        self._bytes = 0
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "bytes": self._bytes,
            "max_bytes": self._max_bytes,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / total if total else 0.0,
        }
