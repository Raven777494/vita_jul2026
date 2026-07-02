# app/logger.py
# 統一日誌配置系統 – 結合彩色終端機、JSON 文件存檔、VictoriaLogs 轉送與分層日誌 (Vita 3.0 異步相容完整版)

import atexit
import json
import logging
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional, Set

# 引入 config 獲取動態路徑
from app.config import config

# 自動使用 config.py 中建立好的 logs 資料夾
LOGS_DIR = config.LOGS_DIR

# 日誌檔案路徑總表
LOG_FILES = {
    'public': LOGS_DIR / "public.log",
    'private': LOGS_DIR / "private.log",
    'critical': LOGS_DIR / "critical.log",
    'app': LOGS_DIR / "app.log",
    'audit': LOGS_DIR / "audit.log",
    'error': LOGS_DIR / "error.log",
    'health': LOGS_DIR / "health.log",
    'crisis': LOGS_DIR / "crisis.log",
    'database': LOGS_DIR / "database.log",
    'orchestrator': LOGS_DIR / "orchestrator.log"
}

LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# 敏感日誌類型不轉送至 VictoriaLogs
_VICTORIA_EXCLUDED_LOG_TYPES = frozenset({'private'})

_victoria_ship_handler: Optional["VictoriaLogsShipHandler"] = None
_victoria_attached_loggers: Set[str] = set()
_victoria_lock = threading.Lock()

# ==================== 格式化器 ====================

class JSONFormatter(logging.Formatter):
    """JSON 格式化器 – 用於寫入檔案，便於日後數據分析與追蹤"""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)

class PlainTextFormatter(logging.Formatter):
    """純文本格式化器 – 用於簡單日誌"""

    def format(self, record: logging.LogRecord) -> str:
        return f"[{record.levelname}] {record.name} - {record.getMessage()}"

class ColoredFormatter(logging.Formatter):
    """彩色格式化器 - 用於終端機開發顯示"""
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 綠色
        'WARNING': '\033[33m',    # 黃色
        'ERROR': '\033[31m',      # 紅色
        'CRITICAL': '\033[41m'    # 紅背景
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        log_level = record.levelname
        color = self.COLORS.get(log_level, self.RESET)
        record.levelname = f"{color}{log_level}{self.RESET}"
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)-18s [%(name)s:%(lineno)d] %(message)s',
            datefmt='%H:%M:%S'
        )
        return formatter.format(record)

# ==================== VictoriaLogs Shipper ====================

class LogTypeFilter(logging.Filter):
    """在 LogRecord 上標記 vita_log_type，供 VictoriaLogs 串流分類使用。"""

    def __init__(self, log_type: str) -> None:
        super().__init__()
        self.log_type = log_type

    def filter(self, record: logging.LogRecord) -> bool:
        record.vita_log_type = self.log_type
        return True

class VictoriaLogsShipHandler(logging.Handler):
    """非阻塞 NDJSON shipper，轉送至 VictoriaLogs /insert/jsonline。"""

    def __init__(
        self,
        base_url: str,
        service: str,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        queue_maxsize: int = 10000,
        timeout: float = 3.0,
    ) -> None:
        super().__init__(level=logging.NOTSET)
        self._service = service
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.1, flush_interval)
        self._timeout = max(0.5, timeout)
        self._insert_url = (
            f"{base_url.rstrip('/')}/insert/jsonline"
            f"?_msg_field=message&_time_field=timestamp"
            f"&_stream_fields=service,log_type,logger"
        )
        self._queue: queue.Queue[str] = queue.Queue(maxsize=max(100, queue_maxsize))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._last_error_log = 0.0
        self._error_interval = 60.0
        self._worker = threading.Thread(
            target=self._run,
            name="victoria-logs-shipper",
            daemon=True,
        )
        self._worker.start()

    def emit(self, record: logging.LogRecord) -> None:
        log_type = getattr(record, 'vita_log_type', 'app')
        if log_type in _VICTORIA_EXCLUDED_LOG_TYPES:
            return
        try:
            payload = self._record_to_line(record, log_type)
            self._queue.put_nowait(payload)
            self._wake.set()
        except queue.Full:
            self._maybe_log_error("VictoriaLogs shipper queue full; dropping log line")
        except Exception:
            self.handleError(record)

    def _record_to_line(self, record: logging.LogRecord, log_type: str) -> str:
        log_obj: Dict[str, Any] = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'service': self._service,
            'log_type': log_type,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        if record.exc_info:
            log_obj['exception'] = self.formatter.formatException(record.exc_info) if self.formatter else logging.Formatter().formatException(record.exc_info)
        vita_fields = getattr(record, 'vita_fields', None)
        if isinstance(vita_fields, dict):
            for key, value in vita_fields.items():
                if key not in log_obj and value is not None:
                    log_obj[key] = value
        return json.dumps(log_obj, ensure_ascii=False)

    def _run(self) -> None:
        batch: list[str] = []
        last_flush = time.monotonic()
        while True:
            if self._stop.is_set() and self._queue.empty() and not batch:
                break
            try:
                line = self._queue.get(timeout=0.25)
                batch.append(line)
            except queue.Empty:
                pass
            now = time.monotonic()
            should_flush = (
                bool(batch)
                and (
                    len(batch) >= self._batch_size
                    or now - last_flush >= self._flush_interval
                    or self._stop.is_set()
                )
            )
            if should_flush:
                self._flush_batch(batch)
                batch = []
                last_flush = now
            self._wake.clear()

    def _flush_batch(self, batch: list[str]) -> None:
        if not batch:
            return
        try:
            import httpx
        except ImportError:
            self._maybe_log_error("httpx not installed; VictoriaLogs shipper cannot send logs")
            return
        body = "\n".join(batch) + "\n"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    self._insert_url,
                    content=body.encode("utf-8"),
                    headers={"Content-Type": "application/stream+json"},
                )
                response.raise_for_status()
        except Exception as exc:
            self._maybe_log_error(f"VictoriaLogs ingest failed: {exc}")

    def _maybe_log_error(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_error_log < self._error_interval:
            return
        self._last_error_log = now
        print(f"[WARNING] {message}", file=sys.stderr)

    def flush(self) -> None:
        self._wake.set()
        deadline = time.monotonic() + self._timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._worker.join(timeout=self._timeout + 2.0)
        super().close()

def _get_victoria_ship_handler() -> Optional[VictoriaLogsShipHandler]:
    global _victoria_ship_handler
    if not config.ENABLE_VICTORIA_LOGS_SHIPPER:
        return None
    if not config.VICTORIA_LOGS_URL:
        return None
    with _victoria_lock:
        if _victoria_ship_handler is None:
            _victoria_ship_handler = VictoriaLogsShipHandler(
                base_url=config.VICTORIA_LOGS_URL,
                service=config.VICTORIA_LOGS_SERVICE,
                batch_size=config.VICTORIA_LOGS_BATCH_SIZE,
                flush_interval=config.VICTORIA_LOGS_FLUSH_INTERVAL,
                queue_maxsize=config.VICTORIA_LOGS_QUEUE_SIZE,
                timeout=config.VICTORIA_LOGS_TIMEOUT,
            )
        return _victoria_ship_handler

def _attach_victoria_logs_shipper(logger: logging.Logger, log_type: str) -> None:
    if log_type in _VICTORIA_EXCLUDED_LOG_TYPES:
        return
    shipper = _get_victoria_ship_handler()
    if shipper is None:
        return
    if logger.name in _victoria_attached_loggers:
        return
    logger.addFilter(LogTypeFilter(log_type))
    logger.addHandler(shipper)
    _victoria_attached_loggers.add(logger.name)

def _shutdown_victoria_shipper() -> None:
    global _victoria_ship_handler
    with _victoria_lock:
        if _victoria_ship_handler is not None:
            _victoria_ship_handler.close()
            _victoria_ship_handler = None

atexit.register(_shutdown_victoria_shipper)

# ==================== 核心日誌工廠 ====================

def setup_logger(
    name: str,
    log_type: str = 'app',
    level: str = 'INFO',
    use_json: bool = False,
    max_bytes: int = 10485760,  # 10 MB
    backup_count: int = 30
) -> logging.Logger:
    """日誌建立工廠，避免重複創建"""
    logger = logging.getLogger(name)
    is_new = not logger.handlers

    if is_new:
        logger.setLevel(LOG_LEVELS.get(level, logging.INFO))
        logger.propagate = False  # 防止向上傳播導致重複印出

        # 檔案處理器 (依據參數決定是否使用 JSON)
        try:
            log_file = LOG_FILES.get(log_type, LOG_FILES['app'])
            file_handler = RotatingFileHandler(
                filename=str(log_file),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(LOG_LEVELS.get(level, logging.INFO))
            file_handler.setFormatter(JSONFormatter() if use_json else PlainTextFormatter())
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"[ERROR] 無法創建文件處理器 {name}: {e}")

        # 控制台處理器 (永遠使用彩色文字，方便開發查看)
        try:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(LOG_LEVELS.get(level, logging.INFO))
            console_handler.setFormatter(ColoredFormatter())
            logger.addHandler(console_handler)
        except Exception as e:
            print(f"[ERROR] 無法創建控制台處理器 {name}: {e}")

    _attach_victoria_logs_shipper(logger, log_type)
    return logger

# ==================== 便利函數庫 (解決 ImportError 的關鍵) ====================

def get_logger(name: str) -> logging.Logger:
    """相容舊版的獲取一般日誌器"""
    return setup_logger(name, 'app', level='INFO', use_json=False)

def get_app_logger(name: str) -> logging.Logger:
    """獲取應用程式層級日誌器 (解決 orchestrator 報錯)"""
    return setup_logger(name, 'app', level='DEBUG', use_json=False)

def get_crisis_logger() -> logging.Logger:
    """相容舊版的危機日誌器"""
    return setup_logger('crisis', 'crisis', level='WARNING', use_json=True)

def get_public_logger(name: str) -> logging.Logger:
    """公開日誌器"""
    return setup_logger(name, 'public', level='INFO', use_json=True)

def get_private_logger(name: str) -> logging.Logger:
    """私有/敏感數據日誌器 (不轉送至 VictoriaLogs)"""
    return setup_logger(name, 'private', level='INFO', use_json=True)

def get_critical_logger(name: str) -> logging.Logger:
    """嚴重事件日誌器"""
    return setup_logger(name, 'critical', level='WARNING', use_json=True)

def get_audit_logger(name: str) -> logging.Logger:
    """審計日誌器 (解決 orchestrator 報錯)"""
    return setup_logger(name, 'audit', level='INFO', use_json=True)

def get_error_logger(name: str) -> logging.Logger:
    """錯誤日誌器"""
    return setup_logger(name, 'error', level='ERROR', use_json=False)

def get_health_logger(name: str) -> logging.Logger:
    """健康檢查日誌器"""
    return setup_logger(name, 'health', level='INFO', use_json=True)

# ==================== 臨床會話專用 ====================

def log_session_event(logger: logging.Logger, event_type: str, user_id: str, session_id: str, details: Dict[str, Any], level: str = 'INFO'):
    event = {'event_type': event_type, 'user_id': user_id, 'session_id': session_id, 'timestamp': datetime.now().isoformat(), **details}
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(json.dumps(event, ensure_ascii=False))

def log_risk_escalation(logger: logging.Logger, user_id: str, session_id: str, risk_level: int, escalation_reason: str, escalated_to: str):
    event = {'event_type': 'risk_escalation', 'user_id': user_id, 'session_id': session_id, 'risk_level': risk_level, 'escalation_reason': escalation_reason, 'escalated_to': escalated_to, 'timestamp': datetime.now().isoformat()}
    logger.critical(json.dumps(event, ensure_ascii=False))

def get_clinical_logger(name: str) -> logging.Logger:
    """臨床心理會話專用高優先級日誌"""
    return setup_logger(name, 'critical', level='WARNING', use_json=True)

# ==================== 全局初始化 ====================

def initialize_logging():
    """在 app/__init__.py 中呼叫，確保日誌系統最先啟動"""
    logging.getLogger('orchestrator').setLevel(logging.INFO)
    logging.getLogger('safety').setLevel(logging.WARNING)
    logging.getLogger('emotion').setLevel(logging.INFO)

__all__ = [
    'setup_logger',
    'get_logger',
    'get_app_logger',
    'get_crisis_logger',
    'get_public_logger',
    'get_private_logger',
    'get_critical_logger',
    'get_audit_logger',
    'get_error_logger',
    'get_health_logger',
    'get_clinical_logger',
    'log_session_event',
    'log_risk_escalation',
    'initialize_logging',
    'VictoriaLogsShipHandler',
]
