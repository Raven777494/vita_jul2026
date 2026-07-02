# app/utils/error_handler.py
# 統一錯誤處理系統 – 優雅降級與重試

import logging
import time
from typing import Callable, Any, Optional, List, Type
from enum import Enum
from dataclasses import dataclass

from app.config import config
from app.logger import get_error_logger, get_critical_logger

error_logger = get_error_logger('errors')
critical_logger = get_critical_logger('critical')

class ErrorSeverity(Enum):
    """錯誤嚴重級別"""
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'

@dataclass
class ErrorContext:
    """錯誤上下文"""
    error_type: str
    error_message: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    severity: ErrorSeverity = ErrorSeverity.ERROR
    retry_count: int = 0
    last_retry_time: Optional[float] = None

class SystemException(Exception):
    """系統基礎異常"""
    
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.ERROR):
        self.message = message
        self.severity = severity
        super().__init__(self.message)

class RedisException(SystemException):
    """Redis 相關異常"""
    pass

class LLMException(SystemException):
    """LLM 相關異常"""
    pass

class DatabaseException(SystemException):
    """數據庫相關異常"""
    pass

class LLMTimeoutException(LLMException):
    """LLM 超時異常"""
    pass

class LLMContentException(LLMException):
    """LLM 回應不安全異常"""
    pass

class ErrorHandler:
    """
    統一錯誤處理器
    
    職責：
    1. 分類錯誤（Redis/LLM/DB）
    2. 決定 fallback 策略
    3. 實現重試邏輯
    4. 記錄錯誤日誌
    """
    
    def __init__(self):
        """初始化"""
        self.error_log = {}
    
    def handle_redis_error(
        self,
        error: Exception,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> dict:
        """
        處理 Redis 錯誤
        
        降級策略：使用內存快取或 DB
        
        Returns:
            dict: 降級回應
        """
        context = ErrorContext(
            error_type='redis_error',
            error_message=str(error),
            user_id=user_id,
            session_id=session_id,
            severity=ErrorSeverity.WARNING
        )
        
        error_logger.warning(
            f"[REDIS ERROR] {context.error_type}: {context.error_message}"
        )
        
        return {
            'status': 'degraded',
            'fallback': 'memory_cache_or_db',
            'message': '系統正在使用備用模式，請稍候。'
        }
    
    def handle_llm_error(
        self,
        error: Exception,
        model_name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        risk_level: int = 1
    ) -> dict:
        """
        處理 LLM 錯誤
        
        降級策略：
        1. 嘗試 Fallback 模型
        2. 如果全部失敗，返回預設安全回應
        
        Args:
            error: 異常
            model_name: 失敗的模型名稱
            user_id: 用戶 ID
            session_id: 會話 ID
            risk_level: 當前風險級別
        
        Returns:
            dict: 降級回應
        """
        context = ErrorContext(
            error_type='llm_error',
            error_message=str(error),
            user_id=user_id,
            session_id=session_id,
            severity=ErrorSeverity.ERROR
        )
        
        error_logger.error(
            f"[LLM ERROR] Model: {model_name}, Error: {context.error_message}"
        )
        
        # 根據風險級別選擇預設回應
        if risk_level >= 4:
            default_response = config.DEFAULT_SAFE_REPLIES['high_risk']
        elif risk_level >= 2:
            default_response = config.DEFAULT_SAFE_REPLIES['medium_risk']
        else:
            default_response = config.DEFAULT_SAFE_REPLIES['low_risk']
        
        return {
            'status': 'fallback',
            'fallback': 'default_response',
            'message': default_response,
            'model_failed': model_name
        }
    
    def handle_database_error(
        self,
        error: Exception,
        operation: str,
        user_id: Optional[str] = None
    ) -> dict:
        """
        處理數據庫錯誤
        
        降級策略：跳過 DB 操作，繼續服務
        
        Args:
            error: 異常
            operation: 操作名稱
            user_id: 用戶 ID
        
        Returns:
            dict: 降級回應
        """
        context = ErrorContext(
            error_type='database_error',
            error_message=str(error),
            user_id=user_id,
            severity=ErrorSeverity.WARNING
        )
        
        error_logger.warning(
            f"[DB ERROR] Operation: {operation}, Error: {context.error_message}"
        )
        
        return {
            'status': 'degraded',
            'fallback': 'skip_persistence',
            'message': '系統將在恢復後同步數據。'
        }
    
    def retry_with_backoff(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        max_attempts: int = None,
        backoff_delays: Optional[List[float]] = None,
        exception_types: tuple = (Exception,)
    ) -> Any:
        """
        帶 exponential backoff 的重試
        
        Args:
            func: 待重試函數
            args: 位置參數
            kwargs: 關鍵字參數
            max_attempts: 最多嘗試次數
            backoff_delays: 延遲列表（秒）
            exception_types: 捕獲的異常類型
        
        Returns:
            Any: 函數返回值
        
        Raises:
            Exception: 所有重試失敗時拋出
        """
        kwargs = kwargs or {}
        max_attempts = max_attempts or getattr(config, 'RETRY_ATTEMPTS', 3)
        backoff_delays = backoff_delays or getattr(config, 'RETRY_BACKOFF', {'first': 1, 'second': 3, 'third': 5})
        
        last_exception = None
        
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            
            except exception_types as e:
                last_exception = e
                
                if attempt < max_attempts - 1:
                    delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                    error_logger.warning(
                        f"[RETRY] 嘗試 {attempt + 1}/{max_attempts} 失敗, "
                        f"等待 {delay}秒: {str(e)}"
                    )
                    time.sleep(delay)
                else:
                    error_logger.error(
                        f"[RETRY] 全部 {max_attempts} 次嘗試均失敗: {str(e)}"
                    )
        
        raise last_exception
    
    def get_safe_response_for_risk_level(self, risk_level: int) -> str:
        """
        根據風險級別獲取預設安全回應
        
        Args:
            risk_level: 風險級別（1-5）
        
        Returns:
            str: 預設回應
        """
        if risk_level >= 4:
            return config.DEFAULT_SAFE_REPLIES.get(
                'high_risk',
                '寶貝，我聽到你，我陪著你。'
            )
        elif risk_level >= 2:
            return config.DEFAULT_SAFE_REPLIES.get(
                'medium_risk',
                '我喺度陪你。'
            )
        else:
            return config.DEFAULT_SAFE_REPLIES.get(
                'low_risk',
                '寶貝，我喺度。'
            )
    
    def log_error_context(
        self,
        context: ErrorContext,
        additional_info: dict = None
    ):
        """
        記錄詳細的錯誤上下文
        
        Args:
            context: 錯誤上下文
            additional_info: 額外信息
        """
        log_entry = {
            'error_type': context.error_type,
            'error_message': context.error_message,
            'user_id': context.user_id,
            'session_id': context.session_id,
            'severity': context.severity.value,
            'retry_count': context.retry_count,
            'timestamp': time.time(),
            'additional_info': additional_info or {}
        }
        
        if context.severity == ErrorSeverity.CRITICAL:
            critical_logger.critical(str(log_entry))
        elif context.severity == ErrorSeverity.ERROR:
            error_logger.error(str(log_entry))
        else:
            error_logger.warning(str(log_entry))

# 全局錯誤處理實例
error_handler = ErrorHandler()