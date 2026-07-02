# app/workers/twitch_worker.py - v2.1 Redis Queue Worker (生產級)
"""
Vita 2.0 - Redis Queue Processor Worker v2.1
職責：消費來自 Redis 隊列的消息，以恆定速率處理
與 Orchestrator 協作進行業務邏輯處理
增強特性：故障恢復、詳細日誌、性能監控
"""

import asyncio
import json
import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# 全局 Processor 實例
_processor_instance: Optional['QueueProcessor'] = None


class QueueProcessor:
    """Redis Queue 消息處理器（恆定速率控制）"""
    
    def __init__(
        self,
        redis_url: str,
        process_rate: float = 20.0,
        max_concurrent_tasks: int = 100,
        orchestrator: Optional[Any] = None,
        queue_name: str = "vita:chat:queue",
        connection_timeout: float = 10.0,
        message_timeout: float = 30.0
    ):
        """初始化 Queue Processor"""
        self.redis_url = redis_url
        self.process_rate = process_rate
        self.max_concurrent_tasks = max_concurrent_tasks
        self.orchestrator = orchestrator
        self.queue_name = queue_name
        self.connection_timeout = connection_timeout
        self.message_timeout = message_timeout
        
        # Redis 連接
        self.redis_client: Optional[aioredis.Redis] = None
        
        # 運行狀態
        self._is_running = False
        self._start_time = datetime.now(timezone.utc)
        self._last_heartbeat = datetime.now(timezone.utc)
        
        # 統計計數器
        self._processed_count = 0
        self._error_count = 0
        self._skipped_count = 0
        self._redis_error_count = 0
        self._total_latency_ms = 0
        
        # 並發控制
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        # 消息隊列（內部使用）
        self.message_queue: Optional[asyncio.Queue] = None
        
        logger.info(
            f"[INIT] QueueProcessor v2.1 initialized "
            f"[queue={queue_name}, rate={process_rate}msg/sec, "
            f"max_concurrent={max_concurrent_tasks}, "
            f"conn_timeout={connection_timeout}s]"
        )
    
    async def initialize(self) -> bool:
        """初始化 Redis 連接（帶重試機制）"""
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                self.redis_client = await asyncio.wait_for(
                    aioredis.from_url(
                        self.redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                        socket_keepalive=True,
                        socket_connect_timeout=self.connection_timeout,
                        socket_timeout=self.connection_timeout,
                    ),
                    timeout=self.connection_timeout
                )
                
                # 測試連接
                await asyncio.wait_for(
                    self.redis_client.ping(),
                    timeout=self.connection_timeout
                )
                
                logger.info(
                    f"[INIT] Redis Queue Processor connected successfully "
                    f"[attempt={retry_count + 1}]"
                )
                return True
            
            except asyncio.TimeoutError:
                retry_count += 1
                logger.warning(
                    f"[INIT] Redis connection timeout "
                    f"[attempt={retry_count}/{max_retries}]"
                )
                if retry_count < max_retries:
                    await asyncio.sleep(2 ** retry_count)
            
            except Exception as e:
                retry_count += 1
                logger.error(
                    f"[INIT] Redis connection failed "
                    f"[attempt={retry_count}/{max_retries}, error={e}]"
                )
                if retry_count < max_retries:
                    await asyncio.sleep(2 ** retry_count)
        
        logger.error(
            f"[INIT] Redis Queue Processor initialization failed "
            f"after {max_retries} attempts"
        )
        return False
    
    async def run(self) -> None:
        """主消息處理循環"""
        if not self.redis_client:
            logger.error("[RUN] Redis client not initialized, cannot start processor")
            return
        
        self._is_running = True
        self._start_time = datetime.now(timezone.utc)
        
        logger.info(
            f"[RUN] Queue Processor started "
            f"[rate={self.process_rate}msg/sec, queue={self.queue_name}]"
        )
        
        message_interval = 1.0 / self.process_rate
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        try:
            while self._is_running:
                try:
                    # 更新心跳
                    self._last_heartbeat = datetime.now(timezone.utc)
                    
                    # 從 Redis 隊列取消息
                    try:
                        message_json = await asyncio.wait_for(
                            self.redis_client.blpop(
                                self.queue_name,
                                timeout=1.0
                            ),
                            timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        # 隊列空或 Redis 超時，繼續
                        consecutive_errors = 0
                        await asyncio.sleep(0.1)
                        continue
                    
                    if not message_json:
                        consecutive_errors = 0
                        await asyncio.sleep(0.1)
                        continue
                    
                    # 解析消息
                    _, message_data = message_json
                    
                    try:
                        message = json.loads(message_data)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            f"[RUN] Invalid JSON message: {e} "
                            f"[data={message_data[:100]}]"
                        )
                        self._skipped_count += 1
                        consecutive_errors = 0
                        continue
                    
                    # 非同步處理消息（受並發限制）
                    asyncio.create_task(
                        self._process_message_with_limit(message)
                    )
                    
                    # 應用速率限制
                    await asyncio.sleep(message_interval)
                    consecutive_errors = 0
                
                except asyncio.CancelledError:
                    logger.info("[RUN] Queue Processor cancelled")
                    break
                
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(
                        f"[RUN] Processing loop error "
                        f"[error={e}, consecutive={consecutive_errors}]"
                    )
                    self._redis_error_count += 1
                    
                    # 連續錯誤過多時暫停
                    if consecutive_errors >= max_consecutive_errors:
                        logger.critical(
                            f"[RUN] Too many consecutive errors "
                            f"[count={consecutive_errors}], "
                            f"pausing for 30 seconds"
                        )
                        await asyncio.sleep(30)
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(min(1.0 * consecutive_errors, 5.0))
        
        finally:
            self._is_running = False
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
            avg_latency = (
                self._total_latency_ms / max(self._processed_count, 1)
            )
            
            logger.info(
                f"[RUN] Queue Processor stopped [OK] "
                f"[uptime={uptime:.1f}s, "
                f"processed={self._processed_count}, "
                f"errors={self._error_count}, "
                f"skipped={self._skipped_count}, "
                f"redis_errors={self._redis_error_count}, "
                f"avg_latency={avg_latency:.1f}ms]"
            )
    
    async def _process_message_with_limit(
        self,
        message: Dict[str, Any]
    ) -> bool:
        """在並發限制下處理消息"""
        async with self._semaphore:
            return await self._process_message(message)
    
    async def _process_message(self, message: Dict[str, Any]) -> bool:
        """處理單個消息"""
        start_time_ms = datetime.now(timezone.utc).timestamp() * 1000
        
        try:
            user_id = message.get('user_id')
            text = message.get('text')
            
            if not user_id or not text:
                logger.warning(
                    f"[PROCESS] Message missing required fields "
                    f"[user_id={user_id}, text_len={len(str(text))}]"
                )
                self._skipped_count += 1
                return False
            
            if not self.orchestrator:
                logger.error("[PROCESS] Orchestrator not available")
                self._error_count += 1
                return False
            
            # 構建 ChatRequest
            from app.schemas import ChatRequest
            
            request = ChatRequest(
                user_id=user_id,
                text=text,
                session_id=message.get('session_id'),
                language_hint=message.get('language_hint', 'yue-Hant'),
                source='queue_processor'
            )
            
            # 調用 Orchestrator（帶超時）
            try:
                result = await asyncio.wait_for(
                    self.orchestrator.process(
                        request=request,
                        language_hint=message.get('language_hint', 'yue-Hant')
                    ),
                    timeout=self.message_timeout
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"[PROCESS] Orchestrator timeout "
                    f"[user_id={user_id}, timeout={self.message_timeout}s]"
                )
                self._error_count += 1
                return False
            
            if result and result.get('success'):
                self._processed_count += 1
                
                # 記錄延遲
                latency_ms = (
                    datetime.now(timezone.utc).timestamp() * 1000 - start_time_ms
                )
                self._total_latency_ms += latency_ms
                
                # 危機檢測
                risk_level = result.get('risk_level', 0)
                if risk_level >= 3:
                    logger.warning(
                        f"[PROCESS] CRISIS DETECTED "
                        f"[user_id={user_id}, risk_level={risk_level}, "
                        f"latency={latency_ms:.1f}ms]"
                    )
                
                return True
            else:
                logger.warning(
                    f"[PROCESS] Orchestrator returned failure "
                    f"[user_id={user_id}, warnings={result.get('warnings')}]"
                )
                self._error_count += 1
                return False
        
        except Exception as e:
            logger.error(
                f"[PROCESS] Message processing exception "
                f"[error={e}, traceback={traceback.format_exc()[:200]}]"
            )
            self._error_count += 1
            return False
    
    async def shutdown(self) -> None:
        """優雅關閉"""
        logger.info("[SHUTDOWN] Queue Processor shutting down...")
        
        self._is_running = False
        
        if self.redis_client:
            try:
                await asyncio.wait_for(
                    self.redis_client.close(),
                    timeout=5.0
                )
                logger.info("[SHUTDOWN] Redis connection closed [OK]")
            except Exception as e:
                logger.error(f"[SHUTDOWN] Redis close error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取處理器統計"""
        uptime = (
            datetime.now(timezone.utc) - self._start_time
        ).total_seconds()
        
        throughput = round(
            self._processed_count / max(uptime, 1),
            2
        )
        
        avg_latency = round(
            self._total_latency_ms / max(self._processed_count, 1),
            2
        ) if self._processed_count > 0 else 0
        
        return {
            'status': 'running' if self._is_running else 'stopped',
            'messages_processed': self._processed_count,
            'messages_failed': self._error_count,
            'messages_skipped': self._skipped_count,
            'redis_errors': self._redis_error_count,
            'uptime_sec': round(uptime, 1),
            'throughput_msg_per_sec': throughput,
            'average_latency_ms': avg_latency,
            'process_rate_configured': self.process_rate,
            'last_heartbeat': self._last_heartbeat.isoformat(),
        }


async def initialize_queue_processor(
    redis_url: str,
    process_rate: float = 20.0,
    max_concurrent_tasks: int = 100,
    orchestrator: Optional[Any] = None,
    queue_name: str = "vita:chat:queue",
    connection_timeout: float = 10.0,
    message_timeout: float = 30.0
) -> Optional[QueueProcessor]:
    """初始化 Redis Queue Processor"""
    global _processor_instance
    
    try:
        processor = QueueProcessor(
            redis_url=redis_url,
            process_rate=process_rate,
            max_concurrent_tasks=max_concurrent_tasks,
            orchestrator=orchestrator,
            queue_name=queue_name,
            connection_timeout=connection_timeout,
            message_timeout=message_timeout
        )
        
        success = await processor.initialize()
        if not success:
            logger.error("[INIT] Queue Processor initialization failed")
            return None
        
        _processor_instance = processor
        logger.info(
            "[INIT] Queue Processor initialized successfully [OK]"
        )
        return processor
    
    except Exception as e:
        logger.error(f"[INIT] Queue Processor initialization error: {e}")
        return None


async def shutdown_queue_processor() -> None:
    """優雅關閉 Queue Processor"""
    global _processor_instance
    
    if _processor_instance:
        try:
            await _processor_instance.shutdown()
            logger.info("[SHUTDOWN] Queue Processor shutdown complete [OK]")
        except Exception as e:
            logger.error(f"[SHUTDOWN] Queue Processor shutdown error: {e}")
        finally:
            _processor_instance = None


def get_processor_stats() -> Dict[str, Any]:
    """獲取 Queue Processor 統計信息"""
    global _processor_instance
    
    if _processor_instance is None:
        return {
            'status': 'not_initialized',
            'messages_processed': 0,
            'uptime_sec': 0,
            'error': 'Processor instance not created'
        }
    
    return _processor_instance.get_stats()


async def enqueue_message(
    redis_url: str,
    message: Dict[str, Any],
    queue_name: str = "vita:chat:queue"
) -> bool:
    """將消息添加到 Redis 隊列"""
    connection_timeout = 5.0
    
    try:
        redis_client = await asyncio.wait_for(
            aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            ),
            timeout=connection_timeout
        )
        
        message_json = json.dumps(message)
        
        await asyncio.wait_for(
            redis_client.rpush(queue_name, message_json),
            timeout=connection_timeout
        )
        
        await redis_client.close()
        logger.debug(
            f"[ENQUEUE] Message enqueued successfully "
            f"[queue={queue_name}, size={len(message_json)}]"
        )
        return True
    
    except asyncio.TimeoutError:
        logger.error(f"[ENQUEUE] Operation timeout after {connection_timeout}s")
        return False
    
    except Exception as e:
        logger.error(f"[ENQUEUE] Failed to enqueue message: {e}")
        return False