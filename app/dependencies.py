# app/dependencies.py

from fastapi import Depends, HTTPException, status
import logging
from typing import Optional
import redis
from redis.exceptions import ConnectionError as RedisConnectionError
import re

from app.orchestrator import Orchestrator  
from app.config import config

logger = logging.getLogger("vita.dependencies")

# 全域編排器單例
_orchestrator_instance: Optional[Orchestrator] = None
_redis_client: Optional[redis.Redis] = None


def _parse_redis_url(redis_url: str) -> dict:
    """
    安全解析 Redis URL
    支持格式：redis://host:port/db 或 redis://password@host:port/db
    
    Returns:
        dict: Redis 連接配置
    """
    try:
        # 使用正則表達式確保解析安全
        pattern = r"redis://(?:([^@]+)@)?([^:]+):(\d+)/(\d+)"
        match = re.match(pattern, redis_url)
        
        if not match:
            logger.warning(f"Redis URL format unexpected: {redis_url}")
            raise ValueError("Invalid Redis URL format")
        
        password, host, port, db = match.groups()
        
        config_dict = {
            'host': host,
            'port': int(port),
            'db': int(db),
            'decode_responses': True,
            'socket_connect_timeout': 5,
            'socket_keepalive': True,
        }
        
        if password:
            config_dict['password'] = password
        
        return config_dict
    
    except Exception as e:
        logger.error(f"Failed to parse Redis URL: {e}")
        raise


def get_redis_client() -> redis.Redis:
    """
    FastAPI 依賴注入：獲取 Redis 連接
    
    Returns:
        redis.Redis: 連接實例
        
    Raises:
        HTTPException: 連接失敗
    """
    global _redis_client
    
    if _redis_client is not None:
        return _redis_client
    
    try:
        redis_config = _parse_redis_url(config.REDIS_URL)
        _redis_client = redis.Redis(**redis_config)
        
        # 驗證連線（PING）
        _redis_client.ping()
        logger.info("✓ Redis connection verified")
        return _redis_client
    
    except RedisConnectionError as e:
        logger.error(f"Redis connection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis cache service unavailable"
        )
    except Exception as e:
        logger.error(f"Unexpected error initializing Redis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Infrastructure service initialization failed"
        )


async def get_orchestrator(redis_client: redis.Redis = Depends(get_redis_client)) -> Orchestrator:
    """
    FastAPI 依賴注入：獲取並確保編排器單例的生命週期
    ...
    """
    global _orchestrator_instance
    
    if _orchestrator_instance is None:
        try:
            # 【修復 TypeError】Orchestrator 不再直接接收 redis_client 參數
            _orchestrator_instance = Orchestrator()
            logger.info("✓ Orchestrator initialized successfully")
        
        except Exception as e:
            logger.error(f"Failed to initialize Orchestrator: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Core AI Orchestration service is currently unavailable"
            )
    
    return _orchestrator_instance


async def shutdown_dependencies():
    """
    應用關閉時清理資源
    由 main.py 的 lifespan 調用
    """
    global _orchestrator_instance, _redis_client
    
    # 關閉 Orchestrator
    if _orchestrator_instance:
        try:
            _orchestrator_instance.shutdown()
            logger.info("✓ Orchestrator shut down")
        except Exception as e:
            logger.error(f"Error during Orchestrator shutdown: {e}", exc_info=True)
    
    # 關閉 Redis
    if _redis_client:
        try:
            _redis_client.close()
            logger.info("✓ Redis client closed")
        except Exception as e:
            logger.error(f"Error closing Redis: {e}", exc_info=True)
    
    _orchestrator_instance = None
    _redis_client = None