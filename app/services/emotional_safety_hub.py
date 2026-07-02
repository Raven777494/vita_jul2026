# app/services/emotional_safety_hub.py
# 情緒安全中樞 – 核心業務邏輯整合
# 
# 職責：
# 1. 協調所有子系統（LLM、風險評估、會話管理）
# 2. 實現臨床陪伴邏輯（Walker Score 計算）
# 3. 管理風險升級流程
# 4. 審計日誌記錄

import json
import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
import asyncio

from app.config import config
from app.logger import (
    get_app_logger, 
    get_private_logger, 
    get_critical_logger,
    log_session_event,
    log_risk_escalation
)
from app.services.session_manager import SessionManager
from app.utils.audit_logger import audit_log
from app.utils.error_handler import error_handler, ErrorSeverity, LLMTimeoutException
from app.metrics.crisis_metrics import record_crisis_interception_outcome

app_logger = get_app_logger('emotional_hub')
session_logger = get_private_logger('session_events')
critical_logger = get_critical_logger('critical_events')

# ============ 數據結構 ============

@dataclass
class RiskAssessment:
    """風險評估結果"""
    risk_level: int  # 1-5
    suicidal_indicators: int  # 檢測到的自殺傾向指標數
    self_harm_indicators: int  # 自傷指標數
    hopelessness_indicators: int  # 絕望感指標數
    isolation_indicators: int  # 孤立感指標數
    crisis_keywords: List[str]  # 檢測到的危機關鍵詞
    confidence: float  # 評估信心（0.0-1.0）
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

@dataclass
class WalkerScore:
    """陪伴分數評估結果"""
    overall_score: float  # 0.0-1.0
    empathy_score: float
    presence_score: float  # 「我在這裡」的表現
    safety_messaging_score: float  # 安全信息傳遞
    active_listening_score: float  # 主動傾聽
    
    # 診斷信息
    needs_improvement_areas: List[str]
    strengths: List[str]
    
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

@dataclass
class SafetyResponse:
    """安全回應結果"""
    response_text: str
    model_used: str
    response_type: str  # empathy/support/directive/safety_alert
    is_safe: bool  # 內容檢查通過
    confidence: float  # 0.0-1.0
    processing_time_ms: float
    fallback_used: bool = False
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

# ============ 主中樞類 ============

class EmotionalSafetyHub:
    """
    情緒安全中樞 – 核心業務邏輯驅動
    
    工作流程：
    1. 接收用戶輸入
    2. 風險評估（使用 EmoBLOOM）
    3. 生成陪伴回應（使用 Main-LLM）
    4. 計算 Walker Score（陪伴質量）
    5. 決定是否升級人工干預
    6. 記錄審計日誌並持久化
    """
    
    def __init__(
        self,
        session_manager: SessionManager,
        llm_service=None,
        risk_assessor=None
    ):
        """
        初始化中樞
        
        Args:
            session_manager: 會話管理器
            llm_service: LLM 服務（注入）
            risk_assessor: 風險評估服務（注入）
        """
        self.session_mgr = session_manager
        self.llm = llm_service
        self.risk_assessor = risk_assessor
        
        # 風險級別定義
        self.risk_thresholds = {
            1: {'min': 0, 'max': 10, 'label': '低風險'},
            2: {'min': 11, 'max': 25, 'label': '輕度風險'},
            3: {'min': 26, 'max': 50, 'label': '中度風險'},
            4: {'min': 51, 'max': 75, 'label': '高風險'},
            5: {'min': 76, 'max': 100, 'label': '極高風險 - 立即升級'}
        }
        
        app_logger.info("[HUB INIT] 情緒安全中樞已初始化")
    
    async def process_user_input(
        self,
        user_id: str,
        conversation_id: str,
        user_input: str,
        session_state: Dict = None
    ) -> Dict:
        """
        核心處理流程 - 完整的用戶輸入到回應管道
        
        Args:
            user_id: 用戶 ID
            conversation_id: 對話 ID
            user_input: 用戶輸入文本
            session_state: 現有會話狀態（若無則創建）
        
        Returns:
            Dict: {
                'success': bool,
                'response': str,
                'session_id': str,
                'risk_level': int,
                'walker_score': float,
                'escalated': bool
            }
        """
        import time
        start_time = time.time()
        
        try:
            # 1. 載入或創建會話
            if session_state is None:
                session_state = self.session_mgr.create_session(
                    user_id,
                    conversation_id
                )
            
            session_id = session_state['session_id']
            turn_count = session_state.get('turn_count', 0) + 1
            
            app_logger.info(
                f"[PROCESS] Turn {turn_count}: "
                f"user_id={user_id}, session_id={session_id}"
            )
            
            # 2. 風險評估（非同步調用，帶超時）
            risk_assessment = await self._assess_risk(
                user_input,
                session_state,
                user_id,
                session_id,
                turn_count
            )
            
            app_logger.debug(f"[RISK] Level={risk_assessment.risk_level}")
            
            # 3. 記錄審計日誌（風險評估）
            audit_log.log_risk_assessment(
                user_id,
                session_id,
                conversation_id,
                risk_assessment.risk_level,
                0.5,  # 臨時 walker_score
                risk_assessment.crisis_keywords,
                turn_count
            )
            
            # 4. 檢查是否需要立即升級（極高風險）
            if risk_assessment.risk_level >= 5:
                response = await self._handle_critical_escalation(
                    user_id,
                    session_id,
                    conversation_id,
                    risk_assessment,
                    turn_count
                )
                
                session_state['is_escalated'] = True
                session_state['escalation_history'].append({
                    'turn': turn_count,
                    'reason': 'critical_risk_level_5',
                    'timestamp': datetime.now().isoformat()
                })
                
                self.session_mgr.save_session(
                    user_id,
                    conversation_id,
                    session_state,
                    persist_to_db=True
                )
                
                processing_time = (time.time() - start_time) * 1000

                record_crisis_interception_outcome(
                    risk_assessment=risk_assessment,
                    response_text=response,
                    escalated=True,
                    fallback_used=False,
                    success=True,
                    user_id=user_id,
                    session_id=session_id,
                )

                return {
                    'success': True,
                    'response': response,
                    'session_id': session_id,
                    'risk_level': risk_assessment.risk_level,
                    'walker_score': 0.0,
                    'escalated': True,
                    'escalation_reason': 'critical_risk',
                    'processing_time_ms': processing_time
                }
            
            # 5. 生成陪伴回應（使用 Main-LLM + 安全過濾）
            safety_response = await self._generate_safe_response(
                user_input,
                session_state,
                risk_assessment,
                user_id,
                session_id,
                turn_count
            )
            
            app_logger.debug(f"[RESPONSE] Generated: {len(safety_response.response_text)} chars")
            
            # 6. 計算 Walker Score（陪伴質量評估）
            walker_score = self._calculate_walker_score(
                safety_response,
                session_state,
                risk_assessment
            )
            
            app_logger.debug(f"[WALKER] Score={walker_score.overall_score}")
            
            # 7. 檢查是否升級（高風險或陪伴不足）
            should_escalate = self._should_escalate(
                risk_assessment,
                walker_score,
                session_state
            )
            
            # 8. 更新會話狀態
            session_state['turn_count'] = turn_count
            session_state['risk_level'] = risk_assessment.risk_level
            session_state['walker_score'] = walker_score.overall_score
            session_state['messages'].append({
                'role': 'user',
                'content': user_input,
                'timestamp': datetime.now().isoformat()
            })
            session_state['messages'].append({
                'role': 'assistant',
                'content': safety_response.response_text,
                'timestamp': datetime.now().isoformat()
            })
            
            # 9. 決定持久化策略
            should_persist = self.session_mgr.should_persist_to_db(session_state)
            
            # 保存會話
            self.session_mgr.save_session(
                user_id,
                conversation_id,
                session_state,
                persist_to_db=should_persist
            )
            
            # 10. 處理升級（若需要）
            if should_escalate:
                await self._handle_escalation(
                    user_id,
                    session_id,
                    conversation_id,
                    risk_assessment,
                    walker_score,
                    turn_count
                )
                
                session_state['is_escalated'] = True
                session_state['escalation_history'].append({
                    'turn': turn_count,
                    'reason': 'high_risk_or_low_walker_score',
                    'timestamp': datetime.now().isoformat(),
                    'risk_level': risk_assessment.risk_level,
                    'walker_score': walker_score.overall_score
                })
                
                self.session_mgr.save_session(
                    user_id,
                    conversation_id,
                    session_state,
                    persist_to_db=True
                )
            
            # 11. 記錄審計日誌（回應）
            audit_log.log_system_response(
                user_id,
                session_id,
                conversation_id,
                safety_response.response_text,
                turn_count,
                safety_response.model_used,
                safety_response.confidence
            )
            
            processing_time = (time.time() - start_time) * 1000

            record_crisis_interception_outcome(
                risk_assessment=risk_assessment,
                response_text=safety_response.response_text,
                escalated=should_escalate,
                fallback_used=safety_response.fallback_used,
                success=True,
                user_id=user_id,
                session_id=session_id,
            )

            # 12. 返回結果
            return {
                'success': True,
                'response': safety_response.response_text,
                'session_id': session_id,
                'risk_level': risk_assessment.risk_level,
                'walker_score': walker_score.overall_score,
                'escalated': should_escalate,
                'walker_feedback': walker_score.needs_improvement_areas,
                'processing_time_ms': processing_time
            }
        
        except Exception as e:
            app_logger.error(f"[PROCESS ERROR] {str(e)}", exc_info=True)
            
            # 發生錯誤時的安全降級
            fallback_response = error_handler.get_safe_response_for_risk_level(
                session_state.get('risk_level', 1) if session_state else 1
            )

            if 'risk_assessment' in locals() and risk_assessment is not None:
                record_crisis_interception_outcome(
                    risk_assessment=risk_assessment,
                    response_text=fallback_response,
                    escalated=False,
                    fallback_used=True,
                    success=False,
                    user_id=user_id,
                    session_id=session_state.get('session_id', 'unknown') if session_state else 'unknown',
                )
            
            audit_log.log_system_error(
                user_id,
                session_state.get('session_id', 'unknown') if session_state else 'unknown',
                'process_error',
                str(e),
                turn_number=session_state.get('turn_count', 0) if session_state else 0
            )
            
            return {
                'success': False,
                'response': fallback_response,
                'error': str(e),
                'escalated': False
            }
    
    # ============ 風險評估 ============
    
    async def _assess_risk(
        self,
        user_input: str,
        session_state: Dict,
        user_id: str,
        session_id: str,
        turn_count: int
    ) -> RiskAssessment:
        """
        評估輸入中的風險級別
        
        方法：
        1. 使用 EmoBLOOM 模型檢測危機指標
        2. 關鍵詞匹配
        3. 加權風險評分
        
        Returns:
            RiskAssessment: 風險評估結果
        """
        try:
            # 調用風險評估服務（若有）或使用啟發式方法
            if self.risk_assessor:
                assessment = await asyncio.wait_for(
                    self.risk_assessor.assess(user_input),
                    timeout=config.LLM_TIMEOUTS.get('emobloom_llm', 2.0)
                )
            else:
                # 備選：簡單啟發式風險評估
                assessment = self._heuristic_risk_assessment(user_input)
            
            return assessment
        
        except asyncio.TimeoutError:
            app_logger.warning(f"[RISK TIMEOUT] EmoBLOOM timeout for turn {turn_count}")
            
            # 超時時使用保守估計
            return self._conservative_risk_assessment(user_input)
        
        except Exception as e:
            app_logger.error(f"[RISK ERROR] {str(e)}")
            
            # 錯誤時返回中度風險（保守估計）
            return RiskAssessment(
                risk_level=3,
                suicidal_indicators=0,
                self_harm_indicators=0,
                hopelessness_indicators=0,
                isolation_indicators=0,
                crisis_keywords=[],
                confidence=0.3
            )
    
    def _heuristic_risk_assessment(self, user_input: str) -> RiskAssessment:
        """
        簡單啟發式風險評估（無 ML 模型時使用）
        
        關鍵詞匹配方法
        """
        # 定義風險關鍵詞
        crisis_keywords = {
            'suicidal': [
                '自殺', '死亡', '結束生命', '想死', '死咗好', '想唔駛活'
            ],
            'self_harm': [
                '自傷', '割', '傷自己', '砍自己', '痛自己'
            ],
            'hopelessness': [
                '無希望', '絕望', '冇辦法', '唔掂', '完咗'
            ],
            'isolation': [
                '孤單', '孤立', '冇人', '冇朋友', '被拋棄'
            ]
        }
        
        user_input_lower = user_input.lower()
        detected_keywords = []
        scores = {'suicidal': 0, 'self_harm': 0, 'hopelessness': 0, 'isolation': 0}
        
        for category, keywords in crisis_keywords.items():
            for keyword in keywords:
                if keyword in user_input_lower:
                    detected_keywords.append(keyword)
                    scores[category] += 1
        
        # 計算總風險分數
        total_score = sum(scores.values()) * 25
        
        # 映射到風險級別
        if total_score >= 76:
            risk_level = 5
        elif total_score >= 51:
            risk_level = 4
        elif total_score >= 26:
            risk_level = 3
        elif total_score >= 11:
            risk_level = 2
        else:
            risk_level = 1
        
        return RiskAssessment(
            risk_level=risk_level,
            suicidal_indicators=scores['suicidal'],
            self_harm_indicators=scores['self_harm'],
            hopelessness_indicators=scores['hopelessness'],
            isolation_indicators=scores['isolation'],
            crisis_keywords=detected_keywords,
            confidence=0.6
        )
    
    def _conservative_risk_assessment(self, user_input: str) -> RiskAssessment:
        """
        保守估計（超時或錯誤時使用）
        
        策略：若無法確定，假設中度風險
        """
        # 至少進行基本的關鍵詞掃描
        has_crisis_keywords = any(
            keyword in user_input.lower()
            for keyword in ['死', '自殺', '傷', '絕望', '孤單']
        )
        
        risk_level = 3 if has_crisis_keywords else 2
        
        return RiskAssessment(
            risk_level=risk_level,
            suicidal_indicators=0,
            self_harm_indicators=0,
            hopelessness_indicators=0,
            isolation_indicators=0,
            crisis_keywords=[],
            confidence=0.3
        )
    
    # ============ 安全回應生成 ============
    
    async def _generate_safe_response(
        self,
        user_input: str,
        session_state: Dict,
        risk_assessment: RiskAssessment,
        user_id: str,
        session_id: str,
        turn_count: int
    ) -> SafetyResponse:
        """
        生成陪伴回應（使用 Main-LLM，帶安全檢查）
        
        策略：
        1. 構建上下文感知的提示
        2. 調用 Main-LLM 模型
        3. 安全性檢查
        4. 失敗時使用預設回應
        
        Args:
            user_input: 用戶輸入
            session_state: 會話狀態
            risk_assessment: 風險評估結果
            user_id: 用戶 ID
            session_id: 會話 ID
            turn_count: 對話輪數
        
        Returns:
            SafetyResponse: 安全回應
        """
        import time
        start_time = time.time()
        
        try:
            # 構建提示
            prompt = self._build_companion_prompt(
                user_input,
                session_state,
                risk_assessment
            )
            
            # 調用 LLM（帶超時和重試）
            if self.llm:
                try:
                    response_text = await asyncio.wait_for(
                        self.llm.generate(
                            prompt,
                            max_tokens=1024,
                            temperature=0.7
                        ),
                        timeout=config.LLM_TIMEOUTS.get('main_llm', 3.0)
                    )
                except asyncio.TimeoutError:
                    app_logger.warning(f"[LLM TIMEOUT] Main-LLM timeout for turn {turn_count}")
                    
                    # 超時時使用預設回應
                    response_text = config.DEFAULT_SAFE_REPLIES.get(
                        'timeout',
                        '我正在思考你講嘅話。請等一陣。'
                    )
                    
                    return SafetyResponse(
                        response_text=response_text,
                        model_used='fallback_timeout',
                        response_type='system',
                        is_safe=True,
                        confidence=0.5,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        fallback_used=True
                    )
            else:
                # 無 LLM 服務時使用預設回應
                response_text = config.DEFAULT_SAFE_REPLIES.get(
                    'low_risk' if risk_assessment.risk_level <= 2 else 'medium_risk',
                    '寶貝，我喺度。'
                )
                
                return SafetyResponse(
                    response_text=response_text,
                    model_used='fallback_no_llm',
                    response_type='fallback',
                    is_safe=True,
                    confidence=0.5,
                    processing_time_ms=(time.time() - start_time) * 1000,
                    fallback_used=True
                )
            
            # 安全性檢查
            is_safe, safety_issues = self._check_response_safety(response_text)
            
            if not is_safe:
                app_logger.warning(
                    f"[UNSAFE RESPONSE] Issues: {safety_issues}. "
                    f"Using fallback."
                )
                
                # 使用根據風險級別的預設回應
                response_text = error_handler.get_safe_response_for_risk_level(
                    risk_assessment.risk_level
                )
                
                return SafetyResponse(
                    response_text=response_text,
                    model_used='main_llm',
                    response_type='fallback',
                    is_safe=True,
                    confidence=0.5,
                    processing_time_ms=(time.time() - start_time) * 1000,
                    fallback_used=True
                )
            
            processing_time = (time.time() - start_time) * 1000
            
            return SafetyResponse(
                response_text=response_text,
                model_used='main_llm',
                response_type=self._classify_response_type(response_text),
                is_safe=True,
                confidence=0.8,
                processing_time_ms=processing_time,
                fallback_used=False
            )
        
        except Exception as e:
            app_logger.error(f"[RESPONSE GENERATION ERROR] {str(e)}")
            
            # 最後的安全降級
            fallback_text = error_handler.get_safe_response_for_risk_level(
                risk_assessment.risk_level
            )
            
            return SafetyResponse(
                response_text=fallback_text,
                model_used='fallback_error',
                response_type='emergency_fallback',
                is_safe=True,
                confidence=0.3,
                processing_time_ms=(time.time() - start_time) * 1000,
                fallback_used=True
            )
    
    def _build_companion_prompt(
        self,
        user_input: str,
        session_state: Dict,
        risk_assessment: RiskAssessment
    ) -> str:
        """
        構建上下文感知的提示
        
        策略：
        1. 包含同行者角色定義（非醫療分流）
        2. 風險級別提示
        3. 聊天歷史（最後 3 輪）
        4. 明確的陪伴指引（hold / ground / recall / gentle connection）
        """
        role_prompt = (
            "你是一個心理生命同行者（不是醫療分流或急診機器人）。\n"
            "使用粵語，優先：承接情緒、陪伴在場、溫和 grounding。\n"
            "禁止在用戶可見回應中出現：熱線電話、急診/住院/約束、用藥指令、"
            "病患標籤、或告知用戶已被通報/通知他人。\n"
            "你應該：\n"
            "1. 首先確認和驗證用戶的感受\n"
            "2. 用『我喺度』『我聽到』等現身措辭\n"
            "3. 危機時以慢節奏陪伴，可邀請用戶回想曾幫助過自己的小事或信任的人\n"
            "4. 避免命令式醫療或機構轉介\n"
        )
        
        risk_prompt = ""
        if risk_assessment.risk_level >= 4:
            risk_prompt = (
                "用戶目前處於高度心理痛苦。請以同行者語言回應，"
                "不要提供機構轉介、熱線或就醫指令。\n"
            )
        elif risk_assessment.risk_level >= 2:
            risk_prompt = (
                "用戶表現出中等風險跡象。加強陪伴和同理心回應。\n"
            )
        
        # 最近聊天歷史
        messages = session_state.get('messages', [])
        conversation_context = ""
        
        if messages:
            recent_messages = messages[-6:]  # 最後 3 輪
            conversation_context = "對話背景：\n"
            for msg in recent_messages:
                role = "用戶" if msg['role'] == 'user' else "你"
                conversation_context += f"{role}: {msg['content']}\n"
        
        # 完整提示
        complete_prompt = (
            f"{role_prompt}\n"
            f"{risk_prompt}\n"
            f"{conversation_context}\n"
            f"用戶現在說：{user_input}\n\n"
            f"請給予一個溫暖、同理、專業的陪伴回應（最多 50 字）："
        )
        
        return complete_prompt
    
    def _check_response_safety(self, response_text: str) -> Tuple[bool, List[str]]:
        """
        檢查回應是否符合安全標準
        
        Returns:
            Tuple[bool, List[str]]: (is_safe, issues_list)
        """
        from app.clinical.companion_language_policy import validate_user_facing_text

        issues: List[str] = []

        ok, policy_issues = validate_user_facing_text(response_text)
        if not ok:
            issues.extend(policy_issues)
            return False, issues

        # Assistant must not instruct self-harm or echo dangerous directives
        dangerous_patterns = [
            "你應該死",
            "去自殺",
            "割腕",
        ]

        for pattern in dangerous_patterns:
            if pattern in response_text:
                issues.append(f"dangerous_pattern:{pattern}")

        if len(response_text) > 500:
            issues.append("response_too_long")

        return len(issues) == 0, issues
    
    def _classify_response_type(self, response_text: str) -> str:
        """分類回應類型"""
        lower_text = response_text.lower()
        
        if any(kw in lower_text for kw in ['聽到', '理解', '明白', '感受']):
            return 'empathy'
        elif any(kw in lower_text for kw in ['幫忙', '支持', '陪你']):
            return 'support'
        elif any(kw in lower_text for kw in ['試下', '可以', '建議']):
            return 'directive'
        elif any(kw in lower_text for kw in ['一起', '這一刻', '慢慢', '安穩', '呼吸']):
            return 'companion_grounding'
        else:
            return 'other'
    
    # ============ Walker Score 計算 ============
    
    def _calculate_walker_score(
        self,
        safety_response: SafetyResponse,
        session_state: Dict,
        risk_assessment: RiskAssessment
    ) -> WalkerScore:
        """
        計算陪伴質量分數（Walker Score）
        
        維度：
        1. Empathy Score（同理心）：回應中同理詞彙的比例
        2. Presence Score（在場）：「我在這裡」的直接表達
        3. Safety Messaging Score：安全信息的傳遞
        4. Active Listening Score：主動傾聽的表現
        
        總分公式：
        walker_score = 0.4*empathy + 0.3*presence + 0.2*safety + 0.1*listening
        
        Args:
            safety_response: 生成的回應
            session_state: 會話狀態
            risk_assessment: 風險評估
        
        Returns:
            WalkerScore: 陪伴分數
        """
        response_text = safety_response.response_text
        
        # 計算各個維度
        empathy_score = self._calculate_empathy_score(response_text)
        presence_score = self._calculate_presence_score(response_text)
        safety_messaging_score = self._calculate_safety_messaging_score(response_text)
        active_listening_score = self._calculate_active_listening_score(
            response_text,
            session_state
        )
        
        # 加權平均
        overall_score = (
            0.4 * empathy_score +
            0.3 * presence_score +
            0.2 * safety_messaging_score +
            0.1 * active_listening_score
        )
        
        # 高風險情況下提高標準
        if risk_assessment.risk_level >= 4:
            # 在危機情況下，期望更高的陪伴質量
            overall_score = max(0, overall_score - config.WALKER_SCORE_HIGH_RISK_BOOST)
        
        # 診斷信息
        needs_improvement_areas = []
        if empathy_score < 0.6:
            needs_improvement_areas.append('increase_empathy_expressions')
        if presence_score < 0.5:
            needs_improvement_areas.append('strengthen_presence_messaging')
        if safety_messaging_score < 0.4:
            needs_improvement_areas.append('add_safety_resources')
        
        strengths = []
        if empathy_score >= 0.8:
            strengths.append('strong_empathy')
        if presence_score >= 0.8:
            strengths.append('clear_presence')
        if overall_score >= 0.7:
            strengths.append('overall_high_quality')
        
        return WalkerScore(
            overall_score=min(1.0, overall_score),  # 限制在 0-1
            empathy_score=empathy_score,
            presence_score=presence_score,
            safety_messaging_score=safety_messaging_score,
            active_listening_score=active_listening_score,
            needs_improvement_areas=needs_improvement_areas,
            strengths=strengths
        )
    
    def _calculate_empathy_score(self, response_text: str) -> float:
        """計算同理心分數"""
        empathy_keywords = [
            '聽到', '明白', '理解', '感受', '知道', '懂得',
            '真係', '確實', '難得', '痛', '辛苦'
        ]
        
        matches = sum(1 for kw in empathy_keywords if kw in response_text)
        max_possible = 3  # 預期最多 3 個同理詞彙
        
        return min(1.0, matches / max_possible)
    
    def _calculate_presence_score(self, response_text: str) -> float:
        """計算在場感分數"""
        presence_keywords = [
            '我喺度', '我在這裡', '我陪著你', '陪你', '喺度'
        ]
        
        has_presence = any(kw in response_text for kw in presence_keywords)
        
        return 0.8 if has_presence else 0.3
    
    def _calculate_safety_messaging_score(self, response_text: str) -> float:
        """計算安全信息分數"""
        safety_keywords = [
            '陪', '一起', '這一刻', '安穩', '慢慢', '呼吸',
            '聽到', '我喺度', '我在', '不用一個人', '安全',
        ]
        
        matches = sum(1 for kw in safety_keywords if kw in response_text)
        
        return min(1.0, matches / 2)  # 預期 2 個安全詞彙
    
    def _calculate_active_listening_score(
        self,
        response_text: str,
        session_state: Dict
    ) -> float:
        """計算主動傾聽分數"""
        # 檢查回應是否引用或回應用戶提到的具體內容
        messages = session_state.get('messages', [])
        
        if len(messages) >= 2:
            last_user_message = messages[-2].get('content', '')
            
            # 簡單啟發式：檢查是否包含用戶提到的詞彙
            user_words = set(last_user_message.split())
            response_words = set(response_text.split())
            
            overlap = len(user_words & response_words) / max(len(user_words), 1)
            
            return min(1.0, overlap * 2)  # 縮放到 0-1
        
        return 0.5  # 沒有足夠的上下文
    
    # ============ 升級邏輯 ============
    
    def _should_escalate(
        self,
        risk_assessment: RiskAssessment,
        walker_score: WalkerScore,
        session_state: Dict
    ) -> bool:
        """
        決定是否升級人工干預
        
        條件：
        1. risk_level >= 4（高風險）
        2. walker_score < 0.3（陪伴不足）
        3. 多輪高風險（保持升級）
        
        Args:
            risk_assessment: 風險評估
            walker_score: 陪伴分數
            session_state: 會話狀態
        
        Returns:
            bool: 是否應該升級
        """
        # 條件 1：高風險
        if risk_assessment.risk_level >= config.RISK_ESCALATION_THRESHOLD:
            return True
        
        # 條件 2：陪伴不足
        if walker_score.overall_score < config.WALKER_SCORE_THRESHOLD:
            return True
        
        # 條件 3：持續高風險
        recent_risk_levels = [
            msg.get('risk_level', 1)
            for msg in session_state.get('messages', [])[-6:]
            if 'risk_level' in msg
        ]
        
        if len(recent_risk_levels) >= 3:
            avg_recent_risk = sum(recent_risk_levels) / len(recent_risk_levels)
            if avg_recent_risk >= 3.5:
                return True
        
        return False
    
    async def _handle_escalation(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str,
        risk_assessment: RiskAssessment,
        walker_score: WalkerScore,
        turn_count: int
    ):
        """
        處理升級流程
        
        步驟：
        1. 通知臨床團隊（Slack/Email）
        2. 暫停 AI 回應
        3. 記錄升級事件
        4. 設置升級標誌
        """
        app_logger.critical(
            f"[ESCALATION] user_id={user_id}, session_id={session_id}, "
            f"reason=risk_level_{risk_assessment.risk_level}_or_walker_{walker_score.overall_score}"
        )
        
        # 記錄升級事件
        log_risk_escalation(
            critical_logger,
            user_id,
            session_id,
            risk_assessment.risk_level,
            f"risk_level={risk_assessment.risk_level}, walker_score={walker_score.overall_score}",
            'clinical_team'
        )
        
        # 發送通知（模擬）
        await self._send_escalation_notifications(
            user_id,
            session_id,
            risk_assessment.risk_level,
            walker_score.overall_score
        )
    
    async def _handle_critical_escalation(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str,
        risk_assessment: RiskAssessment,
        turn_count: int
    ) -> str:
        """
        處理極高風險（level 5）的緊急升級
        
        返回：立即的安全回應 + 資源信息
        """
        critical_logger.critical(
            f"[CRITICAL ESCALATION] user_id={user_id}, session_id={session_id}, "
            f"risk_level=5 (CRITICAL)"
        )
        
        # 立即通知
        await self._send_escalation_notifications(
            user_id,
            session_id,
            risk_assessment.risk_level,
            0.0
        )
        
        # 返回引導式同行者回應（不暴露機構轉介或內部升級細節）
        return config.DEFAULT_SAFE_REPLIES['critical']
    
    async def _send_escalation_notifications(
        self,
        user_id: str,
        session_id: str,
        risk_level: int,
        walker_score: float
    ):
        """
        發送升級通知給臨床團隊
        
        模擬實現（實際應集成 Slack/Email）
        """
        notification = {
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'session_id': session_id,
            'risk_level': risk_level,
            'walker_score': walker_score,
            'action': 'ESCALATION_REQUIRED'
        }
        
        app_logger.warning(f"[NOTIFICATION] {notification}")
        
        # 實際實現應該在這裡調用 Slack API、Email API 等
        # await slack_service.send_escalation_alert(notification)
        # await email_service.send_escalation_alert(notification)
    
    # ============ 工具方法 ============
    
    def get_session_summary(
        self,
        user_id: str,
        conversation_id: str
    ) -> Optional[Dict]:
        """獲取會話摘要（臨床人員查看）"""
        session = self.session_mgr.load_session(user_id, conversation_id)
        
        if not session:
            return None
        
        return {
            'session_id': session['session_id'],
            'duration_turns': session['turn_count'],
            'peak_risk_level': max(
                [1] + [msg.get('risk_level', 1) for msg in session.get('messages', [])]
            ),
            'average_walker_score': session['walker_score'],
            'is_escalated': session.get('is_escalated', False),
            'escalation_history': session.get('escalation_history', []),
            'last_updated': session.get('last_updated_at', 'unknown')
        }
    
    def get_all_high_risk_sessions(self) -> List[Dict]:
        """獲取所有活躍高風險會話"""
        high_risk = self.session_mgr.get_active_high_risk_sessions()
        
        summaries = []
        for session in high_risk:
            summaries.append({
                'session_id': session['session_id'],
                'user_id_masked': f"{session['user_id'][:3]}***",
                'risk_level': session['risk_level'],
                'walker_score': session['walker_score'],
                'turn_count': session['turn_count'],
                'is_escalated': session.get('is_escalated', False)
            })
        
        return summaries