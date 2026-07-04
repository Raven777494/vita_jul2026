# app/main.py - v3.8 完全修復版 (異步事件驅動 + Worker 集成)
"""
Vita 2.0 - FastAPI 應用主入口
完整初始化順序 + 依賴注入 + 非同步支持 + Redis Queue Worker
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
import logging
import time
import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from enum import Enum
import math

from app.config import config, CURRENT_ENV, IS_PRODUCTION, IS_DEVELOPMENT
from app.api import routes
from app.schemas import ChatRequest, ChatResponse, ChatMeta, LangCode
from app.startup_checks import run_startup_checks
from app.middleware.request_logger import log_requests_middleware
from app.middleware.rate_limiter import rate_limit_middleware, rate_limiter
from app.utils.language_switcher import LanguageSwitcher
from app.utils.llm_health import probe_llm_service
from app.engines import collect_three_engine_health
from hardware_profile_loader import get_profile_summary, get_llm_compute_health
from app.logger import get_crisis_logger
from sqlalchemy import text

import redis
import redis.asyncio as aioredis

logger = logging.getLogger("vita.main")
crisis_logger = get_crisis_logger()

# ==================== 初始化第 1 層：基礎配置驗證 ====================

logger.info("[INIT_L1] 啟動基礎配置驗證...")

startup_result = run_startup_checks()
if not startup_result:
    if IS_PRODUCTION:
        logger.critical("[INIT_L1] 啟動檢查失敗（生產環境）。系統停止。")
        sys.exit(1)
    else:
        logger.warning("[INIT_L1] 啟動檢查失敗。開發模式繼續運行。")

logger.info("[INIT_L1] 基礎配置驗證完成 [OK]")

# ==================== 初始化第 2 層：數據庫與快取層 ====================

logger.info("[INIT_L2] 初始化數據庫與快取層...")

# 2.1 同步資料庫初始化
try:
    from app.services.db_manager import db_manager, async_db_manager, SessionLocal
    
    test_session = db_manager.get_session()
    test_session.execute(text("SELECT 1"))
    test_session.close()
    
    logger.info("[INIT_L2] 同步數據庫已初始化 [OK]")
except Exception as e:
    logger.critical(f"[INIT_L2] 同步數據庫初始化失敗: {e}")
    if IS_PRODUCTION:
        sys.exit(1)

# 2.2 非同步資料庫初始化（驗證配置，不實際連接）
try:
    logger.info("[INIT_L2] 非同步數據庫層可用")
except Exception as e:
    logger.warning(f"[INIT_L2] 非同步數據庫設置警告: {e}")

# 2.3 Redis 快取層初始化
redis_client = None
redis_url = None
try:
    from app.dependencies import _parse_redis_url
    
    redis_url = config.REDIS_URL
    redis_config = _parse_redis_url(redis_url)
    redis_client = redis.Redis(**redis_config)
    redis_client.ping()
    logger.info("[INIT_L2] Redis 快取已連接 [OK]")
except redis.ConnectionError as e:
    logger.warning(f"[INIT_L2] Redis 不可用（非關鍵）: {e}")
    redis_client = None
except Exception as e:
    logger.warning(f"[INIT_L2] Redis 設置警告: {e}")
    redis_client = None

logger.info("[INIT_L2] 數據庫與快取層初始化完成 [OK]")

# ==================== 初始化第 3 層：AI 服務層 ====================

logger.info("[INIT_L3] 初始化 AI 服務層...")

# 3.1 情感分析服務
try:
    from app.services.emotion_service import EmotionService
    emotion_service = EmotionService()
    logger.info("[INIT_L3] 情感分析服務已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L3] 情感分析服務失敗: {e}")
    emotion_service = None

# 3.2 向量服務
try:
    from app.services.vector_service import VectorService
    vector_service = VectorService()
    logger.info("[INIT_L3] 向量服務已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L3] 向量服務失敗: {e}")
    vector_service = None

# 3.3 LLM 服務
try:
    from app.services.llm_service import llm_service
    logger.info("[INIT_L3] LLM 服務已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L3] LLM 服務失敗: {e}")
    if IS_PRODUCTION:
        sys.exit(1)

# 3.4 天氣服務（可選）
try:
    from app.services.hko_service import HKOService
    hko_service = HKOService()
    logger.info("[INIT_L3] 天氣服務已初始化 [OK]")
except Exception as e:
    logger.warning(f"[INIT_L3] 天氣服務不可用（非關鍵）: {e}")
    hko_service = None

logger.info("[INIT_L3] AI 服務層初始化完成 [OK]")

# ==================== 初始化第 4 層：Fracture Map 與心理引擎 ====================

logger.info("[INIT_L4] 初始化 Fracture Map 與心理引擎...")

# 4.1 Fracture Map 資料庫管理器
try:
    from app.services.fracture_map.db_fm_manager import DBFMManager
    db_fm_manager = DBFMManager()
    logger.info("[INIT_L4] DBFMManager 已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L4] DBFMManager 初始化失敗: {e}")
    if IS_PRODUCTION:
        sys.exit(1)
    db_fm_manager = None

# 4.2 Fracture Map 管理器（快取層）
try:
    from app.services.fracture_map.fracture_map_manager import FractureMapManager
    fm_manager = FractureMapManager(
        redis_client=redis_client,
        db_manager=db_fm_manager,
        cache_ttl_minutes=5
    )
    logger.info("[INIT_L4] FractureMapManager 已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L4] FractureMapManager 初始化失敗: {e}")
    fm_manager = None

# 4.3 GSW 永恆迴響引擎
try:
    from PersonalityModule.gsw_engine import GSWEngine
    
    config_dict = {}
    if hasattr(config, 'to_dict') and callable(config.to_dict):
        try:
            config_dict = config.to_dict()
        except Exception as cfg_e:
            logger.warning(f"[INIT_L4] config.to_dict() 失敗: {cfg_e}")
            config_dict = {}
    
    gsw_engine = GSWEngine(
        config=config_dict,
        vector_service=vector_service,
        db_manager=db_manager,
    )
    logger.info("[INIT_L4] GSWEngine 已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L4] GSWEngine 初始化失敗: {e}")
    gsw_engine = None

# 4.4 Intelligent Navigator（雙軌決策系統）
try:
    from app.services.fracture_map.intelligent_navigator import IntelligentNavigator
    
    config_dict = {}
    if hasattr(config, 'to_dict') and callable(config.to_dict):
        try:
            config_dict = config.to_dict()
        except Exception as cfg_e:
            logger.warning(f"[INIT_L4] config.to_dict() 失敗: {cfg_e}")
            config_dict = {}
    
    navigator = IntelligentNavigator(
        llm_service=llm_service,
        db_manager=db_manager,
        db_service=None,
        fracture_manager=db_fm_manager,
        config=config_dict
    )
    logger.info("[INIT_L4] IntelligentNavigator 已初始化 [OK]")
except Exception as e:
    logger.error(f"[INIT_L4] IntelligentNavigator 初始化失敗: {e}")
    navigator = None

logger.info("[INIT_L4] Fracture Map 與心理引擎層初始化完成 [OK]")

# ==================== 初始化第 5 層：Orchestrator ====================

logger.info("[INIT_L5] 初始化 Orchestrator...")

orchestrator = None
try:
    from app.orchestrator import Orchestrator
    
    redis_config_dict = None
    if redis_client:
        try:
            from app.dependencies import _parse_redis_url
            parsed_config = _parse_redis_url(redis_url) if redis_url else {}
            redis_config_dict = {
                'host': parsed_config.get('host', 'localhost'),
                'port': parsed_config.get('port', 6379),
                'db': parsed_config.get('db', 0),
                'decode_responses': True,
            }
        except Exception as cfg_e:
            logger.warning(f"[INIT_L5] Redis 配置解析失敗: {cfg_e}")
            redis_config_dict = None
    
    # [FIX-ALIGN] 將 L3/L4 已建立的服務注入 Orchestrator，避免重複初始化
    # （EmotionService / VectorService / HKOService / DBFMManager /
    #  FractureMapManager / GSWEngine / IntelligentNavigator）。
    shared_services = {
        'db_manager': db_manager,
        'emotion_service': emotion_service,
        'vector_service': vector_service,
        'hko_service': hko_service,
        'db_fm_manager': db_fm_manager,
        'fracture_map_manager': fm_manager,
        'gsw_engine': gsw_engine,
        'intelligent_navigator': navigator,
    }
    orchestrator = Orchestrator(
        redis_config=redis_config_dict,
        shared_services=shared_services
    )
    logger.info("[INIT_L5] Orchestrator 已初始化（共享服務注入）[OK]")
except Exception as e:
    logger.critical(f"[INIT_L5] Orchestrator 初始化失敗: {e}")
    if IS_PRODUCTION:
        sys.exit(1)
    orchestrator = None

logger.info("[INIT_L5] Orchestrator 層初始化完成 [OK]")

# ==================== 初始化第 6 層：Personality Module ====================

logger.info("[INIT_L6] 初始化 Personality Module...")

# [FIX-ALIGN] 不再重複建立 PersonalityModule。Orchestrator 已使用上述共享服務於內部
# 建立並完成依賴注入（單一真實來源）。此處直接引用該實例，供健康檢查與生命週期關閉使用，
# 避免兩套人格大腦各自初始化（重複載入模型、狀態可能發散）。
personality_module = orchestrator.personality if orchestrator is not None else None

if personality_module is not None:
    logger.info("[INIT_L6] Personality Module 已就緒（來自 Orchestrator 共享實例）[OK]")
else:
    logger.critical("[INIT_L6] Personality Module 不可用（Orchestrator 未提供）")
    if IS_PRODUCTION:
        sys.exit(1)

logger.info("[INIT_L6] Personality Module 層初始化完成 [OK]")

# ==================== 初始化第 7 層：FastAPI 應用 ====================

logger.info("[INIT_L7] 初始化 FastAPI 應用...")


class ResponsePhase(str, Enum):
    """對話階段列舉"""
    GREETING = "greeting"
    EXPLORATION = "exploration"
    DEEP_ENGAGEMENT = "deep_engagement"
    CRISIS = "crisis"
    RESOLUTION = "resolution"
    CLOSURE = "closure"
    DREAM_WEAVING = "dream_weaving"
    UNKNOWN = "unknown"
    ERROR = "error"


class VADVectorValidator:
    """VAD 向量驗證器"""
    VALENCE_MIN, VALENCE_MAX = -1.0, 1.0
    AROUSAL_MIN, AROUSAL_MAX = 0.0, 1.0
    DOMINANCE_MIN, DOMINANCE_MAX = -1.0, 1.0
    DECIMAL_PLACES = 3
    
    @staticmethod
    def validate_and_normalize(emotions: Any) -> Dict[str, float]:
        """驗證並規範化情緒 VAD 向量"""
        if not isinstance(emotions, dict):
            return {'valence': 0.0, 'arousal': 0.0, 'dominance': 0.0}
        
        vad_dict = {}
        specs = {
            'valence': (VADVectorValidator.VALENCE_MIN, VADVectorValidator.VALENCE_MAX),
            'arousal': (VADVectorValidator.AROUSAL_MIN, VADVectorValidator.AROUSAL_MAX),
            'dominance': (VADVectorValidator.DOMINANCE_MIN, VADVectorValidator.DOMINANCE_MAX),
        }
        
        for key, (min_bound, max_bound) in specs.items():
            value = emotions.get(key)
            
            try:
                float_val = float(value) if value is not None else 0.0
                if math.isnan(float_val) or math.isinf(float_val):
                    float_val = 0.0
            except (TypeError, ValueError):
                float_val = 0.0
            
            clamped = max(min_bound, min(max_bound, float_val))
            vad_dict[key] = round(clamped, VADVectorValidator.DECIMAL_PLACES)
        
        return vad_dict


# ==================== Worker 統計函數 ====================

def get_processor_stats() -> Dict[str, Any]:
    """獲取 Queue Processor 統計信息"""
    try:
        from app.workers.twitch_worker import _processor_instance
        
        if _processor_instance is None:
            return {
                'status': 'not_initialized',
                'messages_processed': 0,
                'uptime_sec': 0,
            }
        
        return {
            'status': 'running' if _processor_instance._is_running else 'stopped',
            'messages_processed': _processor_instance._processed_count,
            'messages_failed': _processor_instance._error_count,
            'messages_skipped': _processor_instance._skipped_count,
            'redis_errors': _processor_instance._redis_error_count,
            'queue_depth': _processor_instance.message_queue.qsize() 
                if _processor_instance.message_queue else 0,
            'uptime_sec': (datetime.now(timezone.utc) - _processor_instance._start_time).total_seconds()
                if hasattr(_processor_instance, '_start_time') else 0,
        }
    except Exception as e:
        logger.debug(f"[STATS] Worker 統計查詢失敗: {e}")
        return {
            'status': 'error',
            'error': str(e),
        }


# ==================== 生命週期管理器 ====================

class LifecycleManager:
    """應用生命週期管理"""
    _orchestrator_ready = False
    _shutdown_timeout = 30
    _worker_task: Optional[asyncio.Task] = None
    _queue_processor_enabled = False
    
    @classmethod
    def _is_worker_enabled(cls) -> bool:
        """檢查 Worker 是否應啟用"""
        queue_processor_enabled = os.getenv(
            "QUEUE_PROCESSOR_ENABLED",
            "false"
        ).lower() == "true"
        
        logger.debug(
            f"[LIFECYCLE] QUEUE_PROCESSOR_ENABLED={queue_processor_enabled}"
        )
        
        return queue_processor_enabled
    
    @classmethod
    async def startup(cls) -> bool:
        """啟動流程"""
        logger.info("[LIFECYCLE] Vita 2.0 startup sequence initiated...")
        logger.info("=" * 80)
        logger.info(f"Environment: {CURRENT_ENV}")
        logger.info(f"Debug Mode: {config.DEBUG}")
        logger.info("=" * 80)
        
        try:
            # 驗證核心組件
            if orchestrator is None:
                logger.error("[LIFECYCLE] Orchestrator not initialized")
                if IS_PRODUCTION:
                    return False
            
            if personality_module is None:
                logger.error("[LIFECYCLE] Personality Module not initialized")
                if IS_PRODUCTION:
                    return False
            
            cls._orchestrator_ready = orchestrator is not None
            logger.info("[LIFECYCLE] All critical services verified [OK]")
            
            # 初始化 Redis Queue Worker
            cls._queue_processor_enabled = cls._is_worker_enabled()
            
            if cls._queue_processor_enabled:
                try:
                    from app.workers.twitch_worker import (
                        initialize_queue_processor,
                        _processor_instance
                    )
                    
                    logger.info(
                        "[LIFECYCLE] Initializing Twitch Queue Worker "
                        "(Rate: 20 msg/s)..."
                    )
                    
                    await initialize_queue_processor(
                        redis_url=config.REDIS_URL,
                        process_rate=20,
                        max_concurrent_tasks=100,
                        orchestrator=orchestrator
                    )
                    
                    if _processor_instance:
                        cls._worker_task = asyncio.create_task(
                            _processor_instance.run()
                        )
                        logger.info(
                            "[LIFECYCLE] Twitch Queue Worker successfully "
                            "mounted to event loop [OK]"
                        )
                    else:
                        logger.warning(
                            "[LIFECYCLE] Queue Processor initialization "
                            "returned None"
                        )
                
                except ImportError as e:
                    logger.error(
                        f"[LIFECYCLE] Failed to import Worker module: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"[LIFECYCLE] Worker initialization failed: {e}"
                    )
            else:
                logger.info("[LIFECYCLE] Queue Processor disabled by environment")
            
            return True
            
        except Exception as e:
            logger.critical(f"[LIFECYCLE] Startup failed: {e}")
            return False
    
    @classmethod
    async def shutdown(cls) -> bool:
        """關閉流程"""
        logger.info("[LIFECYCLE] Vita 2.0 shutdown sequence initiated...")
        logger.info("=" * 80)
        
        try:
            # 優雅關閉 Queue Worker
            if cls._worker_task and cls._queue_processor_enabled:
                try:
                    from app.workers.twitch_worker import (
                        shutdown_queue_processor,
                        _processor_instance
                    )
                    
                    logger.info("[LIFECYCLE] Shutting down Twitch Queue Worker...")
                    
                    await shutdown_queue_processor()
                    
                    cls._worker_task.cancel()
                    
                    try:
                        await asyncio.wait_for(
                            cls._worker_task,
                            timeout=cls._shutdown_timeout
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[LIFECYCLE] Worker task shutdown timeout exceeded"
                        )
                    except asyncio.CancelledError:
                        pass
                    
                    logger.info(
                        "[LIFECYCLE] Twitch Queue Worker task terminated "
                        "safely [OK]"
                    )
                
                except Exception as e:
                    logger.error(
                        f"[LIFECYCLE] Worker shutdown error: {e}"
                    )
            
            # 關閉 Orchestrator
            if orchestrator:
                try:
                    if hasattr(orchestrator, 'wait_for_background_tasks'):
                        await orchestrator.wait_for_background_tasks(timeout=5.0)
                    if hasattr(orchestrator, 'shutdown'):
                        orchestrator.shutdown()
                    logger.info("[LIFECYCLE] Orchestrator shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] Orchestrator shutdown warning: {e}")
            
            # 關閉 Personality Module
            if personality_module and hasattr(personality_module, 'shutdown'):
                try:
                    personality_module.shutdown()
                    logger.info("[LIFECYCLE] Personality Module shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] Personality Module shutdown warning: {e}")
            
            # 關閉 GSW Engine
            if gsw_engine and hasattr(gsw_engine, 'shutdown'):
                try:
                    gsw_engine.shutdown()
                    logger.info("[LIFECYCLE] GSW Engine shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] GSW Engine shutdown warning: {e}")
            
            # 關閉 Fracture Map Manager
            if fm_manager and hasattr(fm_manager, 'close'):
                try:
                    fm_manager.close()
                    logger.info("[LIFECYCLE] Fracture Map Manager shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] Fracture Map Manager shutdown warning: {e}")
            
            # 關閉 Rate Limiter Redis
            if hasattr(rate_limiter, 'redis_client') and rate_limiter.redis_client:
                try:
                    rate_limiter.redis_client.close()
                    logger.info("[LIFECYCLE] Rate limiter Redis shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] Rate limiter shutdown warning: {e}")
            
            # 關閉主 Redis
            if redis_client:
                try:
                    redis_client.close()
                    logger.info("[LIFECYCLE] Main Redis shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] Main Redis shutdown warning: {e}")
            
            # 關閉資料庫
            if db_manager:
                try:
                    db_manager.close()
                    logger.info("[LIFECYCLE] Database connection shut down [OK]")
                except Exception as e:
                    logger.warning(f"[LIFECYCLE] Database shutdown warning: {e}")
            
            logger.info("=" * 80)
            logger.info("[LIFECYCLE] Application shutdown complete [OK]")
            logger.info("=" * 80)
            return True
            
        except Exception as e:
            logger.error(f"[LIFECYCLE] Shutdown error: {e}", exc_info=True)
            return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期上下文"""
    startup_success = await LifecycleManager.startup()
    
    if not startup_success and IS_PRODUCTION:
        logger.critical("[LIFESPAN] Production environment startup failed")
        sys.exit(1)
    
    yield
    
    await LifecycleManager.shutdown()


# FastAPI 應用實例
app_instance = FastAPI(
    title="Vita 2.0",
    description="香港 AI 伴侶系統（臨床級）",
    version="2.0.0",
    docs_url="/docs" if IS_DEVELOPMENT else None,
    redoc_url="/redoc" if IS_DEVELOPMENT else None,
    lifespan=lifespan
)

logger.info("[INIT_L7] FastAPI 應用實例已建立 [OK]")

# ==================== 初始化第 8 層：中間件配置 ====================

logger.info("[INIT_L8] 配置中間件堆棧...")

app_instance.middleware("http")(log_requests_middleware)

# CORS 配置
if IS_PRODUCTION:
    cors_origins = config.CORS_ORIGINS
    logger.warning(f"[INIT_L8] Production CORS origins: {len(cors_origins)}")
else:
    cors_origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8080",
    ]

app_instance.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)

app_instance.middleware("http")(rate_limit_middleware)

logger.info("[INIT_L8] Middleware stack configured [OK]")

# ==================== 初始化第 9 層：靜態文件 & 路由 ====================

logger.info("[INIT_L9] 掛載靜態文件與路由...")

public_dir = Path("public")
try:
    public_dir.mkdir(parents=True, exist_ok=True)
    app_instance.mount("/public", StaticFiles(directory=str(public_dir)), name="public")
    logger.info("[INIT_L9] Static files mounted [OK]")
except Exception as e:
    logger.warning(f"[INIT_L9] Static files mount warning: {e}")

# 包含 API 路由
try:
    app_instance.include_router(routes.router, prefix="/api/v1", tags=["chat"])
    logger.info("[INIT_L9] API routes included [OK]")
except Exception as e:
    logger.error(f"[INIT_L9] API routes inclusion failed: {e}")
    if IS_PRODUCTION:
        sys.exit(1)

logger.info("[INIT_L9] Static files and routes initialization complete [OK]")

# ==================== 依賴注入函數 ====================

async def get_language_switcher(
    redis_client_dep: Optional[redis.Redis] = Depends(lambda: redis_client)
) -> LanguageSwitcher:
    """依賴注入：語言切換器"""
    try:
        return LanguageSwitcher(redis_client=redis_client_dep)
    except Exception as e:
        logger.error(f"[LANG] LanguageSwitcher initialization failed: {e}")
        return LanguageSwitcher(redis_client=None)


# ==================== 根路由 ====================

@app_instance.get("/", tags=["root"])
async def root():
    """根路由"""
    html_file = public_dir / "chat.html"
    if html_file.exists():
        try:
            return FileResponse(html_file, media_type="text/html")
        except Exception as e:
            logger.error(f"[ROOT] HTML service failed: {e}")
    
    return JSONResponse({
        "message": "Vita 2.0 System",
        "version": "2.0.0",
        "environment": CURRENT_ENV,
        "status": "online",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def _logic_engine_components() -> Dict[str, bool]:
    """Component map for Logic Engine health (runtime state from app.main)."""
    return {
        "orchestrator": LifecycleManager._orchestrator_ready,
        "personality_module": personality_module is not None,
        "gsw_engine": gsw_engine is not None,
        "navigator": navigator is not None,
        "fracture_map": fm_manager is not None,
        "emotion_service": emotion_service is not None,
        "vector_service": vector_service is not None,
    }


@app_instance.get("/health/engines", tags=["health"])
async def engines_health():
    """Three-engine architecture health: Platform / Compute / Logic."""
    payload = await collect_three_engine_health(
        redis_client=redis_client,
        orchestrator_ready=LifecycleManager._orchestrator_ready,
        logic_components=_logic_engine_components(),
        meta_controller_enabled=getattr(config, "SEELE_META_CONTROLLER_ENABLED", False),
    )
    status_code = 200 if payload["overall_state"] != "down" else 503
    return JSONResponse(payload, status_code=status_code)


@app_instance.get("/health", tags=["health"])
async def health_check():
    """健康檢查端點"""
    redis_status = "unavailable"
    if redis_client:
        try:
            redis_client.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "error"
    
    worker_stats = get_processor_stats()
    
    # [FIX-ALIGN] 實際查詢資料庫健康狀態，取代寫死的 "online"
    db_status = "error"
    try:
        from app.services.db_manager import db_manager as _dbm
        db_hc = _dbm.health_check()
        db_status = "online" if db_hc.get("status") == "healthy" else "error"
    except Exception as e:
        logger.debug(f"[HEALTH] Database health check failed: {e}")
        db_status = "error"
    
    # LLM 探針（8081 Soul / 8084 Memory / 8085 Emobloom）
    main_ok, main_detail = probe_llm_service(
        config.MAIN_LLM_URL,
        timeout=3.0,
    )
    memory_ok, memory_detail = probe_llm_service(
        config.MEMORY_LLM_URL,
        timeout=3.0,
    )
    emobloom_ok, emobloom_detail = probe_llm_service(
        config.EMOBLOOM_LLM_URL,
        timeout=3.0,
    )

    llm_status = "online" if memory_ok and emobloom_ok else "degraded"
    generative_status = "online" if main_ok else "degraded"
    overall_status = "online"
    if db_status != "online" or not memory_ok or not emobloom_ok:
        overall_status = "degraded"
    if not main_ok:
        overall_status = "degraded"

    meta_controller_block: Dict[str, Any] = {
        "enabled": getattr(config, "SEELE_META_CONTROLLER_ENABLED", False),
        "url": getattr(config, "SEELE_META_CONTROLLER_URL", ""),
        "on_demand_idle_sec": getattr(config, "SEELE_ON_DEMAND_IDLE_SEC", 300),
        "on_demand_services": ["revise_llm", "logic_llm"],
        "resident_services": ["main_llm", "memory_llm", "emobloom_llm"],
        "status": "disabled",
    }
    if meta_controller_block["enabled"]:
        try:
            from app.utils.seele_meta_client import meta_controller_reachable, list_meta_services

            meta_ok, meta_detail = await meta_controller_reachable(timeout=2.0)
            meta_controller_block["status"] = "online" if meta_ok else "unavailable"
            meta_controller_block["detail"] = meta_detail
            if meta_ok:
                listed, services_payload = await list_meta_services(timeout=3.0)
                if listed:
                    meta_controller_block["services"] = services_payload.get("services", {})
        except Exception as meta_exc:
            meta_controller_block["status"] = "error"
            meta_controller_block["detail"] = str(meta_exc)
    
    return JSONResponse({
        "status": overall_status,
        "architecture": "three-engine",
        "engines_summary": (
            await collect_three_engine_health(
                redis_client=redis_client,
                orchestrator_ready=LifecycleManager._orchestrator_ready,
                logic_components=_logic_engine_components(),
                meta_controller_enabled=getattr(config, "SEELE_META_CONTROLLER_ENABLED", False),
            )
        )["summary"],
        "environment": CURRENT_ENV,
        "components": {
            "orchestrator": LifecycleManager._orchestrator_ready,
            "personality_module": personality_module is not None,
            "gsw_engine": gsw_engine is not None,
            "navigator": navigator is not None,
            "fracture_map": fm_manager is not None,
            "emotion_service": emotion_service is not None,
            "vector_service": vector_service is not None,
        },
        "services": {
            "redis": redis_status,
            "cache_backend": (
                "redis" if redis_status == "connected" else "memory_fallback"
            ),
            "database": db_status,
            "api": "operational",
            "main_llm": {
                "url": config.MAIN_LLM_URL,
                "status": "online" if main_ok else "unavailable",
                "detail": main_detail,
            },
            "memory_llm": {
                "url": config.MEMORY_LLM_URL,
                "status": "online" if memory_ok else "unavailable",
                "detail": memory_detail,
            },
            "emobloom_llm": {
                "url": config.EMOBLOOM_LLM_URL,
                "status": "online" if emobloom_ok else "unavailable",
                "detail": emobloom_detail,
            },
            "llm_safety_layer": llm_status,
            "generative_llm": generative_status,
            "memory_chain": {
                "gsw_engine": gsw_engine is not None,
                "vector_service": vector_service is not None,
                "pgvector": db_status == "online",
                "embedding_llm": "online" if memory_ok else "unavailable",
            },
            "star_orchestration": {
                "enabled": getattr(config, 'STAR_ORCHESTRATION_ENABLED', True),
                "pipeline_version": "v9",
                "pipeline": (
                    "sensing -> user_shadow -> nemo(8081) "
                    "-> llama_audit(8082, conditional/on-demand) "
                    "-> nemo_regen(<=1) -> gemma_personality(8083, on-demand)"
                ),
                "meta_controller_enabled": getattr(
                    config, "SEELE_META_CONTROLLER_ENABLED", False,
                ),
                "v9_enabled": getattr(config, 'V9_PIPELINE_ENABLED', True),
                "llama_audit_enabled": getattr(config, 'LLAMA_AUDIT_ENABLED', True),
                "nemo_regen_on_low_quality": getattr(
                    config, 'V9_NEMO_REGEN_ON_LOW_QUALITY', True,
                ),
                "meta_layer_persist": getattr(config, 'META_LAYER_PERSIST', True),
            },
            "cognitive_layer": {
                "enabled": getattr(config, 'COGNITIVE_LAYER_ENABLED', True),
                "emotion_dimensions": getattr(config, 'EMOTION_DIMENSIONS', 24),
                "user_shadow_blend": getattr(config, 'USER_SHADOW_BLEND', 0.35),
                "tables": [
                    "user_shadow_state",
                    "psychological_milestones",
                ],
            },
            "meta_controller": meta_controller_block,
            "kag_reality_layer": {
                "enabled": getattr(config, "KAG_REALITY_ENABLED", True),
                "max_facts": getattr(config, "KAG_MAX_FACTS", 12),
                "table": "reality_facts",
                "seed_file": "config/reality_seed.json",
            },
        },
        "llm_compute": get_llm_compute_health(),
        "worker": worker_stats,
        "hardware_profile": get_profile_summary(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0"
    })


@app_instance.get("/metrics", tags=["observability"])
async def prometheus_metrics():
    """Prometheus scrape endpoint (VictoriaMetrics / Grafana)."""
    if not getattr(config, "ENABLE_METRICS", True):
        raise HTTPException(status_code=404, detail="Metrics disabled")
    import app.metrics.crisis_metrics  # noqa: F401 — register vita_crisis_* counters
    import app.metrics.chat_latency_metrics  # noqa: F401 — register vita_chat_processing_seconds
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ==================== 核心對話端點 ====================

async def _log_crisis_alert(user_id: str, risk_level: int, session_id: str) -> None:
    """Background task: audit log for crisis-level turns."""
    try:
        crisis_logger.critical(
            f"CRISIS_ALERT | user_id={user_id} | risk_level={risk_level} | "
            f"session_id={session_id}"
        )
        logger.warning(
            f"[CHAT] Crisis alert for user {user_id} (risk_level={risk_level})"
        )
    except Exception as exc:
        logger.error(f"[CHAT] Crisis alert logging failed: {exc}")


@app_instance.get("/chat/greeting", tags=["chat"])
async def chat_greeting():
    """Return canonical opening greeting (same source as identity fast-track)."""
    from app.utils.identity_intent import get_opening_greeting

    persona_name = getattr(config, "PERSONA_NAME", "希兒")
    if persona_name and "," in persona_name:
        persona_name = persona_name.split(",")[-1].strip()

    text = get_opening_greeting(persona_name)
    return JSONResponse({
        "text": text,
        "persona_name": persona_name,
        "source": "identity_canonical",
    })


@app_instance.post("/chat", response_model=ChatResponse, tags=["chat"])
async def process_chat(
    request: ChatRequest,
    language_switcher: LanguageSwitcher = Depends(get_language_switcher),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """主對話端點"""
    start_time = time.time()
    
    try:
        # 驗證 Orchestrator 可用性
        if orchestrator is None:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator service unavailable"
            )
        
        # 語言決策
        lang_result = language_switcher.decide(request.user_id, request.text)
        effective_lang = lang_result.effective_lang
        detected_lang = language_switcher._detect_lang(request.text)
        
        logger.debug(
            f"[CHAT] Language routing: detected={detected_lang}, "
            f"effective={effective_lang}"
        )
        
        # 調用 Orchestrator
        result = await orchestrator.process(
            request,
            language_hint=effective_lang
        )
        
        if not result or not isinstance(result, dict):
            raise HTTPException(status_code=500, detail="Invalid Orchestrator response")
        
        # 驗證與提取
        emotions = VADVectorValidator.validate_and_normalize(
            result.get('emotion_analysis', {})
        )
        
        response_text = result.get('text', '').strip()
        turn_success = bool(result.get('success', False))
        risk_level = int(result.get('risk_level', 0) or 0)

        if risk_level >= int(getattr(config, 'RISK_ESCALATION_THRESHOLD', 4)):
            crisis_logger.critical(
                f"CRISIS_ALERT | user_id={request.user_id} | "
                f"risk_level={risk_level} | session_id={request.session_id}"
            )
            background_tasks.add_task(
                _log_crisis_alert,
                request.user_id,
                risk_level,
                request.session_id,
            )

        if not response_text:
            response_text = (
                "I'm not quite sure what to say. "
                "Could you tell me more about what you're thinking?"
            )
            turn_success = False
        
        # 構建回應
        meta = ChatMeta(
            emotions=emotions,
            risk_level=risk_level,
            phase=result.get('phase', 'unknown'),
            language=effective_lang,
            detected_input_lang=detected_lang
        )
        
        response = ChatResponse(
            text=response_text,
            meta=meta,
            success=turn_success,
            latency_ms=int((time.time() - start_time) * 1000)
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CHAT] Error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=(
                "System error. Please try again in a moment."
            )
        )


# ==================== 語言偏好端點 ====================

@app_instance.get("/user/{user_id}/language-preference", tags=["user"])
async def get_language_preference(
    user_id: str,
    language_switcher: LanguageSwitcher = Depends(get_language_switcher)
):
    """取得用戶語言偏好"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user_id")
        
        pref = language_switcher.get_user_pref(user_id)
        return JSONResponse({
            "user_id": user_id,
            "language_preference": pref or "yue-Hant",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LANG_PREF] Get failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get language preference")


@app_instance.post("/user/{user_id}/language-preference", tags=["user"])
async def set_language_preference(
    user_id: str,
    language: LangCode,
    language_switcher: LanguageSwitcher = Depends(get_language_switcher)
):
    """設定用戶語言偏好"""
    try:
        if not user_id or not language:
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        language_switcher.set_user_pref(user_id, language)
        return JSONResponse({
            "user_id": user_id,
            "language_preference": language,
            "message": "Language preference updated",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LANG_PREF] Set failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to set language preference")


# ==================== Worker 統計端點 ====================

@app_instance.get("/admin/worker-stats", tags=["admin"])
async def get_worker_stats():
    """取得 Worker 統計信息（管理員端點）"""
    try:
        stats = get_processor_stats()
        return JSONResponse({
            "worker_stats": stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        logger.error(f"[ADMIN] Worker stats query failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get worker statistics")


# ==================== 異常處理器 ====================

@app_instance.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 異常處理"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path)
        }
    )


@app_instance.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """全局異常處理"""
    logger.critical(
        f"[ERROR] Unhandled exception at {request.url.path}: {exc}",
        exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": (
                "Critical system error. Please try again in a moment."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


# ==================== 應用導出 ====================

app = app_instance

__version__ = "2.0.0"
__author__ = "Vita Team"
__description__ = "Hong Kong AI Companion System (Clinical Grade)"

logger.info("=" * 80)
logger.info("[MAIN] Vita 2.0 initialization complete [OK]")
logger.info(f"[MAIN] Version: {__version__}")
logger.info(f"[MAIN] Environment: {CURRENT_ENV}")
logger.info("=" * 80)


# ==================== 主程序 ====================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn_config = {
        "app": "app.main:app",
        "host": config.HOST,
        "port": config.PORT,
        "log_level": config.LOG_LEVEL.lower(),
        "access_log": False,
    }
    
    if IS_DEVELOPMENT:
        uvicorn_config["reload"] = True
        logger.info("[MAIN] Development mode: hot reload enabled")
    
    logger.info(
        f"[MAIN] Starting Uvicorn server {config.HOST}:{config.PORT}"
    )
    
    uvicorn.run(**uvicorn_config)