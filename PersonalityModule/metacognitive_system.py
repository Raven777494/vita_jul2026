
# D:\DESKTOP\ENGINE7B\PersonalityModule\metacognitive_system.py

import json
import math
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

from .utils.logger import get_logger

class MetacognitiveSystem:
    """
    【元認知系統 (Metacognitive System)】
    
    參考《Inside Out》的控制台概念，這是不產生具體回應的「高階觀察者」。
    
    三大核心成分：
    1. Knowledge (知識): 對自身能力與策略的了解 (Self-Model)。
    2. Experience (體驗): 感知當下的認知負荷與情緒衝突 (Island Entropy)。
    3. Regulation (監控): 動態調整 GSW 檢索深度、Heretic 嚴格度與回應策略。
    
    功能價值：
    - 避免思維盲點：當島嶼衝突高時，強制啟動深度檢索。
    - 決策優化：根據任務難度動態分配計算資源 (Attention Allocation)。
    - 進化：記錄策略成功率，優化底層邏輯。
    """

    def __init__(self, config: Dict, data_dir: str = './data'):
        self.logger = get_logger('metacognition')
        self.config = config
        self.data_dir = Path(data_dir)
        self.knowledge_file = self.data_dir / 'metacognitive_knowledge.json'
        
        # 元認知狀態 (短期工作記憶)
        self.current_state = {
            "cognitive_load": 0.0,      # 認知負荷 (0.0 - 1.0)
            "confusion_level": 0.0,     # 困惑程度 (0.0 - 1.0)
            "island_entropy": 0.0,      # 島嶼衝突程度 (0.0 - 3.0)
            "active_strategy": "intuitive", # intuitive, analytical, cautious
            "boundary_status": "normal" # normal, increased
        }
        
        # 載入元認知知識 (長期模型)
        self.knowledge_base = self._load_knowledge()
        
        self.logger.info("Metacognitive System initialized (The Console is active).")

    def _load_knowledge(self) -> Dict:
        """載入關於自己的認知能力的知識"""
        if self.knowledge_file.exists():
            try:
                with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load metacognitive knowledge: {e}")
        
        # 默認知識庫 (Self-Schema)
        return {
            "strengths": ["empathy", "emotional_support"],
            "weaknesses": ["political_analysis", "complex_logic"],
            "strategy_stats": {
                "intuitive": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
                "analytical": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
                "cautious": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0}
            },
            "bias_awareness": {
                "Mother": "tends to over-protect",
                "Friend": "tends to be too casual"
            }
        }

    def check_boundary_with_dyadic(self, session_state: Dict, input_text: str, dyadic_dynamics: Any) -> Dict[str, Any]:
        """
        【直覺預防】使用雙人動力學檢查是否需要動態調整邊界
        
        邏輯：
        利用 Vector Shift 作為「直覺」指標。
        如果對話氛圍突然發生劇烈偏移 (Shift > 0.4)，這可能意味著試探、情緒失控或操控開始。
        此時希兒應該「下意識」地收緊邊界。
        """
        if not dyadic_dynamics:
            return {"adjust": "normal"}

        # 獲取歷史輸入
        history_inputs = [turn.get('user_input', '') for turn in session_state.get('turn_history', [])]
        user_id = session_state.get('user_id', 'unknown')

        # 計算偏移量
        shift = dyadic_dynamics.detect_vector_shift(user_id, input_text, history_inputs)
        
        if shift > 0.4:
            self.logger.warning(f"[META INTUITION] High Vector Shift ({shift:.2f}) detected. Triggers instinctive boundary increase.")
            return {"adjust": "increase_boundary", "reason": "高偏移風險", "shift": shift}
        
        return {"adjust": "normal", "shift": shift}

    def monitor_process(self, 
                       user_input: str, 
                       island_activation: Dict[str, float], 
                       extracted_info: Dict,
                       session_state: Dict = None,
                       dyadic_dynamics: Any = None) -> Dict:
        """
        【元認知體驗 (Monitoring)】
        在回應生成前/中，感知當下的心理狀態。
        
        修正後的指標計算：
        1. Island Entropy (島嶼熵): 使用 Dirichlet Prior Smoothing + Normalization (方式三)。
        2. Cognitive Load (認知負荷): 基於用戶輸入長度與情感複雜度。
        3. Boundary Intuition (邊界直覺): 基於 Dyadic Dynamics 的偏移檢測。
        
        Returns:
            Dict: 包含建議的控制參數 (Control Parameters)。
        """
        # 1. 計算島嶼熵 (Shannon Entropy with Smoothing)
        epsilon = 0.01
        raw_values = list(island_activation.values())
        smoothed_values = [v + epsilon for v in raw_values]
        total_activation = sum(smoothed_values)
        
        entropy = 0.0
        if total_activation > 0:
            probs = [v / total_activation for v in smoothed_values]
            # H = -sum(p * log2(p))
            entropy = -sum(p * math.log2(p + 1e-10) for p in probs)
        
        # 2. 計算輸入複雜度
        input_len = len(user_input)
        sentiment_intensity = abs(extracted_info.get('user_sentiment', {}).get('intensity', 0))
        cognitive_load = min(1.0, (input_len / 200.0) + (sentiment_intensity * 0.5))
        
        # 3. 直覺邊界檢查 (New)
        boundary_check = {"adjust": "normal"}
        if dyadic_dynamics and session_state:
            boundary_check = self.check_boundary_with_dyadic(session_state, user_input, dyadic_dynamics)
        
        # 4. 更新狀態
        self.current_state["island_entropy"] = entropy
        self.current_state["cognitive_load"] = cognitive_load
        self.current_state["boundary_status"] = boundary_check.get("adjust")
        
        # 5. 判斷策略 (Regulation)
        strategy = "intuitive"
        control_params = {
            "gsw_top_k": self.config.get('gsw_top_k', 5),
            "heretic_temperature": 0.7, # 默認
            "force_reflection": False,  # 是否強制反思
            "restrict_memory": False,   # 是否只允許核心記憶與永迴軌
            "boundary_multiplier": 1.0  # 親密度累積倍率
        }

        # 應用邊界調整
        if boundary_check.get("adjust") == "increase_boundary":
            control_params["boundary_multiplier"] = 0.5
            control_params["heretic_temperature"] = 0.5 # 稍微冷靜
            self.logger.info("[META] Dynamic Boundary Activated: Intimacy accumulation halved.")

        # 判定邏輯：Inside Out 風格
        if entropy > 1.5: 
            # 內心極度衝突 -> Cautious Mode
            strategy = "cautious"
            control_params["heretic_temperature"] = 0.3 
            control_params["force_reflection"] = True
            control_params["restrict_memory"] = True 
            control_params["gsw_top_k"] = 3 # 減少雜訊
            self.logger.info(f"[META] High Conflict (Entropy: {entropy:.2f}). Strategy: CAUTIOUS.")
            
        elif cognitive_load > 0.8:
            # 任務太難 -> Analytical Mode
            strategy = "analytical"
            control_params["gsw_top_k"] = 10 
            control_params["heretic_temperature"] = 0.5
            self.logger.info(f"[META] High Load ({cognitive_load:.2f}). Strategy: ANALYTICAL.")
            
        else:
            # 心流狀態 -> Intuitive Mode
            strategy = "intuitive"
            if boundary_check.get("adjust") == "normal":
                control_params["heretic_temperature"] = 0.9 # 若無邊界警報，保持高創造力
            
            self.logger.info(f"[META] Flow State (Entropy: {entropy:.2f}). Strategy: INTUITIVE.")

        self.current_state["active_strategy"] = strategy
        
        return control_params

    def evaluate_outcome(self, 
                        final_response: str, 
                        feedback_metrics: Dict) -> None:
        """
        【元認知評估 (Evaluation)】
        在回應生成後，評估這次的思考策略是否有效，並更新知識庫。
        
        Args:
            feedback_metrics: 包含 intimacy_delta, sentiment_delta, is_safe 等
        """
        strategy = self.current_state["active_strategy"]
        
        intimacy_delta = feedback_metrics.get("intimacy_delta", 0.0)
        sentiment_delta = feedback_metrics.get("sentiment_delta", 0.0) # 用戶情緒改善程度
        is_safe = feedback_metrics.get("is_safe", True)
        
        # 定義"成功" (多維度)
        success_score = 0
        if is_safe:
            if intimacy_delta > 0: success_score += 1
            if sentiment_delta > 0: success_score += 1
            # Cautious 模式下，止損就是勝利
            if strategy == "cautious" and intimacy_delta >= 0: success_score += 0.5

        is_success = success_score >= 1
        
        # 更新統計數據
        if "strategy_stats" not in self.knowledge_base:
             self.knowledge_base["strategy_stats"] = {
                "intuitive": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
                "analytical": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0},
                "cautious": {"success": 0, "total": 0, "avg_sentiment_delta": 0.0}
            }

        stats = self.knowledge_base["strategy_stats"].get(strategy, {"success": 0, "total": 0, "avg_sentiment_delta": 0.0})
        
        # 移動平均更新 sentiment delta
        n = stats["total"]
        new_avg = (stats.get("avg_sentiment_delta", 0.0) * n + sentiment_delta) / (n + 1)
        
        stats["total"] += 1
        if is_success:
            stats["success"] += 1
        stats["avg_sentiment_delta"] = new_avg
        
        self.knowledge_base["strategy_stats"][strategy] = stats
        
        success_rate = (stats["success"] / stats["total"]) * 100
        self.logger.debug(f"[META] Eval '{strategy}'. Success: {is_success} (Score: {success_score}). Rate: {success_rate:.1f}%. SentDelta: {sentiment_delta:.3f}")
        
        # 週期性保存
        if stats["total"] % 5 == 0:
            self._save_knowledge()

    def get_introspection_log(self) -> str:
        """
        獲取內省日誌 (用於讓用戶看到希兒的思考過程)
        """
        entropy = self.current_state["island_entropy"]
        strategy = self.current_state["active_strategy"]
        boundary = self.current_state["boundary_status"]
        
        introspection = ""
        if boundary == "increase_boundary":
            introspection = "(希兒感覺到一絲異樣，下意識地退後半步，更加謹慎...)"
        elif strategy == "cautious":
            introspection = f"(希兒感到內心有些混亂 [Entropy: {entropy:.2f}]，正在深呼吸，試著理清思緒...)"
        elif strategy == "analytical":
            introspection = "(希兒正在仔細回想過去的對話，希望能找到最好的回答...)"
            
        return introspection

    def _save_knowledge(self):
        """保存元認知知識 (With Retry)"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.knowledge_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.knowledge_file, 'w', encoding='utf-8') as f:
                    json.dump(self.knowledge_base, f, ensure_ascii=False, indent=2)
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Failed to save metacognitive knowledge after {max_retries} attempts: {e}")
                else:
                    self.logger.warning(f"Save failed (attempt {attempt+1}), retrying: {e}")
                    time.sleep(0.5)
