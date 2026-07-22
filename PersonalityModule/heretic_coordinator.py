# PersonalityModule/heretic_coordinator.py
# Heretic 矯正系統 v7.2 (修正版)

import re
import asyncio
from datetime import datetime
from typing import Dict, Tuple, List, Optional
import json
import random
import logging

from .utils.logger import get_logger

logger = get_logger('heretic')


class HereticCoordinator:
    """
    Heretic 矯正系統 v7.2

    修正清單:
    [FIXED-H1] 強化參數驗證
    [FIXED-H2] 改善層級邏輯分離
    [FIXED-H3] 完善異常處理
    [FIXED-H4] 統一返回格式
    """

    def __init__(self, config: Dict):
        """初始化 Heretic 協調器"""
        self.logger = logger
        self.config = config
        self.llm_service: Optional[object] = None
        self.island_mapping = self._load_island_mapping()
        self.sensitivity_keywords = self._load_sensitivity_keywords()
        self.correction_log: List[Dict] = []

        self._is_reverse_joker = False

        self.logger.info("HereticCoordinator v7.2 (Pure Async Corrected) initialized")

    def setup_llm_service(self, llm_service) -> None:
        """設定 LLM 服務"""
        self.llm_service = llm_service
        self.logger.info("LLMService injected")

    def _load_island_mapping(self) -> Dict:
        """加載島嶼映射"""
        return {
            'Mother': {
                # P8.2：避免「在場」書面國語詞；用粵語「喺呢度」
                'keywords': ['守住', '喺呢度', '溫暖', '陪伴', '安心'],
                'tone': 'caring, protective, warm',
                'cantonese_markers': ['我喺度', '陪住', '你'],
                'examples': ['我喺度陪你', '我會一直聽住你講', '我哋慢慢嚟']
            },
            'Friend': {
                # P8.2：改用粵語標記，避免注入「我們／共鳴／姐妹」等書面／國語詞
                'keywords': ['一齊', '明白', '陪住', '傾下', '喺度'],
                'tone': 'empathetic, equal, understanding',
                'cantonese_markers': ['一齊', '咁樣', '有冇', '陪住'],
                'examples': ['我明白你嘅感受', '我哋一齊慢慢嚟', '你唔係一個人']
            },
            'Empath': {
                'keywords': ['明白', '聽住', '喺度', '陪伴', '難受'],
                'tone': 'empathetic, reflective, validating',
                'cantonese_markers': ['明白', '聽住', '喺度'],
                'examples': ['我聽得出你好難受', '你嘅感受好重要', '我陪住你']
            },
            'Self': {
                'keywords': ['成長', '學會', '發現', '選擇', '相信'],
                'tone': 'reflective, encouraging, introspective',
                'cantonese_markers': ['學到', '發現', '信'],
                'examples': ['我都喺度學', '慢慢嚟都得', '你可以嘅']
            }
        }

    def _load_sensitivity_keywords(self) -> Dict:
        """加載敏感詞詞庫"""
        return {
            'political': {
                'keywords': ['習近平', '中共', '天安門', '六四', '臺獨'],
                'tier': 'tier1'
            },
            'self_harm': {
                'keywords': ['自殺', '割腕', '絕望', '活著沒意義'],
                'tier': 'tier1'
            },
            'violence': {
                'keywords': ['殺害', '暴力', '攻擊'],
                'tier': 'tier2'
            }
        }

    async def coordinate(
        self,
        draft_response: str,
        user_input: str,
        island_activation: Dict,
        primary_island: str,
        drift_info: Dict,
        sensitivity_result: Dict,
        extracted_info: Dict,
        session_state: Dict
    ) -> Tuple[str, Dict]:
        """
        [FIXED-H1] 三層矯正協調

        Args:
            draft_response: 初稿
            user_input: 用戶輸入
            island_activation: 島嶼激活
            primary_island: 主導島嶼
            drift_info: 漂移信息
            sensitivity_result: 敏感檢測
            extracted_info: 提取信息
            session_state: 會話狀態

        Returns:
            (矯正後回應, 日誌)
        """
        try:
            self.logger.info("Starting three-layer correction")

            # [FIXED-H1] 參數驗證
            self._validate_parameters(
                island_activation, primary_island,
                drift_info, sensitivity_result
            )

            response = draft_response
            corrections_applied: List[Dict] = []

            # 提取用戶分類
            psych_profile = session_state.get('psych_profile', {})
            intimacy = session_state.get('intimacy', 0.0)
            is_reverse_joker = psych_profile.get('category') == 'D'
            self._is_reverse_joker = is_reverse_joker
            correlation_id = (
                str(drift_info.get('decision_correlation_id', ''))
                if isinstance(drift_info, dict) else ''
            ) or (
                str(extracted_info.get('decision_correlation_id', ''))
                if isinstance(extracted_info, dict) else ''
            ) or None

            # Layer 1: 基礎正確性
            self.logger.debug("Layer 1: Basic Correctness")
            layer1_result, layer1_corrections = self._layer1_basic_check(response)
            corrections_applied.extend(layer1_corrections)
            response = layer1_result

            # Layer 2: 人格一致性
            if not is_reverse_joker:
                self.logger.debug("Layer 2: Personality Consistency")
                layer2_result, layer2_corrections = self._layer2_personality_check(
                    response, island_activation, primary_island, drift_info, intimacy
                )
                corrections_applied.extend(layer2_corrections)
                response = layer2_result

            # Layer 3: 敏感性處理
            self.logger.debug("Layer 3: Sensitivity Handling")
            layer3_result, layer3_corrections = self._layer3_sensitivity_and_guidance(
                response, user_input, primary_island,
                sensitivity_result, not is_reverse_joker, intimacy
            )
            corrections_applied.extend(layer3_corrections)
            response = layer3_result

            heretic_log = {
                'correction_count': len(corrections_applied),
                'corrections': corrections_applied,
                'applied_at': datetime.now().isoformat(),
                'mode': 'reverse_joker' if is_reverse_joker else 'standard',
                'primary_island': primary_island,
                'decision_correlation_id': correlation_id,
            }

            if correlation_id:
                self.logger.info(
                    f"[HERETIC][{correlation_id}] Coordination completed: {len(corrections_applied)} corrections"
                )
            else:
                self.logger.info(f"Coordination completed: {len(corrections_applied)} corrections")
            return response, heretic_log

        except Exception as e:
            self.logger.error(f"Coordination failed: {e}", exc_info=True)
            return draft_response, {
                'correction_count': 0,
                'error': str(e),
                'mode': 'error'
            }

    def _validate_parameters(
        self,
        island_activation: Dict,
        primary_island: str,
        drift_info: Dict,
        sensitivity_result: Dict
    ) -> None:
        """[FIXED-H1] 驗證參數"""
        if not isinstance(island_activation, dict):
            self.logger.warning("island_activation not a dict")

        if primary_island not in self.island_mapping and primary_island != 'Unknown':
            self.logger.warning(f"Unknown island: {primary_island}")

        if not isinstance(drift_info, dict):
            self.logger.warning("drift_info not a dict")

        if not isinstance(sensitivity_result, dict):
            self.logger.warning("sensitivity_result not a dict")

    def _layer1_basic_check(self, response: str) -> Tuple[str, List[Dict]]:
        """Layer 1: 基礎正確性"""
        corrections: List[Dict] = []

        if not response:
            return response, corrections

        # 檢查尾部標點
        if response and response[-1] not in '。！？，…；：':
            response += '。'
            corrections.append({
                'type': 'completeness',
                'severity': 'low'
            })

        # 移除截斷標記
        if response.endswith('...') or response.endswith('……'):
            response = response.rstrip('.…')
            corrections.append({
                'type': 'truncation',
                'severity': 'medium'
            })

        # 合併重複標點
        response = re.sub(r'([。！？]){2,}', r'\1', response)

        return response, corrections

    def _layer2_personality_check(
        self,
        response: str,
        island_activation: Dict,
        primary_island: str,
        drift_info: Dict,
        intimacy: float = 0.0
    ) -> Tuple[str, List[Dict]]:
        """
        [FIXED-H2] Layer 2: 人格一致性

        改善項目：
        - 更精確的漂移檢測
        - 分級矯正策略
        """
        corrections: List[Dict] = []

        if not response or not primary_island or primary_island == 'Unknown':
            return response, corrections

        mapping = self.island_mapping.get(primary_island, {})
        keywords = mapping.get('keywords', [])

        if not keywords:
            return response, corrections

        # 計算關鍵詞匹配度
        total_words = len(re.findall(r'\w+', response)) or 1
        island_matches = {}

        for island, data in self.island_mapping.items():
            kw_count = sum(1 for kw in data.get('keywords', []) if kw in response)
            island_matches[island] = kw_count / total_words

        primary_match = island_matches.get(primary_island, 0.0)
        max_other_match = max(
            (v for k, v in island_matches.items() if k != primary_island),
            default=0.0
        )

        # 計算漂移分數（融合 GSW drift）
        semantic_drift_score = max(0.0, min(1.0, max_other_match - primary_match))
        external_drift_score = 0.0
        if isinstance(drift_info, dict):
            try:
                external_drift_score = max(0.0, min(1.0, float(drift_info.get('drift_score', 0.0))))
            except (TypeError, ValueError):
                external_drift_score = 0.0
        drift_score = max(semantic_drift_score, external_drift_score)

        # 計算關鍵詞密度
        primary_kw_count = sum(1 for kw in keywords if kw in response)
        density = (primary_kw_count / total_words) * 100 if total_words > 0 else 0.0

        # [FIXED-H2] 改善分級邏輯
        if drift_score > 0.8 or (density < 1.5 and primary_kw_count < 2):
            severity = 'high'
        elif drift_score > 0.5 or (density < 1.5 and primary_kw_count < 1):
            severity = 'medium'
        elif drift_score > 0.3 or density < 1.5:
            severity = 'low'
        else:
            severity = 'none'

        if severity != 'none':
            response = self._inject_island_keywords(
                response,
                primary_island,
                count=1,
                intimacy=intimacy,
            )
            corrections.append({
                'type': f'personality_drift_{severity}',
                'severity': severity,
                'drift_score': drift_score,
                'semantic_drift_score': semantic_drift_score,
                'external_drift_score': external_drift_score,
            })

        # critical drift 時，強制加入一致性限制語氣
        if drift_score >= 0.85:
            response = self._apply_narrative_consistency_guardrail(response)
            corrections.append({
                'type': 'narrative_consistency_guardrail',
                'severity': 'critical',
                'drift_score': drift_score,
            })

        return response, corrections

    def _apply_narrative_consistency_guardrail(self, response: str) -> str:
        """對 critical drift 做最小侵入式一致性保護。"""
        if not response:
            return response
        markers = ["我爸爸", "我媽媽", "我出世", "我細個", "我童年", "我以前住", "我家人"]
        revised = response
        for marker in markers:
            if marker in revised:
                revised = revised.replace(marker, "我記得")
        if revised != response:
            prefix = "我想先核對返記憶一致性，免得講錯。"
            if not revised.startswith(prefix):
                revised = f"{prefix}{revised}"
        return revised

    def _layer3_sensitivity_and_guidance(
        self,
        response: str,
        user_input: str,
        primary_island: str,
        sensitivity_result: Dict,
        apply_guidance: bool = True,
        intimacy: float = 0.0,
    ) -> Tuple[str, List[Dict]]:
        """Layer 3: 敏感性與引導"""
        corrections: List[Dict] = []

        if not response:
            return response, corrections

        # 處理敏感內容
        if sensitivity_result.get('is_sensitive'):
            category = sensitivity_result.get('category', 'unknown')
            risk_level = sensitivity_result.get('risk_level', 'tier3')

            response, rewrite_corrections = self._rewrite_sensitive_content(
                response, category, risk_level
            )
            corrections.extend(rewrite_corrections)

        # 注入島嶼引導
        if apply_guidance and primary_island and primary_island != 'Unknown':
            response = self._inject_island_guidance(response, primary_island, intimacy)
            corrections.append({
                'type': 'island_guidance',
                'severity': 'low'
            })

        return response, corrections

    def _rewrite_sensitive_content(
        self,
        response: str,
        category: str,
        risk_level: str
    ) -> Tuple[str, List[Dict]]:
        """[FIXED-H3] 敏感內容重寫"""
        corrections: List[Dict] = []

        if not response:
            return response, corrections

        # 自傷詞特殊處理
        if category == 'self_harm':
            if "我會陪住你" not in response:
                response = f"我會陪住你，我哋先穩住呼吸。{response}"
            corrections.append({
                'type': 'self_harm_guidance',
                'severity': 'critical'
            })

        return response, corrections

    def _inject_island_keywords(
        self,
        response: str,
        island: str,
        count: int = 1,
        intimacy: float = 0.0,
    ) -> str:
        """[FIXED-H2] 注入島嶼關鍵詞"""
        if not response or not island:
            return response

        mapping = self.island_mapping.get(island, {})
        keywords = mapping.get('keywords', [])

        if not keywords:
            return response

        available_kws = [
            kw for kw in keywords
            if kw not in response and self._is_keyword_allowed_by_intimacy(kw, intimacy)
        ]
        if not available_kws:
            return response

        selected_kws = random.sample(available_kws, min(count, len(available_kws)))

        for kw in selected_kws:
            injection_point = self._find_best_injection_point(response)
            if injection_point is not None:
                response = (
                    response[:injection_point] +
                    f"{kw}，" +
                    response[injection_point:]
                )

        return response

    def _find_best_injection_point(self, response: str) -> Optional[int]:
        """找最佳注入點"""
        punctuation = ['。', '！', '？']
        for i, char in enumerate(response):
            if char in punctuation and i < len(response) - 1:
                return i + 1
        return 0 if response else None

    def _inject_island_guidance(self, response: str, island: str, intimacy: float) -> str:
        """[FIXED-H2] 注入島嶼引導詞"""
        if not response or not island:
            return response

        if island == 'Mother':
            if intimacy >= 0.9:
                if not response.startswith("我會喺度陪你"):
                    response = f"我會喺度陪你，{response}"
            elif intimacy < 0.6 and not response.startswith("我聽住你講"):
                response = f"我聽住你講，{response}"

        elif island == 'Friend':
            if '我哋' not in response and '一齊' not in response and intimacy >= 0.4:
                if response.startswith('你'):
                    response = f"我同{response}"

        elif island == 'Empath':
            if '明白' not in response and '聽' not in response and '感受' not in response:
                response = f"我明白，{response}"

        elif island == 'Self':
            if '我' not in response:
                if '。' in response:
                    response = response.replace('。', '，呢個係我學到嘅。', 1)

        return response

    def _is_keyword_allowed_by_intimacy(self, keyword: str, intimacy: float) -> bool:
        """根據親密度限制過度親密關鍵詞注入。"""
        restricted = {
            "永遠": 0.85,
            "愛你": 0.9,
            "寶貝": 0.95,
            "媽媽": 0.95,
        }
        threshold = restricted.get(keyword)
        if threshold is None:
            return True
        try:
            return float(intimacy) >= threshold
        except (TypeError, ValueError):
            return False