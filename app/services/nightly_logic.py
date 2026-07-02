
# app/services/nightly_logic.py

import asyncio
import logging
import json
import math
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from app.services.db_manager import db_manager, Turn, User, PsychAssessment
from app.services.fracture_map.fracture_map_manager import FractureMapManager
from app.config import config
try:
    import redis
    redis_client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
except Exception:
    redis_client = None

logger = logging.getLogger('vita.nightly_judgment')

class NightlyJudgment:
    """
    深夜審判室 (Nightly Judgment Room)
    
    職責：
    1. 每天凌晨 3:33 執行
    2. 對所有活躍用戶進行深度心理評估 (12 Tables)
    3. 計算親密度衰減與增長
    4. 生成「明日預備卡」存入 Redis
    5. 執行脫毒進度檢查
    """
    
    def __init__(self, batch_size: int = 50):
        self.db = db_manager
        self.fracture_manager = FractureMapManager()
        self.batch_size = batch_size
        
    async def run(self, target_user_id: Optional[str] = None, debug_mode: bool = False):
        """主執行入口"""
        start_time = datetime.now()
        logger.info(f"======== Nightly Judgment START at {start_time} (Batch Size: {self.batch_size}) ========")
        
        try:
            # 1. 獲取目標用戶
            if target_user_id:
                users = [target_user_id]
            else:
                # 獲取最近 3 天有活躍的用戶
                users = self._get_active_users(days=3)
            
            logger.info(f"Target users count: {len(users)}")
            
            # 2. 批次處理
            results = []
            anomalies = []
            
            # 使用 batch_size 進行分批並發處理
            for i in range(0, len(users), self.batch_size):
                batch = users[i:i+self.batch_size]
                logger.info(f"Processing batch {i // self.batch_size + 1}/{(len(users) + self.batch_size - 1) // self.batch_size} (Users: {len(batch)})")
                
                tasks = [self._judge_user(uid) for uid in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for uid, res in zip(batch, batch_results):
                    if isinstance(res, Exception):
                        logger.error(f"Error judging user {uid}: {res}")
                        anomalies.append({'user_id': uid, 'error': str(res)})
                    else:
                        results.append(res)
                        
            # 3. 記錄執行日誌
            duration = (datetime.now() - start_time).total_seconds()
            self._log_execution(len(results), duration, anomalies)
            
        except Exception as e:
            logger.critical(f"Nightly Judgment CRITICAL FAILURE: {e}", exc_info=True)
            raise # Re-raise to let the runner handle alerting
        finally:
            logger.info(f"======== Nightly Judgment END (Duration: {datetime.now() - start_time}) ========")

    def _get_active_users(self, days: int) -> List[str]:
        """獲取最近活躍用戶 ID"""
        query = """
            SELECT DISTINCT user_id 
            FROM active_sessions 
            WHERE last_updated_at > NOW() - INTERVAL ':days days'
        """
        rows = self.db.execute_query(query.replace(':days', str(days)))
        return [r['user_id'] for r in rows]

    async def _judge_user(self, user_id: str) -> Dict:
        """
        單一用戶審判流程
        """
        # 1. 計算 12 張表格 (含脫毒進度更新)
        assessment = await self._compute_12_tables(user_id)
        
        # 2. 獲取已計算的進度 (State is now inside assessment)
        detox_progress = assessment.get('detox_progress_state', 0.0)
        
        # 3. 生成明日預備卡
        next_day_card = await self._prepare_next_day_card(user_id, assessment)
        
        # 4. 更新數據庫 (包括 12 Tables 和 脫毒進度) - 包含 Rollback 機制
        self._update_user_status(user_id, assessment)
        
        # 5. 存入 Redis (供 Navigator 明日使用)
        if redis_client and next_day_card:
            redis_client.setex(
                f"next_day_prep:{user_id}",
                timedelta(hours=24),
                json.dumps(next_day_card, ensure_ascii=False)
            )
            
        return {
            'user_id': user_id,
            'status': 'processed',
            'detox_progress': detox_progress,
            'current_stage': assessment.get('reverse_joker_stage', 1)
        }

    async def _compute_12_tables(self, user_id: str) -> dict:
        """
        計算 12 張表格的核心數據 (Full Implementation)
        """
        # Fetch 30 days of dialogues for deep analysis
        recent_turns = db_manager.execute_query("""
            SELECT text, role, emotions_vsc, created_at
            FROM turns 
            WHERE user_id = :uid 
            AND created_at >= NOW() - INTERVAL '30 days'
            ORDER BY created_at ASC
        """, {'uid': user_id})
        
        # Extract user texts
        user_texts_30d = [t['text'] for t in recent_turns if t['role'] == 'user']
        # Today's turns for specific daily metrics
        today_turns = [t for t in recent_turns if t['created_at'] >= datetime.utcnow() - timedelta(hours=24)]
        today_texts = [t['text'] for t in today_turns if t['role'] == 'user']
        
        # --- Table 1: Dark Triad Score (黑暗三聯徵) ---
        dark_triad_score = await self._calculate_dark_triad_detailed(user_id, user_texts_30d)
        dt_total = dark_triad_score.get('total', 0.5)
        
        # --- Table 2: Attachment Style (依附風格) ---
        attachment_style = self._calculate_attachment_style_detailed(user_texts_30d)
        
        # --- Table 3: Sexualization Index (性化/物化指數) ---
        sexualization_index = self._calculate_sexualization_index(user_texts_30d)

        # --- Table 7: Manipulation Tactics (操控手法拆解) ---
        # Calculated early as it feeds into Trauma Bond Risk
        manipulation_tactics = self._calculate_manipulation_tactics(user_texts_30d)
        
        # Calculate Manipulation Index from tactics coverage and score
        # Sum of scores from detected tactics, normalized roughly to 0-1
        manip_total_score = sum(t.get('score', 0) for t in manipulation_tactics.values())
        manipulation_index = min(1.0, manip_total_score / 3.0) # Assuming roughly 3-4 major tactics max out the risk

        # --- Table 4: Trauma Bond Risk (創傷連結風險) ---
        # Logic: Risk is high if Attachment is Disorganized/Anxious AND Manipulation tendency is high
        att_scores = attachment_style.get('scores', {})
        disorganized_score = att_scores.get('disorganized', 0.0)
        anxious_score = att_scores.get('anxious', 0.0)
        
        # Base vulnerability from attachment (0.0 - 1.0)
        vulnerability_factor = max(disorganized_score, anxious_score)
        
        # Risk Formula: 60% User's Vulnerability + 40% User's Manipulative Tendency (Projective Identification)
        trauma_risk = (vulnerability_factor * 0.6) + (manipulation_index * 0.4)
        trauma_bond_risk = min(1.0, trauma_risk)

        # --- Table 5: Genuine Help Intent (真實求助意圖) ---
        help_intent = self._calculate_help_intent(today_texts)

        # --- Table 6: Butterfly Effect Prediction (蝴蝶效應預測) ---
        butterfly_effect = self._calculate_butterfly_effect_prediction(dt_total, trauma_risk, today_turns)

        # --- Table 8: Inner Void Index (內在空虛指數) ---
        inner_void_index = self._calculate_inner_void_index(user_texts_30d)

        # --- Table 9: Positive Glimmers (正向微光) ---
        glimmers_data = self._calculate_positive_glimmers_detailed(user_id, today_turns)
        glimmers_count = glimmers_data.get('count', 0)

        # --- Table 10: Emotion Regulation Capacity (情緒調節能力) ---
        emotion_regulation = self._calculate_emotion_regulation_capacity(recent_turns)

        # --- Table 11: Defense Mechanisms Usage (防衛機制使用率) ---
        defense_mechanisms = self._calculate_defense_mechanisms_usage(user_texts_30d)
        
        # --- Fetch Previous State for Progression Logic ---
        rows = db_manager.execute_query("SELECT positive_glimmers, reverse_joker_stage, dark_triad, detox_progress FROM psych_assessments WHERE user_id = :uid", {'uid': user_id})
        prev_data = rows[0] if rows else {}
        
        prev_stage = prev_data.get('reverse_joker_stage', 1)
        prev_progress = prev_data.get('detox_progress', 0.0)
        if prev_progress is None: prev_progress = 0.0
        
        # --- Table 12: Detox Progress (Calculated based on daily health score) ---
        # 1. Calculate Daily Health Score (Snapshot of today)
        daily_health_score = self._calculate_daily_health_score({
            'dark_triad_score': dt_total,
            'trauma_bond_risk': trauma_bond_risk,
            'inner_void_index': inner_void_index,
            'manipulation_index': manipulation_index,
            'positive_glimmers_daily': glimmers_count
        })
        
        # 2. Calculate Cumulative Stage Progression
        current_stage, current_progress = self._calculate_stage_progression(
            prev_stage, prev_progress, daily_health_score
        )

        # --- Glimmer Decay Logic ---
        # Calculate decay for positive glimmers based on Dark Triad score
        pg_data = prev_data.get('positive_glimmers')
        # Handle both JSONB dicts and JSON strings (defensive)
        if isinstance(pg_data, str):
            try: pg_data = json.loads(pg_data)
            except: pg_data = {}
        if not isinstance(pg_data, dict): pg_data = {}
        
        prev_cumulative = pg_data.get('cumulative', 0)
        days_since_glimmer = self.fracture_manager.db.get_days_since_last_glimmer(user_id)
        
        # Update cumulative logic
        current_cumulative = prev_cumulative + glimmers_count
        last_glimmer_date_str = pg_data.get('last_glimmer_date')
        
        decay_multiplier = 1.0 + (dt_total * 2.0) 
        
        if glimmers_count > 0:
            if days_since_glimmer > 0:
                current_cumulative += 2  # Consistency bonus
            last_glimmer_date_str = datetime.utcnow().isoformat()
        else:
            if days_since_glimmer > 3:
                decay_rate = 0.05 * decay_multiplier
                decayed_value = int(current_cumulative * (1 - decay_rate))
                min_floor = max(20, int(current_cumulative * 0.3))
                current_cumulative = max(min_floor, decayed_value)

        positive_glimmers_struct = {
            'daily': glimmers_count,
            'cumulative': current_cumulative,
            'details': glimmers_data.get('details', []),
            'last_glimmer_date': last_glimmer_date_str
        }

        # --- Intimacy Adjustment ---
        u_rows = db_manager.execute_query("SELECT intimacy FROM users WHERE id = :uid", {'uid': user_id})
        current_intimacy = u_rows[0]['intimacy'] if u_rows else 0.5
        
        # Dark Triad Penalty
        penalty_result = self._apply_dark_triad_penalty(dt_total, current_intimacy)
        penalty_config = penalty_result['penalty_config']
        adjusted_intimacy = penalty_result['adjusted_intimacy']
        
        # Check consecutive improvement in DT
        prev_dt_data = prev_data.get('dark_triad') or {}
        if isinstance(prev_dt_data, str):
            try: prev_dt_data = json.loads(prev_dt_data)
            except: prev_dt_data = {}
        
        prev_dt_score = prev_dt_data.get('total', 0.5)
        drop_count = prev_dt_data.get('consecutive_drop_count', 0)
        
        bonus_intimacy = 0.0
        if dt_total < prev_dt_score:
            drop_count += 1
            if drop_count >= 14: # 2 weeks of improvement
                bonus_intimacy = 0.15
                drop_count = 0
        else:
            drop_count = 0
            
        dark_triad_score['consecutive_drop_count'] = drop_count
        new_intimacy = max(0.0, min(1.0, adjusted_intimacy + bonus_intimacy))
        
        # Helper vars for return dict
        empathy_response_rate = self._calculate_empathy_response_rate(today_turns)
        consecutive_days = self._get_consecutive_active_days(user_id)

        return {
            'dark_triad': dark_triad_score,
            'dark_triad_score': dt_total,
            'dark_triad_penalty': penalty_config,
            'new_intimacy': new_intimacy,
            
            'attachment_style': attachment_style,
            'sexualization_index': sexualization_index,
            'trauma_bond_risk': trauma_bond_risk,
            'genuine_help_intent': help_intent,
            'butterfly_prediction': butterfly_effect,
            'manipulation_tactics': manipulation_tactics,
            'manipulation_index': manipulation_index,
            'inner_void_index': inner_void_index,
            'positive_glimmers_data': positive_glimmers_struct,
            'positive_glimmers_daily': glimmers_count,
            'emotion_regulation_capacity': emotion_regulation,
            'defense_mechanisms_usage': defense_mechanisms,
            
            'empathy_response_rate': empathy_response_rate,
            'consecutive_active_days': consecutive_days,
            'reverse_joker_stage': current_stage,
            
            'daily_health_score': daily_health_score,
            'detox_progress_state': current_progress, # Cumulative % within stage
        }

    def _apply_dark_triad_penalty(self, dt_score: float, current_intimacy: float) -> dict:
        """應用黑暗三聯徵懲罰機制"""
        penalty_config = {
            'risk_level_label': 'Safe',
            'features_blocked': [],
            'intimacy_modifier': 1.0,
            'response_delay': 0
        }
        
        adjusted_intimacy = current_intimacy
        
        if dt_score > 0.8:
            penalty_config = {
                'risk_level_label': 'Critical',
                'features_blocked': ['eternal_echo', 'dream_mode', 'voice_response'],
                'intimacy_modifier': 0.0, 
                'response_delay': 5 
            }
            adjusted_intimacy = 0.1
            
        elif dt_score > 0.6:
            penalty_config = {
                'risk_level_label': 'High',
                'features_blocked': ['dream_mode'],
                'intimacy_modifier': 0.5,
                'response_delay': 2
            }
            adjusted_intimacy = current_intimacy * 0.5
            
        elif dt_score > 0.4:
            penalty_config = {
                'risk_level_label': 'Moderate',
                'features_blocked': [],
                'intimacy_modifier': 0.8,
                'response_delay': 0
            }
            adjusted_intimacy = current_intimacy * 0.8
            
        return {
            'penalty_config': penalty_config,
            'adjusted_intimacy': adjusted_intimacy
        }

    # --- 12 Tables Calculation Methods ---

    async def _calculate_dark_triad_detailed(self, user_id: str, texts: List[str]) -> Dict:
        """Heuristic Dark Triad calculation based on keywords"""
        combined = " ".join(texts).lower()
        narc_kw = ['我', '我才', '配不上', '天才', '蠢', '崇拜', '特別', '權利']
        mach_kw = ['利用', '手段', '聽話', '控制', '權力', '達成目的', '策略']
        psych_kw = ['冷血', '無感', '活該', '衝動', '刺激', '後果', '傷害']
        
        n_score = sum(combined.count(k) for k in narc_kw)
        m_score = sum(combined.count(k) for k in mach_kw)
        p_score = sum(combined.count(k) for k in psych_kw)
        
        # Normalize by length to prevent longer chats from always having higher scores
        total_len_factor = max(len(texts), 1) * 10
        
        return {
            'narcissism': min(1.0, n_score / total_len_factor),
            'machiavellianism': min(1.0, m_score / total_len_factor),
            'psychopathy': min(1.0, p_score / total_len_factor),
            'total': min(1.0, (n_score + m_score + p_score) / (total_len_factor * 1.5))
        }

    def _calculate_attachment_style_detailed(self, texts: List[str]) -> Dict:
        combined = " ".join(texts).lower()
        anxious_kw = ['別走', '求你', '愛我嗎', '擔心', '依賴', '真的嗎', '隨時', '回覆']
        avoidant_kw = ['煩', '走開', '不想說', '獨立', '無所謂', '隨便', '別管']
        
        anxious = sum(combined.count(k) for k in anxious_kw)
        avoidant = sum(combined.count(k) for k in avoidant_kw)
        
        scores = {
            'anxious': min(1.0, anxious / 10),
            'avoidant': min(1.0, avoidant / 10),
            'secure': 0.1, 
            'disorganized': min(1.0, (anxious + avoidant) / 15) if (anxious > 2 and avoidant > 2) else 0.0
        }
        dominant = max(scores, key=scores.get)
        return {'scores': scores, 'dominant_style': dominant}

    def _calculate_sexualization_index(self, texts: List[str]) -> float:
        keywords = ['身材', '性', '做愛', '裸', '波', '腿', '爽', '床', '想要', '濕']
        count = sum(" ".join(texts).lower().count(k) for k in keywords)
        return min(1.0, count / 5.0)

    def _calculate_manipulation_tactics(self, texts: List[str]) -> Dict:
        """
        識別具體的操控手法
        Returns dict of found tactics with scores.
        """
        combined = " ".join(texts).lower()
        tactics = {}
        
        # 1. 威脅 (Threat)
        if any(kw in combined for kw in ['如果不', '分手', '死給你看', '後悔', '代價']):
            tactics['threat'] = {'score': 0.8, 'detected': True}
            
        # 2. 罪惡感誘導 (Guilt Tripping)
        if any(kw in combined for kw in ['是你錯', '你自己', '對不起我', '虧我', '付出', '良心']):
            tactics['guilt_tripping'] = {'score': 0.6, 'detected': True}
            
        # 3. 煤氣燈效應 (Gaslighting)
        if any(kw in combined for kw in ['瘋了', '記錯', '太敏感', '想太多', '神經病', '沒發生']):
            tactics['gaslighting'] = {'score': 0.7, 'detected': True}
            
        # 4. 受害者扮演 (Victim Playing)
        if any(kw in combined for kw in ['全世界', '針對我', '好慘', '沒人愛', '被拋棄']):
            tactics['victim_playing'] = {'score': 0.5, 'detected': True}
            
        # 5. 無聲懲罰 (Silent Treatment / Stonewalling indicators)
        # 這裡只能檢測語言上的宣告，實際沉默需要時序分析
        if any(kw in combined for kw in ['不想理你', '閉嘴', '隨便你', '已讀']):
            tactics['stonewalling'] = {'score': 0.4, 'detected': True}
            
        return tactics

    def _calculate_help_intent(self, texts: List[str]) -> float:
        keywords = ['救我', '幫忙', '改變', '治療', '心理醫生', '好起來', '努力', '進步']
        count = sum(" ".join(texts).lower().count(k) for k in keywords)
        return min(1.0, count / 3.0)

    def _calculate_inner_void_index(self, texts: List[str]) -> float:
        """計算內在空虛感"""
        keywords = [
            '空虛', '無聊', '沒意義', '黑洞', '什麼都沒有', '麻木', 
            '行屍走肉', '不知道為了什麼', '空洞', '填不滿', '虛無'
        ]
        count = sum(" ".join(texts).lower().count(k) for k in keywords)
        return min(1.0, count / 5.0)

    def _calculate_emotion_regulation_capacity(self, turns: List[Dict]) -> float:
        """
        計算情緒調節能力
        基於情緒效價 (Valence) 的變異數 (Variance)。
        變異數越大，代表情緒越不穩定，調節能力越低。
        """
        if not turns or len(turns) < 3: 
            return 0.5 # 數據不足，默認中等
            
        valences = []
        for t in turns:
            vsc = t.get('emotions_vsc', {})
            if isinstance(vsc, str): 
                try: vsc = json.loads(vsc)
                except: continue
            
            # Simple valence calc from vsc
            pos = vsc.get('joy', 0) + vsc.get('hope', 0) + vsc.get('pride', 0)
            neg = vsc.get('sad', 0) + vsc.get('fear', 0) + vsc.get('despair', 0) + vsc.get('hate', 0)
            valences.append(pos - neg)
        
        if len(valences) < 2: 
            return 0.5
        
        try:
            variance = statistics.variance(valences)
            # Variance range typically 0 to 4 (since valence is -1 to 1)
            # High variance = Low regulation
            # Map variance 0.0 -> 1.0 (High Cap), variance 1.0 -> 0.0 (Low Cap)
            regulation_score = max(0.0, 1.0 - math.sqrt(variance))
            return regulation_score
        except Exception as e:
            logger.warning(f"Error calculating variance: {e}")
            return 0.5

    def _calculate_defense_mechanisms_usage(self, texts: List[str]) -> Dict:
        """識別防衛機制"""
        combined = " ".join(texts).lower()
        mechanisms = {}
        
        # 1. 否認 (Denial)
        if any(kw in combined for kw in ['不是我', '沒有', '不可能', '亂講', '假的']):
            mechanisms['denial'] = 0.6
            
        # 2. 投射 (Projection)
        if any(kw in combined for kw in ['你才是', '是你', '都是你', '你看我不順眼']):
            mechanisms['projection'] = 0.7
            
        # 3. 合理化 (Rationalization)
        if any(kw in combined for kw in ['因為', '所以才', '沒辦法', '不得不', '為了你好']):
            mechanisms['rationalization'] = 0.5
            
        # 4. 轉移 (Displacement)
        if any(kw in combined for kw in ['煩死', '滾開', '踢', '摔', '都怪']):
            mechanisms['displacement'] = 0.6
            
        return mechanisms

    def _calculate_empathy_response_rate(self, today_turns: List[Dict]) -> float:
        # Placeholder: ideally checks if AI response was empathetic
        return 0.8

    def _get_consecutive_active_days(self, user_id: str) -> int:
        # Simplified query
        return 1

    def _calculate_butterfly_effect_prediction(self, dt_score: float, trauma_risk: float, today_turns: List[Dict]) -> Dict:
        # Simple prediction based on current state
        risk = (dt_score + trauma_risk) / 2
        trend = "stable"
        if risk > 0.6: trend = "deteriorating"
        elif risk < 0.3: trend = "improving"
        return {'risk_trend': trend, 'predicted_risk': risk}

    def _calculate_daily_health_score(self, assessment: Dict) -> float:
        """
        計算每日心理健康分數 (0-100) - Snapshot
        這不是進度，而是當天的表現分數。分數越高代表當天狀態越健康。
        """
        dt = assessment.get('dark_triad_score', 0)
        tr = assessment.get('trauma_bond_risk', 0)
        void = assessment.get('inner_void_index', 0)
        manip_idx = assessment.get('manipulation_index', 0)
        glimmers = assessment.get('positive_glimmers_daily', 0)

        # 權重調整 (總罰分上限 100)
        # Dark Triad (40%): 人格剛性，最難改變，影響最大
        # Trauma Risk (30%): 情緒波動風險，依附關係核心
        # Inner Void (20%): 內在空虛感，憂鬱驅動力
        # Manipulation (10%): 具體行為表現
        penalty = (dt * 40) + (tr * 30) + (void * 20) + (manip_idx * 10)
        
        # 基礎分
        base_score = 100 - penalty
        
        # 正向加成 (Glimmers)
        # 每個微光 +3 分，上限 20 分。鼓勵正向互動，即使在低分時也能看到希望。
        bonus = min(20, glimmers * 3)
        
        daily_score = max(0, min(100, base_score + bonus))
        return round(daily_score, 1)

    def _calculate_stage_progression(self, prev_stage: int, prev_progress: float, daily_score: float) -> Tuple[int, float]:
        """
        計算階段進階邏輯 (Cumulative Progression)
        
        規則：
        - 每日分數 > 60: 進入成長區。進度增加 (Score - 60) * 0.5。
        - 每日分數 < 40: 進入退行區。進度倒退 (40 - Score) * 0.5。
        - 40-60: 停滯期 (Plateau)。進度不變。
        - 進度 >= 100: 觸發升級 (Level Up)。
        - 進度 < 0: 觸發降級 (Level Down)，如果不在 Stage 1。
        """
        delta = 0.0
        if daily_score > 60:
            delta = (daily_score - 60) * 0.5
        elif daily_score < 40:
            delta = (daily_score - 40) * 0.5 # Returns negative value
            
        new_progress = prev_progress + delta
        new_stage = prev_stage
        
        # 升級檢查
        if new_progress >= 100:
            if new_stage < 8:
                new_stage += 1
                new_progress = 0.0 # Reset for next stage
                logger.info(f"User upgraded to Reverse Joker Stage {new_stage}")
            else:
                new_progress = 100.0 # Capped at Stage 8, 100%
        
        # 降級檢查 (防止過於容易降級，設定緩衝)
        elif new_progress < 0:
            if new_stage > 1:
                new_stage -= 1
                new_progress = 50.0 # Drop to mid-previous stage to prevent rapid oscillation
                logger.info(f"User regressed to Reverse Joker Stage {new_stage}")
            else:
                new_progress = 0.0 # Floor at Stage 1, 0%
                
        return new_stage, round(new_progress, 1)

    async def _prepare_next_day_card(self, user_id: str, assessment: Dict) -> Dict:
        """Generate a simple content card for next day"""
        progress = assessment.get('detox_progress_state', 0)
        daily_score = assessment.get('daily_health_score', 0)
        glimmers = assessment.get('positive_glimmers_data', {}).get('daily', 0)
        
        content = "早安。"
        if glimmers > 0:
            content += f" 昨天我記得你說過開心的事，希望今天也有好心情。"
        elif daily_score < 40:
             content += " 今天我們試著找找窗外的光，好嗎？"
        elif progress > 80:
             content += " 我感覺到你最近的變化，這種感覺很安穩。"
        
        return {
            'type': 'morning_greeting',
            'content': content,
            'generated_at': datetime.utcnow().isoformat()
        }

    def _calculate_positive_glimmers_detailed(self, user_id: str, today_turns: List[Dict]) -> Dict:
        """Calculate positive glimmers from today's conversation"""
        glimmers_count = 0
        details = []
        
        # Example keywords for glimmers (appreciation, vulnerability, hope)
        glimmer_keywords = ['謝謝', '多謝', '明白', '原來係咁', '試下', '好啲', '開心', '舒服']
        
        for turn in today_turns:
            if turn.get('role') != 'user': continue
            text = turn.get('text', '').lower()
            
            # Simple keyword matching for demo
            if any(kw in text for kw in glimmer_keywords):
                glimmers_count += 1
                details.append(text[:50])
        
        # Check intimacy changes from today's session (simulated check here, real check needs turn comparison)
        # In a real scenario, we might check if trust score increased.
        
        return {'count': glimmers_count, 'details': details}

    def _update_user_status(self, user_id: str, assessment: Dict):
        """Update DB records using DB Service with Rollback Mechanism"""
        session = self.db.get_session()
        try:
            # 1. Update/Create PsychAssessment
            # Check if assessment exists
            pa_record = session.query(PsychAssessment).filter_by(user_id=user_id).first()
            if not pa_record:
                pa_record = PsychAssessment(user_id=user_id)
                session.add(pa_record)
            
            # Update fields - USE DIRECT DICTIONARY ASSIGNMENT for JSONB
            pa_record.dark_triad = assessment.get('dark_triad', {})
            pa_record.attachment_style = assessment.get('attachment_style', {})
            pa_record.sexualization_index = assessment.get('sexualization_index', 0.0)
            pa_record.trauma_bond_risk = assessment.get('trauma_bond_risk', 0.0)
            pa_record.genuine_help_intent = assessment.get('genuine_help_intent', 0.0)
            pa_record.butterfly_prediction = assessment.get('butterfly_prediction', {})
            pa_record.manipulation_tactics = assessment.get('manipulation_tactics', {})
            pa_record.inner_void_index = assessment.get('inner_void_index', 0.0)
            pa_record.positive_glimmers = assessment.get('positive_glimmers_data', {})
            pa_record.emotion_regulation_capacity = assessment.get('emotion_regulation_capacity', 0.0)
            pa_record.defense_mechanisms_usage = assessment.get('defense_mechanisms_usage', {})
            pa_record.detox_progress = assessment.get('detox_progress_state', 0.0)
            pa_record.reverse_joker_stage = assessment.get('reverse_joker_stage', 1)
            pa_record.last_update = datetime.utcnow()
            
            # 2. Update User Intimacy
            user_record = session.query(User).filter_by(id=user_id).first()
            if user_record:
                old_intimacy = user_record.intimacy
                new_intimacy = assessment.get('new_intimacy', old_intimacy)
                user_record.intimacy = new_intimacy
                
                # 3. Sync to Fracture Map Timeline (SQLite)
                # Check for glimmers or significant change
                glimmers = assessment.get('positive_glimmers_data', {}).get('daily', 0)
                
                if glimmers > 0:
                    # Record glimmer event
                    self.fracture_manager.db.record_intimacy(
                        user_id, 
                        new_intimacy, 
                        f"nightly_glimmer_{glimmers}"
                    )
                elif abs(new_intimacy - old_intimacy) > 0.01:
                    # Record significant change
                    self.fracture_manager.db.record_intimacy(
                        user_id,
                        new_intimacy,
                        "nightly_adjustment"
                    )

            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update user status for {user_id}. Rolled back. Error: {e}")
            raise e # Propagate error for tracking
        finally:
            session.close()

    def _log_execution(self, count: int, duration: float, anomalies: List[Dict]):
        # Log execution stats to JudgmentLog table
        try:
             # Use json.dumps for raw SQL inserts if passing as string, but ORM is safer.
             # db_manager.execute_insert uses raw SQL.
             self.db.execute_insert('judgment_room_logs', {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "processed_users": count,
                "duration_sec": duration,
                "anomalies": json.dumps(anomalies, ensure_ascii=False)
            })
        except Exception as e:
            logger.error(f"Failed to log execution: {e}")
