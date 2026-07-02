# app/services/cache_manager.py
# Redis 快取層（可選）

import json
import logging
from typing import Any, Optional

logger = logging.getLogger('cache_manager')


class CacheManager:
    """
    Redis 快取管理器（用於 GSWEngine）
    
    用途：
    - 緩存 core_memories 和 semantic_atoms（TTL=1小時）
    - 緩存相似度計算結果
    - 加速初始化
    """
    
    def __init__(self, redis_client=None, enable_compression: bool = False):
        """
        初始化快取管理器
        
        Args:
            redis_client: Redis 連接對象
            enable_compression: 是否啟用壓縮（大數據推薦）
        """
        self.redis = redis_client
        self.enable_compression = enable_compression
        self.enabled = redis_client is not None
        
        if self.enabled:
            logger.info("✅ CacheManager initialized with Redis")
        else:
            logger.warning("⚠️  CacheManager: Redis not available (cache disabled)")
    
    def get(self, key: str) -> Optional[Any]:
        """
        從快取獲取值
        
        Args:
            key: 快取鍵
            
        Returns:
            快取值或 None
        """
        if not self.enabled:
            return None
        
        try:
            data = self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"⚠️  Cache get failed for {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """
        設置快取值
        
        Args:
            key: 快取鍵
            value: 要存儲的值
            ttl: 存活時間（秒）
            
        Returns:
            是否成功
        """
        if not self.enabled:
            return False
        
        try:
            data = json.dumps(value, ensure_ascii=False)
            
            if self.enable_compression and len(data) > 10000:
                # 如果數據大於 10KB，考慮壓縮
                logger.debug(f"💾 Compressing cache data for {key}")
            
            self.redis.setex(key, ttl, data)
            logger.debug(f"✅ Cache set: {key} (ttl={ttl}s)")
            return True
        
        except Exception as e:
            logger.warning(f"⚠️  Cache set failed for {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """刪除快取"""
        if not self.enabled:
            return False
        
        try:
            self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning(f"⚠️  Cache delete failed: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """
        刪除匹配模式的所有快取
        
        Args:
            pattern: 模式（如 "gsw:*"）
            
        Returns:
            刪除的鍵個數
        """
        if not self.enabled:
            return 0
        
        try:
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
                logger.info(f"🗑️  Cleared {len(keys)} cache keys matching {pattern}")
                return len(keys)
            return 0
        except Exception as e:
            logger.warning(f"⚠️  Cache clear failed: {e}")
            return 0
    
    def get_stats(self) -> Dict:
        """獲取快取統計信息"""
        if not self.enabled:
            return {'enabled': False}
        
        try:
            info = self.redis.info()
            return {
                'enabled': True,
                'used_memory': info.get('used_memory_human', 'unknown'),
                'connected_clients': info.get('connected_clients', 0),
                'total_commands': info.get('total_commands_processed', 0)
            }
        except Exception as e:
            logger.warning(f"⚠️  Stats retrieval failed: {e}")
            return {'enabled': True, 'error': str(e)}