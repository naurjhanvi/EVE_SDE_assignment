import json
import logging
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)
redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=0.2,
    socket_timeout=0.2,
)


def get_json(key: str) -> Any | None:
    try:
        value = redis_client.get(key)
        return json.loads(value) if value is not None else None
    except (RedisError, json.JSONDecodeError) as exc:
        logger.warning("Redis cache read failed", extra={"cache_operation": "get", "error": str(exc)})
        return None


def set_json(key: str, value: Any, ttl_seconds: int = 60) -> None:
    try:
        redis_client.set(key, json.dumps(value), ex=ttl_seconds)
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning("Redis cache write failed", extra={"cache_operation": "set", "error": str(exc)})


def invalidate(key: str) -> None:
    try:
        redis_client.delete(key)
    except RedisError as exc:
        logger.warning("Redis cache invalidation failed", extra={"cache_operation": "delete", "error": str(exc)})
