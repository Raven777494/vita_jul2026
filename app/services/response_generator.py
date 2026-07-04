# app/services/response_generator.py
"""
回應生成層（修訂版 - Phase 2）
整合 LLM 服務和智慧導航層
"""

import logging
import asyncio
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime

logger = logging.getLogger('vita.response_generator')

from app.services.llm_service import llm_service
from app.services.fracture_map.intelligent_navigator import get_navigator, NavigationDecision
from app.services.db_service import db_service

class ResponseGenerator:
    """回應生成器"""
    
    def __init__(self):
        self.llm_service = llm_service
        self.navigator = get_navigator()
        self.db_service = db_service
        logger.info("[RESPONSE GENERATOR] Initialized")
    
    async def generate(self, user_id: str, user_input: str, session_history: Optional[List[Dict]] = None, intimacy: Optional[float] = None) -> Tuple[str, Dict[str, Any]]:
        try:
            if intimacy is None: intimacy = 0.5 # Simplified
            
            logger.debug(f"[GEN] User {user_id}, Intimacy: {intimacy:.2f}")
            
            # Intelligent Navigation
            if self.navigator:
                response_text, navigation_decision = await self.navigator.navigate_async(
                    user_id=user_id,
                    user_input=user_input,
                    session_history=session_history,
                    intimacy=intimacy
                )
            else:
                # Fallback if navigator fails to init
                response_text = "Navigator unavailable."
                navigation_decision = None

            metadata = {
                'decision_id': navigation_decision.decision_id if navigation_decision else 'none',
                'decision_type': navigation_decision.decision_type if navigation_decision else 'unknown',
                'total_time': navigation_decision.total_time if navigation_decision else 0
            }
            
            return response_text, metadata
        
        except Exception as e:
            logger.error(f"[GEN] Error: {e}", exc_info=True)
            return "對不起，我現在無法回應。請稍候再試。", {'error': str(e)}

response_generator = ResponseGenerator()
__all__ = ['ResponseGenerator', 'response_generator']
