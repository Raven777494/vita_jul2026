# app/__init__.py - 最終安全版（與新config.py完全兼容）

"""
Vita 2.0 - AI 心理伴侶
香港粵語心理健康聊天系統

【初始化流程】
1. 驗證 Python 版本
2. 驗證項目結構
3. 加載配置（config）
4. 設置日誌
5. 初始化數據庫連接
6. 執行啟動檢查
7. 驗證 LLM 服務
8. 安裝清理鉤子
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Any

__version__ = "2.0.0"
__author__ = "Vita Team"

# ==================== 第一步：Python 版本檢查 ====================

MIN_PYTHON_VERSION = (3, 9)

if sys.version_info < MIN_PYTHON_VERSION:
    error_msg = (
        f"[CRITICAL] Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+ required, "
        f"got {sys.version_info.major}.{sys.version_info.minor}"
    )
    print(error_msg, file=sys.stderr)
    sys.exit(1)

# ==================== 第二步：驗證項目結構 ====================

PROJECT_ROOT = Path(__file__).parent.parent

# 必需的目錄列表
required_dirs = [
    PROJECT_ROOT / "logs",
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "cache",
    PROJECT_ROOT / "config"
]

for dir_path in required_dirs:
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[WARNING] Failed to create directory {dir_path}: {e}", file=sys.stderr)

# ==================== 第三步：加載配置（與新安全系統兼容） ====================

config = None
config_error = None

try:
    # 導入新版 config（已驗證敏感信息）
    from app.config import (
        config,
        Config,
        ConfigLogger,
        CURRENT_ENV,
        IS_PRODUCTION,
        IS_STAGING,
        IS_TESTING,
        IS_DEVELOPMENT
    )
    
    ConfigLogger.info("Config module imported successfully")
    
except ImportError as e:
    config_error = f"[CRITICAL] Failed to import config: {e}"
    print(config_error, file=sys.stderr)
    sys.exit(1)

except Exception as e:
    config_error = f"[CRITICAL] Unexpected error importing config: {e}"
    print(config_error, file=sys.stderr)
    sys.exit(1)

# ==================== 第四步：驗證配置完整性（與新驗證系統兼容） ====================

def verify_config_integrity() -> bool:
    """
    驗證關鍵配置項
    
    【注意】新版 config.py 已在類初始化時進行嚴格驗證
    此函數作為雙重保險，檢查運行時狀態
    """
    
    errors = []
    warnings = []
    
    # 檢查基礎配置
    if not config.DATABASE_URL:
        errors.append("DATABASE_URL 未設定")
    elif 'postgresql' not in config.DATABASE_URL.lower():
        errors.append(f"DATABASE_URL 必須是 PostgreSQL 格式")
    
    if not config.HOST:
        warnings.append("HOST 未設定，使用預設值")
    
    if not config.PORT or config.PORT <= 0:
        errors.append("PORT 配置無效")
    
    # 生產環境的額外檢查（新 config.py 已做過，此處為雙重保險）
    if IS_PRODUCTION or IS_STAGING:
        if not config.JWT_SECRET or len(config.JWT_SECRET) < 32:
            errors.append("JWT_SECRET 長度不足或未設定（生產環境必須）")
        
        if not config.ENCRYPT_KEY or len(config.ENCRYPT_KEY) < 32:
            errors.append("ENCRYPT_KEY 長度不足或未設定（生產環境必須）")
        
        if not config.API_KEY or config.API_KEY.startswith("dev_"):
            errors.append("API_KEY 未設定或仍用開發預設值（生產環境禁止）")
        
        if not config.DB_PASSWORD:
            errors.append("DB_PASSWORD 未設定（生產環境必須）")
    
    # 輸出結果
    if errors:
        for error in errors:
            ConfigLogger.critical(f"[ERROR] {error}")
        return False
    
    if warnings:
        for warning in warnings:
            ConfigLogger.warning(f"[WARN] {warning}")
    
    ConfigLogger.info("Configuration integrity verified [OK]")
    return True

# 執行驗證
if not verify_config_integrity():
    if IS_PRODUCTION:
        ConfigLogger.critical("Production environment validation failed!")
        sys.exit(1)
    else:
        ConfigLogger.warning("Configuration issues detected, but continuing in dev mode")

# ==================== 第五步：設置日誌系統 ====================

# 從我們的新工廠匯入並取得 logger
from app.logger import get_logger
from app.config import ConfigLogger
vita_logger = get_logger("vita")

# 設置其他模塊的日誌（避免第三方套件太吵）
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

vita_logger.info("="*70)
vita_logger.info(f"Vita {__version__} - AI 心理伴侶系統")
vita_logger.info("="*70)
vita_logger.info(f"Environment: {config.ENV.upper()}")
vita_logger.info(f"Debug Mode: {config.DEBUG}")
vita_logger.info(f"Log Level: {config.LOG_LEVEL}")
vita_logger.info(f"Project Root: {PROJECT_ROOT}")
vita_logger.info(f"Database: {ConfigLogger.mask_sensitive_url(config.DATABASE_URL)}")

# ==================== 第六步：初始化數據庫 ====================

db_manager = None
db_initialized = False

try:
    # 【修復】使用新版 db_service.py 中的導入
    from app.services.db_service import DBService
    
    vita_logger.info("Database service imported")
    
    # 初始化 DBService
    db_manager = DBService()
    from app.services.db_manager import db_manager as _core_db_manager

    _db_health = _core_db_manager.health_check()
    db_initialized = _db_health.get("status") == "healthy"
    if db_initialized:
        vita_logger.info("Database manager initialized [OK]")
    else:
        vita_logger.warning(
            "Database unavailable: %s",
            _db_health.get("error", "unknown"),
        )
    
except ImportError as e:
    vita_logger.error(f"Failed to import database service: {e}", exc_info=True)
    if IS_PRODUCTION:
        vita_logger.critical("Production requires working database!")
        sys.exit(1)
    else:
        vita_logger.warning("Database functionality may be unavailable")

except Exception as e:
    vita_logger.error(f"Database initialization failed: {e}", exc_info=True)
    if IS_PRODUCTION:
        vita_logger.critical("Production database initialization failed!")
        sys.exit(1)
    else:
        db_initialized = False
        vita_logger.warning("Continuing without database in dev mode")

# ==================== 第七步：驗證 LLM 服務可用性 ====================

from app.utils.llm_health import probe_llm_service

# 檢查 LLM 服務（非阻塞性檢查）
llm_services = config.get_startup_llm_services()

vita_logger.info("\nLLM Services Status:")
llm_status: Dict[str, bool] = {}

for service_name, service_url in llm_services.items():
    is_available, detail = probe_llm_service(
        service_url,
        timeout=3.0,
        api_key=getattr(config, 'API_KEY', None),
    )
    llm_status[service_name] = is_available
    if is_available:
        vita_logger.info(f"  [OK] {service_name}: {service_url} ({detail})")
    else:
        vita_logger.warning(f"  [FAIL] {service_name}: {service_url} ({detail})")

# 警告：如果所有 LLM 服務都不可用
all_llm_down = not any(llm_status.values())
if all_llm_down:
    vita_logger.warning("[!] All LLM services are unavailable!")
    vita_logger.warning("Application will start but chat functionality will fail")

# ==================== 第八步：驗證 Redis 連接（可選） ====================

redis_available = False
redis_client = None

try:
    import redis

    redis_client = redis.from_url(
        config.REDIS_URL,
        socket_connect_timeout=config.REDIS_SOCKET_CONNECT_TIMEOUT,
        socket_timeout=config.REDIS_SOCKET_TIMEOUT,
        decode_responses=True,
    )

    redis_client.ping()
    redis_available = True
    vita_logger.info("Redis connection verified [OK]")

except ImportError:
    vita_logger.warning("Redis not installed, caching disabled")

except Exception as e:
    vita_logger.warning(f"Redis connection failed: {e}, caching will be unavailable")

finally:
    if redis_client is not None:
        try:
            redis_client.close()
        except Exception:
            pass

# ==================== 第九步：服務狀態總結 ====================

services_status: Dict[str, Any] = {
    'Config': True,
    'Logger': True,
    'Database': db_initialized,
    'Redis': redis_available,
    'LLM (Main-LLM)': llm_status.get('Main-LLM (Soul)', False),
    'LLM (Revise-LLM)': llm_status.get('Revise-LLM', False),
    'LLM (Logic-LLM)': llm_status.get('Logic-LLM', False),
    'LLM (Memory-LLM)': llm_status.get('Memory-LLM', False),
    'LLM (Emobloom-LLM)': llm_status.get('Emobloom-LLM', False),
}

vita_logger.info("\nServices Status:")
critical_services_ok = True

for service_name, is_available in services_status.items():
    if is_available:
        vita_logger.info(f"  [OK] {service_name}")
    else:
        vita_logger.warning(f"  [FAIL] {service_name}")
    
    # 檢查是否有關鍵服務故障
    if service_name == 'Database' and IS_PRODUCTION and not is_available:
        critical_services_ok = False

if IS_PRODUCTION and not critical_services_ok:
    vita_logger.critical("Critical services are unavailable in production!")
    sys.exit(1)

# ==================== 第十步：安裝清理鉤子 ====================

import atexit

def _logging_streams_open(logger) -> bool:
    """Return False if any handler stream is already closed (common during pytest teardown)."""
    current = logger
    while current is not None:
        for handler in getattr(current, "handlers", []):
            stream = getattr(handler, "stream", None)
            if stream is not None and getattr(stream, "closed", False):
                return False
        current = getattr(current, "parent", None)
    return True

def _log_shutdown(message: str) -> None:
    """Log shutdown line; skip when streams are closed during interpreter teardown."""
    if not _logging_streams_open(vita_logger):
        return
    vita_logger.info(message)

def cleanup():
    """應用退出時的優雅清理"""
    try:
        if not _logging_streams_open(vita_logger):
            return

        _log_shutdown("\nInitiating graceful shutdown...")
        
        # 關閉數據庫連接（動態導入，避免 NameError）
        try:
            from app.services.db_service import db_manager  # 改成你實際嘅檔案名
            # 如果你用 db_manager.py，請改為：from app.services.db_manager import db_manager
            if db_manager:
                db_manager.close()
                _log_shutdown("Database connections closed")
        except Exception as e:
            vita_logger.debug(f"Database cleanup skipped or failed: {e}")
        
        # 關閉 Redis（動態導入）
        try:
            from app.orchestrator import Orchestrator
            # Orchestrator 內有 redis_client
            if hasattr(Orchestrator, '_orchestrator_instance') and Orchestrator._orchestrator_instance:
                instance = Orchestrator._orchestrator_instance
                if instance.redis_client:
                    instance.redis_client.close()
                    _log_shutdown("Redis connection closed")
        except Exception as e:
            vita_logger.debug(f"Redis cleanup skipped or failed: {e}")
        
        # 關閉 Orchestrator（如果有全局實例）
        try:
            from app.orchestrator import shutdown_orchestrator
            shutdown_orchestrator()
            _log_shutdown("Orchestrator shutdown complete")
        except Exception as e:
            vita_logger.debug(f"Orchestrator shutdown skipped: {e}")
        
        _log_shutdown("=" * 70)
        _log_shutdown("Vita shutdown complete")
        _log_shutdown("=" * 70)
    
    except Exception as e:
        # 最外層保護，確保一定唔會因為 cleanup 本身出錯而崩潰
        print(f"[CLEANUP ERROR] Unexpected error during shutdown: {e}", file=sys.stderr)

atexit.register(cleanup)

# ==================== 第十一步：驗證啟動完成 ====================

vita_logger.info("\n" + "="*70)
vita_logger.info(f"[OK] Vita {__version__} initialized successfully!")
vita_logger.info(f"[OK] Environment: {config.ENV.upper()}")
vita_logger.info(f"[OK] API will be available at: http://{config.HOST}:{config.PORT}")
vita_logger.info("="*70 + "\n")

# ==================== 導出公共 API ====================

__all__ = [
    '__version__',
    '__author__',
    'PROJECT_ROOT',
    'config',
    'CONFIG',
    'db_manager',
    'vita_logger', # Export as vita_logger
    'IS_PRODUCTION',
    'IS_STAGING',
    'IS_TESTING',
    'IS_DEVELOPMENT',
    'services_status',
    'llm_status',
]

# ==================== 完成標記 ====================

vita_logger.debug("app/__init__.py module fully initialized")