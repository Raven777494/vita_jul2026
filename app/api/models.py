# app/api/models.py

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, List, Any
from datetime import datetime

# ==========================================
# 【情緒分析模型】
# ==========================================

class EmotionAnalysis(BaseModel):
    """標準情緒分析結構"""
    valence: float = Field(default=0.0, ge=-1.0, le=1.0, description="正負情緒值")
    arousal: float = Field(default=0.0, ge=0.0, le=1.0, description="激動程度")
    dominance: float = Field(default=0.0, ge=-1.0, le=1.0, description="支配感")
    
    class Config:
        example = {
            "valence": 0.3,
            "arousal": 0.5,
            "dominance": 0.1
        }


# ==========================================
# 【聊天相關】
# ==========================================

class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="用戶輸入文本")
    user_id: str = Field(default="anonymous", description="用戶 ID")
    session_id: Optional[str] = Field(default=None, description="會話 ID")
    stream: bool = Field(default=False, description="是否使用流式輸出")
    
    class Config:
        example = {
            "text": "嗨，我好累呀",
            "user_id": "user_123",
            "session_id": None,
            "stream": False
        }


class ChatMeta(BaseModel):
    """聊天元數據 - 簡化版"""
    emotions: Dict[str, float] = Field(
        default_factory=dict, 
        description="情緒分析 {valence, arousal, dominance}"
    )
    risk_level: int = Field(default=0, ge=0, le=5, description="風險等級 0-5")
    phase: str = Field(default="unknown", description="對話階段")
    
    @field_validator('emotions')
    @classmethod
    def validate_emotions(cls, v):
        """確保 emotions 只包含數字"""
        if not isinstance(v, dict):
            return {}
        # 過濾出所有非數字值
        return {
            k: float(val) 
            for k, val in v.items() 
            if isinstance(val, (int, float))
        }
    
    @field_validator('phase')
    @classmethod
    def validate_phase(cls, v):
        """確保 phase 是非空字串"""
        if v is None or v == 'None':
            return 'unknown'
        phase_str = str(v).strip()
        return phase_str if phase_str else 'unknown'
    
    class Config:
        populate_by_name = True


class ChatResponse(BaseModel):
    """聊天回應模型"""
    text: str = Field(..., description="AI 回應文本")
    meta: ChatMeta = Field(..., description="元數據")
    success: bool = Field(default=True, description="是否成功")
    
    class Config:
        example = {
            "text": "你好！我在這裡陪你...",
            "meta": {
                "emotions": {"valence": 0.3, "arousal": 0.5, "dominance": 0.1},
                "risk_level": 0,
                "phase": "greeting"
            },
            "success": True
        }


# ==========================================
# 【會話管理】
# ==========================================

class SessionResponse(BaseModel):
    """會話回應模型"""
    session_id: str = Field(..., description="會話 ID")
    user_id: str = Field(..., description="用戶 ID")
    created_at: str = Field(..., description="創建時間")


class SessionDetailResponse(BaseModel):
    """會話詳情回應"""
    session_id: str
    user_id: str
    phase: str
    turn_count: int
    emotion_trend: List[Dict[str, float]]
    created_at: str


# ==========================================
# 【提醒與承諾】
# ==========================================

class ReminderRequest(BaseModel):
    """提醒請求模型"""
    user_id: str = Field(..., description="用戶 ID")
    reminder_text: str = Field(..., min_length=1, max_length=500, description="提醒文本")
    target_datetime: datetime = Field(..., description="目標時間")
    context: Optional[str] = Field(None, max_length=1000, description="原始上下文")


class ReminderResponse(BaseModel):
    """提醒回應模型"""
    reminder_id: str = Field(..., description="提醒 ID")
    user_id: str = Field(..., description="用戶 ID")
    created_at: str = Field(..., description="創建時間")


class RemindersListResponse(BaseModel):
    """提醒列表回應"""
    pending: List[Dict[str, Any]] = Field(default_factory=list, description="待觸發的提醒")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="已觸發的提醒")


# ==========================================
# 【對話摘要】
# ==========================================

class SummaryResponse(BaseModel):
    """摘要回應模型"""
    summary_id: int = Field(..., description="摘要 ID")
    summary_text: str = Field(..., description="摘要文本")
    key_emotions: List[str] = Field(default_factory=list, description="關鍵情緒")
    key_topics: List[str] = Field(default_factory=list, description="關鍵話題")


# ==========================================
# 【用戶偏好】
# ==========================================

class UserPreferencesRequest(BaseModel):
    """用戶偏好更新"""
    favorite_books: Optional[List[str]] = None
    favorite_music: Optional[List[str]] = None
    favorite_activities: Optional[List[str]] = None
    preferred_temperature: Optional[float] = Field(None, ge=0.1, le=1.0)
    language_style: Optional[str] = None


class UserPreferencesResponse(BaseModel):
    """用戶偏好回應"""
    user_id: str
    favorite_books: List[str]
    favorite_music: List[str]
    favorite_activities: List[str]
    preferred_temperature: float
    language_style: str


# ==========================================
# 【天氣相關】
# ==========================================

class WeatherResponse(BaseModel):
    """天氣回應"""
    forecast: Optional[Dict[str, str]] = None
    regional_temps: Optional[Dict[str, float]] = None
    solar_lunar: Optional[Dict[str, Any]] = None
    timestamp: str


# ==========================================
# 【干預卡片】
# ==========================================

class InterventionCard(BaseModel):
    """干預卡片模型"""
    code: str
    title: str
    content: str
    safe_score: float = 1.0
    trigger_logic: Dict[str, Any] = Field(default_factory=dict)


class InterventionCardsResponse(BaseModel):
    """干預卡片回應"""
    cards: List[InterventionCard]
    count: int


# ==========================================
# 【Vita 版本】
# ==========================================

class VitaVersionRequest(BaseModel):
    """Vita 版本創建請求"""
    version_name: str = Field(..., min_length=1, max_length=100)
    prompt_text: str = Field(..., min_length=1)


class VitaVersionResponse(BaseModel):
    """Vita 版本回應"""
    version_id: int
    version_name: str
    status: str


# ==========================================
# 【健康檢查】
# ==========================================

class HealthResponse(BaseModel):
    """健康檢查回應"""
    status: str
    services: Dict[str, Any]
    timestamp: str


class HealthDetailedResponse(BaseModel):
    """詳細健康檢查回應"""
    status: str
    services: Dict[str, Any]
    timestamp: str
    error: Optional[str] = None


# ==========================================
# 【錯誤回應】
# ==========================================

class ErrorResponse(BaseModel):
    """錯誤回應模型"""
    error: str
    detail: Optional[str] = None
    timestamp: str