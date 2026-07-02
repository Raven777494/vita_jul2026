# app/services/session_manager.py
# Session 持久化管理系統 – Redis + DB 同步

import json
import redis
import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import uuid

from app.config import config
from app.logger import get_app_logger, get_private_logger, log_session_event

logger = get_app_logger('session_manager')
session_logger = get_private_logger('session_events')

class SessionManager:
    """
    會話管理器
    
    職責：
    1. 從 Redis 快速載入活躍會話
    2. 將會話持久化到 DB（高風險或定期）
    3. 管理會話生命週期（創建→活躍→結束）
    4. 自動清理過期會話
    """
    
    def __init__(self):
        """初始化 Session Manager"""
        try:
            self.redis = redis.Redis.from_url(
                config.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=config.REDIS_TIMEOUT,
                socket_keepalive=True
            )
            
            # 測試連接
            self.redis.ping()
            logger.info("[SESSION MANAGER] Redis 連接成功")
            
        except Exception as e:
            logger.error(f"[SESSION MANAGER] Redis 連接失敗: {e}")
            self.redis = None
        
        # 會話 TTL（時間活躍）
        self.default_ttl_seconds = int(
            config.REDIS_TTL_MINUTES * 60
        ) if hasattr(config, 'REDIS_TTL_MINUTES') else 7200  # 2小時
        
        # 內存快取（若 Redis 不可用的備選方案）
        self._memory_cache: Dict[str, Dict] = {}
    
    def generate_session_id(self) -> str:
        """生成唯一的 Session ID"""
        return str(uuid.uuid4())
    
    def create_session(
        self,
        user_id: str,
        conversation_id: str
    ) -> Dict:
        """
        創建新會話
        
        Args:
            user_id: 用戶 ID
            conversation_id: 對話 ID
        
        Returns:
            Dict: 會話狀態
        """
        session_id = self.generate_session_id()
        
        session_state = {
            'session_id': session_id,
            'user_id': user_id,
            'conversation_id': conversation_id,
            'created_at': datetime.now().isoformat(),
            'last_updated_at': datetime.now().isoformat(),
            'turn_count': 0,
            'risk_level': 1,
            'walker_score': 0.5,
            'messages': [],
            'is_active': True,
            'escalation_history': []
        }
        
        # 保存到 Redis
        self._save_to_redis(user_id, conversation_id, session_state)
        
        # 記錄事件
        log_session_event(
            session_logger,
            'session_created',
            user_id,
            session_id,
            {
                'conversation_id': conversation_id
            }
        )
        
        logger.info(
            f"[SESSION CREATE] "
            f"user_id={user_id}, "
            f"session_id={session_id}"
        )
        
        return session_state
    
    def load_session(
        self,
        user_id: str,
        conversation_id: str
    ) -> Optional[Dict]:
        """
        載入會話（優先從 Redis，失敗則從內存）
        
        Args:
            user_id: 用戶 ID
            conversation_id: 對話 ID
        
        Returns:
            Dict: 會話狀態，如果不存在返回 None
        """
        key = self._build_redis_key(user_id, conversation_id)
        
        # 優先嘗試 Redis
        if self.redis:
            try:
                data = self.redis.get(key)
                if data:
                    logger.info(f"[SESSION LOAD] Redis hit: {key}")
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"[SESSION LOAD] Redis 讀取失敗: {e}")
        
        # 備選：內存快取
        if key in self._memory_cache:
            logger.info(f"[SESSION LOAD] Memory hit: {key}")
            return self._memory_cache[key]
        
        logger.warning(f"[SESSION LOAD] 會話不存在: {key}")
        return None
    
    def save_session(
        self,
        user_id: str,
        conversation_id: str,
        session_state: Dict,
        persist_to_db: bool = False
    ) -> bool:
        """
        保存會話
        
        Args:
            user_id: 用戶 ID
            conversation_id: 對話 ID
            session_state: 會話狀態
            persist_to_db: 是否同時持久化到 DB
        
        Returns:
            bool: 是否成功
        """
        session_state['last_updated_at'] = datetime.now().isoformat()
        
        # 保存到 Redis
        success = self._save_to_redis(user_id, conversation_id, session_state)
        
        if not success:
            logger.warning(f"[SESSION SAVE] Redis 保存失敗，使用內存備選")
            key = self._build_redis_key(user_id, conversation_id)
            self._memory_cache[key] = session_state
        
        # 若需要，同時持久化到 DB
        if persist_to_db:
            try:
                self._persist_to_db(user_id, conversation_id, session_state)
            except Exception as e:
                logger.error(f"[SESSION SAVE] DB 持久化失敗: {e}")
        
        return success
    
    def end_session(
        self,
        user_id: str,
        conversation_id: str,
        reason: str = 'normal',
        final_outcome: str = 'ongoing'
    ) -> bool:
        """
        結束會話
        
        Args:
            user_id: 用戶 ID
            conversation_id: 對話 ID
            reason: 結束原因 (normal/timeout/escalated/user_ended)
            final_outcome: 最終結果 (resolved/referred/ongoing)
        
        Returns:
            bool: 是否成功
        """
        session = self.load_session(user_id, conversation_id)
        
        if not session:
            logger.warning(f"[SESSION END] 會話不存在: {conversation_id}")
            return False
        
        # 標記為非活躍
        session['is_active'] = False
        session['ended_at'] = datetime.now().isoformat()
        session['end_reason'] = reason
        session['final_outcome'] = final_outcome
        
        # 強制持久化到 DB（會話結束必須記錄）
        success = self.save_session(
            user_id,
            conversation_id,
            session,
            persist_to_db=True
        )
        
        # 記錄事件
        log_session_event(
            session_logger,
            'session_ended',
            user_id,
            session['session_id'],
            {
                'reason': reason,
                'final_outcome': final_outcome,
                'turn_count': session.get('turn_count', 0)
            }
        )
        
        logger.info(
            f"[SESSION END] "
            f"user_id={user_id}, "
            f"reason={reason}, "
            f"outcome={final_outcome}"
        )
        
        return success
    
    def should_persist_to_db(self, session_state: Dict) -> bool:
        """
        判斷是否應該持久化到 DB
        
        邏輯：
        1. risk_level >= 3 → 自動持久化（高風險）
        2. walker_score < 0.5 → 自動持久化（陪伴不足）
        3. turn_count % persist_every_n_turns == 0 → 定期持久化
        4. is_escalated = True → 自動持久化
        
        Args:
            session_state: 會話狀態
        
        Returns:
            bool: 是否應該持久化
        """
        risk_level = session_state.get('risk_level', 1)
        walker_score = session_state.get('walker_score', 0.5)
        turn_count = session_state.get('turn_count', 0)
        is_escalated = session_state.get('is_escalated', False)
        
        # 高風險自動持久化
        if risk_level >= 3:
            return True
        
        # 低陪伴分數自動持久化
        if walker_score < 0.5:
            return True
        
        # 升級事件自動持久化
        if is_escalated:
            return True
        
        # 定期持久化
        persist_every_n = config.PERSIST_EVERY_N_TURNS
        if turn_count > 0 and turn_count % persist_every_n == 0:
            return True
        
        return False
    
    # ============ 私有方法 ============
    
    def _build_redis_key(self, user_id: str, conversation_id: str) -> str:
        """構建 Redis key"""
        return f"session:{user_id}:{conversation_id}"
    
    def _save_to_redis(
        self,
        user_id: str,
        conversation_id: str,
        session_state: Dict
    ) -> bool:
        """保存到 Redis（帶重試）"""
        if not self.redis:
            return False
        
        key = self._build_redis_key(user_id, conversation_id)
        
        for attempt in range(config.RETRY_ATTEMPTS):
            try:
                self.redis.set(
                    key,
                    json.dumps(session_state, ensure_ascii=False),
                    ex=self.default_ttl_seconds
                )
                logger.debug(f"[REDIS SAVE] {key}")
                return True
            
            except Exception as e:
                wait_time = [
                    config.RETRY_BACKOFF['first'],
                    config.RETRY_BACKOFF['second'],
                    config.RETRY_BACKOFF['third']
                ][attempt]
                
                logger.warning(
                    f"[REDIS SAVE] 嘗試 {attempt + 1}/{config.RETRY_ATTEMPTS} 失敗, "
                    f"等待 {wait_time}秒: {e}"
                )
                
                if attempt < config.RETRY_ATTEMPTS - 1:
                    import time
                    time.sleep(wait_time)
        
        logger.error(f"[REDIS SAVE] 最終失敗: {key}")
        return False
    
    def _persist_to_db(
        self,
        user_id: str,
        conversation_id: str,
        session_state: Dict
    ):
        """
        持久化到數據庫
        
        注意：這是一個佔位符，實際實現應該使用 SQLAlchemy
        或其他 ORM 與 DB 互動。詳見 Phase 2。
        """
        try:
            # 這裡應該有 DB 插入邏輯
            # 例如：db_manager.insert_session_history(user_id, session_state)
            logger.info(
                f"[DB PERSIST] "
                f"user_id={user_id}, "
                f"conversation_id={conversation_id}, "
                f"turn_count={session_state.get('turn_count')}"
            )
        except Exception as e:
            logger.error(f"[DB PERSIST] 失敗: {e}")
            raise
    
    def cleanup_expired_sessions(self) -> int:
        """
        清理過期會話（定時任務調用）
        
        Returns:
            int: 清理的會話數
        """
        if not self.redis:
            return 0
        
        try:
            # 掃描所有 session: 鍵
            cursor = 0
            deleted_count = 0
            
            while True:
                cursor, keys = self.redis.scan(
                    cursor,
                    match='session:*',
                    count=100
                )
                
                # Redis 會自動清理過期鍵，這裡只是清理內存快取
                for key in keys:
                    if key in self._memory_cache:
                        del self._memory_cache[key]
                        deleted_count += 1
                
                if cursor == 0:
                    break
            
            logger.info(f"[CLEANUP] 清理了 {deleted_count} 個過期會話")
            return deleted_count
        
        except Exception as e:
            logger.error(f"[CLEANUP] 清理失敗: {e}")
            return 0
    
    def get_active_high_risk_sessions(self) -> List[Dict]:
        """
        獲取所有活躍且高風險的會話（臨床團隊查詢）
        
        Returns:
            List[Dict]: 高風險會話列表
        """
        high_risk_sessions = []
        
        try:
            cursor = 0
            
            while True:
                cursor, keys = self.redis.scan(
                    cursor,
                    match='session:*',
                    count=100
                )
                
                for key in keys:
                    try:
                        data = self.redis.get(key)
                        if data:
                            session = json.loads(data)
                            
                            # 篩選：活躍 + 高風險
                            if (session.get('is_active', False) and
                                session.get('risk_level', 1) >= 4):
                                high_risk_sessions.append(session)
                    
                    except Exception as e:
                        logger.warning(f"[HIGH RISK] 解析失敗 {key}: {e}")
                
                if cursor == 0:
                    break
        
        except Exception as e:
            logger.error(f"[HIGH RISK] 查詢失敗: {e}")
        
        return high_risk_sessions
    
    def get_session_stats(self) -> Dict:
        """獲取會話統計信息"""
        try:
            info = self.redis.info('stats') if self.redis else {}
            
            stats = {
                'redis_connected': self.redis is not None,
                'memory_cache_size': len(self._memory_cache),
                'redis_info': info
            }
            
            return stats
        
        except Exception as e:
            logger.error(f"[STATS] 獲取統計失敗: {e}")
            return {}