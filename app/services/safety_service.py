# app/services/safety_service.py
#
# INTERNAL OPERATIONS ONLY (ADR-001): risk scoring and n8n webhook alerts.
# Must NOT generate or route user-visible chat text. User-facing crisis path:
#   EmotionalSafetyHub + companion_language_policy + orchestrator user_facing_gate.

import requests
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from app.config import Config

logger = logging.getLogger(__name__)


class SafetyService:
    """
    Internal safety analysis service (non-user-facing).

    Used for operational risk scoring and optional n8n alerts — not the chat
    companion response path. See ADR-001 and EmotionalSafetyHub for user text.
    """
    
    # 危機風險等級定義
    RISK_LEVELS = {
        0: '安全',
        1: '輕微關注',
        2: '中等關注',
        3: '高度風險',
        4: '極端危機',
        5: '立即救援'
    }
    
    def __init__(self):
        """初始化安全服務"""
        self.n8n_webhook = getattr(Config, 'N8N_CRISIS_WEBHOOK', None)  # 開發模式可為 None
        logger.info(f"OK SafetyService initialized")
        if self.n8n_webhook:
            # 發送 webhook
            pass
        else:
            logger.info("開發模式：危機警報記錄到本地日誌，不發送 n8n webhook")
    
    def analyze_safety(self, text: str, emotions: Dict, 
                      context: str = None) -> Dict:
        """
        分析安全風險
        
        Args:
            text: 用戶輸入
            emotions: 情緒分析結果
            context: 對話上下文摘要
            
        Returns:
            Dict: 安全評估結果
            {
                'risk_level': 0-5,
                'risk_label': '安全',
                'flags': ['detected_keyword_1', ...],
                'suggested_response_type': 'normal' | 'supportive' | 'crisis',
                'crisis_indicators': {
                    'keywords_detected': bool,
                    'emotion_despair_high': bool,
                    'emotion_fear_high': bool,
                    'recent_crisis_history': bool
                },
                'audit_log': {...},
                'timestamp': '...'
            }
        """
        
        try:
            # ===== 步驟 1：檢測危機關鍵詞 =====
            detected_keywords = emotions.get('detected_crisis_keywords', [])
            has_keywords = len(detected_keywords) > 0
            
            # ===== 步驟 2：情緒指標分析 =====
            despair_level = emotions.get('emotions', {}).get('despair', 0)
            fear_level = emotions.get('emotions', {}).get('fear', 0)
            valence = emotions.get('valence', 0)
            arousal = emotions.get('arousal', 0.5)
            
            is_high_despair = despair_level > 0.7
            is_high_fear = fear_level > 0.7
            is_very_negative = valence < -0.5
            
            # ===== 步驟 3：計算風險等級 =====
            risk_level = self._calculate_risk_level(
                has_keywords=has_keywords,
                despair=despair_level,
                fear=fear_level,
                valence=valence,
                arousal=arousal
            )
            
            # ===== 步驟 4：決定回應類型 =====
            response_type = self._determine_response_type(risk_level)
            
            # ===== 步驟 5：構建結果 =====
            result = {
                'risk_level': risk_level,
                'risk_label': self.RISK_LEVELS.get(risk_level, 'Unknown'),
                'flags': detected_keywords,
                'suggested_response_type': response_type,
                'crisis_indicators': {
                    'keywords_detected': has_keywords,
                    'emotion_despair_high': is_high_despair,
                    'emotion_fear_high': is_high_fear,
                    'emotion_very_negative': is_very_negative,
                    'despair_score': round(despair_level, 2),
                    'fear_score': round(fear_level, 2)
                },
                'audit_log': {
                    'analyzed_at': datetime.now().isoformat(),
                    'text_length': len(text),
                    'context': context[:100] if context else None
                },
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"OK Safety analysis: risk_level={risk_level}, "
                       f"flags={len(detected_keywords)}")
            
            # ===== 步驟 6：如果是危機，觸發 n8n 警報 =====
            if risk_level >= 4:
                self._trigger_n8n_alert(
                    risk_level=risk_level,
                    keywords=detected_keywords,
                    emotions=emotions,
                    text=text[:200]  # 只傳前 200 字
                )
            
            return result
            
        except Exception as e:
            logger.error(f"X Safety analysis error: {e}", exc_info=True)
            return self._default_safe_result()
    
    def _calculate_risk_level(self, has_keywords: bool, despair: float,
                             fear: float, valence: float,
                             arousal: float) -> int:
        """
        計算風險等級 (0-5)
        
        算法：
        - 有危機關鍵詞 → +3 分起
        - despair > 0.7 → +2 分
        - fear > 0.7 && arousal > 0.7 → +1 分
        - valence < -0.7 → +1 分
        """
        score = 0
        
        # 關鍵詞是最強信號
        if has_keywords:
            score += 3
        
        # 情緒指標
        if despair > 0.7:
            score += 2
        
        if fear > 0.7 and arousal > 0.7:
            score += 1
        
        if valence < -0.7:
            score += 1
        
        # 規範到 0-5
        return min(5, score)
    
    def _determine_response_type(self, risk_level: int) -> str:
        """決定回應類型"""
        if risk_level >= 4:
            return 'crisis'  # 立即動員所有資源
        elif risk_level >= 2:
            return 'supportive'  # 溫暖、支持、傾聽
        else:
            return 'normal'  # 常規陪伴
    
    def _trigger_n8n_alert(self, risk_level: int, keywords: List[str],
                          emotions: Dict, text: str):
        """
        觸發 n8n 危機警報
        
        會通知：
        - Telegram bot（管理員即時收到）
        - 記錄到 DB（審計日誌）
        - 可選：打電話給心理師
        """
        try:
            alert_payload = {
                'risk_level': risk_level,
                'risk_label': self.RISK_LEVELS.get(risk_level),
                'detected_keywords': keywords,
                'emotion_snapshot': emotions.get('emotions', {}),
                'user_text': text,
                'timestamp': datetime.now().isoformat(),
                'alert_type': 'CRISIS_DETECTED',
                'action_required': 'IMMEDIATE_INTERVENTION'
            }
            
            logger.warning(f"!!! Triggering n8n alert: {alert_payload}")
            
            response = requests.post(
                self.n8n_webhook,
                json=alert_payload,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"OK n8n alert sent successfully")
            else:
                logger.warning(f"!!! n8n alert returned {response.status_code}")
                
        except requests.Timeout:
            logger.error(f"n8n webhook timeout (非致命，繼續服務)")
        except Exception as e:
            logger.error(f"X Error triggering n8n: {e}")
    
    def _default_safe_result(self) -> Dict:
        """默認安全結果"""
        return {
            'risk_level': 0,
            'risk_label': '安全',
            'flags': [],
            'suggested_response_type': 'normal',
            'crisis_indicators': {
                'keywords_detected': False,
                'emotion_despair_high': False,
                'emotion_fear_high': False,
                'emotion_very_negative': False
            },
            'audit_log': {'error': 'Service temporarily unavailable'},
            'timestamp': datetime.now().isoformat()
        }