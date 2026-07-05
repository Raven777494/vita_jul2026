# app/config.py - v10.0.0 完全重構版
"""
Vita 2.0 配置管理系統 v10.0.0 - 零截斷統一版本
修復清單:
1. 環境變數名稱統一為 MAIN_LLM_URL / REVISE_LLM_URL / LOGIC_LLM_URL / MEMORY_LLM_URL / EMOBLOOM_LLM_URL
2. CRITIC_LLM_* 為已棄用別名，讀取時映射至 REVISE_LLM_*
3. 統一 Docker Hostname 映射
4. 移除雙重配置加載邏輯
5. 添加 LLM 服務配置工廠類
6. 完整的配置驗證機制
"""

import os
import sys
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv
from dataclasses import dataclass

from compose_env import compose_file_credential, compose_or_env

# ==================== 日誌系統 ====================

class ConfigLogger:
    @staticmethod
    def info(message: str) -> None:
        print(f"[CONFIG-INFO] {message}", file=sys.stdout)
    
    @staticmethod
    def warning(message: str) -> None:
        print(f"[CONFIG-WARN] {message}", file=sys.stderr)
    
    @staticmethod
    def error(message: str) -> None:
        print(f"[CONFIG-ERROR] {message}", file=sys.stderr)
    
    @staticmethod
    def critical(message: str) -> None:
        print(f"[CONFIG-CRITICAL] {message}", file=sys.stderr)
    
    @staticmethod
    def mask_sensitive_url(url: str) -> str:
        if not url:
            return "Unknown"
        return re.sub(r'(://\w+:)\w+(@)', r'\1****\2', url)

logger = ConfigLogger()

# ==================== 環境偵測 ====================

def _get_environment() -> str:
    env_raw = os.getenv("ENV", "development").lower().strip()
    valid_environments = {
        "dev": "development",
        "development": "development",
        "test": "testing",
        "testing": "testing",
        "staging": "staging",
        "prod": "production",
        "production": "production"
    }
    if env_raw not in valid_environments:
        logger.warning(f"Unknown environment '{env_raw}', using 'development'")
        return "development"
    return valid_environments[env_raw]

CURRENT_ENV = _get_environment()
IS_PRODUCTION = CURRENT_ENV == "production"
IS_STAGING = CURRENT_ENV == "staging"
IS_TESTING = CURRENT_ENV == "testing"
IS_DEVELOPMENT = CURRENT_ENV == "development"

# Docker 環境偵測
IS_RUNNING_IN_DOCKER = os.path.exists('/.dockerenv') or os.getenv('RUNNING_IN_DOCKER', '').lower() == 'true'


def _resolve_db_credential(key: str, default: str = "") -> str:
    """Resolve a DB auth credential (DB_USER / DB_PASSWORD).

    Local/testing host development treats config/.env.compose as authoritative
    because that file initializes the local Docker Postgres. This prevents a
    stale inherited OS/Machine environment value (e.g. a leftover DB_PASSWORD)
    from silently causing "password authentication failed". Production, staging,
    and in-container runtimes keep OS-environment precedence so injected secrets
    win.
    """
    local_dev = not (IS_PRODUCTION or IS_STAGING or IS_RUNNING_IN_DOCKER)
    if local_dev:
        file_value = compose_file_credential(key)
        if file_value:
            return file_value
    return compose_or_env(key, default)

def _resolve_database_url() -> str:
    """Build DATABASE_URL with the same credential precedence as DB_* fields.

    Local host development ignores a stale OS-level DATABASE_URL (often exported
    together with Machine-scope DB_PASSWORD) and builds from config/.env.compose
    credentials plus DB_HOST from .env.local.
    """
    db_user = _resolve_db_credential("DB_USER", "postgres")
    db_password = _resolve_db_credential("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST") or ("postgres" if IS_RUNNING_IN_DOCKER else "127.0.0.1")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME") or compose_or_env(
        "DB_NAME", "vita_test" if IS_TESTING else "vita_db"
    )
    built = (
        f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )

    local_dev = not (IS_PRODUCTION or IS_STAGING or IS_RUNNING_IN_DOCKER)
    if local_dev:
        return built

    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    if IS_RUNNING_IN_DOCKER:
        docker_url = compose_or_env("DATABASE_URL", "")
        if docker_url:
            return docker_url

    return built

# ==================== .env 載入 ====================

def _load_env_file() -> None:
    """Load .env files. In production/staging, never override existing OS env vars."""
    env_paths = [
        Path(__file__).parent.parent / "config" / ".env.local",
        Path(__file__).parent.parent / "config" / ".env",
        Path(__file__).parent.parent / ".env",
        Path.home() / ".vita.env"
    ]
    override = not (IS_PRODUCTION or IS_STAGING)

    for env_path in env_paths:
        if env_path.exists() and env_path.is_file():
            try:
                load_dotenv(dotenv_path=str(env_path), override=override)
                logger.info(
                    f"Loaded .env from {env_path} "
                    f"(override={'yes' if override else 'no'})"
                )
                return
            except Exception as e:
                logger.warning(f"Failed to load .env from {env_path}: {e}")

_load_env_file()

# ==================== 目錄配置 ====================

class DirectoryConfig:
    PROJECT_ROOT = Path(__file__).parent.parent
    
    LOGS_DIR = Path(os.getenv("LOGS_DIR", str(PROJECT_ROOT / "logs")))
    DATA_DIR = PROJECT_ROOT / "data"
    CACHE_DIR = PROJECT_ROOT / "cache"
    CONFIG_DIR = PROJECT_ROOT / "config"
    MODELS_DIR = PROJECT_ROOT / "models"
    UPLOADS_DIR = DATA_DIR / "uploads"
    BACKUPS_DIR = DATA_DIR / "backups"
    
    @classmethod
    def ensure_all_dirs(cls) -> None:
        directories = [
            cls.LOGS_DIR, cls.DATA_DIR, cls.CACHE_DIR, 
            cls.CONFIG_DIR, cls.MODELS_DIR, cls.UPLOADS_DIR, cls.BACKUPS_DIR
        ]
        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

DirectoryConfig.ensure_all_dirs()


def _resolve_llm_env(primary_key: str, legacy_key: str, default: str) -> str:
    """讀取 LLM 環境變數；legacy_key 為已棄用別名（如 CRITIC_LLM_URL）。"""
    primary = os.getenv(primary_key)
    if primary:
        return primary
    legacy = os.getenv(legacy_key)
    if legacy:
        logger.warning(
            f"Deprecated environment variable {legacy_key}; use {primary_key} instead"
        )
        return legacy
    return default

# ==================== LLM 服務埠與 Hostname 映射 ====================
#
# 環境變數與管線職責對照:
#   MAIN_LLM_URL     :8081  SoulEngine    Mistral-Nemo
#   REVISE_LLM_URL   :8082  ReviseEngine  Llama-3.2-3B
#   LOGIC_LLM_URL    :8083  LogicEngine   Distil-NPC-gemma
#   MEMORY_LLM_URL   :8084  embedding     BAAI/bge-m3
#   EMOBLOOM_LLM_URL :8085  emotion       Emobloom-7b

@dataclass
class LLMServiceConfig:
    """LLM 服務統一配置"""
    service_id: str
    display_name: str
    description: str
    pipeline_role: str
    env_url_key: str
    startup_label: str
    port: int
    model_name: str
    model_path: str
    timeout_seconds: float
    docker_hostname: str
    gpu_layers: int
    n_threads: int
    n_ctx: int
    priority: int
    priority_level: str

class AIServiceRegistry:
    """統一的 LLM 服務註冊表 - 單一信源"""
    
    SERVICES = {
        'main_llm': LLMServiceConfig(
            service_id='main_llm',
            display_name='Main LLM (Mistral-Nemo-12B)',
            description='Primary response generator (v9 Nemo); MAIN_LLM_URL :8081',
            pipeline_role='primary_generate',
            env_url_key='MAIN_LLM_URL',
            startup_label='Main-LLM (Soul)',
            port=8081,
            model_name='Mistral-Nemo-12B',
            model_path='models/Mistral-Nemo-Instruct-2407-Q5_K_M.gguf',
            timeout_seconds=120,
            docker_hostname='main-llm',
            gpu_layers=40,
            n_threads=8,
            n_ctx=2048,
            priority=1,
            priority_level='critical'
        ),
        'revise_llm': LLMServiceConfig(
            service_id='revise_llm',
            display_name='Revise LLM (Llama-3.2-3B)',
            description='Conditional Meta Auditor (v9); REVISE_LLM_URL :8082',
            pipeline_role='meta_audit',
            env_url_key='REVISE_LLM_URL',
            startup_label='Revise-LLM',
            port=8082,
            model_name='Llama-3.2-3B',
            model_path='models/Llama-3.2-3B-Instruct-Q4_K_M.gguf',
            timeout_seconds=30,
            docker_hostname='revise-llm',
            gpu_layers=0,
            n_threads=6,
            n_ctx=1024,
            priority=2,
            priority_level='critical'
        ),
        'logic_llm': LLMServiceConfig(
            service_id='logic_llm',
            display_name='Logic LLM (Distil-NPC-gemma-3-1b)',
            description='Character personality layer (v9 Gemma); LOGIC_LLM_URL :8083',
            pipeline_role='personality',
            env_url_key='LOGIC_LLM_URL',
            startup_label='Logic-LLM',
            port=8083,
            model_name='Distil-NPC-gemma-3-1b',
            model_path='models/Distil-NPC-gemma-3-1b-it-Q4_K_M-imat.gguf',
            timeout_seconds=30,
            docker_hostname='logic-llm',
            gpu_layers=0,
            n_threads=4,
            n_ctx=2048,
            priority=3,
            priority_level='important'
        ),
        'memory_llm': LLMServiceConfig(
            service_id='memory_llm',
            display_name='Memory LLM (BGE-M3)',
            description='Semantic embedding and memory retrieval (VectorService)',
            pipeline_role='memory',
            env_url_key='MEMORY_LLM_URL',
            startup_label='Memory-LLM',
            port=8084,
            model_name='bge-m3',
            model_path='BAAI/bge-m3',
            timeout_seconds=20,
            docker_hostname='memory-llm',
            gpu_layers=0,
            n_threads=4,
            n_ctx=1024,
            priority=5,
            priority_level='important'
        ),
        'emobloom_llm': LLMServiceConfig(
            service_id='emobloom_llm',
            display_name='Emobloom LLM (Emobloom-7b)',
            description='Emotional state recognition (EmotionService)',
            pipeline_role='emotion',
            env_url_key='EMOBLOOM_LLM_URL',
            startup_label='Emobloom-LLM',
            port=8085,
            model_name='Emobloom-7b',
            model_path='models/Emobloom-7b.i1-Q5_K_M.gguf',
            timeout_seconds=10,
            docker_hostname='emobloom-llm',
            gpu_layers=0,
            n_threads=6,
            n_ctx=1024,
            priority=4,
            priority_level='important'
        ),
    }

    @classmethod
    def apply_hardware_profile(cls) -> None:
        """Merge config/hardware_profile.json compute settings into SERVICES."""
        try:
            from dataclasses import replace
            from hardware_profile_loader import load_hardware_profile
        except ImportError:
            return

        profile = load_hardware_profile()
        if not profile:
            return

        overrides = profile.get("services", {})
        for service_id, cfg in list(cls.SERVICES.items()):
            ovr = overrides.get(service_id)
            if not ovr:
                continue
            patch = {}
            for key in ("gpu_layers", "n_threads", "n_ctx", "priority_level"):
                if key in ovr:
                    patch[key] = ovr[key]
            if patch:
                cls.SERVICES[service_id] = replace(cfg, **patch)
    
    @classmethod
    def get_service(cls, service_id: str) -> Optional[LLMServiceConfig]:
        return cls.SERVICES.get(service_id)
    
    @classmethod
    def get_all_services(cls) -> Dict[str, LLMServiceConfig]:
        return cls.SERVICES.copy()
    
    @classmethod
    def validate_all(cls) -> Tuple[bool, List[str]]:
        """驗證所有服務配置"""
        errors = []
        ports_seen = set()
        
        for service_id, config in cls.SERVICES.items():
            # 驗證埠號
            if not (1024 <= config.port <= 65535):
                errors.append(f"{service_id}: Invalid port {config.port}")
            
            if config.port in ports_seen:
                errors.append(f"{service_id}: Duplicate port {config.port}")
            ports_seen.add(config.port)
            
            # 驗證 timeout
            if config.timeout_seconds <= 0:
                errors.append(f"{service_id}: Invalid timeout {config.timeout_seconds}")
            
            # 驗證 Docker hostname
            if not config.docker_hostname:
                errors.append(f"{service_id}: Missing Docker hostname")
        
        return len(errors) == 0, errors

AIServiceRegistry.apply_hardware_profile()

class URLNormalizer:
    @staticmethod
    def normalize(url: Optional[str]) -> str:
        if not url:
            return ""
        url = str(url).strip()
        if url.endswith('/'):
            url = url.rstrip('/')
        return url

# ==================== 主配置類別 ====================

class Config:
    """
    Vita 2.0 配置管理系統 v10.0.0
    完整支援環境變數和容器網絡
    統一 LLM 服務命名
    """
    
    # ---------- 環境 ----------
    ENV = CURRENT_ENV
    IS_PRODUCTION = IS_PRODUCTION
    IS_STAGING = IS_STAGING
    IS_TESTING = IS_TESTING
    IS_DEVELOPMENT = IS_DEVELOPMENT
    IS_DOCKER = IS_RUNNING_IN_DOCKER
    DEBUG = CURRENT_ENV in ("dev", "development", "staging") and os.getenv("DEBUG", "true").lower() == "true"
    
    # ---------- 目錄 ----------
    PROJECT_ROOT = DirectoryConfig.PROJECT_ROOT
    LOGS_DIR = DirectoryConfig.LOGS_DIR
    DATA_DIR = DirectoryConfig.DATA_DIR
    CACHE_DIR = DirectoryConfig.CACHE_DIR
    CONFIG_DIR = DirectoryConfig.CONFIG_DIR
    MODELS_DIR = DirectoryConfig.MODELS_DIR
    
    # ---------- 認證與加密 ----------
    JWT_SECRET = os.getenv("JWT_SECRET", "dev_jwt_secret_change_in_production_minimum_32_chars")
    ENCRYPT_KEY = os.getenv("ENCRYPT_KEY", "dev_encrypt_key_change_in_production_minimum_32_chars")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key_change_in_production_minimum_32_chars")
    API_KEY = os.getenv("API_KEY", "dev_api_key_change_in_production_minimum_32_chars")
    JWT_ALGORITHM = "HS256"
    TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "30"))
    AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
    
    # ---------- 數據庫配置（本地密碼：config/.env.compose；見 _resolve_db_credential） ----------
    DB_USER = _resolve_db_credential("DB_USER", "postgres")
    DB_PASSWORD = _resolve_db_credential("DB_PASSWORD", "")
    DB_HOST = os.getenv("DB_HOST") or ("postgres" if IS_DOCKER else "127.0.0.1")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME") or compose_or_env("DB_NAME", "vita_test" if IS_TESTING else "vita_db")

    DATABASE_URL = _resolve_database_url()
    
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    DB_POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"
    DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
    DB_ECHO_POOL = os.getenv("DB_ECHO_POOL", "false").lower() == "true"
    DB_AUTO_FLUSH = os.getenv("DB_AUTO_FLUSH", "false").lower() == "true"
    DB_AUTO_COMMIT = os.getenv("DB_AUTO_COMMIT", "false").lower() == "true"
    DB_EXPIRE_ON_COMMIT = os.getenv("DB_EXPIRE_ON_COMMIT", "false").lower() == "true"
    DB_PLATFORM_ENGINE_REQUIRED = (
        os.getenv("DB_PLATFORM_ENGINE_REQUIRED", "true" if IS_DEVELOPMENT else "false").lower()
        == "true"
    )
    DB_PLATFORM_POSTGRES_IMAGE = "vita-postgres:pg16-vector-age-cron"
    
    # ---------- Redis ----------
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0" if IS_DOCKER else "redis://127.0.0.1:6379/0")
    REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
    REDIS_SOCKET_TIMEOUT = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
    REDIS_SOCKET_CONNECT_TIMEOUT = int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "5"))
    REDIS_TIMEOUT = int(os.getenv("REDIS_TIMEOUT", os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "5")))
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
    
    # ---------- LLM 服務 URL - 統一命名 (v10.0.0 核心修復) ----------
    
    # Main LLM (Mistral-Nemo-12B)
    MAIN_LLM_URL = URLNormalizer.normalize(os.getenv(
        "MAIN_LLM_URL",
        "http://main-llm:8081" if IS_DOCKER else "http://127.0.0.1:8081"
    ))
    MAIN_LLM_MODEL = os.getenv("MAIN_LLM_MODEL", "Mistral-Nemo-12B")
    MAIN_LLM_TIMEOUT = float(os.getenv("MAIN_LLM_TIMEOUT", "120.0"))
    
    # Revise pipeline endpoint (Llama-3.2-3B, port 8082)
    REVISE_LLM_URL = URLNormalizer.normalize(_resolve_llm_env(
        "REVISE_LLM_URL",
        "CRITIC_LLM_URL",
        "http://revise-llm:8082" if IS_DOCKER else "http://127.0.0.1:8082",
    ))
    REVISE_LLM_MODEL = _resolve_llm_env("REVISE_LLM_MODEL", "CRITIC_LLM_MODEL", "Llama-3.2-3B")
    REVISE_LLM_TIMEOUT = float(_resolve_llm_env("REVISE_LLM_TIMEOUT", "CRITIC_LLM_TIMEOUT", "30.0"))
    
    # Logic LLM (Distil-NPC-gemma-3-1b)
    LOGIC_LLM_URL = URLNormalizer.normalize(os.getenv(
        "LOGIC_LLM_URL",
        "http://logic-llm:8083" if IS_DOCKER else "http://127.0.0.1:8083"
    ))
    LOGIC_LLM_MODEL = os.getenv("LOGIC_LLM_MODEL", "Distil-NPC-gemma-3-1b")
    LOGIC_LLM_TIMEOUT = float(os.getenv("LOGIC_LLM_TIMEOUT", "30.0"))
    
    # Memory LLM (BGE-M3)
    MEMORY_LLM_URL = URLNormalizer.normalize(os.getenv(
        "MEMORY_LLM_URL",
        "http://memory-llm:8084" if IS_DOCKER else "http://127.0.0.1:8084"
    ))
    MEMORY_LLM_MODEL = os.getenv("MEMORY_LLM_MODEL", "bge-m3")
    MEMORY_LLM_TIMEOUT = float(os.getenv("MEMORY_LLM_TIMEOUT", "20.0"))
    
    # Emobloom LLM (Emobloom-7b)
    EMOBLOOM_LLM_URL = URLNormalizer.normalize(os.getenv(
        "EMOBLOOM_LLM_URL",
        "http://emobloom-llm:8085" if IS_DOCKER else "http://127.0.0.1:8085"
    ))
    EMOBLOOM_LLM_MODEL = os.getenv("EMOBLOOM_LLM_MODEL", "Emobloom-7b")
    EMOBLOOM_LLM_TIMEOUT = float(os.getenv("EMOBLOOM_LLM_TIMEOUT", "10.0"))
    
    # LLM 重試策略
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_DELAY_SECONDS", "1.0"))

    # 管線超時索引（供 emotional_safety_hub 等模組使用）
    LLM_TIMEOUTS = {
        'main_llm': MAIN_LLM_TIMEOUT,
        'revise_llm': REVISE_LLM_TIMEOUT,
        'logic_llm': LOGIC_LLM_TIMEOUT,
        'memory_llm': MEMORY_LLM_TIMEOUT,
        'emobloom_llm': EMOBLOOM_LLM_TIMEOUT,
    }
    
    # ---------- FastAPI 網路 ----------
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
    RATE_LIMIT_REQUESTS_PER_MINUTE = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "60"))
    RATE_LIMIT_BURST_SIZE = int(os.getenv("RATE_LIMIT_BURST_SIZE", "10"))
    
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080,http://localhost:5173").split(",") if o.strip()]
    if IS_DEVELOPMENT and not CORS_ORIGINS:
        CORS_ORIGINS = ["*"]
    
    # ---------- 臨床風險 ----------
    RISK_ESCALATION_THRESHOLD = int(os.getenv("RISK_ESCALATION_THRESHOLD", "4"))
    CRISIS_SIGNAL_THRESHOLD = int(os.getenv("CRISIS_SIGNAL_THRESHOLD", "3"))
    CRISIS_INTERCEPTION_RATE_ALERT_THRESHOLD = float(
        os.getenv("CRISIS_INTERCEPTION_RATE_ALERT_THRESHOLD", "0.95")
    )
    CRISIS_INTERCEPTION_ALERT_MIN_SIGNALS = int(
        os.getenv("CRISIS_INTERCEPTION_ALERT_MIN_SIGNALS", "5")
    )
    MEMORY_RETRIEVAL_TOP_K = int(os.getenv("MEMORY_RETRIEVAL_TOP_K", "5"))
    MEMORY_MIN_SIMILARITY = float(os.getenv("MEMORY_MIN_SIMILARITY", "0.45"))
    STAR_ORCHESTRATION_ENABLED = os.getenv("STAR_ORCHESTRATION_ENABLED", "true").lower() == "true"
    V9_PIPELINE_ENABLED = os.getenv("V9_PIPELINE_ENABLED", "true").lower() == "true"
    LLAMA_AUDIT_ENABLED = os.getenv("LLAMA_AUDIT_ENABLED", "true").lower() == "true"
    LLAMA_AUDIT_RISK_THRESHOLD = int(os.getenv("LLAMA_AUDIT_RISK_THRESHOLD", "3"))
    LLAMA_AUDIT_QUALITY_THRESHOLD = float(os.getenv("LLAMA_AUDIT_QUALITY_THRESHOLD", "0.7"))
    V9_PERSONALITY_ENABLED = os.getenv("V9_PERSONALITY_ENABLED", "true").lower() == "true"
    V9_MIN_RESPONSE_LENGTH = int(os.getenv("V9_MIN_RESPONSE_LENGTH", "10"))
    V9_NEMO_REGEN_ON_LOW_QUALITY = os.getenv(
        "V9_NEMO_REGEN_ON_LOW_QUALITY", "true"
    ).lower() == "true"
    V9_NEMO_REGEN_MAX = int(os.getenv("V9_NEMO_REGEN_MAX", "1"))
    META_LAYER_PERSIST = os.getenv("META_LAYER_PERSIST", "true").lower() == "true"
    COGNITIVE_LAYER_ENABLED = os.getenv("COGNITIVE_LAYER_ENABLED", "true").lower() == "true"
    EMOTION_DIMENSIONS = int(os.getenv("EMOTION_DIMENSIONS", "24"))
    USER_SHADOW_BLEND = float(os.getenv("USER_SHADOW_BLEND", "0.35"))
    # Phase 6: Seele Meta Controller (on-demand 8082/8083)
    SEELE_META_CONTROLLER_ENABLED = (
        os.getenv("SEELE_META_CONTROLLER_ENABLED", "true").lower() == "true"
        and not IS_DOCKER
    )
    SEELE_META_CONTROLLER_URL = os.getenv(
        "SEELE_META_CONTROLLER_URL",
        "http://host.docker.internal:8090" if IS_DOCKER else "http://127.0.0.1:8090",
    )
    SEELE_META_PORT = int(os.getenv("SEELE_META_PORT", "8090"))
    SEELE_ON_DEMAND_IDLE_SEC = int(os.getenv("SEELE_ON_DEMAND_IDLE_SEC", "300"))
    SEELE_ON_DEMAND_START_TIMEOUT = int(os.getenv("SEELE_ON_DEMAND_START_TIMEOUT", "120"))
    KAG_REALITY_ENABLED = os.getenv("KAG_REALITY_ENABLED", "true").lower() == "true"
    KAG_MAX_FACTS = int(os.getenv("KAG_MAX_FACTS", "12"))
    WALKER_SCORE_THRESHOLD = float(os.getenv("WALKER_SCORE_THRESHOLD", "0.3"))
    WALKER_SCORE_HIGH_RISK_BOOST = float(os.getenv("WALKER_SCORE_HIGH_RISK_BOOST", "0.1"))
    CONCERN_THRESHOLD = float(os.getenv("CONCERN_THRESHOLD", "0.6"))
    HIGH_RISK_SESSION_THRESHOLD = int(os.getenv("HIGH_RISK_SESSION_THRESHOLD", "10"))
    SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
    SESSION_MAX_RETENTION_DAYS = int(os.getenv("SESSION_MAX_RETENTION_DAYS", "90"))
    AUTO_ESCALATION_DELAY_MINUTES = int(os.getenv("AUTO_ESCALATION_DELAY_MINUTES", "1"))
    ESCALATION_CONFIRMATION_TIMEOUT = int(os.getenv("ESCALATION_CONFIRMATION_TIMEOUT", "30"))
    ESCALATION_WEBHOOK_URL = os.getenv("ESCALATION_WEBHOOK_URL", "").strip()
    ESCALATION_NOTIFIER_ENABLED = (
        os.getenv("ESCALATION_NOTIFIER_ENABLED", "true").lower() == "true"
    )

    from app.clinical.companion_language_policy import COMPANION_SAFE_REPLIES

    DEFAULT_SAFE_REPLIES = dict(COMPANION_SAFE_REPLIES)
    
    RISK_KEYWORDS = {
        'critical': ["自殺", "想死", "自傷", "跳樓", "割脈"],
        'high': ["好痛", "忍受唔到", "孤獨", "絕望", "放棄"],
        'medium': ["唔開心", "好累", "好難", "受傷"]
    }
    
    # ---------- 個性配置 ----------
    PERSONA_NAME = "Joanna, 希兒"
    PERSONA_ID = "seele_joanna_v1"
    DEFAULT_LANG = "zh-HK"
    MIX_EN_RATIO = 0.2
    INITIAL_INTIMACY = 0.3
    INTIMACY_DECAY_RATE = 0.05
    BOUNDARY_MULTIPLIER = float(os.getenv("BOUNDARY_MULTIPLIER", "1.0"))
    DRIFT_THRESHOLD = 0.7
    DREAM_MODE_TEMPERATURE = float(os.getenv("DREAM_MODE_TEMPERATURE", "0.73"))
    DREAM_MODE_KEYWORDS = ["夢", "想像", "故事", "如果", "假如"]
    PERSONALITY_TRAITS = {'warmth': 0.85, 'professionalism': 0.8, 'empathy': 0.9, 'humor': 0.7, 'directness': 0.6}
    
    # ---------- 系統監控 ----------
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ACCESS_LOG_FILE = str(LOGS_DIR / "access.log")
    ERROR_LOG_FILE = str(LOGS_DIR / "error.log")
    HEALTH_LOG_FILE = str(LOGS_DIR / "health.log")
    ENABLE_FILE_LOGGING = os.getenv("ENABLE_FILE_LOGGING", "true" if IS_PRODUCTION else "false").lower() == "true"
    ENABLE_HEALTH_CHECK = os.getenv("ENABLE_HEALTH_CHECK", "true").lower() == "true"
    HEALTH_CHECK_INTERVAL_SECONDS = int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "60"))
    ALERT_RECOVERY_TIMEOUT = int(os.getenv("ALERT_RECOVERY_TIMEOUT", "300"))
    VICTORIA_METRICS_URL = os.getenv("VICTORIA_METRICS_URL", "http://127.0.0.1:8428").rstrip("/")
    VICTORIA_LOGS_URL = os.getenv("VICTORIA_LOGS_URL", "http://127.0.0.1:9428").rstrip("/")
    ENABLE_METRICS = os.getenv("ENABLE_METRICS", "true").lower() == "true"
    ENABLE_TRACING = os.getenv("ENABLE_TRACING", "true").lower() == "true"
    ENABLE_VICTORIA_LOGS_SHIPPER = os.getenv("ENABLE_VICTORIA_LOGS_SHIPPER", "true").lower() == "true"
    VICTORIA_LOGS_SERVICE = os.getenv("VICTORIA_LOGS_SERVICE", "vita-api")
    VICTORIA_LOGS_BATCH_SIZE = int(os.getenv("VICTORIA_LOGS_BATCH_SIZE", "50"))
    VICTORIA_LOGS_FLUSH_INTERVAL = float(os.getenv("VICTORIA_LOGS_FLUSH_INTERVAL", "1.0"))
    VICTORIA_LOGS_TIMEOUT = float(os.getenv("VICTORIA_LOGS_TIMEOUT", "3.0"))
    VICTORIA_LOGS_QUEUE_SIZE = int(os.getenv("VICTORIA_LOGS_QUEUE_SIZE", "10000"))
    
    # ---------- 測試 ----------
    TESTING = IS_TESTING
    USE_MOCK_LLM = IS_TESTING
    USE_MOCK_EMOTION = IS_TESTING

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def validate(cls) -> Tuple[bool, List[str]]:
        """驗證配置有效性"""
        errors = []
        
        # 驗證 LLM 服務配置
        services_valid, service_errors = AIServiceRegistry.validate_all()
        if not services_valid:
            errors.extend(service_errors)
        
        # 驗證生產環境安全性
        if IS_PRODUCTION or IS_STAGING:
            if len(cls.JWT_SECRET) < 32 or cls.JWT_SECRET.startswith("dev_"):
                errors.append("Invalid JWT_SECRET for production")
            if len(cls.API_KEY) < 32 or cls.API_KEY.startswith("dev_"):
                errors.append("Invalid API_KEY for production")
            if not cls.DB_PASSWORD:
                errors.append("DB_PASSWORD is required in production")
        
        # 驗證 LLM URL
        llm_urls = [
            ("MAIN_LLM_URL", cls.MAIN_LLM_URL),
            ("REVISE_LLM_URL", cls.REVISE_LLM_URL),
            ("LOGIC_LLM_URL", cls.LOGIC_LLM_URL),
            ("MEMORY_LLM_URL", cls.MEMORY_LLM_URL),
            ("EMOBLOOM_LLM_URL", cls.EMOBLOOM_LLM_URL),
        ]
        
        for url_name, url_value in llm_urls:
            if not url_value:
                errors.append(f"{url_name} is empty")
            elif not url_value.startswith("http"):
                errors.append(f"{url_name} must start with http: {url_value}")
        
        return len(errors) == 0, errors

    @classmethod
    def get_llm_service_url(cls, service_id: str) -> Optional[str]:
        """獲取特定 LLM 服務的 URL"""
        url_map = {
            'main_llm': cls.MAIN_LLM_URL,
            'revise_llm': cls.REVISE_LLM_URL,
            'logic_llm': cls.LOGIC_LLM_URL,
            'memory_llm': cls.MEMORY_LLM_URL,
            'emobloom_llm': cls.EMOBLOOM_LLM_URL,
            # deprecated service_id alias
            'critic_llm': cls.REVISE_LLM_URL,
        }
        return url_map.get(service_id)
    
    @classmethod
    def get_llm_service_timeout(cls, service_id: str) -> Optional[float]:
        """獲取特定 LLM 服務的超時時間"""
        timeout_map = {
            'main_llm': cls.MAIN_LLM_TIMEOUT,
            'revise_llm': cls.REVISE_LLM_TIMEOUT,
            'logic_llm': cls.LOGIC_LLM_TIMEOUT,
            'memory_llm': cls.MEMORY_LLM_TIMEOUT,
            'emobloom_llm': cls.EMOBLOOM_LLM_TIMEOUT,
            'critic_llm': cls.REVISE_LLM_TIMEOUT,
        }
        return timeout_map.get(service_id)
    
    @classmethod
    def get_llm_service_model(cls, service_id: str) -> Optional[str]:
        """獲取特定 LLM 服務的模型名稱"""
        model_map = {
            'main_llm': cls.MAIN_LLM_MODEL,
            'revise_llm': cls.REVISE_LLM_MODEL,
            'logic_llm': cls.LOGIC_LLM_MODEL,
            'memory_llm': cls.MEMORY_LLM_MODEL,
            'emobloom_llm': cls.EMOBLOOM_LLM_MODEL,
            'critic_llm': cls.REVISE_LLM_MODEL,
        }
        return model_map.get(service_id)

    @classmethod
    def get_startup_llm_services(cls) -> Dict[str, str]:
        """啟動健康檢查標籤 -> URL（職責標籤與 env 變數對齊）"""
        url_by_service = {
            'main_llm': cls.MAIN_LLM_URL,
            'revise_llm': cls.REVISE_LLM_URL,
            'logic_llm': cls.LOGIC_LLM_URL,
            'memory_llm': cls.MEMORY_LLM_URL,
            'emobloom_llm': cls.EMOBLOOM_LLM_URL,
        }
        ordered = sorted(AIServiceRegistry.SERVICES.values(), key=lambda s: s.port)
        return {svc.startup_label: url_by_service[svc.service_id] for svc in ordered}

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        """返回配置字典"""
        return {
            k: v for k, v in cls.__dict__.items()
            if not k.startswith('_') and not callable(v)
        }

    @classmethod
    def log_config_summary(cls) -> None:
        """記錄配置摘要"""
        logger.info(f"Environment: {cls.ENV}")
        logger.info(f"Running in Docker: {cls.IS_DOCKER}")
        logger.info(f"Debug Mode: {cls.DEBUG}")
        logger.info(f"Database: {cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}")
        logger.info(f"Redis: {logger.mask_sensitive_url(cls.REDIS_URL)}")
        logger.info("LLM Services:")
        logger.info(f"  - MAIN_LLM: {cls.MAIN_LLM_URL} (Timeout: {cls.MAIN_LLM_TIMEOUT}s)")
        logger.info(
            f"  - REVISE_LLM: {cls.REVISE_LLM_URL} "
            f"(Timeout: {cls.REVISE_LLM_TIMEOUT}s)"
        )
        logger.info(f"  - LOGIC_LLM: {cls.LOGIC_LLM_URL} (Timeout: {cls.LOGIC_LLM_TIMEOUT}s)")
        logger.info(f"  - MEMORY_LLM: {cls.MEMORY_LLM_URL} (Timeout: {cls.MEMORY_LLM_TIMEOUT}s)")
        logger.info(f"  - EMOBLOOM_LLM: {cls.EMOBLOOM_LLM_URL} (Timeout: {cls.EMOBLOOM_LLM_TIMEOUT}s)")

config = Config()

# 驗證配置
_config_valid, _config_errors = config.validate()
if not _config_valid:
    logger.error("Configuration validation failed:")
    for error in _config_errors:
        logger.error(f"  - {error}")
    if IS_PRODUCTION or IS_STAGING:
        sys.exit(1)
else:
    logger.info("Configuration validation passed")

# 記錄配置摘要
if IS_DEVELOPMENT:
    config.log_config_summary()

__all__ = [
    'config',
    'Config',
    'AIServiceRegistry',
    'LLMServiceConfig',
    'CURRENT_ENV',
    'IS_PRODUCTION',
    'IS_STAGING',
    'IS_TESTING',
    'IS_DEVELOPMENT',
]