# app/utils/health_check.py
# 系統健康檢查系統 - 修正版本 (Async 完整版)

import asyncio
import logging
import time
import json
import os
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field, asdict
from contextlib import asynccontextmanager
import functools

# 嘗試導入依賴，如果不存在則使用 Mock（確保代碼可獨立檢查）
try:
    from app.config import config
except ImportError:
    class MockConfig:
        HIGH_RISK_SESSION_THRESHOLD = 10
        AUTO_CLEANUP_OLD_SESSIONS = False
        ALERT_RECOVERY_TIMEOUT = 300
    config = MockConfig()

try:
    from app.logger import get_app_logger, get_health_logger
except ImportError:
    def get_app_logger(name: str):
        return logging.getLogger(name)
    def get_health_logger(name: str):
        return logging.getLogger(f"health.{name}")

app_logger = get_app_logger('health_check')
health_logger = get_health_logger('health')


# ============ 數據結構 ============

class ServiceStatus(Enum):
    """服務狀態枚舉"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealthReport:
    """單個組件健康報告"""
    component_name: str
    status: str  # 'ok', 'warning', 'down'
    response_time_ms: float
    last_check_time: str
    error_message: Optional[str] = None
    error_count: int = 0
    recovery_attempts: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemMetrics:
    """系統整體指標"""
    timestamp: str
    uptime_hours: float
    total_sessions_processed: int
    active_sessions_count: int
    high_risk_sessions_count: int
    total_escalations: int
    average_response_time_ms: float
    error_rate_percent: float
    redis_memory_usage_mb: float
    db_size_mb: float
    system_status: str


@dataclass
class HealthCheckReport:
    """完整的健康檢查報告"""
    timestamp: str
    overall_status: str
    system_start_time: str
    check_duration_ms: float
    components: Dict[str, ComponentHealthReport]
    metrics: SystemMetrics
    alerts: List[str]
    recommendations: List[str]
    last_escalation_event: Optional[Dict[str, Any]] = None


# ============ 執行緒安全輔助類 ============

class AsyncSafeHistory:
    """Async 安全的狀態歷史記錄器"""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._data: Dict[str, List[Dict]] = {
            'redis': [], 'database': [], 'llm': [], 
            'session_manager': [], 'overall': []
        }
        self._lock = asyncio.Lock()
    
    async def append(self, component: str, record: Dict):
        async with self._lock:
            if component not in self._data:
                self._data[component] = []
            self._data[component].append(record)
            if len(self._data[component]) > self.max_size:
                self._data[component].pop(0)
    
    async def get(self, component: str, limit: int = 50) -> List[Dict]:
        async with self._lock:
            history = self._data.get(component, [])
            return history[-limit:] if history else []
    
    async def get_all_stats(self) -> Dict[str, List[Dict]]:
        async with self._lock:
            return {k: v.copy() for k, v in self._data.items()}


# ============ 健康檢查主類 (Async 版本) ============

class HealthCheckManager:
    """
    【已修正】Async 版健康檢查管理器
    
    修正項目：
    1. 所有阻塞操作改為非阻塞執行（run_in_executor）
    2. 加入 Async 鎖確保資料一致性
    3. 修正 Redis 資源洩漏問題
    4. 安全存取配置項（使用 getattr）
    5. 修正異常處理，避免未捕獲的例外終止檢查迴圈
    """
    
    STATUS_HISTORY_SIZE = 100
    
    def __init__(
        self,
        redis_client=None,
        db_manager=None,
        llm_service=None,
        session_manager=None
    ):
        self.redis = redis_client
        self.db = db_manager
        self.llm = llm_service
        self.session_manager = session_manager
        
        self.start_time = datetime.now()
        self.component_history = AsyncSafeHistory(self.STATUS_HISTORY_SIZE)
        
        # 指標統計（使用執行緒安全機制）
        self.metrics_stats = {
            'total_sessions': 0,
            'total_escalations': 0,
            'total_errors': 0,
            'response_times': []
        }
        self._stats_lock = asyncio.Lock()
        
        # 告警和恢復
        self.active_alerts: Dict[str, Dict] = {}
        self.recovery_callbacks: Dict[str, Any] = {}
        self._alerts_lock = asyncio.Lock()
        
        # Async 控制
        self._check_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
        app_logger.info("[HEALTH INIT] Async 健康檢查管理器已初始化")

    async def start(self):
        """Async 啟動健康檢查"""
        if self._check_task is not None and not self._check_task.done():
            app_logger.warning("[HEALTH] 健康檢查已在運行")
            return

        self._stop_event.clear()
        self._check_task = asyncio.create_task(
            self._continuous_health_check_async(),
            name="health_check_loop"
        )
        app_logger.info("[HEALTH START] Async 後台健康檢查已啟動")

    async def stop(self):
        """Async 優雅停止"""
        app_logger.info("[HEALTH STOP] 正在停止健康檢查...")
        self._stop_event.set()
        
        if self._check_task:
            self._check_task.cancel()
            try:
                await asyncio.wait_for(self._check_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._check_task = None
            
        app_logger.info("[HEALTH STOP] Async 健康檢查已停止")

    async def _continuous_health_check_async(self):
        """【核心】Async 持續檢查迴圈"""
        quick_interval = 10
        detailed_interval = 60
        full_interval = 300

        last_detailed = time.time()
        last_full = time.time()

        while not self._stop_event.is_set():
            try:
                current = time.time()

                # 快速檢查
                await self.perform_quick_check_async()

                # 詳細檢查
                if current - last_detailed >= detailed_interval:
                    await self.perform_detailed_check_async()
                    last_detailed = current

                # 完整檢查
                if current - last_full >= full_interval:
                    await self.perform_full_check_async()
                    last_full = current

                await self._process_alerts_async()

                # 使用 wait_for 以支援優雅關閉
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), 
                        timeout=quick_interval
                    )
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                app_logger.info("[HEALTH] 接收到取消訊號，準備停止...")
                break
            except Exception as e:
                app_logger.error(f"[HEALTH CHECK LOOP] 未預期錯誤: {e}", exc_info=True)
                await asyncio.sleep(10)

    # ============ Async 檢查級別 ============

    async def perform_quick_check_async(self) -> Dict[str, Any]:
        """快速檢查（Async 版本）"""
        results = {}
        
        # Redis 快速檢查
        try:
            if self.redis:
                # 在執行緒池中執行阻塞操作
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.redis.ping)
                results['redis'] = True
            else:
                results['redis'] = None
        except Exception as e:
            app_logger.warning(f"[QUICK CHECK] Redis 異常: {e}")
            results['redis'] = False
        
        # 數據庫快速檢查
        try:
            if self.db:
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, self.db.get_db_stats)
                results['database'] = stats is not None
            else:
                results['database'] = None
        except Exception as e:
            app_logger.warning(f"[QUICK CHECK] Database 異常: {e}")
            results['database'] = False
        
        return results

    async def perform_detailed_check_async(self) -> HealthCheckReport:
        """詳細檢查（Async 版本）"""
        start_time = time.time()
        
        # 並行執行各組件檢查
        redis_report, db_report, llm_report, session_report = await asyncio.gather(
            self._check_redis_detailed_async(),
            self._check_database_detailed_async(),
            self._check_llm_detailed_async(),
            self._check_session_manager_detailed_async(),
            return_exceptions=True
        )
        
        # 處理可能的例外
        reports = {
            'redis': redis_report if not isinstance(redis_report, Exception) else self._create_error_report('redis', redis_report),
            'database': db_report if not isinstance(db_report, Exception) else self._create_error_report('database', db_report),
            'llm': llm_report if not isinstance(llm_report, Exception) else self._create_error_report('llm', llm_report),
            'session_manager': session_report if not isinstance(session_report, Exception) else self._create_error_report('session_manager', session_report)
        }
        
        metrics = await self._collect_metrics_async()
        overall_status = self._determine_overall_status(reports)
        alerts = self._generate_alerts(reports, metrics)
        recommendations = self._generate_recommendations(reports, metrics)
        
        check_duration = (time.time() - start_time) * 1000
        
        report = HealthCheckReport(
            timestamp=datetime.now().isoformat(),
            overall_status=overall_status,
            system_start_time=self.start_time.isoformat(),
            check_duration_ms=check_duration,
            components=reports,
            metrics=metrics,
            alerts=alerts,
            recommendations=recommendations
        )
        
        await self.component_history.append('overall', {
            'status': overall_status,
            'time': datetime.now().isoformat()
        })
        
        health_logger.info(f"[DETAILED CHECK] Status: {overall_status}, Duration: {check_duration:.2f}ms")
        return report

    async def perform_full_check_async(self) -> HealthCheckReport:
        """完整檢查（Async 版本）"""
        start_time = time.time()
        
        # 執行詳細檢查
        report = await self.perform_detailed_check_async()
        
        # 額外檢查
        if self.db:
            try:
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, self.db.get_db_stats)
                
                # 檢查活躍會話數
                active_count = stats.get('active_sessions', 0) if stats else 0
                if active_count > 1000:
                    app_logger.warning(f"[FULL CHECK] 活躍會話數過高: {active_count}")
                    report.recommendations.append(
                        "活躍會話數超過1000，建議歸檔舊會話以減少記憶體佔用"
                    )
                
                # 檢查高風險會話
                high_risk = await loop.run_in_executor(
                    None, self.db.get_active_high_risk_sessions
                )
                threshold = getattr(config, 'HIGH_RISK_SESSION_THRESHOLD', 10)
                if isinstance(high_risk, list) and len(high_risk) > threshold:
                    app_logger.critical(f"[FULL CHECK] 高風險會話數: {len(high_risk)}")
                    report.alerts.append(
                        f"嚴重警告: 存在 {len(high_risk)} 個高風險會話"
                    )
                
                # 【修正】安全存取配置項
                auto_cleanup = getattr(config, 'AUTO_CLEANUP_OLD_SESSIONS', False)
                if auto_cleanup:
                    try:
                        deleted = await loop.run_in_executor(
                            None, functools.partial(self.db.cleanup_old_sessions, days=90)
                        )
                        if deleted > 0:
                            app_logger.info(f"[FULL CHECK] 已清理 {deleted} 個舊會話")
                    except Exception as e:
                        app_logger.error(f"[FULL CHECK] 清理失敗: {e}")
                        
            except Exception as e:
                app_logger.error(f"[FULL CHECK] 數據庫檢查失敗: {e}")
        
        check_duration = (time.time() - start_time) * 1000
        report.check_duration_ms = check_duration
        
        health_logger.info(f"[FULL CHECK] 完成，耗時 {check_duration:.2f}ms")
        return report

    # ============ Async 組件檢查 ============

    async def _check_redis_detailed_async(self) -> ComponentHealthReport:
        """詳細檢查 Redis（Async 版本）"""
        start_time = time.time()
        error_msg = None
        status = 'ok'
        metadata: Dict[str, Any] = {}
        
        try:
            if not self.redis:
                return ComponentHealthReport(
                    component_name='redis',
                    status='unknown',
                    response_time_ms=0,
                    last_check_time=datetime.now().isoformat()
                )
            
            loop = asyncio.get_event_loop()
            
            # 1. Ping 測試
            await loop.run_in_executor(None, self.redis.ping)
            
            # 2. 寫入測試（帶自動清理）
            test_key = f"health_check:{int(time.time())}"
            try:
                await loop.run_in_executor(
                    None, functools.partial(self.redis.setex, test_key, 10, "ok")
                )
                test_value = await loop.run_in_executor(None, self.redis.get, test_key)
                
                if test_value != b"ok" and test_value != "ok":
                    status = 'warning'
                    error_msg = "Redis 讀寫測試失敗"
            finally:
                # 【修正】確保清理測試鍵
                try:
                    await loop.run_in_executor(None, self.redis.delete, test_key)
                except:
                    pass
            
            # 3. 內存使用
            try:
                info = await loop.run_in_executor(None, self.redis.info, 'memory')
                memory_usage = info.get('used_memory_human', 'unknown')
                memory_bytes = info.get('used_memory', 0)
                metadata['memory_usage'] = memory_usage
                metadata['memory_usage_mb'] = memory_bytes / (1024 * 1024) if memory_bytes else 0
            except Exception as e:
                metadata['memory_error'] = str(e)
            
            # 4. 連接數
            try:
                info = await loop.run_in_executor(None, self.redis.info, 'clients')
                metadata['connected_clients'] = info.get('connected_clients', 0)
            except Exception as e:
                metadata['clients_error'] = str(e)
            
            response_time = (time.time() - start_time) * 1000
            
            report = ComponentHealthReport(
                component_name='redis',
                status=status,
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=error_msg,
                metadata=metadata
            )
            
            await self.component_history.append('redis', {
                'status': status,
                'time': datetime.now().isoformat(),
                'response_time_ms': response_time
            })
            
            return report
            
        except ConnectionError as e:
            response_time = (time.time() - start_time) * 1000
            return ComponentHealthReport(
                component_name='redis',
                status='down',
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=f"連線失敗: {str(e)}",
                error_count=1
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            app_logger.error(f"[REDIS CHECK] 錯誤: {e}")
            return ComponentHealthReport(
                component_name='redis',
                status='down',
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=str(e),
                error_count=1
            )

    async def _check_database_detailed_async(self) -> ComponentHealthReport:
        """詳細檢查數據庫（Async 版本）"""
        start_time = time.time()
        error_msg = None
        status = 'ok'
        metadata: Dict[str, Any] = {}
        
        try:
            if not self.db:
                return ComponentHealthReport(
                    component_name='database',
                    status='unknown',
                    response_time_ms=0,
                    last_check_time=datetime.now().isoformat()
                )
            
            loop = asyncio.get_event_loop()
            
            # 基本連接測試
            stats = await loop.run_in_executor(None, self.db.get_db_stats)
            
            if stats:
                metadata = {
                    'active_sessions': stats.get('active_sessions', 0),
                    'high_risk_sessions': stats.get('high_risk_sessions', 0),
                    'archived_sessions': stats.get('total_archived_sessions', 0),
                    'total_escalations': stats.get('total_escalations', 0),
                    'unconfirmed_escalations': stats.get('unconfirmed_escalations', 0)
                }
                
                # 檢查未確認升級
                if metadata.get('unconfirmed_escalations', 0) > 10:
                    status = 'warning'
                    error_msg = f"未確認升級事件過多: {metadata['unconfirmed_escalations']}"
            
            response_time = (time.time() - start_time) * 1000
            
            report = ComponentHealthReport(
                component_name='database',
                status=status,
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=error_msg,
                metadata=metadata
            )
            
            await self.component_history.append('database', {
                'status': status,
                'time': datetime.now().isoformat(),
                'response_time_ms': response_time
            })
            
            return report
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            app_logger.error(f"[DATABASE CHECK] 錯誤: {e}")
            return ComponentHealthReport(
                component_name='database',
                status='down',
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=str(e),
                error_count=1
            )

    async def _check_llm_detailed_async(self) -> ComponentHealthReport:
        """詳細檢查 LLM 服務（Async 版本）"""
        start_time = time.time()
        error_msg = None
        status = 'ok'
        
        try:
            if not self.llm:
                return ComponentHealthReport(
                    component_name='llm',
                    status='degraded',
                    response_time_ms=0,
                    last_check_time=datetime.now().isoformat(),
                    error_message='LLM 服務未配置'
                )
            
            # 檢查 LLM 健康狀態
            if hasattr(self.llm, 'health_check'):
                loop = asyncio.get_event_loop()
                # 如果 health_check 是同步的，在執行緒中執行
                if asyncio.iscoroutinefunction(self.llm.health_check):
                    result = await self.llm.health_check()
                else:
                    result = await loop.run_in_executor(None, self.llm.health_check)
                
                if not result:
                    status = 'warning'
                    error_msg = "LLM 健康檢查返回 False"
            
            response_time = (time.time() - start_time) * 1000
            
            metadata = {'fallback_enabled': status != 'ok'}
            
            report = ComponentHealthReport(
                component_name='llm',
                status=status,
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=error_msg,
                metadata=metadata
            )
            
            await self.component_history.append('llm', {
                'status': status,
                'time': datetime.now().isoformat(),
                'response_time_ms': response_time
            })
            
            return report
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            app_logger.warning(f"[LLM CHECK] 警告: {e}")
            return ComponentHealthReport(
                component_name='llm',
                status='degraded',
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=str(e),
                metadata={'fallback_enabled': True}
            )

    async def _check_session_manager_detailed_async(self) -> ComponentHealthReport:
        """詳細檢查會話管理器（Async 版本）"""
        start_time = time.time()
        
        try:
            if not self.session_manager:
                return ComponentHealthReport(
                    component_name='session_manager',
                    status='unknown',
                    response_time_ms=0,
                    last_check_time=datetime.now().isoformat()
                )
            
            # 【修正】實際執行會話操作測試
            loop = asyncio.get_event_loop()
            metadata: Dict[str, Any] = {}
            
            try:
                # 測試獲取活躍會話數（如果支援）
                if hasattr(self.session_manager, 'get_active_count'):
                    if asyncio.iscoroutinefunction(self.session_manager.get_active_count):
                        count = await self.session_manager.get_active_count()
                    else:
                        count = await loop.run_in_executor(None, self.session_manager.get_active_count)
                    metadata['active_sessions'] = count
            except Exception as e:
                metadata['count_error'] = str(e)
            
            response_time = (time.time() - start_time) * 1000
            
            report = ComponentHealthReport(
                component_name='session_manager',
                status='ok',
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                metadata=metadata
            )
            
            await self.component_history.append('session_manager', {
                'status': 'ok',
                'time': datetime.now().isoformat(),
                'response_time_ms': response_time
            })
            
            return report
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            app_logger.error(f"[SESSION MANAGER CHECK] 錯誤: {e}")
            return ComponentHealthReport(
                component_name='session_manager',
                status='degraded',
                response_time_ms=response_time,
                last_check_time=datetime.now().isoformat(),
                error_message=str(e),
                error_count=1
            )

    # ============ 輔助方法 ============

    def _create_error_report(self, component_name: str, error: Exception) -> ComponentHealthReport:
        """創建錯誤報告"""
        return ComponentHealthReport(
            component_name=component_name,
            status='down',
            response_time_ms=0,
            last_check_time=datetime.now().isoformat(),
            error_message=f"檢查過程中拋出例外: {str(error)}",
            error_count=1
        )

    async def _collect_metrics_async(self) -> SystemMetrics:
        """收集系統指標（Async 版本）"""
        uptime = (datetime.now() - self.start_time).total_seconds() / 3600
        
        # 從數據庫獲取統計
        active_sessions = high_risk_sessions = total_escalations = 0
        if self.db:
            try:
                loop = asyncio.get_event_loop()
                stats = await loop.run_in_executor(None, self.db.get_db_stats)
                if stats:
                    active_sessions = stats.get('active_sessions', 0)
                    high_risk_sessions = stats.get('high_risk_sessions', 0)
                    total_escalations = stats.get('total_escalations', 0)
            except Exception as e:
                app_logger.error(f"[METRICS] 獲取數據庫統計失敗: {e}")
        
        # 計算響應時間平均值
        async with self._stats_lock:
            recent_times = self.metrics_stats['response_times'][-100:]
            avg_response_time = sum(recent_times) / len(recent_times) if recent_times else 0
        
        # 計算錯誤率
        history_data = await self.component_history.get_all_stats()
        total_ops = sum(len(h) for h in history_data.values() if isinstance(h, list))
        error_count = sum(
            1 for h in history_data.values() 
            if isinstance(h, list) for item in h 
            if isinstance(item, dict) and item.get('status') != 'ok'
        )
        error_rate = (error_count / total_ops * 100) if total_ops > 0 else 0
        
        # Redis 內存使用
        redis_memory = 0.0
        if self.redis:
            try:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(None, self.redis.info, 'memory')
                memory_bytes = info.get('used_memory', 0)
                redis_memory = float(memory_bytes) / (1024 * 1024) if memory_bytes else 0.0
            except Exception:
                pass
        
        # 數據庫大小
        db_size = 0.0
        if self.db and hasattr(self.db, 'db_path'):
            try:
                if os.path.exists(self.db.db_path):
                    db_size = os.path.getsize(self.db.db_path) / (1024 * 1024)
            except Exception:
                pass
        
        # 系統狀態判斷
        if active_sessions == 0:
            system_status = 'idle'
        elif high_risk_sessions > 0:
            system_status = 'handling_crisis'
        elif active_sessions > 10:
            system_status = 'high_load'
        else:
            system_status = 'normal'
        
        async with self._stats_lock:
            total_processed = self.metrics_stats['total_sessions']
        
        return SystemMetrics(
            timestamp=datetime.now().isoformat(),
            uptime_hours=uptime,
            total_sessions_processed=total_processed,
            active_sessions_count=active_sessions,
            high_risk_sessions_count=high_risk_sessions,
            total_escalations=total_escalations,
            average_response_time_ms=avg_response_time,
            error_rate_percent=error_rate,
            redis_memory_usage_mb=redis_memory,
            db_size_mb=db_size,
            system_status=system_status
        )

    def _determine_overall_status(self, components: Dict[str, ComponentHealthReport]) -> str:
        """決定整體狀態"""
        critical_components = ['database', 'redis']
        critical_down = any(
            components[comp].status == 'down' 
            for comp in critical_components 
            if comp in components
        )
        
        if critical_down:
            return ServiceStatus.CRITICAL.value
        
        has_warning = any(
            comp.status in ['warning', 'degraded'] 
            for comp in components.values()
        )
        
        if has_warning:
            return ServiceStatus.DEGRADED.value
        
        return ServiceStatus.HEALTHY.value

    def _generate_alerts(
        self,
        components: Dict[str, ComponentHealthReport],
        metrics: SystemMetrics
    ) -> List[str]:
        """生成告警"""
        alerts = []
        
        for name, report in components.items():
            if report.status == 'down':
                alerts.append(f"嚴重: {name} 服務已停止")
            elif report.status == 'warning':
                alerts.append(f"警告: {name} 存在問題")
        
        if metrics.average_response_time_ms > 1000:
            alerts.append(f"性能: 平均響應時間為 {metrics.average_response_time_ms:.0f}ms")
        
        if metrics.active_sessions_count > 100:
            alerts.append(f"負載: 存在 {metrics.active_sessions_count} 個活躍會話")
        
        if metrics.high_risk_sessions_count > 5:
            alerts.append(f"危機: 存在 {metrics.high_risk_sessions_count} 個高風險會話")
        
        if metrics.error_rate_percent > 5:
            alerts.append(f"錯誤率: {metrics.error_rate_percent:.1f}%")
        
        return alerts

    def _generate_recommendations(
        self,
        components: Dict[str, ComponentHealthReport],
        metrics: SystemMetrics
    ) -> List[str]:
        """生成建議"""
        recommendations = []
        
        for name, report in components.items():
            if report.status in ['warning', 'degraded']:
                if name == 'redis':
                    recommendations.append("考慮重新啟動 Redis 服務")
                elif name == 'database':
                    recommendations.append("檢查數據庫磁碟空間和性能")
                elif name == 'llm':
                    recommendations.append("LLM 服務不可用，已自動啟用 fallback 模式")
        
        if metrics.redis_memory_usage_mb > 1000:
            recommendations.append("Redis 內存使用量高，考慮清理舊會話數據")
        
        if metrics.db_size_mb > 500:
            recommendations.append("數據庫大小較大，考慮歸檔舊會話")
        
        if metrics.average_response_time_ms > 500:
            recommendations.append("響應時間較長，考慮優化 LLM 提示或增加計算資源")
        
        if metrics.high_risk_sessions_count > 3:
            recommendations.append("多個高危會話，建議人工檢查升級事件")
        
        return recommendations

    async def _process_alerts_async(self):
        """處理告警（Async 版本）"""
        async with self._alerts_lock:
            alerts_to_check = list(self.active_alerts.items())
        
        for component_name, alert_info in alerts_to_check:
            alert_duration = (datetime.now() - alert_info['started_at']).total_seconds()
            timeout = getattr(config, 'ALERT_RECOVERY_TIMEOUT', 300)
            
            if alert_duration > timeout:
                if component_name in self.recovery_callbacks:
                    try:
                        app_logger.info(f"[RECOVERY] 觸發 {component_name} 恢復機制")
                        callback = self.recovery_callbacks[component_name]
                        
                        # 支援 Async 回調
                        if asyncio.iscoroutinefunction(callback):
                            await callback()
                        else:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, callback)
                        
                        async with self._alerts_lock:
                            if component_name in self.active_alerts:
                                del self.active_alerts[component_name]
                    except Exception as e:
                        app_logger.error(f"[RECOVERY] {component_name} 恢復失敗: {e}")

    # ============ 公共 API ============

    def register_recovery_callback(self, component_name: str, callback):
        """註冊恢復回調（可為 sync 或 async 函數）"""
        self.recovery_callbacks[component_name] = callback
        app_logger.info(f"[HEALTH] 已註冊 {component_name} 的恢復回調")

    async def trigger_manual_check(self) -> HealthCheckReport:
        """手動觸發完整檢查"""
        return await self.perform_full_check_async()

    async def get_status_summary(self) -> Dict[str, Any]:
        """獲取簡潔的狀態摘要（Async 版本）"""
        redis_report = await self._check_redis_detailed_async()
        db_report = await self._check_database_detailed_async()
        llm_report = await self._check_llm_detailed_async()
        session_report = await self._check_session_manager_detailed_async()
        
        components = {
            'redis': redis_report,
            'database': db_report,
            'llm': llm_report,
            'session_manager': session_report
        }
        
        metrics = await self._collect_metrics_async()
        overall_status = self._determine_overall_status(components)
        
        return {
            'status': overall_status,
            'timestamp': datetime.now().isoformat(),
            'components': {
                name: {
                    'status': report.status,
                    'response_time_ms': report.response_time_ms
                }
                for name, report in components.items()
            },
            'metrics': {
                'active_sessions': metrics.active_sessions_count,
                'high_risk_sessions': metrics.high_risk_sessions_count,
                'average_response_time_ms': metrics.average_response_time_ms
            }
        }

    async def get_component_history(self, component_name: str, limit: int = 50) -> List[Dict]:
        """獲取特定組件的狀態歷史"""
        return await self.component_history.get(component_name, limit)

    async def export_metrics_for_monitoring(self) -> Dict[str, Any]:
        """導出監控指標"""
        metrics = await self._collect_metrics_async()
        return {
            'system_uptime_hours': metrics.uptime_hours,
            'active_sessions_total': metrics.active_sessions_count,
            'high_risk_sessions_total': metrics.high_risk_sessions_count,
            'escalation_events_total': metrics.total_escalations,
            'average_response_time_milliseconds': metrics.average_response_time_ms,
            'error_rate_percent': metrics.error_rate_percent,
            'redis_memory_megabytes': metrics.redis_memory_usage_mb,
            'database_size_megabytes': metrics.db_size_mb
        }

    async def update_session_stats(self, increment: int = 1):
        """更新會話統計（供外部呼叫）"""
        async with self._stats_lock:
            self.metrics_stats['total_sessions'] += increment


# ============ 向後兼容的同步包裝器 ============

class SimpleHealthCheck:
    """
    【已修正】簡化版健康檢查（同步版本，向後兼容）
    使用執行緒池執行 Async 管理器的操作
    """
    
    def __init__(self, redis_client, db_manager=None, llm_service=None):
        self._async_manager = HealthCheckManager(
            redis_client=redis_client,
            db_manager=db_manager,
            llm_service=llm_service
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def _get_loop(self):
        """獲取或創建事件迴圈"""
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            return asyncio.new_event_loop()
    
    def check_all(self) -> Dict[str, Any]:
        """執行所有健康檢查（同步接口）"""
        loop = self._get_loop()
        try:
            # 執行快速檢查
            result = loop.run_until_complete(
                self._async_manager.perform_quick_check_async()
            )
            return {
                'status': 'healthy' if all(v is True for v in result.values() if v is not None) else 'degraded',
                'timestamp': datetime.now().isoformat(),
                'checks': result
            }
        except Exception as e:
            return {
                'status': 'error',
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }


# ============ FastAPI 整合範例 ============

"""
# app/main.py 使用範例:

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.utils.health_check import HealthCheckManager

# 全域健康檢查管理器實例
health_manager: Optional[HealthCheckManager] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global health_manager
    # 初始化
    health_manager = HealthCheckManager(
        redis_client=app.state.redis,
        db_manager=app.state.db,
        llm_service=app.state.llm,
        session_manager=app.state.session_manager
    )
    
    # 啟動健康檢查
    await health_manager.start()
    yield
    # 優雅關閉
    await health_manager.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health_endpoint():
    if not health_manager:
        return {"status": "unknown", "error": "Health manager not initialized"}
    return await health_manager.get_status_summary()

@app.get("/health/detailed")
async def health_detailed():
    if not health_manager:
        return {"status": "unknown", "error": "Health manager not initialized"}
    report = await health_manager.trigger_manual_check()
    return {
        "timestamp": report.timestamp,
        "overall_status": report.overall_status,
        "components": {
            name: {
                "status": comp.status,
                "response_time_ms": comp.response_time_ms,
                "error": comp.error_message
            }
            for name, comp in report.components.items()
        },
        "metrics": {
            "active_sessions": report.metrics.active_sessions_count,
            "high_risk_sessions": report.metrics.high_risk_sessions_count,
            "uptime_hours": report.metrics.uptime_hours,
            "error_rate": report.metrics.error_rate_percent
        },
        "alerts": report.alerts,
        "recommendations": report.recommendations
    }
"""