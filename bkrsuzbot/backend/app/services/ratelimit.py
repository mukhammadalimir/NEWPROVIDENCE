"""Простое ограничение частоты запросов в памяти процесса (на одного пользователя).

Для нескольких экземпляров сервиса замените на Redis — интерфейс тот же.
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        q = self._hits[user_id]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
