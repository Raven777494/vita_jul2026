# vita_core_config.py - 系統配置統一層

"""

Vita 核心系統配置 - 統一管理所有超時、資源、模型配置

LLM 端點使用 MAIN/REVISE/LOGIC/MEMORY/EMOBLOOM_LLM_* 命名

"""



import os

from dataclasses import dataclass

from pathlib import Path

from typing import Dict





def _resolve_llm_env(primary_key: str, legacy_key: str, default: str) -> str:

    primary = os.getenv(primary_key)

    if primary:

        return primary

    legacy = os.getenv(legacy_key)

    if legacy:

        return legacy

    return default





@dataclass

class TimeoutConfig:

    """統一超時配置（秒）"""

    EMBEDDING: float = 5.0

    MEMORY_SEARCH: float = 4.0

    DRIFT_DETECTION: float = 6.0

    ISLAND_ACTIVATION: float = 5.0

    NAVIGATION: float = 5.0

    BUTTERFLY_EFFECT: float = 6.0

    HERETIC_COORDINATION: float = 8.0

    VECTOR_SHIFT: float = 6.0

    WEAVING: float = 2.0

    EMOTION_ANALYSIS: float = 3.0

    LLM_GENERATION: float = 30.0

    MAIN_LLM: float = 30.0

    REVISE_LLM: float = 10.0

    LOGIC_LLM: float = 15.0





@dataclass

class MemoryConfig:

    """統一記憶配置"""

    CORE_MEMORY_MAX: int = 1000

    ECHO_MEMORY_MAX: int = 5000

    CONTEXT_WINDOW_SIZE: int = 20

    SESSION_HISTORY_SIZE: int = 100

    MEMORY_DECAY_FACTOR: float = 0.95

    MEMORY_REFRESH_INTERVAL_HOURS: int = 24





@dataclass

class PerformanceConfig:

    """性能優化配置"""

    ENABLE_RESPONSE_CACHE: bool = True

    ENABLE_EMBEDDING_CACHE: bool = True

    ENABLE_MEMORY_POOLING: bool = True

    BATCH_PROCESS_SIZE: int = 10

    BACKGROUND_TASK_POOL_SIZE: int = 4

    VECTOR_BATCH_SIZE: int = 32





@dataclass

class ModelConfig:

    """模型配置統一管理（*_LLM_* 命名）"""

    MAIN_LLM_URL: str = _resolve_llm_env("MAIN_LLM_URL", "MAIN_LLM_URL", "http://127.0.0.1:8081")

    REVISE_LLM_URL: str = _resolve_llm_env("REVISE_LLM_URL", "CRITIC_LLM_URL", "http://127.0.0.1:8082")

    LOGIC_LLM_URL: str = _resolve_llm_env("LOGIC_LLM_URL", "LOGIC_LLM_URL", "http://127.0.0.1:8083")

    MEMORY_LLM_URL: str = _resolve_llm_env("MEMORY_LLM_URL", "MEMORY_LLM_URL", "http://127.0.0.1:8084")

    EMOBLOOM_LLM_URL: str = _resolve_llm_env("EMOBLOOM_LLM_URL", "EMOBLOOM_LLM_URL", "http://127.0.0.1:8085")



    MAIN_LLM_MAX_TOKENS: int = 512

    REVISE_LLM_MAX_TOKENS: int = 1024

    LOGIC_LLM_MAX_TOKENS: int = 1024



    MAIN_LLM_TEMPERATURE: float = 0.6

    REVISE_LLM_TEMPERATURE: float = 0.8

    LOGIC_LLM_TEMPERATURE: float = 0.3



    MAIN_LLM_RETRY_ATTEMPTS: int = 3

    REVISE_LLM_RETRY_ATTEMPTS: int = 2

    LOGIC_LLM_RETRY_ATTEMPTS: int = 2





@dataclass

class ResourcePool:

    """資源池配置"""

    ENABLE_THREAD_POOLING: bool = True

    ENABLE_CONNECTION_POOLING: bool = True

    THREAD_POOL_WORKERS: int = 6

    DB_POOL_SIZE: int = 10

    REDIS_MAX_CONNECTIONS: int = 50





class VitaCoreConfig:

    """Vita 大腦核心統一配置"""



    def __init__(self):

        self.timeout = TimeoutConfig()

        self.memory = MemoryConfig()

        self.performance = PerformanceConfig()

        self.model = ModelConfig()

        self.resource = ResourcePool()



        self.env = os.getenv("ENV", "development")

        self.debug = self.env != "production"

        self.log_dir = Path(os.getenv("LOG_DIR", "./logs"))

        self.data_dir = Path(os.getenv("DATA_DIR", "./data"))



        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        self.redis_prefix = "vita:"



        self.db_url = os.getenv("DATABASE_URL", "postgresql://localhost/vita_db")



    def get_llm_urls(self) -> Dict[str, str]:

        """返回全部 LLM 服務 URL"""

        return {

            'main_llm': self.model.MAIN_LLM_URL,

            'revise_llm': self.model.REVISE_LLM_URL,

            'logic_llm': self.model.LOGIC_LLM_URL,

            'memory_llm': self.model.MEMORY_LLM_URL,

            'emobloom_llm': self.model.EMOBLOOM_LLM_URL,

            'critic_llm': self.model.REVISE_LLM_URL,

        }



    def get_cache_ttl(self, cache_type: str) -> int:

        """獲取快取 TTL"""

        ttl_map = {

            'response': 3600,

            'embedding': 86400,

            'emotion': 300,

            'memory': 7200,

            'session': 3600

        }

        return ttl_map.get(cache_type, 3600)





vita_core_config = VitaCoreConfig()

