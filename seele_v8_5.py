# engine7b/seele_v8_5.py - v8.5.1 生产级稳定性版（完全修复）
# 【Engine7B Compute Engine】LLM 進程部署、GPU/VRAM 管理、8081-8085 推理服務
# 不負責：對話路由、人格錨定、PostgreSQL/Redis（Platform / Logic Engine）
# 【核心改進】
# 1. 增强 Emotion Service JSON 解析鲁棒性
# 2. 改进错误恢复机制
# 3. 完善日誌追踪
# 4. 自动化测试框架集成
# 5. 生产级错误处理
# 6. 修复 _build_emotion_cmd 中的缩进和占位符问题
# 7. 修复 return 语句缩进问题

import os
import sys
import json
import time
import logging
import subprocess
import signal
import platform
import asyncio
import threading
import textwrap
import socket
import urllib.request
import urllib.error
from pathlib import Path
from hardware_profile_loader import (
    load_hardware_profile as _load_hw_profile_file,
    merge_config_services,
    vram_reserve_mb,
    estimate_gpu_memory_mb,
    get_conditional_service_names,
    get_resident_service_names,
)
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from enum import Enum
import psutil
from threading import Lock, Thread, RLock, Event
from queue import Queue, Empty, Full
import traceback
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import ast
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# ============================================================================
# 【系统常数定义】
# ============================================================================

CACHE_DIR = Path("cache/prompt_cache")
LOG_DIR = Path("logs")
MODELS_DIR = Path("models")

GPU_VRAM_MB = 16384
CPU_RAM_MB = 196608
VRAM_RESERVE_PERCENT = 20
SOUL_GPU_LAYERS = 40
AUX_LLM_GPU_LAYERS = 0

VOCAL_TIMEOUT = 30
SOUL_TIMEOUT = 120
LOGIC_TIMEOUT = 30
HEALTH_CHECK_TIMEOUT = 5

SERVICE_PRIORITY = {
    'critical': 1,
    'important': 2,
    'optional': 3
}

HEALTH_CHECK_TIMEOUT = 5
DEFAULT_META_HTTP_PORT = 8090
DEFAULT_ON_DEMAND_IDLE_SEC = 300

# ============================================================================
# 【Seele Meta Controller HTTP】Phase 6 — on-demand 8082/8083
# ============================================================================

class _ThreadingMetaHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SeeleMetaHTTPHandler(BaseHTTPRequestHandler):
    """Local control plane for on-demand LLM services."""

    orchestrator: Optional["SeeleUnifiedOrchestrator"] = None

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        orc = self.orchestrator
        if not orc:
            self._send_json(503, {"success": False, "error": "orchestrator_unavailable"})
            return

        if self.path == "/meta/health":
            self._send_json(200, orc.meta_health_payload())
            return

        if self.path == "/meta/services":
            self._send_json(200, orc.meta_services_payload())
            return

        self._send_json(404, {"success": False, "error": "not_found"})

    def do_POST(self) -> None:
        orc = self.orchestrator
        if not orc:
            self._send_json(503, {"success": False, "error": "orchestrator_unavailable"})
            return

        if self.path.startswith("/meta/ensure/"):
            name = self.path.rsplit("/", 1)[-1]
            timeout_sec = int(os.getenv("SEELE_ON_DEMAND_START_TIMEOUT", "120"))
            ok, detail = orc.ensure_on_demand_service(name, timeout_sec=timeout_sec)
            status = 200 if ok else 503
            self._send_json(status, {
                "success": ok,
                "service": name,
                "detail": detail,
                "already_running": detail == "already_running",
            })
            return

        if self.path.startswith("/meta/touch/"):
            name = self.path.rsplit("/", 1)[-1]
            orc.touch_on_demand_service(name)
            self._send_json(200, {"success": True, "service": name, "detail": "touched"})
            return

        if self.path.startswith("/meta/release/"):
            name = self.path.rsplit("/", 1)[-1]
            ok, detail = orc.release_on_demand_service(name)
            status = 200 if ok else 400
            self._send_json(status, {
                "success": ok,
                "service": name,
                "detail": detail,
            })
            return

        self._send_json(404, {"success": False, "error": "not_found"})

# ============================================================================
# 【日誌系统】
# ============================================================================

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class LogRecord:
    timestamp: str
    level: str
    logger_name: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    exception: Optional[str] = None
    duration_ms: Optional[float] = None

class UnifiedLogger:
    """统一日志系统，支持非同步寫入"""
    
    def __init__(self, log_dir: str = "logs", max_queue_size: int = 1000):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.main_log = self.log_dir / f"seele_main_{timestamp}.log"
        self.audit_log = self.log_dir / f"seele_audit_{timestamp}.log"
        self.perf_log = self.log_dir / f"seele_perf_{timestamp}.log"
        
        self._lock = RLock()
        self._queue: Queue = Queue(maxsize=max_queue_size)
        self._stop_event = Event()
        self._writer_thread: Optional[Thread] = None
        self._is_shutdown = False
        
        self._setup_loggers()
        self._start_writer_thread()
    
    def _setup_loggers(self) -> None:
        """初始化 Python logging 系统"""
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        self.logger_main = logging.getLogger('seele.main')
        self.logger_main.setLevel(logging.DEBUG)
        self.logger_main.handlers.clear()
        
        main_fh = logging.FileHandler(self.main_log, encoding='utf-8')
        main_fh.setFormatter(formatter)
        main_fh.setLevel(logging.DEBUG)
        self.logger_main.addHandler(main_fh)
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger_main.addHandler(console_handler)
    
    def _start_writer_thread(self) -> None:
        """启动背景写入线程"""
        self._writer_thread = Thread(
            target=self._log_writer_loop,
            daemon=True,
            name="LogWriter"
        )
        self._writer_thread.start()
    
    def _log_writer_loop(self):
        try:
            while not self._stop_event.is_set():
                try:
                    record = self._queue.get(timeout=1)
                    if record is None:
                        break
                    log_entry = {
                        'timestamp': record.timestamp,
                        'level': record.level,
                        'message': record.message,
                        **record.context
                    }
                    log_line = json.dumps(log_entry, ensure_ascii=False)
                    with open(self.main_log, 'a', encoding='utf-8') as f:
                        f.write(log_line + '\n')
                except Empty:
                    pass
                except Exception as e:
                    print(f"Log writer error: {e}", file=sys.stderr)
        finally:
            # 确保所有剩余日志被写入
            while True:
                try:
                    record = self._queue.get_nowait()
                    if record is None:
                        break
                    # ... 处理 ...
                except Empty:
                    break
    
    def log(self, level: str, message: str, context: Optional[Dict[str, Any]] = None, sync: bool = False) -> None:
        """记录日誌"""
        record = LogRecord(
            timestamp=datetime.now().isoformat(),
            level=level,
            logger_name='seele',
            message=message,
            context=context or {}
        )
        
        if sync:
            try:
                log_entry = {
                    'timestamp': record.timestamp,
                    'level': record.level,
                    'message': record.message,
                    **record.context
                }
                log_line = json.dumps(log_entry, ensure_ascii=False)
                with open(self.main_log, 'a', encoding='utf-8') as f:
                    f.write(log_line + '\n')
            except Exception:
                pass
        else:
            try:
                self._queue.put(record, timeout=0.5)
            except Full:
                pass
        
        log_method = getattr(self.logger_main, level.lower(), self.logger_main.info)
        log_method(message)
    
    def info(self, msg: str, context: Optional[Dict[str, Any]] = None, sync: bool = False) -> None:
        self.log('INFO', msg, context, sync)
    
    def warning(self, msg: str, context: Optional[Dict[str, Any]] = None, sync: bool = False) -> None:
        self.log('WARNING', msg, context, sync)
    
    def error(self, msg: str, context: Optional[Dict[str, Any]] = None, sync: bool = False) -> None:
        self.log('ERROR', msg, context, sync)
    
    def critical(self, msg: str, context: Optional[Dict[str, Any]] = None, sync: bool = False) -> None:
        self.log('CRITICAL', msg, context, sync)
    
    def debug(self, msg: str, context: Optional[Dict[str, Any]] = None, sync: bool = False) -> None:
        self.log('DEBUG', msg, context, sync)
    
    def shutdown(self) -> None:
        """关闭日誌系统"""
        if self._is_shutdown:
            return
        
        self._is_shutdown = True
        self._stop_event.set()
        self._queue.put(None)
        
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=5)
        
        for handler in logging.root.handlers[:]:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass

_logger = UnifiedLogger(log_dir=str(LOG_DIR))

# ============================================================================
# 【情感分析响应解析器】
# ============================================================================

class EmotionResponseParser:
    """
    增强的情感分析响应解析器
    处理 Emobloom 模型可能产生的各种格式问题
    """
    
    @staticmethod
    def parse_emotion_output(text_output: str) -> Dict[str, Any]:
        """
        解析情感分析模型的输出
        
        Args:
            text_output: 模型生成的原始文本
            
        Returns:
            标准化的情感分析结果字典
        """
        
        # 步骤 1: 直接 JSON 解析
        try:
            result = json.loads(text_output)
            _logger.debug(f"[EMOTION_PARSE] Direct JSON parse succeeded")
            return EmotionResponseParser._validate_and_normalize(result)
        except json.JSONDecodeError:
            pass
        
        # 步骤 2: 提取 JSON 块
        cleaned = text_output.strip()
        if not cleaned.startswith('{'):
            match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
            if match:
                cleaned = match.group()
                _logger.debug(f"[EMOTION_PARSE] Extracted JSON block from text")
        
        # 步骤 3: 修复单引号格式 (Python 字典)
        try:
            fixed = cleaned.replace("'", '"')
            result = json.loads(fixed)
            _logger.debug(f"[EMOTION_PARSE] Fixed single quotes and parsed")
            return EmotionResponseParser._validate_and_normalize(result)
        except json.JSONDecodeError:
            pass
        
        # 步骤 4: 修复数字键格式
        try:
            fixed = re.sub(
                r'(-?\d+\.?\d*)\s*:',
                r'"\1":',
                cleaned
            )
            result = json.loads(fixed)
            _logger.debug(f"[EMOTION_PARSE] Fixed numeric keys and parsed")
            return EmotionResponseParser._validate_and_normalize(result)
        except json.JSONDecodeError:
            pass
        
        # 步骤 5: 使用 ast.literal_eval (处理 Python 字典)
        try:
            result = ast.literal_eval(cleaned)
            if isinstance(result, dict):
                _logger.debug(f"[EMOTION_PARSE] Parsed as Python literal")
                return EmotionResponseParser._validate_and_normalize(result)
        except (ValueError, SyntaxError):
            pass
        
        # 步骤 6: 正则表达式提取数值 (最后手段)
        try:
            numbers = re.findall(r'-?\d+\.?\d*', cleaned)
            if len(numbers) >= 3:
                _logger.debug(f"[EMOTION_PARSE] Extracted values using regex fallback")
                return {
                    "valence": float(numbers[0]),
                    "arousal": float(numbers[1]),
                    "dominance": float(numbers[2]),
                    "dominant_emotion": "unknown",
                    "confidence": 0.2,
                    "is_crisis_risk": False,
                    "parse_quality": "degraded"
                }
        except (ValueError, IndexError):
            pass
        
        # 步骤 7: 终极 fallback
        _logger.warning(
            f"[EMOTION_PARSE] All parsing methods failed, returning defaults",
            context={"raw_output": text_output[:200]}
        )
        return {
            "valence": 0.0,
            "arousal": 0.5,
            "dominance": 0.0,
            "dominant_emotion": "neutral",
            "confidence": 0.0,
            "is_crisis_risk": False,
            "parse_quality": "fallback"
        }
    
    @staticmethod
    def _validate_and_normalize(data: Dict[str, Any]) -> Dict[str, Any]:
        """验证并标准化解析结果"""
        
        result = {
            "valence": float(data.get("valence", 0.0) or 0.0),
            "arousal": float(data.get("arousal", 0.5) or 0.5),
            "dominance": float(data.get("dominance", 0.0) or 0.0),
            "dominant_emotion": str(data.get("dominant_emotion", "neutral") or "neutral").lower(),
            "confidence": float(data.get("confidence", 0.8) or 0.8),
            "is_crisis_risk": bool(data.get("is_crisis_risk", False))
        }
        
        result["valence"] = max(-1.0, min(1.0, result["valence"]))
        result["arousal"] = max(0.0, min(1.0, result["arousal"]))
        result["dominance"] = max(-1.0, min(1.0, result["dominance"]))
        result["confidence"] = max(0.0, min(1.0, result["confidence"]))
        
        if "choices" in data:
            result["choices"] = data["choices"]
        if "usage" in data:
            result["usage"] = data["usage"]
        
        return result

# ============================================================================
# 【GPU 監控系統】
# ============================================================================

class GPUMonitor:
    """監控 GPU 記憶體狀態"""
    
    def __init__(self) -> None:
        self._lock = RLock()
        self.last_status: Dict[str, Any] = {}
        self.status_cache_time: float = 0
        self._cache_dirty = True
    
    def mark_cache_dirty(self) -> None:
        """標記快取為過期，強制下次查詢"""
        with self._lock:
            self._cache_dirty = True
    
    def get_gpu_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """取得 GPU 狀態（含 5 秒快取，可強制刷新）"""
        with self._lock:
            now = time.time()
            if not force_refresh and not self._cache_dirty and (now - self.status_cache_time) < 5:
                return self.last_status
        
        try:
            cmd = [
                'nvidia-smi',
                '--query-gpu=memory.total,memory.used,memory.free',
                '--format=csv,nounits,noheader'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                values = result.stdout.strip().split(',')
                total_mb = float(values[0])
                used_mb = float(values[1])
                free_mb = float(values[2])
                
                reserve_mb = vram_reserve_mb()
                status = {
                    'available': True,
                    'total_mb': total_mb,
                    'used_mb': used_mb,
                    'free_mb': free_mb,
                    'reserve_mb': reserve_mb,
                    'usable_mb': max(0, free_mb - reserve_mb),
                }
            else:
                raise ValueError(f"nvidia-smi returned {result.returncode}")
        except Exception as e:
            _logger.warning(f"GPU monitoring failed: {e}. Using fallback.")
            status = {
                'available': False,
                'total_mb': GPU_VRAM_MB,
                'used_mb': 0,
                'free_mb': GPU_VRAM_MB,
                'reserve_mb': vram_reserve_mb(),
                'usable_mb': max(0, GPU_VRAM_MB - vram_reserve_mb()),
            }
        
        with self._lock:
            self.last_status = status
            self.status_cache_time = time.time()
            self._cache_dirty = False
        
        return status
    
    def wait_for_space(self, required_mb: float, max_wait: int = 120) -> bool:
        """等待 GPU 有足夠空間。

        usable_mb 已扣除 vram_reserve_mb()，因此 required_mb 只需為模型估計值，
        不可再加 reserve（否則 reserve 會被重複扣除，導致永遠超時）。
        """
        start = time.time()
        while time.time() - start < max_wait:
            if self.get_gpu_status(force_refresh=True)['usable_mb'] >= required_mb:
                return True
            time.sleep(1)
        
        _logger.warning(f"GPU space wait timeout: needed {required_mb}MB, max waited {max_wait}s")
        return False

# ============================================================================
# 【進程輸出監控】
# ============================================================================

class ProcessOutputMonitor:
    """監控子進程的 stdout/stderr"""
    
    def __init__(self, process: subprocess.Popen, service_name: str) -> None:
        self.process = process
        self.service_name = service_name
        self.lines: List[str] = []
        self._lock = RLock()
        self._stop_event = Event()
        self._threads: List[Thread] = []
    
    def start(self) -> None:
        """啟動流讀取線程"""
        if self.process.stdout:
            t = Thread(
                target=self._read_stream,
                args=(self.process.stdout,),
                daemon=True,
                name=f"Monitor-{self.service_name}-stdout"
            )
            t.start()
            self._threads.append(t)
        
        if self.process.stderr:
            t = Thread(
                target=self._read_stream,
                args=(self.process.stderr,),
                daemon=True,
                name=f"Monitor-{self.service_name}-stderr"
            )
            t.start()
            self._threads.append(t)
    
    def _read_stream(self, stream: Any) -> None:
        """讀取流內容"""
        try:
            for line in iter(stream.readline, ''):
                if not line or self._stop_event.is_set():
                    break
                
                decoded = line.strip()
                if not decoded:
                    continue
                
                with self._lock:
                    self.lines.append(decoded)
                    if len(self.lines) > 100:
                        self.lines.pop(0)
                
                lower_decoded = decoded.lower()
                is_template_meta = "chat_template" in lower_decoded or "raise_exception" in lower_decoded
                
                if any(x in lower_decoded for x in ["error", "exception", "failed", "traceback"]) and not is_template_meta:
                    _logger.error(f"[{self.service_name}] {decoded}", sync=True)
                elif any(x in decoded for x in ["llm_load_tensors", "model_load", "Llama.cpp", "HTTP", "listening", "started server"]):
                    _logger.info(f"[{self.service_name}] {decoded}")
        except Exception as e:
            _logger.debug(f"Stream read error for {self.service_name}: {type(e).__name__}: {e}")
    
    def get_recent_output(self, count: int = 30) -> str:
        """取得最近的輸出行"""
        with self._lock:
            return '\n'.join(self.lines[-count:])
    
    def stop(self) -> None:
        """停止監控"""
        self._stop_event.set()

# ============================================================================
# 【進程管理器】
# ============================================================================

class ProcessManager:
    """管理 LLM 模型進程"""
    
    def __init__(self, python_exe: str, gpu_monitor: GPUMonitor) -> None:
        self.python_exe = python_exe
        self.gpu_monitor = gpu_monitor
        self.processes: Dict[str, int] = {}
        self.process_objects: Dict[str, subprocess.Popen] = {}
        self.monitors: Dict[str, ProcessOutputMonitor] = {}
        self._lock = RLock()
        
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        _logger.info("ProcessManager initialized", context={
            'python_exe': python_exe,
            'cache_dir': str(CACHE_DIR)
        }, sync=True)
    
    def _is_local_model_path(self, model_path: str) -> bool:
        """判斷是否為本地模型路徑"""
        if '/' in model_path and not ('\\' in model_path or model_path.startswith('.')):
            return False
        
        if model_path.endswith(('.gguf', '.bin', '.safetensors', '.pt', '.pth')):
            return True
        
        if '\\' in model_path or model_path.startswith('.') or model_path.startswith('/'):
            return True
        
        return False
    
    def _validate_model_path(self, model_path: str, service_type: str) -> Tuple[bool, str]:
        """驗證模型文件存在，返回 (是否有效, 錯誤信息)"""
        
        if os.getenv("MOCK_LLM") == "true":
            return True, ""

        if service_type == "fastapi_custom":
            script_path = Path(model_path)
            if not script_path.exists() or not script_path.suffix == '.py':
                return False, f"FastAPI script not found: {model_path}"
            return True, ""
        
        if not self._is_local_model_path(model_path):
            _logger.debug(f"Skipping local validation for remote model: {model_path}", sync=False)
            return True, ""
        
        path = Path(model_path)
        if path.exists() and path.is_file():
            return True, ""
        
        return False, f"Model file not found: {model_path}"
    
    def start_service(
            self,
            service_name: str,
            model_path: str,
            port: int,
            gpu_layers: int,
            service_type: str,
            n_threads: int,
            n_ctx: int,
            timeout_sec: int = 60,
            retry_count: int = 3
        ) -> Optional[int]:
        """啟動服務（含重試機制）"""
        
        for attempt in range(1, retry_count + 1):
            result = self._start_service_once(
                service_name, model_path, port, gpu_layers,
                service_type, n_threads, n_ctx, timeout_sec, attempt
            )
            
            if result is not None:
                return result
            
            if attempt < retry_count:
                wait_time = min(5 * attempt, 30)
                _logger.warning(
                    f"{service_name}: Retrying in {wait_time}s (attempt {attempt}/{retry_count - 1})",
                    sync=True
                )
                time.sleep(wait_time)
        
        return None
    
    def _start_service_once(
            self,
            service_name: str,
            model_path: str,
            port: int,
            gpu_layers: int,
            service_type: str,
            n_threads: int,
            n_ctx: int,
            timeout_sec: int = 60,
            attempt: int = 1
        ) -> Optional[int]:
        """單次服務啟動嘗試"""
        
        model_path_str = str(model_path).replace('\\', '/')
        
        is_valid, error_msg = self._validate_model_path(model_path_str, service_type)
        if not is_valid:
            _logger.error(f"{service_name}: {error_msg}", sync=True)
            return None
        
        if self.is_port_in_use(port):
            _logger.error(f"{service_name}: Port {port} is ALREADY IN USE. Killing potentially dead process...", sync=True)
            try:
                for proc in psutil.process_iter(['pid', 'name']):
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr.port == port:
                            _logger.warning(f"Killing PID {proc.pid} ({proc.name()}) holding port {port}")
                            proc.kill()
            except Exception:
                pass
            time.sleep(1)
            
        if service_type in ("llm", "emotion_proxy") and gpu_layers > 0:
            model_mb = estimate_gpu_memory_mb(service_name, gpu_layers)
            reserve_mb = vram_reserve_mb()
            max_wait = 120 if service_name in ("main_llm", "soul") else 60
            if not self.gpu_monitor.wait_for_space(model_mb, max_wait=max_wait):
                usable = self.gpu_monitor.get_gpu_status(force_refresh=True).get('usable_mb', 0)
                _logger.error(
                    f"{service_name}: GPU space insufficient "
                    f"(need ~{model_mb:.0f}MB usable, have ~{usable:.0f}MB; "
                    f"{reserve_mb}MB reserve already excluded from usable)",
                    sync=True,
                )
                return None
        
        if os.getenv("MOCK_LLM") == "true":
            _logger.info(f"{service_name}: RUNNING IN MOCK MODE", sync=True)
            cmd = ["tail", "-f", "/dev/null"] if platform.system() != "Windows" else ["cmd", "/c", "pause"]
        elif service_type == "embedding":
            cmd = self._build_embedding_cmd(service_name, model_path_str, port)
        elif service_type == "emotion_proxy":
            cmd = self._build_emotion_cmd(service_name, model_path_str, port, gpu_layers)
        elif service_type == "fastapi_custom":
            script_path = Path(model_path_str)
            module_name = script_path.stem
            cmd = [
                self.python_exe, "-m", "uvicorn",
                f"{module_name}:app",
                "--host", "0.0.0.0",
                "--port", str(port)
            ]
        else:
            cmd = self._build_llm_cmd(
                service_name, model_path_str, port,
                gpu_layers, n_threads, n_ctx
            )
        
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['FOR_DISABLE_CONSOLE_CTRL_HANDLER'] = '1'
        env['MKL_NUM_THREADS'] = '1'
        env['OMP_NUM_THREADS'] = '1'
        env['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
        env.pop('API_KEY', None)
        env.pop('LLAMA_CPP_API_KEY', None)
        env['PYTHONUTF8'] = '1'
        env['PYTHONPATH'] = os.path.abspath(os.getcwd())
        
        if service_type == "fastapi_custom":
            script_dir = str(Path(model_path_str).parent.absolute())
            pythonpath = env.get('PYTHONPATH', '')
            env['PYTHONPATH'] = f"{script_dir}{os.pathsep}{pythonpath}".rstrip(os.pathsep)
        
        try:
            popen_kwargs: Dict[str, Any] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
                "env": env,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace"
            }
            
            if platform.system() == 'Windows':
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["preexec_fn"] = os.setsid
                
            process = subprocess.Popen(cmd, **popen_kwargs)
            
            monitor = ProcessOutputMonitor(process, service_name)
            monitor.start()
            
            with self._lock:
                self.processes[service_name] = process.pid
                self.process_objects[service_name] = process
                self.monitors[service_name] = monitor
            
            time.sleep(3)
            
            exit_code = process.poll()
            if exit_code is not None:
                recent_output = monitor.get_recent_output(30)
                _logger.error(
                    f"{service_name} crashed immediately (attempt {attempt})",
                    context={
                        'exit_code': exit_code,
                        'recent_output': recent_output[:500]
                    },
                    sync=True
                )
                return None
            
            self.gpu_monitor.mark_cache_dirty()
            _logger.info(
                f"{service_name} started successfully",
                context={'pid': process.pid, 'attempt': attempt},
                sync=True
            )
            return process.pid
        
        except Exception as e:
            _logger.error(
                f"Failed to start {service_name} (attempt {attempt})",
                context={
                    'error': str(e),
                    'traceback': traceback.format_exc()
                },
                sync=True
            )
            return None
    
    def _build_embedding_cmd(self, service_name: str, model_path: str, port: int) -> List[str]:
        """構建 Embedding 服務啟動指令"""
        code = textwrap.dedent("""
import uvicorn
import sys
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel
from typing import List

app = FastAPI()

try:
    model = SentenceTransformer(
        r"{model_path}",
        device="cpu"
    )
except Exception as e:
    print(f"Model load error: {e}", file=sys.stderr)
    sys.exit(1)

class EmbedRequest(BaseModel):
    input: List[str]

@app.get("/")
@app.get("/health")
@app.get("/v1/embeddings/health")
async def health():
    return {"status": "ok", "message": "Embedding service is running"}

@app.get("/v1/models")
async def models():
    return {"data": [{"id": "bge-m3", "object": "model"}]}

@app.post("/v1/embeddings")
async def get_embeddings(item: EmbedRequest):
    try:
        emb = model.encode(item.input, normalize_embeddings=True)
        return {
            "data": [
                {"embedding": e.tolist(), "index": i, "object": "embedding"}
                for i, e in enumerate(emb)
            ]
        }
    except Exception as e:
        print(f"Embedding error: {e}", file=sys.stderr)
        return JSONResponse(content={"error": str(e)}, status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port={port})
""")
        code = code.replace("{model_path}", str(model_path))
        code = code.replace("{port}", str(port))
        return [self.python_exe, "-c", code]
    
    def _build_emotion_cmd(
        self,
        service_name: str,
        model_path: str,
        port: int,
        gpu_layers: int = 0
    ) -> List[str]:
        """構建情緒分析服務啟動指令（修復版）"""
        
        code = textwrap.dedent(f"""
    import uvicorn
    import sys
    import json
    import re
    import ast
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from llama_cpp import Llama
    from pydantic import BaseModel
    from typing import List, Dict, Any

    app = FastAPI()

    try:
        llm = Llama(
            model_path=r"{model_path}",
            n_gpu_layers={gpu_layers},
            n_ctx=1024,
            verbose=False
        )
    except Exception as e:
        print(f"Emotion model load error: {{e}}", file=sys.stderr)
        sys.exit(1)

    def parse_emotion_output(text_output: str) -> dict:
        \"\"\"增强的情感输出解析器\"\"\"
        try:
            return json.loads(text_output)
        except json.JSONDecodeError:
            pass
        
        cleaned = text_output.strip()
        if not cleaned.startswith('{{'):
            cleaned = '{{' + cleaned
        if not cleaned.endswith('}}'):
            cleaned = cleaned + '}}'
        
        try:
            fixed = cleaned.replace("'", '"')
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        
        try:
            numbers = re.findall(r'-?\\d+\\.?\\d*', cleaned)
            if len(numbers) >= 3:
                return {{
                    "valence": float(numbers[0]),
                    "arousal": float(numbers[1]),
                    "dominance": float(numbers[2]),
                    "dominant_emotion": "unknown",
                    "confidence": 0.2
                }}
        except (ValueError, IndexError):
            pass
        
        return {{
            "valence": 0.0,
            "arousal": 0.5,
            "dominance": 0.0,
            "dominant_emotion": "neutral",
            "confidence": 0.0
        }}

    @app.get("/")
    @app.get("/health")
    @app.get("/v1/analyze/health")
    async def health():
        return {{"status": "ok", "service": "emotion"}}

    @app.get("/v1/models")
    async def models():
        return {{"data": [{{"id": "emobloom", "object": "model"}}]}}

    @app.post("/v1/analyze")
    async def analyze(request: Request):
        try:
            body = await request.json()
            prompt = body.get("prompt", "")
            
            if not prompt:
                return {{
                    "valence": 0.0,
                    "arousal": 0.5,
                    "dominance": 0.0,
                    "dominant_emotion": "neutral",
                    "confidence": 1.0
                }}
            
            analysis_prompt = f"Analyze emotion in: {{prompt[:100]}}"
            output = llm(analysis_prompt, max_tokens=64, stop=["}}"], echo=False)
            text_output = output["choices"][0]["text"].strip()
            
            res = parse_emotion_output(text_output)
            
            return {{
                "valence": float(res.get("valence", 0.0) or 0.0),
                "arousal": float(res.get("arousal", 0.5) or 0.5),
                "dominance": float(res.get("dominance", 0.0) or 0.0),
                "dominant_emotion": res.get("dominant_emotion", "neutral"),
                "confidence": float(res.get("confidence", 0.5) or 0.5),
                "choices": [{{"text": text_output, "index": 0}}]
            }}
        except Exception as e:
            print(f"[ERROR] {{e}}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return JSONResponse(
                content={{"error": str(e)}},
                status_code=500
            )

    if __name__ == "__main__":
        uvicorn.run(app, host="0.0.0.0", port={port})
    """)
        
        return [self.python_exe, "-c", code]

    def _build_llm_cmd(
            self,
            service_name: str,
            model_path: str,
            port: int,
            gpu_layers: int,
            n_threads: int,
            n_ctx: int
        ) -> List[str]:
        """構建 LLM 服務啟動指令 (FastAPI 封裝以增強穩定性)"""
        code = textwrap.dedent("""
import uvicorn
import sys
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from llama_cpp import Llama
from typing import List, Dict, Any

app = FastAPI()

try:
    llm = Llama(
        model_path=r"{model_path}",
        n_gpu_layers={gpu_layers},
        n_ctx={n_ctx},
        n_threads={n_threads},
        verbose=False
    )
except Exception as e:
    print(f"Model load error: {e}", file=sys.stderr)
    sys.exit(1)

@app.get("/")
@app.get("/health")
@app.get("/v1/completions/health")
@app.get("/v1/chat/completions/health")
async def health():
    return {"status": "ok", "service": "{service_name}"}

@app.get("/v1/models")
async def models():
    return {"data": [{"id": "{service_name}", "object": "model"}]}

@app.post("/v1/completions")
@app.post("/v1/chat/completions")
async def completions(request: Request):
    try:
        body = await request.json()
        
        if "/chat/" in str(request.url) or "messages" in body:
            messages = body.get("messages", [])
            if not messages and body.get("prompt"):
                messages = [{"role": "user", "content": body.get("prompt")}]
            
            res = llm.create_chat_completion(
                messages=messages,
                max_tokens=body.get("max_tokens", 1024),
                stop=body.get("stop", ["\\nInstruction:", "User:", "Assistant:"]),
                temperature=body.get("temperature", 0.7),
                stream=False
            )
            return res
            
        prompt = body.get("prompt", "")
        output = llm(
            prompt,
            max_tokens=body.get("max_tokens", 1024),
            stop=body.get("stop", ["\\nInstruction:", "User:", "Assistant:"]),
            temperature=body.get("temperature", 0.7),
            echo=False
        )
        return output
    except Exception as e:
        error_msg = str(e) or "Unknown internal error"
        print(f"[ERROR] completions failed: {error_msg}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return JSONResponse(content={"error": error_msg}, status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port={port})
""")
        code = code.replace("{model_path}", str(model_path))
        code = code.replace("{gpu_layers}", str(gpu_layers))
        code = code.replace("{n_ctx}", str(n_ctx))
        code = code.replace("{n_threads}", str(n_threads))
        code = code.replace("{service_name}", str(service_name))
        code = code.replace("{port}", str(port))
        
        return [self.python_exe, "-c", code]
    
    def check_health(self, port: int, service_type: str = "llm", timeout: int = HEALTH_CHECK_TIMEOUT) -> bool:
        """检查服务健康状态"""
        if os.getenv("MOCK_LLM") == "true":
            return True
        
        endpoints = ["/v1/models", "/health", "/"]
        
        for path in endpoints:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status in [200, 401, 404]
            except urllib.error.HTTPError as e:
                return e.code in [200, 401, 404]
            except urllib.error.URLError:
                continue
            except Exception:
                pass
        
        return False
    
    def is_port_in_use(self, port: int) -> bool:
        """檢查端口是否已被佔用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    
    def stop_service(self, service_name: str) -> None:
        """停止服務"""
        with self._lock:
            proc = self.process_objects.get(service_name)
            mon = self.monitors.get(service_name)
        
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                _logger.info(f"{service_name} terminated", sync=True)
            except subprocess.TimeoutExpired:
                _logger.warning(f"Force killing {service_name}", sync=True)
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
            except Exception as e:
                _logger.warning(f"Error stopping {service_name}: {e}", sync=True)
        
        if mon:
            mon.stop()

# ============================================================================
# 【統一編排器】
# ============================================================================

class SeeleUnifiedOrchestrator:
    """統一的模型編排與部署系統"""
    
    def __init__(self, config_path: str = "config.json", models_dir: str = "models") -> None:
        self.models_dir = Path(models_dir)
        self.config_path = config_path
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            _logger.error(f"Config file not found: {config_path}", sync=True)
            self.config = {}
        except json.JSONDecodeError as e:
            _logger.error(f"Config file format error: {e}", sync=True)
            self.config = {}
        
        self._apply_hardware_profile()
        
        self.python_exe = sys.executable
        
        try:
            import uvicorn
            import fastapi
            _logger.info(f"Environment Audit: All server dependencies verified in {self.python_exe}")
            
            try:
                import llama_cpp
                _logger.info("llama-cpp-python core module found.")
            except ImportError:
                _logger.error("CRITICAL: 'llama-cpp-python' core is missing.")
                print("\n" + "="*80)
                print("CRITICAL ERROR: llama-cpp-python is NOT installed correctly.")
                print("CAUSED BY: Windows Long Path Limit (260 characters).")
                print("FIX (Admin): reg add \"HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\" /v LongPathsEnabled /t REG_DWORD /d 1 /f")
                print("FIX (No-Admin workaround):")
                print("  1. git clone --depth 1 https://github.com/abetlen/llama-cpp-python.git D:\\L")
                print("  2. pip install D:\\L[server]")
                print("="*80 + "\n")
                sys.exit(1)
        except ImportError as e:
            _logger.error(f"CRITICAL: Missing dependency '{e.name}' in the current environment.")
            print(f"ModuleNotFoundError: No module named '{e.name}'")
            print(f"Current Sys Path: {sys.path}")
            print(f"Current Executable: {sys.executable}")
            print(f"FIX: Run 'pip install llama-cpp-python[server]' in this environment.")
            if "llama_cpp" in str(e) or "uvicorn" in str(e):
                print("HINT: This usually means the installation failed silently due to 'Long Path' errors.")

        self.gpu_monitor = GPUMonitor()
        self.pm = ProcessManager(self.python_exe, self.gpu_monitor)
        self.running = False
        self.started_services: Dict[str, Dict[str, Any]] = {}
        self.on_demand_registry: Dict[str, Dict[str, Any]] = {}
        self.on_demand_last_used: Dict[str, float] = {}
        self.on_demand_idle_sec = int(
            os.getenv("SEELE_ON_DEMAND_IDLE_SEC", str(DEFAULT_ON_DEMAND_IDLE_SEC))
        )
        self.meta_http_port = int(os.getenv("SEELE_META_PORT", str(DEFAULT_META_HTTP_PORT)))
        self._meta_http_server: Optional[_ThreadingMetaHTTPServer] = None
        self._meta_http_thread: Optional[Thread] = None
        self._meta_lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="Seele-Deploy")
        
        atexit.register(self.shutdown)
        
        _logger.info("SeeleUnifiedOrchestrator v8.5.1 initialized", context={
            'config_path': config_path,
            'models_dir': str(self.models_dir)
        }, sync=True)
    
    def _load_hardware_profile(self) -> Optional[Dict[str, Any]]:
        """Load optional hardware profile (config/hardware_profile.json)."""
        return _load_hw_profile_file()

    def _apply_hardware_profile(self) -> None:
        """Merge hardware_profile.json into config.json service entries."""
        global GPU_VRAM_MB, CPU_RAM_MB, VRAM_RESERVE_PERCENT, SOUL_GPU_LAYERS, AUX_LLM_GPU_LAYERS

        profile = self._load_hardware_profile()
        if not profile:
            return

        GPU_VRAM_MB = int(profile.get('vram_total_mb', GPU_VRAM_MB))
        CPU_RAM_MB = int(profile.get('ram_total_mb', CPU_RAM_MB))
        VRAM_RESERVE_PERCENT = int(profile.get('vram_reserve_percent', VRAM_RESERVE_PERCENT))

        self.config['services'] = merge_config_services(self.config.get('services', []))

        main_cfg = profile.get('services', {}).get('main_llm', {})
        if 'gpu_layers' in main_cfg:
            SOUL_GPU_LAYERS = int(main_cfg['gpu_layers'])

        env_main_layers = os.getenv('MAIN_LLM_GPU_LAYERS')
        if env_main_layers is not None and env_main_layers.strip().isdigit():
            SOUL_GPU_LAYERS = int(env_main_layers.strip())

        env_aux_layers = os.getenv('AUX_LLM_GPU_LAYERS')
        if env_aux_layers is not None and env_aux_layers.strip().isdigit():
            AUX_LLM_GPU_LAYERS = int(env_aux_layers.strip())

        budget = profile.get('vram_budget_mb')
        _logger.info(
            "Hardware profile applied",
            context={
                'machine_id': profile.get('machine_id'),
                'vram_total_mb': GPU_VRAM_MB,
                'vram_reserve_percent': VRAM_RESERVE_PERCENT,
                'vram_budget_mb': budget,
                'gpu_strategy': profile.get('gpu_strategy'),
                'soul_gpu_layers': SOUL_GPU_LAYERS,
                'aux_gpu_layers': AUX_LLM_GPU_LAYERS,
            },
            sync=True,
        )
    
    def _get_service_priority_level(self, service_name: str) -> str:
        """取得服務優先級級別"""
        for svc in self.config.get('services', []):
            if svc['name'] == service_name:
                return svc.get('priority_level', 'important')
        return 'important'

    def _prepare_service_config(self, service_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve model path, GPU layers, and runtime fields for one service."""
        s = service_entry
        if '/' in s['model_path'] or '\\' in s['model_path'] or Path(s['model_path']).is_absolute():
            model_path = s['model_path']
        else:
            model_path = str(self.models_dir / s['model_path'])

        gpu_layers = s.get('gpu_layers', -1)
        if s['name'] in ('main_llm', 'soul'):
            if gpu_layers in (0, -1):
                gpu_layers = SOUL_GPU_LAYERS
        elif gpu_layers < 0:
            gpu_layers = AUX_LLM_GPU_LAYERS

        return {
            'name': s['name'],
            'model_path': model_path,
            'port': s['port'],
            'gpu_layers': gpu_layers,
            'type': s.get('type', 'llm'),
            'n_threads': s.get('n_threads', 4),
            'n_ctx': s.get('n_ctx', 4096),
            'timeout_sec': s.get('timeout_sec', 60),
            'priority_level': s.get('priority_level', 'important'),
            'conditional': bool(s.get('conditional', False)),
        }

    def _wait_service_ready(
        self,
        name: str,
        port: int,
        service_type: str,
        timeout_sec: int,
    ) -> bool:
        wait_start = time.time()
        timeout = max(timeout_sec, 60) * 5
        while time.time() - wait_start < timeout:
            if self.pm.check_health(port, service_type):
                return True
            if int(time.time() - wait_start) % 30 == 0:
                _logger.info(
                    f"[WAITING] Still loading {name}... "
                    f"({int(time.time() - wait_start)}s / {timeout}s)",
                    sync=True,
                )
            time.sleep(2)
        return False

    def _start_from_config(
        self,
        cfg: Dict[str, Any],
        *,
        on_demand: bool = False,
    ) -> bool:
        """Start one service from a prepared config dict."""
        name = cfg['name']
        pid = self.pm.start_service(
            name,
            cfg['model_path'],
            cfg['port'],
            cfg['gpu_layers'],
            cfg['type'],
            cfg['n_threads'],
            cfg['n_ctx'],
            cfg['timeout_sec'],
            retry_count=3,
        )
        if not pid:
            return False

        self.started_services[name] = {
            'pid': pid,
            'port': cfg['port'],
            'type': cfg['type'],
            'priority_level': cfg['priority_level'],
            'model_path': cfg['model_path'],
            'gpu_layers': cfg['gpu_layers'],
            'n_threads': cfg['n_threads'],
            'n_ctx': cfg['n_ctx'],
            'timeout_sec': cfg['timeout_sec'],
            'on_demand': on_demand,
        }

        ready = self._wait_service_ready(
            name,
            cfg['port'],
            cfg['type'],
            cfg['timeout_sec'],
        )
        if ready:
            self.started_services[name]['ready'] = True
            if on_demand:
                self.on_demand_last_used[name] = time.time()
            _logger.info(f"[READY] {name} is online", sync=True)
            return True

        _logger.warning(f"[TIMEOUT] {name} failed to become ready", sync=True)
        self.started_services.pop(name, None)
        self.pm.stop_service(name)
        return False

    def _start_meta_http_server(self) -> None:
        if self._meta_http_server is not None:
            return
        try:
            SeeleMetaHTTPHandler.orchestrator = self
            server = _ThreadingMetaHTTPServer(
                ("127.0.0.1", self.meta_http_port),
                SeeleMetaHTTPHandler,
            )
            thread = Thread(
                target=server.serve_forever,
                name="Seele-Meta-HTTP",
                daemon=True,
            )
            thread.start()
            self._meta_http_server = server
            self._meta_http_thread = thread
            _logger.info(
                f"[META] Control plane listening on http://127.0.0.1:{self.meta_http_port}",
                sync=True,
            )
        except OSError as exc:
            _logger.error(f"[META] Failed to bind port {self.meta_http_port}: {exc}", sync=True)

    def _stop_meta_http_server(self) -> None:
        if self._meta_http_server is not None:
            try:
                self._meta_http_server.shutdown()
                self._meta_http_server.server_close()
            except Exception:
                pass
            self._meta_http_server = None
            self._meta_http_thread = None

    def meta_health_payload(self) -> Dict[str, Any]:
        profile = self._load_hardware_profile() or {}
        return {
            "success": True,
            "status": "online" if self.running else "starting",
            "meta_port": self.meta_http_port,
            "on_demand_idle_sec": self.on_demand_idle_sec,
            "resident_services": get_resident_service_names(profile),
            "conditional_services": get_conditional_service_names(profile),
            "running_count": len(self.started_services),
            "on_demand_active": sorted(
                n for n, info in self.started_services.items() if info.get('on_demand')
            ),
        }

    def meta_services_payload(self) -> Dict[str, Any]:
        services: Dict[str, Any] = {}
        for name, cfg in self.on_demand_registry.items():
            running = name in self.started_services
            info = self.started_services.get(name, {})
            services[name] = {
                "conditional": True,
                "port": cfg.get('port'),
                "running": running,
                "ready": bool(info.get('ready')) if running else False,
                "last_used": self.on_demand_last_used.get(name),
            }
        for name, info in self.started_services.items():
            if name in services:
                continue
            services[name] = {
                "conditional": False,
                "port": info.get('port'),
                "running": True,
                "ready": bool(info.get('ready')),
                "on_demand": bool(info.get('on_demand')),
            }
        return {
            "success": True,
            "services": services,
            "on_demand_registry": sorted(self.on_demand_registry.keys()),
        }

    def touch_on_demand_service(self, name: str) -> None:
        with self._meta_lock:
            if name in self.started_services and self.started_services[name].get('on_demand'):
                self.on_demand_last_used[name] = time.time()

    def ensure_on_demand_service(self, name: str, timeout_sec: int = 120) -> Tuple[bool, str]:
        with self._meta_lock:
            if name not in self.on_demand_registry:
                return False, "not_registered_on_demand"

            info = self.started_services.get(name)
            if info and info.get('ready') and self.pm.check_health(
                info['port'], info.get('type', 'llm')
            ):
                self.on_demand_last_used[name] = time.time()
                return True, "already_running"

            cfg = self.on_demand_registry[name]
            port = cfg['port']
            if self.pm.is_port_in_use(port) and self.pm.check_health(port, cfg['type']):
                self.started_services[name] = {
                    **cfg,
                    'ready': True,
                    'on_demand': True,
                    'external': True,
                }
                self.on_demand_last_used[name] = time.time()
                return True, "already_running"

            _logger.info(f"[META] On-demand start requested: {name}", sync=True)
            if not self._start_from_config(cfg, on_demand=True):
                return False, "start_failed"

            deadline = time.time() + max(30, timeout_sec)
            while time.time() < deadline:
                info = self.started_services.get(name)
                if info and info.get('ready'):
                    self.on_demand_last_used[name] = time.time()
                    return True, "started"
                time.sleep(1)

            return False, "start_timeout"

    def release_on_demand_service(self, name: str) -> Tuple[bool, str]:
        with self._meta_lock:
            info = self.started_services.get(name)
            if not info or not info.get('on_demand'):
                return True, "not_active_on_demand"
            if info.get('external'):
                self.started_services.pop(name, None)
                self.on_demand_last_used.pop(name, None)
                return True, "external_detached"

            _logger.info(f"[META] Releasing on-demand service: {name}", sync=True)
            self.pm.stop_service(name)
            self.started_services.pop(name, None)
            self.on_demand_last_used.pop(name, None)
            return True, "released"

    def _release_idle_on_demand_services(self) -> None:
        now = time.time()
        with self._meta_lock:
            candidates = [
                name for name, info in self.started_services.items()
                if info.get('on_demand') and not info.get('external')
            ]
        for name in candidates:
            last_used = self.on_demand_last_used.get(name, 0.0)
            if now - last_used >= self.on_demand_idle_sec:
                _logger.info(
                    f"[META] Idle timeout ({self.on_demand_idle_sec}s) — releasing {name}",
                    sync=True,
                )
                self.release_on_demand_service(name)
    
    def deploy(self) -> bool:
        """部署所有模型服務（循序部署以確保穩定性）"""
        
        _logger.info("=" * 80, sync=True)
        _logger.info("Seele v8.5.1 Deployment System - Sequential Mode", sync=True)
        _logger.info("=" * 80, sync=True)
        
        svcs = sorted(
            self.config.get('services', []),
            key=lambda x: x.get('priority', 99)
        )
        
        if not svcs:
            _logger.error("No services defined in config", sync=True)
            return False
        
        _logger.info("[STARTUP] Launching services one-by-one...", sync=True)
        
        self.started_services = {}
        self.on_demand_registry = {}
        critical_failed = False
        deploy_all = os.getenv("SEELE_DEPLOY_ALL", "").lower() == "true"
        profile = self._load_hardware_profile() or {}
        conditional_names = set(get_conditional_service_names(profile))
        resident_names = set(get_resident_service_names(profile))
        
        if conditional_names and not deploy_all:
            _logger.info(
                f"[META] Conditional on-demand services: {sorted(conditional_names)}",
                sync=True,
            )
        if resident_names:
            _logger.info(
                f"[META] Resident always-on services: {sorted(resident_names)}",
                sync=True,
            )
        
        for i, s in enumerate(svcs):
            cfg = self._prepare_service_config(s)
            is_conditional = bool(cfg.get('conditional')) or s['name'] in conditional_names

            if is_conditional and not deploy_all:
                self.on_demand_registry[s['name']] = cfg
                _logger.info(
                    f"[ON-DEMAND] Registered {s['name']} (port {cfg['port']}) — skipped at startup",
                    sync=True,
                )
                continue

            priority_level = cfg['priority_level']
            
            _logger.info(
                f"[STEP {i+1}/{len(svcs)}] Deploying {s['name']} "
                f"(GPU: {cfg['gpu_layers']}, Priority: {priority_level})",
                sync=True
            )
            
            if self._start_from_config(cfg, on_demand=False):
                ready_count = sum(
                    1 for info in self.started_services.values()
                    if info.get('ready', False)
                )
                _logger.info(
                    f"[PROGRESS] {ready_count} resident service(s) ready",
                    sync=True,
                )
            else:
                if priority_level == 'critical':
                    critical_failed = True
                    _logger.critical(
                        f"[FAILED] CRITICAL service {s['name']} failed to start",
                        sync=True,
                    )
                else:
                    _logger.warning(
                        f"[FAILED] {s['name']} startup failed (non-critical)",
                        sync=True,
                    )

            if critical_failed:
                _logger.error("[ABORT] Critical failure detected. Stopping deployment.", sync=True)
                return False

        self.running = True
        self._start_meta_http_server()
        ready_count = sum(
            1 for info in self.started_services.values() if info.get('ready', False)
        )
        on_demand_count = len(self.on_demand_registry)
        if ready_count == 0:
            _logger.error("[ABORT] No resident services are running.", sync=True)
            return False
        if on_demand_count:
            _logger.info(
                f"[META] Resident ready: {ready_count}; on-demand registered: {on_demand_count}",
                sync=True,
            )
        _logger.info(
            f"[SUCCESS] Deployment completed. {ready_count} resident service(s) ready.",
            sync=True,
        )
        return True
    
    def monitor(self, duration: int = 86400) -> None:
        """監控服務運行，包含資源追蹤與自癒機制"""
        _logger.info(f"[MONITOR] Running for {duration} seconds...", sync=True)
        
        start = time.time()
        metrics_interval = 60
        health_interval = 30
        
        last_metrics_time = 0.0
        last_health_time = 0.0
        
        while time.time() - start < duration and self.running:
            now = time.time()
            
            if now - last_metrics_time > metrics_interval:
                gpu_status = self.gpu_monitor.get_gpu_status(force_refresh=True)
                cpu_usage = psutil.cpu_percent()
                ram_usage = psutil.virtual_memory().percent
                
                status_msg = f"[MONITOR] Sys: CPU {cpu_usage}%, RAM {ram_usage}% | GPU: {round(gpu_status.get('usable_mb', 0), 0)}MB Free"
                _logger.info(status_msg)
                
                if cpu_usage > 85 or ram_usage > 85:
                    _logger.critical(f"[AUTOSCALE] HIGH LOAD DETECTED ({max(cpu_usage, ram_usage)}%). Triggering resource re-allocation...")
                    self._handle_high_load_emergency()
                
                last_metrics_time = now
            
            if now - last_health_time > health_interval:
                self._check_and_heal_services()
                self._release_idle_on_demand_services()
                last_health_time = now
            
            time.sleep(5)
        
        _logger.info("[MONITOR] Monitoring ended", sync=True)
    
    def _check_and_heal_services(self) -> None:
        """檢查所有服務的健康狀況，如果失效則重啟"""
        cpu_usage = psutil.cpu_percent()
        ram_usage = psutil.virtual_memory().percent
        is_strained = cpu_usage > 88 or ram_usage > 88
        
        with self.pm._lock:
            active_services = list(self.started_services.keys())
            
        for name in active_services:
            svc = self.started_services[name]
            port = svc['port']
            priority = svc['priority_level']
            
            process = self.pm.process_objects.get(name)
            is_dead = not process or process.poll() is not None
            
            if is_dead:
                if is_strained and priority != 'critical':
                    _logger.warning(f"[SELF-HEALING] Skipping revival of {name} due to high system load ({max(cpu_usage, ram_usage)}%).")
                    continue
                    
                _logger.error(f"[SELF-HEALING] Service {name} is DEAD. Attempting restart...")
                self._restart_service(name)
                continue
                
            if not self.pm.check_health(port, svc['type']):
                _logger.warning(f"[SELF-HEALING] Service {name} is UNRESPONSIVE. Attempting restart...")
                self._restart_service(name)

    def _restart_service(self, name: str) -> None:
        """重啟特定服務"""
        svc = self.started_services[name]
        
        _logger.info(f"[RESTART] Stopping {name} before restart...")
        self.pm.stop_service(name)
        time.sleep(2)
        
        _logger.info(f"[RESTART] Launching new instance of {name}...")
        pid = self.pm.start_service(
            name,
            svc['model_path'],
            svc['port'],
            svc['gpu_layers'],
            svc['type'],
            svc['n_threads'],
            svc['n_ctx'],
            svc['timeout_sec'],
            retry_count=2
        )
        
        if pid:
            self.started_services[name]['pid'] = pid
            _logger.info(f"[RESTART] {name} successfully recovered with PID {pid}")
        else:
            _logger.critical(f"[RESTART] Recovery failed for {name}!")

    def _handle_high_load_emergency(self) -> None:
        """緊急負載處理：根據優先級重新分配資源"""
        with self.pm._lock:
            targets = [
                n for n, s in self.started_services.items()
                if s['priority_level'] != 'critical'
            ]
            targets.sort(
                key=lambda n: (0 if self.started_services[n].get('on_demand') else 1)
            )
            
        if not targets:
            _logger.warning("[AUTOSCALE] No non-critical services to throttle. System at hard limit.")
            return

        _logger.warning(f"[AUTOSCALE] Attempting to offload non-critical services: {targets}")
        
        for name in targets:
            svc = self.started_services[name]
            
            mem_usage = psutil.virtual_memory().percent
            if mem_usage > 90:
                _logger.critical(f"[AUTOSCALE] EXTREME LOAD ({mem_usage}%). Terminating {name} to preserve core system stability.")
                self.pm.stop_service(name)
                continue
            
            original_threads = svc.get('n_threads', 4)
            throttled_threads = max(1, original_threads // 2)
            
            _logger.info(f"[AUTOSCALE] Throttling {name}: threads {original_threads} -> {throttled_threads}")
            
            self.started_services[name]['n_threads'] = throttled_threads
            
            self._restart_service(name)
            
            time.sleep(10)
            if psutil.cpu_percent() < 85 and psutil.virtual_memory().percent < 85:
                _logger.info("[AUTOSCALE] System load stabilized. Throttling sequence paused.")
                break

    def shutdown(self) -> None:
        """關閉所有服務"""
        if not self.running and not self.started_services:
            self._stop_meta_http_server()
            return
        
        _logger.info("Shutting down all services...", sync=True)
        
        for name in list(self.started_services.keys()):
            self.pm.stop_service(name)
        
        self.started_services.clear()
        self.on_demand_last_used.clear()
        self._stop_meta_http_server()
        self._executor.shutdown(wait=False)
        self.running = False
        
        _logger.info("System shutdown complete", sync=True)
        _logger.shutdown()

# ============================================================================
# 【主程式入口】
# ============================================================================

def main() -> int:
    """主程式"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Seele v8.5.1 Unified Orchestration System',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--action',
        choices=['deploy', 'shutdown', 'monitor'],
        default='deploy',
        help='Action to perform'
    )
    parser.add_argument(
        '--config',
        default='config.json',
        help='Config file path'
    )
    parser.add_argument(
        '--models-dir',
        default='models',
        help='Models directory'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=86400,
        help='Monitor duration (seconds)'
    )
    
    args = parser.parse_args()
    
    orc = SeeleUnifiedOrchestrator(args.config, args.models_dir)
    
    try:
        if args.action == 'deploy':
            if orc.deploy():
                orc.monitor(duration=args.duration)
                return 0
            else:
                return 1
        
        elif args.action == 'shutdown':
            orc.shutdown()
            return 0
        
        elif args.action == 'monitor':
            orc.monitor(duration=args.duration)
            return 0
    
    except KeyboardInterrupt:
        _logger.info("Received interrupt signal", sync=True)
        orc.shutdown()
        return 130
    
    except Exception as e:
        _logger.critical(
            f"Critical error: {e}",
            context={'traceback': traceback.format_exc()},
            sync=True
        )
        orc.shutdown()
        return 1
    
    finally:
        if orc and orc.running:
            orc.shutdown()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())