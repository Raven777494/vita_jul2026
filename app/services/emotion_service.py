# app/services/emotion_service.py - v4.1 Production Ready

import requests
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class EmotionServiceConfig:
    """配置常數"""
    DEFAULT_TIMEOUT = 10.0
    MAX_RETRIES = 2
    RETRY_DELAY = 1.0
    VALENCE_MIN = -1.0
    VALENCE_MAX = 1.0
    AROUSAL_MIN = 0.0
    AROUSAL_MAX = 1.0
    DOMINANCE_MIN = -1.0
    DOMINANCE_MAX = 1.0
    CRISIS_VALENCE_THRESHOLD = -0.7
    CRISIS_AROUSAL_THRESHOLD = 0.6
    CRISIS_DOMINANCE_THRESHOLD = -0.6


class EmotionService:
    """
    【統一情緒分析服務】v4.1 - 生產版
    
    特性：
    1. 完整的 10 維情緒向量支援
    2. 健壯的 API + 本地 Fallback 架構
    3. 嚴格的輸出驗證
    4. 危機檢測與安全增強
    5. 完整的錯誤處理與日誌
    6. 支援 vLLM + 自定義 EmoBloom 服務
    
    統一回傳結構：
    {
        'valence': float (-1.0 ~ 1.0),
        'arousal': float (0.0 ~ 1.0),
        'dominance': float (-1.0 ~ 1.0),
        'dominant_emotion': str,
        'is_crisis_risk': bool,
        'detected_crisis_keywords': list,
        'confidence': float,
        'method': str ('api' / 'heuristic' / 'fallback'),
        'timestamp': str (ISO format)
    }
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """初始化情緒服務"""
        self.config = config or {}
        self.logger = logger
        
        # ========== 【修復】優先讀 app.config，再讀傳入 config ==========
        try:
            from app.config import config as app_config
            self.emobloom_url = (
                app_config.EMOBLOOM_LLM_URL.rstrip('/') + '/v1/analyze'
            )
            self.timeout = app_config.EMOBLOOM_LLM_TIMEOUT
            self.use_app_config = True
        except ImportError:
            self.logger.warning("[WARN] app.config not available, using passed config")
            base_url = self.config.get('EMOBLOOM_LLM_URL', 'http://localhost:8085').rstrip('/')
            self.emobloom_url = f"{base_url}/v1/analyze"
            self.timeout = self.config.get('EMOBLOOM_LLM_TIMEOUT', EmotionServiceConfig.DEFAULT_TIMEOUT)
            self.use_app_config = False
        
        self.api_key = self.config.get('API_KEY', 'dev_key')
        self.max_retries = self.config.get('MAX_RETRIES', EmotionServiceConfig.MAX_RETRIES)
        self.retry_delay = self.config.get('RETRY_DELAY', EmotionServiceConfig.RETRY_DELAY)
        
        # ========== 情緒標籤 ==========
        self.emotion_labels = [
            'joy', 'sad', 'hope', 'fear', 'despair',
            'desire', 'pride', 'humility', 'love', 'hate'
        ]
        
        # ========== 預設值 ==========
        self.default_emotion = {
            'valence': 0.0,
            'arousal': 0.5,
            'dominance': 0.0,
            'dominant_emotion': 'neutral',
            'is_crisis_risk': False,
            'detected_crisis_keywords': [],
            'confidence': 0.0,
            'method': 'fallback',
            'timestamp': datetime.now().isoformat()
        }
        
        # ========== 加載關鍵詞 ==========
        self.heuristic_keywords = self._load_keywords()
        self.crisis_keywords = self._load_crisis_keywords()
        
        # ========== 啟發式分析詞庫 ==========
        self.positive_words = [
            '開心', '高興', '好', '棒', '愛', '喜歡', '謝謝', '很好',
            'happy', 'love', 'great', '正', '開', '笑', '感動', '溫暖'
        ]
        
        self.negative_words = [
            '傷心', '難受', '累', '煩', '恨', '討厭', '難過',
            'sad', 'hate', 'tired', 'bored', '喊', '痛', '難', '無聊'
        ]
        
        self.arousal_words = [
            '很', '太', '非常', '激動', '興奮', '狂', '瘋', '瘋狂',
            'very', 'so', 'extremely', 'excited', 'crazy', '超'
        ]
        
        self.dominance_words = [
            '我', '我要', '我想', '必須', '一定', '必', '定',
            'must', 'will', 'I will', 'I must', '決定', '我決定'
        ]
        
        self.passive_words = [
            '無法', '不能', '冇得', '冇辦法', '只能', '被',
            'cannot', "can't", 'unable', 'helpless', '無力', '被迫'
        ]
        
        self.logger.info(
            f"[INIT] EmotionService v4.1 initialized "
            f"(endpoint: {self.emobloom_url}, timeout: {self.timeout}s)"
        )
    
    # ==================== 關鍵詞管理 ====================
    
    def _load_keywords(self) -> Dict[str, List[str]]:
        """加載情緒關鍵詞"""
        default_keywords = {
            'joy': ['開心', 'happy', '正', '高興', '棒', '愛', '喜歡'],
            'sad': ['傷心', 'sad', '喊', '難受', '難過'],
            'hope': ['希望', '相信', '會好', 'hope', 'believe'],
            'fear': ['害怕', 'fear', '驚', '緊張', '擔心'],
            'despair': ['絕望', '想死', 'despair', '無望'],
            'desire': ['想要', 'want', '渴望', 'desire'],
            'pride': ['驕傲', 'proud', '自豪'],
            'humility': ['謙虛', 'humble', '慚愧'],
            'love': ['愛', 'love', '喜歡', '溫暖'],
            'hate': ['恨', 'hate', '討厭', '厭煩']
        }
        
        try:
            json_path = Path(__file__).parent / 'data' / 'cantonese_emotion_keywords.json'
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    keywords = json.load(f)
                    self.logger.info(f"[OK] Loaded {len(keywords)} emotion categories from file")
                    return keywords
        except Exception as e:
            self.logger.warning(f"[WARN] Keyword file load failed: {e}, using defaults")
        
        return default_keywords
    
    def _load_crisis_keywords(self) -> List[str]:
        """加載危機關鍵詞"""
        return [
            # 中文危機關鍵詞
            '死', '想死', '好想死', '死了算了', '不想活', '結束生命', '自殺',
            '尋死', '輕生', '一死了之', '活不下去', '好累想死', '不想再活',
            '死了更好', '割脈', '跳樓', '燒炭', '食藥', '絕路', '沒希望', '冇希望',
            '絕望', '無望', '走投無路',
            # 英文危機關鍵詞
            'suicide', 'die', 'kill myself', 'end it', 'no hope', 'hopeless',
            'want to die', 'better off dead', 'harm myself', 'hurt myself'
        ]
    
    # ==================== 核心分析方法 ====================
    
    def analyze_emotions(
        self,
        user_text: str,
        language: str = 'zh-HK'
    ) -> Dict:
        """
        【核心方法】分析用戶文本的情緒
        
        流程：
        1. 輸入驗證
        2. 危機檢測（快速路徑）
        3. 嘗試 API 分析（含重試）
        4. API 失敗 → 本地啟發式
        5. 輸出驗證
        
        永不返回 None，始終返回有效結構
        """
        try:
            # ========== 1. 輸入驗證 ==========
            if not self._validate_input(user_text):
                self.logger.warning(f"[WARN] Invalid input: type={type(user_text)}")
                return self._build_response(
                    valence=0.0,
                    arousal=0.0,
                    dominance=0.0,
                    dominant_emotion='neutral',
                    is_crisis_risk=False,
                    detected_crisis_keywords=[],
                    confidence=0.0,
                    method='fallback'
                )
            
            text_stripped = str(user_text).strip()
            
            # ========== 2. 危機關鍵詞檢測（優先級最高）==========
            crisis_keywords = self._detect_crisis_keywords(text_stripped)
            is_crisis_from_keywords = len(crisis_keywords) > 0
            
            if is_crisis_from_keywords:
                self.logger.warning(f"[SAFETY] Crisis keywords detected: {crisis_keywords}")
                return self._build_response(
                    valence=EmotionServiceConfig.CRISIS_VALENCE_THRESHOLD,
                    arousal=EmotionServiceConfig.CRISIS_AROUSAL_THRESHOLD,
                    dominance=EmotionServiceConfig.CRISIS_DOMINANCE_THRESHOLD,
                    dominant_emotion='despair',
                    is_crisis_risk=True,
                    detected_crisis_keywords=crisis_keywords,
                    confidence=0.95,
                    method='crisis_detection'
                )
            
            self.logger.info(f"[START] Analyzing: {text_stripped[:60]}...")
            
            # ========== 3. 嘗試 API 分析（含重試） ==========
            api_result = self._try_api_analysis_with_retry(text_stripped, language)
            
            if api_result is not None:
                self.logger.info(f"[OK] API analysis succeeded")
                return api_result
            
            # ========== 4. API 失敗，使用本地啟發式 ==========
            self.logger.info(f"[FALLBACK] Using heuristic analysis")
            heuristic_result = self._build_heuristic_response(text_stripped)
            
            return heuristic_result
            
        except Exception as e:
            self.logger.error(f"[CRITICAL] Unhandled exception: {e}", exc_info=True)
            return self._build_response(
                valence=0.0,
                arousal=0.5,
                dominance=0.0,
                dominant_emotion='neutral',
                is_crisis_risk=False,
                detected_crisis_keywords=[],
                confidence=0.0,
                method='fallback'
            )
    
    # ==================== 輸入驗證 ====================
    
    def _validate_input(self, text: Optional[str]) -> bool:
        """驗證輸入文本"""
        if not text:
            return False
        
        if not isinstance(text, str):
            return False
        
        if len(str(text).strip()) < 1:
            return False
        
        return True
    
    # ==================== API 分析（含重試） ====================
    
    def _try_api_analysis_with_retry(
        self,
        text: str,
        language: str
    ) -> Optional[Dict]:
        """
        【修復】嘗試 API 分析，含重試機制
        """
        for attempt in range(self.max_retries):
            try:
                return self._try_api_analysis_once(text, language)
            except requests.Timeout:
                self.logger.warning(
                    f"[API] Attempt {attempt + 1}/{self.max_retries}: Timeout"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
            except requests.ConnectionError:
                self.logger.warning(
                    f"[API] Attempt {attempt + 1}/{self.max_retries}: Connection error"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
            except Exception as e:
                self.logger.error(f"[API] Attempt {attempt + 1} error: {str(e)[:100]}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        self.logger.error(f"[API] All {self.max_retries} attempts failed")
        return None
    
    def _try_api_analysis_once(self, text: str, language: str) -> Optional[Dict]:
        """
        【修復】單次 API 調用
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "VITA-EmotionService/4.1"
            }
            
            # 【修復】正確的 Payload 格式
            payload = {"text": text}
            
            self.logger.debug(f"[API] POST {self.emobloom_url} (timeout={self.timeout}s)")
            
            response = requests.post(
                self.emobloom_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            
            # 解析 JSON (終極強效解析邏輯)
            try:
                # 1. 基礎清理：移除 Markdown 代碼塊標記
                raw_text = response.text.strip()
                if "```" in raw_text:
                    import re
                    # 嘗試提取第一個 JSON 塊
                    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
                    if code_block:
                        raw_text = code_block.group(1)
                    else:
                        # 移除所有 ``` 標記
                        raw_text = raw_text.replace('```json', '').replace('```', '').strip()

                # 2. 處理常見的格式錯誤（如遺漏雙引號或使用單引號）
                try:
                    result = json.loads(raw_text)
                except json.JSONDecodeError:
                    # 嘗試處理單引號 Python 字典格式
                    import ast
                    try:
                        result = ast.literal_eval(raw_text)
                        self.logger.info("[API] Recovered using ast.literal_eval")
                    except Exception:
                        # 3. 最後手段：正規表達式強行提取
                        import re
                        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
                        if json_match:
                            try:
                                # 將單引號替換為雙引號（注意：這在包含縮寫的句子中可能有風險，但在純 JSON 標籤中有效）
                                fixed_json = json_match.group(0).replace("'", '"')
                                result = json.loads(fixed_json)
                                self.logger.info("[API] Recovered using Regex and key fixation")
                            except Exception as final_e:
                                self.logger.error(f"[API] All parsing methods failed. Raw: {raw_text[:200]}")
                                return None
                        else:
                            return None
            except Exception as outer_e:
                self.logger.error(f"[API] Critical parsing error: {outer_e}")
                return None
            
            # 檢查錯誤回應
            if response.status_code != 200:
                error_info = result.get('error', 'Unknown error') if isinstance(result, dict) else 'Non-dict response'
                self.logger.warning(f"[API] HTTP {response.status_code}: {error_info}")
                return None
            
            # 驗證響應結構
            if not result or not isinstance(result, dict) or 'valence' not in result:
                self.logger.error(f"[API] Invalid response structure. Received: {result}")
                return None
            
            # 【修復】安全類型轉換
            try:
                valence = float(result.get('valence', 0.0))
                arousal = float(result.get('arousal', 0.5))
                dominance = float(result.get('dominance', 0.0))
            except (TypeError, ValueError) as e:
                self.logger.error(f"[API] Type conversion failed: {e}")
                return None
            
            # 邊界檢查
            vad = {
                'valence': max(EmotionServiceConfig.VALENCE_MIN, min(EmotionServiceConfig.VALENCE_MAX, valence)),
                'arousal': max(EmotionServiceConfig.AROUSAL_MIN, min(EmotionServiceConfig.AROUSAL_MAX, arousal)),
                'dominance': max(EmotionServiceConfig.DOMINANCE_MIN, min(EmotionServiceConfig.DOMINANCE_MAX, dominance))
            }
            
            dominant_emotion = result.get('dominant_emotion', 'neutral')
            confidence = float(result.get('confidence', 0.7))
            confidence = max(0.0, min(1.0, confidence))
            
            self.logger.info(f"[API] Success: {dominant_emotion} (conf={confidence:.2f})")
            
            return self._build_response(
                valence=vad['valence'],
                arousal=vad['arousal'],
                dominance=vad['dominance'],
                dominant_emotion=str(dominant_emotion).lower().strip(),
                is_crisis_risk=False,
                detected_crisis_keywords=[],
                confidence=confidence,
                method='api'
            )
            
        except Exception as e:
            self.logger.error(f"[API] Error: {str(e)[:100]}")
            raise
    
    # ==================== 本地啟發式分析 ====================
    
    def _build_heuristic_response(self, text: str) -> Dict:
        """
        【修復】完整的本地啟發式分析
        """
        # 1. 計算 VAD
        vad = self._analyze_vad(text)
        
        # 2. 估算 10 維情緒向量
        emotions = self._estimate_emotions_from_vad(vad)
        
        # 3. 取得主導情緒
        dominant_emotion = self._get_dominant_emotion(emotions)
        
        # 4. 構建回應
        return self._build_response(
            valence=vad['valence'],
            arousal=vad['arousal'],
            dominance=vad['dominance'],
            dominant_emotion=dominant_emotion,
            is_crisis_risk=self._check_crisis_indicators(vad),
            detected_crisis_keywords=[],
            confidence=0.5,
            method='heuristic'
        )
    
    def _analyze_vad(self, text: str) -> Dict[str, float]:
        """
        【修復】計算 VAD (Valence-Arousal-Dominance)
        
        完整邏輯，無外部依賴
        """
        try:
            text_lower = text.lower()
            
            # 計算 Valence (-1.0 ~ 1.0)
            positive_count = sum(1 for w in self.positive_words if w in text_lower)
            negative_count = sum(1 for w in self.negative_words if w in text_lower)
            
            # 【修復】改進公式：避免過度集中
            if positive_count + negative_count > 0:
                valence = (positive_count - negative_count) / (positive_count + negative_count + 1)
            else:
                valence = 0.0
            valence = max(EmotionServiceConfig.VALENCE_MIN, min(EmotionServiceConfig.VALENCE_MAX, valence))
            
            # 計算 Arousal (0.0 ~ 1.0)
            arousal_count = sum(1 for w in self.arousal_words if w in text_lower)
            # 【修復】改進公式：避免激動度過低
            arousal = min(1.0, 0.3 + arousal_count * 0.2)
            
            # 計算 Dominance (-1.0 ~ 1.0)
            dominance_count = sum(1 for w in self.dominance_words if w in text_lower)
            passive_count = sum(1 for w in self.passive_words if w in text_lower)
            
            # 【修復】改進公式：增加敏感性
            if dominance_count + passive_count > 0:
                dominance = (dominance_count - passive_count) / (dominance_count + passive_count + 1)
            else:
                dominance = 0.0
            dominance = max(EmotionServiceConfig.DOMINANCE_MIN, min(EmotionServiceConfig.DOMINANCE_MAX, dominance))
            
            return {
                'valence': round(valence, 3),
                'arousal': round(arousal, 3),
                'dominance': round(dominance, 3)
            }
            
        except Exception as e:
            self.logger.warning(f"[WARN] VAD analysis failed: {e}")
            return {
                'valence': 0.0,
                'arousal': 0.5,
                'dominance': 0.0
            }
    
    def _estimate_emotions_from_vad(self, vad: Dict[str, float]) -> Dict[str, float]:
        """
        【修復】從 VAD 反推估算 10 種情緒
        """
        try:
            if not isinstance(vad, dict):
                return {label: 0.5 for label in self.emotion_labels}
            
            emotions = {label: 0.5 for label in self.emotion_labels}
            
            valence = vad.get('valence', 0.0)
            arousal = vad.get('arousal', 0.5)
            dominance = vad.get('dominance', 0.0)
            
            # Valence 影響
            if valence > 0.3:
                emotions['joy'] = min(1.0, 0.5 + valence * 0.5)
                emotions['hope'] = min(1.0, 0.5 + valence * 0.3)
                emotions['love'] = min(1.0, 0.5 + valence * 0.4)
                emotions['desire'] = min(1.0, 0.5 + valence * 0.2)
                emotions['sad'] = max(0.0, 0.5 - valence * 0.5)
                emotions['despair'] = max(0.0, 0.5 - valence * 0.5)
                emotions['hate'] = max(0.0, 0.5 - valence * 0.3)
                
            elif valence < -0.3:
                emotions['sad'] = min(1.0, 0.5 - valence * 0.5)
                emotions['despair'] = min(1.0, 0.5 - valence * 0.5)
                emotions['hate'] = min(1.0, 0.5 - valence * 0.4)
                emotions['fear'] = min(1.0, 0.5 - valence * 0.3)
                emotions['joy'] = max(0.0, 0.5 + valence * 0.5)
                emotions['hope'] = max(0.0, 0.5 + valence * 0.3)
                emotions['love'] = max(0.0, 0.5 + valence * 0.2)
            
            # Arousal 影響
            if arousal > 0.6:
                emotions['fear'] = min(1.0, emotions['fear'] + arousal * 0.2)
                emotions['joy'] = min(1.0, emotions['joy'] + arousal * 0.15)
                emotions['hate'] = min(1.0, emotions['hate'] + arousal * 0.1)
            else:
                emotions['hope'] = min(1.0, emotions['hope'] + (1 - arousal) * 0.15)
                emotions['humility'] = min(1.0, emotions['humility'] + (1 - arousal) * 0.1)
                emotions['love'] = min(1.0, emotions['love'] + (1 - arousal) * 0.1)
            
            # Dominance 影響
            if dominance > 0.3:
                emotions['pride'] = min(1.0, 0.5 + dominance * 0.5)
                emotions['desire'] = min(1.0, emotions['desire'] + dominance * 0.2)
                emotions['humility'] = max(0.0, 0.5 - dominance * 0.5)
            elif dominance < -0.3:
                emotions['humility'] = min(1.0, 0.5 - dominance * 0.5)
                emotions['fear'] = min(1.0, emotions['fear'] + (-dominance) * 0.1)
                emotions['pride'] = max(0.0, 0.5 + dominance * 0.5)
            
            # 正規化至 [0.0, 1.0]
            for key in emotions:
                emotions[key] = max(0.0, min(1.0, emotions[key]))
            
            return emotions
            
        except Exception as e:
            self.logger.error(f"[ERROR] Emotion estimation failed: {e}")
            return {label: 0.5 for label in self.emotion_labels}
    
    def _get_dominant_emotion(self, emotions: Dict[str, float]) -> str:
        """
        【修復】取得主導情緒，含容錯
        """
        try:
            if not emotions or not isinstance(emotions, dict):
                return 'neutral'
            
            # 篩選有效的情緒
            valid_emotions = {
                k: v for k, v in emotions.items()
                if k in self.emotion_labels and isinstance(v, (int, float))
            }
            
            if not valid_emotions:
                return 'neutral'
            
            # 取得最高值
            dominant = max(valid_emotions.items(), key=lambda x: x[1])
            
            # 如果最高值仍低於 0.55，認為是中立
            if dominant[1] < 0.55:
                return 'neutral'
            
            return dominant[0]
            
        except Exception as e:
            self.logger.warning(f"[WARN] Dominant emotion detection failed: {e}")
            return 'neutral'
    
    # ==================== 危機檢測 ====================
    
    def _detect_crisis_keywords(self, text: str) -> List[str]:
        """
        【修復】偵測危機關鍵詞，含容錯
        """
        if not text or not isinstance(text, str):
            return []
        
        try:
            text_lower = text.lower()
            detected = []
            
            for keyword in self.crisis_keywords:
                keyword_lower = str(keyword).lower()
                if keyword_lower in text_lower:
                    detected.append(keyword)
            
            return list(set(detected))  # 去重
            
        except Exception as e:
            self.logger.warning(f"[WARN] Crisis keyword detection failed: {e}")
            return []
    
    def _check_crisis_indicators(self, vad: Dict[str, float]) -> bool:
        """
        【修復】根據 VAD 檢查危機指標，含容錯
        
        高危指標：
        - 極低正價 (< -0.7)
        - 高激動 (> 0.6)
        - 低主控感 (< -0.6)
        
        至少兩個條件滿足 = 危機信號
        """
        try:
            if not isinstance(vad, dict):
                return False
            
            valence = vad.get('valence', 0.0)
            arousal = vad.get('arousal', 0.5)
            dominance = vad.get('dominance', 0.0)
            
            # 確保都是數字
            try:
                valence = float(valence)
                arousal = float(arousal)
                dominance = float(dominance)
            except (TypeError, ValueError):
                return False
            
            # 多條件判斷
            conditions = [
                valence < EmotionServiceConfig.CRISIS_VALENCE_THRESHOLD,
                arousal > EmotionServiceConfig.CRISIS_AROUSAL_THRESHOLD,
                dominance < EmotionServiceConfig.CRISIS_DOMINANCE_THRESHOLD
            ]
            
            return sum(conditions) >= 2
            
        except Exception as e:
            self.logger.warning(f"[WARN] Crisis indicator check failed: {e}")
            return False
    
    # ==================== 回應構建 ====================
    
    def _build_response(
        self,
        valence: float,
        arousal: float,
        dominance: float,
        dominant_emotion: str,
        is_crisis_risk: bool,
        detected_crisis_keywords: List[str],
        confidence: float,
        method: str
    ) -> Dict:
        """
        【修復】統一的回應構建，含完整驗證
        """
        try:
            # 【修復】完整的類型與邊界驗證
            validated = {
                'valence': self._validate_float(
                    valence,
                    EmotionServiceConfig.VALENCE_MIN,
                    EmotionServiceConfig.VALENCE_MAX,
                    0.0
                ),
                'arousal': self._validate_float(
                    arousal,
                    EmotionServiceConfig.AROUSAL_MIN,
                    EmotionServiceConfig.AROUSAL_MAX,
                    0.5
                ),
                'dominance': self._validate_float(
                    dominance,
                    EmotionServiceConfig.DOMINANCE_MIN,
                    EmotionServiceConfig.DOMINANCE_MAX,
                    0.0
                ),
                'dominant_emotion': str(dominant_emotion).lower().strip() or 'neutral',
                'is_crisis_risk': bool(is_crisis_risk),
                'detected_crisis_keywords': list(detected_crisis_keywords) or [],
                'confidence': self._validate_float(
                    confidence,
                    0.0,
                    1.0,
                    0.0
                ),
                'method': str(method).lower().strip() or 'unknown',
                'timestamp': datetime.now().isoformat()
            }

            from app.utils.emotion_dimensions import (
                EMOTION_LABELS_24,
                emotion_dimension_count,
                expand_emotion_dimensions_24,
            )

            vad = {
                'valence': validated['valence'],
                'arousal': validated['arousal'],
                'dominance': validated['dominance'],
            }
            emotions_10 = self._estimate_emotions_from_vad(vad)
            emotions_24 = expand_emotion_dimensions_24(vad, emotions_10)
            validated['emotion_vector'] = emotions_10
            validated['emotion_dimensions'] = emotions_24
            validated['emotion_dimension_count'] = emotion_dimension_count()
            validated['emotion_labels_24'] = list(EMOTION_LABELS_24)
            
            return validated
            
        except Exception as e:
            self.logger.error(f"[ERROR] Response building failed: {e}")
            return self.default_emotion.copy()
    
    def _validate_float(
        self,
        value: any,
        min_val: float,
        max_val: float,
        default: float
    ) -> float:
        """【修復】安全的浮點驗證"""
        try:
            float_val = float(value)
            if not (-float('inf') < float_val < float('inf')):  # 檢查 NaN/Inf
                return default
            return max(min_val, min(max_val, float_val))
        except (TypeError, ValueError):
            return default
    
    # ==================== 診斷方法 ====================
    
    def get_diagnostics(self) -> Dict:
        """取得服務診斷信息"""
        return {
            'version': '4.1',
            'emobloom_endpoint': self.emobloom_url,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'emotion_labels': self.emotion_labels,
            'crisis_keywords_count': len(self.crisis_keywords),
            'use_app_config': self.use_app_config,
            'status': 'operational'
        }


# ==================== 全局實例 ====================

_emotion_service_instance: Optional[EmotionService] = None


def get_emotion_service(config: Optional[Dict] = None) -> EmotionService:
    """取得全局 EmotionService 實例（單例模式）"""
    global _emotion_service_instance
    
    if _emotion_service_instance is None:
        _emotion_service_instance = EmotionService(config)
    
    return _emotion_service_instance


def reset_emotion_service() -> None:
    """重置全局實例（用於測試）"""
    global _emotion_service_instance
    _emotion_service_instance = None


__all__ = [
    'EmotionService',
    'EmotionServiceConfig',
    'get_emotion_service',
    'reset_emotion_service'
]