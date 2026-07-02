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
                'keywords': ['媽媽', '抱', '溫暖', '陪伴', '愛你', '寶貝'],
                'tone': 'caring, protective, warm',
                'cantonese_markers': ['媽媽', '寶貝', '妳'],
                'examples': ['寶貝，媽媽在這裡', '讓媽媽陪著你', '媽媽永遠愛你']
            },
            'Friend': {
                'keywords': ['姐妹', '我們', '一起', '共鳴', '懂你'],
                'tone': 'empathetic, equal, understanding',
                'cantonese_markers': ['姐妹', '咁樣', '有冇'],
                'examples': ['我完全懂你的感受', '咱們一起加油', '妳不孤單']
            },
            'Empath': {
                'keywords': ['感受', '理解', '療癒', '陪伴', '傾聽'],
                'tone': 'empathetic, reflective, validating',
                'cantonese_markers': ['感受', '明白', '聽住'],
                'examples': ['我能感受到你的痛', '你的感受很重要', '讓我陪著你']
            },
            'Self': {
                'keywords': ['成長', '學會', '發現', '選擇', '相信'],
                'tone': 'reflective, encouraging, introspective',
                'cantonese_markers': ['學到', '發現', '信'],
                'examples': ['我也在學習', '慢慢來，沒關係', '你可以的']
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
            is_reverse_joker = psych_profile.get('category') == 'D'
            self._is_reverse_joker = is_reverse_joker

            # Layer 1: 基礎正確性
            self.logger.debug("Layer 1: Basic Correctness")
            layer1_result, layer1_corrections = self._layer1_basic_check(response)
            corrections_applied.extend(layer1_corrections)
            response = layer1_result

            # Layer 2: 人格一致性
            if not is_reverse_joker:
                self.logger.debug("Layer 2: Personality Consistency")
                layer2_result, layer2_corrections = self._layer2_personality_check(
                    response, island_activation, primary_island, drift_info
                )
                corrections_applied.extend(layer2_corrections)
                response = layer2_result

            # Layer 3: 敏感性處理
            self.logger.debug("Layer 3: Sensitivity Handling")
            layer3_result, layer3_corrections = self._layer3_sensitivity_and_guidance(
                response, user_input, primary_island,
                sensitivity_result, not is_reverse_joker
            )
            corrections_applied.extend(layer3_corrections)
            response = layer3_result

            heretic_log = {
                'correction_count': len(corrections_applied),
                'corrections': corrections_applied,
                'applied_at': datetime.now().isoformat(),
                'mode': 'reverse_joker' if is_reverse_joker else 'standard',
                'primary_island': primary_island
            }

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
        drift_info: Dict
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

        # 計算漂移分數
        drift_score = max(0.0, min(1.0, max_other_match - primary_match))

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
            response = self._inject_island_keywords(response, primary_island, count=1)
            corrections.append({
                'type': f'personality_drift_{severity}',
                'severity': severity,
                'drift_score': drift_score
            })

        return response, corrections

    def _layer3_sensitivity_and_guidance(
        self,
        response: str,
        user_input: str,
        primary_island: str,
        sensitivity_result: Dict,
        apply_guidance: bool = True
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
            response = self._inject_island_guidance(response, primary_island)
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
            self_harm_keywords = self.sensitivity_keywords.get('self_harm', {}).get('keywords', [])
            for keyword in self_harm_keywords:
                if keyword in response:
                    response = response.replace(
                        keyword,
                        f"{keyword}（但生命中總有希望存在）"
                    )
                    corrections.append({
                        'type': 'self_harm_guidance',
                        'severity': 'critical'
                    })

        return response, corrections

    def _inject_island_keywords(
        self,
        response: str,
        island: str,
        count: int = 1
    ) -> str:
        """[FIXED-H2] 注入島嶼關鍵詞"""
        if not response or not island:
            return response

        mapping = self.island_mapping.get(island, {})
        keywords = mapping.get('keywords', [])

        if not keywords:
            return response

        available_kws = [kw for kw in keywords if kw not in response]
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

    def _inject_island_guidance(self, response: str, island: str) -> str:
        """[FIXED-H2] 注入島嶼引導詞"""
        if not response or not island:
            return response

        if island == 'Mother':
            if '媽媽' not in response and '寶貝' not in response:
                response = f"寶貝，{response}"

        elif island == 'Friend':
            if '我們' not in response and '咱們' not in response:
                if response.startswith('你'):
                    response = f"我跟{response}"
                elif '你' in response:
                    response = response.replace('你', '妳', 1)

        elif island == 'Empath':
            if '感受' not in response and '感覺' not in response:
                response = f"我能感受到，{response}"

        elif island == 'Self':
            if '我' not in response:
                if '。' in response:
                    response = response.replace('。', '，這是我學到的。', 1)

        return response