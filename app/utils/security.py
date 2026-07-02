# app/utils/security.py

from fastapi import HTTPException, Security, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from app.config import config
import logging
import redis
import time

logger = logging.getLogger("vita.security")

# Define security schemes
security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)

# Initialize Redis for rate limiting / brute force protection
try:
    redis_client = redis.Redis.from_url(
        config.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2
    )
except Exception:
    redis_client = None
    logger.warning("Redis not available for security features")

def check_auth_failure_limit(request: Request):
    """Check if the IP is banned due to too many auth failures"""
    if not redis_client:
        return

    ip = request.client.host if request.client else "unknown"
    key = f"auth_fail:{ip}"
    
    try:
        failures = int(redis_client.get(key) or 0)
        if failures >= 5:
            logger.warning(f"IP {ip} banned due to repeated auth failures")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Too many authentication failures. Try again later."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Redis error in security check: {e}")

def record_auth_failure(request: Request):
    """Record an authentication failure for the IP"""
    if not redis_client:
        return
        
    ip = request.client.host if request.client else "unknown"
    key = f"auth_fail:{ip}"
    
    try:
        pipeline = redis_client.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, 3600) # Expire in 1 hour
        pipeline.execute()
    except Exception as e:
        logger.error(f"Redis error recording failure: {e}")

async def get_current_user(
    request: Request,
    auth: HTTPAuthorizationCredentials = Security(security),
    api_key: str = Security(api_key_header)
) -> dict:
    """
    驗證當前用戶 (JWT/API Key)
    
    Returns:
        dict: User info {'user_id': str, 'role': str}
    """
    # Check brute force protection
    check_auth_failure_limit(request)
    
    if not config.AUTH_ENABLED:
        # 如果認證被禁用（僅限開發環境），返回匿名用戶
        if not config.IS_PRODUCTION:
            return {'user_id': 'anonymous_dev', 'role': 'admin'}
    
    # 1. 驗證 Bearer Token
    if auth and auth.credentials:
        if auth.credentials == config.API_KEY:
            return {'user_id': 'system_user', 'role': 'admin'}
            
    # 2. 驗證 Header API Key
    if api_key and api_key == config.API_KEY:
        return {'user_id': 'system_user', 'role': 'admin'}
        
    # 3. 驗證失敗
    record_auth_failure(request)
    logger.warning(f"Authentication failed for IP {request.client.host if request.client else 'unknown'}")
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
