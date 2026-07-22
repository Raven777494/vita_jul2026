# PersonalityModule/memory_manager.py
# 臨床心理學記憶管理引擎 v3.2 (完整修正版)

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum


logger = logging.getLogger('vita.memory_manager')


class DecayMode(Enum):
    """衰減模式枚舉"""
    EBBINGHAUS = "ebbinghaus"  # 艾賓浩斯遺忘曲線
    LINEAR = "linear"           # 線性衰減
    EXPONENTIAL = "exponential" # 指數衰減


class MemoryManager:
    """
    臨床心理學記憶管理系統 v3.2 (Cognitive Memory Regulation)

    基於神經科學與心理學模型：
    1. 艾賓浩斯遺忘曲線 (Ebbinghaus Forgetting Curve)
    2. 情緒顯著性記憶固化 (Emotional Salience Consolidation)
    3. 創傷/強迫反芻強化 (Rumination Reinforcement)
    4. 檢索誘發便利 (Retrieval-Induced Facilitation)

    修正清單:
    [FIXED-M1] 統一時區處理 (UTC 標準化)
    [FIXED-M2] 強化異常情況容錯
    [FIXED-M3] 修復情感顯著性計算邊界
    [FIXED-M4] 改善存取計數計算
    [FIXED-M5] 新增完整訪問歷史追蹤
    [FIXED-M6] 修復衰減邏輯 (統一單一模式)
    [FIXED-M7] 新增可配置的衰減參數
    [FIXED-M8] 完善記憶狀態檢查
    [FIXED-M9] 新增權重溢出保護
    [FIXED-M10] 增強日誌記錄完整性
    """

    # ==================== 類別常量 ====================

    # 心理學參數
    BASE_DECAY_LAMBDA = 0.03           # 基礎遺忘率
    MIN_WEIGHT = 0.5                   # 核心記憶最低權重
    MAX_BOOST_WEIGHT = 3.0             # 最高權重限制
    RUMINATION_MULTIPLIER = 1.15       # 反芻思考權重增益
    ACTIVATION_BOOST_FACTOR = 1.2      # 激活提升係數
    EMOTIONAL_SALIENCE_THRESHOLD = 0.5 # 情感顯著性閾值

    # 衰減參數
    TIME_DECAY_LAMBDA = 0.01           # 時間衰減常數
    USE_DECAY_FACTOR = 0.95            # 使用衰減因子
    ACCESS_BOOST_RATE = 0.05           # 訪問計數增益率
    MAX_AGE_DAYS = 365                 # 記憶最大年齡

    # 數值限制
    MAX_ACCESS_COUNT = 10000           # 最大訪問計數
    MIN_TIME_DELTA_SECONDS = 1         # 最小時間差

    # [FIXED-M1] UTC 時區
    UTC = timezone.utc

    def __init__(self, decay_mode: DecayMode = DecayMode.EBBINGHAUS):
        """
        初始化記憶管理器

        Args:
            decay_mode: 衰減模式
        """
        self.logger = logger
        self.decay_mode = decay_mode

        # 配置參數 (可於運行時調整)
        self.base_decay_lambda = self.BASE_DECAY_LAMBDA
        self.min_weight = self.MIN_WEIGHT
        self.max_boost_weight = self.MAX_BOOST_WEIGHT
        self.rumination_multiplier = self.RUMINATION_MULTIPLIER
        self.activation_boost_factor = self.ACTIVATION_BOOST_FACTOR

        # GSWEngine fallback 用的簡易記憶庫（無向量 DB 時降級，避免 AttributeError）
        self._store: List[Dict] = []

        self.logger.info(
            f"[MemoryManager] v3.2 initialized "
            f"(decay_mode: {decay_mode.value})"
        )

    # ==================== GSW 相容介面（fallback） ====================

    def store(self, record: Dict) -> bool:
        """
        儲存一筆記憶（GSWEngine fallback 路徑）。
        P3.4：拒絕以正史／核心 id 寫入或覆寫（echo ≠ 改寫童年正史）。
        """
        if not isinstance(record, dict):
            return False

        memory_id = str(record.get('id') or '')
        if any(memory_id.startswith(p) for p in ('memory_', 'core_', 'gold_hk_', 'canon_')):
            self.logger.error(
                f"[MemoryManager] Refused store of immutable soul id: {memory_id}"
            )
            return False
        if record.get('locked') or record.get('protected'):
            # 允許新建 locked 旗標的 echo；但禁止 source=canon 寫入
            source = str(
                (record.get('metadata') or {}).get('source', '')
                if isinstance(record.get('metadata'), dict)
                else record.get('source', '')
            ).lower()
            if source in {'seele_childhood_canon', 'canonical', 'canon'}:
                self.logger.error(
                    f"[MemoryManager] Refused store of canon-sourced record: {memory_id}"
                )
                return False

        payload = dict(record)
        meta = payload.get('metadata')
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault('source', 'eternal_echo')
        meta.setdefault('memory_type', 'eternal_echo')
        payload['metadata'] = meta

        self._store.append(payload)
        # 防止無界成長
        if len(self._store) > 2000:
            self._store = self._store[-2000:]
        return True

    def search(self, query_vector: List[float], k: int = 5) -> List[Dict]:
        """
        簡易相似度搜尋（GSWEngine fallback）。
        無 embedding 的記錄會被跳過；結果附 similarity 欄位。
        """
        if not query_vector or not self._store:
            return []
        scored: List[Tuple[float, Dict]] = []
        for mem in self._store:
            if mem.get('archived'):
                continue
            emb = mem.get('embedding')
            if not isinstance(emb, list) or not emb:
                continue
            if len(emb) != len(query_vector):
                continue
            try:
                sim = self._cosine_similarity_01(query_vector, emb)
            except Exception:
                continue
            item = dict(mem)
            item['similarity'] = sim
            scored.append((sim, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[: max(1, int(k))]]

    def apply_decay(self) -> int:
        """對內部 store 套用心理學衰減（GSWEngine.apply_decay_to_db fallback）。"""
        return self.apply_decay_to_memories(self._store)

    @staticmethod
    def _cosine_similarity_01(vec1: List[float], vec2: List[float]) -> float:
        dot = sum(float(a) * float(b) for a, b in zip(vec1, vec2))
        n1 = math.sqrt(sum(float(a) ** 2 for a in vec1))
        n2 = math.sqrt(sum(float(b) ** 2 for b in vec2))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return max(0.0, min(1.0, (dot / (n1 * n2) + 1.0) / 2.0))

    # ==================== 時間處理工具 [FIXED-M1] ====================

    @staticmethod
    def _parse_datetime(time_str: Optional[str]) -> Optional[datetime]:
        """
        [FIXED-M1] 統一解析日期時間字符串

        支持的格式:
        - ISO 8601 (with/without timezone)
        - Unix timestamp

        Args:
            time_str: 時間字符串

        Returns:
            datetime 對象或 None
        """
        if not time_str:
            return None

        try:
            # 字符串格式
            if isinstance(time_str, str):
                # 移除 'Z' 時區標誌，轉換為 +00:00
                if time_str.endswith('Z'):
                    time_str = time_str[:-1] + '+00:00'

                dt = datetime.fromisoformat(time_str)

                # [FIXED-M1] 轉換為 UTC naive datetime
                if dt.tzinfo is not None:
                    dt = dt.astimezone(MemoryManager.UTC).replace(tzinfo=None)

                return dt

            # Unix timestamp 格式
            elif isinstance(time_str, (int, float)):
                dt = datetime.fromtimestamp(time_str, tz=MemoryManager.UTC)
                return dt.replace(tzinfo=None)

        except (ValueError, TypeError, AttributeError) as e:
            return None

        return None

    @staticmethod
    def _get_current_time() -> datetime:
        """[FIXED-M1] 取得當前 UTC 時間"""
        return datetime.now(MemoryManager.UTC).replace(tzinfo=None)

    def _calculate_time_delta_days(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime] = None
    ) -> float:
        """
        [FIXED-M1] 計算時間差 (天)

        Args:
            start_time: 起始時間
            end_time: 結束時間 (預設: 當前時間)

        Returns:
            時間差 (天)
        """
        if start_time is None:
            return 0.0

        if end_time is None:
            end_time = self._get_current_time()

        try:
            delta = end_time - start_time
            total_seconds = delta.total_seconds()

            # [FIXED-M1] 防止負數時間差
            if total_seconds < 0:
                self.logger.warning("Negative time delta detected, clamping to 0")
                return 0.0

            return max(0.0, total_seconds / 86400.0)

        except Exception as e:
            self.logger.error(f"Time delta calculation error: {e}")
            return 0.0

    # ==================== 核心衰減邏輯 ====================

    def calculate_psychological_decay(
        self,
        memory_record: Dict,
        current_time: Optional[datetime] = None
    ) -> float:
        """
        [FIXED-M3,M4] 計算記憶經過心理學修正後的當前權重

        邏輯：
        - 基礎權重隨時間指數衰減 (艾賓浩斯曲線)
        - 高喚醒度 (Arousal > 0.7) 降低遺忘率 (創傷/強烈印記)
        - 存取次數模擬神經突觸強化
        - 反芻思考增加權重

        Args:
            memory_record: 記憶字典
            current_time: 當前時間 (預設: 系統時間)

        Returns:
            修正後的權重 [MIN_WEIGHT, MAX_BOOST_WEIGHT]
        """
        if not memory_record:
            return self.min_weight

        # [FIXED-M2] 參數驗證
        try:
            old_weight = float(memory_record.get('weight', 2.0))
            # [FIXED-M2] 確保初始權重在合理範圍
            old_weight = max(self.min_weight, min(self.max_boost_weight, old_weight))
        except (ValueError, TypeError):
            old_weight = 2.0

        # [FIXED-M5] 取得訪問計數
        try:
            access_count = int(memory_record.get('access_count', 0))
            access_count = min(access_count, self.MAX_ACCESS_COUNT)
        except (ValueError, TypeError):
            access_count = 0

        # [FIXED-M3] 提取情緒向量
        emotions = memory_record.get('user_sentiment', {})
        if not isinstance(emotions, dict):
            emotions = {}

        try:
            arousal = float(emotions.get('arousal', 0.0))
            valence = float(emotions.get('valence', 0.0))

            # [FIXED-M3] 限制情緒值到 [0, 1]
            arousal = max(0.0, min(1.0, arousal))
            valence = max(-1.0, min(1.0, valence))
        except (ValueError, TypeError):
            arousal = 0.0
            valence = 0.0

        # [FIXED-M1] 計算時間差
        if current_time is None:
            current_time = self._get_current_time()

        creation_time_str = memory_record.get('timestamp', '')
        creation_time = self._parse_datetime(creation_time_str)

        if creation_time is None:
            self.logger.debug(
                f"Invalid timestamp for memory {memory_record.get('id', 'unknown')}"
            )
            age_days = 0.0
        else:
            age_days = self._calculate_time_delta_days(creation_time, current_time)

        # [FIXED-M3] 計算情感顯著性 (0.0 - 1.0)
        # 結合喚醒度和效價的極端性
        emotional_salience = (
            (arousal * 0.6) +  # 喚醒度佔 60%
            (abs(valence) * 0.4)  # 效價極端性佔 40%
        )
        emotional_salience = max(0.0, min(1.0, emotional_salience))

        # [FIXED-M3] 計算調整後的遺忘率
        # 高情感顯著性 -> 低遺忘率 (強烈記憶保持)
        salience_factor = 1.0 - (emotional_salience * 0.8)
        adjusted_lambda = self.base_decay_lambda * salience_factor
        # [FIXED-M3] 確保遺忘率非負
        adjusted_lambda = max(0.005, min(self.base_decay_lambda, adjusted_lambda))

        # [FIXED-M3] 艾賓浩斯時間衰減
        try:
            time_decay_weight = old_weight * math.exp(-adjusted_lambda * age_days)
        except (ValueError, OverflowError):
            self.logger.warning("Overflow in exponential decay calculation")
            time_decay_weight = old_weight

        # [FIXED-M4] 反芻與存取強化
        # 使用改進的對數計算，防止 access_count=0 時出現邊界問題
        if access_count > 0:
            retention_boost = 1.0 + (math.log(access_count + 1) * self.ACCESS_BOOST_RATE)
        else:
            retention_boost = 1.0

        # [FIXED-M4] 限制反芻增益
        retention_boost = min(self.rumination_multiplier, retention_boost)

        new_weight = time_decay_weight * retention_boost

        # [FIXED-M9] 權重溢出保護
        new_weight = max(self.min_weight, min(self.max_boost_weight, new_weight))

        self.logger.debug(
            f"Decay calc for {memory_record.get('id', 'unknown')}: "
            f"old={old_weight:.3f}, new={new_weight:.3f}, "
            f"age={age_days:.1f}d, arousal={arousal:.2f}, access={access_count}"
        )

        return new_weight

    def apply_decay_to_memories(
        self,
        memories: List[Dict],
        current_time: Optional[datetime] = None
    ) -> int:
        """
        [FIXED-M6] 應用衰減到記憶列表

        Args:
            memories: 記憶列表
            current_time: 當前時間

        Returns:
            更新的記憶數
        """
        if not memories:
            return 0

        if current_time is None:
            current_time = self._get_current_time()

        updated_count = 0

        for memory in memories:
            # [FIXED-M8] 檢查記憶狀態
            if memory.get('archived', False) or memory.get('locked', False):
                continue

            try:
                old_weight = memory.get('weight', 2.0)
                new_weight = self.calculate_psychological_decay(memory, current_time)

                # [FIXED-M9] 記錄權重變化
                if abs(new_weight - old_weight) > 0.001:
                    memory['weight'] = new_weight
                    memory['weight_updated_at'] = current_time.isoformat()
                    updated_count += 1

            except Exception as e:
                self.logger.error(
                    f"Decay failed for memory {memory.get('id', 'unknown')}: {e}"
                )

        if updated_count > 0:
            self.logger.info(f"Applied decay to {updated_count} memories")

        return updated_count

    # ==================== 激活與訪問記錄 ====================

    def calculate_activation_boost(
        self,
        current_weight: float,
        user_arousal: float = 0.5,
        boost_factor: Optional[float] = None
    ) -> float:
        """
        [FIXED-M2,M9] 計算記憶提取時的激活增益

        邏輯：
        - 基礎激活增益為 1.2 倍
        - 用戶高情緒激動時增益更大
        - 結果限制在 [MIN_WEIGHT, MAX_BOOST_WEIGHT]

        Args:
            current_weight: 當前權重
            user_arousal: 用戶喚醒度 [0.0, 1.0]
            boost_factor: 自定義增益係數 (預設: ACTIVATION_BOOST_FACTOR)

        Returns:
            提升後的權重
        """
        if boost_factor is None:
            boost_factor = self.activation_boost_factor

        # [FIXED-M2] 參數驗證
        try:
            current_weight = float(current_weight)
            user_arousal = max(0.0, min(1.0, float(user_arousal)))
            boost_factor = float(boost_factor)
        except (ValueError, TypeError):
            return current_weight

        # 計算增益
        base_boost = boost_factor
        stress_modifier = 1.0 + (user_arousal * 0.3)  # 高喚醒度增加 0-30% 的增益
        new_weight = current_weight * base_boost * stress_modifier

        # [FIXED-M9] 權重溢出保護
        new_weight = max(self.min_weight, min(self.max_boost_weight, new_weight))

        return new_weight

    def record_memory_access(
        self,
        memory: Dict,
        user_arousal: float = 0.5,
        apply_boost: bool = True
    ) -> bool:
        """
        [FIXED-M5] 記錄記憶訪問並更新統計

        Args:
            memory: 記憶字典
            user_arousal: 當前用戶喚醒度
            apply_boost: 是否應用激活提升

        Returns:
            是否成功更新
        """
        if not memory:
            return False

        try:
            current_time = self._get_current_time()
            current_time_str = current_time.isoformat()

            # [FIXED-M5] 更新訪問時間
            memory['last_accessed'] = current_time_str

            # [FIXED-M5] 更新訪問計數
            access_count = memory.get('access_count', 0)
            if not isinstance(access_count, int):
                access_count = 0
            access_count = min(access_count + 1, self.MAX_ACCESS_COUNT)
            memory['access_count'] = access_count

            # [FIXED-M5] 初始化訪問歷史
            if 'access_history' not in memory:
                memory['access_history'] = []

            access_history = memory['access_history']
            if not isinstance(access_history, list):
                access_history = []

            # 限制歷史記錄大小 (保留最近 100 次訪問)
            if len(access_history) >= 100:
                access_history = access_history[-99:]

            access_history.append({
                'timestamp': current_time_str,
                'arousal': user_arousal
            })

            memory['access_history'] = access_history

            # [FIXED-M2] 應用激活提升
            if apply_boost:
                old_weight = memory.get('weight', 2.0)
                new_weight = self.calculate_activation_boost(
                    old_weight,
                    user_arousal
                )
                memory['weight'] = new_weight

                self.logger.debug(
                    f"Boosted memory {memory.get('id', 'unknown')}: "
                    f"{old_weight:.3f} -> {new_weight:.3f} "
                    f"(access_count: {access_count})"
                )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to record access for memory {memory.get('id', 'unknown')}: {e}"
            )
            return False

    def record_rumination(self, memory: Dict) -> bool:
        """
        [FIXED-M5] 記錄反芻思考 (用戶重複思考該記憶)

        增加記憶權重以模擬反覆回想的強化效果

        Args:
            memory: 記憶字典

        Returns:
            是否成功
        """
        if not memory:
            return False

        try:
            old_weight = memory.get('weight', 2.0)
            new_weight = old_weight * self.rumination_multiplier

            # [FIXED-M9] 權重溢出保護
            new_weight = min(self.max_boost_weight, new_weight)

            memory['weight'] = new_weight

            # [FIXED-M5] 記錄反芻事件
            memory['rumination_count'] = memory.get('rumination_count', 0) + 1
            memory['last_ruminated_at'] = self._get_current_time().isoformat()

            self.logger.debug(
                f"Recorded rumination for {memory.get('id', 'unknown')}: "
                f"{old_weight:.3f} -> {new_weight:.3f}"
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to record rumination for {memory.get('id', 'unknown')}: {e}"
            )
            return False

    # ==================== 記憶清理與維護 ====================

    def cleanup_old_memories(
        self,
        memories: List[Dict],
        max_age_days: int = MAX_AGE_DAYS,
        min_weight_threshold: float = 0.6
    ) -> Tuple[int, int]:
        """
        [FIXED-M8] 清理過期或低質量記憶

        策略：
        - 超過最大年齡的記憶標記為歸檔
        - 權重低於閾值且年齡大的記憶標記為歸檔
        - 已歸檔記憶不再處理

        Args:
            memories: 記憶列表
            max_age_days: 最大年齡 (天)
            min_weight_threshold: 最小權重閾值

        Returns:
            (歸檔計數, 跳過計數)
        """
        if not memories:
            return 0, 0

        current_time = self._get_current_time()
        archived_count = 0
        skipped_count = 0

        for memory in memories:
            # [FIXED-M8] 檢查狀態
            if memory.get('archived', False):
                skipped_count += 1
                continue

            if memory.get('locked', False) or memory.get('protected', False):
                skipped_count += 1
                continue

            try:
                creation_time_str = memory.get('timestamp', '')
                creation_time = self._parse_datetime(creation_time_str)

                if creation_time is None:
                    continue

                age_days = self._calculate_time_delta_days(
                    creation_time, current_time
                )

                weight = memory.get('weight', 2.0)

                # 歸檔條件 1: 超過最大年齡
                if age_days > max_age_days:
                    memory['archived'] = True
                    memory['archived_at'] = current_time.isoformat()
                    memory['archive_reason'] = 'max_age_exceeded'
                    archived_count += 1
                    continue

                # 歸檔條件 2: 低權重 + 年齡 > 180 天
                if weight < min_weight_threshold and age_days > 180:
                    memory['archived'] = True
                    memory['archived_at'] = current_time.isoformat()
                    memory['archive_reason'] = 'low_weight_old_age'
                    archived_count += 1
                    continue

            except Exception as e:
                self.logger.debug(
                    f"Cleanup check failed for {memory.get('id', 'unknown')}: {e}"
                )

        if archived_count > 0:
            self.logger.info(
                f"Archived {archived_count} old memories "
                f"(skipped: {skipped_count})"
            )

        return archived_count, skipped_count

    # ==================== 統計與分析 ====================

    def get_memory_statistics(
        self,
        memories: List[Dict]
    ) -> Dict:
        """
        [FIXED-M10] 計算記憶統計信息

        Args:
            memories: 記憶列表

        Returns:
            統計信息字典
        """
        if not memories:
            return {
                'total': 0,
                'active': 0,
                'archived': 0,
                'avg_weight': 0.0,
                'avg_age_days': 0.0,
                'avg_access_count': 0.0,
                'high_weight_count': 0,
                'low_weight_count': 0,
            }

        active_memories = [m for m in memories if not m.get('archived', False)]
        archived_memories = [m for m in memories if m.get('archived', False)]

        if not active_memories:
            return {
                'total': len(memories),
                'active': 0,
                'archived': len(archived_memories),
                'avg_weight': 0.0,
                'avg_age_days': 0.0,
                'avg_access_count': 0.0,
                'high_weight_count': 0,
                'low_weight_count': 0,
            }

        current_time = self._get_current_time()
        weights = []
        ages = []
        access_counts = []

        for mem in active_memories:
            try:
                weight = float(mem.get('weight', 2.0))
                weights.append(weight)

                creation_time = self._parse_datetime(mem.get('timestamp', ''))
                if creation_time:
                    age = self._calculate_time_delta_days(creation_time, current_time)
                    ages.append(age)

                access_count = int(mem.get('access_count', 0))
                access_counts.append(access_count)

            except (ValueError, TypeError):
                continue

        return {
            'total': len(memories),
            'active': len(active_memories),
            'archived': len(archived_memories),
            'avg_weight': sum(weights) / len(weights) if weights else 0.0,
            'max_weight': max(weights) if weights else 0.0,
            'min_weight': min(weights) if weights else 0.0,
            'avg_age_days': sum(ages) / len(ages) if ages else 0.0,
            'avg_access_count': sum(access_counts) / len(access_counts) if access_counts else 0.0,
            'high_weight_count': sum(1 for w in weights if w > 2.5),
            'low_weight_count': sum(1 for w in weights if w < 1.0),
            'total_access_count': sum(access_counts),
        }

    def identify_ruminating_memories(
        self,
        memories: List[Dict],
        min_rumination_count: int = 3
    ) -> List[Dict]:
        """
        [FIXED-M10] 識別反芻記憶 (被重複思考的記憶)

        Args:
            memories: 記憶列表
            min_rumination_count: 最小反芻次數

        Returns:
            反芻記憶列表
        """
        ruminating = []

        for mem in memories:
            if mem.get('archived', False):
                continue

            rumination_count = mem.get('rumination_count', 0)
            if rumination_count >= min_rumination_count:
                ruminating.append({
                    'id': mem.get('id'),
                    'rumination_count': rumination_count,
                    'weight': mem.get('weight', 0.0),
                    'last_ruminated_at': mem.get('last_ruminated_at'),
                })

        # 按反芻次數排序
        ruminating.sort(
            key=lambda x: x['rumination_count'],
            reverse=True
        )

        return ruminating

    def identify_traumatic_memories(
        self,
        memories: List[Dict],
        arousal_threshold: float = 0.7,
        valence_threshold: float = -0.5
    ) -> List[Dict]:
        """
        [FIXED-M10] 識別創傷記憶 (高喚醒度 + 負面效價)

        Args:
            memories: 記憶列表
            arousal_threshold: 喚醒度閾值
            valence_threshold: 效價閾值

        Returns:
            創傷記憶列表
        """
        traumatic = []

        for mem in memories:
            if mem.get('archived', False):
                continue

            emotions = mem.get('user_sentiment', {})
            arousal = float(emotions.get('arousal', 0.0))
            valence = float(emotions.get('valence', 0.0))

            if arousal >= arousal_threshold and valence <= valence_threshold:
                traumatic.append({
                    'id': mem.get('id'),
                    'arousal': arousal,
                    'valence': valence,
                    'weight': mem.get('weight', 0.0),
                    'timestamp': mem.get('timestamp'),
                })

        traumatic.sort(
            key=lambda x: x['weight'],
            reverse=True
        )

        return traumatic

    # ==================== 健康檢查 ====================

    def health_check(self, memories: List[Dict]) -> Dict:
        """
        [FIXED-M10] 執行系統健康檢查

        Args:
            memories: 記憶列表

        Returns:
            健康狀態報告
        """
        issues = []
        stats = self.get_memory_statistics(memories)

        # 檢查 1: 記憶數量
        if stats['total'] == 0:
            issues.append("No memories stored")

        # 檢查 2: 平均權重
        if stats['avg_weight'] < self.min_weight * 1.5:
            issues.append(
                f"Average weight too low ({stats['avg_weight']:.3f}), "
                f"consider memory refresh"
            )

        # 檢查 3: 高權重記憶數量
        if stats['high_weight_count'] == 0 and stats['active'] > 0:
            issues.append("No high-weight memories detected")

        # 檢查 4: 訪問不足
        if stats['total_access_count'] == 0 and stats['active'] > 0:
            issues.append("Memories not being accessed")

        status = (
            "healthy"
            if not issues
            else "warning" if len(issues) == 1
            else "critical"
        )

        return {
            'status': status,
            'issues': issues,
            'statistics': stats,
            'check_timestamp': self._get_current_time().isoformat(),
        }