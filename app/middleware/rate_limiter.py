# app/middleware/rate_limiter.py

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
import time
import logging
from app.config import config
import redis

logger = logging.getLogger("vita.limiter")

class RateLimiter:
    """
    簡單速率限制器 (Token Bucket 思想)
    優先使用 Redis，降級使用內存
    """
    def __init__(self):
        self.redis_client = None
        # Memory store structure: {key: (count, timestamp)}
        self.memory_store = {}
        # 安全讀取配置，預設 60
        self.rate_limit = getattr(config, 'RATE_LIMIT_REQUESTS_PER_MINUTE', 60)
        self.window = 60 # 1 minute
        
        try:
            self.redis_client = redis.Redis.from_url(
                config.REDIS_URL, 
                decode_responses=True,
                socket_connect_timeout=1
            )
            self.redis_client.ping()
        except Exception:
            self.redis_client = None
            logger.warning("Redis unavailable for RateLimiter, falling back to memory.")

    async def check_rate_limit(self, request: Request):
        # [FIX] 安全讀取 RATE_LIMIT_ENABLED，預設為 False，避免 AttributeError
        if not getattr(config, 'RATE_LIMIT_ENABLED', False):
            return

        # 識別符：優先使用 User ID (如果已認證)，否則 IP
        # 由於中間件在依賴注入前執行，無法輕易獲取 user_id，這裡使用 IP
        identifier = request.client.host if request.client else "unknown"
        
        key = f"rate_limit:{identifier}"
        current_time = int(time.time())
        window_start = current_time // self.window

        if self.redis_client:
            try:
                # Redis 原子操作
                redis_key = f"{key}:{window_start}"
                count = self.redis_client.incr(redis_key)
                if count == 1:
                    self.redis_client.expire(redis_key, self.window + 10)
                
                if count > self.rate_limit:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Rate limit exceeded"
                    )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Redis rate limit error: {e}")
                # Fallback allowed pass to avoid blocking on redis error
        else:
            # Memory implementation with expiration
            # Clean up old keys periodically or on access
            mem_key = f"{identifier}:{window_start}"
            
            # Simple cleanup of keys from different windows
            keys_to_delete = [k for k in self.memory_store if k.split(':')[1] != str(window_start)]
            for k in keys_to_delete:
                del self.memory_store[k]
            
            current_val = self.memory_store.get(mem_key, (0, current_time))
            count, timestamp = current_val
            
            # Since key includes window_start, logic is simplified
            count += 1
            self.memory_store[mem_key] = (count, current_time)
            
            if count > self.rate_limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded"
                )

rate_limiter = RateLimiter()

async def rate_limit_middleware(request: Request, call_next):
    try:
        await rate_limiter.check_rate_limit(request)
        return await call_next(request)
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": e.detail}
        )