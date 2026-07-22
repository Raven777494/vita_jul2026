# PersonalityModule/gsw_engine.py - 完整修復版 v8.3
"""
GSW 引擎 v8.3 - 永恆迴響記憶系統
修復問題：
1. 完整的異步初始化
2. 非同步操作完整 await
3. 向量搜索故障恢復
"""

import asyncio
import uuid
import json
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger('vita.gsw_engine')
AUTOBIOGRAPHY_MARKERS = (
    '我爸爸', '我媽媽', '我出世', '我細個', '我童年',
    '我以前住', '我家人', '我讀幼稚園', '我讀小學', '我讀中學',
)

try:
    from .echo_write_gate import (
        EchoWriteGate,
        sentiment_affect_intensity,
        is_immutable_soul_memory_id,
    )
except ImportError:  # pragma: no cover
    EchoWriteGate = None
    sentiment_affect_intensity = None
    is_immutable_soul_memory_id = None


class GSWEngine:
    """GSW 引擎 v8.3 - 永恆迴響記憶系統"""

    def __init__(
        self,
        config: Dict = None,
        vector_service=None,
        memory_manager=None,
        db_manager=None
    ):
        """
        初始化 GSW 引擎
        
        [修復 v8.3] 支持注入 db_manager 以支持異步操作
        """
        self.config = config or {}
        self.vector_service = vector_service
        self.memory_manager = memory_manager
        self.db_manager = db_manager
        self.logger = logger

        # [NEW] 異步初始化標誌
        self._initialized = False
        self._initialization_lock = asyncio.Lock()

        logger.info(
            "[INIT] GSWEngine v8.3 initialized "
            f"(vector_service={vector_service is not None}, "
            f"memory_manager={memory_manager is not None}, "
            f"db_manager={db_manager is not None})"
        )

    async def ensure_initialized(self) -> None:
        """[NEW] 確保初始化完成"""
        async with self._initialization_lock:
            if not self._initialized:
                # 延遲初始化邏輯
                self._initialized = True
                self.logger.debug("[INIT] Lazy initialization complete")

    async def search_memories(
        self,
        query_vector: List[float],
        k: int = 5,
        min_similarity: float = 0.5,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        [修復 v8.3] 異步搜索相似記憶 - 完整 await
        """
        await self.ensure_initialized()

        if not query_vector or len(query_vector) == 0:
            return []

        try:
            # 【修復】如果有 db_manager，使用異步方法
            if self.db_manager and hasattr(self.db_manager, 'async_db_manager'):
                try:
                    results = await self.db_manager.async_db_manager.search_similar_memories_async(
                        query_vector=query_vector,
                        k=k,
                        min_similarity=min_similarity,
                        user_id=user_id,
                    )
                    self.logger.debug(f"[SEARCH] Found {len(results)} memories via async DB")
                    return results
                except Exception as e:
                    self.logger.warning(f"[SEARCH] Async DB search failed: {e}")
                    # Fallback

            # Fallback：內存搜索
            if self.memory_manager:
                try:
                    results = await asyncio.to_thread(
                        self.memory_manager.search,
                        query_vector,
                        k
                    )
                    self.logger.debug(f"[SEARCH] Found {len(results)} memories via memory_manager")
                    return results if results else []
                except Exception as e:
                    self.logger.warning(f"[SEARCH] Memory manager search failed: {e}")

            return []

        except Exception as e:
            self.logger.error(f"[SEARCH] Vector search critical error: {e}")
            return []

    async def detect_drift(
        self,
        response_vector: List[float],
        user_input: str,
        session_state: Dict,
        restrict_memory: bool = False,
        candidate_k: int = 5,
        correlation_id: Optional[str] = None,
    ) -> Dict:
        """
        [修復 v8.3] 檢測漂移 - 完整 await
        """
        if not response_vector:
            return {
                'drift_score': 0.0,
                'closest_core_memory': None,
                'closest_distance': 1.0,
                'available': False,
                'correlation_id': correlation_id,
            }

        try:
            search_k = max(1, min(20, int(candidate_k)))
            if correlation_id:
                self.logger.debug(
                    f"[DRIFT][{correlation_id}] start (restrict_memory={restrict_memory}, candidate_k={search_k})"
                )
            similar_mems = await self.search_memories(
                response_vector,
                k=search_k,
                min_similarity=0.0
            )

            if restrict_memory:
                similar_mems = [
                    mem for mem in similar_mems
                    if self._is_allowed_restrict_memory_candidate(mem)
                ]

            if not similar_mems:
                return {
                    'drift_score': 0.0,
                    'closest_core_memory': None,
                    'closest_distance': 1.0,
                    'available': False,
                    'correlation_id': correlation_id,
                }

            closest = similar_mems[0]
            drift_score = 1.0 - closest.get('similarity', 0.5)

            return {
                'drift_score': drift_score,
                'closest_core_memory': closest,
                'closest_distance': drift_score,
                'available': True,
                'correlation_id': correlation_id,
            }

        except Exception as e:
            if correlation_id:
                self.logger.error(f"[DRIFT][{correlation_id}] Detection failed: {e}")
            else:
                self.logger.error(f"[DRIFT] Detection failed: {e}")
            return {
                'drift_score': 0.0,
                'closest_core_memory': None,
                'closest_distance': 1.0,
                'available': False,
                'correlation_id': correlation_id,
            }

    def _is_allowed_restrict_memory_candidate(self, memory: Dict[str, Any]) -> bool:
        """
        與 personality_module restrict_memory 一致的候選允許規則。
        """
        if not isinstance(memory, dict):
            return False

        memory_id = str(memory.get('id', ''))
        if memory_id.startswith(('core_', 'memory_', 'echo_')):
            return True

        metadata = memory.get('metadata', {})
        if isinstance(metadata, dict):
            memory_type = str(metadata.get('memory_type', '')).lower()
            source = str(metadata.get('source', '')).lower()
            if memory_type in {'core', 'canonical', 'eternal_echo'}:
                return True
            if source in {'core', 'canonical', 'eternal_echo', 'seele_childhood_canon'}:
                return True

        record_type = str(memory.get('record_type', '')).upper()
        if record_type in {'CORE', 'CANON', 'ETERNAL_ECHO'}:
            return True

        return False

    def judge_eternal_echo_generation(
        self,
        response: str,
        extracted_info: Dict,
        session_state: Dict
    ) -> Tuple[bool, float]:
        """
        判斷是否應生成永恆迴響
        
        Returns:
            (是否生成, 迴響分數)
        """
        trigger_keywords = [
            '感動', '心痛', '後悔', '原諒', '成長',
            '明白', '終於', '決定', '改變', '學會', '珍惜', '陪伴'
        ]

        keyword_score = (
            0.5 if any(kw in response for kw in trigger_keywords) else 0.0
        )

        sentiment = extracted_info.get('user_sentiment', {})
        if not isinstance(sentiment, dict):
            sentiment = {}
        # P7／P6.1：EmotionService 多用 valence/arousal，未必有 intensity
        if sentiment_affect_intensity is not None:
            sentiment_intensity = sentiment_affect_intensity(sentiment)
        else:
            try:
                sentiment_intensity = abs(float(sentiment.get('intensity', 0) or 0))
            except (TypeError, ValueError):
                sentiment_intensity = 0.0
        sentiment_score = 0.5 if sentiment_intensity > 0.6 else 0.0

        base_score = keyword_score + sentiment_score

        # drift-aware 雙因子：signal + alert_level
        raw_signal = extracted_info.get('narrative_drift_signal', 0.0)
        try:
            drift_signal = max(0.0, min(1.0, float(raw_signal)))
        except (TypeError, ValueError):
            drift_signal = 0.0

        alert_level = str(extracted_info.get('narrative_drift_alert_level', 'none')).lower()
        alert_floor = 0.0
        if alert_level == 'warning':
            alert_floor = 0.7
        elif alert_level == 'critical':
            alert_floor = 1.0

        effective_drift = max(drift_signal, alert_floor)

        # 高漂移直接阻斷，避免把漂移內容固化成永迴軌
        if effective_drift >= 0.85:
            return False, 0.0

        penalty_ratio = effective_drift * 0.8
        echo_score = max(0.0, min(1.0, base_score * (1.0 - penalty_ratio)))
        threshold = 0.75 if effective_drift >= 0.65 else 0.6

        # [修復 v8.3] 確保返回值類型
        policy_level = self._resolve_memory_policy_level(extracted_info, session_state)
        if policy_level == 'critical' and self._contains_autobiography_marker(response):
            return False, 0.0
        return echo_score >= threshold, float(echo_score)

    async def generate_and_store_echo(
        self,
        user_input: str,
        response: str,
        extracted_info: Dict,
        session_state: Dict,
        echo_score: float
    ) -> str:
        """
        [修復 v8.3] 生成並儲存永恆迴響 - 完整 await
        """
        await self.ensure_initialized()

        if not user_input or not response:
            return ""

        # P7：落盤前統一寫入閘（憲法級：空內容／hint／critical／正史 source）
        gate = EchoWriteGate() if EchoWriteGate is not None else None
        if gate is not None:
            pre = gate.evaluate_pre_store(
                user_input=user_input,
                response=response,
                echo_id="",
                echo_score=echo_score,
                metadata={
                    'source': 'eternal_echo',
                    'memory_type': 'eternal_echo',
                    'canon_mutable': False,
                },
                extracted_info=extracted_info if isinstance(extracted_info, dict) else {},
                session_state=session_state if isinstance(session_state, dict) else {},
                turn_info=extracted_info if isinstance(extracted_info, dict) else {},
                force=bool(
                    isinstance(extracted_info, dict)
                    and extracted_info.get('force_echo_store')
                ),
            )
            if not pre.allowed:
                self.logger.info(
                    f"[ECHO] Write gate denied at pre_store: {pre.deny_reason}"
                )
                if isinstance(extracted_info, dict):
                    extracted_info['echo_write_trace'] = pre.to_public_dict()
                if isinstance(session_state, dict):
                    session_state['echo_write_trace'] = pre.to_public_dict()
                    session_state['echo_write_allowed'] = False
                    session_state['echo_write_deny_reason'] = pre.deny_reason
                return ""

        echo_id = f"echo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        # P3.4／P7：echo id 永不可落在正史／核心前綴
        if is_immutable_soul_memory_id is not None:
            illegal = is_immutable_soul_memory_id(echo_id)
        else:
            illegal = echo_id.startswith(('memory_', 'core_', 'gold_hk_', 'canon_'))
        if illegal:
            self.logger.error(f"[ECHO] Illegal echo id generated: {echo_id}")
            return ""

        user_id = session_state.get('user_id', 'unknown')

        # 【修復 v8.3】獲取嵌入向量
        embedding = extracted_info.get('response_embedding')
        if not embedding and self.vector_service:
            try:
                embedding = await asyncio.to_thread(
                    self.vector_service.get_semantic_embedding,
                    response
                )
            except Exception as e:
                self.logger.warning(f"[ECHO] Failed to get embedding: {e}")
                embedding = None

        try:
            # P3.3／P3.4：明示 skip 則不寫（閘門已覆蓋；保留雙保險）
            if bool(extracted_info.get('skip_echo_consolidation')):
                self.logger.info("[ECHO] Skipped by orchestrator hint")
                return ""

            policy_level = self._resolve_memory_policy_level(extracted_info, session_state)
            metadata = {
                'primary_island': session_state.get('primary_island', 'Unknown'),
                'intimacy': session_state.get('intimacy', 0.1),
                'session_id': session_state.get('session_id', 'unknown'),
                'user_sentiment': extracted_info.get('user_sentiment', {}),
                'narrative_drift_signal': extracted_info.get('narrative_drift_signal', 0.0),
                'narrative_drift_alert_level': extracted_info.get('narrative_drift_alert_level', 'none'),
                'memory_policy_level': policy_level,
                'source': 'eternal_echo',
                'memory_type': 'eternal_echo',
                'canon_mutable': False,
            }
            metadata_overrides = extracted_info.get('metadata_overrides')
            if isinstance(metadata_overrides, dict):
                metadata.update(metadata_overrides)
            metadata['source'] = 'eternal_echo'
            metadata['memory_type'] = 'eternal_echo'
            metadata['canon_mutable'] = False
            metadata = self._sanitize_metadata_by_policy(metadata, policy_level)

            # 再驗 metadata 不可偷帶 canon source
            if gate is not None:
                meta_check = gate.evaluate_pre_store(
                    user_input=user_input,
                    response=response,
                    echo_id=echo_id,
                    echo_score=echo_score,
                    metadata=metadata,
                    extracted_info=extracted_info,
                    session_state=session_state,
                    turn_info=extracted_info,
                )
                if not meta_check.allowed:
                    self.logger.info(
                        f"[ECHO] Write gate denied before backend store: "
                        f"{meta_check.deny_reason}"
                    )
                    return ""

            # 【修復 v8.3】使用異步 DB 存儲
            if (self.db_manager and 
                hasattr(self.db_manager, 'async_db_manager')):
                success = await self.db_manager.async_db_manager.store_echo_async(
                    echo_id=echo_id,
                    user_id=user_id,
                    user_input=user_input,
                    response=response,
                    embedding=embedding,
                    echo_score=max(0.0, min(1.0, float(echo_score))),
                    metadata=metadata
                )

                if success:
                    self.logger.info(f"[ECHO] Stored {echo_id} with score {echo_score:.2f}")
                    return echo_id
                else:
                    self.logger.error(f"[ECHO] Failed to store {echo_id}")
                    return ""

            # Fallback：記憶管理器存儲（Zero-Truncation：不硬截斷正文）
            if self.memory_manager:
                try:
                    echo_record = {
                        'id': echo_id,
                        'user_id': user_id,
                        'user_input': user_input,
                        'response': response,
                        'embedding': embedding,
                        'echo_score': echo_score,
                        'metadata': metadata,
                        'created_at': datetime.now().isoformat()
                    }

                    stored_ok = await asyncio.to_thread(
                        self.memory_manager.store,
                        echo_record
                    )
                    if not stored_ok:
                        self.logger.error(
                            f"[ECHO] Memory manager refused store for {echo_id}"
                        )
                        return ""

                    self.logger.info(f"[ECHO] Stored {echo_id} via memory_manager")
                    return echo_id

                except Exception as e:
                    self.logger.error(f"[ECHO] Memory manager store failed: {e}")
                    return ""

            self.logger.warning("[ECHO] No storage backend available")
            return ""

        except Exception as e:
            self.logger.error(f"[ECHO] Store operation failed: {e}")
            return ""

    async def apply_decay_to_db(self) -> bool:
        """
        [修復 v8.3] 非同步應用記憶衰減 - 完整 await
        """
        await self.ensure_initialized()

        self.logger.info("[DECAY] Starting memory decay operation...")

        try:
            # 【修復 v8.3】使用異步方法
            if (self.db_manager and 
                hasattr(self.db_manager, 'async_db_manager')):
                success = await self.db_manager.async_db_manager.apply_memory_decay_async()

                if success:
                    self.logger.info("[DECAY] Memory decay completed successfully")
                return success

            # Fallback：內存管理器
            if self.memory_manager:
                try:
                    await asyncio.to_thread(self.memory_manager.apply_decay)
                    self.logger.info("[DECAY] Memory decay applied via memory_manager")
                    return True
                except Exception as e:
                    self.logger.error(f"[DECAY] Memory manager decay failed: {e}")

            return False
        except Exception as e:
            self.logger.error(f"[DECAY] Operation failed: {e}")
            return False

    def _resolve_memory_policy_level(self, extracted_info: Dict, session_state: Dict) -> str:
        """
        將 drift/restrict 訊號統一成 memory policy level。
        """
        explicit = str(extracted_info.get('memory_policy_level', '')).lower()
        if explicit in {'normal', 'strict', 'critical'}:
            return explicit

        alert_level = str(extracted_info.get('narrative_drift_alert_level', 'none')).lower()
        if alert_level == 'critical':
            return 'critical'
        if alert_level == 'warning':
            return 'strict'

        meta_control = extracted_info.get('metacognitive_control', {})
        if isinstance(meta_control, dict):
            if bool(meta_control.get('restrict_memory', False)):
                return 'strict'

        drift_info = session_state.get('last_drift_info', {}) if isinstance(session_state, dict) else {}
        if isinstance(drift_info, dict):
            if str(drift_info.get('alert_level', '')).lower() == 'critical':
                return 'critical'
            if str(drift_info.get('alert_level', '')).lower() == 'warning':
                return 'strict'

        return 'normal'

    def _contains_autobiography_marker(self, text: str) -> bool:
        if not text or not isinstance(text, str):
            return False
        return any(marker in text for marker in AUTOBIOGRAPHY_MARKERS)

    def _sanitize_metadata_by_policy(self, metadata: Dict[str, Any], policy_level: str) -> Dict[str, Any]:
        """
        依 memory policy 對 metadata 做一致性清洗，避免非 canonical 自傳片段落盤。
        """
        if not isinstance(metadata, dict):
            return {}
        if policy_level not in {'strict', 'critical'}:
            return metadata

        def _sanitize_value(value: Any) -> Any:
            if isinstance(value, dict):
                cleaned: Dict[str, Any] = {}
                for k, v in value.items():
                    sanitized_v = _sanitize_value(v)
                    if sanitized_v is not None:
                        cleaned[k] = sanitized_v
                return cleaned
            if isinstance(value, list):
                cleaned_list = []
                for item in value:
                    sanitized_item = _sanitize_value(item)
                    if sanitized_item is not None:
                        cleaned_list.append(sanitized_item)
                return cleaned_list
            if isinstance(value, str):
                if not self._contains_autobiography_marker(value):
                    return value
                if policy_level == 'critical':
                    return None
                sanitized = value
                for marker in AUTOBIOGRAPHY_MARKERS:
                    sanitized = sanitized.replace(marker, '我記得')
                return sanitized
            return value

        cleaned = _sanitize_value(dict(metadata))
        return cleaned if isinstance(cleaned, dict) else {}

    async def batch_search_memories(
        self,
        user_id: str,
        context_tokens: List[str],
        k: int = 10
    ) -> Dict[str, List[Dict]]:
        """
        [修復 v8.3] 批量搜索記憶 - 完整 await
        """
        await self.ensure_initialized()

        try:
            all_memories = []

            for token in context_tokens[:5]:
                if self.vector_service:
                    try:
                        token_vector = await asyncio.to_thread(
                            self.vector_service.get_semantic_embedding,
                            token
                        )
                        if token_vector:
                            mems = await self.search_memories(
                                token_vector,
                                k=k,
                                min_similarity=0.3
                            )
                            all_memories.extend(mems)
                    except Exception:
                        pass

            return {'similar_memories': all_memories}

        except Exception as e:
            self.logger.error(f"[BATCH] Batch search failed: {e}")
            return {'similar_memories': []}

    async def close(self) -> None:
        """[NEW] 優雅關閉"""
        self.logger.info("[CLOSE] GSWEngine closing...")
        # 清理資源
        self._initialized = False

    def shutdown(self) -> None:
        """同步關閉（向後相容）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.close())
            else:
                loop.run_until_complete(self.close())
        except Exception as e:
            self.logger.warning(f"[CLOSE] Error: {e}")