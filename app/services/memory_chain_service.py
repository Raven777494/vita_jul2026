# app/services/memory_chain_service.py
"""
Memory perception chain: BGE-M3 (8084) embeddings -> pgvector retrieval -> context injection -> persist.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class MemoryRetrievalResult:
    """Result of a single memory retrieval pass."""
    memories: List[Dict[str, Any]] = field(default_factory=list)
    context_text: str = ""
    degraded: bool = False
    sources: List[str] = field(default_factory=list)


def format_memory_context(memories: List[Dict[str, Any]], max_items: int = 3) -> str:
    """Format retrieved echoes into prompt-ready context."""
    if not memories:
        return ""

    lines: List[str] = []
    for mem in memories[:max_items]:
        if not isinstance(mem, dict):
            continue
        content = (
            mem.get('content')
            or mem.get('response')
            or mem.get('user_input')
            or ""
        )
        if not content or not isinstance(content, str):
            continue
        similarity = mem.get('similarity')
        if similarity is not None:
            lines.append(f"- [{float(similarity):.2f}] {content[:160]}")
        else:
            lines.append(f"- {content[:160]}")

    return "\n".join(lines)


class MemoryChainService:
    """
    End-to-end memory chain for the main chat pipeline.

    Retrieve: query_vector + user_id -> pgvector (gsw_eternal_echoes)
    Persist: turn text + embeddings -> pgvector via GSWEngine
    """

    def __init__(
        self,
        gsw_engine=None,
        vector_service=None,
        top_k: int = 5,
        min_similarity: float = 0.45,
    ):
        self.gsw_engine = gsw_engine
        self.vector_service = vector_service
        self.top_k = top_k
        self.min_similarity = min_similarity
        self.logger = logger

    async def retrieve(
        self,
        user_id: str,
        query_vector: Optional[List[float]],
        *,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
    ) -> MemoryRetrievalResult:
        """Retrieve user-scoped memories similar to the query embedding."""
        if not query_vector:
            return MemoryRetrievalResult(degraded=True, sources=['no_query_vector'])

        if not self.gsw_engine:
            return MemoryRetrievalResult(degraded=True, sources=['gsw_engine_unavailable'])

        k = top_k if top_k is not None else self.top_k
        min_sim = min_similarity if min_similarity is not None else self.min_similarity

        try:
            memories = await self.gsw_engine.search_memories(
                query_vector=query_vector,
                k=k,
                min_similarity=min_sim,
                user_id=user_id,
            )
            context_text = format_memory_context(memories)
            return MemoryRetrievalResult(
                memories=memories or [],
                context_text=context_text,
                degraded=len(memories or []) == 0,
                sources=['pgvector'] if memories else ['pgvector_empty'],
            )
        except Exception as exc:
            self.logger.warning({
                "event": "memory_chain_retrieve_failed",
                "user_id": user_id,
                "error": str(exc),
            })
            return MemoryRetrievalResult(degraded=True, sources=['retrieve_error'])

    async def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        user_input: str,
        response: str,
        user_embedding: Optional[List[float]],
        response_embedding: Optional[List[float]] = None,
        session_state: Optional[Dict[str, Any]] = None,
        emotion_profile: Optional[Dict[str, Any]] = None,
        risk_level: int = 0,
        force: bool = False,
    ) -> Optional[str]:
        """
        Persist a completed turn into gsw_eternal_echoes when storage is available.

        Returns echo_id on success, None otherwise.
        """
        if not self.gsw_engine or not user_input or not response:
            return None

        if risk_level >= 4 and not force:
            return None

        session_state = dict(session_state or {})
        session_state.setdefault('user_id', user_id)
        session_state.setdefault('session_id', session_id)

        extracted_info: Dict[str, Any] = {
            'response_embedding': response_embedding or user_embedding,
            'user_sentiment': emotion_profile or {},
        }

        try:
            should_store, echo_score = self.gsw_engine.judge_eternal_echo_generation(
                response, extracted_info, session_state
            )
        except Exception as judge_exc:
            # 判斷失敗時預設不落盤，避免把漂移／低顯著內容固化為長期記憶。
            self.logger.warning({
                "event": "memory_chain_judge_failed",
                "user_id": user_id,
                "session_id": session_id,
                "error": str(judge_exc),
            })
            should_store, echo_score = False, 0.0

        if not should_store and not force:
            self.logger.info({
                "event": "memory_chain_persist_skipped",
                "user_id": user_id,
                "session_id": session_id,
                "echo_score": float(echo_score or 0.0),
                "reason": "judge_should_store_false",
            })
            return None

        echo_score = max(0.35, float(echo_score or 0.35))

        try:
            echo_id = await self.gsw_engine.generate_and_store_echo(
                user_input=user_input,
                response=response,
                extracted_info=extracted_info,
                session_state=session_state,
                echo_score=echo_score,
            )
            if echo_id:
                self.logger.info({
                    "event": "memory_chain_persisted",
                    "user_id": user_id,
                    "session_id": session_id,
                    "echo_id": echo_id,
                    "echo_score": echo_score,
                })
            return echo_id or None
        except Exception as exc:
            self.logger.warning({
                "event": "memory_chain_persist_failed",
                "user_id": user_id,
                "session_id": session_id,
                "error": str(exc),
            })
            return None
