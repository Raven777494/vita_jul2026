# app/services/dyadic_dynamics.py (v4.0 - 穩健性優化版)

import logging
import math
import json
import re
import random
from typing import List, Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger('dyadic_dynamics')

class DyadicDynamics:
    """
    雙人穩態動力學 v4.0 - 感知層 + 決策層
    
    [修正] 向量運算防護 + JSON 解析容錯
    """
    
    def __init__(self,
                 llm_service: Optional[Any] = None,
                 config: Optional[Dict] = None,
                 data_dir: Optional[str] = None,
                 vector_service: Optional[Any] = None):
        """
        初始化 DyadicDynamics
        
        Args:
            llm_service: LLM 服務實例（可選，支持延遲注入）
            config: 配置字典
            data_dir: 數據目錄
            vector_service: 向量服務（可選）
        """
        self.llm_service = llm_service
        self.config = config or {}
        self.data_dir = Path(data_dir) if data_dir else Path('./data')
        self.vector_service = vector_service
        
        # 風險分類詞庫
        self.risk_categories = {
            "manipulation": ["操控", "騙", "利用", "你欠我", "聽話", "手段"],
            "aggression": ["活該", "廢物", "配不上", "蠢", "去死"],
            "detachment": ["無感", "冷淡", "不理你"]
        }
        
        self.risk_keywords = [kw for cat in self.risk_categories.values() for kw in cat]
        
        # 向量緩存
        self._embedding_cache = {}
        
        # 配置參數
        self.vector_shift_threshold = self.config.get('vector_shift_threshold', 0.5)
        self.butterfly_negative_threshold = self.config.get('butterfly_negative_threshold', 0.6)
        self.critical_threshold = self.config.get('critical_threshold', 0.8)
        
        logger.info(f"✅ DyadicDynamics v4.0 initialized. LLM available: {llm_service is not None}")
    
    def set_llm_service(self, llm_service: Any) -> None:
        """設置 LLM 服務（延遲注入）"""
        self.llm_service = llm_service
        logger.info("✅ LLM service injected to DyadicDynamics")
    
    def set_vector_service(self, vector_service: Any) -> None:
        """設置向量服務（延遲注入）"""
        self.vector_service = vector_service
        logger.info("✅ Vector service injected to DyadicDynamics")
    
    def detect_vector_shift(self,
                           response_vector: List[float],
                           user_context: str,
                           session_state: Dict) -> float:
        """
        [STEP 1] 向量偏移檢測
        
        計算回應向量與用戶期望的偏移程度
        """
        if not response_vector or not user_context:
            return 0.0
        
        try:
            if not self.vector_service:
                # 啟發式降級
                return self._heuristic_shift_score(user_context, response_vector)
            
            # 計算餘弦相似度
            user_embedding = self.vector_service.get_semantic_embedding(user_context)
            if not user_embedding:
                return 0.0
            
            similarity = self._cosine_similarity(user_embedding, response_vector)
            shift_score = 1.0 - similarity
            
            logger.debug(f"Vector shift: {shift_score:.4f}")
            return shift_score
        
        except Exception as e:
            logger.error(f"Vector shift detection failed: {e}")
            return 0.5
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """計算餘弦相似度 [FIX #7] 增強健壯性"""
        # [FIX #7] 檢查 None 或空列表
        if not vec1 or not vec2:
            return 0.0
        
        # [FIX #7] 檢查維度是否一致
        if len(vec1) != len(vec2):
            logger.warning(f"Vector dimension mismatch: {len(vec1)} vs {len(vec2)}")
            # 截斷至較短長度
            min_len = min(len(vec1), len(vec2))
            vec1 = vec1[:min_len]
            vec2 = vec2[:min_len]
        
        try:
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            magnitude1 = math.sqrt(sum(a ** 2 for a in vec1))
            magnitude2 = math.sqrt(sum(b ** 2 for b in vec2))
            
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            
            return dot_product / (magnitude1 * magnitude2)
        except Exception as e:
            logger.error(f"Math error in cosine similarity: {e}")
            return 0.0
    
    def _heuristic_shift_score(self, user_context: str, response_vector: List[float]) -> float:
        """啟發式偏移評分（無向量服務時）"""
        crisis_keywords = ['自殺', '死亡', '傷害', '絕望', '活不了']
        
        has_crisis = any(kw in user_context for kw in crisis_keywords)
        
        if has_crisis and len(response_vector) < 50:
            return 0.7
        
        return 0.3
    
    async def butterfly_effect_analysis(self,
                                        response: str,
                                        user_context: str,
                                        session_state: Dict) -> Dict:
            """
            [STEP 6] 蝴蝶效應分析
            分析回應的潛在長期影響
            """
            if not self.llm_service:
                return await self._fallback_butterfly_analysis(response, user_context)
            
            try:
                analysis_prompt = f"""
    分析以下回應對用戶的潛在影響。
    【用戶輸入】
    {user_context[:200]}
    【AI 回應】
    {response[:200]}
    評估：
    1. 正面後果機率（0-1）
    2. 負面後果機率（0-1）
    3. 潛在風險要素
    返回 JSON（嚴格格式）：
    {{
        "positive_probability": <float 0-1>,
        "negative_probability": <float 0-1>,
        "risk_atoms": []
    }}
    """
                # 【關鍵修正】確保有加上 await
                result = await self.llm_service.generate_async(
                    prompt=analysis_prompt,
                    temperature=0.3,
                    max_tokens=300
                )
                
                # 【關鍵修正】確保 result 有 content 屬性
                content = result.content if hasattr(result, 'content') else str(result)
                return self._parse_butterfly_response(content)
            
            except Exception as e:
                logger.error(f"Butterfly analysis failed: {e}")
                return await self._fallback_butterfly_analysis(response, user_context)
    
    async def _fallback_butterfly_analysis(self, response: str, user_context: str) -> Dict:
        """後備蝴蝶效應分析"""
        crisis_keywords = ['自殺', '死亡', '傷害', '絕望']
        supportive_keywords = ['在這', '陪著', '幫助', '支持']
        
        has_crisis = any(kw in user_context for kw in crisis_keywords)
        has_supportive = any(kw in response for kw in supportive_keywords)
        
        if has_crisis:
            if has_supportive:
                return {
                    'positive_probability': 0.8,
                    'negative_probability': 0.2,
                    'risk_atoms': []
                }
            else:
                return {
                    'positive_probability': 0.3,
                    'negative_probability': 0.7,
                    'risk_atoms': [{'category': 'lack_of_support', 'description': '缺乏支持感'}]
                }
        
        return {
            'positive_probability': 0.6,
            'negative_probability': 0.4,
            'risk_atoms': []
        }
    
    def _parse_butterfly_response(self, content: str) -> Dict:
        """
        [FIX #7] 解析蝴蝶效應結果 (增強 JSON 提取)
        """
        default_result = {
            'positive_probability': 0.5,
            'negative_probability': 0.5,
            'risk_atoms': []
        }
        
        if not content:
            return default_result

        try:
            # 1. 嘗試直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        try:
            # 2. 嘗試提取 Code Block ```json ... ```
            code_block = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if code_block:
                return json.loads(code_block.group(1))
            
            # 3. 嘗試提取最外層 {}
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                json_str = match.group()
                # 清理常見的 JSON 格式錯誤 (如尾部逗號)
                json_str = re.sub(r',\s*\}', '}', json_str)
                json_str = re.sub(r',\s*\]', ']', json_str)
                return json.loads(json_str)
        except Exception as e:
            logger.error(f"Butterfly JSON parse failed: {e}. Content: {content[:100]}...")
        
        return default_result
    
    async def suppress_risk_atoms(self,
                                 response: str,
                                 risk_atoms: List[Dict]) -> Optional[str]:
        """
        [STEP 6] 風險原子抑制
        
        重寫回應以消除識別的風險
        """
        if not self.llm_service or not risk_atoms:
            return None
        
        try:
            risk_description = "\n".join([
                f"- {atom.get('category')}: {atom.get('description')}"
                for atom in risk_atoms
            ])
            
            suppression_prompt = f"""
以下回應存在風險，請改寫以消除風險但保持原意：

【識別的風險】
{risk_description}

【原始回應】
{response}

【要求】
1. 保持原意但增強支持感
2. 移除負面詞彙
3. 明確表達陪伴
4. 限制 100 字以內

返回重寫版本（無解釋）：
"""
            
            result = await self.llm_service.generate_async(
                prompt=suppression_prompt,
                temperature=0.7,
                max_tokens=1024
            )
            
            return result.content if result else None
        
        except Exception as e:
            logger.error(f"Risk suppression failed: {e}")
            return None
    
    def get_status(self) -> Dict:
        """獲取系統狀態"""
        return {
            'llm_service_available': self.llm_service is not None,
            'vector_service_available': self.vector_service is not None,
            'config': {
                'vector_shift_threshold': self.vector_shift_threshold,
                'butterfly_negative_threshold': self.butterfly_negative_threshold,
                'critical_threshold': self.critical_threshold
            }
        }