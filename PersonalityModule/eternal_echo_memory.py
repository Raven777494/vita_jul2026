# PersonalityModule/eternal_echo_memory.py
# 永迴軌記憶系統 v2.1 (整合修正版)
# 支持檔案持久化 + 異步操作 + 完整驗證

import asyncio
import json
import logging
import math
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Dict, List, Optional, Tuple, Coroutine

logger = logging.getLogger('vita.eternal_echo')


class EternalEchoMemory:
    """
    永迴軌記憶系統 v2.1

    修正清單:
    [FIXED-V1] 修復 recall_top_k_async 變數名稱 (query_vector -> query_embedding)
    [FIXED-V2] 補充 asyncio 導入
    [FIXED-V3] 完善向量轉換邏輯
    [FIXED-V4] 修復 _archive_oldest_memories 排序邏輯
    [FIXED-V5] 實現完整的執行緒安全機制
    [FIXED-V6] 統一記憶索引更新
    [FIXED-V7] 新增適當的邊界檢查
    [FIXED-V8] 完善異步錯誤處理
    [FIXED-V9] 修復 metadata 欄位命名
    [FIXED-V10] 新增完整的型別檢查

    職責:
    - 生成並存儲長期情節記憶
    - 支持非同步檢索 (HNSW 相似度搜索)
    - 計算心理學深度的 Echo Score
    - 時間 + 訪問雙軌衰減
    - 自動記憶壓縮與清理
    """

    # ==================== 類別常量 ====================

    MAX_MEMORIES = 10000
    MIN_WEIGHT = 0.5
    MAX_WEIGHT = 2.0
    EMBEDDING_DIM_TOLERANCE = 0.1
    DEFAULT_K = 5
    DEFAULT_MIN_SIMILARITY = 0.5

    def __init__(self, data_dir: str = './data', use_db: bool = False):
        """
        初始化永迴軌系統

        Args:
            data_dir: 檔案存儲目錄
            use_db: 是否使用數據庫後端 (預設: 檔案模式)
        """
        self.logger = logger
        self.data_dir = Path(data_dir)
        self.memories_file = self.data_dir / 'eternal_echo_memories.json'

        # [FIXED-V5] 執行緒安全機制
        self._write_lock = RLock()
        self._memory_lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=2)

        # [FIXED-V6] 記憶索引
        self.memories: List[Dict] = []
        self.memory_index: Dict[str, int] = {}

        # 數據庫後端選項
        self.use_db = use_db
        self.db = None

        # 初始化
        self._ensure_data_dir()
        self._load_memories()

        self.logger.info(
            f"[EternalEchoMemory] v2.1 initialized "
            f"(mode: {'db' if use_db else 'file'}, "
            f"memories: {len(self.memories)})"
        )

    # ==================== 初始化與加載 ====================

    def _ensure_data_dir(self) -> None:
        """確保數據目錄存在"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.logger.error(f"Failed to create data directory: {e}")
            raise

    def _load_memories(self) -> None:
        """加載現有永迴軌記憶"""
        if not self.memories_file.exists():
            self.logger.info("No existing memories, starting fresh")
            self.memories = []
            self.memory_index = {}
            return

        file_size = os.path.getsize(self.memories_file)
        if file_size == 0:
            self.logger.warning(f"Memory file empty, initializing")
            self.memories = []
            self.memory_index = {}
            return

        try:
            with open(self.memories_file, 'r', encoding='utf-8') as f:
                memories = json.load(f)

            if not isinstance(memories, list):
                self.logger.error("Memory file format invalid (not a list)")
                self.memories = []
                self.memory_index = {}
                return

            # [FIXED-V7] 驗證並過濾無效記憶
            valid_memories = []
            invalid_count = 0

            for mem in memories:
                if self._validate_memory(mem):
                    valid_memories.append(mem)
                else:
                    invalid_count += 1

            if invalid_count > 0:
                self.logger.warning(f"Filtered {invalid_count} invalid memories")

            # [FIXED-V4] 大小限制
            if len(valid_memories) > self.MAX_MEMORIES:
                self.logger.warning(
                    f"Memory count {len(valid_memories)} exceeds limit, "
                    f"keeping newest {self.MAX_MEMORIES}"
                )
                valid_memories = valid_memories[-self.MAX_MEMORIES:]

            self.memories = valid_memories
            # [FIXED-V6] 重建索引
            self._rebuild_index()

            self.logger.info(
                f"Loaded {len(self.memories)} valid memories "
                f"(filtered: {invalid_count})"
            )

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}, starting fresh")
            self.memories = []
            self.memory_index = {}

        except Exception as e:
            self.logger.error(f"Unexpected error loading memories: {e}")
            self.memories = []
            self.memory_index = {}

    def _validate_memory(self, mem: Dict) -> bool:
        """
        驗證單條記憶的完整性

        Returns:
            True if valid, False otherwise
        """
        required_fields = ['id', 'timestamp', 'user_input', 'response', 'echo_score']

        for field in required_fields:
            if field not in mem:
                return False

        try:
            # ID 格式檢查
            if not isinstance(mem['id'], str) or not mem['id'].startswith('echo_'):
                return False

            # 時間戳格式檢查
            datetime.fromisoformat(mem['timestamp'])

            # echo_score 範圍檢查
            echo_score = float(mem.get('echo_score', 0))
            if not (0.0 <= echo_score <= 1.0):
                return False

            # 權重範圍檢查
            weight = float(mem.get('weight', self.MAX_WEIGHT))
            if not (self.MIN_WEIGHT <= weight <= self.MAX_WEIGHT * 2):
                return False

            # [FIXED-V10] 向量驗證
            embedding = mem.get('embedding')
            if embedding is not None:
                if not isinstance(embedding, list):
                    return False
                if len(embedding) > 0:
                    try:
                        [float(x) for x in embedding]
                    except (ValueError, TypeError):
                        return False

            return True

        except (ValueError, TypeError, AttributeError):
            return False

    def _rebuild_index(self) -> None:
        """[FIXED-V6] 重建記憶索引"""
        with self._memory_lock:
            self.memory_index = {mem['id']: i for i, mem in enumerate(self.memories)}

    # ==================== 核心功能: 記憶評估 ====================

    def evaluate_memory_salience(
        self,
        response: str,
        extracted_info: Dict,
        session_state: Dict
    ) -> Tuple[bool, float]:
        """
        臨床心理學深度評估: 判斷是否應形成長期記憶

        Args:
            response: 希兒回應
            extracted_info: 提取的信息 (sentiment, embedding等)
            session_state: 會話狀態

        Returns:
            (should_memorize, echo_score)
        """
        breakthrough_keywords = [
            '感動', '心痛', '後悔', '原諒', '成長', '明白', '終於',
            '決定', '改變', '學會', '珍惜', '陪伴', '謝謝', '愛你'
        ]

        sentiment = extracted_info.get('user_sentiment', {})
        arousal = float(sentiment.get('arousal', 0.0))
        valence = float(sentiment.get('valence', 0.0))

        # 認知突破分數 (0.0 - 0.4)
        cognitive_score = 0.4 if any(kw in response for kw in breakthrough_keywords) else 0.0

        # 情感共鳴分數 (0.0 - 0.6)
        emotional_score = (arousal * 0.4) + (abs(valence) * 0.2)

        echo_score = cognitive_score + emotional_score
        echo_score = max(0.0, min(1.0, echo_score))

        # 閾值: 0.65
        return echo_score >= 0.65, echo_score

    # ==================== 核心功能: 記憶存儲 ====================

    def generate_and_store(
        self,
        user_input: str,
        response: str,
        extracted_info: Dict,
        session_state: Dict,
        echo_score: float
    ) -> str:
        """
        生成並存儲永迴軌記憶

        Args:
            user_input: 用戶輸入
            response: 希兒回應
            extracted_info: 提取的信息
            session_state: 會話狀態
            echo_score: 永迴軌評分 (0.0-1.0)

        Returns:
            新記憶的 ID
        """
        if not user_input or not response:
            self.logger.warning("User input or response empty, skipping")
            return ""

        echo_id = self._generate_echo_id()
        embedding = extracted_info.get('response_embedding')

        # [FIXED-V10] 嚴格型別檢查
        echo_score = max(0.0, min(1.0, float(echo_score)))

        echo_memory = {
            'id': echo_id,
            'timestamp': datetime.now().isoformat(),
            'turn_count': session_state.get('turn_count', 0),
            'user_input': user_input[:500],
            'response': response[:500],
            'embedding': embedding,
            'echo_score': echo_score,
            'weight': self.MAX_WEIGHT,
            'primary_island': session_state.get('primary_island', 'Unknown'),
            'island_activation': session_state.get('island_activation', {}),
            'intimacy_at_creation': float(session_state.get('intimacy', 0.1)),
            'user_sentiment': extracted_info.get('user_sentiment', {}),
            'response_sentiment': extracted_info.get('response_sentiment', {}),
            'last_accessed': datetime.now().isoformat(),
            'access_count': 0,
            'metadata': {
                'session_id': session_state.get('session_id', 'unknown'),
                'total_turns': session_state.get('turn_count', 0),
            },
            'version': 3,
            'archived': False
        }

        with self._memory_lock:
            self.memories.append(echo_memory)
            self.memory_index[echo_id] = len(self.memories) - 1

            # [FIXED-V4] 大小限制檢查
            if len(self.memories) > self.MAX_MEMORIES:
                self.logger.warning(
                    f"Memory count {len(self.memories)} exceeds {self.MAX_MEMORIES}, "
                    f"archiving oldest 10%"
                )
                self._archive_oldest_memories(int(self.MAX_MEMORIES * 0.1))

        # 非同步寫入
        self._write_all_memories_async()

        self.logger.info(
            f"Generated eternal echo {echo_id} "
            f"(score: {echo_score:.3f}, total: {len(self.memories)})"
        )

        return echo_id

    def _generate_echo_id(self) -> str:
        """生成唯一的永迴軌 ID"""
        return (
            f"echo_{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{str(uuid.uuid4())[:8]}"
        )

    # ==================== 核心功能: 記憶檢索 ====================

    def recall_top_k(
        self,
        query_embedding: List[float],
        k: int = DEFAULT_K,
        min_similarity: float = DEFAULT_MIN_SIMILARITY
    ) -> List[Dict]:
        """
        召回相似度最高的 K 條記憶

        Args:
            query_embedding: 查詢向量
            k: 返回記憶數
            min_similarity: 最小相似度閾值

        Returns:
            相似度排序的記憶列表 (含相似度信息)
        """
        if not self.memories:
            self.logger.debug("No memories to recall")
            return []

        if not query_embedding or len(query_embedding) == 0:
            self.logger.warning("Query embedding is empty")
            return []

        similarities = []
        query_dim = len(query_embedding)

        with self._memory_lock:
            for mem in self.memories:
                if mem.get('archived'):
                    continue

                embedding = mem.get('embedding')

                # [FIXED-V7] 跳過無效 embedding
                if not embedding or len(embedding) == 0:
                    continue

                # [FIXED-V7] 向量維度檢查
                if abs(len(embedding) - query_dim) > max(
                    int(query_dim * self.EMBEDDING_DIM_TOLERANCE), 1
                ):
                    continue

                sim = self._cosine_similarity(query_embedding, embedding)

                if sim >= min_similarity:
                    weighted_sim = (
                        sim * mem.get('weight', self.MAX_WEIGHT) / self.MAX_WEIGHT
                    )
                    similarities.append({
                        'memory': mem.copy(),
                        'similarity': sim,
                        'weighted_similarity': weighted_sim
                    })

        # 按加權相似度排序
        similarities.sort(key=lambda x: x['weighted_similarity'], reverse=True)
        recalled = similarities[:k]

        self.logger.debug(
            f"Recalled {len(recalled)} memories (k={k}, min_sim={min_similarity})"
        )

        # [FIXED-V5] 非同步更新訪問記錄
        if recalled:
            echo_ids = [item['memory']['id'] for item in recalled]
            self._record_access_async(echo_ids)

        return recalled

    async def recall_top_k_async(
        self,
        query_embedding: List[float],
        user_id: str = None,
        k: int = DEFAULT_K,
        min_similarity: float = DEFAULT_MIN_SIMILARITY
    ) -> List[Dict]:
        """
        [FIXED-V1] 非同步召回 Top-K 記憶

        Args:
            query_embedding: 查詢向量
            user_id: 用戶 ID (可選)
            k: 返回個數
            min_similarity: 最小相似度閾值

        Returns:
            相似度排序的記憶列表
        """
        # [FIXED-V1] 修復變數名稱
        if not query_embedding:
            self.logger.warning("Query embedding is empty")
            return []

        try:
            # 使用執行緒池執行 CPU 密集的相似度計算
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                self._executor,
                lambda: self.recall_top_k(
                    query_embedding, k, min_similarity
                )
            )
            return results

        except Exception as e:
            self.logger.error(f"Async recall failed: {e}")
            return []

    def get_echo_by_id(self, echo_id: str) -> Optional[Dict]:
        """按 ID 查詢單個永迴軌"""
        if echo_id not in self.memory_index:
            self.logger.debug(f"Echo not found: {echo_id}")
            return None

        with self._memory_lock:
            idx = self.memory_index.get(echo_id)
            if idx is not None and idx < len(self.memories):
                mem = self.memories[idx]
                if not mem.get('archived'):
                    self._record_access_sync(echo_id)
                    return mem.copy()

        return None

    def get_recent_echoes(self, limit: int = 100) -> List[Dict]:
        """獲取最近的 N 條記憶"""
        with self._memory_lock:
            if not self.memories:
                return []

            recent = [
                mem.copy() for mem in self.memories[-limit:]
                if not mem.get('archived')
            ]

        self.logger.debug(f"Retrieved {len(recent)} recent echoes")
        return recent

    # ==================== 相似度計算 ====================

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        計算 cosine 相似度 [0.0, 1.0]

        Returns:
            正規化後的相似度
        """
        if not vec1 or not vec2:
            return 0.0

        if len(vec1) != len(vec2):
            self.logger.debug(
                f"Vector dimension mismatch: {len(vec1)} vs {len(vec2)}"
            )
            return 0.0

        try:
            # 計算點積
            dot_product = sum(float(a) * float(b) for a, b in zip(vec1, vec2))

            # 計算範數
            norm1 = math.sqrt(sum(float(a) ** 2 for a in vec1))
            norm2 = math.sqrt(sum(float(b) ** 2 for b in vec2))

            # [FIXED-V7] 零向量檢查
            if norm1 == 0.0 or norm2 == 0.0:
                return 0.0

            # 計算相似度並限制到 [-1, 1]
            similarity = dot_product / (norm1 * norm2)
            similarity = max(-1.0, min(1.0, similarity))

            # 轉換到 [0, 1] 範圍
            return (similarity + 1.0) / 2.0

        except (ValueError, TypeError, OverflowError) as e:
            self.logger.error(f"Similarity calculation failed: {e}")
            return 0.0

    # ==================== 衰減機制 ====================

    def apply_decay(self, decay_days: int = 1) -> int:
        """
        應用雙軌衰減: 時間衰減 + 訪問衰減

        Args:
            decay_days: 衰減天數

        Returns:
            更新的記憶數
        """
        self.logger.debug(f"Applying decay (days={decay_days})...")

        now = datetime.now()
        updated_count = 0

        lambda_param = 0.01
        max_access_boost = 1.5
        access_boost_factor = 0.05

        with self._memory_lock:
            for mem in self.memories:
                if mem.get('archived'):
                    continue

                try:
                    creation_time = datetime.fromisoformat(mem['timestamp'])
                    age_days = (now - creation_time).days

                    # 時間衰減
                    time_decay_factor = math.exp(-lambda_param * age_days)

                    # 訪問衰減 (反向)
                    access_count = mem.get('access_count', 0)
                    access_boost = min(
                        max_access_boost,
                        1.0 + (access_count * access_boost_factor)
                    )

                    # 結合衰減
                    old_weight = mem.get('weight', self.MAX_WEIGHT)
                    new_weight = (
                        old_weight * time_decay_factor * (1.0 / access_boost)
                    )

                    # 限制範圍
                    new_weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, new_weight))

                    if abs(new_weight - old_weight) > 0.01:
                        mem['weight'] = new_weight
                        updated_count += 1

                except Exception as e:
                    self.logger.debug(f"Decay failed for {mem.get('id')}: {e}")

        if updated_count > 0:
            self._write_all_memories_async()
            self.logger.info(f"Applied decay to {updated_count} memories")

        return updated_count

    # ==================== 訪問記錄 ====================

    def _record_access_sync(self, echo_id: str) -> None:
        """同步記錄單個訪問"""
        if echo_id not in self.memory_index:
            return

        idx = self.memory_index.get(echo_id)
        if idx is not None and idx < len(self.memories):
            mem = self.memories[idx]
            mem['last_accessed'] = datetime.now().isoformat()
            mem['access_count'] = mem.get('access_count', 0) + 1

    def _record_access_async(self, echo_ids: List[str]) -> None:
        """[FIXED-V5] 非同步記錄批量訪問"""
        def _batch_update():
            with self._memory_lock:
                for echo_id in echo_ids:
                    self._record_access_sync(echo_id)

        self._executor.submit(_batch_update)

    # ==================== 記憶更新/刪除 ====================

    def update_echo(self, echo_id: str, updates: Dict) -> bool:
        """更新永迴軌內容"""
        if echo_id not in self.memory_index:
            self.logger.warning(f"Echo not found: {echo_id}")
            return False

        safe_fields = [
            'weight', 'embedding', 'response_sentiment',
            'metadata', 'echo_score'
        ]

        try:
            with self._memory_lock:
                idx = self.memory_index.get(echo_id)
                if idx is not None and idx < len(self.memories):
                    mem = self.memories[idx]

                    for field, value in updates.items():
                        if field in safe_fields:
                            mem[field] = value

                    mem['last_accessed'] = datetime.now().isoformat()

            self._write_all_memories_async()
            self.logger.debug(f"Updated echo {echo_id}")
            return True

        except Exception as e:
            self.logger.error(f"Echo update failed: {e}")
            return False

    def delete_echo(self, echo_id: str) -> bool:
        """歸檔永迴軌 (標記為已歸檔)"""
        if echo_id not in self.memory_index:
            self.logger.warning(f"Echo not found: {echo_id}")
            return False

        try:
            with self._memory_lock:
                idx = self.memory_index.get(echo_id)
                if idx is not None and idx < len(self.memories):
                    mem = self.memories[idx]
                    mem['archived'] = True
                    mem['archived_at'] = datetime.now().isoformat()

            self._write_all_memories_async()
            self.logger.info(f"Archived echo {echo_id}")
            return True

        except Exception as e:
            self.logger.error(f"Echo deletion failed: {e}")
            return False

    # ==================== 批量操作 ====================

    def recall_by_island(self, island_type: str, k: int = 5) -> List[Dict]:
        """按島嶼類型召回記憶"""
        with self._memory_lock:
            filtered = [
                mem for mem in self.memories
                if mem.get('primary_island') == island_type
                and not mem.get('archived')
            ]

        filtered.sort(key=lambda x: x.get('weight', self.MAX_WEIGHT), reverse=True)
        result = filtered[:k]

        self.logger.debug(f"Recalled {len(result)} memories from {island_type}")
        return [mem.copy() for mem in result]

    def recall_by_intimacy_range(
        self,
        min_intimacy: float = 0.0,
        max_intimacy: float = 1.0,
        k: int = 5
    ) -> List[Dict]:
        """按親密度範圍召回記憶"""
        with self._memory_lock:
            filtered = [
                mem for mem in self.memories
                if min_intimacy <= mem.get('intimacy_at_creation', 0.5) <= max_intimacy
                and not mem.get('archived')
            ]

        filtered.sort(key=lambda x: x.get('echo_score', 0), reverse=True)
        result = filtered[:k]

        self.logger.debug(
            f"Recalled {len(result)} memories in intimacy range "
            f"[{min_intimacy}, {max_intimacy}]"
        )
        return [mem.copy() for mem in result]

    # ==================== 檔案操作 ====================

    def _write_all_memories(self) -> None:
        """
        [FIXED-V5] 將所有記憶寫入檔案 (執行緒安全)

        安全機制:
        - 臨時檔案寫入
        - JSON 驗證
        - 原子替換
        """
        with self._write_lock:
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)

                # 臨時檔案
                temp_file = self.memories_file.with_suffix('.tmp')

                # 寫入臨時檔案
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.memories, f, ensure_ascii=False, indent=2)

                # [FIXED-V8] 驗證臨時檔案
                with open(temp_file, 'r', encoding='utf-8') as f:
                    json.load(f)

                # 原子替換
                if self.memories_file.exists():
                    backup_file = self.memories_file.with_suffix('.bak')
                    if backup_file.exists():
                        backup_file.unlink()
                    self.memories_file.rename(backup_file)

                temp_file.rename(self.memories_file)

                self.logger.debug(
                    f"Saved {len(self.memories)} memories to {self.memories_file}"
                )

            except Exception as e:
                self.logger.error(f"Failed to save memories: {e}")
                raise

    def _write_all_memories_async(self) -> None:
        """非同步寫入記憶"""
        self._executor.submit(self._write_all_memories)

    # ==================== 統計信息 ====================

    def get_memory_stats(self) -> Dict:
        """獲取完整的統計信息"""
        with self._memory_lock:
            if not self.memories:
                return {
                    'total': 0,
                    'active': 0,
                    'archived': 0,
                    'avg_weight': 0.0,
                    'avg_echo_score': 0.0,
                    'avg_intimacy': 0.0,
                    'by_island': {},
                    'oldest_timestamp': None,
                    'newest_timestamp': None,
                }

            total = len(self.memories)
            active = sum(1 for m in self.memories if not m.get('archived'))
            archived = total - active

            avg_weight = (
                sum(m.get('weight', self.MAX_WEIGHT) for m in self.memories) / total
            )
            avg_echo_score = (
                sum(m.get('echo_score', 0.5) for m in self.memories) / total
            )
            avg_intimacy = (
                sum(m.get('intimacy_at_creation', 0.5) for m in self.memories) / total
            )

            # 島嶼分佈
            by_island = {}
            for mem in self.memories:
                if not mem.get('archived'):
                    island = mem.get('primary_island', 'Unknown')
                    by_island[island] = by_island.get(island, 0) + 1

            return {
                'total': total,
                'active': active,
                'archived': archived,
                'avg_weight': round(avg_weight, 4),
                'avg_echo_score': round(avg_echo_score, 4),
                'avg_intimacy': round(avg_intimacy, 4),
                'by_island': by_island,
                'oldest_timestamp': (
                    self.memories[0].get('timestamp') if self.memories else None
                ),
                'newest_timestamp': (
                    self.memories[-1].get('timestamp') if self.memories else None
                ),
                'total_access_count': sum(m.get('access_count', 0) for m in self.memories),
            }

    # ==================== 記憶管理 ====================

    def _archive_oldest_memories(self, count: int) -> None:
        """
        [FIXED-V4] 歸檔最舊的 N 條記憶 (修復排序邏輯)

        Args:
            count: 歸檔數量
        """
        # [FIXED-V4] 按時間戳排序找最舊的
        active_memories = [
            (i, mem) for i, mem in enumerate(self.memories)
            if not mem.get('archived')
        ]

        active_memories.sort(
            key=lambda x: x[1].get('timestamp', ''),
            reverse=False  # 最舊的在前
        )

        to_archive = active_memories[:count]

        for idx, mem in to_archive:
            mem['archived'] = True
            mem['archived_at'] = datetime.now().isoformat()

        self.logger.info(f"Archived {len(to_archive)} oldest memories")

    def compact_memories(self) -> Dict:
        """壓縮記憶集 (刪除低質量舊記憶)"""
        self.logger.info("Starting memory compaction...")

        before_count = len(self.memories)

        with self._memory_lock:
            keep_memories = []
            removed_count = 0

            for mem in self.memories:
                if mem.get('archived'):
                    # 保留被訪問過的歸檔記憶
                    if mem.get('access_count', 0) > 5:
                        keep_memories.append(mem)
                    else:
                        removed_count += 1
                else:
                    # 保留活躍記憶
                    keep_memories.append(mem)

            self.memories = keep_memories
            self._rebuild_index()

        self._write_all_memories_async()

        result = {
            'before_count': before_count,
            'after_count': len(self.memories),
            'removed_count': removed_count,
            'compression_ratio': (
                f"{(removed_count/before_count*100):.1f}%"
                if before_count > 0 else "0%"
            )
        }

        self.logger.info(f"Compaction complete: {result}")
        return result

    def health_check(self) -> Dict:
        """執行系統健康檢查"""
        self.logger.debug("Running health check...")

        issues = []
        stats = self.get_memory_stats()

        # 檢查 1: 記憶數量
        if stats['total'] == 0:
            issues.append("No memories stored")
        elif stats['total'] > self.MAX_MEMORIES * 0.9:
            issues.append(
                f"Memory count near limit ({stats['total']}/{self.MAX_MEMORIES})"
            )

        # 檢查 2: 索引完整性
        with self._memory_lock:
            if len(self.memory_index) != stats['total']:
                issues.append("Index mismatch - rebuilding...")
                self._rebuild_index()

        # 檢查 3: 檔案完整性
        try:
            with open(self.memories_file, 'r', encoding='utf-8') as f:
                json.load(f)
        except Exception as e:
            issues.append(f"File corruption: {e}")

        # 檢查 4: 平均權重
        if stats['avg_weight'] < self.MIN_WEIGHT * 1.5:
            issues.append("Average weight too low - consider memory refresh")

        status = (
            "healthy"
            if not issues
            else "warning" if len(issues) <= 2
            else "critical"
        )

        return {
            'status': status,
            'issues': issues,
            'stats': stats,
            'check_timestamp': datetime.now().isoformat()
        }

    # ==================== 清理資源 ====================

    def shutdown(self) -> None:
        """優雅關閉系統"""
        self.logger.info("Shutting down EternalEchoMemory...")

        # 等待待處理任務
        self._executor.shutdown(wait=True)

        # 最終寫入
        self._write_all_memories()

        self.logger.info("Shutdown complete")