# orchestrator.py - 修正版本 v5.5.6 (Zero-Truncation Protocol)
# 【Engine7B Logic Engine】對話管線、安全閘門、人格錨定、導航決策
# 不負責：LLM 進程部署（Compute Engine）、PostgreSQL/Redis 容器（Platform Engine）
# 
# 修復清單:
# [FIX-BUG-001] 添加缺失的 math 模塊導入
# [FIX-BUG-002] 移除類外代碼，整合 MemoryCacheBackend 到類內
# [FIX-BUG-003] 修復 Union 類型檢查邏輯
# [FIX-BUG-004] 添加完整的異常處理和邊界檢查
# [FIX-BUG-005] 實現完整的 Redis 降級機制

import asyncio
import json
import logging
import traceback
import hashlib
import time
import math
from datetime import datetime
from typing import Dict, Optional, Any, List, Tuple, Union
from enum import Enum
import uuid
import os

from app.schemas import ChatRequest
from app.logger import get_app_logger, get_audit_logger

# ==================== 核心服務導入 ====================

from app.services.db_manager import db_manager, SessionLocal
from app.services.emotion_service import EmotionService
from app.services.vector_service import VectorService
from app.services.hko_service import HKOService
from app.services.llm_service import llm_service
from app.services.risk_assessment_service import assess_turn_risk
from app.services.memory_chain_service import MemoryChainService
from app.services.star_orchestration_service import (
    StarOrchestrationService,
    SensingBundle,
)
from app.utils.identity_intent import detect_identity_intent, get_identity_reply
from app.services.fracture_map.db_fm_manager import DBFMManager
from app.services.fracture_map.intelligent_navigator import IntelligentNavigator, NavigationDecision

from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.gsw_engine import GSWEngine
from PersonalityModule.config import get_config

# ==================== 日誌初始化 ====================

logger = get_app_logger('orchestrator.main')
audit_logger = get_audit_logger('orchestrator.audit')
perf_logger = get_app_logger('orchestrator.performance')

# ==================== 列舉與配置 ====================

class ConversationPhase(Enum):
    """對話階段定義"""
    GREETING = "greeting"
    EXPLORATION = "exploration"
    DEEP_ENGAGEMENT = "deep_engagement"
    CRISIS = "crisis"
    RESOLUTION = "resolution"
    CLOSURE = "closure"
    ERROR = "error"


class PerformanceConfig:
    """性能與快取配置"""
    EMBEDDING_CACHE_TTL = 604800
    EMOTION_CACHE_TTL = 3600
    WEATHER_CACHE_TTL = 1800
    SESSION_STATE_CACHE_TTL = 3600
    CACHE_SALT = "vita_3.0_router_v5.5.6"
    DB_WRITE_TIMEOUT = 10
    MAX_BACKGROUND_TASKS = 100
    TASK_CLEANUP_INTERVAL = 60
    PERSONALITY_ANCHOR_TIMEOUT = 15.0
    SESSION_STATE_FETCH_TIMEOUT = 5.0
    EMOTION_ANALYSIS_TIMEOUT = 3.0
    EMBEDDING_GENERATION_TIMEOUT = 10.0
    WEATHER_FETCH_TIMEOUT = 5.0
    NAVIGATOR_TIMEOUT = 8.0
    GSW_TIMEOUT = 5.0
    MEMORY_RETRIEVAL_TIMEOUT = 5.0
    STAR_ORCHESTRATION_TIMEOUT = 90.0
    STAR_ORCHESTRATION_TIMEOUT_DEGRADED = 35.0
    LLM_PROBE_TIMEOUT = 2.0
    FRACTURE_CHECK_TIMEOUT = 3.0
    LLM_DRAFT_GENERATION_TIMEOUT = 30.0
    MIN_RESPONSE_LENGTH = 10
    
    REDIS_CONNECT_TIMEOUT = 10
    REDIS_SOCKET_TIMEOUT = 5
    REDIS_RETRY_ATTEMPTS = 3
    REDIS_RETRY_DELAY = 2


# ==================== 環境感知配置 ====================

class EnvironmentConfig:
    """生產環境配置管理"""
    
    @staticmethod
    def get_environment() -> str:
        """取得執行環境"""
        return os.getenv('ENV', 'production')
    
    @staticmethod
    def is_production() -> bool:
        """檢查是否為生產環境"""
        return EnvironmentConfig.get_environment() == 'production'
    
    @staticmethod
    def get_redis_config() -> Dict[str, Any]:
        """取得 Redis 連線配置"""
        from app.config import config
        default_host = 'redis' if config.IS_DOCKER else '127.0.0.1'
        return {
            'host': os.getenv('REDIS_HOST', default_host),
            'port': int(os.getenv('REDIS_PORT', '6379')),
            'db': int(os.getenv('REDIS_DB', '0')),
            'decode_responses': True,
            'socket_connect_timeout': int(os.getenv('REDIS_SOCKET_CONNECT_TIMEOUT', '10')),
            'socket_timeout': int(os.getenv('REDIS_SOCKET_TIMEOUT', '5')),
            'socket_keepalive': os.getenv('REDIS_SOCKET_KEEPALIVE', 'true').lower() == 'true',
            'health_check_interval': 30,
        }
    
    @staticmethod
    def get_llm_endpoints() -> Dict[str, str]:
        """取得 LLM 服務端點（統一 *_LLM_* 命名）"""
        from app.config import config
        return {
            'main_llm': config.MAIN_LLM_URL,
            'revise_llm': config.REVISE_LLM_URL,
            'logic_llm': config.LOGIC_LLM_URL,
            'memory_llm': config.MEMORY_LLM_URL,
            'emobloom_llm': config.EMOBLOOM_LLM_URL,
        }


# ==================== Redis 型別定義與初始化 ====================

REDIS_AVAILABLE = False
redis = None
RedisConnectionError = Exception

try:
    import redis as redis_module
    from redis.exceptions import ConnectionError as RedisConnectionError
    REDIS_AVAILABLE = True
    redis = redis_module
except ImportError:
    REDIS_AVAILABLE = False
    redis = None
    RedisConnectionError = Exception


# ==================== 記憶體快取後備系統 ====================

class MemoryCacheBackend:
    """[FIX-BUG-002] 內存快取備份 - 當 Redis 不可用時使用"""
    
    def __init__(self, max_items: int = 1000):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._max_items = max_items
        self._access_count: Dict[str, int] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """取得快取項"""
        if key not in self._cache:
            return None
        
        value, expiry_time = self._cache[key]
        
        if time.time() > expiry_time:
            del self._cache[key]
            return None
        
        self._access_count[key] = self._access_count.get(key, 0) + 1
        return value
    
    def setex(self, key: str, ttl: int, value: Any) -> None:
        """設置快取項（含過期時間）"""
        if len(self._cache) >= self._max_items:
            self._evict_lru()
        
        self._cache[key] = (value, time.time() + ttl)
        self._access_count[key] = 1
    
    def _evict_lru(self) -> None:
        """驅逐最少使用的項"""
        if not self._cache:
            return
        
        lru_key = min(self._access_count.keys(), 
                     key=lambda k: self._access_count.get(k, 0))
        
        if lru_key in self._cache:
            del self._cache[lru_key]
        if lru_key in self._access_count:
            del self._access_count[lru_key]
    
    def clear(self) -> None:
        """清除所有快取"""
        self._cache.clear()
        self._access_count.clear()


# ==================== Redis 連線管理類 ====================

class RedisConnectionManager:
    """管理 Redis 連線的專用類，處理連線、重試和降級"""
    
    def __init__(
        self,
        host: str = 'redis',
        port: int = 6379,
        db: int = 0,
        logger_instance: Optional[Any] = None
    ) -> None:
        """初始化 Redis 連線管理器"""
        self.host = host
        self.port = port
        self.db = db
        self.logger = logger_instance or logger
        self.client: Optional[Any] = None
        self.is_connected = False
        self.last_error: Optional[str] = None
    
    def connect(self, retry_count: int = PerformanceConfig.REDIS_RETRY_ATTEMPTS) -> bool:
        """嘗試連接 Redis，支持重試機制"""
        if self.is_connected and self.client:
            return True
        
        if not REDIS_AVAILABLE:
            self.logger.warning({
                "event": "redis_not_available",
                "status": "redis_module_missing"
            })
            return False
        
        for attempt in range(1, retry_count + 1):
            try:
                redis_config: Dict[str, Any] = {
                    'host': self.host,
                    'port': self.port,
                    'db': self.db,
                    'decode_responses': True,
                    'socket_connect_timeout': PerformanceConfig.REDIS_CONNECT_TIMEOUT,
                    'socket_timeout': PerformanceConfig.REDIS_SOCKET_TIMEOUT,
                    'health_check_interval': 30,
                    'retry_on_timeout': True,
                }
                
                try:
                    if redis and hasattr(redis, 'retry'):
                        redis_config['connection_pool_kwargs'] = {
                            'retry_on_timeout': True,
                            'retry': redis.retry.Retry(
                                backoff=redis.retry.NoBackoff(),
                                retries=2
                            )
                        }
                except Exception:
                    pass
                
                self.client = redis.Redis(**redis_config)
                
                if self.client:
                    self.client.ping()
                
                self.is_connected = True
                self.last_error = None
                
                self.logger.info({
                    "event": "redis_connected_success",
                    "host": self.host,
                    "port": self.port,
                    "attempt": attempt,
                    "status": "success"
                })
                
                return True
                
            except Exception as e:
                self.last_error = str(e)
                
                if attempt < retry_count:
                    wait_time = PerformanceConfig.REDIS_RETRY_DELAY * attempt
                    self.logger.warning({
                        "event": "redis_connection_retry",
                        "host": self.host,
                        "port": self.port,
                        "attempt": attempt,
                        "max_attempts": retry_count,
                        "error": str(e),
                        "next_retry_sec": wait_time
                    })
                    time.sleep(wait_time)
                else:
                    self.logger.error({
                        "event": "redis_connection_failed_final",
                        "host": self.host,
                        "port": self.port,
                        "total_attempts": retry_count,
                        "error": str(e),
                        "status": "FATAL"
                    })
                    self.is_connected = False
                    self.client = None
        
        return False
    
    def get_client(self) -> Optional[Any]:
        """取得 Redis 客戶端"""
        if self.is_connected and self.client:
            try:
                self.client.ping()
                return self.client
            except Exception:
                self.is_connected = False
                self.client = None
        
        return None
    
    def close(self) -> None:
        """關閉連線"""
        if self.client:
            try:
                self.client.close()
                self.is_connected = False
                self.logger.info({
                    "event": "redis_connection_closed",
                    "status": "success"
                })
            except Exception as e:
                self.logger.warning({
                    "event": "redis_close_error",
                    "error": str(e)
                })
            finally:
                self.client = None


# ==================== 主要 Orchestrator 類 ====================

class Orchestrator:
    """
    Vita 3.0 極速路由層 (v5.5.6 - 生產環境版修正)
    
    特性：
    - 完全非同步（AsyncFirst）
    - 完整的依賴注入
    - 零阻塞回傳
    - 生產級錯誤處理
    - 雙層快取（內存 + Redis）
    - 完整的 Redis 降級機制
    - 詳細的監控與日誌
    - 環境感知配置
    - 優雅降級支持
    """
    
    def __init__(
        self,
        redis_config: Optional[Dict[str, Any]] = None,
        shared_services: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        初始化路由器與所有依賴

        Args:
            redis_config: Redis 連線配置覆寫
            shared_services: [FIX-ALIGN] 由上層（app.main）建立並共享的服務實例，
                用以避免重複初始化（emotion_service / vector_service / hko_service /
                db_fm_manager / fracture_map_manager / gsw_engine /
                intelligent_navigator / personality_module）。未提供者則由
                Orchestrator 自行建立（向後相容，供 get_orchestrator() 獨立使用）。
        """
        init_start = datetime.now()
        shared_services = shared_services or {}
        
        self.environment = EnvironmentConfig.get_environment()
        self.is_production = EnvironmentConfig.is_production()
        
        self.logger = logger
        self.audit_logger = audit_logger
        self.perf_logger = perf_logger
        
        self.logger.info({
            "event": "orchestrator_v5.5.6_init_start",
            "version": "5.5.6",
            "environment": self.environment,
            "production": self.is_production,
            "timestamp": init_start.isoformat()
        })
        
        # ========== Redis 初始化（生產環境必需） ==========
        self.redis_manager: Optional[RedisConnectionManager] = None
        self.redis_client: Optional[Any] = None
        self.fallback_cache: Optional[MemoryCacheBackend] = None
        
        if REDIS_AVAILABLE:
            try:
                env_redis_config = EnvironmentConfig.get_redis_config()
                if redis_config:
                    env_redis_config.update(redis_config)
                
                self.redis_manager = RedisConnectionManager(
                    host=env_redis_config['host'],
                    port=env_redis_config['port'],
                    db=env_redis_config.get('db', 0),
                    logger_instance=self.logger
                )
                
                if self.redis_manager.connect(
                    retry_count=PerformanceConfig.REDIS_RETRY_ATTEMPTS
                ):
                    self.redis_client = self.redis_manager.get_client()
                    self.logger.info({
                        "event": "redis_initialized",
                        "status": "connected",
                        "environment": self.environment
                    })
                else:
                    error_msg = self.redis_manager.last_error or "Unknown error"
                    
                    if self.is_production:
                        self.logger.error({
                            "event": "redis_initialization_failed_production",
                            "error": error_msg,
                            "status": "critical"
                        })
                    else:
                        self.logger.warning({
                            "event": "redis_initialization_failed",
                            "error": error_msg,
                            "fallback": "memory_cache_only",
                            "status": "degraded"
                        })
                    
                    self.redis_manager = None
                    self.redis_client = None
                    # [FIX-BUG-002] 初始化後備快取
                    self.fallback_cache = MemoryCacheBackend()
            
            except Exception as e:
                log_level = self.logger.error if self.is_production else self.logger.warning
                log_level({
                    "event": "redis_init_exception",
                    "error": str(e),
                    "fallback": "memory_cache_only",
                    "environment": self.environment,
                    "traceback": traceback.format_exc()
                })
                self.redis_manager = None
                self.redis_client = None
                # [FIX-BUG-002] 初始化後備快取
                self.fallback_cache = MemoryCacheBackend()
        else:
            self.logger.warning({
                "event": "redis_module_not_available",
                "status": "redis_not_installed"
            })
            # [FIX-BUG-002] 初始化後備快取
            self.fallback_cache = MemoryCacheBackend()

        # ========== 核心服務初始化（優先重用共享實例） ==========
        try:
            self.db = shared_services.get('db_manager') or db_manager
            self.emotion = shared_services.get('emotion_service') or EmotionService()
            self.vector = shared_services.get('vector_service') or VectorService()
            self.hko = shared_services.get('hko_service') or HKOService()
            self.db_fm = shared_services.get('db_fm_manager') or DBFMManager()
            self.fm_manager = shared_services.get('fracture_map_manager')
            
            self.logger.info({
                "event": "core_services_initialized",
                "services": ["db", "emotion", "vector", "hko", "db_fm"],
                "reused_from_shared": [
                    k for k in (
                        'db_manager', 'emotion_service', 'vector_service',
                        'hko_service', 'db_fm_manager', 'fracture_map_manager'
                    ) if shared_services.get(k) is not None
                ],
                "status": "success"
            })
        except Exception as e:
            self.logger.error({
                "event": "core_services_init_failed",
                "error": str(e),
                "status": "critical"
            })
            raise
        
        # ========== 配置字典 ==========
        try:
            from app.config import config
            config_dict = config.to_dict()
        except Exception as e:
            self.logger.warning(f"Failed to get config dict: {e}")
            config_dict = {}

        # ========== GSWEngine 初始化（優先重用共享實例） ==========
        self.gsw_engine: Optional[GSWEngine] = shared_services.get('gsw_engine')
        if self.gsw_engine is not None:
            self.logger.info({
                "event": "gsw_engine_reused_from_shared",
                "status": "success"
            })
        else:
            try:
                GSWEngine_params: Dict[str, Any] = {
                    'config': config_dict,
                    'vector_service': self.vector,
                    'db_manager': self.db,
                }
                self.gsw_engine = GSWEngine(**GSWEngine_params)
                
                self.logger.info({
                    "event": "gsw_engine_initialized",
                    "status": "success",
                    "version": "8.1"
                })
            except Exception as e:
                self.logger.error({
                    "event": "gsw_engine_init_failed",
                    "error": str(e),
                    "status": "warning"
                })
                self.gsw_engine = None

        if self.gsw_engine and self.db and not getattr(self.gsw_engine, 'db_manager', None):
            self.gsw_engine.db_manager = self.db

        try:
            from app.config import config as _mem_cfg
            from app.services.db_manager import async_db_manager as _async_db
            if self.db and not getattr(self.db, 'async_db_manager', None):
                self.db.async_db_manager = _async_db
        except Exception:
            pass

        try:
            from app.config import config as _mem_cfg
            self.memory_chain = MemoryChainService(
                gsw_engine=self.gsw_engine,
                vector_service=self.vector,
                top_k=getattr(_mem_cfg, 'MEMORY_RETRIEVAL_TOP_K', 5),
                min_similarity=getattr(_mem_cfg, 'MEMORY_MIN_SIMILARITY', 0.45),
            )
        except Exception as mem_exc:
            self.logger.warning({
                "event": "memory_chain_init_failed",
                "error": str(mem_exc),
            })
            self.memory_chain = None

        try:
            from app.config import config as _star_cfg
            self.star_orchestration = StarOrchestrationService(
                llm_service=llm_service,
                enabled=getattr(_star_cfg, 'STAR_ORCHESTRATION_ENABLED', True),
            )
        except Exception as star_exc:
            self.logger.warning({
                "event": "star_orchestration_init_failed",
                "error": str(star_exc),
            })
            self.star_orchestration = None

        try:
            from app.config import config as _cog_cfg
            from app.services.cognitive_persistence_service import (
                CognitivePersistenceService,
            )
            self.cognitive_persistence = CognitivePersistenceService(
                self.db,
                enabled=getattr(_cog_cfg, 'COGNITIVE_LAYER_ENABLED', True),
            )
        except Exception as cog_exc:
            self.logger.warning({
                "event": "cognitive_persistence_init_failed",
                "error": str(cog_exc),
            })
            self.cognitive_persistence = None

        try:
            from app.config import config as _kag_cfg
            from app.services.kag_reality_service import KAGRealityService

            persona = getattr(_kag_cfg, "PERSONA_NAME", "希兒")
            if persona and "," in persona:
                persona = persona.split(",")[-1].strip()
            self.kag_reality = KAGRealityService(
                self.db,
                hko_service=self.hko,
                enabled=getattr(_kag_cfg, "KAG_REALITY_ENABLED", True),
                max_facts=getattr(_kag_cfg, "KAG_MAX_FACTS", 12),
                persona_name=persona,
            )
        except Exception as kag_exc:
            self.logger.warning({
                "event": "kag_reality_init_failed",
                "error": str(kag_exc),
            })
            self.kag_reality = None

        # ========== IntelligentNavigator 初始化（優先重用共享實例） ==========
        self.navigator: Optional[IntelligentNavigator] = shared_services.get('intelligent_navigator')
        if self.navigator is not None:
            self.logger.info({
                "event": "intelligent_navigator_reused_from_shared",
                "status": "success"
            })
        else:
            try:
                navigator_params: Dict[str, Any] = {
                    'llm_service': llm_service,
                    'db_manager': db_manager,
                    'db_service': None,
                    'fracture_manager': self.db_fm,
                    'config': config_dict
                }
                self.navigator = IntelligentNavigator(**navigator_params)
                
                self.logger.info({
                    "event": "intelligent_navigator_initialized",
                    "status": "success"
                })
            except Exception as e:
                self.logger.error({
                    "event": "intelligent_navigator_init_failed",
                    "error": str(e),
                    "status": "warning"
                })
                self.navigator = None

        # ========== PersonalityModule 初始化（優先重用共享實例） ==========
        self.personality: Optional[PersonalityModule] = shared_services.get('personality_module')
        if self.personality is not None:
            self.logger.info({
                "event": "personality_module_reused_from_shared",
                "status": "success"
            })
        else:
            try:
                personality_params: Dict[str, Any] = {'config': config_dict}
                self.personality = PersonalityModule(**personality_params)
                
                self.personality.setup_dependencies({
                    'vector_service': self.vector,
                    'db_service': self.db,
                    'llm_service': llm_service,
                    'emotion_service': self.emotion,
                    'hko_service': self.hko,
                    'gsw_engine': self.gsw_engine,
                    'db_fm_manager': self.db_fm,
                    'intelligent_navigator': self.navigator,
                    'fracture_map_manager': self.fm_manager,
                })
                
                self.logger.info({
                    "event": "personality_module_initialized",
                    "status": "success",
                    "dependencies_injected": ["vector", "db", "llm", "emotion", "hko", "gsw", "db_fm", "navigator", "fracture_map_manager"]
                })
            except Exception as e:
                self.logger.error({
                    "event": "personality_module_init_failed",
                    "error": str(e),
                    "status": "error"
                })
                raise

        # ========== 內部快取 ==========
        self._session_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self._embedding_cache: Dict[str, Tuple[Any, float]] = {}
        self._emotion_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        
        # ========== 背景任務管理 ==========
        self._background_tasks: set = set()
        self._last_cleanup = time.time()

        init_duration = (datetime.now() - init_start).total_seconds()
        self.logger.info({
            "event": "orchestrator_v5.5.6_init_complete",
            "duration_sec": round(init_duration, 3),
            "environment": self.environment,
            "components": {
                "personality": self.personality is not None,
                "gsw_engine": self.gsw_engine is not None,
                "memory_chain": self.memory_chain is not None,
                "star_orchestration": self.star_orchestration is not None,
                "db_fm_manager": self.db_fm is not None,
                "navigator": self.navigator is not None,
                "redis": self.redis_client is not None,
                "redis_manager": self.redis_manager is not None,
                "fallback_cache": self.fallback_cache is not None,
            },
            "status": "ready"
        })

    # ==================== 會話管理 ====================

    def _is_valid_uuid(self, val: Optional[str]) -> bool:
        """UUID 格式驗證"""
        if not val:
            return False
        try:
            uuid.UUID(str(val))
            return True
        except (ValueError, TypeError):
            return False

    def _resolve_session_id(self, request: ChatRequest) -> Optional[str]:
        """
        解析或建立會話 ID
        
        優先級：
        1. 提供的有效 session_id
        2. 該用戶的活躍會話
        3. 新建會話
        """
        user_id = request.user_id
        session_id = getattr(request, 'session_id', None)
        
        try:
            if session_id and self._is_valid_uuid(session_id):
                # [FIX-ALIGN] db_manager.get_session() 不接受參數（回傳 SQLAlchemy Session）。
                # 驗證會話是否存在應使用 get_session_state(session_id)，其在找不到時回傳空 dict。
                session_info = self.db.get_session_state(session_id)
                if session_info:
                    self.logger.debug({
                        "event": "session_resolved_existing",
                        "session_id": session_id,
                        "user_id": user_id
                    })
                    return session_id
        except Exception as e:
            self.logger.debug({
                "event": "session_lookup_failed",
                "session_id": session_id,
                "error": str(e)
            })

        try:
            active_session = self.db.find_active_session_by_user(user_id)
            if active_session and self._is_valid_uuid(active_session):
                self.logger.debug({
                    "event": "session_resolved_active",
                    "session_id": active_session,
                    "user_id": user_id
                })
                return active_session
        except Exception as e:
            self.logger.debug({
                "event": "active_session_lookup_failed",
                "user_id": user_id,
                "error": str(e)
            })

        try:
            new_session_id = self.db.create_session(user_id)
            if new_session_id and self._is_valid_uuid(new_session_id):
                self.logger.info({
                    "event": "new_session_created",
                    "session_id": new_session_id,
                    "user_id": user_id
                })
                return new_session_id
        except Exception as e:
            self.logger.error({
                "event": "session_creation_failed",
                "user_id": user_id,
                "error": str(e)
            })

        return None

    # ==================== 快取管理（修復版） ====================

    def _build_cache_key(self, *parts: str) -> str:
        """構建快取鍵"""
        return ":".join(str(p) for p in parts if p)

    def _build_embedding_cache_key(self, text: str) -> str:
        """構建嵌入快取鍵"""
        salted = f"{text}:{PerformanceConfig.CACHE_SALT}"
        hash_val = hashlib.md5(salted.encode()).hexdigest()[:16]
        return f"emb:{hash_val}"

    def _build_emotion_cache_key(self, text: str) -> str:
        """構建情緒快取鍵"""
        salted = f"{text}:{PerformanceConfig.CACHE_SALT}"
        hash_val = hashlib.md5(salted.encode()).hexdigest()[:16]
        return f"emo:{hash_val}"

    def _get_embedding_cache(self, key: str) -> Optional[Any]:
        """從雙層快取取得嵌入向量"""
        try:
            current_time = time.time()
            
            # [FIX-BUG-003] 優先嘗試 Redis，再回退到內存
            if self.redis_client:
                try:
                    cached = self.redis_client.get(key)
                    if cached:
                        self.logger.debug({
                            "event": "embedding_cache_hit_redis",
                            "cache_key": key
                        })
                        return json.loads(cached)
                except Exception as e:
                    self.logger.debug({
                        "event": "redis_get_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            # 如果 Redis 不可用，嘗試後備快取
            if self.fallback_cache:
                try:
                    cached = self.fallback_cache.get(key)
                    if cached:
                        self.logger.debug({
                            "event": "embedding_cache_hit_fallback",
                            "cache_key": key
                        })
                        return cached
                except Exception as e:
                    self.logger.debug({
                        "event": "fallback_get_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            # 嘗試內存快取
            if key in self._embedding_cache:
                cached_value, cached_time = self._embedding_cache[key]
                if current_time - cached_time < PerformanceConfig.EMBEDDING_CACHE_TTL:
                    self.logger.debug({
                        "event": "embedding_cache_hit_memory",
                        "cache_key": key
                    })
                    return cached_value
                else:
                    del self._embedding_cache[key]
            
        except Exception as e:
            self.logger.debug({
                "event": "embedding_cache_get_failed",
                "error": str(e)
            })
        
        return None

    def _set_embedding_cache(self, key: str, value: Any) -> bool:
        """設置嵌入向量快取"""
        try:
            self._embedding_cache[key] = (value, time.time())
            
            # 嘗試寫入 Redis
            if self.redis_client:
                try:
                    self.redis_client.setex(
                        key,
                        PerformanceConfig.EMBEDDING_CACHE_TTL,
                        json.dumps(value, default=str)
                    )
                except Exception as e:
                    self.logger.debug({
                        "event": "redis_setex_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            # 寫入後備快取
            if self.fallback_cache:
                try:
                    self.fallback_cache.setex(
                        key,
                        PerformanceConfig.EMBEDDING_CACHE_TTL,
                        value
                    )
                except Exception as e:
                    self.logger.debug({
                        "event": "fallback_setex_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            return True
        except Exception as e:
            self.logger.debug({
                "event": "embedding_cache_set_failed",
                "error": str(e)
            })
            return False

    def _get_emotion_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """從雙層快取取得情緒分析結果"""
        try:
            current_time = time.time()
            
            if self.redis_client:
                try:
                    cached = self.redis_client.get(key)
                    if cached:
                        self.logger.debug({
                            "event": "emotion_cache_hit_redis",
                            "cache_key": key
                        })
                        return json.loads(cached)
                except Exception as e:
                    self.logger.debug({
                        "event": "redis_get_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            # 後備快取
            if self.fallback_cache:
                try:
                    cached = self.fallback_cache.get(key)
                    if cached:
                        self.logger.debug({
                            "event": "emotion_cache_hit_fallback",
                            "cache_key": key
                        })
                        return cached
                except Exception as e:
                    self.logger.debug({
                        "event": "fallback_get_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            if key in self._emotion_cache:
                cached_value, cached_time = self._emotion_cache[key]
                if current_time - cached_time < PerformanceConfig.EMOTION_CACHE_TTL:
                    self.logger.debug({
                        "event": "emotion_cache_hit_memory",
                        "cache_key": key
                    })
                    return cached_value
                else:
                    del self._emotion_cache[key]
            
        except Exception as e:
            self.logger.debug({
                "event": "emotion_cache_get_failed",
                "error": str(e)
            })
        
        return None

    def _set_emotion_cache(self, key: str, value: Dict[str, Any]) -> bool:
        """設置情緒分析快取"""
        try:
            self._emotion_cache[key] = (value, time.time())
            
            if self.redis_client:
                try:
                    self.redis_client.setex(
                        key,
                        PerformanceConfig.EMOTION_CACHE_TTL,
                        json.dumps(value, ensure_ascii=False, default=str)
                    )
                except Exception as e:
                    self.logger.debug({
                        "event": "redis_setex_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            if self.fallback_cache:
                try:
                    self.fallback_cache.setex(
                        key,
                        PerformanceConfig.EMOTION_CACHE_TTL,
                        value
                    )
                except Exception as e:
                    self.logger.debug({
                        "event": "fallback_setex_failed",
                        "key": key,
                        "error": str(e)
                    })
            
            return True
        except Exception as e:
            self.logger.debug({
                "event": "emotion_cache_set_failed",
                "error": str(e)
            })
            return False

    # ==================== 天氣功能 ====================

    def _is_weather_related(self, text: str) -> bool:
        """檢測文本是否與天氣相關"""
        if not text:
            return False
        
        weather_keywords = [
            '天氣', '下雨', '溫度', '日出', '日落', '月亮', '月相',
            '天晴', '下雪', '颱風', '暴雨', '陰天', '氣溫', '陽光',
            'weather', 'rain', 'temperature', 'moon', 'sunset', 'sunny'
        ]
        
        text_lower = text.lower()
        return any(kw in text_lower for kw in weather_keywords)

    async def _fetch_weather_context(self) -> str:
        """非同步獲取天氣上下文"""
        try:
            if not self.hko:
                return ""
            
            loop = asyncio.get_running_loop()
            weather_context = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.hko.get_formatted_weather_context
                ),
                timeout=PerformanceConfig.WEATHER_FETCH_TIMEOUT
            )
            
            return weather_context if weather_context else ""
        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "weather_fetch_timeout",
                "timeout": PerformanceConfig.WEATHER_FETCH_TIMEOUT
            })
            return ""
        except Exception as e:
            self.logger.debug({
                "event": "weather_fetch_failed",
                "error": str(e)
            })
            return ""

    # ==================== 情緒分析 ====================

    async def _analyze_emotions(self, user_text: str) -> Dict[str, Any]:
        """非同步情緒分析 - 保留 VAD 與危機信號欄位。"""
        try:
            emotion_cache_key = self._build_emotion_cache_key(user_text)
            
            cached_emotions = self._get_emotion_cache(emotion_cache_key)
            if cached_emotions:
                self.logger.debug({
                    "event": "emotion_fast_path_hit",
                    "cache_key": emotion_cache_key
                })
                return self._normalize_emotion_profile(cached_emotions)
            
            loop = asyncio.get_running_loop()
            
            try:
                emotion_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self.emotion.analyze_emotions,
                        user_text
                    ),
                    timeout=PerformanceConfig.EMOTION_ANALYSIS_TIMEOUT
                )
            except asyncio.TimeoutError:
                self.logger.warning({
                    "event": "emotion_analysis_timeout_using_default",
                    "timeout": PerformanceConfig.EMOTION_ANALYSIS_TIMEOUT
                })
                emotions_vsc = self._normalize_emotion_profile(None)
                self._set_emotion_cache(emotion_cache_key, emotions_vsc)
                return emotions_vsc
            
            emotions_vsc = self._normalize_emotion_profile(emotion_result)
            self._set_emotion_cache(emotion_cache_key, emotions_vsc)
            
            return emotions_vsc
            
        except Exception as e:
            self.logger.warning({
                "event": "emotion_analysis_failed",
                "error": str(e)
            })
            return self._normalize_emotion_profile(None)

    # ==================== 嵌入向量化 ====================

    async def _get_embedding(self, user_text: str) -> Optional[List[float]]:
        """非同步取得文本嵌入向量"""
        try:
            embedding_cache_key = self._build_embedding_cache_key(user_text)
            
            cached_embedding = self._get_embedding_cache(embedding_cache_key)
            if cached_embedding is not None:
                self.logger.debug({
                    "event": "embedding_cache_hit",
                    "cache_key": embedding_cache_key
                })
                return cached_embedding
            
            loop = asyncio.get_running_loop()
            embedding = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.vector.get_semantic_embedding,
                    user_text
                ),
                timeout=PerformanceConfig.EMBEDDING_GENERATION_TIMEOUT
            )
            
            if embedding is not None:
                self._set_embedding_cache(embedding_cache_key, embedding)
            
            return embedding
            
        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "embedding_generation_timeout",
                "timeout": PerformanceConfig.EMBEDDING_GENERATION_TIMEOUT
            })
            return None
        except Exception as e:
            self.logger.debug({
                "event": "embedding_generation_failed",
                "error": str(e)
            })
            return None

    # ==================== 向量驗證（完整修復版） ====================

    def _is_valid_embedding(self, embedding: Optional[List[float]]) -> bool:
        """[FIX-BUG-001] 完整的嵌入向量驗證"""
        if embedding is None:
            return False
        
        if not isinstance(embedding, (list, tuple)):
            return False
        
        if len(embedding) == 0:
            return False
        
        # 標準維度檢查
        standard_dims = {96, 128, 256, 384, 512, 768, 1024}
        if len(embedding) not in standard_dims:
            self.logger.warning({
                "event": "unusual_embedding_dimension",
                "dimension": len(embedding),
                "standard_dims": list(standard_dims)
            })
        
        # 檢查所有值（不僅僅是前10個）
        nan_count = 0
        inf_count = 0
        
        try:
            for idx, val in enumerate(embedding):
                if not isinstance(val, (int, float)):
                    self.logger.warning({
                        "event": "non_numeric_embedding_value",
                        "index": idx,
                        "type": type(val).__name__
                    })
                    return False
                
                # [FIX-BUG-001] 檢查 NaN
                if isinstance(val, float) and math.isnan(val):
                    nan_count += 1
                    continue
                
                # 檢查無窮大
                if isinstance(val, float) and math.isinf(val):
                    inf_count += 1
                    continue
                
                # 範圍檢查（通常在 -1 到 1，但允許 -100 到 100 的容限）
                if not (-100 <= val <= 100):
                    self.logger.warning({
                        "event": "embedding_value_out_of_range",
                        "index": idx,
                        "value": val,
                        "min": -100,
                        "max": 100
                    })
                    return False
        
        except Exception as e:
            self.logger.warning({
                "event": "embedding_validation_exception",
                "error": str(e)
            })
            return False
        
        # 計算異常比例
        total_anomalies = nan_count + inf_count
        anomaly_ratio = total_anomalies / len(embedding) if len(embedding) > 0 else 0
        
        if anomaly_ratio > 0.3:
            self.logger.warning({
                "event": "high_anomaly_ratio_in_embedding",
                "nan_count": nan_count,
                "inf_count": inf_count,
                "total": len(embedding),
                "ratio": round(anomaly_ratio, 3)
            })
            return False
        
        return True

    # ==================== 安全回應（完整版） ====================

    def _get_safe_reply(self, response_type: str = 'system_error') -> str:
        """Return companion-safe fallback text (policy + user-facing gate)."""
        from app.clinical.companion_language_policy import get_companion_reply
        from app.clinical.user_facing_gate import apply_user_facing_gate

        reply = get_companion_reply(response_type)

        if len(reply.strip()) <= 10:
            self.logger.error({
                "event": "safe_reply_too_short",
                "response_type": response_type,
                "length": len(reply.strip())
            })
            reply = get_companion_reply('fallback')

        risk_hint = 5 if response_type == 'critical' else 4 if response_type == 'high_risk' else 1
        gate = apply_user_facing_gate(
            reply,
            risk_level=risk_hint,
            source=f"orchestrator_get_safe_reply:{response_type}",
        )
        if gate.sanitized:
            self.logger.warning({
                "event": "companion_gate_safe_reply_sanitized",
                "response_type": response_type,
                "issues": list(gate.issues),
            })
        return gate.text

    async def _generate_draft_response(
        self,
        user_text: str,
        session_state: Dict[str, Any],
        emotions_vsc: Dict[str, float],
        language_hint: Optional[str] = None,
        weather_context: str = "",
        memory_context: str = "",
        sensing_bundle: Optional[SensingBundle] = None,
        result: Optional[Dict[str, Any]] = None,
        personality_system_prompt: str = "",
    ) -> str:
        """當 Navigator 未產出回應時，透過 Star-Orchestration 或 LLM 管線生成初稿。

        personality_system_prompt：PersonalityModule Layer 1（PersonaGraph + SystemPromptBuilder）
        前置產出的完整系統提示。有則優先使用，使初稿已帶希兒人格方向。
        """
        min_len = PerformanceConfig.MIN_RESPONSE_LENGTH

        # Zero-Truncation：前置人格 prompt 完整注入，不截斷。
        seele_prompt = (personality_system_prompt or "").strip()
        if seele_prompt:
            base_system_parts = [seele_prompt]
            if language_hint:
                base_system_parts.append(f"語言偏好: {language_hint}")
        else:
            base_system_parts = [
                "你是 Vita，一位溫暖、專業的心理伴侶。",
                "以自然、有同理心的繁體中文回應，避免過短或敷衍。",
            ]
            if language_hint:
                base_system_parts.append(f"語言偏好: {language_hint}")

        # v9: Nemo primary -> conditional Llama audit -> Gemma personality
        if (
            sensing_bundle
            and self.star_orchestration
            and self.star_orchestration.enabled
        ):
            from app.utils.llm_availability import snapshot_llm_availability

            llm_avail = await snapshot_llm_availability(
                timeout=PerformanceConfig.LLM_PROBE_TIMEOUT,
            )
            star_timeout = PerformanceConfig.STAR_ORCHESTRATION_TIMEOUT
            if not llm_avail.star_soul_available:
                star_timeout = PerformanceConfig.STAR_ORCHESTRATION_TIMEOUT_DEGRADED

            if not llm_avail.any_generative_llm:
                self.logger.warning({
                    "event": "star_orchestration_skipped",
                    "reason": "all_generative_llms_unreachable",
                    "details": llm_avail.details,
                    "status": "skipped",
                })
            else:
                from app.config import config as app_config

                persona_name = getattr(app_config, 'PERSONA_NAME', '希兒')
                if persona_name and ',' in persona_name:
                    persona_name = persona_name.split(',')[-1].strip()

                try:
                    star_result = await asyncio.wait_for(
                        self.star_orchestration.execute(
                            sensing_bundle,
                            base_system_prompt="\n".join(base_system_parts),
                            persona_name=persona_name,
                        ),
                        timeout=star_timeout,
                    )
                    star_text_ok = (
                        star_result.success
                        and len(star_result.text or "") >= min_len
                    )

                    if result is not None:
                        result['metadata']['star_orchestration'] = {
                            'used': True,
                            'pipeline_version': getattr(
                                star_result, 'pipeline_version', 'v9',
                            ),
                            'pipeline_stages': star_result.pipeline_stages,
                            'execution_track': star_result.execution_track,
                            'primary_text_length': len(star_result.primary_text or ""),
                            'meta_audit': star_result.meta_audit,
                            'meta_layer': star_result.meta_layer,
                            'user_shadow': star_result.user_shadow,
                            'nemo_regenerated': (
                                (star_result.meta_layer or {}).get('nemo_regenerated', False)
                            ),
                            'soul_guidance': star_result.meta_audit,
                            'draft_length': len(star_result.draft_text or ""),
                            'inference_time_sec': round(star_result.inference_time, 3),
                            'success': star_text_ok,
                            'llm_availability': {
                                'main_llm': llm_avail.main_llm,
                                'logic_llm': llm_avail.logic_llm,
                                'revise_llm': llm_avail.revise_llm,
                            },
                            'timeout_sec': star_timeout,
                        }
                        if star_text_ok:
                            result['metadata']['star_orchestration_used'] = True
                            result['metadata']['llm_draft_used'] = True

                    if star_text_ok:
                        self.logger.info({
                            "event": "star_orchestration_complete",
                            "response_length": len(star_result.text),
                            "pipeline": star_result.pipeline_stages,
                            "status": "success",
                        })
                        return star_result.text

                    self.logger.warning({
                        "event": "star_orchestration_degraded",
                        "error": star_result.error,
                        "pipeline": star_result.pipeline_stages,
                        "response_length": len(star_result.text or ""),
                        "status": "degraded",
                    })
                except asyncio.TimeoutError:
                    self.logger.warning({
                        "event": "star_orchestration_timeout",
                        "timeout": star_timeout,
                        "soul_available": llm_avail.star_soul_available,
                        "status": "timeout",
                    })
                except Exception as star_exc:
                    self.logger.warning({
                        "event": "star_orchestration_failed",
                        "error": str(star_exc),
                        "status": "error",
                    })

        # Legacy fallback: Soul -> Revise -> Logic polish (Soul 不可達時跳過心理分析)
        try:
            from app.utils.llm_availability import is_main_llm_reachable

            main_llm_ok, _ = await is_main_llm_reachable(
                timeout=PerformanceConfig.LLM_PROBE_TIMEOUT,
            )
            use_psychology = main_llm_ok
            context_window = session_state.get('context_window', [])
            history_lines = []
            for turn in context_window[-6:]:
                if isinstance(turn, dict):
                    role = turn.get('role', 'user')
                    content = turn.get('content', turn.get('text', ''))
                    if content:
                        history_lines.append(f"{role}: {content}")

            system_parts = list(base_system_parts)
            if weather_context:
                system_parts.append(f"天氣背景: {weather_context}")
            if emotions_vsc:
                system_parts.append(
                    f"情緒狀態 valence={emotions_vsc.get('valence', 0.5):.2f}, "
                    f"arousal={emotions_vsc.get('arousal', 0.3):.2f}"
                )
            if memory_context:
                system_parts.append(f"相關記憶（供參考，勿逐字重複）:\n{memory_context}")

            prompt_parts = []
            if history_lines:
                prompt_parts.append("近期對話:\n" + "\n".join(history_lines))
            prompt_parts.append(f"用戶: {user_text}")
            prompt_parts.append("Vita:")

            llm_result = await asyncio.wait_for(
                llm_service.generate_full_response_async(
                    prompt="\n".join(prompt_parts),
                    system_prompt="\n".join(system_parts),
                    use_psychology=use_psychology,
                    use_polish=True,
                ),
                timeout=PerformanceConfig.LLM_DRAFT_GENERATION_TIMEOUT,
            )

            draft = (llm_result.content or "").strip() if llm_result else ""
            if draft and len(draft) >= min_len and llm_result.is_success():
                if result is not None:
                    result['metadata']['star_orchestration'] = {
                        'used': False,
                        'fallback': 'legacy_pipeline',
                        'pipeline_stages': llm_result.pipeline_stages,
                    }
                self.logger.info({
                    "event": "llm_draft_generated",
                    "response_length": len(draft),
                    "pipeline": llm_result.pipeline_stages,
                    "status": "success",
                })
                return draft

            self.logger.warning({
                "event": "llm_draft_generation_empty",
                "response_length": len(draft),
                "error": getattr(llm_result, 'error', None),
                "status": "degraded"
            })
            return ""

        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "llm_draft_generation_timeout",
                "timeout": PerformanceConfig.LLM_DRAFT_GENERATION_TIMEOUT,
                "status": "timeout"
            })
            return ""
        except Exception as e:
            self.logger.warning({
                "event": "llm_draft_generation_failed",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "status": "error"
            })
            return ""

    def _normalize_emotion_profile(self, emotion_result: Any) -> Dict[str, Any]:
        """統一 EmotionService 輸出結構（含危機信號）。"""
        profile: Dict[str, Any] = {
            'valence': 0.5,
            'arousal': 0.3,
            'dominance': 0.5,
            'dominant_emotion': 'neutral',
            'is_crisis_risk': False,
            'detected_crisis_keywords': [],
            'confidence': 0.0,
            'method': 'fallback',
        }
        if not isinstance(emotion_result, dict):
            return profile

        profile['valence'] = float(emotion_result.get('valence', 0.5))
        profile['arousal'] = float(emotion_result.get('arousal', 0.3))
        profile['dominance'] = float(emotion_result.get('dominance', 0.5))
        profile['dominant_emotion'] = str(emotion_result.get('dominant_emotion', 'neutral'))
        profile['is_crisis_risk'] = bool(emotion_result.get('is_crisis_risk', False))
        profile['detected_crisis_keywords'] = list(
            emotion_result.get('detected_crisis_keywords') or []
        )
        profile['confidence'] = float(emotion_result.get('confidence', 0.0))
        profile['method'] = str(emotion_result.get('method', 'unknown'))
        if isinstance(emotion_result.get('emotion_vector'), dict):
            profile['emotion_vector'] = dict(emotion_result['emotion_vector'])
        if isinstance(emotion_result.get('emotion_dimensions'), dict):
            profile['emotion_dimensions'] = dict(emotion_result['emotion_dimensions'])
            profile['emotion_dimension_count'] = int(
                emotion_result.get('emotion_dimension_count', len(profile['emotion_dimensions']))
            )
        elif profile.get('valence') is not None:
            try:
                from app.utils.emotion_dimensions import (
                    expand_emotion_dimensions_24,
                    emotion_dimension_count,
                )
                vad = {
                    'valence': profile['valence'],
                    'arousal': profile['arousal'],
                    'dominance': profile['dominance'],
                }
                ev10 = emotion_result.get('emotion_vector') if isinstance(
                    emotion_result.get('emotion_vector'), dict
                ) else None
                profile['emotion_dimensions'] = expand_emotion_dimensions_24(vad, ev10)
                profile['emotion_dimension_count'] = emotion_dimension_count()
            except Exception:
                pass
        return profile

    def _is_response_too_short(self, response: Any) -> bool:
        """檢查回應是否過短（Zero-Truncation：拒絕敷衍式短回覆）。"""
        if not response:
            return True
        return len(str(response).strip()) < PerformanceConfig.MIN_RESPONSE_LENGTH

    def _finalize_turn_outcome(
        self,
        result: Dict[str, Any],
        final_response: str,
        session_id: str,
        fallback_reason: Optional[str] = None,
    ) -> str:
        """
        最終回應品質閘門：禁止過短回覆標記為 success。
        必要時套用安全保底回覆（完整文本，不截斷）。
        """
        min_len = PerformanceConfig.MIN_RESPONSE_LENGTH
        text = (final_response or "").strip()
        risk_level = int(result.get('risk_level', 0) or 0)

        if len(text) < min_len:
            safe_type = 'critical' if risk_level >= 4 else 'fallback'
            text = self._get_safe_reply(safe_type)
            result['metadata']['response_fallback'] = fallback_reason or 'empty_or_short_response'
            result['warnings'].append(
                f"Response below minimum length ({min_len}); safe reply applied"
            )
            self.logger.warning({
                "event": "fallback_response_activated",
                "session_id": session_id,
                "reason": result['metadata']['response_fallback'],
                "risk_level": risk_level,
                "final_response_length": len(text),
            })

        if len(text.strip()) < min_len:
            result['success'] = False
            result['metadata']['response_quality'] = 'failed'
            self.logger.error({
                "event": "safe_reply_still_too_short",
                "session_id": session_id,
                "response_length": len(text.strip()),
                "minimum_required": min_len,
            })
        else:
            result['success'] = True
            if result['metadata'].get('response_fallback'):
                result['metadata']['response_quality'] = 'degraded'
            else:
                result['metadata']['response_quality'] = 'ok'

        from app.clinical.user_facing_gate import apply_user_facing_gate

        gate = apply_user_facing_gate(
            text,
            risk_level=risk_level,
            source="orchestrator_finalize_turn",
        )
        if gate.sanitized:
            result['metadata']['companion_gate_sanitized'] = True
            result['metadata']['response_quality'] = 'degraded'
            result['warnings'].append(
                "Response sanitized by companion user-facing gate"
            )
            self.logger.warning({
                "event": "companion_gate_sanitized",
                "session_id": session_id,
                "risk_level": risk_level,
                "issue_count": len(gate.issues),
                "fallback_tier": gate.fallback_tier,
            })
            text = gate.text

        return text

    # ==================== Navigator 決策層 ====================

    async def _get_navigator_decision(
        self,
        user_id: str,
        user_text: str,
        session_state: Dict[str, Any],
        emotions_vsc: Dict[str, float]
    ) -> Tuple[str, Dict[str, Any]]:
        """調用 IntelligentNavigator 進行雙軌決策"""
        if not self.navigator:
            return "", {
                'final_decision': 'error',
                'error': 'Navigator not initialized',
                'track_used': 'error'
            }
        
        try:
            loop = asyncio.get_running_loop()
            intimacy = session_state.get('intimacy', 0.5)
            
            response, nav_decision = await asyncio.wait_for(
                self.navigator.navigate_async(
                    user_id=user_id,
                    user_input=user_text,
                    session_history=session_state.get('context_window', []),
                    intimacy=intimacy
                ),
                timeout=PerformanceConfig.NAVIGATOR_TIMEOUT
            )
            
            nav_log: Dict[str, Any] = {
                'final_decision': nav_decision.decision_type,
                'decision_id': nav_decision.decision_id,
                'detected_fractures': [
                    {
                        'keyword': f.trigger_keyword,
                        'severity': f.severity_level,
                        'confidence': f.confidence
                    }
                    for f in nav_decision.detected_fractures
                ],
                'crisis_triggered': nav_decision.decision_type == 'safety_mode',
                'track_used': 'fast' if nav_decision.decision_type == 'safety_mode' else 'slow',
                'response': response,
                'intimacy_level': nav_decision.intimacy_level,
                'total_time': nav_decision.total_time
            }
            
            self.logger.debug({
                "event": "navigator_decision_success",
                "user_id": user_id,
                "decision_type": nav_decision.decision_type,
                "duration_ms": round(nav_decision.total_time * 1000, 1)
            })
            
            return response, nav_log
            
        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "navigator_decision_timeout",
                "user_id": user_id,
                "timeout": PerformanceConfig.NAVIGATOR_TIMEOUT
            })
            return "", {
                'final_decision': 'timeout',
                'error': 'Navigator timeout',
                'track_used': 'error'
            }
        except Exception as e:
            self.logger.error({
                "event": "navigator_decision_failed",
                "user_id": user_id,
                "error": str(e)
            })
            return "", {
                'final_decision': 'error',
                'error': str(e),
                'track_used': 'error'
            }

    # ==================== GSW 記憶相關方法 ====================

    async def _process_gsw_memories(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
        response_vector: Optional[List[float]],
        session_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """非同步處理 GSW 永迴軌與記憶檢測"""
        if not self.gsw_engine:
            return {'drift_score': 0.5, 'closest_core_memory': None}
        
        try:
            loop = asyncio.get_running_loop()
            
            # detect_drift 為 async；不可丟進 run_in_executor（會得到 coroutine 物件）。
            if asyncio.iscoroutinefunction(self.gsw_engine.detect_drift):
                drift_result = await asyncio.wait_for(
                    self.gsw_engine.detect_drift(
                        response_vector=response_vector,
                        user_input=user_text,
                        session_state=session_state,
                    ),
                    timeout=PerformanceConfig.GSW_TIMEOUT
                )
            else:
                drift_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self.gsw_engine.detect_drift,
                        response_vector,
                        user_text,
                        session_state
                    ),
                    timeout=PerformanceConfig.GSW_TIMEOUT
                )

            if asyncio.iscoroutine(drift_result):
                self.logger.error({
                    "event": "gsw_drift_coroutine_leak",
                    "session_id": session_id,
                })
                return {'drift_score': 0.5, 'closest_core_memory': None, 'available': False}

            return drift_result if drift_result else {'drift_score': 0.5, 'closest_core_memory': None}
            
        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "gsw_drift_detection_timeout",
                "session_id": session_id
            })
            return {'drift_score': 0.5, 'closest_core_memory': None}
        except Exception as e:
            self.logger.debug({
                "event": "gsw_drift_detection_failed",
                "error": str(e)
            })
            return {'drift_score': 0.5, 'closest_core_memory': None}

    # ==================== Fracture Map 相關方法 ====================

    async def _check_fracture_points(
        self,
        user_id: str,
        user_text: str,
        emotions_vsc: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """非同步檢查用戶的裂痕點觸發"""
        if not self.db_fm:
            return []
        
        try:
            loop = asyncio.get_running_loop()
            
            fracture_points = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self.db_fm.get_user_fracture_points,
                    user_id
                ),
                timeout=PerformanceConfig.FRACTURE_CHECK_TIMEOUT
            )
            
            triggered: List[Dict[str, Any]] = []
            for fp in fracture_points:
                keywords = fp.get('context_tags', [])
                emotion_spike = fp.get('emotion_spike_score', 0.0)
                current_arousal = emotions_vsc.get('arousal', 0.0)
                
                if any(kw in user_text for kw in keywords) or current_arousal > emotion_spike:
                    triggered.append(fp)
            
            if triggered:
                self.logger.debug({
                    "event": "fracture_points_triggered",
                    "user_id": user_id,
                    "count": len(triggered)
                })
            
            return triggered
            
        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "fracture_check_timeout",
                "user_id": user_id
            })
            return []
        except Exception as e:
            self.logger.debug({
                "event": "fracture_check_failed",
                "error": str(e)
            })
            return []

    # ==================== 背景資料庫寫入 ====================

    async def _background_memory_persist(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
        final_response: str,
        user_embedding: Optional[List[float]],
        emotions_vsc: Dict[str, Any],
        session_state: Dict[str, Any],
        risk_level: int,
        skip_persist: bool = False,
    ) -> None:
        """Background: embed response (8084) and persist turn to pgvector."""
        if skip_persist or not self.memory_chain:
            return

        try:
            response_embedding = user_embedding
            if final_response:
                response_embedding = await self._get_embedding(final_response) or user_embedding

            await self.memory_chain.persist_turn(
                user_id=user_id,
                session_id=session_id,
                user_input=user_text,
                response=final_response,
                user_embedding=user_embedding,
                response_embedding=response_embedding,
                session_state=session_state,
                emotion_profile=emotions_vsc,
                risk_level=risk_level,
            )
        except Exception as e:
            self.logger.warning({
                "event": "background_memory_persist_failed",
                "session_id": session_id,
                "user_id": user_id,
                "error": str(e),
            })

    async def _background_kag_persist(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
    ) -> None:
        """Background: extract and persist user-stated reality facts."""
        if not self.kag_reality or not self.kag_reality.enabled:
            return
        try:
            loop = asyncio.get_running_loop()
            ids = await loop.run_in_executor(
                None,
                lambda: self.kag_reality.persist_user_statement_facts(
                    user_id=user_id,
                    user_text=user_text,
                    session_id=session_id,
                ),
            )
            if ids:
                self.logger.debug({
                    "event": "kag_facts_persisted",
                    "session_id": session_id,
                    "user_id": user_id,
                    "count": len(ids),
                })
        except Exception as e:
            self.logger.warning({
                "event": "background_kag_persist_failed",
                "session_id": session_id,
                "user_id": user_id,
                "error": str(e),
            })

    async def _background_cognitive_persist(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
        emotions_vsc: Dict[str, Any],
        session_state: Dict[str, Any],
        risk_level: int,
        meta_layer: Optional[Dict[str, Any]] = None,
        evolved_shadow: Optional[Dict[str, float]] = None,
    ) -> None:
        """Background: evolve User Shadow and record psychological milestones."""
        if not self.cognitive_persistence or not self.cognitive_persistence.enabled:
            return

        try:
            loop = asyncio.get_running_loop()

            def _sync_persist():
                return self.cognitive_persistence.persist_turn(
                    user_id=user_id,
                    session_id=session_id,
                    emotion_profile=emotions_vsc,
                    risk_level=risk_level,
                    session_state=session_state,
                    meta_layer=meta_layer,
                    user_text=user_text,
                    evolved_shadow=evolved_shadow,
                )

            evolved, milestone_ids = await loop.run_in_executor(None, _sync_persist)
            self.logger.debug({
                "event": "cognitive_persist_complete",
                "session_id": session_id,
                "user_id": user_id,
                "shadow": evolved.to_dict(),
                "milestones_recorded": len(milestone_ids),
            })
        except Exception as e:
            self.logger.warning({
                "event": "background_cognitive_persist_failed",
                "session_id": session_id,
                "user_id": user_id,
                "error": str(e),
            })

    async def _background_db_write(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
        final_response: str,
        emotions_vsc: Dict[str, float],
        embedding: Optional[List[float]],
        risk_level: int,
        language_hint: Optional[str],
        nav_log: Optional[Dict[str, Any]] = None,
        meta_layer: Optional[Dict[str, Any]] = None,
    ) -> None:
        """背景執行資料庫寫入 (Fire and Forget)"""
        try:
            loop = asyncio.get_running_loop()
            
            def _sync_db_write() -> None:
                """同步 DB 寫入包裝函數"""
                try:
                    self.db.store_turn(
                        session_id=session_id,
                        user_id=user_id,
                        role='user',
                        text=user_text,
                        emotions_vsc=emotions_vsc,
                        risk_level=risk_level,
                        safety_audit={},
                        embedding=embedding,
                        emotion_vector=emotions_vsc,
                        metadata={
                            'source': 'orchestrator_v5.5.6',
                            'language_hint': language_hint,
                            'timestamp': datetime.utcnow().isoformat(),
                            'environment': self.environment
                        }
                    )
                    
                    assistant_meta = {
                            'source': 'orchestrator_v5.5.6',
                            'timestamp': datetime.utcnow().isoformat(),
                            'navigator_decision': nav_log.get('final_decision') if nav_log else None,
                            'environment': self.environment,
                        }
                    if meta_layer:
                        assistant_meta['meta_layer'] = meta_layer

                    self.db.store_turn(
                        session_id=session_id,
                        user_id=user_id,
                        role='assistant',
                        text=final_response,
                        emotions_vsc=None,
                        risk_level=0,
                        safety_audit=meta_layer or nav_log or {},
                        embedding=None,
                        emotion_vector=None,
                        metadata=assistant_meta,
                    )
                    
                    self.logger.debug({
                        "event": "background_db_write_success",
                        "session_id": session_id,
                        "user_id": user_id,
                        "turns_written": 2
                    })
                    
                except Exception as e:
                    self.logger.error({
                        "event": "background_db_write_failed",
                        "session_id": session_id,
                        "user_id": user_id,
                        "error": str(e),
                        "traceback": traceback.format_exc()
                    })
            
            task = loop.run_in_executor(None, _sync_db_write)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            
            await self._cleanup_background_tasks()
            
        except Exception as e:
            self.logger.error({
                "event": "background_write_task_creation_failed",
                "error": str(e)
            })

    async def _cleanup_background_tasks(self) -> None:
        """清理已完成的背景任務"""
        current_time = time.time()
        
        if current_time - self._last_cleanup < PerformanceConfig.TASK_CLEANUP_INTERVAL:
            return
        
        try:
            done_tasks = [t for t in self._background_tasks if t.done()]
            for task in done_tasks:
                self._background_tasks.discard(task)
                try:
                    task.result()
                except Exception as e:
                    self.logger.warning({
                        "event": "background_task_error",
                        "error": str(e)
                    })
            
            self._last_cleanup = current_time
            
            if len(self._background_tasks) > PerformanceConfig.MAX_BACKGROUND_TASKS:
                self.logger.warning({
                    "event": "background_tasks_overflow",
                    "count": len(self._background_tasks),
                    "max": PerformanceConfig.MAX_BACKGROUND_TASKS
                })
        except Exception as e:
            self.logger.error({
                "event": "cleanup_background_tasks_failed",
                "error": str(e)
            })

    # ==================== 主核心流程 ====================

    async def process(
        self,
        request: ChatRequest,
        language_hint: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """API 入口"""
        try:
            session_id = self._resolve_session_id(request)
            if not session_id:
                self.logger.error({
                    "event": "session_resolution_failed",
                    "user_id": request.user_id,
                    "status": "error"
                })
                return {
                    "success": False,
                    "text": self._get_safe_reply('system_error'),
                    "session_id": "unknown",
                    "phase": ConversationPhase.GREETING.value,
                    "risk_level": 0,
                    "emotion_analysis": {'valence': 0.5, 'arousal': 0.3, 'dominance': 0.5},
                    "warnings": ["無法建立或恢復會話"],
                    "metadata": {}
                }
            
            user_text = (
                getattr(request, 'text', None) or
                getattr(request, 'message', None) or
                getattr(request, 'user_text', '')
            )
            
            if not user_text or not str(user_text).strip():
                self.logger.warning({
                    "event": "empty_user_input",
                    "session_id": session_id,
                    "user_id": request.user_id
                })
                return {
                    "success": False,
                    "text": self._get_safe_reply('empty_input'),
                    "session_id": session_id,
                    "phase": ConversationPhase.GREETING.value,
                    "risk_level": 0,
                    "emotion_analysis": {'valence': 0.5, 'arousal': 0.3, 'dominance': 0.5},
                    "warnings": ["輸入文本為空"],
                    "metadata": {}
                }

            from app.security.prompt_sanitizer import sanitize_user_input_for_llm

            sanitize_result = sanitize_user_input_for_llm(
                str(user_text),
                user_id=str(request.user_id),
                session_id=str(session_id),
                audit=True,
            )
            user_text = sanitize_result.sanitized_text
            
            return await self.process_user_message_async(
                session_id=session_id,
                user_id=request.user_id,
                user_text=user_text,
                language_hint=language_hint,
                prompt_sanitize_metadata={
                    "patterns_detected": list(sanitize_result.patterns_detected),
                    "was_modified": sanitize_result.was_modified,
                },
                **kwargs
            )
            
        except Exception as e:
            self.logger.error({
                "event": "process_exception",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "status": "error"
            })
            return {
                "success": False,
                "text": self._get_safe_reply('fallback'),
                "session_id": getattr(request, 'session_id', 'unknown'),
                "phase": ConversationPhase.GREETING.value,
                "risk_level": 0,
                "emotion_analysis": {'valence': 0.5, 'arousal': 0.3, 'dominance': 0.5},
                "warnings": [str(e)],
                "metadata": {}
            }

    def _record_chat_processing_latency(
        self,
        process_duration_seconds: float,
        risk_level: int,
    ) -> None:
        """Observe vita_chat_processing_seconds for the runtime /chat path (SLO-2/3).

        Metric recording must never break the chat turn, so failures are logged
        at debug level and swallowed.
        """
        try:
            from app.metrics.chat_latency_metrics import (
                record_chat_processing_from_risk_level,
            )

            record_chat_processing_from_risk_level(
                risk_level=int(risk_level or 0),
                duration_seconds=float(process_duration_seconds),
            )
        except Exception as metric_error:
            self.logger.debug({
                "event": "chat_latency_metric_record_failed",
                "error": str(metric_error),
            })

    async def process_user_message_async(
        self,
        session_id: str,
        user_id: str,
        user_text: str,
        language_hint: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        [FIX-BUG-005] 核心非同步流程 (v5.5.6 生產環境版修正)
        
        流程改進：
        1. 取得會話狀態
        2. 並行收集：情緒、向量、天氣 (優化超時)
        3. 檢測裂痕點
        4. 調用 IntelligentNavigator 進行雙軌決策
        5. 委派 PersonalityModule.anchor() 並驗證回應
        6. 格式化並立即回傳
        7. 背景執行 DB 寫入 (Fire and Forget)
        """
        process_start = datetime.now()
        loop = asyncio.get_running_loop()
        
        result: Dict[str, Any] = {
            'success': False,
            'text': '',
            'session_id': session_id,
            'phase': ConversationPhase.EXPLORATION.value,
            'risk_level': 0,
            'emotion_analysis': {'valence': 0.5, 'arousal': 0.3, 'dominance': 0.5},
            'warnings': [],
            'metadata': {
                'language_hint': language_hint,
                'processing_time_sec': 0.0,
                'cache_hits': {
                    'emotion': False,
                    'embedding': False,
                },
                'navigator_used': False,
                'personality_used': False,
                'llm_draft_used': False,
                'star_orchestration_used': False,
                'environment': self.environment,
            }
        }

        try:
            self.logger.info({
                "event": "process_user_message_start",
                "session_id": session_id,
                "user_id": user_id,
                "input_length": len(user_text),
                "language_hint": language_hint,
                "environment": self.environment
            })

            if kwargs.get("prompt_sanitize_metadata"):
                result["metadata"]["prompt_sanitize"] = kwargs["prompt_sanitize_metadata"]

            # ========== 1. 獲取會話狀態 ==========
            session_state: Dict[str, Any] = {
                'session_id': session_id,
                'user_id': user_id,
                'turn_count': 0,
                'risk_level': 0,
                'phase': ConversationPhase.GREETING.value,
                'intimacy': 0.1,
            }
            
            try:
                session_state = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self.db.get_session_state,
                        session_id
                    ),
                    timeout=PerformanceConfig.SESSION_STATE_FETCH_TIMEOUT
                ) or session_state
            except asyncio.TimeoutError:
                self.logger.warning({
                    "event": "session_state_fetch_timeout",
                    "session_id": session_id
                })
            except Exception as e:
                self.logger.warning({
                    "event": "session_state_fetch_failed",
                    "session_id": session_id,
                    "error": str(e)
                })

            if self.cognitive_persistence and self.cognitive_persistence.enabled:
                try:
                    stored_shadow = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            self.cognitive_persistence.load_shadow_dict,
                            user_id,
                        ),
                        timeout=PerformanceConfig.SESSION_STATE_FETCH_TIMEOUT,
                    )
                    if stored_shadow:
                        session_state['stored_shadow'] = stored_shadow
                        session_state['intimacy'] = max(
                            float(session_state.get('intimacy', 0.1)),
                            float(stored_shadow.get('trust', 0.5)),
                        )
                        session_state['hope'] = float(stored_shadow.get('hope', 0.5))
                        result['metadata']['cognitive_layer'] = {
                            'shadow_loaded': True,
                            'prior_turn_count': int(stored_shadow.get('turn_count', 0) or 0),
                        }
                except asyncio.TimeoutError:
                    self.logger.warning({
                        "event": "user_shadow_load_timeout",
                        "session_id": session_id,
                        "user_id": user_id,
                    })
                except Exception as shadow_exc:
                    self.logger.warning({
                        "event": "user_shadow_load_failed",
                        "session_id": session_id,
                        "user_id": user_id,
                        "error": str(shadow_exc),
                    })

            # ========== 2. 並行收集基礎信息（優化版） ==========
            emotion_cache_key = self._build_emotion_cache_key(user_text)
            embedding_cache_key = self._build_embedding_cache_key(user_text)
            
            try:
                emotion_task = self._analyze_emotions(user_text)
                embedding_task = self._get_embedding(user_text)
                
                # [FIX-BUG-005] 修復 Union 類型檢查
                if self._is_weather_related(user_text):
                    weather_task = self._fetch_weather_context()
                else:
                    async def _empty_coro():
                        return ""
                    weather_task = _empty_coro()
                
                gather_results = await asyncio.gather(
                    emotion_task,
                    embedding_task,
                    weather_task,
                    return_exceptions=True
                )
                
                emotions_vsc: Dict[str, float] = (
                    self._normalize_emotion_profile(gather_results[0])
                    if not isinstance(gather_results[0], Exception)
                    else self._normalize_emotion_profile(None)
                )
                
                embedding: Optional[List[float]] = (
                    gather_results[1]
                    if not isinstance(gather_results[1], Exception)
                    else None
                )
                
                # [FIX-BUG-001] 驗證嵌入向量
                if not self._is_valid_embedding(embedding):
                    self.logger.warning({
                        "event": "invalid_embedding_detected",
                        "session_id": session_id,
                        "embedding_type": type(embedding),
                        "embedding_length": len(embedding) if embedding else 0
                    })
                    embedding = None
                
                weather_context: str = (
                    gather_results[2]
                    if not isinstance(gather_results[2], Exception) and gather_results[2]
                    else ""
                )
                
                result['metadata']['cache_hits']['emotion'] = emotion_cache_key in self._emotion_cache
                result['metadata']['cache_hits']['embedding'] = embedding_cache_key in self._embedding_cache
                
            except Exception as e:
                self.logger.warning({
                    "event": "parallel_collection_failed",
                    "error": str(e)
                })
                emotions_vsc = self._normalize_emotion_profile(None)
                embedding = None
                weather_context = ""

            result['emotion_analysis'] = emotions_vsc

            # ========== 2.5 風險評估（關鍵詞 + Emotion 危機信號） ==========
            from app.config import config as app_config

            risk_assessment = assess_turn_risk(user_text, emotions_vsc)
            assessed_risk = int(risk_assessment.risk_level)
            prior_risk = int(session_state.get('risk_level', 0) or 0)
            session_risk = max(prior_risk, assessed_risk)
            session_state['risk_level'] = session_risk
            result['risk_level'] = session_risk
            result['metadata']['risk_assessment'] = {
                'risk_level': assessed_risk,
                'session_risk_level': session_risk,
                'crisis_keywords': risk_assessment.crisis_keywords,
                'confidence': risk_assessment.confidence,
                'sources': risk_assessment.sources,
            }

            self.logger.info({
                "event": "turn_risk_assessed",
                "session_id": session_id,
                "user_id": user_id,
                "assessed_risk_level": assessed_risk,
                "session_risk_level": session_risk,
                "crisis_keywords": risk_assessment.crisis_keywords,
                "is_crisis_risk": emotions_vsc.get('is_crisis_risk', False),
            })

            # ========== 2.6 記憶感知鏈（8084 BGE -> pgvector） ==========
            memory_context = ""
            retrieved_memories: List[Dict[str, Any]] = []
            memory_degraded = embedding is None

            if embedding and self.memory_chain:
                try:
                    memory_result = await asyncio.wait_for(
                        self.memory_chain.retrieve(
                            user_id=user_id,
                            query_vector=embedding,
                        ),
                        timeout=PerformanceConfig.MEMORY_RETRIEVAL_TIMEOUT,
                    )
                    retrieved_memories = memory_result.memories
                    memory_context = memory_result.context_text
                    memory_degraded = memory_result.degraded
                except asyncio.TimeoutError:
                    self.logger.warning({
                        "event": "memory_chain_retrieve_timeout",
                        "session_id": session_id,
                        "user_id": user_id,
                    })
                    memory_degraded = True
                except Exception as mem_exc:
                    self.logger.warning({
                        "event": "memory_chain_retrieve_failed",
                        "session_id": session_id,
                        "user_id": user_id,
                        "error": str(mem_exc),
                    })
                    memory_degraded = True

            result['metadata']['memory'] = {
                'retrieved_count': len(retrieved_memories),
                'context_available': bool(memory_context),
                'degraded': memory_degraded,
                'embedding_available': embedding is not None,
            }
            if retrieved_memories:
                self.logger.info({
                    "event": "memory_chain_retrieved",
                    "session_id": session_id,
                    "user_id": user_id,
                    "count": len(retrieved_memories),
                    "top_similarity": retrieved_memories[0].get('similarity'),
                })

            reality_context = ""
            reality_facts: List[Dict[str, Any]] = []
            if self.kag_reality and self.kag_reality.enabled:
                try:
                    recent_milestones: List[Dict[str, Any]] = []
                    if self.cognitive_persistence and self.cognitive_persistence.enabled:
                        recent_milestones = self.db.list_psychological_milestones(
                            user_id, limit=3,
                        )
                    shadow_for_kag = session_state.get("stored_shadow")
                    reality_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: self.kag_reality.build_reality_layer(
                                user_id=user_id,
                                user_text=user_text,
                                risk_level=session_risk,
                                weather_context=weather_context,
                                shadow_dict=shadow_for_kag,
                                milestones=recent_milestones,
                            ),
                        ),
                        timeout=PerformanceConfig.SESSION_STATE_FETCH_TIMEOUT,
                    )
                    reality_context = reality_result.context_text
                    reality_facts = reality_result.facts
                    result['metadata']['kag_reality'] = {
                        'enabled': True,
                        'fact_count': len(reality_facts),
                        'degraded': reality_result.degraded,
                        'sources': reality_result.sources,
                    }
                except asyncio.TimeoutError:
                    self.logger.warning({
                        "event": "kag_reality_build_timeout",
                        "session_id": session_id,
                        "user_id": user_id,
                    })
                except Exception as kag_exc:
                    self.logger.warning({
                        "event": "kag_reality_build_failed",
                        "session_id": session_id,
                        "user_id": user_id,
                        "error": str(kag_exc),
                    })

            self.logger.info({
                "event": "star_phase1_sensing_complete",
                "session_id": session_id,
                "user_id": user_id,
                "embedding_available": embedding is not None,
                "emotion_method": emotions_vsc.get('method', 'unknown'),
                "memory_count": len(retrieved_memories),
                "weather_available": bool(weather_context),
                "kag_fact_count": len(reality_facts),
            })

            sensing_bundle = SensingBundle(
                user_text=user_text,
                emotion_profile=emotions_vsc,
                embedding=embedding,
                weather_context=weather_context,
                memory_context=memory_context,
                retrieved_memories=retrieved_memories,
                language_hint=language_hint,
                risk_level=session_risk,
                session_state=session_state,
                reality_context=reality_context,
                reality_facts=reality_facts,
            )

            escalation_threshold = int(getattr(app_config, 'RISK_ESCALATION_THRESHOLD', 4))
            critical_fast_track = (
                session_risk >= escalation_threshold
                or bool(emotions_vsc.get('is_crisis_risk', False))
            )

            identity_intent = (
                None if critical_fast_track
                else detect_identity_intent(user_text)
            )
            persona_name = getattr(app_config, 'PERSONA_NAME', '希兒')
            if persona_name and ',' in persona_name:
                persona_name = persona_name.split(',')[-1].strip()

            final_response = ""
            nav_log: Optional[Dict[str, Any]] = None
            updated_session_state = session_state.copy()

            if identity_intent:
                final_response = get_identity_reply(identity_intent, persona_name)
                result['metadata']['identity_fast_track'] = identity_intent
                result['metadata']['navigator_used'] = False
                result['metadata']['personality_used'] = False
                result['metadata']['star_orchestration_used'] = False
                self.logger.info({
                    "event": "identity_fast_track_activated",
                    "session_id": session_id,
                    "user_id": user_id,
                    "intent": identity_intent,
                })
            elif critical_fast_track:
                final_response = self._get_safe_reply('critical')
                result['metadata']['fast_track'] = 'critical_safety'
                result['metadata']['navigator_used'] = False
                result['metadata']['personality_used'] = False
                self.logger.warning({
                    "event": "critical_fast_track_activated",
                    "session_id": session_id,
                    "user_id": user_id,
                    "risk_level": session_risk,
                    "escalation_threshold": escalation_threshold,
                })
            else:
                # ========== 3. 檢測裂痕點 ==========
                triggered_fractures = await self._check_fracture_points(
                    user_id=user_id,
                    user_text=user_text,
                    emotions_vsc=emotions_vsc
                )

                # ========== 4. 調用 IntelligentNavigator 進行雙軌決策 ==========
                use_navigator = self.navigator is not None and (
                    triggered_fractures or emotions_vsc.get('arousal', 0.0) > 0.6
                )
                
                if use_navigator:
                    try:
                        nav_response, nav_log = await self._get_navigator_decision(
                            user_id=user_id,
                            user_text=user_text,
                            session_state=session_state,
                            emotions_vsc=emotions_vsc
                        )
                        
                        if nav_response:
                            final_response = nav_response
                            result['metadata']['navigator_used'] = True
                            
                            self.logger.info({
                                "event": "navigator_response_used",
                                "session_id": session_id,
                                "decision_type": nav_log.get('final_decision')
                            })
                    except Exception as e:
                        self.logger.warning({
                            "event": "navigator_failed_fallback_to_personality",
                            "error": str(e)
                        })

                # ========== 4.4 Layer 1：PersonaGraph + SystemPrompt 前置 ==========
                # 在 draft 之前解析島嶼/階段/政策，並把完整 system_prompt 注入初稿生成。
                pre_draft_guidance: Optional[Dict[str, Any]] = None
                personality_system_prompt = ""
                # P3.3：只收集白名單 hints，不做 ABCD 分類
                orchestrator_hints: Dict[str, Any] = {}
                raw_hints = kwargs.get('orchestrator_hints')
                if isinstance(raw_hints, dict):
                    for key in (
                        'user_mode_hint',
                        'skip_echo_consolidation',
                        'expression_preference',
                        'force_quiet_presence',
                        'decision_correlation_id',
                    ):
                        if key in raw_hints and raw_hints[key] is not None:
                            orchestrator_hints[key] = raw_hints[key]
                for key in (
                    'user_mode_hint',
                    'skip_echo_consolidation',
                    'expression_preference',
                    'force_quiet_presence',
                ):
                    if key in kwargs and kwargs[key] is not None and key not in orchestrator_hints:
                        orchestrator_hints[key] = kwargs[key]
                if self.personality and hasattr(self.personality, 'prepare_draft_guidance'):
                    try:
                        pre_draft_guidance = self.personality.prepare_draft_guidance(
                            user_input=user_text,
                            session_state=updated_session_state,
                            turn_info={
                                'user_sentiment': emotions_vsc,
                                'memory_context': memory_context,
                                'retrieved_memories': retrieved_memories,
                                'risk_level': session_risk,
                                'orchestrator_hints': orchestrator_hints,
                            },
                        )
                        if isinstance(pre_draft_guidance, dict):
                            personality_system_prompt = str(
                                pre_draft_guidance.get('system_prompt') or ""
                            )
                            if pre_draft_guidance.get('primary_island'):
                                updated_session_state['primary_island'] = (
                                    pre_draft_guidance['primary_island']
                                )
                            if pre_draft_guidance.get('relationship_stage'):
                                updated_session_state['relationship_stage'] = (
                                    pre_draft_guidance['relationship_stage']
                                )
                            result['metadata']['persona_graph'] = {
                                'used': True,
                                'primary_island': pre_draft_guidance.get('primary_island'),
                                'relationship_stage': pre_draft_guidance.get(
                                    'relationship_stage'
                                ),
                                'intensity': pre_draft_guidance.get('intensity'),
                                'graph_version': pre_draft_guidance.get('graph_version'),
                                'prompt_chars': len(personality_system_prompt),
                                'soul_memory_id': pre_draft_guidance.get('soul_memory_id'),
                                'soul_memory_source': pre_draft_guidance.get(
                                    'soul_memory_source'
                                ),
                                'orchestrator_hints': pre_draft_guidance.get(
                                    'orchestrator_hints'
                                ) or orchestrator_hints,
                            }
                            result['metadata']['system_prompt_pre_draft'] = True
                            result['metadata']['prompt_contract'] = (
                                pre_draft_guidance.get('prompt_contract')
                                or 'pre_draft_full_no_truncation'
                            )
                    except Exception as pre_exc:
                        self.logger.warning({
                            "event": "pre_draft_guidance_failed",
                            "session_id": session_id,
                            "error": str(pre_exc),
                        })
                        pre_draft_guidance = None
                        personality_system_prompt = ""

                # ========== 4.5 LLM 初稿生成（Navigator 未產出時） ==========
                if self._is_response_too_short(final_response):
                    draft_response = await self._generate_draft_response(
                        user_text=user_text,
                        session_state=updated_session_state,
                        emotions_vsc=emotions_vsc,
                        language_hint=language_hint,
                        weather_context=weather_context,
                        memory_context=memory_context,
                        sensing_bundle=sensing_bundle,
                        result=result,
                        personality_system_prompt=personality_system_prompt,
                    )
                    if draft_response:
                        final_response = draft_response
                        result['metadata']['llm_draft_used'] = True
                        if personality_system_prompt:
                            result['metadata']['seele_system_prompt_used_in_draft'] = True

                # ========== 5. 委派 PersonalityModule.anchor() ==========
                if self.personality:
                    try:
                        # Drift / echo policy 必須用「草稿回應」向量，不可重用用戶查詢向量。
                        response_embedding = embedding
                        if final_response:
                            try:
                                draft_embedding = await self._get_embedding(final_response)
                                if draft_embedding:
                                    response_embedding = draft_embedding
                            except Exception as emb_exc:
                                self.logger.warning({
                                    "event": "response_embedding_fallback",
                                    "session_id": session_id,
                                    "error": str(emb_exc),
                                })

                        turn_info: Dict[str, Any] = {
                            'embedding': embedding,
                            'response_embedding': response_embedding,
                            'emotion_urgency': 5 if emotions_vsc.get('arousal', 0.0) > 0.8 else 1,
                            'is_crisis': emotions_vsc.get('arousal', 0.0) > 0.8,
                            'user_sentiment': emotions_vsc,
                            'weather_context': weather_context,
                            'language_hint': language_hint,
                            'turn_count': updated_session_state.get('turn_count', 0),
                            'triggered_fractures': triggered_fractures,
                            'navigator_decision': nav_log,
                            'environment': self.environment,
                            'risk_level': session_risk,
                            'retrieved_memories': retrieved_memories,
                            'memory_context': memory_context,
                            'pre_draft_guidance': pre_draft_guidance or {},
                            'personality_system_prompt': personality_system_prompt,
                            'orchestrator_hints': orchestrator_hints,
                            'skip_echo_consolidation': bool(
                                orchestrator_hints.get('skip_echo_consolidation')
                            ),
                            'soul_guidance': (
                                (result.get('metadata') or {})
                                .get('star_orchestration', {})
                                .get('soul_guidance')
                            ),
                        }
                        turn_info.update(kwargs)

                        # 傳入 updated_session_state，使 drift/intimacy/history 寫入可被後續持久化。
                        if asyncio.iscoroutinefunction(self.personality.anchor):
                            anchor_result = await asyncio.wait_for(
                                self.personality.anchor(
                                    draft_response=final_response,
                                    user_input=user_text,
                                    session_state=updated_session_state,
                                    turn_info=turn_info
                                ),
                                timeout=PerformanceConfig.PERSONALITY_ANCHOR_TIMEOUT
                            )
                        else:
                            anchor_result = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    self.personality.anchor,
                                    final_response,
                                    user_text,
                                    updated_session_state,
                                    turn_info
                                ),
                                timeout=PerformanceConfig.PERSONALITY_ANCHOR_TIMEOUT
                            )

                        response_text = ""
                        # 現行契約：anchor() -> (final_response, session_state)
                        if isinstance(anchor_result, tuple) and len(anchor_result) >= 2:
                            response_text = anchor_result[0] if isinstance(anchor_result[0], str) else ""
                            state_out = anchor_result[1]
                            if isinstance(state_out, dict):
                                updated_session_state = state_out
                        elif isinstance(anchor_result, dict):
                            response_text = (
                                anchor_result.get('response')
                                or anchor_result.get('text')
                                or anchor_result.get('final_response')
                                or ""
                            )
                            state_out = anchor_result.get('session_state')
                            if isinstance(state_out, dict):
                                updated_session_state = state_out
                        elif isinstance(anchor_result, str):
                            response_text = anchor_result

                        if response_text and not self._is_response_too_short(response_text):
                            final_response = response_text
                            self.logger.info({
                                "event": "personality_anchor_success",
                                "session_id": session_id,
                                "response_length": len(final_response),
                                "status": "success"
                            })

                        result['metadata']['personality_used'] = (
                            bool(response_text)
                            and not self._is_response_too_short(response_text)
                        )

                    except asyncio.TimeoutError:
                        self.logger.error({
                            "event": "personality_anchor_timeout",
                            "session_id": session_id,
                            "timeout": PerformanceConfig.PERSONALITY_ANCHOR_TIMEOUT
                        })
                    except Exception as e:
                        self.logger.error({
                            "event": "personality_anchor_failed",
                            "session_id": session_id,
                            "error": str(e)
                        })

            # ========== 6. 最終品質閘門（Zero-Truncation） ==========
            final_response = self._finalize_turn_outcome(
                result,
                final_response,
                session_id,
                fallback_reason='empty_or_short_response',
            )
            result['text'] = final_response

            # ========== 7. 更新結果 ==========
            result['phase'] = updated_session_state.get('phase', ConversationPhase.EXPLORATION.value)
            result['risk_level'] = max(
                int(updated_session_state.get('risk_level', 0) or 0),
                int(result.get('risk_level', 0) or 0),
            )
            updated_session_state['risk_level'] = result['risk_level']

            turn_status = 'success' if result['success'] else 'failed'
            response_quality = result['metadata'].get('response_quality', 'unknown')

            # ========== 8. 性能度量 ==========
            process_duration = (datetime.now() - process_start).total_seconds()
            result['metadata']['processing_time_sec'] = round(process_duration, 3)
            self._record_chat_processing_latency(process_duration, result['risk_level'])
            
            self.perf_logger.info({
                "event": "turn_completed",
                "session_id": session_id,
                "user_id": user_id,
                "duration_ms": round(process_duration * 1000, 1),
                "response_length": len(final_response),
                "cache_hits": result['metadata']['cache_hits'],
                "phase": result['phase'],
                "risk_level": result['risk_level'],
                "response_quality": response_quality,
                "navigator_used": result['metadata']['navigator_used'],
                "personality_used": result['metadata']['personality_used'],
                "star_orchestration_used": result['metadata'].get('star_orchestration_used', False),
                "star_pipeline": (
                    (result['metadata'].get('star_orchestration') or {}).get('pipeline_stages')
                ),
                "environment": self.environment,
                "status": turn_status,
            })

            self.logger.info({
                "event": "process_user_message_complete",
                "session_id": session_id,
                "user_id": user_id,
                "phase": result['phase'],
                "risk_level": result['risk_level'],
                "duration_sec": round(process_duration, 3),
                "response_length": len(final_response),
                "response_quality": response_quality,
                "environment": self.environment,
                "status": turn_status,
            })

            # ========== 9. 背景執行 DB 寫入 (Fire and Forget) ==========
            from app.utils.meta_audit_gate import build_turn_meta_layer

            turn_meta_layer = (result.get('metadata') or {}).get('meta_layer')
            if not turn_meta_layer:
                turn_meta_layer = build_turn_meta_layer(
                    audit_ran=False,
                    audit_reason='non_v9_pipeline',
                )
            result['metadata']['meta_layer'] = turn_meta_layer

            persist_meta = True
            try:
                from app.config import config as _cfg
                persist_meta = getattr(_cfg, 'META_LAYER_PERSIST', True)
            except Exception:
                pass
            if not persist_meta:
                turn_meta_layer = None

            try:
                db_write_task = asyncio.create_task(
                    self._background_db_write(
                        session_id=session_id,
                        user_id=user_id,
                        user_text=user_text,
                        final_response=final_response,
                        emotions_vsc=emotions_vsc,
                        embedding=embedding,
                        risk_level=result['risk_level'],
                        language_hint=language_hint,
                        nav_log=nav_log,
                        meta_layer=turn_meta_layer,
                    )
                )
                self._background_tasks.add(db_write_task)
                db_write_task.add_done_callback(self._background_tasks.discard)

                memory_persist_task = asyncio.create_task(
                    self._background_memory_persist(
                        session_id=session_id,
                        user_id=user_id,
                        user_text=user_text,
                        final_response=final_response,
                        user_embedding=embedding,
                        emotions_vsc=emotions_vsc,
                        session_state=updated_session_state,
                        risk_level=int(result.get('risk_level', 0) or 0),
                        skip_persist=critical_fast_track,
                    )
                )
                self._background_tasks.add(memory_persist_task)
                memory_persist_task.add_done_callback(self._background_tasks.discard)

                star_meta = (result.get('metadata') or {}).get('star_orchestration') or {}
                evolved_shadow = star_meta.get('user_shadow')
                cognitive_task = asyncio.create_task(
                    self._background_cognitive_persist(
                        session_id=session_id,
                        user_id=user_id,
                        user_text=user_text,
                        emotions_vsc=emotions_vsc,
                        session_state=updated_session_state,
                        risk_level=int(result.get('risk_level', 0) or 0),
                        meta_layer=turn_meta_layer,
                        evolved_shadow=evolved_shadow,
                    )
                )
                self._background_tasks.add(cognitive_task)
                cognitive_task.add_done_callback(self._background_tasks.discard)

                if self.kag_reality and self.kag_reality.enabled:
                    kag_task = asyncio.create_task(
                        self._background_kag_persist(
                            session_id=session_id,
                            user_id=user_id,
                            user_text=user_text,
                        )
                    )
                    self._background_tasks.add(kag_task)
                    kag_task.add_done_callback(self._background_tasks.discard)
            except Exception as e:
                self.logger.error({
                    "event": "background_task_creation_failed",
                    "session_id": session_id,
                    "error": str(e)
                })

            return result

        except Exception as e:
            process_duration = (datetime.now() - process_start).total_seconds()
            
            self.logger.error({
                "event": "process_user_message_exception",
                "session_id": session_id,
                "user_id": user_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "duration_sec": round(process_duration, 3),
                "environment": self.environment,
                "status": "error"
            })
            
            result['text'] = self._finalize_turn_outcome(
                result,
                self._get_safe_reply('fallback'),
                session_id,
                fallback_reason='exception_handler',
            )
            result['success'] = False
            result['metadata']['response_quality'] = 'error'
            result['phase'] = ConversationPhase.ERROR.value
            result['warnings'].append(str(e))
            result['metadata']['processing_time_sec'] = round(process_duration, 3)
            self._record_chat_processing_latency(
                process_duration,
                int(result.get('risk_level', 0) or 0),
            )
            
            return result

    # ==================== 生命週期管理 ====================

    async def wait_for_background_tasks(self, timeout: float = 5.0) -> None:
        """等待所有背景任務完成"""
        if not self._background_tasks:
            return
        
        try:
            self.logger.info({
                "event": "waiting_for_background_tasks",
                "count": len(self._background_tasks),
                "timeout": timeout
            })
            
            await asyncio.wait_for(
                asyncio.gather(*self._background_tasks, return_exceptions=True),
                timeout=timeout
            )
            
            self.logger.info({
                "event": "background_tasks_completed",
                "count": len(self._background_tasks)
            })
        except asyncio.TimeoutError:
            self.logger.warning({
                "event": "background_tasks_timeout",
                "timeout": timeout,
                "remaining_tasks": len(self._background_tasks)
            })
        except Exception as e:
            self.logger.error({
                "event": "wait_for_background_tasks_failed",
                "error": str(e)
            })

    def shutdown(self) -> None:
        """優雅關閉資源"""
        try:
            self.logger.info({
                "event": "orchestrator_shutdown_start",
                "background_tasks": len(self._background_tasks),
                "environment": self.environment,
                "status": "in_progress"
            })
            
            self._session_cache.clear()
            self._embedding_cache.clear()
            self._emotion_cache.clear()
            
            if self.fallback_cache:
                self.fallback_cache.clear()
            
            self.logger.info({
                "event": "cache_cleared",
                "status": "success"
            })
            
            if self.redis_manager:
                try:
                    self.redis_manager.close()
                    self.logger.info({
                        "event": "redis_manager_closed",
                        "status": "success"
                    })
                except Exception as e:
                    self.logger.warning({
                        "event": "redis_manager_close_failed",
                        "error": str(e)
                    })
            
            if self.personality and hasattr(self.personality, 'shutdown'):
                try:
                    self.personality.shutdown()
                    self.logger.info({
                        "event": "personality_module_shutdown",
                        "status": "success"
                    })
                except Exception as e:
                    self.logger.warning({
                        "event": "personality_shutdown_failed",
                        "error": str(e)
                    })
            
            if self.gsw_engine and hasattr(self.gsw_engine, 'shutdown'):
                try:
                    self.gsw_engine.shutdown()
                    self.logger.info({
                        "event": "gsw_engine_shutdown",
                        "status": "success"
                    })
                except Exception as e:
                    self.logger.warning({
                        "event": "gsw_engine_shutdown_failed",
                        "error": str(e)
                    })
            
            if self.navigator and hasattr(self.navigator, 'close'):
                try:
                    self.navigator.close()
                    self.logger.info({
                        "event": "navigator_shutdown",
                        "status": "success"
                    })
                except Exception as e:
                    self.logger.warning({
                        "event": "navigator_shutdown_failed",
                        "error": str(e)
                    })
            
            self.logger.info({
                "event": "orchestrator_shutdown_complete",
                "environment": self.environment,
                "status": "success"
            })
            
        except Exception as e:
            self.logger.error({
                "event": "orchestrator_shutdown_failed",
                "error": str(e),
                "environment": self.environment,
                "status": "error"
            })


# ==================== 全局單例管理 ====================

_orchestrator_instance: Optional[Orchestrator] = None


def get_orchestrator(redis_config: Optional[Dict[str, Any]] = None) -> Orchestrator:
    """取得全局 Orchestrator 實例"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = Orchestrator(redis_config=redis_config)
    return _orchestrator_instance


def shutdown_orchestrator() -> None:
    """優雅關閉全局 Orchestrator"""
    global _orchestrator_instance
    if _orchestrator_instance:
        _orchestrator_instance.shutdown()
        _orchestrator_instance = None