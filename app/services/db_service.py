# app/services/db_service.py - 修正版 v3.8.1
"""
Vita 2.0 - 數據庫服務層
完全基於 app.services.db_manager (SQLAlchemy) 運作
"""

import logging
from typing import Dict, Optional, List, Any
from datetime import datetime
import uuid

from app.services.db_manager import (
    db_manager, User, ActiveSession, Turn, 
    FractureMap, PsychAssessment, EscalationEvent, 
    Reminder, RiskAssessment, SessionHistory
)

logger = logging.getLogger('vita.db_service')

class DBService:
    """數據庫服務層包裝器"""
    
    def __init__(self):
        self.db = db_manager
        logger.info("[DB SERVICE] Linked to unified DatabaseManager [OK]")

    def close(self):
        """關閉數據庫連接"""
        if hasattr(self.db, 'close'):
            self.db.close()

    # ==================== 用戶與會話管理 ====================

    def get_or_create_user(self, user_id: str, alias: Optional[str] = None) -> Dict:
        """獲取或創建用戶"""
        session = self.db.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                user = User(id=user_id, alias=alias)
                session.add(user)
                session.commit()
            
            return {
                'user_id': user.id,
                'alias': user.alias,
                'trust_score': user.trust_score
            }
        except Exception as e:
            logger.error(f"get_or_create_user failed: {e}")
            session.rollback()
            return None
        finally:
            session.close()

    def create_session(self, user_id: str, active_persona='friend', temperature=0.7) -> str:
        """創建新會話"""
        session = self.db.get_session()
        try:
            # 確保用戶存在
            if not session.query(User).filter_by(id=user_id).first():
                self.get_or_create_user(user_id)

            new_session = ActiveSession(
                user_id=user_id,
                session_metadata={
                    'active_persona': active_persona,
                    'temperature': temperature
                }
            )
            session.add(new_session)
            session.commit()
            return str(new_session.session_id)
        except Exception as e:
            logger.error(f"create_session failed: {e}")
            session.rollback()
            return None
        finally:
            session.close()

    def get_session(self, session_id: str) -> Optional[Dict]:
        """獲取會話詳情"""
        session = self.db.get_session()
        try:
            # UUID 轉換
            try:
                if isinstance(session_id, str):
                    uuid_obj = uuid.UUID(session_id)
                else:
                    uuid_obj = session_id
            except (ValueError, AttributeError):
                return None

            sess_obj = session.query(ActiveSession).filter_by(session_id=uuid_obj).first()
            if not sess_obj:
                return None
            
            meta = sess_obj.session_metadata or {}
            return {
                'session_id': str(sess_obj.session_id),
                'user_id': sess_obj.user_id,
                'active_persona': meta.get('active_persona', 'friend'),
                'temperature': meta.get('temperature', 0.7),
                'risk_level': sess_obj.risk_level,
                'turn_count': sess_obj.turn_count,
                'created_at': sess_obj.created_at.isoformat() if sess_obj.created_at else None
            }
        except Exception as e:
            logger.error(f"get_session failed: {e}")
            return None
        finally:
            session.close()

    def find_active_session_by_user(self, user_id: str) -> Optional[str]:
        """查找用戶的活躍會話"""
        session = self.db.get_session()
        try:
            sess = session.query(ActiveSession).filter_by(
                user_id=user_id, 
                is_active=True
            ).order_by(ActiveSession.last_updated_at.desc()).first()
            return str(sess.session_id) if sess else None
        except Exception as e:
            logger.error(f"find_active_session_by_user failed: {e}")
            return None
        finally:
            session.close()

    # ==================== 對話存儲 ====================

    def store_turn(self, session_id: str, user_id: str, role: str, text: str, 
                   emotions_vsc: dict = None, risk_level: int = 0, safety_audit: dict = None,
                   embedding: Optional[List[float]] = None,
                   emotion_vector: Optional[Dict] = None,
                   butterfly_impact: float = 0.0,
                   metadata: Optional[Dict] = None) -> bool:
        """存儲對話輪次"""
        session = self.db.get_session()
        try:
            try:
                if isinstance(session_id, str):
                    uuid_obj = uuid.UUID(session_id)
                else:
                    uuid_obj = session_id
            except (ValueError, AttributeError):
                logger.error(f"Invalid session_id format: {session_id}")
                return False

            active_sess = session.query(ActiveSession).filter_by(session_id=uuid_obj).first()
            current_turn_count = 0
            if active_sess:
                active_sess.last_updated_at = datetime.utcnow()
                active_sess.turn_count += 1
                current_turn_count = active_sess.turn_count
                if risk_level > active_sess.risk_level:
                    active_sess.risk_level = risk_level

            new_turn = Turn(
                session_id=uuid_obj,
                user_id=user_id,
                role=role,
                text=text,
                emotions_vsc=emotions_vsc or {},
                risk_level=risk_level,
                safety_audit=safety_audit or {},
                session_seq=current_turn_count,
                embedding=embedding,
                emotion_vector=emotion_vector or {},
                butterfly_impact=butterfly_impact,
                metadata_dict=metadata or {}
            )
            session.add(new_turn)
            session.commit()
            return True
        except Exception as e:
            logger.error(f"store_turn failed: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    def get_session_turns(self, session_id: str, limit: int = 20) -> List[Dict]:
        """獲取會話的歷史對話"""
        session = self.db.get_session()
        try:
            try:
                if isinstance(session_id, str):
                    uuid_obj = uuid.UUID(session_id)
                else:
                    uuid_obj = session_id
            except (ValueError, AttributeError):
                return []

            turns = session.query(Turn).filter_by(session_id=uuid_obj)\
                          .order_by(Turn.turn_id.asc())\
                          .limit(limit).all()
            
            return [{
                'role': t.role,
                'content': t.text,
                'timestamp': t.created_at.isoformat() if t.created_at else None
            } for t in turns]
        except Exception as e:
            logger.error(f"get_session_turns failed: {e}")
            return []
        finally:
            session.close()

    # ==================== 心理評估 ====================

    def create_or_update_psych_assessment(self, user_id: str, phase_stage: int = None, joker_patterns: Dict = None, shame_triggers: Dict = None) -> bool:
        session = self.db.get_session()
        try:
            assessment = session.query(PsychAssessment).filter_by(user_id=user_id).first()
            if not assessment:
                assessment = PsychAssessment(
                    user_id=user_id, phase_stage=phase_stage or 1,
                    joker_patterns=joker_patterns or {}, shame_triggers=shame_triggers or {}
                )
                session.add(assessment)
            else:
                if phase_stage is not None:
                    assessment.phase_stage = phase_stage
                if joker_patterns:
                    current = dict(assessment.joker_patterns or {})
                    for key, val in joker_patterns.items():
                        if key in current:
                            if isinstance(current[key], dict) and isinstance(val, dict):
                                current[key]['count'] = current[key].get('count', 0) + val.get('count', 1)
                                current[key]['last_seen'] = datetime.utcnow().isoformat()
                        else:
                            current[key] = val
                    assessment.joker_patterns = current
                if shame_triggers:
                    current = dict(assessment.shame_triggers or {})
                    for key, val in shame_triggers.items():
                        if key in current:
                            if isinstance(current[key], dict) and isinstance(val, dict):
                                current[key]['times'] = current[key].get('times', 0) + val.get('times', 1)
                                current[key]['last'] = datetime.utcnow().isoformat()
                        else:
                            current[key] = val
                    assessment.shame_triggers = current
                assessment.last_update = datetime.utcnow()
            
            session.commit()
            return True
        except Exception as e:
            logger.error(f"create_or_update_psych_assessment failed: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    # ==================== Fracture Map ====================

    def get_fracture_map(self) -> Dict[str, Dict]:
        session = self.db.get_session()
        try:
            maps = session.query(FractureMap).all()
            if not maps:
                return {}
            result = {}
            for m in maps:
                result[m.fracture_name] = {
                    'description': m.description, 'keywords': m.keywords,
                    'risk_indicators': m.risk_indicators, 'intervention_prompts': m.intervention_prompts,
                    'clinical_guidelines': m.clinical_guidelines, 'severity_level': m.severity_level
                }
            return result
        except Exception as e:
            logger.error(f"get_fracture_map failed: {e}")
            return {}
        finally:
            session.close()

    def search_fracture_by_keywords(self, keywords: List[str]) -> List[Dict]:
        if not keywords: return []
        session = self.db.get_session()
        try:
            results = session.query(FractureMap).all()
            formatted = []
            for fracture in results:
                if any(kw in fracture.keywords for kw in keywords):
                    formatted.append({
                        'fracture_type': fracture.fracture_name, 'description': fracture.description,
                        'keywords': fracture.keywords, 'risk_indicators': fracture.risk_indicators,
                        'intervention_prompts': fracture.intervention_prompts, 'severity_level': fracture.severity_level
                    })
            return formatted
        except Exception as e:
            logger.error(f"search_fracture_by_keywords failed: {e}")
            return []
        finally:
            session.close()
            
    # ==================== 危機事件管理 ====================

    def create_escalation_event(self, session_id: str, turn_number: int, reason: str, risk_level: int, walker_score: float, escalated_to: str) -> bool:
        session = self.db.get_session()
        try:
            try:
                uuid_obj = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            except (ValueError, AttributeError):
                return False

            event = EscalationEvent(session_id=uuid_obj, turn_number=turn_number, escalation_reason=reason, risk_level=risk_level, walker_score=walker_score, escalated_to=escalated_to)
            session.add(event)
            session.commit()
            return True
        except Exception as e:
            logger.error(f"create_escalation_event failed: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    def log_risk_assessment(self, session_id: str, turn_number: int, risk_assessment: Dict) -> Optional[int]:
        session = self.db.get_session()
        try:
            try:
                uuid_obj = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            except (ValueError, AttributeError):
                return None

            record = RiskAssessment(session_id=uuid_obj, turn_number=turn_number, risk_level=risk_assessment.get('risk_level', 0), flags=risk_assessment.get('flags', []), confidence=risk_assessment.get('confidence', 0.0))
            session.add(record)
            session.commit()
            return record.id
        except Exception as e:
            logger.error(f"log_risk_assessment failed: {e}")
            session.rollback()
            return None
        finally:
            session.close()

    def store_embedding(self, record_id: int, embedding: List[float]):
        session = self.db.get_session()
        try:
            record = session.query(RiskAssessment).get(record_id)
            if record:
                record.embedding = embedding
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def store_emotion_vector(self, record_id: int, emotion_vector: Dict):
        session = self.db.get_session()
        try:
            record = session.query(RiskAssessment).get(record_id)
            if record:
                record.emotion_vector = emotion_vector
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    # ==================== 提醒管理 ====================

    def create_reminder(self, user_id: str, reminder_text: str, target_datetime: datetime, context: Optional[str] = None) -> Optional[int]:
        session = self.db.get_session()
        try:
            reminder = Reminder(user_id=user_id, reminder_text=reminder_text, target_datetime=target_datetime, context={'original_text': context} if context else {})
            session.add(reminder)
            session.commit()
            return reminder.reminder_id
        except Exception:
            session.rollback()
            return None
        finally:
            session.close()

    def get_pending_reminders(self, user_id: str) -> List[Dict]:
        session = self.db.get_session()
        try:
            reminders = session.query(Reminder).filter(Reminder.user_id == user_id, Reminder.is_triggered == False, Reminder.target_datetime <= datetime.utcnow()).all()
            return [{'reminder_id': r.reminder_id, 'reminder_text': r.reminder_text, 'target_datetime': r.target_datetime.isoformat()} for r in reminders]
        except Exception:
            return []
        finally:
            session.close()

    def mark_reminders_triggered(self, reminder_ids: List[int]):
        session = self.db.get_session()
        try:
            session.query(Reminder).filter(Reminder.reminder_id.in_(reminder_ids)).update({Reminder.is_triggered: True}, synchronize_session=False)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    # ==================== 代理方法 ====================

    def health_check(self):
        return self.db.health_check()
        
    def get_db_stats(self):
        return self.db.get_db_stats()
        
    def get_active_prompt_version(self):
        return {
            'version_id': 'v1.0-default',
            'prompt_text': '你是一個溫柔、有同理心的 AI 伴侶。'
        }

# 全局實例
db_service = DBService()