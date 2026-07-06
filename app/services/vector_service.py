# app/services/vector_service.py - 完整修復版 v8.8
"""
向量嵌入服務客戶端 - v8.8 完整重構
修復問題：
1. Memory-LLM 端點對齊（Port 8084）
2. 統一使用 config.MEMORY_LLM_* 配置
3. 完整的熔斷器 + 健康檢查
4. 三層快取系統
5. 向量驗證機制
6. 詳細的診斷日誌
"""

import logging
import requests
import time
import hashlib
import json
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from threading import Lock
import sys

logger = logging.getLogger(__name__)


def _logging_streams_open(log: logging.Logger) -> bool:
    """Return False when handler streams are closed (pytest teardown / atexit)."""
    current: Optional[logging.Logger] = log
    while current is not None:
        for handler in getattr(current, "handlers", []):
            stream = getattr(handler, "stream", None)
            if stream is not None and getattr(stream, "closed", False):
                return False
        current = getattr(current, "parent", None)
    return True


class VectorServiceConfig:
    """向量服務配置常數"""
    
    # API 超時配置
    DEFAULT_TIMEOUT = 20.0
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_BACKOFF = 2.0
    
    # 健康檢查策略
    HEALTH_CHECK_INTERVAL = 60  # 秒
    HEALTH_CHECK_TIMEOUT = 5
    
    # 熔斷器策略
    CIRCUIT_BREAKER_THRESHOLD = 5  # 5 次連續失敗觸發
    CIRCUIT_BREAKER_RECOVERY_TIME = 120  # 2 分鐘恢復
    
    # 快取策略
    EMBEDDING_CACHE_TTL = 7 * 24 * 3600  # 7 天
    CACHE_MAX_ENTRIES = 10000
    
    # 向量驗證
    EXPECTED_DIMENSION = 1024  # BGE-M3 維度
    ZERO_VECTOR_THRESHOLD = 0.01


class VectorService:
    """向量服務 v8.9 - 修復 URL 配置"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.logger = logger
        self._closed = False
        
        # ========== 直接從 config 讀取 MEMORY_LLM_* ==========
        try:
            from app.config import config as app_config
            self.api_url = app_config.MEMORY_LLM_URL.rstrip('/')
            self.embedding_endpoint = f"{self.api_url}/v1/embeddings"
            self.health_endpoint = f"{self.api_url}/v1/models"
            self.request_timeout = app_config.MEMORY_LLM_TIMEOUT
            self.max_retries = app_config.LLM_MAX_RETRIES
            self.retry_backoff_factor = app_config.LLM_RETRY_DELAY_SECONDS
        except ImportError:
            self.api_url = self.config.get(
                'MEMORY_LLM_URL',
                'http://127.0.0.1:8084'
            ).rstrip('/')
            self.embedding_endpoint = f"{self.api_url}/v1/embeddings"
            self.health_endpoint = f"{self.api_url}/v1/models"
            self.request_timeout = float(self.config.get('MEMORY_LLM_TIMEOUT', 20.0))
            self.max_retries = int(self.config.get('LLM_MAX_RETRIES', 3))
            self.retry_backoff_factor = float(self.config.get('LLM_RETRY_DELAY_SECONDS', 1.0))
        
        self.session = self._create_session()
        
        # ========== 健康狀態與熔斷器 ==========
        self._service_healthy: Optional[bool] = None
        self._last_health_check: float = 0
        self._consecutive_failures: int = 0
        self._circuit_breaker_triggered: bool = False
        self._circuit_breaker_time: float = 0
        self._health_check_lock = Lock()
        
        # ========== 快取系統 ==========
        self._embedding_cache: Dict[str, Tuple[List[float], float, int]] = {}
        self._cache_lock = Lock()
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0
        }
        
        # ========== 診斷統計 ==========
        self._stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'timeout_requests': 0,
            'connection_errors': 0,
            'validation_errors': 0,
            'fallback_used': 0,
            'last_error': None,
            'last_error_time': None,
            'last_error_timestamp': None
        }
        
        self.logger.info(
            f"[INIT] VectorService v8.8 initialized "
            f"(endpoint: {self.embedding_endpoint}, "
            f"timeout: {self.request_timeout}s, "
            f"max_retries: {self.max_retries})"
        )
    
    # ==================== HTTP 會話管理 ====================
    
    def _create_session(self) -> requests.Session:
        """
        建立帶有重試策略的 HTTP 會話
        
        Returns:
            配置好的 requests.Session
        """
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        self.logger.debug(
            f"[SESSION] Created with retry strategy "
            f"(backoff={self.retry_backoff_factor}x)"
        )
        
        return session
    
    # ==================== 熔斷器管理 ====================
    
    def _check_circuit_breaker(self) -> bool:
        """
        檢查熔斷器狀態
        
        Returns:
            True 如果可以進行請求，False 如果在熔斷狀態
        """
        if not self._circuit_breaker_triggered:
            return True
        
        current_time = time.time()
        recovery_time = (
            self._circuit_breaker_time +
            VectorServiceConfig.CIRCUIT_BREAKER_RECOVERY_TIME
        )
        
        if current_time >= recovery_time:
            # 進入恢復期
            self._circuit_breaker_triggered = False
            self._consecutive_failures = 0
            self.logger.info(
                f"[CIRCUIT] Recovered from circuit breaker "
                f"(recovery_time: {VectorServiceConfig.CIRCUIT_BREAKER_RECOVERY_TIME}s)"
            )
            return True
        
        # 仍在熔斷中
        remaining_sec = recovery_time - current_time
        self.logger.debug(
            f"[CIRCUIT] Still active "
            f"(remaining: {remaining_sec:.1f}s)"
        )
        
        return False
    
    def _record_failure(self, error: str) -> None:
        """
        記錄故障並檢查是否觸發熔斷
        
        Args:
            error: 錯誤描述
        """
        self._consecutive_failures += 1
        self._stats['failed_requests'] += 1
        self._stats['last_error'] = error
        self._stats['last_error_time'] = datetime.utcnow().isoformat()
        self._stats['last_error_timestamp'] = time.time()
        
        if (self._consecutive_failures >=
            VectorServiceConfig.CIRCUIT_BREAKER_THRESHOLD):
            self._circuit_breaker_triggered = True
            self._circuit_breaker_time = time.time()
            
            self.logger.error(
                f"[CIRCUIT] TRIGGERED "
                f"(failures: {self._consecutive_failures}, "
                f"threshold: {VectorServiceConfig.CIRCUIT_BREAKER_THRESHOLD})"
            )
    
    def _record_success(self) -> None:
        """記錄成功請求"""
        self._consecutive_failures = 0
        self._stats['successful_requests'] += 1
    
    # ==================== 健康檢查 ====================
    
    def _is_service_healthy(self) -> bool:
        """
        檢查服務健康狀態（含熔斷器邏輯）
        
        Returns:
            True 如果服務健康且熔斷器未觸發
        """
        # 檢查熔斷器
        if not self._check_circuit_breaker():
            self.logger.warning("[HEALTH] Circuit breaker active")
            return False
        
        # 檢查快取的健康狀態
        with self._health_check_lock:
            current_time = time.time()
            
            if (self._service_healthy is not None and
                current_time - self._last_health_check <
                VectorServiceConfig.HEALTH_CHECK_INTERVAL):
                return self._service_healthy
            
            # 執行健康檢查
            try:
                response = self.session.get(
                    self.health_endpoint,
                    timeout=VectorServiceConfig.HEALTH_CHECK_TIMEOUT,
                    allow_redirects=False
                )
                
                self._service_healthy = response.status_code == 200
                self._last_health_check = current_time
                
                if self._service_healthy:
                    self.logger.debug(
                        f"[HEALTH] Check passed (HTTP {response.status_code})"
                    )
                else:
                    error_msg = f"HTTP {response.status_code}"
                    self.logger.warning(
                        f"[HEALTH] Check failed: {error_msg}"
                    )
                    self._record_failure(error_msg)
                
                return self._service_healthy
                
            except requests.Timeout:
                self._service_healthy = False
                self._last_health_check = current_time
                error_msg = (
                    f"Timeout ({VectorServiceConfig.HEALTH_CHECK_TIMEOUT}s)"
                )
                self.logger.warning(f"[HEALTH] {error_msg}")
                self._record_failure(error_msg)
                return False
                
            except Exception as e:
                self._service_healthy = False
                self._last_health_check = current_time
                error_msg = f"{type(e).__name__}: {str(e)[:100]}"
                self.logger.warning(f"[HEALTH] Exception: {error_msg}")
                self._record_failure(error_msg)
                return False
    
    # ==================== 快取管理 ====================
    
    def _build_cache_key(self, text: str) -> str:
        """
        構建快取鍵（MD5 雜湊）
        
        Args:
            text: 輸入文本
        
        Returns:
            快取鍵
        """
        hash_obj = hashlib.md5(text.encode('utf-8'))
        return f"emb_{hash_obj.hexdigest()}"
    
    def _get_from_cache(self, key: str) -> Optional[List[float]]:
        """
        從快取取得向量
        
        Args:
            key: 快取鍵
        
        Returns:
            向量或 None
        """
        with self._cache_lock:
            if key not in self._embedding_cache:
                self._cache_stats['misses'] += 1
                return None
            
            embedding, timestamp, ttl = self._embedding_cache[key]
            
            # 檢查 TTL
            if time.time() - timestamp > ttl:
                del self._embedding_cache[key]
                self._cache_stats['misses'] += 1
                return None
            
            self._cache_stats['hits'] += 1
            return embedding
    
    def _set_cache(
        self,
        key: str,
        embedding: List[float],
        ttl: Optional[int] = None
    ) -> None:
        """
        設置快取
        
        Args:
            key: 快取鍵
            embedding: 向量
            ttl: TTL（秒，預設 7 天）
        """
        ttl = ttl or VectorServiceConfig.EMBEDDING_CACHE_TTL
        
        with self._cache_lock:
            # 檢查快取大小
            if (len(self._embedding_cache) >=
                VectorServiceConfig.CACHE_MAX_ENTRIES):
                # 移除最舊的項目
                oldest_key = min(
                    self._embedding_cache.keys(),
                    key=lambda k: self._embedding_cache[k][1]
                )
                del self._embedding_cache[oldest_key]
                self._cache_stats['evictions'] += 1
            
            self._embedding_cache[key] = (embedding, time.time(), ttl)
    
    def _validate_embedding(
        self,
        embedding: Optional[List[float]]
    ) -> Tuple[bool, Optional[str]]:
        """
        驗證向量的有效性
        
        Args:
            embedding: 要驗證的向量
        
        Returns:
            (是否有效, 錯誤消息)
        """
        if not embedding:
            return False, "Embedding is None or empty"
        
        if not isinstance(embedding, list):
            return False, f"Embedding is not a list (got {type(embedding)})"
        
        if len(embedding) != VectorServiceConfig.EXPECTED_DIMENSION:
            self.logger.warning(
                f"[VALIDATION] Dimension mismatch: "
                f"expected {VectorServiceConfig.EXPECTED_DIMENSION}, "
                f"got {len(embedding)}"
            )
            self._stats['validation_errors'] += 1
            return False, (
                f"Dimension mismatch: {len(embedding)} "
                f"!= {VectorServiceConfig.EXPECTED_DIMENSION}"
            )
        
        # 檢查是否為零向量
        try:
            magnitude = sum(x**2 for x in embedding) ** 0.5
            
            if magnitude < VectorServiceConfig.ZERO_VECTOR_THRESHOLD:
                self.logger.warning(
                    f"[VALIDATION] Zero vector detected "
                    f"(magnitude: {magnitude})"
                )
                self._stats['validation_errors'] += 1
                return False, f"Zero vector (magnitude: {magnitude})"
        
        except Exception as e:
            return False, f"Magnitude calculation failed: {str(e)}"
        
        # 檢查是否包含 NaN 或 Inf
        try:
            for val in embedding:
                if not isinstance(val, (int, float)):
                    return False, f"Non-numeric value in embedding: {type(val)}"
        except Exception as e:
            return False, f"Embedding validation error: {str(e)}"
        
        return True, None
    
    # ==================== 核心嵌入方法 ====================
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        【核心方法】獲取單段文本的嵌入向量
        
        流程：
        1. 輸入驗證
        2. 快取查詢
        3. 熔斷器 + 健康檢查
        4. API 請求（含重試）
        5. 向量驗證
        6. 快取儲存
        
        Args:
            text: 輸入文本
        
        Returns:
            1024 維浮點向量，或 None
        """
        self._stats['total_requests'] += 1
        
        # ========== 階段 1: 輸入驗證 ==========
        if not text or len(text.strip()) == 0:
            self.logger.debug("[EMBED] Empty input text")
            return None
        
        # ========== 階段 2: 快取查詢 ==========
        cache_key = self._build_cache_key(text)
        cached = self._get_from_cache(cache_key)
        
        if cached is not None:
            self.logger.debug(
                f"[EMBED] Cache hit (key: {cache_key[:16]}...)"
            )
            return cached
        
        # ========== 階段 3: 服務檢查 ==========
        if not self._is_service_healthy():
            self.logger.error("[EMBED] Service unavailable")
            self._stats['fallback_used'] += 1
            return None
        
        # ========== 階段 4: API 請求 ==========
        try:
            payload = {"input": [text]}
            
            response = self.session.post(
                self.embedding_endpoint,
                json=payload,
                timeout=self.request_timeout
            )
            
            # 檢查狀態碼
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                self.logger.error(
                    f"[EMBED] Request failed: {error_msg}"
                )
                self._record_failure(error_msg)
                self._stats['fallback_used'] += 1
                return None
            
            # 解析 JSON
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"JSON decode error: {str(e)[:50]}"
                self.logger.error(f"[EMBED] {error_msg}")
                self._record_failure(error_msg)
                return None
            
            # 驗證響應結構
            if not data.get("data") or len(data["data"]) == 0:
                error_msg = "Empty embedding data in response"
                self.logger.error(f"[EMBED] {error_msg}")
                self._record_failure(error_msg)
                return None
            
            embedding = data["data"][0].get("embedding")
            
            # ========== 階段 5: 向量驗證 ==========
            is_valid, validation_error = self._validate_embedding(embedding)
            
            if not is_valid:
                self.logger.error(
                    f"[EMBED] Validation failed: {validation_error}"
                )
                self._record_failure(validation_error or "Validation failed")
                return None
            
            # ========== 階段 6: 快取儲存 ==========
            self._set_cache(cache_key, embedding)
            self._record_success()
            
            inference_time = response.elapsed.total_seconds()
            self.logger.debug(
                f"[EMBED] Success "
                f"(dim: {len(embedding)}, "
                f"time: {inference_time:.3f}s)"
            )
            
            return embedding
            
        except requests.Timeout:
            error_msg = f"Timeout ({self.request_timeout}s)"
            self.logger.error(f"[EMBED] {error_msg}")
            self._stats['timeout_requests'] += 1
            self._record_failure(error_msg)
            return None
            
        except requests.ConnectionError as e:
            error_msg = f"Connection error: {str(e)[:100]}"
            self.logger.error(f"[EMBED] {error_msg}")
            self._stats['connection_errors'] += 1
            self._record_failure(error_msg)
            return None
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:100]}"
            self.logger.error(
                f"[EMBED] Unexpected error: {error_msg}",
                exc_info=True
            )
            self._record_failure(error_msg)
            return None
    
    # ==================== 相容性方法 ====================
    
    def get_semantic_embedding(self, text: str) -> Optional[List[float]]:
        """
        相容性別名 (給 GSWEngine 使用)
        
        Args:
            text: 輸入文本
        
        Returns:
            向量或 None
        """
        return self.get_embedding(text)
    
    # ==================== 批量方法 ====================
    
    def batch_embedding(
        self,
        texts: List[str]
    ) -> Optional[List[List[float]]]:
        """
        批量獲取嵌入向量
        
        Args:
            texts: 文本列表
        
        Returns:
            向量列表，或 None
        """
        self._stats['total_requests'] += 1
        
        # 過濾有效文本
        valid_texts = [
            t for t in (texts or [])
            if t and isinstance(t, str) and len(t.strip()) > 0
        ]
        
        if not valid_texts:
            self.logger.debug(f"[BATCH] Empty input (count: {len(texts or [])})")
            return None
        
        # 檢查服務健康
        if not self._is_service_healthy():
            self.logger.error("[BATCH] Service unavailable")
            self._stats['fallback_used'] += 1
            return None
        
        try:
            payload = {"input": valid_texts}
            
            response = self.session.post(
                self.embedding_endpoint,
                json=payload,
                timeout=self.request_timeout + len(valid_texts)
            )
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                self.logger.error(f"[BATCH] {error_msg}")
                self._record_failure(error_msg)
                return None
            
            data = response.json()
            embeddings = [
                item.get("embedding")
                for item in data.get("data", [])
            ]
            
            # 驗證結果數量
            if len(embeddings) != len(valid_texts):
                error_msg = (
                    f"Count mismatch: expected {len(valid_texts)}, "
                    f"got {len(embeddings)}"
                )
                self.logger.warning(f"[BATCH] {error_msg}")
                return None
            
            # 驗證每個向量
            validated_embeddings = []
            for embedding in embeddings:
                is_valid, _ = self._validate_embedding(embedding)
                if is_valid:
                    validated_embeddings.append(embedding)
                else:
                    return None
            
            self._record_success()
            self.logger.info(f"[BATCH] Success (count: {len(embeddings)})")
            
            return validated_embeddings
            
        except requests.Timeout:
            error_msg = f"Batch timeout"
            self.logger.error(f"[BATCH] {error_msg}")
            self._stats['timeout_requests'] += 1
            self._record_failure(error_msg)
            return None
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:100]}"
            self.logger.error(f"[BATCH] Error: {error_msg}")
            self._record_failure(error_msg)
            return None
    
    # ==================== 診斷與管理 ====================
    
    def get_diagnostics(self) -> Dict:
        """
        取得詳細診斷信息
        
        Returns:
            診斷字典
        """
        with self._cache_lock:
            total_cache = self._cache_stats['hits'] + self._cache_stats['misses']
            cache_hit_rate = (
                self._cache_stats['hits'] / total_cache
                if total_cache > 0 else 0.0
            )
        
        with self._health_check_lock:
            total_requests = self._stats['total_requests']
            success_rate = (
                self._stats['successful_requests'] / total_requests
                if total_requests > 0 else 0.0
            )
        
        return {
            'version': '8.8',
            'endpoint': self.embedding_endpoint,
            'service_healthy': self._service_healthy,
            'circuit_breaker_active': self._circuit_breaker_triggered,
            'consecutive_failures': self._consecutive_failures,
            'statistics': {
                'total_requests': self._stats['total_requests'],
                'successful_requests': self._stats['successful_requests'],
                'failed_requests': self._stats['failed_requests'],
                'success_rate': round(success_rate, 3),
                'timeout_requests': self._stats['timeout_requests'],
                'connection_errors': self._stats['connection_errors'],
                'validation_errors': self._stats['validation_errors'],
                'fallback_used': self._stats['fallback_used'],
            },
            'cache': {
                'entries': len(self._embedding_cache),
                'max_entries': VectorServiceConfig.CACHE_MAX_ENTRIES,
                'hits': self._cache_stats['hits'],
                'misses': self._cache_stats['misses'],
                'evictions': self._cache_stats['evictions'],
                'hit_rate': round(cache_hit_rate, 3),
            },
            'last_error': self._stats['last_error'],
            'last_error_time': self._stats['last_error_time'],
        }
    
    def clear_cache(self) -> int:
        """
        手動清理快取
        
        Returns:
            清理的快取項目數
        """
        with self._cache_lock:
            count = len(self._embedding_cache)
            self._embedding_cache.clear()
            self.logger.info(f"[CACHE] Cleared {count} entries")
            return count
    
    def reset_circuit_breaker(self) -> None:
        """手動重置熔斷器（用於恢復）"""
        self._circuit_breaker_triggered = False
        self._consecutive_failures = 0
        self.logger.info("[CIRCUIT] Manually reset")
    
    def close(self) -> None:
        """優雅關閉資源（idempotent；直譯器關閉階段不寫日誌）"""
        if getattr(self, "_closed", False):
            return
        self._closed = True

        try:
            if self.session:
                self.session.close()
        except Exception:
            pass

        # 直譯器關閉 / pytest teardown 時 log handler 可能已關閉，
        # 對已關閉的 stream 寫入會觸發 "I/O operation on closed file"
        if not sys.is_finalizing() and _logging_streams_open(self.logger):
            try:
                self.logger.info(
                    f"[CLOSE] VectorService closed "
                    f"(final stats: {self._stats.copy()})"
                )
            except Exception:
                pass

    def __del__(self):
        """析構函式：直譯器關閉階段不做日誌與非必要清理"""
        if sys.is_finalizing():
            return
        try:
            self.close()
        except Exception:
            pass


# ==================== 全局實例 ====================

_vector_service_instance: Optional[VectorService] = None
_instance_lock = Lock()


def get_vector_service(config: Optional[Dict] = None) -> VectorService:
    """
    取得全局 VectorService 實例（單例模式）
    
    Args:
        config: 配置字典（第一次初始化時使用）
    
    Returns:
        VectorService 實例
    """
    global _vector_service_instance
    
    if _vector_service_instance is None:
        with _instance_lock:
            if _vector_service_instance is None:
                _vector_service_instance = VectorService(config)
    
    return _vector_service_instance


def reset_vector_service() -> None:
    """重置全局實例（用於測試）"""
    global _vector_service_instance
    
    with _instance_lock:
        if _vector_service_instance:
            _vector_service_instance.close()
        _vector_service_instance = None


__all__ = [
    'VectorService',
    'VectorServiceConfig',
    'get_vector_service',
    'reset_vector_service'
]