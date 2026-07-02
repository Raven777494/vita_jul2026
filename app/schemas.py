# app/schemas.py

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Dict, Any, List, Literal
from enum import Enum
from datetime import datetime, timezone

# ==================== 枚舉定義 ====================

class LanguageCode(str, Enum):
    """支持的語言代碼"""
    CANTONESE = "yue-Hant"      # 粵語（繁體）
    MANDARIN_SIMPLIFIED = "zh-Hans"  # 普通話（簡體）
    MANDARIN_TRADITIONAL = "zh-Hant"  # 普通話（繁體）
    ENGLISH = "en"               # 英語
    JAPANESE = "ja"              # 日語

# 【修復 E.txt 崩潰】為相容 main.py 的導入，建立型別別名
LangCode = LanguageCode

class CodeMixingLevel(str, Enum):
    """代碼混合的允許級別"""
    NONE = "none"                # 完全不允許英文
    TECHNICAL = "technical"      # 允許技術術語
    CASUAL = "casual"            # 允許日常英文詞彙
    FULL = "full"                # 完全允許代碼混合


class DialoguePhase(str, Enum):
    """對話階段"""
    GREETING = "greeting"
    EXPLORATION = "exploration"
    DEEP_ENGAGEMENT = "deep_engagement"
    CRISIS = "crisis"
    RESOLUTION = "resolution"
    CLOSURE = "closure"
    DREAM_WEAVING = "dream_weaving"
    UNKNOWN = "unknown"
    ERROR = "error"


class RiskLevel(int, Enum):
    """風險等級"""
    NONE = 0
    LOW = 1
    MODERATE = 2
    SIGNIFICANT = 3
    HIGH = 4
    CRITICAL = 5


class TTSVoiceGender(str, Enum):
    """TTS 語音性別"""
    FEMALE = "female"
    MALE = "male"
    NEUTRAL = "neutral"


# ==================== 請求 Schema ====================

class ChatRequest(BaseModel):
    """聊天請求"""
    
    user_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique user identifier"
    )
    
    session_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=256,
        description="Conversation session ID"
    )
    
    text: str = Field(
        ...,
        alias="message",
        min_length=1,
        max_length=5000,
        description="Input text from user"
    )
    
    lang: Optional[LanguageCode] = Field(
        None,
        description="Explicitly specified output language (if not specified, auto-detect)"
    )
    
    detected_lang: Optional[LanguageCode] = Field(
        None,
        description="Client-side detected input language (for analytics)"
    )
    
    code_mixing: Optional[CodeMixingLevel] = Field(
        CodeMixingLevel.CASUAL,
        description="Allow English code-mixing in response"
    )
    
    tts: Optional[bool] = Field(
        False,
        description="Require TTS audio generation"
    )
    
    tts_voice_gender: Optional[TTSVoiceGender] = Field(
        TTSVoiceGender.FEMALE,
        description="Preferred TTS voice gender"
    )
    
    tts_speed: Optional[float] = Field(
        1.0,
        ge=0.5,
        le=2.0,
        description="TTS playback speed (0.5x to 2.0x)"
    )
    
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional client metadata (e.g., device info, context)"
    )
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "user_id": "user_12345",
                "session_id": "sess_abc123",
                "message": "我最近感到很沮喪",
                "lang": "yue-Hant",
                "detected_lang": "yue-Hant",
                "code_mixing": "casual",
                "tts": True,
                "tts_voice_gender": "female",
                "tts_speed": 1.0,
                "metadata": {
                    "device": "mobile",
                    "timezone": "Asia/Hong_Kong"
                }
            }
        }
    
    @field_validator('tts_speed')
    def validate_tts_speed(cls, v):
        """驗證 TTS 速度"""
        if v is not None and (v < 0.5 or v > 2.0):
            raise ValueError('tts_speed must be between 0.5 and 2.0')
        return v


# ==================== 回應 Schema ====================

class ChatMeta(BaseModel):
    """聊天後設數據"""
    
    emotions: Dict[str, float] = Field(
        ...,
        description="VAD emotion vector (valence, arousal, dominance)"
    )
    
    risk_level: RiskLevel = Field(
        ...,
        description="Risk level assessment (0-5)"
    )
    
    phase: DialoguePhase = Field(
        ...,
        description="Current dialogue phase"
    )
    
    language: LanguageCode = Field(
        ...,
        description="Language used for the response"
    )
    
    detected_input_lang: Optional[LanguageCode] = Field(
        None,
        description="Detected language of the input text"
    )
    
    code_mixing_applied: Optional[CodeMixingLevel] = Field(
        None,
        description="Code-mixing level actually applied in response"
    )
    
    confidence_scores: Optional[Dict[str, float]] = Field(
        None,
        description="Confidence scores for various predictions (emotion, phase, etc.)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "emotions": {
                    "valence": -0.5,
                    "arousal": 0.7,
                    "dominance": -0.2
                },
                "risk_level": 3,
                "phase": "deep_engagement",
                "language": "yue-Hant",
                "detected_input_lang": "yue-Hant",
                "code_mixing_applied": "casual",
                "confidence_scores": {
                    "emotion": 0.85,
                    "phase": 0.92,
                    "risk": 0.78
                }
            }
        }


class TTSAudioMetadata(BaseModel):
    """TTS 音頻後設數據"""
    
    audio_url: str = Field(
        ...,
        description="URL to the generated TTS audio file"
    )
    
    duration_seconds: float = Field(
        ...,
        ge=0.1,
        description="Audio duration in seconds"
    )
    
    format: Literal["mp3", "wav", "ogg", "webm"] = Field(
        ...,
        description="Audio format"
    )
    
    language: LanguageCode = Field(
        ...,
        description="Language of the TTS audio"
    )
    
    voice_gender: TTSVoiceGender = Field(
        ...,
        description="Gender of the TTS voice"
    )
    
    voice_speed: float = Field(
        ...,
        ge=0.5,
        le=2.0,
        description="Speed multiplier used for TTS generation"
    )


class ChatResponse(BaseModel):
    """聊天回應"""
    
    text: str = Field(
        ...,
        description="Response text content"
    )
    
    meta: ChatMeta = Field(
        ...,
        description="Response metadata"
    )
    
    success: bool = Field(
        True,
        description="Whether the request was processed successfully"
    )
    
    tts_audio: Optional[TTSAudioMetadata] = Field(
        None,
        description="TTS audio information (if requested)"
    )
    
    warnings: Optional[List[str]] = Field(
        None,
        description="List of non-fatal warnings"
    )
    
    latency_ms: int = Field(
        ...,
        ge=0,
        description="Request processing time in milliseconds"
    )
    
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Response generation timestamp"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "text": "我明白您的感受。最近的壓力確實可能讓人感到無力...",
                "meta": {
                    "emotions": {
                        "valence": 0.3,
                        "arousal": 0.5,
                        "dominance": 0.0
                    },
                    "risk_level": 2,
                    "phase": "deep_engagement",
                    "language": "yue-Hant",
                    "detected_input_lang": "yue-Hant",
                    "code_mixing_applied": "casual",
                    "confidence_scores": {
                        "emotion": 0.88,
                        "phase": 0.95,
                        "risk": 0.82
                    }
                },
                "success": True,
                "tts_audio": {
                    "audio_url": "https://example.com/audio/sess_abc123_123456.mp3",
                    "duration_seconds": 12.5,
                    "format": "mp3",
                    "language": "yue-Hant",
                    "voice_gender": "female",
                    "voice_speed": 1.0
                },
                "warnings": None,
                "latency_ms": 285,
                "timestamp": "2024-04-12T10:30:45.123Z"
            }
        }


# ==================== 錯誤 Schema ====================

class ErrorDetail(BaseModel):
    """錯誤詳情"""
    
    error_code: str = Field(
        ...,
        description="Machine-readable error code"
    )
    
    error_message: str = Field(
        ...,
        description="Human-readable error message"
    )
    
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional error context"
    )


class ErrorResponse(BaseModel):
    """標準錯誤回應"""
    
    success: bool = Field(
        False,
        description="Always False for errors"
    )
    
    error: ErrorDetail = Field(
        ...,
        description="Error information"
    )
    
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Error timestamp"
    )
    
    request_id: Optional[str] = Field(
        None,
        description="Unique request identifier for debugging"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": {
                    "error_code": "ORCHESTRATOR_UNAVAILABLE",
                    "error_message": "Core AI service is temporarily unavailable",
                    "details": {
                        "retry_after_seconds": 30
                    }
                },
                "timestamp": "2024-04-12T10:30:45.123Z",
                "request_id": "req_xyz789"
            }
        }


# ==================== 健康檢查 Schema ====================

class ModelStatus(BaseModel):
    """單個模型狀態"""
    
    name: str = Field(..., description="Model name")
    loaded: bool = Field(..., description="Whether model is loaded in memory")
    version: str = Field(..., description="Model version")
    last_used: Optional[datetime] = Field(None, description="Last usage timestamp")


class HealthResponse(BaseModel):
    """健康檢查回應"""
    
    status: Literal["online", "degraded", "offline"] = Field(
        ...,
        description="Overall system status"
    )
    
    environment: str = Field(
        ...,
        description="Current environment (development/production)"
    )
    
    orchestrator_status: Literal["ready", "unavailable", "degraded"] = Field(
        ...,
        description="Orchestrator service status"
    )
    
    redis_status: Literal["connected", "disconnected", "degraded"] = Field(
        ...,
        description="Redis connection status"
    )
    
    models: Dict[str, ModelStatus] = Field(
        ...,
        description="Status of loaded models"
    )
    
    uptime_seconds: int = Field(
        ...,
        ge=0,
        description="Server uptime in seconds"
    )
    
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Health check timestamp"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "online",
                "environment": "production",
                "orchestrator_status": "ready",
                "redis_status": "connected",
                "models": {
                    "emotion_classifier": {
                        "name": "Emotion Classifier v2.1",
                        "loaded": True,
                        "version": "2.1.0",
                        "last_used": "2024-04-12T10:29:30Z"
                    },
                    "phase_detector": {
                        "name": "Phase Detector v1.5",
                        "loaded": True,
                        "version": "1.5.0",
                        "last_used": "2024-04-12T10:29:45Z"
                    }
                },
                "uptime_seconds": 3600,
                "timestamp": "2024-04-12T10:30:45.123Z"
            }
        }


# ==================== 向量化 Schema ====================

class EmbeddingRequest(BaseModel):
    """文本向量化請求"""
    
    texts: List[str] = Field(
        ...,
        min_items=1,
        max_items=100,
        description="List of texts to embed"
    )
    
    model: Optional[str] = Field(
        "default",
        description="Embedding model to use"
    )
    
    language: Optional[LanguageCode] = Field(
        None,
        description="Language of the texts (for model selection)"
    )
    
    normalize: Optional[bool] = Field(
        True,
        description="Normalize vectors to unit length"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "texts": [
                    "我感到很沮喪",
                    "最近工作壓力很大",
                    "生活缺乏意義"
                ],
                "model": "default",
                "language": "yue-Hant",
                "normalize": True
            }
        }


class VectorMetadata(BaseModel):
    """單個向量的後設數據"""
    
    text: str = Field(..., description="Original text")
    dimension: int = Field(..., description="Vector dimension")
    norm: float = Field(..., description="Vector L2 norm (if not normalized)")


class EmbeddingResponse(BaseModel):
    """向量化回應"""
    
    vectors: List[List[float]] = Field(
        ...,
        description="Embedding vectors"
    )
    
    metadata: List[VectorMetadata] = Field(
        ...,
        description="Metadata for each vector"
    )
    
    model: str = Field(
        ...,
        description="Model used for embedding"
    )
    
    dimension: int = Field(
        ...,
        description="Dimension of each embedding vector"
    )
    
    distance_metric: Literal["cosine", "euclidean", "dot_product"] = Field(
        ...,
        description="Recommended distance metric for similarity search"
    )
    
    latency_ms: int = Field(
        ...,
        ge=0,
        description="Processing time in milliseconds"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "vectors": [
                    [0.1, 0.2, 0.3, -0.1, 0.05],
                    [0.15, 0.22, 0.28, -0.12, 0.08],
                    [0.12, 0.18, 0.32, -0.08, 0.06]
                ],
                "metadata": [
                    {
                        "text": "我感到很沮喪",
                        "dimension": 5,
                        "norm": 0.425
                    },
                    {
                        "text": "最近工作壓力很大",
                        "dimension": 5,
                        "norm": 0.438
                    },
                    {
                        "text": "生活缺乏意義",
                        "dimension": 5,
                        "norm": 0.421
                    }
                ],
                "model": "default",
                "dimension": 5,
                "distance_metric": "cosine",
                "latency_ms": 45
            }
        }


# ==================== 語言偏好 Schema ====================

class UserLanguagePreference(BaseModel):
    """用戶語言偏好"""
    
    user_id: str = Field(..., description="User ID")
    primary_language: LanguageCode = Field(..., description="Primary language")
    secondary_language: Optional[LanguageCode] = Field(None, description="Secondary language")
    code_mixing_preference: CodeMixingLevel = Field(
        ...,
        description="Code-mixing preference"
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp"
    )


class UserLanguagePreferenceUpdate(BaseModel):
    """更新用戶語言偏好"""
    
    primary_language: Optional[LanguageCode] = Field(None, description="Primary language")
    secondary_language: Optional[LanguageCode] = Field(None, description="Secondary language")
    code_mixing_preference: Optional[CodeMixingLevel] = Field(None, description="Code-mixing preference")


# ==================== 批次處理 Schema ====================

class BatchChatRequest(BaseModel):
    """批次聊天請求"""
    
    requests: List[ChatRequest] = Field(
        ...,
        min_items=1,
        max_items=10,
        description="List of chat requests"
    )
    
    parallel: Optional[bool] = Field(
        False,
        description="Process requests in parallel if possible"
    )


class BatchChatResponse(BaseModel):
    """批次聊天回應"""
    
    results: List[ChatResponse] = Field(
        ...,
        description="List of responses corresponding to requests"
    )
    
    total_latency_ms: int = Field(
        ...,
        ge=0,
        description="Total processing time in milliseconds"
    )
    
    success_count: int = Field(
        ...,
        ge=0,
        description="Number of successful requests"
    )
    
    failure_count: int = Field(
        ...,
        ge=0,
        description="Number of failed requests"
    )


# ==================== 匯出 ====================

__all__ = [
    # Enums
    "LanguageCode",
    "LangCode",  # 【修復】加入 LangCode 匯出
    "CodeMixingLevel",
    "DialoguePhase",
    "RiskLevel",
    "TTSVoiceGender",
    # Requests
    "ChatRequest",
    "EmbeddingRequest",
    "BatchChatRequest",
    # Responses
    "ChatResponse",
    "ChatMeta",
    "TTSAudioMetadata",
    "EmbeddingResponse",
    "VectorMetadata",
    "HealthResponse",
    "ModelStatus",
    # Errors
    "ErrorResponse",
    "ErrorDetail",
    # User Preferences
    "UserLanguagePreference",
    "UserLanguagePreferenceUpdate",
    # Batch
    "BatchChatResponse",
]