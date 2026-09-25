import hashlib
import hmac
import logging
import math
import threading
import time

from redis.exceptions import RedisError

from app.cache import redis_client
from app.config import settings

logger = logging.getLogger(__name__)
_local_windows: dict[str, tuple[int, float]] = {}
_local_lock = threading.Lock()
_last_local_cleanup = 0.0

_INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 or redis.call('PTTL', KEYS[1]) < 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('PTTL', KEYS[1])}
"""


def client_bucket_id(client_host: str) -> str:
    digest = hmac.new(settings.jwt_secret_key.encode(), client_host.encode(), hashlib.sha256).hexdigest()
    return digest


def _consume_local(key: str, window_seconds: int) -> tuple[int, int]:
    global _last_local_cleanup
    now = time.monotonic()
    with _local_lock:
        if now - _last_local_cleanup > 60:
            for old_key, (_, reset_at) in list(_local_windows.items()):
                if reset_at <= now:
                    _local_windows.pop(old_key, None)
            _last_local_cleanup = now
        count, reset_at = _local_windows.get(key, (0, now + window_seconds))
        if reset_at <= now:
            count, reset_at = 0, now + window_seconds
        count += 1
        _local_windows[key] = (count, reset_at)
        return count, max(1, math.ceil(reset_at - now))


def consume_request_limit(key: str, window_seconds: int) -> tuple[int, int]:
    try:
        count, ttl_ms = redis_client.eval(_INCREMENT_SCRIPT, 1, key, window_seconds * 1000)
        return int(count), max(1, math.ceil(int(ttl_ms) / 1000))
    except RedisError as exc:
        logger.warning("Redis rate limiter unavailable; using process-local limit", extra={"error": str(exc)})
        return _consume_local(key, window_seconds)
