# app/services/star_orchestration_service.py

"""

Asynchronous Star-Orchestration (v9 pipeline)



Phase 1 — Parallel Sensing (orchestrator): Emobloom + BGE + weather + pgvector memory

Phase 1b — User Shadow (stub): pain / trust / hope / loneliness

Phase 2 — Nemo (8081): primary Cantonese response generation

Phase 3 — Llama (8082): conditional Meta Auditor

Phase 4 — Gemma (8083): character personality layer

"""



from dataclasses import dataclass, field

from typing import Any, Dict, List, Optional

import logging



from app.services.user_shadow_service import (

    UserShadow,

    build_user_shadow,

    format_shadow_context,

)



logger = logging.getLogger(__name__)



MIN_STAR_RESPONSE_LENGTH = 10


def _stored_shadow_from_session(
    session_state: Optional[Dict[str, Any]],
) -> Optional[UserShadow]:
    if not session_state:
        return None
    stored = session_state.get("stored_shadow")
    if not isinstance(stored, dict):
        return None
    return UserShadow.from_dict(stored)


@dataclass

class SensingBundle:

    """Phase 1 output — parallel sensing inputs for v9 generation."""

    user_text: str

    emotion_profile: Dict[str, Any] = field(default_factory=dict)

    embedding: Optional[List[float]] = None

    weather_context: str = ""

    memory_context: str = ""

    retrieved_memories: List[Dict[str, Any]] = field(default_factory=list)

    language_hint: Optional[str] = None

    risk_level: int = 0

    session_state: Optional[Dict[str, Any]] = None

    reality_context: str = ""

    reality_facts: List[Dict[str, Any]] = field(default_factory=list)





@dataclass

class StarOrchestrationResult:

    """Full v9 pipeline result."""

    text: str = ""

    draft_text: str = ""

    primary_text: str = ""

    soul_guidance: Optional[Dict[str, Any]] = None

    meta_audit: Optional[Dict[str, Any]] = None

    meta_layer: Optional[Dict[str, Any]] = None

    user_shadow: Optional[Dict[str, Any]] = None

    pipeline_stages: List[str] = field(default_factory=list)

    execution_track: str = "v9"

    pipeline_version: str = "v9"

    success: bool = False

    error: Optional[str] = None

    inference_time: float = 0.0





def build_v9_context_prompt(bundle: SensingBundle, shadow: UserShadow) -> str:

    """Format Phase 1 sensing + User Shadow for Nemo primary generation."""

    emotion = bundle.emotion_profile or {}

    parts = [

        "=== Phase 1 Sensing (v9) ===",

        format_shadow_context(shadow),

        f"User message: {bundle.user_text}",

        f"Emotion VAD: valence={emotion.get('valence', 0.5):.2f}, "

        f"arousal={emotion.get('arousal', 0.3):.2f}, "

        f"dominance={emotion.get('dominance', 0.5):.2f}",

        f"Dominant emotion: {emotion.get('dominant_emotion', 'neutral')}",

        f"Crisis signal: {emotion.get('is_crisis_risk', False)}",

        f"Session risk level: {bundle.risk_level}",

    ]



    if bundle.language_hint:

        parts.append(f"Language preference: {bundle.language_hint}")

    if bundle.weather_context:

        parts.append(f"Weather/context: {bundle.weather_context}")

    if bundle.memory_context:

        parts.append(f"Retrieved memories:\n{bundle.memory_context}")

    if bundle.reality_context:

        parts.append(bundle.reality_context)



    turn_count = (bundle.session_state or {}).get("turn_count", 0)

    parts.append(f"Turn count: {turn_count}")

    return "\n".join(parts)





class StarOrchestrationService:

    """Coordinates v9 pipeline after Phase 1 sensing."""



    def __init__(self, llm_service=None, enabled: bool = True):

        self.llm_service = llm_service

        self.enabled = enabled

        self.logger = logger



    async def execute(

        self,

        bundle: SensingBundle,

        *,

        base_system_prompt: str = "",

        temperature: Optional[float] = None,

        max_tokens: int = 512,

        persona_name: str = "希兒",

    ) -> StarOrchestrationResult:

        """

        Run v9 pipeline (Nemo -> conditional Llama audit -> Gemma personality).



        Phase 1 must be collected by the caller (orchestrator).

        """

        if not self.enabled or not self.llm_service:

            return StarOrchestrationResult(

                success=False,

                error="star_orchestration_disabled",

            )



        from app.config import config as app_config



        if not getattr(app_config, "V9_PIPELINE_ENABLED", True):

            return StarOrchestrationResult(

                success=False,

                error="v9_pipeline_disabled",

            )



        shadow = build_user_shadow(

            session_state=bundle.session_state,

            emotion_profile=bundle.emotion_profile,

            risk_level=bundle.risk_level,

            stored_shadow=_stored_shadow_from_session(bundle.session_state),

        )

        shadow_context = format_shadow_context(shadow)

        v9_context = build_v9_context_prompt(bundle, shadow)

        combined_system = base_system_prompt

        if v9_context:

            combined_system = (

                f"{base_system_prompt}\n\n{v9_context}"

                if base_system_prompt

                else v9_context

            )



        try:

            llm_result = await self.llm_service.generate_v9_response_async(

                user_text=bundle.user_text,

                system_prompt=combined_system,

                memory_context=bundle.memory_context,

                emotion_profile=bundle.emotion_profile,

                shadow_context=shadow_context,

                risk_level=bundle.risk_level,

                temperature=temperature,

                max_tokens=max_tokens,

                persona_name=persona_name,

            )



            text = (llm_result.content or "").strip()

            stages = list(llm_result.pipeline_stages or [])

            primary = getattr(llm_result, "primary_text", "") or ""

            meta = getattr(llm_result, "meta_audit", None)

            meta_layer = getattr(llm_result, "meta_layer", None)

            meets_length = len(text) >= MIN_STAR_RESPONSE_LENGTH

            success = llm_result.is_success() and bool(text) and meets_length

            error = None if success else (llm_result.error or "response_too_short")



            return StarOrchestrationResult(

                text=text,

                draft_text=getattr(llm_result, "draft_text", "") or text,

                primary_text=primary,

                soul_guidance=meta,

                meta_audit=meta,

                meta_layer=meta_layer,

                user_shadow=shadow.to_dict(),

                pipeline_stages=stages,

                execution_track=llm_result.execution_track or "v9",

                pipeline_version="v9",

                success=success,

                error=error,

                inference_time=llm_result.inference_time,

            )

        except Exception as exc:

            self.logger.error({

                "event": "v9_orchestration_failed",

                "error": str(exc),

            })

            return StarOrchestrationResult(

                success=False,

                error=str(exc),

            )

