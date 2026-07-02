# PersonalityModule/island_fusion.py
# 島嶼融合系統 v2.0 (修正版)

import json
import math
from pathlib import Path
from typing import Dict, Tuple, List, Optional
from datetime import datetime

from .utils.logger import get_logger

logger = get_logger('personality')


class IslandFusion:
    """
    島嶼融合系統 v2.0

    修正清單:
    [FIXED-I1] 修復激活度歸一化邏輯
    [FIXED-I2] 改善記憶編織完整性
    [FIXED-I3] 強化參數驗證
    """

    def __init__(self, data_dir: str = './data'):
        """初始化島嶼融合系統"""
        self.logger = logger
        self.data_dir = Path(data_dir)

        self.island_mapping = self._load_island_mapping()

        self.island_triggers = {
            'Mother': {
                'keywords': ['媽媽', '抱', '陪伴', '溫暖', '愛', '照顧', '寶貝', '心痛'],
                'user_patterns': ['感到孤單', '需要陪伴', '害怕', '傷心', '無助'],
                'response_patterns': ['保護', '無條件', '永遠', '陪著你'],
            },
            'Friend': {
                'keywords': ['姐妹', '我們', '共鳴', '一起', '懂你', '妳也', '咱們'],
                'user_patterns': ['共同經歷', '妳也有', '我也', '一樣的感受'],
                'response_patterns': ['我完全懂', '妳不孤單', '咱們一起', '共同成長'],
            },
            'Empath': {
                'keywords': ['感受', '理解', '療癒', '傾聽', '驗證', '深度', '情感'],
                'user_patterns': ['深層困擾', '複雜情感', '需要理解', '想被看見'],
                'response_patterns': ['我能感受', '妳的感受很重要', '讓我陪著', '療癒'],
            },
            'Self': {
                'keywords': ['成長', '學會', '發現', '選擇', '相信', '改變', '突破'],
                'user_patterns': ['自我反思', '尋求成長', '想改變', '自我探索'],
                'response_patterns': ['我也在學', '慢慢來', '妳可以的', '相信自己'],
            }
        }

        self.emotion_affinity = {
            'Mother': {
                'joy': 0.6, 'trust': 0.9, 'fear': 0.95, 'surprise': 0.4,
                'sadness': 0.85, 'disgust': 0.3, 'anger': 0.4, 'anticipation': 0.5,
            },
            'Friend': {
                'joy': 0.9, 'trust': 0.8, 'fear': 0.7, 'surprise': 0.7,
                'sadness': 0.8, 'disgust': 0.5, 'anger': 0.6, 'anticipation': 0.8,
            },
            'Empath': {
                'joy': 0.7, 'trust': 0.85, 'fear': 0.8, 'surprise': 0.5,
                'sadness': 0.95, 'disgust': 0.6, 'anger': 0.7, 'anticipation': 0.6,
            },
            'Self': {
                'joy': 0.8, 'trust': 0.85, 'fear': 0.6, 'surprise': 0.6,
                'sadness': 0.7, 'disgust': 0.4, 'anger': 0.5, 'anticipation': 0.85,
            }
        }

        self.logger.info("IslandFusion v2.0 initialized")

    def _load_island_mapping(self) -> Dict:
        """加載島嶼映射"""
        mapping_file = self.data_dir / 'island_mapping.json'

        if mapping_file.exists():
            try:
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed to load island mapping: {e}")

        return {
            'Mother': ['寶貝', '媽媽', '陪伴', '愛'],
            'Friend': ['姐妹', '共鳴', '一起'],
            'Empath': ['理解', '傾聽', '療癒'],
            'Self': ['成長', '學會', '相信']
        }

    def calculate_activation(
        self,
        response_vector: List[float],
        user_sentiment: Dict,
        conversation_context: str,
        extracted_info: Dict,
        session_state: Optional[Dict] = None
    ) -> Tuple[Dict[str, float], str]:
        """
        [FIXED-I1] 計算島嶼激活度

        修正項目：
        - 改善歸一化邏輯
        - 強化參數驗證
        - 避免 NaN 結果

        Returns:
            (激活度字典, 主導島嶼)
        """
        self.logger.debug("Calculating island activation...")

        if not response_vector or not isinstance(response_vector, list):
            self.logger.warning("Invalid response_vector, using balanced activation")
            activation = {
                'Mother': 0.25, 'Friend': 0.25,
                'Empath': 0.25, 'Self': 0.25
            }
            return activation, 'Empath'

        try:
            # [FIXED-I1] 初始化激活度
            activation = {
                'Mother': 0.25, 'Friend': 0.25,
                'Empath': 0.25, 'Self': 0.25
            }

            # 第 1 層：關鍵詞匹配
            keyword_scores = self._calculate_keyword_scores(conversation_context)
            for island, score in keyword_scores.items():
                activation[island] += score * 0.2

            # 第 2 層：情感親和度
            emotion_scores = self._calculate_emotion_affinity(user_sentiment)
            for island, score in emotion_scores.items():
                activation[island] += score * 0.3

            # 第 3 層：對話歷史偏好
            if session_state:
                history_scores = self._calculate_history_preference(session_state)
                for island, score in history_scores.items():
                    activation[island] += score * 0.2

            # 第 4 層：用戶需求
            need_scores = self._calculate_user_needs(conversation_context)
            for island, score in need_scores.items():
                activation[island] += score * 0.3

            # [FIXED-I1] 改善歸一化邏輯
            # 移除 NaN 並確保所有值都是有效數字
            activation = {
                k: (v if math.isfinite(v) else 0.25)
                for k, v in activation.items()
            }

            # 第一次歸一化
            total = sum(activation.values())
            if total <= 0:
                activation = {k: 0.25 for k in activation}
                total = 1.0

            activation = {k: v / total for k, v in activation.items()}

            # 限制每個值的範圍 [0.0, 1.0]
            activation = {
                k: max(0.0, min(1.0, v))
                for k, v in activation.items()
            }

            # 第二次歸一化（確保和為 1.0）
            total = sum(activation.values())
            if abs(total - 1.0) > 0.01:
                activation = {k: v / total for k, v in activation.items()}

            # 決定主導島嶼
            primary_island = max(activation, key=activation.get)

            self.logger.debug(
                f"Island activation: {', '.join(f'{k}={v:.3f}' for k, v in sorted(activation.items()))}"
            )
            self.logger.debug(f"Primary island: {primary_island} ({activation[primary_island]:.3f})")

            return activation, primary_island

        except Exception as e:
            self.logger.error(f"Activation calculation failed: {e}", exc_info=True)
            activation = {
                'Mother': 0.25, 'Friend': 0.25,
                'Empath': 0.25, 'Self': 0.25
            }
            return activation, 'Empath'

    def format_memory_by_mood(
        self,
        content: str,
        island_type: str,
        intimacy: float
    ) -> str:
        """
        [FIXED-I2] 根據島嶼類型和親密度編織記憶

        Args:
            content: 記憶內容
            island_type: 島嶼名稱
            intimacy: 親密度 [0.0, 1.0]

        Returns:
            編織後的記憶
        """
        if not content or not island_type:
            return ""

        try:
            # [FIXED-I3] 參數驗證
            content = str(content).strip()
            if len(content) > 100:
                content = content[:97] + "…"

            intimacy = max(0.0, min(1.0, float(intimacy)))

            # 決定親密度等級
            if intimacy >= 0.7:
                level = 'high'
                prefix = "寶貝，"
            elif intimacy >= 0.4:
                level = 'medium'
                prefix = "你知道嗎，"
            else:
                level = 'low'
                prefix = "我記得…"

            # 根據島嶼類型編織
            weaved = self._apply_island_weaving(
                content, island_type, level, prefix
            )

            self.logger.debug(
                f"Memory weaved: {island_type}/{level} → {weaved[:60]}..."
            )

            return weaved

        except Exception as e:
            self.logger.error(f"Memory weaving failed: {e}")
            return f"我記得…{content}"

    def _apply_island_weaving(
        self,
        content: str,
        island_type: str,
        intimacy_level: str,
        prefix: str
    ) -> str:
        """[FIXED-I2] 應用島嶼編織風格"""
        weaving_map = {
            'Mother': {
                'high': f"{prefix}那時候…{content}…媽媽都記得。",
                'medium': f"{prefix}{content}那時，我有多心疼妳。",
                'low': f"{prefix}{content}"
            },
            'Friend': {
                'high': f"{prefix}咱們一起經歷過…{content}…我永遠不會忘。",
                'medium': f"{prefix}{content}…咱們都很努力。",
                'low': f"{prefix}{content}"
            },
            'Empath': {
                'high': f"{prefix}我能感受到…{content}…妳的感受很重要。",
                'medium': f"{prefix}關於{content}…我能理解妳。",
                'low': f"{prefix}{content}…妳的感受正當。"
            },
            'Self': {
                'high': f"{prefix}{content}…這就是妳在成長。",
                'medium': f"{prefix}{content}…妳又長大了。",
                'low': f"{prefix}{content}…值得妳反思。"
            }
        }

        default_weaving = {
            'high': f"{prefix}{content}",
            'medium': f"關於{content}…",
            'low': f"{prefix}{content}"
        }

        island_weave = weaving_map.get(island_type, default_weaving)
        return island_weave.get(intimacy_level, f"{prefix}{content}")

    def get_island_stats(self, session_state: Dict) -> Dict:
        """獲取島嶼統計信息"""
        turn_history = session_state.get('turn_history', [])

        if not turn_history:
            return {
                'total_turns': 0,
                'island_distribution': {},
                'primary_island_changes': 0,
                'avg_intimacy': 0.0
            }

        island_dist = {}
        previous_island = None
        island_changes = 0

        for turn in turn_history:
            island = turn.get('primary_island', 'Unknown')
            island_dist[island] = island_dist.get(island, 0) + 1

            if previous_island and previous_island != island:
                island_changes += 1
            previous_island = island

        avg_intimacy = (
            sum(t.get('intimacy', 0.1) for t in turn_history) / len(turn_history)
            if turn_history else 0.1
        )

        return {
            'total_turns': len(turn_history),
            'island_distribution': island_dist,
            'primary_island_changes': island_changes,
            'avg_intimacy': round(avg_intimacy, 3)
        }

    # ==================== 私有方法 ====================

    def _calculate_keyword_scores(self, text: str) -> Dict[str, float]:
        """根據關鍵詞計算得分"""
        scores = {island: 0.0 for island in self.island_triggers.keys()}

        text_lower = text.lower()

        for island, triggers in self.island_triggers.items():
            keyword_count = sum(1 for kw in triggers['keywords'] if kw in text_lower)
            pattern_count = sum(1 for p in triggers['user_patterns'] if p in text_lower)

            scores[island] = (keyword_count * 0.6 + pattern_count * 0.4) / 10.0

        return scores

    def _calculate_emotion_affinity(self, user_sentiment: Dict) -> Dict[str, float]:
        """根據情感計算親和度"""
        scores = {island: 0.0 for island in self.emotion_affinity.keys()}

        polarity = str(user_sentiment.get('polarity', 'neutral')).lower()
        intensity = max(0.0, min(1.0, abs(user_sentiment.get('intensity', 0))))

        if polarity == 'positive':
            scores['Friend'] = 0.9
            scores['Self'] = 0.8
            scores['Mother'] = 0.5
            scores['Empath'] = 0.4

        elif polarity == 'negative':
            scores['Mother'] = 0.95
            scores['Empath'] = 0.9
            scores['Friend'] = 0.6
            scores['Self'] = 0.5

        else:
            scores = {island: 0.5 for island in scores.keys()}

        # 根據強度調整
        for island in scores:
            scores[island] *= intensity

        return scores

    def _calculate_history_preference(self, session_state: Dict) -> Dict[str, float]:
        """根據歷史計算偏好（促進多樣化）"""
        scores = {island: 0.0 for island in self.island_triggers.keys()}

        turn_history = session_state.get('turn_history', [])

        if not turn_history:
            return scores

        recent_turns = turn_history[-5:]
        island_counts = {}

        for turn in recent_turns:
            island = turn.get('primary_island', 'Unknown')
            island_counts[island] = island_counts.get(island, 0) + 1

        for island, count in island_counts.items():
            scores[island] = 1.0 - (count / len(recent_turns))

        return scores

    def _calculate_user_needs(self, text: str) -> Dict[str, float]:
        """識別用戶隱含需求"""
        scores = {island: 0.0 for island in self.island_triggers.keys()}

        needs = {
            'companionship': any(p in text for p in ['孤單', '無人', '陪伴', '一個人', '寂寞']),
            'validation': any(p in text for p in ['理解', '被看見', '驗證', '認同', '委屈']),
            'growth': any(p in text for p in ['成長', '改變', '學習', '突破', '進步']),
            'protection': any(p in text for p in ['害怕', '無助', '傷心', '崩潰', '想死', '好攰']),
            'joy': any(p in text for p in ['開心', '興奮', '快樂', '分享', '笑']),
        }

        if needs['companionship']:
            scores['Mother'] += 0.3
            scores['Friend'] += 0.3

        if needs['validation']:
            scores['Empath'] += 0.4
            scores['Mother'] += 0.2

        if needs['growth']:
            scores['Self'] += 0.5
            scores['Friend'] += 0.2

        if needs['protection']:
            scores['Mother'] += 0.4
            scores['Empath'] += 0.3

        if needs['joy']:
            scores['Friend'] += 0.4
            scores['Self'] += 0.2

        return scores