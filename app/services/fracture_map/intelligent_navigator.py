# app/services/fracture_map/intelligent_navigator.py
"""
智慧導航層（完全實裝 - Phase 2.1）

【核心設計】
- 雙軌系統：快思（Logic-LLM / Distil-NPC-gemma）+ 慢思（Main-LLM / Soul）
- 實時危機偵測
- 親密度影響回應
- 完整的日誌和可追蹤性
- 與 orchestrator.py v5.5 對齐
"""

import asyncio
import logging
import json
import time
from typing import Dict, Tuple, Optional, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import uuid

logger = logging.getLogger('vita.intelligent_navigator')


@dataclass
class FractureDetection:
    """裂痕偵測結果"""
    fracture_type: str
    trigger_keyword: str
    severity_level: int
    priority: float
    confidence: float
    context_tags: List[str] = field(default_factory=list)
    intervention_prompts: List[str] = field(default_factory=list)
    clinical_guidelines: str = ""
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class NavigationDecision:
    """導航決策"""
    decision_id: str
    user_id: str
    detected_fractures: List[FractureDetection] = field(default_factory=list)
    fast_track_result: Optional[str] = None
    slow_track_result: Optional[str] = None
    final_response: str = ""
    decision_type: str = "normal"
    intimacy_level: float = 0.5
    fast_track_time: float = 0.0
    slow_track_time: float = 0.0
    total_time: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)


class IntelligentNavigator:
    """智慧導航層（完全實裝 v2.1）"""
    
    def __init__(self, 
                 llm_service: Optional[Any] = None,
                 db_manager: Optional[Any] = None,
                 db_service: Optional[Any] = None,
                 fracture_manager: Optional[Any] = None,
                 config: Optional[Dict] = None):
        
        logger.info("[NAVIGATOR] Initializing IntelligentNavigator v2.1...")
        
        # 導入 LLM 服務
        if llm_service is None:
            try:
                from app.services.llm_service import llm_service as default_llm
                llm_service = default_llm
            except Exception as e:
                logger.warning(f"[NAVIGATOR] Failed to import LLM service: {e}")
                llm_service = None
        
        # 導入 DB 管理器
        if db_manager is None:
            try:
                from app.services.db_manager import db_manager as default_db
                db_manager = default_db
            except Exception as e:
                logger.warning(f"[NAVIGATOR] Failed to import DB manager: {e}")
                db_manager = None
        
        self.llm = llm_service
        self.db_manager = db_manager
        self.db_service = db_service
        self.fracture_manager = fracture_manager
        self.config = config or {}
        
        self.fracture_maps = self._load_fracture_maps()
        self.safe_phrases = self._load_safe_phrases()
        self.grounding_techniques = self._load_grounding_techniques()
        
        self.decisions_made = 0
        self.safety_mode_triggered = 0
        
        logger.info(f"[NAVIGATOR] Initialized with {len(self.fracture_maps)} fracture maps | Version: 2.1")

    def _load_fracture_maps(self) -> Dict[str, Dict]:
        """加載裂痕地圖"""
        try:
            if self.db_service:
                raw_maps = self.db_service.get_fracture_map()
                if raw_maps:
                    return raw_maps
            
            if self.db_manager and hasattr(self.db_manager, 'execute_query'):
                results = self.db_manager.execute_query(
                    "SELECT fracture_name, description, keywords, risk_indicators, intervention_prompts, clinical_guidelines, severity_level FROM fracture_maps"
                )
                fracture_maps = {}
                for row in results:
                    fracture_maps[row.get('fracture_name', '')] = {
                        'description': row.get('description', ''),
                        'keywords': row.get('keywords', []),
                        'risk_indicators': row.get('risk_indicators', {}),
                        'intervention_prompts': row.get('intervention_prompts', []),
                        'clinical_guidelines': row.get('clinical_guidelines', ''),
                        'severity_level': int(row.get('severity_level', 3))
                    }
                return fracture_maps
        except Exception as e:
            logger.error(f"[NAVIGATOR] Failed to load fracture maps: {e}")
        
        return {}

    def _load_safe_phrases(self) -> Dict[str, List[str]]:
        """加載安全用語"""
        return {
            'self_harm': [
                '我能感受到你的痛苦，但傷害自己不是唯一的出口。',
                '你值得被溫柔對待。'
            ],
            'suicidal_ideation': [
                '你現在的痛苦是真實的，但這不是永久的。',
                '世界會因為你的存在而有所不同。'
            ],
            'hopelessness': [
                '絕望的感受是可以理解的，但它不是永遠的。',
                '我們可以慢慢找到希望的破口。'
            ],
            'isolation': [
                '你不是孤獨的，我喺度。'
            ]
        }

    def _load_grounding_techniques(self) -> Dict[str, Dict]:
        """加載接地技巧"""
        return {
            '5-4-3-2-1': {
                'name': '五感接地法',
                'steps': [
                    '找 5 樣看到的東西',
                    '4 樣摸到的',
                    '3 樣聽到的',
                    '2 樣聞到的',
                    '1 樣嚐到的'
                ]
            }
        }

    async def navigate_async(self, 
                            user_id: str, 
                            user_input: str, 
                            session_history: Optional[List[Dict]] = None, 
                            intimacy: float = 0.5) -> Tuple[str, NavigationDecision]:
        """
        非同步導航決策 (完全返回 NavigationDecision)
        
        Returns:
            (response_text, NavigationDecision 對象)
        """
        start_time = time.time()
        decision_id = str(uuid.uuid4())[:8]
        
        logger.info(f"[NAV] {decision_id} Starting navigation for user {user_id}")
        
        try:
            detected_fractures = self.detect_fractures(user_id, user_input)
            decision = NavigationDecision(
                decision_id=decision_id,
                user_id=user_id,
                detected_fractures=detected_fractures,
                intimacy_level=intimacy
            )
            
            is_high_risk = any(f.severity_level >= 4 for f in detected_fractures)
            
            if is_high_risk:
                logger.warning(f"[NAV] {decision_id} FRACTURE DETECTED - High Risk")
                final_response, decision = await self._safety_mode(
                    user_id, user_input, detected_fractures, decision, intimacy
                )
                self.safety_mode_triggered += 1
            else:
                logger.debug(f"[NAV] {decision_id} Normal mode - calling LLM...")
                final_response, decision = await self._normal_mode(
                    user_id, user_input, session_history, decision, intimacy
                )
            
            decision.total_time = time.time() - start_time
            decision.final_response = final_response
            self.decisions_made += 1
            
            return final_response, decision
            
        except Exception as e:
            logger.error(f"[NAV] {decision_id} Error: {e}", exc_info=True)
            fallback = "對不起，我現在無法回應。請稍候再試。"
            decision = NavigationDecision(
                decision_id=decision_id,
                user_id=user_id,
                final_response=fallback,
                decision_type="error"
            )
            return fallback, decision

    def navigate(self, 
                user_id: str, 
                user_input: str, 
                session_state: Optional[Dict] = None, 
                intimacy: float = 0.5) -> Tuple[str, Dict]:
        """
        同步包裝器 (返回 Dict)
        
        Returns:
            (response_text, navigation_log_dict)
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            final_response, decision = loop.run_until_complete(
                self.navigate_async(
                    user_id,
                    user_input,
                    session_state.get('context_window', []) if session_state else [],
                    intimacy
                )
            )
            
            nav_log = {
                'final_decision': decision.decision_type,
                'decision_id': decision.decision_id,
                'detected_fractures': [
                    {
                        'keyword': f.trigger_keyword,
                        'severity': f.severity_level,
                        'confidence': f.confidence
                    }
                    for f in decision.detected_fractures
                ],
                'crisis_triggered': decision.decision_type == 'safety_mode',
                'track_used': 'fast' if decision.decision_type == 'safety_mode' else 'slow',
                'response': final_response,
                'intimacy_level': decision.intimacy_level,
                'total_time': decision.total_time
            }
            
            return final_response, nav_log
        
        except Exception as e:
            logger.error(f"[NAV SYNC] Error: {e}", exc_info=True)
            return "對不起，我現在無法回應。", {
                'final_decision': 'error',
                'track_used': 'error',
                'crisis_triggered': False,
                'error': str(e)
            }

    async def _safety_mode(self, 
                          user_id: str, 
                          user_input: str, 
                          detected_fractures: List[FractureDetection], 
                          decision: NavigationDecision, 
                          intimacy: float) -> Tuple[str, NavigationDecision]:
        """安全模式 - 高風險回應"""
        top_fracture = detected_fractures[0] if detected_fractures else None
        
        if not top_fracture:
            return self._get_safe_reply('fallback'), decision
        
        system_prompt = (
            f"用戶目前表達了強烈的【{top_fracture.fracture_type}】。"
            "請以溫柔、安撫的香港廣東話口語回應，先接住對方的情緒，絕對不要說教。"
        )
        
        start_time = time.time()
        try:
            if self.llm and hasattr(self.llm, 'generate_fast_response_async'):
                response = await self.llm.generate_fast_response_async(
                    prompt=user_input,
                    system_prompt=system_prompt,
                    max_tokens=200,
                    temperature=0.5
                )
                fast_response_text = response.content if hasattr(response, 'content') else str(response)
            else:
                fast_response_text = "我在這裡陪著你。"
            
            decision.fast_track_result = fast_response_text
            decision.fast_track_time = time.time() - start_time
            
            final_response = self._generate_safety_response(top_fracture, fast_response_text, intimacy)
            decision.decision_type = "safety_mode"
            
            return final_response, decision
            
        except Exception as e:
            logger.warning(f"[NAV] Safety mode generation failed: {e}")
            final_response = self._generate_safety_response(top_fracture, "我在這裡。", intimacy)
            decision.decision_type = "safety_mode"
            return final_response, decision

    async def _normal_mode(self, 
                          user_id: str, 
                          user_input: str, 
                          session_history: Optional[List[Dict]], 
                          decision: NavigationDecision, 
                          intimacy: float) -> Tuple[str, NavigationDecision]:
        """正常模式 - 常規回應"""
        system_prompt = (
            f"你係希兒。目前與用戶的親密度為 {intimacy:.1f}。"
            "請用自然、活潑的香港廣東話口語給予溫暖的回應。"
        )
        
        start_time = time.time()
        try:
            if self.llm and hasattr(self.llm, 'generate_fast_response_async'):
                response = await self.llm.generate_fast_response_async(
                    prompt=user_input,
                    system_prompt=system_prompt,
                    max_tokens=200,
                    temperature=0.7
                )
                slow_response_text = response.content if hasattr(response, 'content') else str(response)
            else:
                slow_response_text = "我喺度陪著你。"
            
            decision.slow_track_result = slow_response_text
            decision.slow_track_time = time.time() - start_time
            
            final_response = self._adjust_by_intimacy(slow_response_text, intimacy)
            decision.decision_type = "normal"
            
            return final_response, decision
            
        except Exception as e:
            logger.warning(f"[NAV] Normal mode generation failed: {e}")
            final_response = self._adjust_by_intimacy("我喺度陪著你。", intimacy)
            decision.decision_type = "normal"
            return final_response, decision

    def detect_fractures(self, user_id: str, user_input: str) -> List[FractureDetection]:
        """偵測裂痕點"""
        detected = []
        input_lower = user_input.lower()
        
        for name, data in self.fracture_maps.items():
            keywords = data.get('keywords', [])
            if not keywords:
                continue
            
            for kw in keywords:
                if isinstance(kw, str) and kw.lower() in input_lower:
                    severity = data.get('severity_level', 3)
                    detected.append(FractureDetection(
                        fracture_type=name,
                        trigger_keyword=kw,
                        severity_level=severity,
                        priority=severity / 5.0,
                        confidence=0.8,
                        context_tags=data.get('keywords', []),
                        intervention_prompts=data.get('intervention_prompts', []),
                        clinical_guidelines=data.get('clinical_guidelines', '')
                    ))
                    break
        
        detected.sort(key=lambda x: x.priority, reverse=True)
        return detected

    def _generate_safety_response(self, 
                                 top_fracture: FractureDetection, 
                                 fast_track_result: str, 
                                 intimacy: float) -> str:
        """生成安全回應"""
        parts = [
            fast_track_result if fast_track_result else (
                top_fracture.intervention_prompts[0] if top_fracture.intervention_prompts else "我在這。"
            )
        ]
        
        if top_fracture.severity_level >= 4:
            from app.clinical.companion_language_policy import get_companion_grounding_hint
            parts.append(f"\n{get_companion_grounding_hint()}")
        
        return "\n".join(parts)

    def _adjust_by_intimacy(self, response: str, intimacy: float) -> str:
        """根據親密度調整回應"""
        if intimacy >= 0.7:
            response = response.replace('你', '寶貝')
        return response

    def _get_safe_reply(self, response_type: str = 'fallback') -> str:
        """Return companion-safe navigator fallback (ADR-001 gate)."""
        from app.clinical.companion_language_policy import get_companion_reply
        from app.clinical.user_facing_gate import apply_user_facing_gate

        reply = get_companion_reply(response_type)
        risk_hint = 5 if response_type == 'critical' else 4 if response_type == 'high_risk' else 1
        return apply_user_facing_gate(
            reply,
            risk_level=risk_hint,
            source=f"navigator_get_safe_reply:{response_type}",
        ).text

    def get_stats(self) -> Dict[str, Any]:
        """取得統計數據"""
        return {
            'decisions_made': self.decisions_made,
            'safety_mode_triggered': self.safety_mode_triggered,
            'fracture_maps_count': len(self.fracture_maps)
        }
    
    def print_stats(self):
        """打印統計數據"""
        stats = self.get_stats()
        logger.info(f"[NAVIGATOR] Decisions: {stats['decisions_made']}, "
                   f"Safety Mode: {stats['safety_mode_triggered']}, "
                   f"Fracture Maps: {stats['fracture_maps_count']}")

    def close(self) -> None:
        """關閉資源"""
        logger.info("[NAVIGATOR] Closing IntelligentNavigator...")


# 全局實例
navigator: Optional[IntelligentNavigator] = None

try:
    navigator = IntelligentNavigator()
except Exception as e:
    logger.error(f"Failed to initialize global navigator: {e}")

__all__ = ['IntelligentNavigator', 'navigator', 'FractureDetection', 'NavigationDecision']