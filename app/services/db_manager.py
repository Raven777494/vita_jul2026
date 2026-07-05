# app/services/db_manager.py
# 數據庫管理系統 – PostgreSQL + SQLAlchemy + pgvector (Unified Core with Async)

import os
import logging
import re
from typing import Dict, Optional, List, Tuple, Any
from datetime import datetime, timedelta
import json
from enum import Enum
import uuid
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, 
    Boolean, Float, JSON, ForeignKey, Index, event,
    select, and_, or_, desc, func, inspect,
    text as sql_text, CheckConstraint
)
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.orm import (
    sessionmaker, scoped_session, declarative_base, 
    relationship, Session
)
from sqlalchemy.pool import QueuePool, NullPool, AsyncAdaptedQueuePool
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID, JSONB
from pgvector.sqlalchemy import Vector

from app.config import config
from app.logger import get_app_logger, get_private_logger

# ==================== 日誌設置 ====================

db_logger = get_app_logger('db_manager')
session_logger = get_private_logger('session_db')
audit_logger = get_private_logger('audit')

# ==================== 全局 SQLAlchemy 設置 ====================

Base = declarative_base()

# ==================== 同步引擎配置 ====================

# 安全獲取連接池參數，確保即使 Config 類異常也能正常啟動
_pool_size = getattr(config, 'DB_POOL_SIZE', 10)
_max_overflow = getattr(config, 'DB_MAX_OVERFLOW', 20)
_pool_timeout = getattr(config, 'DB_POOL_TIMEOUT', 30)
_pool_recycle = getattr(config, 'DB_POOL_RECYCLE', 3600)
_pool_pre_ping = getattr(config, 'DB_POOL_PRE_PING', True)
_db_auto_flush = getattr(config, 'DB_AUTO_FLUSH', False)
_db_expire_on_commit = getattr(config, 'DB_EXPIRE_ON_COMMIT', False)

if config.ENV == 'test':
    sync_engine = create_engine(
        config.DATABASE_URL,
        echo=False,
        poolclass=NullPool
    )
else:
    sync_engine = create_engine(
        config.DATABASE_URL,
        echo=False,
        poolclass=QueuePool,
        pool_size=_pool_size,
        max_overflow=_max_overflow,
        pool_timeout=_pool_timeout,
        pool_recycle=_pool_recycle,
        pool_pre_ping=_pool_pre_ping
    )

SessionLocal = scoped_session(
    sessionmaker(
        bind=sync_engine,
        autocommit=False,
        autoflush=_db_auto_flush,
        expire_on_commit=_db_expire_on_commit
    )
)

# ==================== 非同步引擎配置 ====================

# 將同步連接字符串轉換為非同步格式
async_database_url = config.DATABASE_URL.replace(
    'postgresql+psycopg2://', 
    'postgresql+asyncpg://'
)

async_engine = create_async_engine(
    async_database_url,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_timeout=_pool_timeout,
    pool_pre_ping=_pool_pre_ping
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=_db_auto_flush,
    expire_on_commit=_db_expire_on_commit
)

# ==================== 自動創建 pgvector 擴展 ====================

@event.listens_for(sync_engine, "connect")
def enable_pgvector_sync(dbapi_connection, connection_record):
    try:
        with dbapi_connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        dbapi_connection.commit()
    except Exception as e:
        db_logger.warning(f"[PGVECTOR] Sync engine note: {e}")

# ==================== 數據庫模型定義 ====================

class User(Base):
    """用戶表 - 核心基礎表"""
    __tablename__ = 'users'
    
    id = Column("id", String(255), primary_key=True, index=True) 
    
    alias = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)
    
    # 擴展屬性
    trust_score = Column(Float, default=0.0, server_default=sql_text("0.0"))
    thought_fingerprint = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    dark_triad_scores = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    session_metadata = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    intimacy = Column(Float, default=0.0, server_default=sql_text("0.0"))
    total_turns = Column(Integer, default=0, server_default=sql_text("0"))
    total_sessions = Column(Integer, default=0, server_default=sql_text("0"))

    # 建立與其他表的關係
    sessions = relationship("ActiveSession", back_populates="user", cascade="all, delete-orphan")
    assessments = relationship("PsychAssessment", back_populates="user", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="user", cascade="all, delete-orphan")
    memory_nodes = relationship("MemoryGraphNode", back_populates="user", cascade="all, delete-orphan")
    fracture_points = relationship("UserFracturePoint", back_populates="user", cascade="all, delete-orphan")
    safe_anchors = relationship("UserSafeAnchor", back_populates="user", cascade="all, delete-orphan")
    crisis_events = relationship("CrisisEvent", back_populates="user", cascade="all, delete-orphan")
    echoes = relationship("GSWEternalEcho", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, trust={self.trust_score})>"


class Turn(Base):
    """對話輪次表 (含 Vector)"""
    __tablename__ = 'turns'
    
    turn_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(PG_UUID(as_uuid=True), ForeignKey('active_sessions.session_id', ondelete='CASCADE'), index=True)
    
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    
    session_seq = Column(Integer)
    role = Column(String(20))
    
    text = Column(Text)
    
    # 情感與向量
    emotions_vsc = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    valence = Column(Float)
    arousal = Column(Float)
    embedding = Column(Vector(1024), nullable=True)
    emotion_vector = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    
    # 風險與審計
    risk_level = Column(Integer, default=0)
    safety_audit = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    butterfly_impact = Column(Float, default=0.0, server_default=sql_text("0.0")) 
    metadata_dict = Column("metadata", JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_turn_session_id', 'session_id'),
        Index('idx_turn_user_id', 'user_id'),
        Index('idx_turn_created_at', 'created_at'),
    )


class PsychAssessment(Base):
    """心理評估表 (逆向小丑系統核心)"""
    __tablename__ = 'psych_assessments'
    
    assessment_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    
    phase_stage = Column(Integer, default=1)
    
    # 核心心理映射
    joker_patterns = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb")) 
    shame_triggers = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb")) 
    
    # 逆向小丑系統擴展欄位 (Reverse Joker System 12 Tables)
    dark_triad = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    attachment_style = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    sexualization_index = Column(Float, default=0.0)
    trauma_bond_risk = Column(Float, default=0.0)
    genuine_help_intent = Column(Float, default=0.0)
    butterfly_prediction = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    manipulation_tactics = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    inner_void_index = Column(Float, default=0.0)
    positive_glimmers = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    emotion_regulation_capacity = Column(Float, default=0.5)
    defense_mechanisms_usage = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    detox_progress = Column(Float, default=0.0)
    
    user_category = Column(String(10))
    reverse_joker_stage = Column(Integer, default=1)
    
    last_update = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="assessments")

    __table_args__ = (
        Index('idx_psych_joker_gin', 'joker_patterns', postgresql_using='gin'),
        Index('idx_psych_shame_gin', 'shame_triggers', postgresql_using='gin'),
        Index('idx_psych_user_phase', 'user_id', 'phase_stage'),
        Index('idx_psych_user_updated', 'user_id', 'last_update'), 
        CheckConstraint('detox_progress >= 0 AND detox_progress <= 100', name='check_detox_progress_range'),
    )

    def __repr__(self):
        return f"<PsychAssessment(user={self.user_id}, phase={self.phase_stage})>"


class ActiveSession(Base):
    """活躍會話表"""
    __tablename__ = 'active_sessions'
    
    session_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    conversation_id = Column(String(255), nullable=True)

    user = relationship("User", back_populates="sessions")

    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    turn_count = Column(Integer, default=0)
    risk_level = Column(Integer, default=1)
    walker_score = Column(Float, default=0.5)
    is_active = Column(Boolean, default=True)
    is_escalated = Column(Boolean, default=False)
    
    messages = Column(JSON, default=[])
    session_metadata = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))


class SessionHistory(Base):
    """會話歷史存檔"""
    __tablename__ = 'session_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(PG_UUID(as_uuid=True), unique=True, index=True)
    user_id = Column(String(255), index=True)
    created_at = Column(DateTime)
    ended_at = Column(DateTime, default=datetime.utcnow)
    end_reason = Column(String(50))
    peak_risk_level = Column(Integer)
    is_escalated = Column(Boolean)
    session_summary = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))


class FractureMap(Base):
    """Fracture Map (危機地圖)"""
    __tablename__ = 'fracture_maps'
    
    fracture_id = Column(Integer, primary_key=True, autoincrement=True)
    fracture_name = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text)
    severity_level = Column(Integer, default=1)
    keywords = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    risk_indicators = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    intervention_prompts = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    clinical_guidelines = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EscalationEvent(Base):
    """升級事件"""
    __tablename__ = 'escalation_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(PG_UUID(as_uuid=True))
    risk_level = Column(Integer)
    escalation_reason = Column(String(255))
    walker_score = Column(Float, default=0.0)
    escalated_to = Column(String(50))
    escalation_status = Column(String(50), default='pending', server_default=sql_text("'pending'"))
    escalated_at = Column(DateTime, default=datetime.utcnow)
    escalation_confirmed = Column(Boolean, default=False)
    turn_number = Column(Integer, default=0)


class SystemError(Base):
    """系統錯誤"""
    __tablename__ = 'system_errors'
    id = Column(Integer, primary_key=True, autoincrement=True)
    error_type = Column(String(50))
    error_message = Column(Text)
    resolved = Column(Boolean, default=False)
    occurred_at = Column(DateTime, default=datetime.utcnow)


class Reminder(Base):
    """提醒/承諾表"""
    __tablename__ = 'reminders'
    reminder_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    reminder_text = Column(Text)
    target_datetime = Column(DateTime)
    context = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    is_triggered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="reminders")


class RiskAssessment(Base):
    """風險評估記錄"""
    __tablename__ = 'risk_assessments'
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(PG_UUID(as_uuid=True), ForeignKey('active_sessions.session_id', ondelete='CASCADE'), index=True)
    turn_number = Column(Integer)
    risk_level = Column(Integer)
    flags = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    confidence = Column(Float)
    embedding = Column(Vector(1024), nullable=True)
    emotion_vector = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow)


class ActionCard(Base):
    """逆向小丑劇本卡片"""
    __tablename__ = 'action_cards'
    card_id = Column(Integer, primary_key=True, autoincrement=True)
    stage = Column(Integer, index=True)
    title = Column(String(100))
    content = Column(Text)
    target_emotions = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    trigger_conditions = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryGraphNode(Base):
    """黑曜石蓮花機制 (Memory Graph)"""
    __tablename__ = 'memory_graph'
    node_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    node_type = Column(String(50))
    content = Column(Text)
    attributes = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    connections = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    status = Column(String(20), default='active')
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="memory_nodes")


class JudgmentLog(Base):
    """深夜審判室執行日誌"""
    __tablename__ = 'judgment_room_logs'
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(20), index=True)
    processed_users = Column(Integer, default=0)
    duration_sec = Column(Float, default=0.0)
    anomalies = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow)


class GSWEternalEcho(Base):
    """GSW 永恆迴響表 (Memory Storage for GSWEngine)"""
    __tablename__ = 'gsw_eternal_echoes'
    
    id = Column(String(255), primary_key=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    user_input = Column(Text)
    response = Column(Text)
    content = Column(Text)
    embedding = Column(Vector(1024), nullable=True)
    echo_score = Column(Float, default=0.0)
    weight = Column(Float, default=1.0)
    metadata_dict = Column("metadata", JSONB, default={}, server_default=sql_text("'{}'::jsonb"))  # 改這裡
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="echoes")
    
    __table_args__ = (
        Index('idx_gsw_user_id', 'user_id'),
        # HNSW index: created by DatabaseManager._ensure_gsw_hnsw_index (init-db + bootstrap)
        Index('idx_gsw_created_at', 'created_at'),
    )


class UserFracturePoint(Base):
    """用戶斷裂點表"""
    __tablename__ = 'user_fracture_points'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    trigger_keyword = Column(String(255))
    context_tags = Column(JSONB, default=[], server_default=sql_text("'[]'::jsonb"))
    emotion_spike_score = Column(Float, default=0.0)
    comfort_efficiency = Column(Float, default=0.5)
    last_triggered = Column(DateTime, nullable=True)
    decay_rate = Column(Float, default=0.08)
    trigger_count = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="fracture_points")

    __table_args__ = (
        Index('idx_fracture_user_active', 'user_id', 'is_active'),
        Index('idx_fracture_keyword', 'trigger_keyword'),
    )


class UserSafeAnchor(Base):
    """用戶安全錨點表"""
    __tablename__ = 'user_safe_anchors'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    anchor_type = Column(String(50))
    content = Column(Text)
    effectiveness_score = Column(Float, default=0.5)
    usage_count = Column(Integer, default=0)
    last_used = Column(DateTime, nullable=True)
    island_association = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="safe_anchors")

    __table_args__ = (
        Index('idx_anchor_user_type', 'user_id', 'anchor_type'),
    )


class CrisisEvent(Base):
    """危機事件表"""
    __tablename__ = 'crisis_events'
    
    event_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    trigger_type = Column(String(100))
    arousal_score = Column(Float, default=0.0)
    user_input_snippet = Column(Text)
    hil_response = Column(Text)
    hotline_provided = Column(Boolean, default=False)
    hotline_name = Column(String(100), nullable=True)
    additional_context = Column(Text, nullable=True)
    intervention_success = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="crisis_events")

    __table_args__ = (
        Index('idx_crisis_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_crisis_trigger_type', 'trigger_type'),
    )


class UserNavigationHistory(Base):
    """導航歷史記錄"""
    __tablename__ = 'user_navigation_history'
    
    history_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    fracture_detected = Column(String(255), nullable=True)
    fast_think_decision = Column(Text, nullable=True)
    slow_think_decision = Column(Text, nullable=True)
    final_decision = Column(Text, nullable=True)
    user_satisfaction = Column(Float, nullable=True)
    
    user = relationship("User", backref="navigation_history")


class IntimacyTimeline(Base):
    """親密度時間線"""
    __tablename__ = 'intimacy_timeline'
    
    record_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    intimacy_score = Column(Float, nullable=False)
    intimacy_delta = Column(Float, nullable=True)
    change_reason = Column(String(255), nullable=True)
    
    user = relationship("User", backref="intimacy_records")


class UserShadowState(Base):
    """User Shadow 持久化 — pain / trust / hope / loneliness (Phase 5)."""
    __tablename__ = 'user_shadow_state'

    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    pain = Column(Float, default=0.0, server_default=sql_text("0.0"))
    trust = Column(Float, default=0.5, server_default=sql_text("0.5"))
    hope = Column(Float, default=0.5, server_default=sql_text("0.5"))
    loneliness = Column(Float, default=0.0, server_default=sql_text("0.0"))
    emotion_snapshot = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    last_session_id = Column(PG_UUID(as_uuid=True), nullable=True)
    turn_count = Column(Integer, default=0, server_default=sql_text("0"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="shadow_state")


class PsychologicalMilestone(Base):
    """關係記憶 / 心理里程碑 (Phase 5)."""
    __tablename__ = 'psychological_milestones'

    milestone_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    session_id = Column(PG_UUID(as_uuid=True), nullable=True, index=True)
    milestone_type = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(Integer, default=1, server_default=sql_text("1"))
    meta = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", backref="psychological_milestones")

    __table_args__ = (
        Index('idx_milestone_user_type', 'user_id', 'milestone_type'),
    )


class RealityFact(Base):
    """KAG Reality Layer — verifiable subject-predicate-object facts."""
    __tablename__ = 'reality_facts'

    fact_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=True)
    subject = Column(String(64), nullable=False, index=True)
    predicate = Column(String(128), nullable=False, index=True)
    object_value = Column(Text, nullable=False)
    confidence = Column(Float, default=0.8, server_default=sql_text("0.8"))
    source = Column(String(64), default='user_statement', server_default=sql_text("'user_statement'"))
    session_id = Column(PG_UUID(as_uuid=True), nullable=True)
    meta = Column(JSONB, default={}, server_default=sql_text("'{}'::jsonb"))
    is_seed = Column(Boolean, default=False, server_default=sql_text("false"))
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="reality_facts")

    __table_args__ = (
        Index('idx_reality_user_subject', 'user_id', 'subject'),
        Index('idx_reality_subject_predicate', 'subject', 'predicate'),
    )

# HNSW params for gsw_eternal_echoes (cosine; aligned with search_vector_similarity_async)
_GSW_HNSW_INDEX_NAME = "idx_gsw_embedding_hnsw"
_GSW_LEGACY_IVFFLAT_INDEX = "idx_gsw_embedding"
_GSW_HNSW_M = 16
_GSW_HNSW_EF_CONSTRUCTION = 200

_AGE_GRAPH_NAME = "vita_memory_graph"
_PGCRON_JOB_NAME = "clean-old-gsw-echoes"
_PLATFORM_EXTENSIONS = ("vector", "age", "pg_cron")


# ==================== 數據庫管理器類 (Unified Sync) ====================

class DatabaseManager:
    """
    同步數據庫管理器 - 單一真理來源
    """
    
    def __init__(self):
        self._ready = False
        try:
            inspector = inspect(sync_engine)
            existing_tables = inspector.get_table_names()
            
            required_tables = [
                'users', 'active_sessions', 'turns', 
                'fracture_maps', 'psych_assessments',
                'escalation_events', 'reminders', 'risk_assessments',
                'action_cards', 'memory_graph', 'judgment_room_logs',
                'session_history', 'system_errors', 'gsw_eternal_echoes',
                'user_fracture_points', 'user_safe_anchors', 'crisis_events',
                'user_navigation_history', 'intimacy_timeline',
                'user_shadow_state', 'psychological_milestones',
                'reality_facts',
            ]
            
            missing = [t for t in required_tables if t not in existing_tables]
            
            if missing:
                db_logger.warning(f"[DB INIT] 檢測到缺失表格: {missing}，正在創建...")
                Base.metadata.create_all(bind=sync_engine)
                db_logger.info("[DB INIT] 缺失表格創建完成")
            else:
                db_logger.info("[DB INIT] 所有關鍵表格已存在")
            
            self.init_fracture_map()
            self.init_action_cards()
            self._ensure_platform_extensions()
            self._ensure_gsw_hnsw_index()
            self._ensure_age_graph()
            self._ensure_pg_cron_jobs()
            
            db_logger.info("[DB INIT] Database initialized successfully [OK]")
            self._ready = True
            
        except Exception as e:
            db_logger.error(f"[DB INIT] Failed: {e}", exc_info=True)
            self._ready = False
    
    def _ensure_gsw_hnsw_index(self) -> None:
        """Ensure gsw_eternal_echoes uses HNSW (cosine), replacing legacy IVFFlat index."""
        try:
            inspector = inspect(sync_engine)
            if "gsw_eternal_echoes" not in inspector.get_table_names():
                db_logger.debug("[DB INIT] gsw_eternal_echoes absent; skip HNSW ensure")
                return

            index_names = {idx["name"] for idx in inspector.get_indexes("gsw_eternal_echoes")}

            if _GSW_HNSW_INDEX_NAME in index_names:
                if _GSW_LEGACY_IVFFLAT_INDEX in index_names:
                    self.execute_update(f"DROP INDEX IF EXISTS {_GSW_LEGACY_IVFFLAT_INDEX}")
                    db_logger.info(
                        f"[DB INIT] Dropped legacy index {_GSW_LEGACY_IVFFLAT_INDEX}"
                    )
                db_logger.info(f"[DB INIT] HNSW index {_GSW_HNSW_INDEX_NAME} present [OK]")
                return

            self.execute_update(f"DROP INDEX IF EXISTS {_GSW_LEGACY_IVFFLAT_INDEX}")
            self.execute_update(
                f"""
                CREATE INDEX IF NOT EXISTS {_GSW_HNSW_INDEX_NAME}
                ON gsw_eternal_echoes
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = {_GSW_HNSW_M}, ef_construction = {_GSW_HNSW_EF_CONSTRUCTION})
                WHERE embedding IS NOT NULL
                """
            )
            db_logger.info(f"[DB INIT] Created HNSW index {_GSW_HNSW_INDEX_NAME} [OK]")
        except Exception as e:
            db_logger.warning(f"[DB INIT] HNSW index ensure failed: {e}")

    def _extension_installed(self, ext: str) -> bool:
        rows = self.execute_query(
            "SELECT 1 FROM pg_extension WHERE extname = :ext LIMIT 1",
            {"ext": ext},
        )
        return bool(rows)

    def _ensure_platform_extensions(self) -> None:
        """Ensure vector, Apache AGE, and pg_cron extensions (custom Postgres image)."""
        for ext in _PLATFORM_EXTENSIONS:
            if self._extension_installed(ext):
                db_logger.info(f"[DB INIT] Extension {ext} present [OK]")
                continue
            self.execute_update(f"CREATE EXTENSION IF NOT EXISTS {ext}")
            if self._extension_installed(ext):
                db_logger.info(f"[DB INIT] Extension {ext} ensured [OK]")
            elif ext == "vector":
                db_logger.error(
                    f"[DB INIT] Required extension {ext} missing after CREATE; "
                    "use pgvector-enabled PostgreSQL or docker/postgres image"
                )
            else:
                db_logger.warning(
                    f"[DB INIT] Extension {ext} unavailable; "
                    "use docker/postgres image (pgvector + AGE + pg_cron) for full Platform Engine"
                )

    def _ensure_age_graph(self) -> None:
        """Provision empty AGE graph shell (read-only reserve per ADR-002).

        Distinct from relational table memory_graph. Application runtime must
        not write cypher to this graph until a future ADR re-opens AGE writes.
        """
        try:
            rows = self.execute_query(
                "SELECT 1 FROM pg_extension WHERE extname = 'age' LIMIT 1"
            )
            if not rows:
                db_logger.debug("[DB INIT] AGE not installed; skip graph ensure")
                return

            existing = self.execute_query(
                "SELECT name FROM ag_catalog.ag_graph WHERE name = :graph_name LIMIT 1",
                {"graph_name": _AGE_GRAPH_NAME},
            )
            if existing:
                db_logger.info(f"[DB INIT] AGE graph {_AGE_GRAPH_NAME} present [OK]")
                return

            session = self.get_session()
            try:
                session.execute(sql_text("LOAD 'age'"))
                session.execute(
                    sql_text("SELECT create_graph(:graph_name)"),
                    {"graph_name": _AGE_GRAPH_NAME},
                )
                session.commit()
                db_logger.info(f"[DB INIT] Created AGE graph {_AGE_GRAPH_NAME} [OK]")
            except Exception as inner:
                session.rollback()
                if "already exists" in str(inner).lower():
                    db_logger.info(f"[DB INIT] AGE graph {_AGE_GRAPH_NAME} already exists")
                else:
                    raise
            finally:
                session.close()
        except Exception as e:
            db_logger.warning(f"[DB INIT] AGE graph ensure failed: {e}")

    def _ensure_pg_cron_jobs(self) -> None:
        """Schedule nightly cleanup for stale gsw_eternal_echoes rows."""
        try:
            ext_rows = self.execute_query(
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_cron' LIMIT 1"
            )
            if not ext_rows:
                db_logger.debug("[DB INIT] pg_cron not installed; skip cron ensure")
                return

            table_rows = self.execute_query(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'gsw_eternal_echoes'
                LIMIT 1
                """
            )
            if not table_rows:
                db_logger.debug("[DB INIT] gsw_eternal_echoes absent; skip cron ensure")
                return

            existing = self.execute_query(
                "SELECT jobid FROM cron.job WHERE jobname = :job_name LIMIT 1",
                {"job_name": _PGCRON_JOB_NAME},
            )
            if existing:
                job_id = existing[0].get("jobid")
                if job_id is not None:
                    self.execute_update(
                        "SELECT cron.unschedule(CAST(:job_id AS bigint))",
                        {"job_id": job_id},
                    )

            self.execute_update(
                f"""
                SELECT cron.schedule(
                    '{_PGCRON_JOB_NAME}',
                    '0 2 * * *',
                    $$DELETE FROM gsw_eternal_echoes
                      WHERE created_at < NOW() - INTERVAL '30 days'$$
                )
                """
            )
            db_logger.info(f"[DB INIT] pg_cron job {_PGCRON_JOB_NAME} ensured [OK]")
        except Exception as e:
            db_logger.warning(f"[DB INIT] pg_cron job ensure failed: {e}")

    def get_session(self) -> Session:
        """獲取同步會話"""
        return SessionLocal()
    
    async def get_async_session(self) -> AsyncSession:
        """獲取非同步會話"""
        return AsyncSessionLocal()
    
    def execute_query(self, query_str: str, params: dict = None) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            result = session.execute(sql_text(query_str), params or {})
            if result.returns_rows:
                return [dict(row._mapping) for row in result]
            return []
        except Exception as e:
            db_logger.error(f"[EXEC QUERY] Failed: {e}")
            return []
        finally:
            session.close()

    def execute_update(self, query_str: str, params: dict = None) -> int:
        session = self.get_session()
        try:
            result = session.execute(sql_text(query_str), params or {})
            session.commit()
            return result.rowcount
        except Exception as e:
            session.rollback()
            db_logger.error(f"[EXEC UPDATE] Failed: {e}")
            return 0
        finally:
            session.close()
    
    def execute_insert(self, table_name: str, data: Dict[str, Any]) -> bool:
        session = self.get_session()
        try:
            columns = ', '.join(data.keys())
            values_placeholders = ', '.join([f":{k}" for k in data.keys()])
            sql = f"INSERT INTO {table_name} ({columns}) VALUES ({values_placeholders})"
            session.execute(sql_text(sql), data)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            db_logger.error(f"[EXEC INSERT] Failed: {e}")
            return False
        finally:
            session.close()
    
    # ==================== 會話與對話管理 (Orchestrator 專用) ====================

    def find_active_session_by_user(self, user_id: str) -> Optional[str]:
        """尋找用戶當前的活躍會話"""
        session = self.get_session()
        try:
            active = session.query(ActiveSession).filter(
                ActiveSession.user_id == user_id,
                ActiveSession.is_active == True
            ).order_by(desc(ActiveSession.created_at)).first()
            return str(active.session_id) if active else None
        except Exception as e:
            db_logger.error(f"[DB] find_active_session_by_user failed: {e}")
            return None
        finally:
            session.close()

    def create_session(self, user_id: str) -> Optional[str]:
        """建立新的對話會話，並確保用戶存在"""
        session = self.get_session()
        try:
            # 1. 確保用戶存在 (避免 ForeignKey 報錯)
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                user = User(id=user_id, trust_score=0.1)
                session.add(user)
                session.flush()

            # 2. 將該用戶之前的活躍會話設為關閉
            session.query(ActiveSession).filter(
                ActiveSession.user_id == user_id,
                ActiveSession.is_active == True
            ).update({"is_active": False})

            # 3. 建立新會話
            new_session = ActiveSession(
                session_id=uuid.uuid4(),
                user_id=user_id,
                is_active=True,
                turn_count=0,
                risk_level=1
            )
            session.add(new_session)
            session.commit()
            return str(new_session.session_id)
        except Exception as e:
            session.rollback()
            db_logger.error(f"[DB] create_session failed: {e}")
            return None
        finally:
            session.close()

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """獲取會話的當前狀態 (字典格式)"""
        session = self.get_session()
        try:
            active = session.query(ActiveSession).filter_by(session_id=session_id).first()
            if active:
                return {
                    'session_id': str(active.session_id),
                    'user_id': active.user_id,
                    'turn_count': active.turn_count,
                    'risk_level': active.risk_level,
                    'is_active': active.is_active,
                    'phase': "exploration",
                    'intimacy': 0.1
                }
            return {}
        except Exception as e:
            db_logger.error(f"[DB] get_session_state failed: {e}")
            return {}
        finally:
            session.close()

    def store_turn(self, session_id: str, user_id: str, role: str, text: str,
                   emotions_vsc: Dict = None, risk_level: int = 0, safety_audit: Dict = None,
                   embedding: List[float] = None, emotion_vector: Dict = None, metadata: Dict = None) -> bool:
        """儲存單輪對話，並更新會話的 turn_count"""
        session = self.get_session()
        try:
            active = session.query(ActiveSession).filter_by(session_id=session_id).first()
            seq = active.turn_count + 1 if active else 1

            turn = Turn(
                session_id=session_id,
                user_id=user_id,
                role=role,
                text=text,
                session_seq=seq,
                emotions_vsc=emotions_vsc or {},
                valence=emotions_vsc.get('valence', 0.0) if emotions_vsc else 0.0,
                arousal=emotions_vsc.get('arousal', 0.0) if emotions_vsc else 0.0,
                risk_level=risk_level,
                safety_audit=safety_audit or {},
                embedding=embedding,
                emotion_vector=emotion_vector or {},
                metadata_dict=metadata or {}
            )
            session.add(turn)

            # 更新 Session 狀態
            if active:
                active.turn_count = seq
                active.risk_level = max(active.risk_level, risk_level)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            db_logger.error(f"[DB] store_turn failed: {e}")
            return False
        finally:
            session.close()

    # ==================== Phase 5: User Shadow & Milestones ====================

    def get_user_shadow_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load persisted User Shadow for a user."""
        session = self.get_session()
        try:
            row = session.query(UserShadowState).filter_by(user_id=user_id).first()
            if not row:
                return None
            return {
                'user_id': row.user_id,
                'pain': float(row.pain or 0.0),
                'trust': float(row.trust or 0.5),
                'hope': float(row.hope or 0.5),
                'loneliness': float(row.loneliness or 0.0),
                'emotion_snapshot': row.emotion_snapshot or {},
                'last_session_id': str(row.last_session_id) if row.last_session_id else None,
                'turn_count': int(row.turn_count or 0),
                'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            }
        except Exception as e:
            db_logger.error(f"[DB] get_user_shadow_state failed: {e}")
            return None
        finally:
            session.close()

    def upsert_user_shadow_state(
        self,
        user_id: str,
        shadow: Dict[str, Any],
        *,
        session_id: Optional[str] = None,
        emotion_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Insert or update User Shadow state."""
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                user = User(id=user_id, trust_score=float(shadow.get('trust', 0.5)))
                session.add(user)
                session.flush()

            row = session.query(UserShadowState).filter_by(user_id=user_id).first()
            if not row:
                row = UserShadowState(user_id=user_id)
                session.add(row)

            row.pain = float(shadow.get('pain', 0.0))
            row.trust = float(shadow.get('trust', 0.5))
            row.hope = float(shadow.get('hope', 0.5))
            row.loneliness = float(shadow.get('loneliness', 0.0))
            row.turn_count = int(row.turn_count or 0) + 1
            if emotion_snapshot is not None:
                row.emotion_snapshot = emotion_snapshot
            if session_id:
                try:
                    row.last_session_id = uuid.UUID(str(session_id))
                except (ValueError, TypeError):
                    pass
            row.updated_at = datetime.utcnow()

            user.trust_score = max(float(user.trust_score or 0.0), row.trust)
            user.intimacy = row.trust

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            db_logger.error(f"[DB] upsert_user_shadow_state failed: {e}")
            return False
        finally:
            session.close()

    def insert_psychological_milestone(
        self,
        user_id: str,
        milestone_type: str,
        title: str,
        description: str = "",
        *,
        session_id: Optional[str] = None,
        severity: int = 1,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Record a psychological milestone; skip duplicate type within 24h."""
        session = self.get_session()
        try:
            since = datetime.utcnow() - timedelta(hours=24)
            recent = session.query(PsychologicalMilestone).filter(
                PsychologicalMilestone.user_id == user_id,
                PsychologicalMilestone.milestone_type == milestone_type,
                PsychologicalMilestone.created_at >= since,
            ).first()
            if recent:
                return None

            sid = None
            if session_id:
                try:
                    sid = uuid.UUID(str(session_id))
                except (ValueError, TypeError):
                    sid = None

            entry = PsychologicalMilestone(
                user_id=user_id,
                session_id=sid,
                milestone_type=milestone_type,
                title=title,
                description=description or "",
                severity=int(severity),
                meta=meta or {},
            )
            session.add(entry)
            session.commit()
            return int(entry.milestone_id)
        except Exception as e:
            session.rollback()
            db_logger.error(f"[DB] insert_psychological_milestone failed: {e}")
            return None
        finally:
            session.close()

    def list_psychological_milestones(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Recent psychological milestones for a user."""
        session = self.get_session()
        try:
            rows = (
                session.query(PsychologicalMilestone)
                .filter_by(user_id=user_id)
                .order_by(desc(PsychologicalMilestone.created_at))
                .limit(max(1, min(limit, 100)))
                .all()
            )
            return [
                {
                    'milestone_id': r.milestone_id,
                    'milestone_type': r.milestone_type,
                    'title': r.title,
                    'description': r.description,
                    'severity': r.severity,
                    'meta': r.meta or {},
                    'session_id': str(r.session_id) if r.session_id else None,
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        except Exception as e:
            db_logger.error(f"[DB] list_psychological_milestones failed: {e}")
            return []
        finally:
            session.close()

    # ==================== KAG Reality Layer ====================

    def upsert_reality_fact(
        self,
        subject: str,
        predicate: str,
        object_value: str,
        *,
        user_id: Optional[str] = None,
        confidence: float = 0.8,
        source: str = "user_statement",
        session_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        is_seed: bool = False,
        expires_at: Optional[datetime] = None,
    ) -> Optional[int]:
        """Insert or update a reality fact (dedupe by user+subject+predicate)."""
        session = self.get_session()
        try:
            if user_id:
                user = session.query(User).filter_by(id=user_id).first()
                if not user:
                    user = User(id=user_id)
                    session.add(user)
                    session.flush()

            query = session.query(RealityFact).filter(
                RealityFact.subject == subject,
                RealityFact.predicate == predicate,
            )
            if user_id:
                query = query.filter(RealityFact.user_id == user_id)
            else:
                query = query.filter(RealityFact.user_id.is_(None))

            row = query.first()
            if row and row.object_value == object_value:
                row.confidence = max(float(row.confidence or 0), float(confidence))
                row.updated_at = datetime.utcnow()
                if expires_at is not None:
                    row.expires_at = expires_at
                session.commit()
                return int(row.fact_id)

            if row and float(confidence) >= float(row.confidence or 0):
                row.object_value = object_value
                row.confidence = float(confidence)
                row.source = source
                row.meta = meta or row.meta or {}
                row.updated_at = datetime.utcnow()
                if expires_at is not None:
                    row.expires_at = expires_at
                session.commit()
                return int(row.fact_id)

            sid = None
            if session_id:
                try:
                    sid = uuid.UUID(str(session_id))
                except (ValueError, TypeError):
                    sid = None

            entry = RealityFact(
                user_id=user_id,
                subject=subject,
                predicate=predicate,
                object_value=object_value,
                confidence=float(confidence),
                source=source,
                session_id=sid,
                meta=meta or {},
                is_seed=bool(is_seed),
                expires_at=expires_at,
            )
            session.add(entry)
            session.commit()
            return int(entry.fact_id)
        except Exception as e:
            session.rollback()
            db_logger.error(f"[DB] upsert_reality_fact failed: {e}")
            return None
        finally:
            session.close()

    def list_reality_facts(
        self,
        *,
        user_id: Optional[str] = None,
        subjects: Optional[List[str]] = None,
        limit: int = 20,
        include_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """List active reality facts, optionally scoped to a user."""
        session = self.get_session()
        try:
            now = datetime.utcnow()
            q = session.query(RealityFact)
            if user_id:
                q = q.filter(
                    or_(RealityFact.user_id == user_id, RealityFact.user_id.is_(None))
                )
            else:
                q = q.filter(RealityFact.user_id.is_(None))
            if subjects:
                q = q.filter(RealityFact.subject.in_(subjects))
            if not include_expired:
                q = q.filter(
                    or_(RealityFact.expires_at.is_(None), RealityFact.expires_at > now)
                )
            rows = (
                q.order_by(desc(RealityFact.confidence), desc(RealityFact.updated_at))
                .limit(max(1, min(limit, 100)))
                .all()
            )
            return [
                {
                    "fact_id": r.fact_id,
                    "user_id": r.user_id,
                    "subject": r.subject,
                    "predicate": r.predicate,
                    "object_value": r.object_value,
                    "confidence": float(r.confidence or 0),
                    "source": r.source,
                    "meta": r.meta or {},
                    "is_seed": bool(r.is_seed),
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        except Exception as e:
            db_logger.error(f"[DB] list_reality_facts failed: {e}")
            return []
        finally:
            session.close()

    def search_reality_facts(
        self,
        user_id: str,
        query_text: str,
        *,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        """Keyword overlap search over user + global seed facts."""
        session = self.get_session()
        try:
            now = datetime.utcnow()
            rows = (
                session.query(RealityFact)
                .filter(
                    or_(RealityFact.user_id == user_id, RealityFact.user_id.is_(None)),
                    or_(RealityFact.expires_at.is_(None), RealityFact.expires_at > now),
                )
                .order_by(desc(RealityFact.confidence), desc(RealityFact.updated_at))
                .limit(80)
                .all()
            )
            if not query_text:
                return [
                    {
                        "fact_id": r.fact_id,
                        "subject": r.subject,
                        "predicate": r.predicate,
                        "object_value": r.object_value,
                        "confidence": float(r.confidence or 0),
                        "source": r.source,
                    }
                    for r in rows[:limit]
                ]

            tokens = {
                t for t in re.split(r"[\s，,。！？!?、；;：:]+", query_text.lower())
                if len(t) >= 2
            }
            scored: List[Tuple[float, RealityFact]] = []
            for row in rows:
                blob = f"{row.subject} {row.predicate} {row.object_value}".lower()
                overlap = sum(1 for t in tokens if t in blob)
                if overlap > 0 or row.is_seed or row.subject in ("seele", "safety", "system"):
                    score = overlap + float(row.confidence or 0) * 0.5
                    if row.is_seed:
                        score += 0.25
                    scored.append((score, row))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = [r for _, r in scored[:limit]]
            return [
                {
                    "fact_id": r.fact_id,
                    "subject": r.subject,
                    "predicate": r.predicate,
                    "object_value": r.object_value,
                    "confidence": float(r.confidence or 0),
                    "source": r.source,
                }
                for r in top
            ]
        except Exception as e:
            db_logger.error(f"[DB] search_reality_facts failed: {e}")
            return []
        finally:
            session.close()

    def init_fracture_map(self):
        """初始化預設危機地圖數據"""
        session = self.get_session()
        try:
            if session.query(FractureMap).count() == 0:
                default_fractures = [
                    {
                        'fracture_name': 'Suicidal_Ideation',
                        'description': '自殺傾向',
                        'severity_level': 5,
                        'keywords': ['自殺', '結束生命', '不想活'],
                        'risk_indicators': {'immediate_risk': True},
                        'intervention_prompts': ['生命價值', '求助資源'],
                        'clinical_guidelines': '立即升級'
                    },
                    {
                        'fracture_name': 'Self_Harm',
                        'description': '自傷行為',
                        'severity_level': 4,
                        'keywords': ['割腕', '傷害自己', '自虐'],
                        'risk_indicators': {'coping_mechanism': True},
                        'intervention_prompts': ['替代行為', '情緒調適'],
                        'clinical_guidelines': '提供替代方案'
                    }
                ]
                for fracture in default_fractures:
                    fm = FractureMap(**fracture)
                    session.add(fm)
                session.commit()
                db_logger.info(f"[FRACTURE MAP] Initialized {len(default_fractures)} default fractures")
        except Exception as e:
            session.rollback()
            db_logger.error(f"[FRACTURE MAP] Init failed: {e}")
        finally:
            session.close()

    def init_action_cards(self):
        """初始化逆向小丑劇本卡片"""
        json_path = Path(__file__).resolve().parent.parent.parent / "PersonalityModule" / "data" / "action_cards.json"
        if not json_path.exists():
            db_logger.warning(f"[ACTION CARDS] JSON file not found at {json_path}")
            return

        session = self.get_session()
        try:
            if session.query(ActionCard).count() == 0:
                with open(json_path, 'r', encoding='utf-8') as f:
                    cards_data = json.load(f)
                
                for card in cards_data:
                    new_card = ActionCard(
                        stage=card.get('stage', 1),
                        title=card.get('title', ''),
                        content=card.get('content', ''),
                        target_emotions=card.get('target_emotions', {}),
                        trigger_conditions=card.get('trigger_conditions', {})
                    )
                    session.add(new_card)
                
                session.commit()
                db_logger.info(f"[ACTION CARDS] Initialized {len(cards_data)} cards from JSON")
            else:
                count = session.query(ActionCard).count()
                db_logger.info(f"[ACTION CARDS] Table already populated ({count} cards)")
        except Exception as e:
            session.rollback()
            db_logger.error(f"[ACTION CARDS] Init failed: {e}")
        finally:
            session.close()

    def get_db_stats(self) -> Dict[str, Any]:
        """獲取各表統計數據"""
        session = self.get_session()
        try:
            stats = {
                'total_users': session.query(User).count(),
                'active_sessions': session.query(ActiveSession).filter_by(is_active=True).count(),
                'fracture_maps_count': session.query(FractureMap).count(),
                'total_escalations': session.query(EscalationEvent).count(),
                'unconfirmed_escalations': session.query(EscalationEvent).filter_by(escalation_confirmed=False).count(),
                'total_turns': session.query(Turn).count(),
                'total_crisis_events': session.query(CrisisEvent).count(),
                'total_echoes': session.query(GSWEternalEcho).count(),
            }
            return stats
        except Exception as e:
            db_logger.error(f"[DB STATS] Failed: {e}")
            return {}
        finally:
            session.close()

    def health_check(self) -> Dict[str, Any]:
        """健康檢查"""
        if not getattr(self, "_ready", False):
            return {
                'status': 'unhealthy',
                'error': 'Database manager failed to initialize',
                'timestamp': datetime.utcnow().isoformat()
            }
        rows = self.execute_query("SELECT 1 AS ok")
        if not rows or rows[0].get("ok") != 1:
            return {
                'status': 'unhealthy',
                'error': 'Database query failed',
                'timestamp': datetime.utcnow().isoformat()
            }
        return {
            'status': 'healthy',
            'database': 'ok',
            'timestamp': datetime.utcnow().isoformat()
        }
            
    def close(self):
        """關閉所有連接"""
        SessionLocal.remove()


# ==================== 非同步數據庫管理器 ====================

class AsyncDatabaseManager:
    """
    非同步數據庫管理器 - 用於 GSWEngine 和其他異步操作
    """
    
    def __init__(self):
        self.logger = db_logger
    
    async def get_session(self) -> AsyncSession:
        """獲取非同步會話"""
        return AsyncSessionLocal()
    
    async def search_similar_memories_async(
        self, 
        query_vector: List[float], 
        k: int = 5, 
        min_similarity: float = 0.5,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        異步向量相似度搜索 - GSWEngine 核心方法
        """
        if not query_vector or len(query_vector) == 0:
            return []
        
        session = await self.get_session()
        try:
            # 將 Python List 轉換為 PostgreSQL vector 支援的字串格式
            query_embedding = f"[{','.join(str(v) for v in query_vector)}]"
            
            # [FIX-BUG] 先前此處誤貼為 store_echo_async 的 INSERT 語句，且綁定參數
            # {vec, min_sim, k} 與佔位符完全不符，導致搜尋必定失敗。
            # 改為正確的 pgvector 餘弦相似度查詢；欄位順序需對齊下方 row[0..6] 的映射：
            # row[0]=id, row[1]=user_id, row[2]=content, row[3]=echo_score,
            # row[4]=weight, row[5]=similarity, row[6]=created_at。
            if user_id:
                sql = sql_text("""
                    SELECT
                        id,
                        user_id,
                        content,
                        echo_score,
                        weight,
                        1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                        created_at
                    FROM gsw_eternal_echoes
                    WHERE embedding IS NOT NULL
                      AND user_id = :user_id
                      AND (1 - (embedding <=> CAST(:vec AS vector))) >= :min_sim
                    ORDER BY embedding <=> CAST(:vec AS vector) ASC
                    LIMIT :k
                """)
                params = {
                    'vec': query_embedding,
                    'min_sim': min_similarity,
                    'k': k,
                    'user_id': user_id,
                }
            else:
                sql = sql_text("""
                    SELECT
                        id,
                        user_id,
                        content,
                        echo_score,
                        weight,
                        1 - (embedding <=> CAST(:vec AS vector)) AS similarity,
                        created_at
                    FROM gsw_eternal_echoes
                    WHERE embedding IS NOT NULL
                      AND (1 - (embedding <=> CAST(:vec AS vector))) >= :min_sim
                    ORDER BY embedding <=> CAST(:vec AS vector) ASC
                    LIMIT :k
                """)
                params = {
                    'vec': query_embedding,
                    'min_sim': min_similarity,
                    'k': k,
                }
            
            result = await session.execute(sql, params)
            
            rows = result.fetchall()
            memories = []
            for row in rows:
                memories.append({
                    'id': row[0],
                    'user_id': row[1],
                    'content': row[2],
                    'echo_score': float(row[3]) if row[3] else 0.0,
                    'weight': float(row[4]) if row[4] else 1.0,
                    'similarity': float(row[5]) if row[5] else 0.0,
                    'created_at': row[6].isoformat() if row[6] else None
                })
            
            return memories
            
        except Exception as e:
            self.logger.error(f"[ASYNC SEARCH] Vector search failed: {e}")
            return []
        finally:
            await session.close()
    
    async def store_echo_async(
        self,
        echo_id: str,
        user_id: str,
        user_input: str,
        response: str,
        embedding: Optional[List[float]],
        echo_score: float,
        metadata: Dict
    ) -> bool:
        """
        異步儲存 GSW 永恆迴響
        """
        session = await self.get_session()
        try:
            embedding_str = f"[{','.join(str(v) for v in embedding)}]" if embedding else None
            
            sql = sql_text("""
                INSERT INTO gsw_eternal_echoes 
                (id, user_id, user_input, response, content, embedding, echo_score, weight, metadata, created_at)
                VALUES (:id, :uid, :user_input, :response, :content, 
                        CAST(:embedding AS vector), :score, 2.0, CAST(:meta AS jsonb), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    echo_score = EXCLUDED.echo_score,
                    weight = EXCLUDED.weight,
                    updated_at = NOW()
            """)
            
            await session.execute(sql, {
                'id': echo_id,
                'uid': user_id,
                'user_input': user_input[:500],
                'response': response[:500],
                'content': response[:500],
                'embedding': embedding_str,
                'score': max(0.0, min(1.0, echo_score)),
                'meta': json.dumps(metadata, ensure_ascii=False)
            })
            
            await session.commit()
            self.logger.info(f"[ASYNC STORE] Echo {echo_id} stored successfully")
            return True
            
        except Exception as e:
            await session.rollback()
            self.logger.error(f"[ASYNC STORE] Failed to store echo: {e}")
            return False
        finally:
            await session.close()
    
    async def apply_memory_decay_async(self) -> bool:
        """
        異步應用記憶衰減
        """
        session = await self.get_session()
        try:
            sql = sql_text("""
                UPDATE gsw_eternal_echoes 
                SET weight = GREATEST(0.5, weight * 0.95),
                    updated_at = NOW()
                WHERE weight > 0.5
            """)
            
            result = await session.execute(sql)
            await session.commit()
            
            self.logger.info(f"[ASYNC DECAY] Memory decay applied to {result.rowcount} records")
            return True
            
        except Exception as e:
            await session.rollback()
            self.logger.error(f"[ASYNC DECAY] Failed: {e}")
            return False
        finally:
            await session.close()


# ==================== 全局實例 ====================

db_manager = DatabaseManager()
async_db_manager = AsyncDatabaseManager()
db_manager.async_db_manager = async_db_manager

def get_session() -> Session:
    """獲取同步會話的便利函數"""
    return db_manager.get_session()

def close_session():
    """關閉數據庫連接"""
    db_manager.close()