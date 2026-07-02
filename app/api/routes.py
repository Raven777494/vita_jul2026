# app/api/routes.py

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
import json
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from threading import Lock

from app.orchestrator import Orchestrator
from app.api.models import (
    ChatRequest, ChatResponse, ChatMeta, SessionResponse, SessionDetailResponse,
    ReminderRequest, ReminderResponse, RemindersListResponse,
    SummaryResponse, UserPreferencesRequest, UserPreferencesResponse,
    WeatherResponse, InterventionCardsResponse, InterventionCard,
    VitaVersionRequest, VitaVersionResponse, HealthResponse, HealthDetailedResponse,
    ErrorResponse
)
from app.logger import get_logger, get_crisis_logger
from app.utils.security import get_current_user

logger = get_logger(__name__)
crisis_logger = get_crisis_logger()
router = APIRouter(tags=["chat"])

# ===== 執行緒安全的依賴注入 =====
_orchestrator_instance: Optional[Orchestrator] = None
_orchestrator_lock = Lock()

def get_orchestrator() -> Orchestrator:
    """獲取編排器實例（執行緒安全單例模式）"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        with _orchestrator_lock:
            if _orchestrator_instance is None:
                _orchestrator_instance = Orchestrator()
    return _orchestrator_instance


# ===== 輔助函數 =====
async def trigger_crisis_alert(user_id: str, risk_level: int, session_id: str):
    """觸發危機警報（具有錯誤處理）"""
    try:
        crisis_logger.critical(
            f"CRISIS_ALERT | user_id={user_id} | risk_level={risk_level} | session_id={session_id}"
        )
        logger.warning(f"Crisis alert triggered for user {user_id} (risk={risk_level})")
    except Exception as e:
        logger.error(f"Error triggering crisis alert: {e}", exc_info=True)


def validate_user_id(user_id: str) -> bool:
    """驗證用戶ID格式"""
    return isinstance(user_id, str) and len(user_id.strip()) > 0


def validate_session_id(session_id: str) -> bool:
    """驗證會話ID格式"""
    return isinstance(session_id, str) and len(session_id.strip()) > 0


# ==========================================
# 【聊天核心端點】
# ==========================================

@router.post(
    "/chat",
    response_model=ChatResponse,
    description="發送聊天訊息 - 非流式端點",
    dependencies=[Depends(get_current_user)]
)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """
    主聊天端點（非流式）
    - 已啟用安全認證與純非同步管線
    - 完整的錯誤處理與日誌記錄
    - 危機風險檢測與背景警報
    """
    try:
        # 輸入驗證
        if not validate_user_id(request.user_id):
            logger.warning(f"Invalid user_id format: {request.user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        if not validate_session_id(request.session_id):
            logger.warning(f"Invalid session_id format: {request.session_id}")
            raise HTTPException(status_code=400, detail="Invalid session_id format")
        
        if not request.text or len(request.text.strip()) == 0:
            raise HTTPException(status_code=400, detail="Message text cannot be empty")
        
        logger.info(f"Chat request from {request.user_id}: {request.text[:50]}")
        
        # 優先使用 async 版本
        result = None
        if hasattr(orc, 'process_user_message_async') and callable(getattr(orc, 'process_user_message_async')):
            result = await orc.process_user_message_async(
                session_id=request.session_id,
                user_id=request.user_id,
                user_text=request.text
            )
        elif hasattr(orc, 'process_user_message') and callable(getattr(orc, 'process_user_message')):
            result = await orc.process_user_message(
                session_id=request.session_id,
                user_id=request.user_id,
                user_text=request.text,
                stream=request.stream
            )
        else:
            logger.error(f"Orchestrator missing required message processing methods")
            raise HTTPException(status_code=500, detail="Service configuration error")
        
        # 檢查處理結果
        if not result or not isinstance(result, dict) or not result.get('success'):
            logger.error(f"Processing failed for user {request.user_id}")
            raise HTTPException(status_code=500, detail="Processing failed")
        
        # 危機風險評估與警報（risk_level >= 4 時觸發）
        risk_level = result.get('risk_level', 0)
        if isinstance(risk_level, (int, float)) and risk_level >= 4:
            background_tasks.add_task(
                trigger_crisis_alert,
                user_id=request.user_id,
                risk_level=risk_level,
                session_id=request.session_id
            )
            logger.warning(
                f"Crisis condition detected for {request.user_id} (risk_level={risk_level})"
            )
        
        # 提取回應文本（支援多種欄位格式）
        response_text = (
            result.get('text') or
            result.get('assistant_response') or
            result.get('response') or
            "我在這裡，請告訴我你的想法。"
        )
        
        if not isinstance(response_text, str):
            response_text = str(response_text)
        
        # 構建元數據
        emotion_analysis = result.get('emotion_analysis', {})
        if not isinstance(emotion_analysis, dict):
            emotion_analysis = {}
        
        meta = ChatMeta(
            emotions=emotion_analysis,
            risk_level=risk_level,
            phase=result.get('phase', 'unknown')
        )
        
        logger.info(
            f"Chat processed successfully for {request.user_id} "
            f"(phase={result.get('phase', 'unknown')}, risk_level={risk_level})"
        )
        
        return ChatResponse(
            text=response_text,
            meta=meta,
            success=bool(result.get('success', True)),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    "/chat/stream",
    dependencies=[Depends(get_current_user)]
)
async def chat_stream(
    request: ChatRequest,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """
    流式聊天端點（Server-Sent Events / SSE）
    - 即時訊息流式傳輸
    - 完整的錯誤處理與格式遵循
    - 自動降級至非流式處理
    """
    
    # 輸入驗證
    if not validate_user_id(request.user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    if not validate_session_id(request.session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")
    
    if not request.text or len(request.text.strip()) == 0:
        raise HTTPException(status_code=400, detail="Message text cannot be empty")
    
    try:
        logger.info(f"Stream chat initiated from {request.user_id}")
        
        async def generate():
            """SSE 格式流生成器"""
            try:
                # 嘗試使用原生流式方法
                if hasattr(orc, 'stream_user_message_async') and callable(getattr(orc, 'stream_user_message_async')):
                    async for chunk in orc.stream_user_message_async(
                        session_id=request.session_id,
                        user_id=request.user_id,
                        user_text=request.text
                    ):
                        # 確保 SSE 格式正確
                        if isinstance(chunk, str):
                            yield f"data: {chunk}\n\n"
                        else:
                            yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    # 降級至非流式處理，使用打字機效果模擬
                    logger.info(f"Falling back to non-stream processing for {request.user_id}")
                    
                    result = None
                    if hasattr(orc, 'process_user_message_async') and callable(getattr(orc, 'process_user_message_async')):
                        result = await orc.process_user_message_async(
                            session_id=request.session_id,
                            user_id=request.user_id,
                            user_text=request.text
                        )
                    elif hasattr(orc, 'process_user_message') and callable(getattr(orc, 'process_user_message')):
                        result = await orc.process_user_message(
                            session_id=request.session_id,
                            user_id=request.user_id,
                            user_text=request.text,
                            stream=False
                        )
                    
                    if result and isinstance(result, dict) and result.get('success'):
                        response_text = (
                            result.get('text') or
                            result.get('assistant_response') or
                            result.get('response') or
                            ""
                        )
                        
                        if not isinstance(response_text, str):
                            response_text = str(response_text)
                        
                        # 逐字符流式輸出（打字機效果）
                        for char in response_text:
                            yield f"data: {char}\n\n"
                            await asyncio.sleep(0.02)  # 20ms 延遲
                        
                        logger.info(f"Stream fallback completed for {request.user_id}")
                    else:
                        logger.error(f"Stream processing failed for {request.user_id}")
                        error_msg = json.dumps({
                            "error": "Processing failed",
                            "user_id": request.user_id
                        })
                        yield f"data: {error_msg}\n\n"
            
            except asyncio.CancelledError:
                logger.info(f"Stream cancelled for {request.user_id}")
            except Exception as e:
                logger.error(f"Stream generation error: {e}", exc_info=True)
                error_msg = json.dumps({
                    "error": str(e),
                    "user_id": request.user_id
                })
                yield f"data: {error_msg}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*"
            }
        )
    
    except Exception as e:
        logger.error(f"Stream endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【會話管理端點】
# ==========================================

@router.post(
    "/session/create",
    response_model=SessionResponse,
    dependencies=[Depends(get_current_user)]
)
async def create_session(
    user_id: str = Query(..., min_length=1, max_length=255),
    persona: str = Query(default="friend", min_length=1, max_length=50),
    temperature: float = Query(default=0.7, ge=0.0, le=1.0),
    orc: Orchestrator = Depends(get_orchestrator)
):
    """建立新對話會話"""
    try:
        if not validate_user_id(user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id")
        
        session_id = orc.create_new_session(
            user_id=user_id,
            persona=persona,
            temperature=temperature
        )
        
        if not session_id:
            logger.error(f"Failed to create session for user {user_id}")
            raise HTTPException(status_code=500, detail="Failed to create session")
        
        logger.info(f"Session created: {session_id} for user {user_id}")
        
        return SessionResponse(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.now().isoformat()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session creation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/session/{session_id}",
    response_model=SessionDetailResponse,
    dependencies=[Depends(get_current_user)]
)
async def get_session(
    session_id: str,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """取得會話詳細信息"""
    try:
        if not validate_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format")
        
        if not hasattr(orc, 'session_states') or session_id not in orc.session_states:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = orc.session_states[session_id]
        
        return SessionDetailResponse(
            session_id=session_id,
            user_id=state.get('user_id', ''),
            phase=state.get('phase', 'unknown'),
            turn_count=int(state.get('turn_count', 0)),
            emotion_trend=state.get('emotion_trend', []),
            created_at=state.get('created_at', '')
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session retrieval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【提醒功能端點】
# ==========================================

@router.post(
    "/reminder/create",
    response_model=ReminderResponse,
    dependencies=[Depends(get_current_user)]
)
async def create_reminder(
    request: ReminderRequest,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """建立使用者提醒（修正：使用 original_context）"""
    try:
        if not validate_user_id(request.user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id")
        
        if not request.reminder_text or len(request.reminder_text.strip()) == 0:
            raise HTTPException(status_code=400, detail="Reminder text cannot be empty")
        
        # 優先使用 original_context，回退至 context
        context = getattr(request, 'original_context', None) or getattr(request, 'context', '')
        
        reminder_id = orc.create_user_reminder(
            user_id=request.user_id,
            reminder_text=request.reminder_text,
            target_datetime=request.target_datetime,
            context=context
        )
        
        if not reminder_id:
            logger.error(f"Failed to create reminder for user {request.user_id}")
            raise HTTPException(status_code=500, detail="Failed to create reminder")
        
        logger.info(f"Reminder created for user {request.user_id} (id={reminder_id})")
        
        return ReminderResponse(
            reminder_id=reminder_id,
            user_id=request.user_id,
            created_at=datetime.now().isoformat()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reminder creation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/reminder/{user_id}",
    response_model=RemindersListResponse,
    dependencies=[Depends(get_current_user)]
)
async def get_reminders(
    user_id: str,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """取得使用者提醒列表"""
    try:
        if not validate_user_id(user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        reminders = orc.get_user_reminders(user_id)
        
        if not reminders or not isinstance(reminders, dict):
            reminders = {'pending': [], 'history': []}
        
        return RemindersListResponse(
            pending=reminders.get('pending', []),
            history=reminders.get('history', [])
        )
    
    except Exception as e:
        logger.error(f"Reminders retrieval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【會話摘要與搜索端點】
# ==========================================

@router.post(
    "/summary/{session_id}",
    response_model=SummaryResponse,
    dependencies=[Depends(get_current_user)]
)
async def generate_summary(
    session_id: str,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """生成會話摘要"""
    try:
        if not validate_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format")
        
        summary = orc.generate_session_summary(session_id)
        
        if not summary or not isinstance(summary, dict):
            raise HTTPException(status_code=500, detail="Summary generation failed")
        
        return SummaryResponse(
            summary_id=summary.get('summary_id', 0),
            summary_text=summary.get('summary_text', ''),
            key_emotions=summary.get('key_emotions', []),
            key_topics=summary.get('key_topics', [])
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Summary generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/search/similar",
    dependencies=[Depends(get_current_user)]
)
async def search_similar_conversations(
    user_id: str = Query(..., min_length=1, max_length=255),
    query: str = Query(..., min_length=1, max_length=1000),
    limit: int = Query(default=5, ge=1, le=50),
    orc: Orchestrator = Depends(get_orchestrator)
):
    """搜索相似的過往對話"""
    try:
        if not validate_user_id(user_id):
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        results = orc.get_relevant_past_conversations(
            user_id=user_id,
            query_text=query,
            limit=limit
        )
        
        if not results:
            results = []
        
        return {
            'user_id': user_id,
            'query': query,
            'results': results,
            'count': len(results)
        }
    
    except Exception as e:
        logger.error(f"Similar conversations search error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【天氣端點】
# ==========================================

@router.get(
    "/weather/forecast",
    response_model=WeatherResponse
)
async def get_weather(
    orc: Orchestrator = Depends(get_orchestrator)
):
    """
    獲取天氣預報（修正：效能最佳化，單次API呼叫）
    """
    try:
        logger.info("Fetching weather data")
        
        if not hasattr(orc, 'hko') or orc.hko is None:
            raise HTTPException(
                status_code=503,
                detail="Weather service not available"
            )
        
        # 單次呼叫區域溫度API
        regional_data = orc.hko.get_regional_temperature()
        regional_temps = regional_data.get('regions') if regional_data else None
        
        forecast = orc.hko.get_weather_forecast() if hasattr(orc.hko, 'get_weather_forecast') else {}
        solar_lunar = orc.hko.get_solar_lunar_data() if hasattr(orc.hko, 'get_solar_lunar_data') else {}
        
        return WeatherResponse(
            forecast=forecast,
            regional_temps=regional_temps,
            solar_lunar=solar_lunar,
            timestamp=datetime.now().isoformat()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Weather fetch error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【干預卡片端點】
# ==========================================

@router.get(
    "/intervention-cards",
    response_model=InterventionCardsResponse,
    dependencies=[Depends(get_current_user)]
)
async def get_intervention_cards(
    session_id: str = Query(..., min_length=1, max_length=255),
    orc: Orchestrator = Depends(get_orchestrator)
):
    """
    取得干預卡片（修正：安全索引訪問）
    """
    try:
        if not validate_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id format")
        
        if not hasattr(orc, 'session_states') or session_id not in orc.session_states:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = orc.session_states[session_id]
        
        cards = []
        if hasattr(orc, 'recommend_intervention_cards') and callable(getattr(orc, 'recommend_intervention_cards')):
            risk_level = state.get('risk_level', 0)
            
            # 安全提取最近情緒（避免索引錯誤）
            recent_emotions = state.get('recent_emotions', [])
            emotion_state = recent_emotions[-1] if isinstance(recent_emotions, list) and len(recent_emotions) > 0 else {}
            
            cards = orc.recommend_intervention_cards(
                session_id=session_id,
                risk_level=risk_level,
                emotion_state=emotion_state
            )
        
        if not isinstance(cards, list):
            cards = []
        
        return InterventionCardsResponse(
            cards=cards,
            count=len(cards)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Intervention cards retrieval error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/intervention-cards/custom",
    dependencies=[Depends(get_current_user)]
)
async def add_intervention_card(
    request: InterventionCard,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """新增自訂干預卡片"""
    try:
        if not request.code or len(request.code.strip()) == 0:
            raise HTTPException(status_code=400, detail="Card code cannot be empty")
        
        if not request.title or len(request.title.strip()) == 0:
            raise HTTPException(status_code=400, detail="Card title cannot be empty")
        
        if hasattr(orc, 'add_custom_intervention_card') and callable(getattr(orc, 'add_custom_intervention_card')):
            result = orc.add_custom_intervention_card(
                code=request.code,
                title=request.title,
                content=request.content,
                trigger_logic=request.trigger_logic or {'always': True}
            )
            
            if not result:
                raise HTTPException(status_code=500, detail="Failed to add card")
        
        logger.info(f"Intervention card added: {request.code}")
        
        return {'success': True, 'code': request.code}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add intervention card error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【Vita 版本管理端點】
# ==========================================

@router.post(
    "/vita/version/create",
    response_model=VitaVersionResponse,
    dependencies=[Depends(get_current_user)]
)
async def create_vita_version(
    request: VitaVersionRequest,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """建立新 Vita 版本"""
    try:
        if not request.version_name or len(request.version_name.strip()) == 0:
            raise HTTPException(status_code=400, detail="Version name cannot be empty")
        
        if not request.prompt_text or len(request.prompt_text.strip()) == 0:
            raise HTTPException(status_code=400, detail="Prompt text cannot be empty")
        
        if hasattr(orc, 'create_new_vita_version') and callable(getattr(orc, 'create_new_vita_version')):
            version_id = orc.create_new_vita_version(
                version_name=request.version_name,
                prompt_text=request.prompt_text,
                persona_card={'default': 'friend'}
            )
            
            if not version_id:
                raise HTTPException(status_code=500, detail="Failed to create version")
            
            logger.info(f"Vita version created: {version_id}")
            
            return VitaVersionResponse(
                version_id=version_id,
                version_name=request.version_name,
                status='created'
            )
        
        # 降級：模擬創建
        logger.warning("Vita version creation method not available, using simulated response")
        return VitaVersionResponse(
            version_id=1,
            version_name=request.version_name,
            status='simulated'
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vita version creation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/vita/version/{version_id}/activate",
    dependencies=[Depends(get_current_user)]
)
async def activate_vita_version(
    version_id: int,
    orc: Orchestrator = Depends(get_orchestrator)
):
    """啟用 Vita 版本"""
    try:
        if version_id < 1:
            raise HTTPException(status_code=400, detail="Invalid version_id")
        
        if hasattr(orc, 'activate_vita_version') and callable(getattr(orc, 'activate_vita_version')):
            result = orc.activate_vita_version(version_id)
            if not result:
                raise HTTPException(status_code=500, detail="Failed to activate version")
        
        logger.info(f"Vita version activated: {version_id}")
        
        return {
            'version_id': version_id,
            'status': 'activated'
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vita version activation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 【健康檢查端點】
# ==========================================

@router.get(
    "/health",
    response_model=HealthResponse
)
async def health_check(
    orc: Orchestrator = Depends(get_orchestrator)
):
    """基礎健康檢查"""
    try:
        return HealthResponse(
            status="online",
            services={},
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/health/detailed",
    response_model=HealthDetailedResponse,
    dependencies=[Depends(get_current_user)]
)
async def health_detailed(
    orc: Orchestrator = Depends(get_orchestrator)
):
    """詳細健康檢查"""
    try:
        services = {}
        if hasattr(orc, 'health_check') and callable(getattr(orc, 'health_check')):
            services = orc.health_check()
        
        if not isinstance(services, dict):
            services = {"status": "ok"}
        
        return HealthDetailedResponse(
            status='online',
            services=services,
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        logger.error(f"Detailed health check error: {e}", exc_info=True)
        return HealthDetailedResponse(
            status='error',
            services={},
            timestamp=datetime.now().isoformat(),
            error=str(e)
        )


# ==========================================
# 【管理員清理端點】
# ==========================================

@router.post(
    "/cleanup/sessions",
    dependencies=[Depends(get_current_user)]
)
async def cleanup_sessions(
    current_user: dict = Depends(get_current_user),
    orc: Orchestrator = Depends(get_orchestrator)
):
    """清理過期會話（需要管理員權限）"""
    try:
        if current_user.get('role') != 'admin':
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        count = 0
        if hasattr(orc, 'cleanup_old_sessions') and callable(getattr(orc, 'cleanup_old_sessions')):
            count = orc.cleanup_old_sessions()
        
        logger.info(f"Sessions cleanup completed: {count} sessions removed")
        
        return {
            'cleaned': count,
            'timestamp': datetime.now().isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sessions cleanup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/cleanup/database",
    dependencies=[Depends(get_current_user)]
)
async def cleanup_database(
    days_old: int = Query(default=90, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    orc: Orchestrator = Depends(get_orchestrator)
):
    """清理舊數據（需要管理員權限）"""
    try:
        if current_user.get('role') != 'admin':
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        count = 0
        if hasattr(orc, 'cleanup_database') and callable(getattr(orc, 'cleanup_database')):
            count = orc.cleanup_database(days_old)
        
        logger.info(f"Database cleanup completed: {count} records removed (older than {days_old} days)")
        
        return {
            'deleted': count,
            'days_old': days_old,
            'timestamp': datetime.now().isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database cleanup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))