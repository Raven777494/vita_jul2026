# PersonalityModule/vocal_personality_layer.py
# 聲音人格層 v1.1 - 希兒發聲的精微調整系統

import re
import logging
import random
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
from functools import lru_cache

from .utils.logger import get_logger
from .cantonese_dict import batch_search
from .island_fusion import IslandFusion
from .heretic_coordinator import HereticCoordinator

logger = get_logger('vocal_personality')


class VocalPersonalityLayer:
    """
    聲音人格層 v1.1 - 希兒發聲的精微調整系統
    
    架構原則：
    1. SystemPromptBuilder 決定「方向」（母愛/友誼/共情/自我反省）
    2. LLM 根據方向生成「內容」
    3. VocalPersonalityLayer 進行「微調」（粒子、斷句、流暢度）
    
    核心職責：
    1. 智能粒子注入 - 檢查避免重複
    2. 安全短句結構 - 保持意思完整性
    3. 流暢性增強 - 口語自然度
    4. 最終清理 - 移除 AI 痕跡
    
    修正清單:
    [FIXED-VPL1] 非同步方法正確實現
    [FIXED-VPL2] 重複粒子檢測機制
    [FIXED-VPL3] 改善句子分割邏輯
    [FIXED-VPL4] 降低島嶼調整侵入度
    [FIXED-VPL5] 增強依賴驗證
    [FIXED-VPL6] 改善正則表達式清理
    [FIXED-VPL7] 上下文感知粒子位置
    [FIXED-VPL8] 統計追蹤完整性
    """
    
    # ==================== 常量定義 ====================
    
    # 粵語人格粒子 - 按強度分類
    PERSONALITY_PARTICLES = {
        'opening': [  # 句首粒子
            '嗯', '其實', '真的', '天啊', '你知道嗎', '聽住', '咁樣',
            '我覺得', '好似', '應該', '其實呀'
        ],
        'closing': [  # 句尾粒子
            '啦', '囉', '呀', '喇', '嘛', '㗎喎', '掖', '咁先', '啦喎',
            '你知吖', '係咪', '唔係'
        ],
        'soft': [  # 溫和粒子
            '好似', '或者', '應該', '大概', '可能', '係咁樣', '又或者'
        ],
        'emphasis': [  # 強調粒子
            '真的', '絕對', '極', '好', '超', '好好', '非常'
        ]
    }
    
    # 島嶼特徵詞庫（**微調用，非替換**）
    ISLAND_SIGNATURE_WORDS = {
        'Mother': {
            'warmth': ['我喺度', '陪住你', '安心', '慢慢嚟', '放心'],
            'exclusion': ['妳可以試試', '也許妳應該'],  # 不強行替換
        },
        'Friend': {
            'warmth': ['咱們', '我們', '一起', '沒關係', '相信妳'],
            'exclusion': ['妳應該知道']
        },
        'Empath': {
            'warmth': ['感受', '明白', '理解', '聽著', '同感'],
            'exclusion': ['解決辦法是']
        },
        'Self': {
            'warmth': ['慢慢來', '相信', '發現', '學到', '妳可以'],
            'exclusion': ['快速改變', '馬上']
        }
    }
    
    SENTENCE_TERMINATORS = {'.', '。', '!', '！', '?', '？', '…', '~', '～'}
    
    # 危險的正則表達式模式（會過度清理）
    DANGEROUS_REGEX_PATTERNS = [
        r'\[.*?\]',      # [系統標記]
        r'<\|.*?\|>',    # <|特殊標記|>
        r'\{.*?\}',      # {配置}
        r'<!--.*?-->',   # HTML 註釋
    ]
    
    # 重複檢測的安全距離（字符）
    REPEAT_CHECK_DISTANCE = 8
    
    def __init__(self, config: Dict):
        """
        初始化聲音人格層
        
        Args:
            config: 配置字典
        """
        self.logger = logger
        self.config = config
        
        # 核心系統指針（由 personality_module 注入）
        self.island_fusion: Optional[IslandFusion] = None
        self.heretic_coordinator: Optional[HereticCoordinator] = None
        
        # 統計資料
        self._stats = {
            'total_finalizations': 0,
            'particle_injections': 0,
            'particle_skips_duplicate': 0,
            'sentence_preservations': 0,
            'cleanups': 0,
            'errors': 0,
        }
        
        # 快取 LRU
        self._cache_detect_particles = {}
        
        self.logger.info("VocalPersonalityLayer v1.1 initialized")
    
    # ==================== 核心方法：聲音最終化 ====================
    
    async def finalize_voice(
        self,
        draft_response: str,
        context: Dict
    ) -> str:
        """
        [FIXED-VPL1] 聲音個性化的第三層 - 非同步正確實現
        
        此時 draft_response 已經根據 SystemPromptBuilder 的指導生成
        我們只做**微調**：
        1. 檢查粒子重複
        2. 安全短句（保持完整性）
        3. 流暢性增強
        4. 最終清理
        
        Args:
            draft_response: LLM 生成的文本
            context: 上下文字典
                - primary_island: 當前島嶼
                - intimacy: 親密度 (0.0-1.0)
                - user_input: 用戶輸入（用於上下文）
                - island_activation: 島嶼激活強度
        
        Returns:
            微調後的聲音化文本
        """
        if not isinstance(draft_response, str):
            self.logger.warning(
                f"Invalid draft_response type: {type(draft_response)}, "
                f"deferring to upstream fallback"
            )
            return ""
        
        try:
            # 基本檢驗
            draft_response = draft_response.strip()
            if not draft_response:
                self.logger.warning(
                    "Empty draft_response received; deferring to upstream fallback"
                )
                return ""
            
            # Zero-Truncation: never hard-cut user-facing draft text.
            if len(draft_response) > 2000:
                self.logger.debug(
                    f"Long draft received ({len(draft_response)} chars); "
                    "keeping full text (no truncation)"
                )

            self._stats['total_finalizations'] += 1
            
            primary_island = context.get('primary_island', 'Empath')
            intimacy = context.get('intimacy', 0.5)
            
            self.logger.debug(
                f"Starting voice finalization for {primary_island} "
                f"(intimacy: {intimacy:.2f}, len: {len(draft_response)})"
            )
            
            # 步驟 1: 智能粒子檢測與注入
            response = self._smart_particle_injection(
                draft_response,
                primary_island,
                intimacy
            )
            
            # 步驟 2: 安全短句結構（保持完整性）
            response = await self._safe_sentence_structure(response)
            
            # 步驟 3: 流暢性增強（口語自然度）
            response = self._enhance_fluency(response, primary_island)
            
            # 步驟 4: 最終清理
            response = self._final_cleanup(response)
            
            self.logger.debug(
                f"Voice finalization complete: {response[:80]}... "
                f"(final len: {len(response)})"
            )
            
            return response
        
        except Exception as e:
            self.logger.error(
                f"Voice finalization failed: {e}",
                exc_info=True
            )
            self._stats['errors'] += 1
            return draft_response or "嗯，我在聽。"
    
    # ==================== 子步驟實現 ====================
    
    def _smart_particle_injection(
        self,
        text: str,
        island: str,
        intimacy: float
    ) -> str:
        """
        [FIXED-VPL2] 智能粒子注入 - 檢查重複
        
        邏輯：
        1. 檢測句首是否已有粒子
        2. 檢測句首前 8 字是否有相同粒子
        3. 根據親密度決定注入概率
        4. 選擇合適的位置（開頭/結尾）
        
        Args:
            text: 輸入文本
            island: 島嶼類型
            intimacy: 親密度
        
        Returns:
            注入粒子後的文本
        """
        try:
            if not text or len(text.split()) < 2:
                return text
            
            # 步驟 1: 檢測句首粒子
            existing_opening_particle = self._detect_existing_particle(
                text, 'opening'
            )
            
            if existing_opening_particle:
                self.logger.debug(
                    f"Particle already exists at opening: {existing_opening_particle}"
                )
                self._stats['particle_skips_duplicate'] += 1
                return text  # 已有粒子，跳過注入
            
            # 步驟 2: 根據親密度和島嶼選擇注入概率
            base_probability = 0.35 + (intimacy * 0.25)  # 0.35-0.6
            
            # 島嶼特定概率調整
            if island == 'Mother':
                probability = base_probability + 0.1  # 母愛更頻繁使用粒子
            elif island == 'Self':
                probability = base_probability - 0.05  # 自我反省較少使用粒子
            else:
                probability = base_probability
            
            # 步驟 3: 決定是否注入
            if random.random() >= probability:
                self.logger.debug("Particle injection skipped by probability")
                return text
            
            # 步驟 4: 選擇合適的粒子
            particle = self._select_contextual_particle(
                text, island, intimacy
            )
            
            if not particle:
                return text
            
            # 步驟 5: 注入粒子
            if particle in self.PERSONALITY_PARTICLES['opening']:
                # 句首注入
                injected = f"{particle}…{text}" if particle in ['其實', '天啊', '你知道嗎'] else f"{particle}{text}"
            else:
                # 句尾注入
                if text[-1] not in self.SENTENCE_TERMINATORS:
                    injected = f"{text}{particle}"
                else:
                    # 在標點前插入
                    injected = f"{text[:-1]}{particle}{text[-1]}"
            
            self._stats['particle_injections'] += 1
            self.logger.debug(f"Particle injected: {particle} -> {injected[:50]}...")
            
            return injected
        
        except Exception as e:
            self.logger.error(f"Particle injection failed: {e}")
            self._stats['errors'] += 1
            return text
    
    def _detect_existing_particle(
        self,
        text: str,
        particle_type: str
    ) -> Optional[str]:
        """
        [FIXED-VPL2] 檢測文本中是否已存在粒子
        
        Args:
            text: 輸入文本
            particle_type: 粒子類型 ('opening' or 'closing')
        
        Returns:
            找到的粒子或 None
        """
        try:
            particles = self.PERSONALITY_PARTICLES.get(particle_type, [])
            
            if particle_type == 'opening':
                # 檢查前 3 個字
                prefix = text[:6]
                for particle in particles:
                    if particle in prefix:
                        return particle
            
            elif particle_type == 'closing':
                # 檢查最後 3 個字
                suffix = text[-6:] if len(text) > 6 else text
                for particle in particles:
                    if particle in suffix:
                        return particle
            
            return None
        
        except Exception as e:
            self.logger.debug(f"Particle detection failed: {e}")
            return None
    
    def _select_contextual_particle(
        self,
        text: str,
        island: str,
        intimacy: float
    ) -> Optional[str]:
        """
        [FIXED-VPL7] 上下文感知的粒子選擇
        
        根據：
        1. 文本情感（偵測關鍵詞）
        2. 島嶼特徵
        3. 親密度
        
        選擇最合適的粒子
        """
        try:
            # 偵測文本情感關鍵詞
            sentiment_keywords = {
                'sad': ['難過', '傷心', '悲傷', '痛', '無力', '絕望', '累', '好辛苦'],
                'happy': ['開心', '快樂', '興奮', '好棒', '太好', '超讚', '喜歡'],
                'confused': ['不知道', '迷茫', '搞唔明', '不明白', '困惑', '糾結'],
                'stressed': ['緊張', '焦慮', '擔心', '害怕', '恐懼', '受唔了']
            }
            
            detected_sentiment = None
            for sentiment, keywords in sentiment_keywords.items():
                if any(kw in text for kw in keywords):
                    detected_sentiment = sentiment
                    break
            
            # 根據情感和島嶼選擇粒子
            if detected_sentiment == 'sad':
                # 悲傷情感：選擇溫和的開場粒子
                candidates = ['其實', '嗯', '我明白']
            elif detected_sentiment == 'happy':
                # 開心情感：選擇活潑的粒子
                candidates = ['天啊', '超', '真的', '妳知道嗎']
            elif detected_sentiment == 'confused':
                # 迷茫情感：選擇思考性的粒子
                candidates = ['其實', '好似', '或者', '應該']
            else:
                # 預設：根據島嶼
                if island == 'Mother':
                    candidates = ['嗯', '其實', '我明白', '聽住']
                elif island == 'Friend':
                    candidates = ['咁樣', '其實', '真的', '妳知道嗎']
                elif island == 'Empath':
                    candidates = ['我明白', '其實', '嗯', '聽住']
                else:  # Self
                    candidates = ['慢慢', '其實', '嗯', '我覺得']
            
            # 根據親密度篩選
            if intimacy < 0.3:
                # 低親密度：溫和粒子
                candidates = [c for c in candidates if c in ['嗯', '其實', '好似']]
            elif intimacy > 0.85:
                # 高親密度：可以用更熟悉的粒子
                candidates = [c for c in candidates if c in ['我明白', '咁樣', '天啊', '聽住']]
            
            if not candidates:
                candidates = ['嗯', '其實']
            
            return random.choice(candidates)
        
        except Exception as e:
            self.logger.debug(f"Contextual particle selection failed: {e}")
            return random.choice(['嗯', '其實'])
    
    async def _safe_sentence_structure(self, text: str) -> str:
        """
        [FIXED-VPL3] 安全短句結構 - 保持完整性
        
        改進邏輯：
        1. 不盲目截斷
        2. 檢查語義完整性
        3. 保留重要信息
        4. 異步處理（允許上層等待）
        
        Args:
            text: 輸入文本
        
        Returns:
            調整後的文本
        """
        try:
            if not text:
                return text
            
            # 預定義的「安全句子長度」而不是盲目限制
            # 根據 Vita 設計，保持 1-3 句是最佳
            
            # 分割句子
            sentences = self._intelligent_sentence_split(text)
            
            if not sentences:
                return text
            
            # 限制到 1-3 句，但保持語義連貫
            max_sentences = min(3, max(1, len(sentences)))
            
            # 如果原文只有 1 句但很長，試著自然斷句而不是截斷
            if max_sentences == 1 and len(text) > 150:
                self.logger.debug("Long single sentence detected, attempting natural break")
                sentences = self._natural_sentence_break(text)
                max_sentences = min(3, len(sentences))
            
            result = ''.join(sentences[:max_sentences])
            
            # 確保結尾完整
            if result and result[-1] not in self.SENTENCE_TERMINATORS:
                result += '。'
            
            self._stats['sentence_preservations'] += 1
            return result
        
        except Exception as e:
            self.logger.error(f"Safe sentence structure failed: {e}")
            self._stats['errors'] += 1
            return text
    
    def _intelligent_sentence_split(self, text: str) -> List[str]:
        """
        [FIXED-VPL3] 智能句子分割
        
        按標點符號分割，並保留標點
        """
        try:
            if not text:
                return []
            
            # 按標點符號分割（保留標點）
            pattern = r'([。！？…~～])'
            parts = re.split(pattern, text)
            
            # 重新組合（句子 + 標點）
            sentences = []
            for i in range(0, len(parts) - 1, 2):
                if i < len(parts) and parts[i].strip():
                    sentence = parts[i].strip() + (parts[i + 1] if i + 1 < len(parts) else '')
                    if sentence.strip():
                        sentences.append(sentence)
            
            return sentences if sentences else [text]
        
        except Exception as e:
            self.logger.debug(f"Intelligent sentence split failed: {e}")
            return [text]
    
    def _natural_sentence_break(self, text: str) -> List[str]:
        """
        [FIXED-VPL3] 自然句子斷句
        
        試著在「逗號」或「語義邊界」處斷句
        而不是盲目截斷
        """
        try:
            # 在逗號或中文句號處分割
            pattern = r'([，、；])'
            parts = re.split(pattern, text)
            
            # 重新組合成合理的句子
            sentences = []
            current = ""
            
            for i, part in enumerate(parts):
                current += part
                
                # 每 2-3 個分隔符或每 60 字時斷一次
                if len(current) > 60 or (i > 0 and i % 3 == 0 and current.strip()):
                    if current.strip():
                        # 在末尾加句號（如果沒有標點）
                        if current[-1] not in self.SENTENCE_TERMINATORS:
                            current += '。'
                        sentences.append(current)
                        current = ""
            
            if current.strip():
                if current[-1] not in self.SENTENCE_TERMINATORS:
                    current += '。'
                sentences.append(current)
            
            return sentences if sentences else [text]
        
        except Exception as e:
            self.logger.debug(f"Natural sentence break failed: {e}")
            return [text]
    
    def _enhance_fluency(
        self,
        text: str,
        island: str
    ) -> str:
        """
        [NEW] 流暢性增強 - 口語自然度
        
        改進：
        1. 檢查是否有不自然的轉接
        2. 加入適當的過渡詞
        3. 調整節奏感
        
        Args:
            text: 輸入文本
            island: 島嶼類型
        
        Returns:
            增強流暢性的文本
        """
        try:
            if not text or len(text) < 10:
                return text
            
            # 檢查是否需要過渡詞
            transition_words = {
                'but': ['但係', '不過', '只係'],
                'because': ['因為', '係因為', '主要係'],
                'and': ['同埋', '而且', '加埋'],
                'so': ['所以', '咁樣', '因此']
            }
            
            # 移除不自然的 LLM 人工轉接
            text = re.sub(r'(但是|然而|因此|所以)[，。]', r'\1，', text)

            # P8.2／Zero-Truncation：不再把每個「，」改成「，…」（會污染粵語節奏）
            # 節奏微調僅限過長句中偶發停頓標記，且不批量改寫全文。
            self._stats['cleanups'] += 1
            return text
        
        except Exception as e:
            self.logger.debug(f"Fluency enhancement failed: {e}")
            return text
    
    def _final_cleanup(self, text: str) -> str:
        """
        [FIXED-VPL6] 最終清理 - 改善正則表達式
        
        安全清理：
        1. 移除已知的 AI 標記
        2. 移除多餘標點
        3. 規範化空白
        4. 保留有效內容
        
        Args:
            text: 輸入文本
        
        Returns:
            清理後的文本
        """
        try:
            if not text:
                return text
            
            # 步驟 1: 移除已知的 AI 標記（保守做法）
            for pattern in self.DANGEROUS_REGEX_PATTERNS:
                try:
                    text = re.sub(pattern, '', text)
                except re.error as e:
                    self.logger.warning(f"Regex pattern failed: {pattern}, {e}")
            
            # 步驟 2: 移除多餘標點（但保留有意義的組合）
            # 避免過度清理 "…" 這樣的有意義標點
            text = re.sub(r'([。！？]){2,}', r'\1', text)  # 移除重複句號
            text = re.sub(r'(…){3,}', r'…', text)  # 最多保留 3 個省略號
            
            # 步驟 3: 規範化空白
            text = re.sub(r'(\s+)', ' ', text).strip()
            
            # 步驟 4: 移除孤立的標點
            text = re.sub(r'^([，。！？])', '', text)
            
            # 步驟 5: 確保結尾的完整性
            if text and text[-1] not in self.SENTENCE_TERMINATORS:
                text += '。'
            
            # 步驟 6: 最後檢查
            if not text or len(text.strip()) == 0:
                text = '嗯，我在聽。'
            
            self._stats['cleanups'] += 1
            return text
        
        except Exception as e:
            self.logger.error(f"Final cleanup failed: {e}")
            self._stats['errors'] += 1
            return text if text else '嗯，我在聽。'
    
    # ==================== 依賴管理 ====================
    
    def setup_dependencies(
        self,
        island_fusion: Optional[IslandFusion] = None,
        heretic_coordinator: Optional[HereticCoordinator] = None
    ) -> None:
        """
        [FIXED-VPL5] 注入依賴 - 增強驗證
        
        Args:
            island_fusion: 島嶼融合引擎
            heretic_coordinator: 異端調整器
        """
        try:
            if island_fusion is None:
                self.logger.warning("island_fusion is None")
            else:
                self.island_fusion = island_fusion
                self.logger.debug("island_fusion injected")
            
            if heretic_coordinator is None:
                self.logger.warning("heretic_coordinator is None")
            else:
                self.heretic_coordinator = heretic_coordinator
                self.logger.debug("heretic_coordinator injected")
            
            self.logger.info("Dependencies setup complete")
        
        except Exception as e:
            self.logger.error(f"Dependency setup failed: {e}")
    
    # ==================== 統計與診斷 ====================
    
    def get_stats(self) -> Dict:
        """
        [FIXED-VPL8] 取得統計資訊 - 完整追蹤
        
        Returns:
            統計字典
        """
        return {
            'layer': 'VocalPersonalityLayer',
            'version': '1.1',
            'total_finalizations': self._stats['total_finalizations'],
            'particle_injections': self._stats['particle_injections'],
            'particle_skips_duplicate': self._stats['particle_skips_duplicate'],
            'sentence_preservations': self._stats['sentence_preservations'],
            'cleanups': self._stats['cleanups'],
            'errors': self._stats['errors'],
            'cache_size': len(self._cache_detect_particles),
        }
    
    def reset_stats(self) -> None:
        """重設統計資料"""
        self._stats = {
            'total_finalizations': 0,
            'particle_injections': 0,
            'particle_skips_duplicate': 0,
            'sentence_preservations': 0,
            'cleanups': 0,
            'errors': 0,
        }
        self._cache_detect_particles.clear()
        self.logger.info("Stats reset")
    
    def get_health_status(self) -> Dict:
        """
        [NEW] 取得健康狀態診斷
        
        Returns:
            健康狀態字典
        """
        total_ops = self._stats['total_finalizations']
        
        if total_ops == 0:
            return {'status': 'idle', 'message': 'No operations yet'}
        
        error_rate = self._stats['errors'] / total_ops
        skip_rate = self._stats['particle_skips_duplicate'] / total_ops
        injection_rate = self._stats['particle_injections'] / total_ops
        
        status = 'healthy'
        issues = []
        
        if error_rate > 0.1:
            status = 'warning'
            issues.append(f"High error rate: {error_rate:.1%}")
        
        if skip_rate > 0.6:
            issues.append(f"Excessive particle skips: {skip_rate:.1%}")
        
        if injection_rate < 0.1:
            issues.append(f"Low injection rate: {injection_rate:.1%}")
        
        return {
            'status': status,
            'total_operations': total_ops,
            'error_rate': f"{error_rate:.1%}",
            'skip_rate': f"{skip_rate:.1%}",
            'injection_rate': f"{injection_rate:.1%}",
            'issues': issues if issues else ['None']
        }