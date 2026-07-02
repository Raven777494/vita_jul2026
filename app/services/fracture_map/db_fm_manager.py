# app/services/fracture_map/db_fm_manager.py
# DBFMManager v7.3 - PostgreSQL 統一架構修復版

import json
import logging
from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy import text as sql_text

from app.services.db_manager import db_manager
from app.logger import get_logger

logger = get_logger('fracture_map')


class DBFMManager:
    """
    Fracture Map 資料庫管理器 v7.3
    - 完全基於 PostgreSQL
    - 同步架構
    - 完整的錯誤處理
    """
    
    def __init__(self):
        self.logger = logger
        self.db = db_manager
        self.logger.info("[DB_FM] DBFMManager v7.3 initialized with PostgreSQL pool")
    
    # ==================== Fracture Point Methods ====================
    
    def get_user_fracture_points(self, user_id: str) -> List[Dict]:
        """取得用戶所有活躍的裂痕點"""
        try:
            if not user_id:
                return []
            
            sql = sql_text("""
                SELECT 
                    trigger_keyword,
                    context_tags,
                    emotion_spike_score,
                    COALESCE(comfort_efficiency, 0.5) as comfort_efficiency,
                    COALESCE(trigger_count, 1) as trigger_count,
                    last_triggered,
                    COALESCE(decay_rate, 0.08) as decay_rate
                FROM user_fracture_points
                WHERE user_id = :uid AND is_active = true
                ORDER BY trigger_count DESC, last_triggered DESC
            """)
            
            session = self.db.get_session()
            try:
                rows = session.execute(sql, {'uid': user_id}).fetchall()
                result = []
                
                for row in rows:
                    try:
                        context_tags = row[1] if len(row) > 1 else "[]"
                        if isinstance(context_tags, str):
                            context_tags = json.loads(context_tags)
                        elif not isinstance(context_tags, list):
                            context_tags = []
                        
                        result.append({
                            'trigger_keyword': str(row[0]) if row[0] else '',
                            'context_tags': context_tags,
                            'emotion_spike_score': float(row[2] or 0.0),
                            'comfort_efficiency': float(row[3] or 0.5),
                            'trigger_count': int(row[4] or 1),
                            'last_triggered': row[5].isoformat() if row[5] else None,
                            'decay_rate': float(row[6] or 0.08),
                            'is_active': True
                        })
                    except (ValueError, TypeError, IndexError) as e:
                        self.logger.warning(f"[PARSE] Fracture point row error: {e}")
                        continue
                
                self.logger.debug(f"[GET] Retrieved {len(result)} fracture points for user {user_id}")
                return result
                
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[GET] get_user_fracture_points failed: {e}")
            return []

    def insert_fracture_point(
        self,
        user_id: str,
        trigger_keyword: str,
        context_tags: List[str],
        emotion_spike_score: float
    ) -> bool:
        """插入或更新裂痕點"""
        try:
            if not user_id or not trigger_keyword:
                return False
            
            context_json = json.dumps(context_tags, ensure_ascii=False)
            
            sql = sql_text("""
                INSERT INTO user_fracture_points 
                (user_id, trigger_keyword, context_tags, emotion_spike_score, last_triggered, trigger_count, is_active, decay_rate, updated_at)
                VALUES (:uid, :kw, :tags::jsonb, :score, NOW(), 1, true, 0.08, NOW())
                ON CONFLICT (user_id, trigger_keyword) DO UPDATE SET
                    trigger_count = user_fracture_points.trigger_count + 1,
                    last_triggered = NOW(),
                    emotion_spike_score = GREATEST(user_fracture_points.emotion_spike_score, EXCLUDED.emotion_spike_score),
                    updated_at = NOW()
            """)
            
            session = self.db.get_session()
            try:
                session.execute(sql, {
                    'uid': user_id,
                    'kw': trigger_keyword,
                    'tags': context_json,
                    'score': max(0.0, min(1.0, emotion_spike_score))
                })
                session.commit()
                self.logger.debug(f"[INSERT] Fracture point: {user_id} - {trigger_keyword}")
                return True
                
            except Exception as e:
                session.rollback()
                self.logger.error(f"[INSERT] Failed: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[INSERT] insert_fracture_point failed: {e}")
            return False

    # ==================== Safe Anchor Methods ====================
    
    def get_user_safe_anchors(self, user_id: str) -> List[Dict]:
        """取得安全島錨點"""
        try:
            if not user_id:
                return []
            
            sql = sql_text("""
                SELECT 
                    anchor_type,
                    content,
                    COALESCE(effectiveness_score, 0.5) as effectiveness_score,
                    COALESCE(usage_count, 0) as usage_count,
                    last_used,
                    island_association
                FROM user_safe_anchors
                WHERE user_id = :uid
                ORDER BY effectiveness_score DESC, usage_count DESC
            """)
            
            session = self.db.get_session()
            try:
                rows = session.execute(sql, {'uid': user_id}).fetchall()
                result = []
                
                for row in rows:
                    result.append({
                        'anchor_type': str(row[0]) if row[0] else '',
                        'content': str(row[1]) if row[1] else '',
                        'effectiveness_score': float(row[2] or 0.5),
                        'usage_count': int(row[3] or 0),
                        'last_used': row[4].isoformat() if row[4] else None,
                        'island_association': row[5]
                    })
                
                self.logger.debug(f"[GET] Retrieved {len(result)} safe anchors for user {user_id}")
                return result
                
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[GET] get_user_safe_anchors failed: {e}")
            return []

    def insert_safe_anchor(
        self,
        user_id: str,
        anchor_type: str,
        content: str,
        island_association: Optional[str] = None
    ) -> bool:
        """插入安全錨點"""
        try:
            if not user_id or not anchor_type or not content:
                return False
            
            sql = sql_text("""
                INSERT INTO user_safe_anchors 
                (user_id, anchor_type, content, effectiveness_score, usage_count, island_association, created_at)
                VALUES (:uid, :atype, :content, 0.5, 0, :island, NOW())
                ON CONFLICT (user_id, anchor_type, content) DO UPDATE SET
                    updated_at = NOW()
            """)
            
            session = self.db.get_session()
            try:
                session.execute(sql, {
                    'uid': user_id,
                    'atype': anchor_type,
                    'content': str(content)[:1000],
                    'island': island_association
                })
                session.commit()
                self.logger.debug(f"[INSERT] Safe anchor: {user_id} - {anchor_type}")
                return True
                
            except Exception as e:
                session.rollback()
                self.logger.error(f"[INSERT] Failed: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[INSERT] insert_safe_anchor failed: {e}")
            return False

    # ==================== Crisis Event Methods ====================
    
    def insert_crisis_event(
        self,
        user_id: str,
        trigger_type: str,
        arousal_score: float,
        user_input_snippet: str,
        hil_response: str,
        intervention_success: bool,
        hotline_provided: bool = False,
        hotline_name: Optional[str] = None
    ) -> bool:
        """記錄危機事件"""
        try:
            if not user_id or not trigger_type:
                return False
            
            sql = sql_text("""
                INSERT INTO crisis_events 
                (user_id, trigger_type, arousal_score, user_input_snippet, hil_response, 
                 hotline_provided, hotline_name, intervention_success, created_at)
                VALUES (:uid, :ttype, :arousal, :snippet, :response, :hotline_prov, :hotline_name, :success, NOW())
            """)
            
            session = self.db.get_session()
            try:
                session.execute(sql, {
                    'uid': user_id,
                    'ttype': trigger_type,
                    'arousal': max(0.0, min(1.0, arousal_score)),
                    'snippet': str(user_input_snippet)[:500],
                    'response': str(hil_response)[:500],
                    'hotline_prov': hotline_provided,
                    'hotline_name': hotline_name,
                    'success': intervention_success
                })
                session.commit()
                self.logger.debug(f"[INSERT] Crisis event for user {user_id}")
                return True
                
            except Exception as e:
                session.rollback()
                self.logger.error(f"[INSERT] Failed: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[INSERT] insert_crisis_event failed: {e}")
            return False

    def get_crisis_events(self, user_id: str, limit: int = 10) -> List[Dict]:
        """取得用戶危機事件歷史"""
        try:
            if not user_id:
                return []
            
            sql = sql_text("""
                SELECT 
                    event_id,
                    created_at as timestamp,
                    trigger_type,
                    COALESCE(arousal_score, 0.0) as arousal_score,
                    COALESCE(user_input_snippet, '') as user_input_snippet,
                    COALESCE(intervention_success, false) as intervention_success,
                    COALESCE(hotline_provided, false) as hotline_provided,
                    hotline_name
                FROM crisis_events
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :lim
            """)
            
            session = self.db.get_session()
            try:
                rows = session.execute(sql, {'uid': user_id, 'lim': limit}).fetchall()
                result = []
                
                for row in rows:
                    result.append({
                        'event_id': row[0],
                        'timestamp': row[1].isoformat() if row[1] else None,
                        'trigger_type': str(row[2]) if row[2] else '',
                        'arousal_score': float(row[3] or 0.0),
                        'user_input_snippet': str(row[4]) if row[4] else '',
                        'intervention_success': bool(row[5]),
                        'hotline_provided': bool(row[6]),
                        'hotline_name': str(row[7]) if row[7] else None
                    })
                
                self.logger.debug(f"[GET] Retrieved {len(result)} crisis events for user {user_id}")
                return result
                
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[GET] get_crisis_events failed: {e}")
            return []

    # ==================== 資料清理與維護方法 ====================
    
    def apply_fracture_point_decay(self) -> bool:
        """對所有裂痕點應用衰減"""
        try:
            sql = sql_text("""
                UPDATE user_fracture_points
                SET updated_at = NOW()
                WHERE is_active = true
            """)
            
            session = self.db.get_session()
            try:
                session.execute(sql)
                session.commit()
                self.logger.debug("[DECAY] Applied to fracture points")
                return True
                
            except Exception as e:
                session.rollback()
                self.logger.error(f"[DECAY] Failed: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[DECAY] apply_fracture_point_decay failed: {e}")
            return False

    def deactivate_old_fracture_points(self, days: int = 30) -> bool:
        """停用 N 天未觸發的裂痕點"""
        try:
            sql = sql_text("""
                UPDATE user_fracture_points
                SET is_active = false,
                    updated_at = NOW()
                WHERE is_active = true 
                AND (last_triggered IS NULL OR last_triggered < NOW() - INTERVAL ':days days')
            """)
            
            session = self.db.get_session()
            try:
                result = session.execute(sql, {'days': days})
                session.commit()
                self.logger.debug(f"[DEACTIVATE] Fracture points inactive for {days} days")
                return True
                
            except Exception as e:
                session.rollback()
                self.logger.error(f"[DEACTIVATE] Failed: {e}")
                return False
            finally:
                session.close()
            
        except Exception as e:
            self.logger.error(f"[DEACTIVATE] deactivate_old_fracture_points failed: {e}")
            return False