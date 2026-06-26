import time
from collections import defaultdict

_MAX_MSG = 10
_WINDOW = 60


class RateLimiter:
    def __init__(self):
        self._history: dict[str, list[float]] = defaultdict(list)

    def check(self, chat_id: str) -> bool:
        now = time.time()
        cutoff = now - _WINDOW
        history = self._history[chat_id]
        history[:] = [t for t in history if t > cutoff]
        if len(history) >= _MAX_MSG:
            return False
        history.append(now)
        return True
