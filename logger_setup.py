# app.logger.py
# 統一日誌配置系統 – 分層日誌（public/private/critical）

import logging
import json
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import sys

# 日誌根目錄 (強制指定)
LOGS_DIR = Path("D:/Desktop/engine7b/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# 日誌檔案路徑
LOG_FILES = {
    'public': LOGS_DIR / "public.log",
    'private': LOGS_DIR / "private.log",
    'critical': LOGS_DIR / "critical.log",
    'app': LOGS_DIR / "app.log",
    'audit': LOGS_DIR / "audit.log",
    'error': LOGS_DIR / "error.log",
    'health': LOGS_DIR / "health.log"
}

# 日誌級別映射
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

class JSONFormatter(logging.Formatter):
    """JSON 格式化器 – 便於機器解析"""
    
    def format(self, record):
        log_obj = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # 如果有異常，加入追蹤
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj, ensure_ascii=False)

class PlainTextFormatter(logging.Formatter):
    """純文本格式化器 – 人類可讀"""
    
    def format(self, record):
        return f"[{record.levelname}] {record.name} - {record.getMessage()}"

def setup_logger(
    name: str,
    log_type: str = 'app',
    level: str = 'INFO',
    use_json: bool = False,
    max_bytes: int = 10485760,  # 10 MB
    backup_count: int = 30
) -> logging.Logger:
    """
    設置單個日誌器
    """
    logger = logging.getLogger(name)
    
    # 避免重複處理
    if logger.handlers:
        return logger
    
    logger.setLevel(LOG_LEVELS.get(level, logging.INFO))
    
    # 獲取日誌文件路徑
    log_file = LOG_FILES.get(log_type, LOG_FILES['app'])
    
    # 選擇格式化器
    formatter = JSONFormatter() if use_json else PlainTextFormatter()
    
    # 文件處理器（輪轉）
    try:
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(LOG_LEVELS.get(level, logging.INFO))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[ERROR] 無法創建文件處理器: {e}")
    
    # 控制台處理器（僅開發/測試）
    try:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(LOG_LEVELS.get(level, logging.INFO))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    except Exception as e:
        print(f"[ERROR] 無法創建控制台處理器: {e}")
    
    # 防止日誌傳播到根日誌器（避免重複）
    logger.propagate = False
    
    return logger

# ============ 分層日誌便利函數 ============

def get_public_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'public', level='INFO', use_json=True)

def get_private_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'private', level='INFO', use_json=True)

def get_critical_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'critical', level='WARNING', use_json=True)

def get_app_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'app', level='DEBUG', use_json=False)

def get_audit_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'audit', level='INFO', use_json=True)

def get_error_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'error', level='ERROR', use_json=False)

def get_health_logger(name: str) -> logging.Logger:
    return setup_logger(name, 'health', level='INFO', use_json=True)

# ============ 臨床會話專用日誌函數 ============

def log_session_event(
    logger: logging.Logger,
    event_type: str,
    user_id: str,
    session_id: str,
    details: Dict[str, Any],
    level: str = 'INFO'
):
    event = {
        'event_type': event_type,
        'user_id': user_id,
        'session_id': session_id,
        'timestamp': datetime.now().isoformat(),
        **details
    }
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(json.dumps(event, ensure_ascii=False))

def log_risk_escalation(
    logger: logging.Logger,
    user_id: str,
    session_id: str,
    risk_level: int,
    escalation_reason: str,
    escalated_to: str
):
    escalation_event = {
        'event_type': 'risk_escalation',
        'user_id': user_id,
        'session_id': session_id,
        'risk_level': risk_level,
        'escalation_reason': escalation_reason,
        'escalated_to': escalated_to,
        'timestamp': datetime.now().isoformat()
    }
    
    logger.critical(json.dumps(escalation_event, ensure_ascii=False))
