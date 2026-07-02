# app/services/fracture_map/fracture_map_manager.py
# Fracture Map Manager v3.2 (Redis + PostgreSQL 同步優化)

import os
import json
import redis
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from functools import wraps
import math

try:
    from .db_fm_manager import DBFMManager
except ImportError:
    from db_fm_manager import DBFMManager

from app.services.db_manager import db_manager as main_db_manager, User

logger = logging.getLogger('fracture_map')
logger.info("[FRACTURE_MAP_MANAGER] Successfully imported and initialized")


class RedisConnectionError(Exception):
    """Redis 連接失敗異常"""
    pass


def handle_redis_failure(fallback_return=None):
    """
    裝飾器：處理 Redis 操作失敗時的降級方案
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except redis.RedisError as e:
                logger.warning(f"[REDIS ERROR] {func.__name__} failed: {e}")
                return fallback_return
            except Exception as e:
                logger.error(f"[ERROR] {func.__name__}: {e}")
                return fallback_return
        return wrapper
    return decorator


class FractureMapManager:
    """
    個人化裂痕地圖管理器 v3.2
    - Redis 快取層
    - PostgreSQL 持久化層
    - 錯誤恢復機制
    """
    
    def __init__(self, 
                 redis_client: Optional[redis.Redis] = None,
                 db_manager: Optional[DBFMManager] = None,
                 cache_ttl_minutes: int = 5):
        
        # 初始化 Redis
        if redis_client:
            self.redis = redis_client
        else:
            try:
                self.redis = redis.Redis(
                    host=os.getenv('REDIS_HOST', 'localhost'),
                    port=int(os.getenv('REDIS_PORT', 6379)),
                    db=int(os.getenv('REDIS_DB', 0)),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    health_check_interval=30
                )
                self.redis.ping()
                logger.info("[INIT] Redis connection established")
            except redis.ConnectionError as e:
                logger.error(f"[INIT] Redis connection failed: {e}")
                self.redis = None
        
        # 初始化 DBFMManager
        self.db = db_manager or DBFMManager()
        
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self.redis_prefix = "vita:fracture:"
        self.decay_factor_min = 0.1
        
        logger.info(f"[INIT] FractureMapManager initialized with {cache_ttl_minutes}min TTL")
    
    # ========== 快取層 ==========
    
    @handle_redis_failure(fallback_return=None)
    def _get_cached_map(self, user_id: str) -> Optional[Dict]:
        """取得快取的裂痕地圖"""
        if not self.redis:
            return None
        
        cache_key = f"{self.redis_prefix}{user_id}"
        cached_data = self.redis.get(cache_key)
        
        if cached_data:
            try:
                return json.loads(cached_data)
            except json.JSONDecodeError:
                self.redis.delete(cache_key)
                return None
        return None
    
    @handle_redis_failure(fallback_return=False)
    def _set_cache(self, user_id: str, fracture_map: Dict) -> bool:
        """設置快取"""
        if not self.redis:
            return False
        
        cache_key = f"{self.redis_prefix}{user_id}"
        try:
            self.redis.setex(
                cache_key,
                int(self.cache_ttl.total_seconds()),
                json.dumps(fracture_map, default=str)
            )
            return True
        except Exception:
            return False
    
    @handle_redis_failure(fallback_return=False)
    def _invalidate_cache(self, user_id: str) -> bool:
        """使快取失效"""
        if not self.redis:
            return False
        return self.redis.delete(f"{self.redis_prefix}{user_id}") > 0
    
    # ========== 核心方法 ==========
    
    def load_user_fracture_map(self, user_id: str, force_refresh: bool = False) -> Dict:
        """
        載入用戶的裂痕地圖
        
        Args:
            user_id: 用戶 ID
            force_refresh: 是否強制刷新快取
            
        Returns:
            裂痕地圖字典
        """
        if not force_refresh:
            cached_map = self._get_cached_map(user_id)
            if cached_map:
                return cached_map
        
        try:
            fracture_points = self.db.get_user_fracture_points(user_id)
            safe_anchors = self.db.get_user_safe_anchors(user_id)
            
            fracture_map = {
                'user_id': user_id,
                'fracture_points': fracture_points,
                'safe_anchors': safe_anchors,
                'loaded_at': datetime.now().isoformat(),
                'status': 'success'
            }
            
            self._set_cache(user_id, fracture_map)
            return fracture_map
            
        except Exception as e:
            logger.error(f"[LOAD] Map loading failed: {e}")
            return {
                'user_id': user_id,
                'fracture_points': [],
                'safe_anchors': [],
                'status': 'error'
            }
    
    def detect_fractures(self, user_id: str, user_input: str) -> List[Dict]:
        """
        檢測輸入中的裂痕點
        
        Args:
            user_id: 用戶 ID
            user_input: 用戶輸入文本
            
        Returns:
            檢測到的裂痕點列表
        """
        fracture_map = self.load_user_fracture_map(user_id)
        detected = []
        input_lower = user_input.lower()
        fracture_points = fracture_map.get('fracture_points', [])
        
        for fp in fracture_points:
            if not fp.get('is_active', True):
                continue
            
            if fp['trigger_keyword'].lower() in input_lower:
                priority = self._calculate_fracture_priority(fp)
                recommended_anchors = self.get_best_anchors(
                    user_id,
                    fp.get('context_tags', []),
                    top_k=3
                )
                
                detected.append({
                    'trigger_keyword': fp['trigger_keyword'],
                    'context_tags': fp.get('context_tags', []),
                    'priority': priority,
                    'recommended_anchors': recommended_anchors
                })
        
        detected.sort(key=lambda x: x['priority'], reverse=True)
        return detected

    def _calculate_fracture_priority(self, fracture_point: Dict) -> float:
        """計算裂痕點優先級"""
        base_priority = (
            min(1.0, fracture_point.get('trigger_count', 1) * 0.1) * 0.4 +
            fracture_point.get('emotion_spike_score', 0.5) * 0.6
        )
        
        if fracture_point.get('last_triggered'):
            try:
                last_triggered = datetime.fromisoformat(
                    fracture_point['last_triggered']
                )
                days_since = (datetime.now() - last_triggered).days
                decay_factor = max(
                    self.decay_factor_min,
                    math.exp(-fracture_point.get('decay_rate', 0.08) * days_since)
                )
                return base_priority * decay_factor
            except Exception:
                pass
        
        return base_priority

    def get_best_anchors(
        self,
        user_id: str,
        context_tags: Optional[List[str]] = None,
        top_k: int = 3
    ) -> List[Dict]:
        """
        獲取最佳安全錨點
        
        Args:
            user_id: 用戶 ID
            context_tags: 上下文標籤
            top_k: 返回數量
            
        Returns:
            錨點列表
        """
        fracture_map = self.load_user_fracture_map(user_id)
        safe_anchors = fracture_map.get('safe_anchors', [])
        
        if not safe_anchors:
            return []
        
        scored = []
        for anchor in safe_anchors:
            score = (
                anchor.get('effectiveness_score', 0.5) * 0.7 +
                (anchor.get('usage_count', 0) * 0.01) * 0.3
            )
            scored.append((score, anchor))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:top_k]]

    def register_fracture_point(
        self,
        user_id: str,
        trigger_keyword: str,
        context_tags: List[str],
        emotion_spike_score: float
    ) -> bool:
        """註冊新的裂痕點"""
        success = self.db.insert_fracture_point(
            user_id,
            trigger_keyword,
            context_tags,
            emotion_spike_score
        )
        
        if success:
            self._invalidate_cache(user_id)
        
        return success

    def register_safe_anchor(
        self,
        user_id: str,
        anchor_type: str,
        content: str,
        island_association: Optional[List[str]] = None
    ) -> bool:
        """註冊新的安全錨點"""
        success = self.db.insert_safe_anchor(
            user_id,
            anchor_type,
            content,
            island_association
        )
        
        if success:
            self._invalidate_cache(user_id)
        
        return success
    
    def log_crisis_event(
        self,
        user_id: str,
        trigger_type: str,
        arousal_score: float,
        user_input_snippet: str,
        hil_response: str,
        hotline_provided: bool
    ) -> bool:
        """記錄危機事件"""
        return self.db.insert_crisis_event(
            user_id,
            trigger_type,
            arousal_score,
            user_input_snippet,
            hil_response,
            True,
            hotline_provided
        )

    def get_intimacy_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        """獲取親密度歷史"""
        return self.db.get_crisis_events(user_id, limit)

    def get_successful_interventions_today(self, user_id: str) -> int:
        """獲取今日成功干預次數"""
        start_dt = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_dt = datetime.now().replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        
        events = self.db.get_crisis_events(user_id, limit=100)
        count = 0
        for event in events:
            try:
                event_time = datetime.fromisoformat(event.get('timestamp', ''))
                if start_dt <= event_time <= end_dt:
                    if event.get('intervention_success'):
                        count += 1
            except Exception:
                pass
        
        return count

    def sync_intimacy_to_main(self, user_id: str, intimacy_score: float) -> bool:
        """同步親密度分數到主資料庫"""
        session = main_db_manager.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                user.intimacy = max(0.0, min(1.0, intimacy_score))
                session.commit()
                logger.info(f"[SYNC] Intimacy updated: {user_id} -> {intimacy_score}")
                return True
            return False
            
        except Exception as e:
            session.rollback()
            logger.error(f"[SYNC] Failed: {e}")
            return False
        finally:
            session.close()

    def close(self) -> None:
        """關閉管理器"""
        if self.redis:
            self.redis.close()
        logger.info("[CLOSE] FractureMapManager closed")