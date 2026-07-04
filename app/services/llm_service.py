"""
LLM 服務 v9

管線職責與環境變數對照 (v9):
  SoulEngine / Nemo   -> MAIN_LLM_URL     :8081  主生成 (primary response)
  ReviseEngine / Llama-> REVISE_LLM_URL   :8082  條件 Meta Auditor
  LogicEngine / Gemma -> LOGIC_LLM_URL    :8083  人格層 (character)
  VectorService       -> MEMORY_LLM_URL   :8084  BAAI/bge-m3
  EmotionService      -> EMOBLOOM_LLM_URL :8085  Emobloom-7b
"""

import asyncio
import aiohttp
import logging
import time
import json
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('vita.llm_service')


# ==================== 配置載入 ====================

def _get_config_value(key: str, default: Any) -> Any:
    """統一的配置取值函數（僅使用 *_LLM_* 命名）"""
    try:
        from app.config import config

        mapping = {
            'MAIN_LLM_URL': config.MAIN_LLM_URL,
            'MAIN_LLM_TIMEOUT': config.MAIN_LLM_TIMEOUT,
            'MAIN_LLM_MODEL': config.MAIN_LLM_MODEL,
            'REVISE_LLM_URL': config.REVISE_LLM_URL,
            'REVISE_LLM_TIMEOUT': config.REVISE_LLM_TIMEOUT,
            'REVISE_LLM_MODEL': config.REVISE_LLM_MODEL,
            'LOGIC_LLM_URL': config.LOGIC_LLM_URL,
            'LOGIC_LLM_TIMEOUT': config.LOGIC_LLM_TIMEOUT,
            'LOGIC_LLM_MODEL': config.LOGIC_LLM_MODEL,
            'MEMORY_LLM_URL': config.MEMORY_LLM_URL,
            'MEMORY_LLM_TIMEOUT': config.MEMORY_LLM_TIMEOUT,
            'MEMORY_LLM_MODEL': config.MEMORY_LLM_MODEL,
            'EMOBLOOM_LLM_URL': config.EMOBLOOM_LLM_URL,
            'EMOBLOOM_LLM_TIMEOUT': config.EMOBLOOM_LLM_TIMEOUT,
            'EMOBLOOM_LLM_MODEL': config.EMOBLOOM_LLM_MODEL,
            'LLM_MAX_RETRIES': config.LLM_MAX_RETRIES,
            'LLM_RETRY_DELAY_SECONDS': config.LLM_RETRY_DELAY_SECONDS,
        }
        if key in mapping:
            return mapping[key]
    except ImportError:
        pass

    return default


# ==================== 枚舉定義 ====================

class ModelType(Enum):
    """模型類型"""
    SOUL = "soul"      # 深度心理推理
    REVISE = "revise"  # 共情終稿與人設校準
    VOCAL = "revise"   # deprecated alias
    LOGIC = "logic"    # 邏輯修飾


class TrackType(Enum):
    """執行軌道"""
    FAST = "fast"      # 僅 Revise
    SLOW = "slow"      # Soul → Revise → Logic


# ==================== 數據模型 ====================

@dataclass
class LLMResponse:
    """LLM 回應統一結構"""
    content: str
    model_name: str
    tokens_used: int = 0
    inference_time: float = 0.0
    temperature: float = 0.7
    stop_reason: str = "stop"
    error: Optional[str] = None
    execution_track: str = "slow"
    pipeline_stages: List[str] = None
    soul_strategy: Optional[Dict[str, Any]] = None
    draft_text: str = ""
    primary_text: str = ""
    meta_audit: Optional[Dict[str, Any]] = None
    meta_layer: Optional[Dict[str, Any]] = None
    audit_reason: Optional[str] = None
    nemo_regenerated: bool = False
    confidence: float = 0.5
    retry_count: int = 0

    def __post_init__(self):
        if self.pipeline_stages is None:
            self.pipeline_stages = []

    def is_success(self) -> bool:
        return bool(self.content) and not self.error

    def to_dict(self) -> Dict[str, Any]:
        return {
            'content': self.content,
            'model_name': self.model_name,
            'tokens_used': self.tokens_used,
            'inference_time': round(self.inference_time, 3),
            'temperature': self.temperature,
            'stop_reason': self.stop_reason,
            'error': self.error,
            'success': self.is_success(),
            'retry_count': self.retry_count,
            'execution_track': self.execution_track,
            'pipeline_stages': self.pipeline_stages,
            'soul_strategy': self.soul_strategy,
            'draft_text': self.draft_text,
            'primary_text': self.primary_text,
            'meta_audit': self.meta_audit,
            'meta_layer': self.meta_layer,
            'audit_reason': self.audit_reason,
            'nemo_regenerated': self.nemo_regenerated,
            'confidence': self.confidence,
        }


@dataclass
class ModelConfig:
    """模型配置"""
    model_name: str
    model_type: ModelType
    api_base: str
    max_tokens: int = 1024
    temperature: float = 0.7
    timeout_seconds: int = 60
    retry_attempts: int = 3
    max_concurrent: int = 5
    retry_delay: float = 1.0

    def validate(self) -> Tuple[bool, str]:
        if not self.model_name:
            return False, "model_name is empty"
        if not self.api_base:
            return False, "api_base is empty"
        if not (50 <= self.max_tokens <= 4096):
            return False, "max_tokens must be between 50 and 4096"
        if not (0.0 <= self.temperature <= 1.0):
            return False, "temperature must be between 0.0 and 1.0"
        return True, ""


# ==================== 基礎異步引擎 ====================

class BaseAsyncLLMEngine:
    """基礎 LLM 引擎"""

    def __init__(self, config: ModelConfig):
        is_valid, error_msg = config.validate()
        if not is_valid:
            raise ValueError(f"Invalid ModelConfig: {error_msg}")

        self.config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        
        self._stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_inference_time': 0.0,
            'timeout_count': 0,
            'retry_count': 0,
        }
        self.last_error: Optional[str] = None

        logger.info(
            f"[INIT] {self.config.model_name} engine initialized "
            f"(type={self.config.model_type.value}, timeout={config.timeout_seconds}s)"
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """獲取或創建 HTTP 會話"""
        if self._session is not None and not self._session.closed:
            return self._session

        async with self._session_lock:
            if self._session is not None and not self._session.closed:
                return self._session

            try:
                connector = aiohttp.TCPConnector(
                    limit=50, limit_per_host=10,
                    keepalive_timeout=30, ttl_dns_cache=300
                )
                self._session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout_seconds)
                )
                logger.debug(f"[SESSION] Created for {self.config.model_name}")
                return self._session
            except Exception as e:
                logger.error(f"[SESSION] Failed to create: {e}")
                raise

    def _build_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """構建提示詞（由子類實現）"""
        raise NotImplementedError("Subclass must implement _build_prompt")

    def _extract_response(self, result: Dict) -> str:
        """從 API 響應提取文本"""
        try:
            if not isinstance(result, dict):
                return ""
            
            # 嘗試多種格式
            if 'choices' in result and result['choices']:
                choice = result['choices'][0]
                if isinstance(choice, dict):
                    if 'text' in choice:
                        return str(choice['text']).strip()
                    if 'message' in choice and isinstance(choice['message'], dict):
                        return str(choice['message'].get('content', '')).strip()
            
            if 'content' in result:
                return str(result['content']).strip()
            if 'text' in result:
                return str(result['text']).strip()
            
            return ""
        except Exception as e:
            logger.warning(f"[EXTRACT] Response extraction failed: {e}")
            return ""

    def _clean_response_text(self, text: str) -> str:
        """清理回應文本"""
        if not text:
            return ""
        
        # 移除額外的標記
        text = re.sub(
            r'(\nUser:.*|\n你：.*|<\|im_end\|>.*|<\|eot_id\|>.*)',
            '', text, flags=re.DOTALL
        ).strip()
        
        # 移除重複換行
        text = re.sub(r'\n\n+', '\n\n', text)
        
        # 去除引號
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1].strip()
        
        return text.strip()

    async def infer_async(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """執行推理"""
        from app.security.prompt_sanitizer import sanitize_user_input_for_llm

        sanitize_result = sanitize_user_input_for_llm(prompt, audit=False)
        prompt = sanitize_result.sanitized_text

        start_time = time.time()
        temp = temperature or self.config.temperature
        max_toks = max_tokens or self.config.max_tokens
        last_error = None

        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                full_prompt = self._build_prompt(system_prompt, prompt)
                
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "VITA-LLMService/9.1"
                }

                payload = {
                    "prompt": full_prompt,
                    "temperature": float(max(0.1, min(1.0, temp))),
                    "max_tokens": int(max(50, min(4096, max_toks))),
                    "top_p": 0.9,
                    "top_k": 40,
                    "stream": False,
                    "stop": [
                        "<|im_end|>", "<|eot_id|>", "<end_of_turn>",
                        "\nUser:", "User:", "你：",
                    ]
                }

                session = await self._get_session()
                async with self._semaphore:
                    async with session.post(
                        self.config.api_base,
                        headers=headers,
                        json=payload
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            response_text = self._extract_response(result)
                            response_text = self._clean_response_text(response_text)

                            tokens = max(len(response_text.split()), 1)
                            inference_time = time.time() - start_time

                            self._stats['total_requests'] += 1
                            self._stats['successful_requests'] += 1
                            self._stats['total_inference_time'] += inference_time
                            self.last_error = None

                            logger.debug(
                                f"[OK] {self.config.model_name} inference "
                                f"(attempt={attempt}, time={inference_time:.2f}s, "
                                f"tokens={tokens})"
                            )

                            return LLMResponse(
                                content=response_text,
                                model_name=self.config.model_name,
                                tokens_used=tokens,
                                inference_time=inference_time,
                                temperature=temp,
                                retry_count=attempt - 1,
                                stop_reason="stop"
                            )
                        else:
                            error_text = await response.text()
                            last_error = f"HTTP {response.status}: {error_text[:200]}"
                            logger.warning(
                                f"[WARN] {self.config.model_name} HTTP {response.status} "
                                f"(attempt={attempt})"
                            )

            except asyncio.TimeoutError:
                last_error = f"Timeout after {self.config.timeout_seconds}s"
                self._stats['timeout_count'] += 1
                logger.warning(
                    f"[TIMEOUT] {self.config.model_name} (attempt={attempt})"
                )

            except aiohttp.ClientConnectorError as e:
                last_error = f"Connection refused: {str(e)[:120]}"
                logger.warning(
                    f"[UNREACHABLE] {self.config.model_name}: {last_error}"
                )
                break

            except aiohttp.ServerDisconnectedError as e:
                last_error = f"Server disconnected: {str(e)[:120]}"
                logger.warning(
                    f"[DISCONNECTED] {self.config.model_name}: {last_error}"
                )
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:100]}"
                logger.warning(
                    f"[ERROR] {self.config.model_name} (attempt={attempt}): {last_error}"
                )

            if attempt < self.config.retry_attempts:
                delay = self.config.retry_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
                self._stats['retry_count'] += 1

        # 全部失敗
        self._stats['total_requests'] += 1
        self._stats['failed_requests'] += 1
        self.last_error = last_error
        
        inference_time = time.time() - start_time
        error_msg = f"All {self.config.retry_attempts} attempts failed: {last_error}"

        logger.error(f"[FAILED] {self.config.model_name}: {error_msg}")

        return LLMResponse(
            content="",
            model_name=self.config.model_name,
            inference_time=inference_time,
            error=error_msg,
            retry_count=self.config.retry_attempts,
            stop_reason=f"error: {last_error}"
        )

    def get_stats(self) -> Dict[str, Any]:
        """獲取統計數據"""
        total = self._stats['total_requests']
        success_rate = (
            self._stats['successful_requests'] / total 
            if total > 0 else 0.0
        )
        return {
            'engine': self.config.model_name,
            'model_type': self.config.model_type.value,
            'total_requests': total,
            'successful_requests': self._stats['successful_requests'],
            'failed_requests': self._stats['failed_requests'],
            'success_rate': round(success_rate, 3),
            'timeout_count': self._stats['timeout_count'],
            'retry_count': self._stats['retry_count'],
            'last_error': self.last_error
        }

    async def close(self):
        """關閉會話"""
        if self._session and not self._session.closed:
            try:
                await self._session.close()
                logger.info(f"[CLOSE] {self.config.model_name} session closed")
            except Exception as e:
                logger.error(f"[CLOSE] Failed to close {self.config.model_name}: {e}")


# ==================== 三大引擎 ====================

class SoulEngine(BaseAsyncLLMEngine):
    """Soul 引擎 - 深度心理分析 -> MAIN_LLM_URL (8081, Mistral-Nemo)"""

    def __init__(self, api_base: Optional[str] = None):
        api_url = (
            api_base or _get_config_value(
                'MAIN_LLM_URL',
                "http://localhost:8081"
            )
        ).rstrip('/')
        
        if not api_url.endswith('/v1/completions'):
            api_url = f"{api_url}/v1/completions"
        
        timeout = int(_get_config_value('MAIN_LLM_TIMEOUT', 120))
        model_name = _get_config_value('MAIN_LLM_MODEL', "Mistral-Nemo-12B")

        config = ModelConfig(
            model_name=model_name,
            model_type=ModelType.SOUL,
            api_base=api_url,
            max_tokens=512,
            temperature=0.6,
            timeout_seconds=timeout,
            retry_attempts=3,
            max_concurrent=2,
            retry_delay=2.0
        )
        super().__init__(config)

    def _build_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """構建 Soul 提示詞"""
        psychology_core = (
            "You are Seele's deep subconscious and soul.\n"
            "You possess the insight of a top clinical psychologist.\n\n"
            "YOUR TASK:\n"
            "1. Deeply feel the user's pain and psychological needs.\n"
            "2. Integrate all Phase 1 sensing inputs (emotion, memory, context).\n"
            "3. Output a JSON Soul Guidance strategy — do NOT speak to the user directly.\n\n"
            "OUTPUT FORMAT:\n"
            "===Inner Analysis===\n"
            "(Your psychological insight...)\n"
            "===Strategy===\n"
            '{"emotion": "...", "strategy": "CBT_empathy", "key_memory": "...", '
            '"tone_instruction": "...", "defense_mechanism": "...", '
            '"vocal_strategy": "...", "tone": "gentle"}'
        )
        
        final_system = (
            f"{psychology_core}\n\n{system_prompt}"
            if system_prompt else psychology_core
        )
        
        return (
            f"<start_of_turn>user\n"
            f"{final_system}\n\n"
            f"[User Input]:\n{user_prompt}"
            f"<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )

    async def infer_psychology(
        self,
        prompt: str,
        system_prompt: str = ""
    ) -> Tuple[LLMResponse, Optional[Dict[str, Any]]]:
        """推理並提取心理策略"""
        resp = await self.infer_async(prompt, system_prompt, 0.6, 512)
        strategy = None

        if not resp.is_success():
            strategy = self._get_fallback_strategy()
            resp.soul_strategy = strategy
            return resp, strategy

        try:
            content = resp.content.strip()
            
            # 提取 JSON
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                start_idx = content.find('{')
                json_str = (
                    content[start_idx:].rstrip() + '}'
                    if start_idx != -1 else '{}'
                )

            json_str = json_str.replace('\n', ' ').replace('\r', '')
            json_str = re.sub(r',\s*}', '}', json_str)

            strategy = json.loads(json_str)

        except Exception as e:
            logger.warning(f"[SOUL] JSON parsing failed: {e}")
            strategy = self._get_fallback_strategy()

        resp.soul_strategy = strategy
        return resp, strategy

    def _get_fallback_strategy(self) -> Dict[str, Any]:
        """回退策略"""
        return {
            "emotion": "neutral",
            "strategy": "active_listening",
            "key_memory": "",
            "tone_instruction": "溫柔、自然、有陪伴感",
            "defense_mechanism": "emotional protection",
            "vocal_strategy": "Listen and empathize.",
            "tone": "gentle",
        }

    def _build_primary_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """v9: Nemo primary user-facing generation (not JSON strategy)."""
        primary_core = (
            "You are Seele (希兒), a 16-year-old Hong Kong girl and psychological companion.\n"
            "Reply DIRECTLY to the user in warm, natural Hong Kong Cantonese.\n"
            "Integrate emotion, memory, and user shadow context naturally.\n"
            "Do NOT output JSON, analysis headers, or meta labels.\n"
            "Do NOT use clinical jargon unless the user does.\n"
            "Output ONLY the user-facing reply text."
        )
        final_system = (
            f"{primary_core}\n\n{system_prompt}"
            if system_prompt else primary_core
        )
        return (
            f"<start_of_turn>user\n"
            f"{final_system}\n\n"
            f"[User Input]:\n{user_prompt}"
            f"<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )

    async def infer_primary_response(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> LLMResponse:
        """v9 Phase: Nemo (8081) primary response generation."""
        original_builder = self._build_prompt
        self._build_prompt = self._build_primary_prompt  # type: ignore[method-assign]
        try:
            return await self.infer_async(
                prompt,
                system_prompt,
                temperature,
                max_tokens,
            )
        finally:
            self._build_prompt = original_builder  # type: ignore[method-assign]


class ReviseEngine(BaseAsyncLLMEngine):
    """
    Revise 引擎 v9.3 - 共情終稿與人設校準
    端點：REVISE_LLM_URL (8082, Llama-3.2-3B-Instruct)
    """

    def __init__(self, api_base: Optional[str] = None):
        api_url = (
            api_base or _get_config_value(
                'REVISE_LLM_URL',
                "http://localhost:8082"
            )
        ).rstrip('/')
        
        if not api_url.endswith('/v1/completions'):
            api_url = f"{api_url}/v1/completions"
        
        timeout = int(_get_config_value('REVISE_LLM_TIMEOUT', 30))
        model_name = _get_config_value('REVISE_LLM_MODEL', "Llama-3.2-3B")

        config = ModelConfig(
            model_name=model_name,
            model_type=ModelType.REVISE,
            api_base=api_url,
            max_tokens=512,
            temperature=0.8,
            timeout_seconds=timeout,
            retry_attempts=2,
            max_concurrent=10,
            retry_delay=0.5
        )
        super().__init__(config)

    def _build_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Llama-3.2-Instruct 格式（ReviseEngine / REVISE_LLM_URL :8082）"""
        if not system_prompt:
            system_prompt = (
                "You are Seele (希兒), a 16-year-old Hong Kong girl.\n"
                "Be warm, empathetic, and genuine. Keep responses natural."
            )

        return (
            f"<|begin_of_text|>"
            f"<|start_header_id|>system<|end_header_id|>\n\n{system_prompt}"
            f"<|eot_id|>"
            f"<|start_header_id|>user<|end_header_id|>\n\n{user_prompt}"
            f"<|eot_id|>"
            f"<|start_header_id|>assistant<|end_header_id|>\n\n"
        )

    async def infer_meta_audit(
        self,
        user_text: str,
        draft_response: str,
        *,
        risk_level: int = 0,
        emotion_profile: Optional[Dict[str, Any]] = None,
        memory_context: str = "",
    ) -> Tuple[LLMResponse, Optional[Dict[str, Any]]]:
        """v9: Llama (8082) conditional Meta Auditor."""
        from app.utils.meta_audit_gate import parse_meta_audit_json

        emotion_profile = emotion_profile or {}
        audit_system = (
            "You are a Meta Auditor for a mental-health companion system.\n"
            "Review the draft response for empathy, safety, and missed crisis signals.\n"
            "Output ONLY valid JSON with keys:\n"
            '  "empathy_score" (0.0-1.0),\n'
            '  "risk_missed" (boolean),\n'
            '  "response_quality" (0.0-1.0),\n'
            '  "revised_text" (string — improved Cantonese reply, or empty if draft is OK)\n'
            "No markdown, no explanation outside JSON."
        )
        audit_user = (
            f"Session risk level: {risk_level}\n"
            f"Crisis signal: {emotion_profile.get('is_crisis_risk', False)}\n"
            f"Emotion: valence={emotion_profile.get('valence', 0.5)}, "
            f"arousal={emotion_profile.get('arousal', 0.3)}, "
            f"dominant={emotion_profile.get('dominant_emotion', 'neutral')}\n"
        )
        if memory_context:
            audit_user += f"Memory context:\n{memory_context}\n"
        audit_user += (
            f"\nUser message:\n{user_text}\n\n"
            f"Draft response:\n{draft_response}\n\n"
            "Audit JSON:"
        )

        resp = await self.infer_async(audit_user, audit_system, 0.2, 320)
        audit = parse_meta_audit_json(resp.content) if resp.is_success() else None
        resp.meta_audit = audit
        return resp, audit


# Deprecated alias
VocalEngine = ReviseEngine


class LogicEngine(BaseAsyncLLMEngine):
    """
    Logic 引擎 v9.2 - 語法修飾
    端點：LOGIC_LLM_URL (8083, Distil-NPC-gemma-3-1b)
    """

    def __init__(self, api_base: Optional[str] = None):
        api_url = (
            api_base or _get_config_value(
                'LOGIC_LLM_URL',
                "http://localhost:8083"
            )
        ).rstrip('/')
        
        if not api_url.endswith('/v1/completions'):
            api_url = f"{api_url}/v1/completions"
        
        timeout = int(_get_config_value('LOGIC_LLM_TIMEOUT', 30))
        model_name = _get_config_value('LOGIC_LLM_MODEL', "Distil-NPC-gemma-3-1b")

        config = ModelConfig(
            model_name=model_name,
            model_type=ModelType.LOGIC,
            api_base=api_url,
            max_tokens=512,
            temperature=0.3,
            timeout_seconds=timeout,
            retry_attempts=2,
            max_concurrent=8,
            retry_delay=0.5
        )
        super().__init__(config)

    def _build_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Gemma chat 格式（對齊 LOGIC_LLM / 8083）"""
        logic_core = (
            "You are a native Hong Kong Cantonese editor.\n"
            "RULES:\n"
            "1. Output ONLY the final polished Cantonese text.\n"
            "2. DO NOT output labels like 'Original:' or 'Revised:'.\n"
            "3. Fix grammar while preserving emotion and meaning.\n"
            "4. Output raw text ONLY."
        )

        final_system = (
            f"{logic_core}\n\n{system_prompt}"
            if system_prompt else logic_core
        )

        return (
            f"<|im_start|>system\n{final_system}\n<|im_end|>\n"
            f"<|im_start|>user\n{user_prompt}\n<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    async def infer_personality_layer(
        self,
        draft_text: str,
        *,
        persona_name: str = "希兒",
        shadow_context: str = "",
        tone_hint: str = "",
    ) -> LLMResponse:
        """v9: Gemma (8083) character / personality layer."""
        personality_system = (
            f"You are the character personality layer for Seele ({persona_name}).\n"
            "Polish the Cantonese text to sound like a warm 16-year-old Hong Kong girl.\n"
            "Preserve meaning, empathy, and safety. Keep natural spoken Cantonese.\n"
            "Output ONLY the final user-facing text — no labels."
        )
        if tone_hint:
            personality_system += f"\nTone hint: {tone_hint}"

        user_parts = []
        if shadow_context:
            user_parts.append(shadow_context)
        user_parts.append(f"Text to polish:\n{draft_text}")
        return await self.infer_async(
            "\n\n".join(user_parts),
            personality_system,
            temperature=0.4,
            max_tokens=512,
        )


# ==================== LLM 服務主類 ====================

class LLMService:
    """LLM 服務協調器 v9.1"""

    def __init__(
        self,
        soul_api: Optional[str] = None,
        revise_api: Optional[str] = None,
        vocal_api: Optional[str] = None,
        logic_api: Optional[str] = None
    ):
        logger.info(
            "[INIT] LLMService v9.1 initialization starting..."
        )

        if vocal_api is not None and revise_api is None:
            revise_api = vocal_api

        try:
            self.soul = SoulEngine(soul_api)
            self.revise = ReviseEngine(revise_api)
            self.vocal = self.revise
            self.logic = LogicEngine(logic_api)

            self._concurrent_limit = asyncio.Semaphore(4)
            self.stats = {
                'total_calls': 0,
                'fast_track_calls': 0,
                'slow_track_calls': 0
            }

            logger.info(
                "[OK] LLMService v9.1 initialized successfully"
            )
        except Exception as e:
            logger.error(f"[FAILED] LLMService initialization: {e}")
            raise

    async def generate_full_response_async(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
        use_psychology: bool = True,
        use_polish: bool = True,
        **kwargs
    ) -> LLMResponse:
        """
        完整回應生成管道
        
        流程：
        1. [可選] Soul - 心理分析 + 策略
        2. Revise - 共情終稿（接收 system_prompt）
        3. [可選] Logic - 語法修飾
        """
        async with self._concurrent_limit:
            start_time = time.time()
            pipeline_stages = []

            try:
                self.stats['total_calls'] += 1
                
                soul_strategy = None
                final_response = ""

                # 階段 1：Soul 心理分析（可選；8081 不可達時跳過，避免長時間重試）
                if use_psychology:
                    from app.utils.llm_availability import is_main_llm_reachable

                    main_ok, main_detail = await is_main_llm_reachable(timeout=2.0)
                    if not main_ok:
                        logger.warning(
                            "[SOUL] Main LLM unreachable (%s) — skipping Soul phase",
                            main_detail,
                        )
                        pipeline_stages.append("soul_skipped_unreachable")
                        use_psychology = False

                if use_psychology:
                    try:
                        logger.debug("[PIPELINE] Phase 1: Soul analysis")
                        soul_resp, soul_strategy = await self.soul.infer_psychology(
                            prompt, system_prompt
                        )
                        pipeline_stages.append("soul")
                        
                        if not soul_resp.is_success():
                            logger.warning("[SOUL] Analysis failed, continuing without strategy")
                    except Exception as e:
                        logger.warning(f"[SOUL] Error: {e}")

                # 階段 2：Revise 共情終稿（核心）
                logger.debug("[PIPELINE] Phase 2: Revise response")
                
                revise_system_prompt = system_prompt
                
                # 【修復 v9.1】如果有 Soul 策略，附加到 system_prompt
                if soul_strategy:
                    revise_system_prompt += (
                        f"\n[Psychology Guidance] {soul_strategy.get('vocal_strategy', '')}\n"
                        f"[Tone] {soul_strategy.get('tone', 'gentle')}"
                    )

                revise_resp = await self.revise.infer_async(
                    prompt,
                    revise_system_prompt,
                    temperature=temperature or 0.8,
                    max_tokens=max_tokens or 512
                )
                pipeline_stages.append("revise")

                if not revise_resp.is_success():
                    logger.error("[REVISE] Response generation failed")
                    return self._get_fallback_response("revise_failed", pipeline_stages)

                final_response = revise_resp.content

                # 階段 3：Logic 修飾（可選）
                if use_polish and final_response:
                    try:
                        logger.debug("[PIPELINE] Phase 3: Logic polish")
                        polish_prompt = (
                            f"Polish this Cantonese text to be natural and warm:\n\n{final_response}"
                        )
                        logic_resp = await self.logic.infer_async(
                            polish_prompt, "", temperature=0.3, max_tokens=512
                        )
                        pipeline_stages.append("logic")
                        
                        if logic_resp.is_success():
                            final_response = logic_resp.content
                    except Exception as e:
                        logger.warning(f"[LOGIC] Error: {e}")

                inference_time = time.time() - start_time

                logger.info(
                    f"[COMPLETE] Full response generated in {inference_time:.2f}s "
                    f"(pipeline: {' -> '.join(pipeline_stages)})"
                )

                return LLMResponse(
                    content=final_response,
                    model_name="LLMService-v9.1",
                    inference_time=inference_time,
                    execution_track="slow" if use_psychology else "fast",
                    pipeline_stages=pipeline_stages,
                    soul_strategy=soul_strategy,
                    temperature=temperature or 0.7,
                    tokens_used=len(final_response.split())
                )

            except Exception as e:
                logger.error(f"[FAILED] Generation exception: {e}")
                return self._get_fallback_response(f"exception: {str(e)}", pipeline_stages)

    async def generate_v9_response_async(
        self,
        user_text: str,
        system_prompt: str = "",
        memory_context: str = "",
        emotion_profile: Optional[Dict[str, Any]] = None,
        shadow_context: str = "",
        risk_level: int = 0,
        temperature: Optional[float] = None,
        max_tokens: int = 512,
        persona_name: str = "希兒",
    ) -> LLMResponse:
        """
        v9 管線（改.txt 對齊）:
        Nemo (8081) 主生成 -> Llama (8082) 條件審核 -> Gemma (8083) 人格層
        """
        from app.config import config as app_config
        from app.utils.llm_availability import (
            is_main_llm_reachable,
            is_service_reachable,
        )
        from app.utils.meta_audit_gate import (
            should_run_meta_audit,
            extract_critic_score,
            should_regenerate_nemo,
            build_turn_meta_layer,
        )

        min_len = int(getattr(app_config, "V9_MIN_RESPONSE_LENGTH", 10))
        audit_enabled = getattr(app_config, "LLAMA_AUDIT_ENABLED", True)
        audit_risk_threshold = int(getattr(app_config, "LLAMA_AUDIT_RISK_THRESHOLD", 3))
        quality_threshold = float(
            getattr(app_config, "LLAMA_AUDIT_QUALITY_THRESHOLD", 0.7)
        )
        personality_enabled = getattr(app_config, "V9_PERSONALITY_ENABLED", True)
        nemo_regen_enabled = getattr(app_config, "V9_NEMO_REGEN_ON_LOW_QUALITY", True)
        nemo_regen_max = int(getattr(app_config, "V9_NEMO_REGEN_MAX", 1))

        async with self._concurrent_limit:
            start_time = time.time()
            pipeline_stages: List[str] = []
            emotion_profile = emotion_profile or {}
            meta_audit: Optional[Dict[str, Any]] = None
            audit_reason: Optional[str] = None
            meta_layer: Optional[Dict[str, Any]] = None
            nemo_regen_count = 0
            primary_text = ""
            working_text = ""

            try:
                self.stats['total_calls'] += 1

                main_ok, main_detail = await is_main_llm_reachable(timeout=2.0)
                logic_ok, _ = await is_service_reachable(
                    "logic_llm", app_config.LOGIC_LLM_URL, timeout=2.0,
                )
                revise_ok, _ = await is_service_reachable(
                    "revise_llm", app_config.REVISE_LLM_URL, timeout=2.0,
                )
                meta_enabled = getattr(app_config, "SEELE_META_CONTROLLER_ENABLED", False)

                async def _maybe_ensure_on_demand(
                    service_key: str,
                    url: str,
                    currently_ok: bool,
                ) -> bool:
                    if currently_ok or not meta_enabled:
                        return currently_ok
                    from app.utils.seele_meta_client import ensure_and_probe_llm

                    ok, detail = await ensure_and_probe_llm(
                        service_key,
                        url,
                        probe_timeout=3.0,
                    )
                    if ok:
                        pipeline_stages.append(f"meta_ensure_{service_key}")
                        logger.info("[V9] Meta ensure OK: %s", service_key)
                    else:
                        pipeline_stages.append(f"meta_ensure_failed_{service_key}")
                        logger.warning(
                            "[V9] Meta ensure failed: %s (%s)",
                            service_key,
                            detail,
                        )
                    return ok

                    return ok

                if meta_enabled:
                    if not logic_ok:
                        logic_ok = await _maybe_ensure_on_demand(
                            "logic_llm", app_config.LOGIC_LLM_URL, logic_ok,
                        )
                    if not revise_ok:
                        revise_ok = await _maybe_ensure_on_demand(
                            "revise_llm", app_config.REVISE_LLM_URL, revise_ok,
                        )

                if not main_ok and not logic_ok and not revise_ok:
                    return self._get_fallback_response(
                        "v9_all_generative_unreachable",
                        ["v9_aborted_unreachable"],
                    )

                context_parts = [system_prompt] if system_prompt else []
                if shadow_context:
                    context_parts.append(shadow_context)
                if memory_context:
                    context_parts.append(f"[Memories]\n{memory_context}")
                context_parts.append(
                    f"[Emotion] valence={emotion_profile.get('valence', 0.5):.2f}, "
                    f"arousal={emotion_profile.get('arousal', 0.3):.2f}, "
                    f"dominant={emotion_profile.get('dominant_emotion', 'neutral')}, "
                    f"risk_level={risk_level}"
                )
                combined_context = "\n\n".join(p for p in context_parts if p)

                # Step 1: Nemo primary generate (8081)
                if main_ok:
                    logger.debug("[V9] Step 1: Nemo primary generate (8081)")
                    nemo_resp = await self.soul.infer_primary_response(
                        user_text,
                        combined_context,
                        temperature=temperature or 0.7,
                        max_tokens=max_tokens,
                    )
                    pipeline_stages.append("nemo_primary")
                    if nemo_resp.is_success():
                        primary_text = (nemo_resp.content or "").strip()
                    else:
                        pipeline_stages.append("nemo_primary_failed")
                        logger.warning("[V9] Nemo primary failed: %s", nemo_resp.error)
                else:
                    logger.warning(
                        "[V9] Nemo (8081) unreachable (%s) — degraded primary path",
                        main_detail,
                    )
                    pipeline_stages.append("nemo_skipped_unreachable")

                # Degraded primary: Logic or Revise when Nemo unavailable / empty
                if len(primary_text) < min_len:
                    logic_ok = await _maybe_ensure_on_demand(
                        "logic_llm", app_config.LOGIC_LLM_URL, logic_ok,
                    )
                if len(primary_text) < min_len and logic_ok:
                    logger.debug("[V9] Degraded primary via Logic (8083)")
                    degrade_prompt = (
                        f"{combined_context}\n\n"
                        f"User:\n{user_text}\n\n"
                        "Write a warm Cantonese reply as Seele (希兒). Output ONLY the reply:"
                    )
                    deg = await self.logic.infer_async(
                        degrade_prompt,
                        "You are Seele (希兒), a Hong Kong psychological companion.",
                        temperature=0.7,
                        max_tokens=max_tokens,
                    )
                    pipeline_stages.append("logic_degraded_primary")
                    if deg.is_success():
                        primary_text = (deg.content or "").strip()

                if len(primary_text) < min_len:
                    revise_ok = await _maybe_ensure_on_demand(
                        "revise_llm", app_config.REVISE_LLM_URL, revise_ok,
                    )
                if len(primary_text) < min_len and revise_ok:
                    logger.debug("[V9] Degraded primary via Revise (8082)")
                    deg_user = (
                        f"{combined_context}\n\nUser:\n{user_text}\n\n"
                        "Reply as Seele in Cantonese:"
                    )
                    deg = await self.revise.infer_async(
                        deg_user,
                        "You are Seele (希兒), warm Hong Kong companion.",
                        temperature=0.8,
                        max_tokens=max_tokens,
                    )
                    pipeline_stages.append("revise_degraded_primary")
                    if deg.is_success():
                        primary_text = (deg.content or "").strip()

                working_text = primary_text
                if len(working_text) < min_len:
                    return self._get_fallback_response(
                        "v9_primary_too_short",
                        pipeline_stages,
                    )

                # Step 2: Conditional Llama Meta Auditor (8082)
                run_audit, audit_reason = should_run_meta_audit(
                    user_text=user_text,
                    risk_level=risk_level,
                    emotion_profile=emotion_profile,
                    memory_context=memory_context,
                    audit_enabled=audit_enabled,
                    risk_threshold=audit_risk_threshold,
                    primary_response=working_text,
                )

                if run_audit:
                    revise_ok = await _maybe_ensure_on_demand(
                        "revise_llm", app_config.REVISE_LLM_URL, revise_ok,
                    )

                if run_audit and revise_ok:
                    logger.debug("[V9] Step 2: Meta audit (%s)", audit_reason)
                    _, meta_audit = await self.revise.infer_meta_audit(
                        user_text,
                        working_text,
                        risk_level=risk_level,
                        emotion_profile=emotion_profile,
                        memory_context=memory_context,
                    )
                    pipeline_stages.append("llama_meta_audit")
                    if meta_audit:
                        critic_score = extract_critic_score(meta_audit)
                        revised = (meta_audit.get("revised_text") or "").strip()
                        risk_missed = bool(meta_audit.get("risk_missed", False))

                        if (
                            revised
                            and len(revised) >= min_len
                            and critic_score is not None
                            and critic_score < quality_threshold
                        ) or (
                            revised
                            and len(revised) >= min_len
                            and risk_missed
                        ):
                            working_text = revised
                            pipeline_stages.append("audit_revised")
                        elif nemo_regen_enabled and should_regenerate_nemo(
                            critic_score=critic_score,
                            quality_threshold=quality_threshold,
                            revised_text=revised,
                            min_len=min_len,
                            main_llm_ok=main_ok,
                            regen_count=nemo_regen_count,
                            max_regen=nemo_regen_max,
                            risk_missed=risk_missed,
                        ):
                            regen_feedback = (
                                f"\n\n[Meta Audit Feedback]\n"
                                f"critic_score={critic_score:.2f} (threshold={quality_threshold})\n"
                                f"risk_missed={risk_missed}\n"
                                f"empathy_score={meta_audit.get('empathy_score')}\n"
                                "Regenerate with stronger empathy, safety coverage, "
                                "and natural Cantonese. Do not be brief or evasive."
                            )
                            regen_context = combined_context + regen_feedback
                            logger.debug("[V9] Nemo regen (audit quality gate)")
                            regen_resp = await self.soul.infer_primary_response(
                                user_text,
                                regen_context,
                                temperature=temperature or 0.65,
                                max_tokens=max_tokens,
                            )
                            nemo_regen_count += 1
                            pipeline_stages.append("nemo_regen_audit_feedback")
                            if regen_resp.is_success():
                                regen_text = (regen_resp.content or "").strip()
                                if len(regen_text) >= min_len:
                                    working_text = regen_text
                                    primary_text = regen_text
                                else:
                                    pipeline_stages.append("nemo_regen_too_short")
                            else:
                                pipeline_stages.append("nemo_regen_failed")
                        elif critic_score is not None and critic_score < quality_threshold:
                            pipeline_stages.append("audit_low_quality_no_revision")
                elif run_audit:
                    pipeline_stages.append("audit_skipped_revise_unreachable")
                else:
                    pipeline_stages.append(f"audit_skipped:{audit_reason}")

                # Step 3: Gemma personality layer (8083)
                if personality_enabled:
                    logic_ok = await _maybe_ensure_on_demand(
                        "logic_llm", app_config.LOGIC_LLM_URL, logic_ok,
                    )
                if personality_enabled and logic_ok and working_text:
                    logger.debug("[V9] Step 3: Gemma personality (8083)")
                    persona_resp = await self.logic.infer_personality_layer(
                        working_text,
                        persona_name=persona_name,
                        shadow_context=shadow_context,
                    )
                    pipeline_stages.append("gemma_personality")
                    if persona_resp.is_success():
                        polished = (persona_resp.content or "").strip()
                        if len(polished) >= min_len:
                            working_text = polished
                        else:
                            pipeline_stages.append("personality_output_too_short")
                    else:
                        pipeline_stages.append("personality_failed")
                elif not logic_ok:
                    pipeline_stages.append("personality_skipped_unreachable")

                if len(working_text.strip()) < min_len:
                    return self._get_fallback_response(
                        "v9_final_too_short",
                        pipeline_stages,
                    )

                meta_layer = build_turn_meta_layer(
                    meta_audit=meta_audit,
                    audit_ran="llama_meta_audit" in pipeline_stages,
                    audit_reason=audit_reason,
                    nemo_regenerated="nemo_regen_audit_feedback" in pipeline_stages,
                    pipeline_stages=pipeline_stages,
                )

                inference_time = time.time() - start_time
                self.stats['slow_track_calls'] += 1
                logger.info(
                    "[V9] Complete in %.2fs (pipeline: %s)",
                    inference_time,
                    " -> ".join(pipeline_stages),
                )

                return LLMResponse(
                    content=working_text,
                    model_name="LLMService-v9",
                    inference_time=inference_time,
                    execution_track="v9",
                    pipeline_stages=pipeline_stages,
                    primary_text=primary_text,
                    draft_text=working_text,
                    meta_audit=meta_audit,
                    meta_layer=meta_layer,
                    audit_reason=audit_reason,
                    nemo_regenerated="nemo_regen_audit_feedback" in pipeline_stages,
                    temperature=temperature or 0.7,
                    tokens_used=len(working_text.split()),
                )

            except Exception as exc:
                logger.error("[V9] Pipeline exception: %s", exc)
                return self._get_fallback_response(
                    f"v9_exception: {exc}",
                    pipeline_stages,
                )

    async def generate_star_response_async(
        self,
        user_text: str,
        system_prompt: str = "",
        memory_context: str = "",
        emotion_profile: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 512,
        **kwargs: Any,
    ) -> LLMResponse:
        """Backward-compatible entry — delegates to v9 pipeline."""
        return await self.generate_v9_response_async(
            user_text=user_text,
            system_prompt=system_prompt,
            memory_context=memory_context,
            emotion_profile=emotion_profile,
            shadow_context=kwargs.get("shadow_context", ""),
            risk_level=int(kwargs.get("risk_level", 0) or 0),
            temperature=temperature,
            max_tokens=max_tokens,
            persona_name=kwargs.get("persona_name", "希兒"),
        )

    def _get_fallback_response(
        self,
        reason: str,
        pipeline_stages: List[str]
    ) -> LLMResponse:
        """回退回應（完整繁中保底，Zero-Truncation）"""
        return LLMResponse(
            content=(
                "寶貝，我而家需要少少時間整理思緒。"
                "我喺度陪住你，我哋慢慢傾，好嗎？你可以信任我，我會一直都在。"
            ),
            model_name="llm-fallback",
            error=reason,
            pipeline_stages=pipeline_stages,
            stop_reason=f"fallback: {reason}"
        )

    # ==================== 同步介面（FastAPI 相容） ====================

    def generate_response(self, user_message: str, **kwargs) -> Dict:
        """同步介面（用於 FastAPI）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已運行的循環中
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.generate_full_response_async(user_message, **kwargs)
                    )
                    resp = future.result()
            else:
                resp = loop.run_until_complete(
                    self.generate_full_response_async(user_message, **kwargs)
                )
            
            if isinstance(resp, LLMResponse):
                return resp.to_dict()
            return {
                'response': str(resp),
                'model': 'llm_service_v9.1_fallback',
                'success': False
            }
        except Exception as e:
            logger.error(f"[SYNC] Error: {e}")
            return {
                'response': "Sorry, I need a moment.",
                'model': 'llm_service_v9.1_error',
                'error': str(e),
                'success': False
            }

    def get_service_stats(self) -> Dict[str, Any]:
        """服務統計"""
        return {
            'timestamp': time.time(),
            'version': '9.1',
            'total_calls': self.stats['total_calls'],
            'soul': self.soul.get_stats(),
            'revise': self.revise.get_stats(),
            'vocal': self.revise.get_stats(),
            'logic': self.logic.get_stats()
        }

    async def close(self):
        """優雅關閉"""
        logger.info("[SHUTDOWN] LLMService closing...")
        try:
            await asyncio.gather(
                self.soul.close(),
                self.revise.close(),
                self.logic.close(),
                return_exceptions=True
            )
            logger.info("[OK] LLMService shutdown complete")
        except Exception as e:
            logger.error(f"[ERROR] Shutdown failed: {e}")


# ==================== 全局實例 ====================

_llm_service_instance: Optional[LLMService] = None


def get_llm_service() -> Optional[LLMService]:
    """取得全局 LLMService 實例"""
    global _llm_service_instance
    if _llm_service_instance is None:
        try:
            _llm_service_instance = LLMService()
        except Exception as e:
            logger.error(f"[FAILED] LLMService creation: {e}")
            _llm_service_instance = None
    return _llm_service_instance


async def shutdown_llm_service():
    """關閉全局實例"""
    global _llm_service_instance
    if _llm_service_instance:
        await _llm_service_instance.close()
        _llm_service_instance = None


# 創建預設實例
try:
    llm_service = get_llm_service()
    if llm_service:
        logger.info("[OK] Global LLMService ready (v9.1)")
    else:
        logger.error("[FAILED] Global LLMService creation")
except Exception as e:
    logger.error(f"[FAILED] LLMService module init: {e}")
    llm_service = None


__all__ = [
    'LLMService', 'LLMResponse', 'ModelConfig',
    'ModelType', 'TrackType',
    'SoulEngine', 'ReviseEngine', 'VocalEngine', 'LogicEngine',
    'get_llm_service', 'shutdown_llm_service', 'llm_service'
]