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
        session_state: Dict
    ) -> Dict:
        """
        [修復 v8.3] 檢測漂移 - 完整 await
        """
        if not response_vector:
            return {
                'drift_score': 0.5,
                'closest_core_memory': None,
                'closest_distance': 1.0
            }

        try:
            similar_mems = await self.search_memories(
                response_vector,
                k=1,
                min_similarity=0.0
            )

            if not similar_mems:
                return {
                    'drift_score': 0.5,
                    'closest_core_memory': None,
                    'closest_distance': 1.0
                }

            closest = similar_mems[0]
            drift_score = 1.0 - closest.get('similarity', 0.5)

            return {
                'drift_score': drift_score,
                'closest_core_memory': closest,
                'closest_distance': drift_score
            }

        except Exception as e:
            self.logger.error(f"[DRIFT] Detection failed: {e}")
            return {
                'drift_score': 0.5,
                'closest_core_memory': None,
                'closest_distance': 1.0
            }

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

        sentiment_intensity = abs(
            extracted_info.get('user_sentiment', {}).get('intensity', 0)
        )
        sentiment_score = 0.5 if sentiment_intensity > 0.6 else 0.0

        echo_score = keyword_score + sentiment_score

        # [修復 v8.3] 確保返回值類型
        return echo_score >= 0.6, float(min(1.0, echo_score))

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

        echo_id = f"echo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
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
            metadata = {
                'primary_island': session_state.get('primary_island', 'Unknown'),
                'intimacy': session_state.get('intimacy', 0.1),
                'session_id': session_state.get('session_id', 'unknown'),
                'user_sentiment': extracted_info.get('user_sentiment', {})
            }

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

            # Fallback：記憶管理器存儲
            if self.memory_manager:
                try:
                    echo_record = {
                        'id': echo_id,
                        'user_id': user_id,
                        'user_input': user_input[:300],
                        'response': response[:300],
                        'embedding': embedding,
                        'echo_score': echo_score,
                        'metadata': metadata,
                        'created_at': datetime.now().isoformat()
                    }

                    await asyncio.to_thread(
                        self.memory_manager.store,
                        echo_record
                    )

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