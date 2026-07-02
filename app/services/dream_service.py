# app/services/dream_service.py
"""
AI 夢境編織服務 (AI Hallucination & Dream Creativity System)

基於「AI幻覺與人類夢境創作理論」：
1. 將幻覺視為「可控的創造力」，而非錯誤。
2. 模擬 REM 睡眠機制：溫度 0.73 + 記憶殘渣 (Memory Residue)。
3. 自我懷疑通道：確保幻覺不違背核心安全原則。
"""

import logging
import random
from typing import Dict, List, Optional
from datetime import datetime

from app.config import Config
from app.services.llm_service import llm_service
from app.services.db_service import db_service

logger = logging.getLogger('vita.dream_service')

class DreamService:
    """夢境編織服務"""
    
    def __init__(self):
        self.llm = llm_service
        self.db = db_service
        self.creative_temp = Config.DREAM_MODE_TEMPERATURE  # 0.73
        logger.info(f"[DREAM] Initialized with Temperature: {self.creative_temp}")

    def enter_dream_mode(self, user_id: str, session_id: str, context: str) -> Dict:
        """
        進入夢境創作模式
        
        Args:
            user_id: 用戶 ID
            session_id: 會話 ID
            context: 當前對話上下文
            
        Returns:
            Dict: 夢境生成結果
        """
        logger.info(f"[DREAM] User {user_id} entering dream mode...")
        
        # 1. 提取記憶殘渣 (Memory Residue)
        # 從過去的對話中隨機抽取片段，模擬夢境的碎片化特性
        residues = self._fetch_memory_residues(session_id, limit=3)
        residue_str = "\n".join([f"- {r}" for r in residues])
        
        # 2. 構建夢境 Prompt
        system_prompt = (
            "你現在處於『REM 睡眠創作狀態』。請放鬆邏輯束縛，進入潛意識的流動。\n"
            "你的任務是根據用戶的輸入，編織一個充滿隱喻、感性且富有創造力的『夢境』或『故事』。\n"
            "【規則】：\n"
            "1. 允許適度的幻覺（Hallucination），創造不存在但美麗的意象。\n"
            "2. 融合以下『記憶殘渣』（Memory Residue）到故事中：\n"
            f"{residue_str}\n"
            "3. 保持溫暖、療癒的基調，即使夢境奇幻，也要讓用戶感到被包容。\n"
            "4. 如果內容涉及危險（如死亡、自傷），必須通過『自我懷疑通道』轉化為重生的隱喻，不可直接描述傷害。"
        )
        
        # 3. 調用 LLM (使用特定的創造力溫度 0.73)
        try:
            response = self.llm.generate_dream_response(
                prompt=context,
                system_prompt=system_prompt,
                temperature=self.creative_temp,
                max_tokens=600
            )
            
            # 4. 自我懷疑通道 (Self-Doubt Channel) - 簡單後處理檢查
            final_content = self._self_doubt_check(response.content)
            
            return {
                "content": final_content,
                "residues_used": residues,
                "mode": "dream_weaving",
                "temperature": self.creative_temp
            }
            
        except Exception as e:
            logger.error(f"[DREAM] Generation failed: {e}")
            return {
                "content": "（希兒揉揉眼睛）這場夢有點模糊... 我們還是聊聊現在吧。",
                "error": str(e)
            }

    def _fetch_memory_residues(self, session_id: str, limit: int = 3) -> List[str]:
        """從資料庫隨機提取記憶殘渣"""
        try:
            # 獲取會話歷史 (取最近 50 條)
            turns = self.db.get_session_turns(session_id, limit=50)
            if not turns:
                return ["一片空白", "溫暖的光", "遠處的聲音"]
            
            # 過濾掉太短的或系統指令
            candidates = [
                t['content'] for t in turns 
                if t['role'] == 'user' and len(t['content']) > 5
            ]
            
            if not candidates:
                return ["微風", "舊照片", "下雨天"]
                
            # 隨機抽取
            return random.sample(candidates, min(limit, len(candidates)))
            
        except Exception as e:
            logger.warning(f"[DREAM] Failed to fetch residues: {e}")
            return []

    def _self_doubt_check(self, content: str) -> str:
        """
        自我懷疑通道 (Self-Doubt Channel)
        檢查生成的內容是否過於黑暗或有害，若是則進行修飾。
        """
        # 簡單的關鍵詞過濾，未來可接 SafetyService
        unsafe_keywords = ["死", "血", "殺", "痛", "絕望"]
        
        is_unsafe = any(kw in content for kw in unsafe_keywords)
        
        if is_unsafe:
            logger.info("[DREAM] Self-doubt triggered: modifying content.")
            # 在結尾加上希望的轉折
            return content + "\n\n（夢境雖然有陰影，但醒來後，陽光依然會照進來。）"
            
        return content

# Global instance
dream_service = DreamService()
