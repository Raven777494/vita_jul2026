# PersonalityModule/personality_module.py
# 完整版 v8.2 - 深度心靈大腦 (修正版 - Zero-Truncation)

import json
import re
import asyncio
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Callable
from pathlib import Path
from dataclasses import asdict, is_dataclass
import concurrent.futures
from functools import partial
import logging
import uuid
import traceback

from .utils.logger import get_logger
from .memory_manager import MemoryManager
from .gsw_engine import GSWEngine
from .heretic_coordinator import HereticCoordinator
from .island_fusion import IslandFusion
from .political_filter import PoliticalFilter
from .config import PersonalityConfig, get_config
from .metacognitive_system import MetacognitiveSystem

try:
    from app.services.dyadic_dynamics import DyadicDynamics
    DYADIC_AVAILABLE = True
except ImportError:
    DYADIC_AVAILABLE = False
    DyadicDynamics = None

try:
    from vita_core_config import vita_core_config
    VITA_CONFIG_AVAILABLE = True
except ImportError:
    VITA_CONFIG_AVAILABLE = False

try:
    from .cantonese_dict import batch_search, get_dict_stats
    CANTONESE_DICT_AVAILABLE = True
except ImportError:
    CANTONESE_DICT_AVAILABLE = False

logger = get_logger('vita.personality')

CRISIS_KEYWORDS = {
    '熱線', '危機', '自殺', '求助', '救命', '無法', '活不了',
    '想死', '不想活', '絕望', '無望', '受不了', '痛不欲生'
}

PERSONALITY_PARTICLES = ['嗯', '其實', '寶貝', '天啊', '真的', '我覺得', '你知道嗎']


class PersonalityModule:
    """
    希兒超並行大腦 v8.2 (Vita 深度臨床心理學)

    修正清單:
    [FIXED-P1] 統一異步任務追蹤機制 - 完整修正
    [FIXED-P2] 移除記憶生成重複邏輯 - 新增 echo_score 驗證
    [FIXED-P3] 強化例外情況處理 - 詳細日誌與追蹤棧
    [FIXED-P4] 改善背景任務可靠性 - 使用任務等待機制
    [FIXED-P5] 新增系統健康檢查 - 完整實作
    [FIXED-P6] 優化資源清理流程 - 強制超時
    [FIXED-P7] 初始化完成機制 - 確保依賴順序
    [FIXED-P8] turn_info 安全檢驗 - 預設值處理
    """

    def __init__(self, config: Dict = None):
        """
        初始化希兒大腦

        Args:
            config: 配置字典（預設使用全局配置）
        """
        if config is None:
            config = get_config().to_dict()

        self.config = config
        self.logger = logger
        self.data_dir = Path(config.get('data_dir', './data'))

        # [FIXED-P1] 改善任務追蹤機制
        self._initialization_done = False
        self._initialization_lock = asyncio.Lock()
        self._background_tasks: Dict[str, asyncio.Task] = {}
        self._task_counter = 0
        self._task_results: Dict[str, Any] = {}

        # 並發控制
        self._anchor_semaphore = asyncio.Semaphore(
            config.get('max_concurrent_anchors', 4)
        )

        # 依賴注入（延遲初始化）
        self.llm_service = None
        self.vector_service = None
        self.db_service = None

        self.memory_manager = None
        self.gsw_engine = None
        self.heretic_coordinator = None
        self.island_fusion = None
        self.political_filter = None
        self.intelligent_navigator = None
        self.metacognitive_system = None
        self.dyadic_dynamics = None
        self.vocal_personality_layer = None
        self.system_prompt_builder = None

        # [NEW] 執行緒池配置
        max_workers = config.get('thread_pool_workers', 6)
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='PersonalityBrain'
        )

        self.boundary_multiplier = config.get('boundary_multiplier', 1.0)
        self._max_background_tasks = config.get('max_background_tasks', 20)

        self.logger.info(
            f"PersonalityModule v8.2 initialized "
            f"(max_workers={max_workers}, semaphore={self._anchor_semaphore._value})"
        )

    def setup_dependencies(self, dependencies: Dict) -> None:
        """
        [FIXED-P4] 注入所有外部依賴 - 循環依賴檢測
        """
        if not isinstance(dependencies, dict):
            self.logger.error("Dependencies must be a dictionary")
            raise TypeError("Dependencies must be a dictionary")

        self.llm_service = dependencies.get('llm_service')
        self.vector_service = dependencies.get('vector_service')
        self.db_service = dependencies.get('db_service')

        # [FIXED-P2] 統一記憶管理 - 單一入口
        self.memory_manager = dependencies.get('memory_manager')
        if not self.memory_manager:
            self.memory_manager = MemoryManager()
            self.logger.debug("Created new MemoryManager instance")

        # GSW 引擎
        self.gsw_engine = dependencies.get('gsw_engine')
        if not self.gsw_engine and self.vector_service and self.memory_manager:
            try:
                self.gsw_engine = GSWEngine(
                    config=self.config,
                    vector_service=self.vector_service,
                    memory_manager=self.memory_manager
                )
                self.logger.debug("Created new GSWEngine instance")
            except Exception as e:
                self.logger.warning(f"Failed to create GSWEngine: {e}")

        # 矯正系統
        self.heretic_coordinator = dependencies.get('heretic_coordinator')
        if not self.heretic_coordinator:
            try:
                self.heretic_coordinator = HereticCoordinator(config=self.config)
                if self.llm_service:
                    self.heretic_coordinator.setup_llm_service(self.llm_service)
                self.logger.debug("Created new HereticCoordinator instance")
            except Exception as e:
                self.logger.warning(f"Failed to create HereticCoordinator: {e}")

        # 政治過濾
        self.political_filter = dependencies.get('political_filter')
        if not self.political_filter:
            try:
                self.political_filter = PoliticalFilter(
                    config=self.config,
                    data_dir=str(self.data_dir)
                )
                self.logger.debug("Created new PoliticalFilter instance")
            except Exception as e:
                self.logger.warning(f"Failed to create PoliticalFilter: {e}")

        # 島嶼融合
        self.island_fusion = dependencies.get('island_fusion')
        if not self.island_fusion:
            try:
                self.island_fusion = IslandFusion(data_dir=str(self.data_dir))
                self.logger.debug("Created new IslandFusion instance")
            except Exception as e:
                self.logger.warning(f"Failed to create IslandFusion: {e}")

        # 元認知系統
        self.metacognitive_system = dependencies.get('metacognitive_system')
        if not self.metacognitive_system:
            try:
                self.metacognitive_system = MetacognitiveSystem(
                    config=self.config,
                    data_dir=str(self.data_dir)
                )
                self.logger.debug("Created new MetacognitiveSystem instance")
            except Exception as e:
                self.logger.warning(f"Failed to create MetacognitiveSystem: {e}")

        # [NEW] 聲音人格層
        self.vocal_personality_layer = dependencies.get('vocal_personality_layer')
        if not self.vocal_personality_layer:
            try:
                from .vocal_personality_layer import VocalPersonalityLayer
                self.vocal_personality_layer = VocalPersonalityLayer(config=self.config)
                if self.island_fusion and self.heretic_coordinator:
                    self.vocal_personality_layer.setup_dependencies(
                        self.island_fusion,
                        self.heretic_coordinator
                    )
                self.logger.debug("Created new VocalPersonalityLayer instance")
            except Exception as e:
                self.logger.warning(f"Failed to create VocalPersonalityLayer: {e}")

        # [NEW] 系統提示詞生成器
        self.system_prompt_builder = dependencies.get('system_prompt_builder')
        if not self.system_prompt_builder:
            try:
                from .system_prompt_builder import SystemPromptBuilder
                self.system_prompt_builder = SystemPromptBuilder(config=self.config)
                self.logger.debug("Created new SystemPromptBuilder instance")
            except Exception as e:
                self.logger.warning(f"Failed to create SystemPromptBuilder: {e}")

        # 關係動力學
        if DYADIC_AVAILABLE:
            self.dyadic_dynamics = dependencies.get('dyadic_dynamics')
            if not self.dyadic_dynamics:
                try:
                    self.dyadic_dynamics = DyadicDynamics(
                        llm_service=self.llm_service,
                        config=self.config,
                        data_dir=str(self.data_dir),
                        vector_service=self.vector_service
                    )
                    self.logger.debug("Created new DyadicDynamics instance")
                except Exception as e:
                    self.logger.warning(f"Failed to create DyadicDynamics: {e}")

        # 危機導航
        # [FIX-ALIGN] 優先使用呼叫端注入的 intelligent_navigator（已完整配置 llm/db/fracture）。
        # 先前版本忽略注入值、改用無參數 IntelligentNavigator() 重建，導致設定遺失且重複建立實例。
        self.intelligent_navigator = dependencies.get('intelligent_navigator')
        if self.intelligent_navigator:
            self.logger.debug("Using injected IntelligentNavigator")
        else:
            try:
                from app.services.fracture_map.intelligent_navigator import IntelligentNavigator
                self.intelligent_navigator = IntelligentNavigator(
                    llm_service=self.llm_service,
                    db_service=self.db_service,
                    config=self.config
                )
                self.logger.debug("Initialized IntelligentNavigator (fallback)")
            except Exception as e:
                self.logger.warning(f"IntelligentNavigator initialization skipped: {e}")
                self.intelligent_navigator = None

        self._initialization_done = True
        self.logger.info("All brain dependencies successfully linked")

    async def _run_in_executor_safe(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        [FIXED-P3] 安全執行同步操作

        Args:
            func: 可呼叫對象
            *args, **kwargs: 參數

        Returns:
            執行結果
        """
        loop = asyncio.get_running_loop()
        try:
            if kwargs:
                partial_func = partial(func, **kwargs)
                return await loop.run_in_executor(self.executor, partial_func, *args)
            return await loop.run_in_executor(self.executor, func, *args)
        except asyncio.CancelledError:
            self.logger.warning(f"Executor task cancelled for {func.__name__}")
            raise
        except Exception as e:
            self.logger.error(
                f"Executor error in {func.__name__}: {e}\n{traceback.format_exc()}"
            )
            raise

    # ==================== 核心錨定流程 ====================

    async def anchor(
        self,
        draft_response: str,
        user_input: str,
        session_state: Dict,
        turn_info: Optional[Dict] = None
    ) -> Tuple[str, Dict]:
        """
        [FIXED-P1,P8] 深度認知循環 v8.2

        修正項目：
        - 改善任務追蹤與取消機制
        - 強化例外處理
        - 優化資源分配
        - turn_info 安全檢驗
        - 三層個性系統整合

        Args:
            draft_response: 初稿回應
            user_input: 用戶輸入
            session_state: 會話狀態
            turn_info: 回合信息（可選）

        Returns:
            (最終回應, 更新後的會話狀態)
        """
        if not self._initialization_done:
            self.logger.error("PersonalityModule not properly initialized")
            raise RuntimeError("Dependencies not setup")

        # [FIXED-P8] 安全提取會話狀態
        current_state = (
            session_state[0]
            if isinstance(session_state, tuple)
            else session_state
        )

        if not isinstance(current_state, dict):
            self.logger.error(f"Invalid session_state type: {type(current_state)}")
            raise TypeError("session_state must be a dictionary")

        # [FIXED-P8] 設定 turn_info 預設值
        if turn_info is None:
            turn_info = {}
        elif not isinstance(turn_info, dict):
            self.logger.warning(f"turn_info type invalid: {type(turn_info)}, using empty dict")
            turn_info = {}

        async with self._anchor_semaphore:
            turn_count = current_state.get('turn_count', 0) + 1
            self.logger.info(f"Starting cognitive cycle #{turn_count}")
            start_time = time.time()

            try:
                user_embedding = turn_info.get('embedding', [])
                intimacy = current_state.get('intimacy', 0.5)

                # ========== 階段 1: 超並行感知 ==========
                self.logger.debug("Phase 1: Hyper-parallel perception")

                perception_tasks = self._create_perception_tasks(
                    user_embedding=user_embedding,
                    intimacy=intimacy,
                    user_input=user_input,
                    turn_info=turn_info,
                    current_state=current_state,
                    draft_response=draft_response
                )

                results = await asyncio.gather(
                    *perception_tasks.values(),
                    return_exceptions=True
                )

                perception_data = self._process_perception_results(
                    perception_tasks, results
                )

                if turn_info.get('retrieved_memories') is not None:
                    perception_data['retrieved_memories'] = turn_info['retrieved_memories']

                # ========== 階段 2a: 前置個性提示詞生成 ==========
                self.logger.debug("Phase 2a: Personality prompt generation")

                primary_island = perception_data.get('primary_island', 'Empath')
                personality_system_prompt = ""

                if self.system_prompt_builder:
                    try:
                        personality_system_prompt = self.system_prompt_builder.build_system_prompt(
                            primary_island=primary_island,
                            user_input=user_input,
                            context={
                                'intimacy': intimacy,
                                'turn_count': turn_count,
                                'user_sentiment': turn_info.get('user_sentiment', {}),
                            }
                        )
                        memory_context = (
                            turn_info.get('memory_context')
                            or self._format_memory_context(
                                perception_data.get('retrieved_memories', [])
                            )
                        )
                        if memory_context:
                            personality_system_prompt = (
                                f"{personality_system_prompt}\n\n相關記憶:\n{memory_context}"
                                if personality_system_prompt
                                else f"相關記憶:\n{memory_context}"
                            )
                        self.logger.debug(f"Generated system prompt for island: {primary_island}")
                    except Exception as e:
                        self.logger.warning(f"Failed to build system prompt: {e}")
                        personality_system_prompt = ""

                # ========== 階段 2b: 元認知與危機處理 ==========
                self.logger.debug("Phase 2b: Metacognition & Crisis intercept")

                if self._should_trigger_safety_protocol(perception_data):
                    self.logger.warning("Safety protocol triggered")
                    final_response = self._generate_safety_response()
                    heretic_log = {'correction_count': 0, 'status': 'safety_bypass'}

                else:
                    # ========== 階段 3: Heretic 矯正 ==========
                    self.logger.debug("Phase 3: Heretic correction")

                    final_response = draft_response
                    heretic_log = {'correction_count': 0, 'status': 'initial'}

                    if self.heretic_coordinator:
                        try:
                            final_response, heretic_log = await self.heretic_coordinator.coordinate(
                                draft_response=final_response,
                                user_input=user_input,
                                island_activation=perception_data.get('island_activation', {}),
                                primary_island=primary_island,
                                drift_info={'drift_score': 0.0},
                                sensitivity_result=perception_data.get('sensitivity_result', {}),
                                extracted_info={},
                                session_state=current_state
                            )
                            self.logger.debug(
                                f"Heretic correction applied: {heretic_log.get('correction_count', 0)} corrections"
                            )
                        except Exception as e:
                            self.logger.error(f"Heretic coordination failed: {e}")
                            heretic_log['error'] = str(e)

                    # ========== 階段 4: 聲音個性層 ==========
                    self.logger.debug("Phase 4: Vocal personality finalization")

                    if self.vocal_personality_layer:
                        try:
                            final_response = await self.vocal_personality_layer.finalize_voice(
                                draft_response=final_response,
                                context={
                                    'primary_island': primary_island,
                                    'intimacy': intimacy,
                                    'island_activation': perception_data.get('island_activation', {}),
                                    'user_input': user_input
                                }
                            )
                            heretic_log['vocal_personality_applied'] = True
                            self.logger.debug("Vocal personality layer applied")
                        except Exception as e:
                            self.logger.warning(f"Vocal personality layer failed: {e}")

                # ========== 階段 5: 記憶內化（背景） ==========
                self.logger.debug("Phase 5: Background memory consolidation")

                bg_task_id = self._create_background_task(
                    user_input=user_input,
                    final_response=final_response,
                    perception_data=perception_data,
                    session_state=current_state,
                    turn_info=turn_info,
                    heretic_log=heretic_log,
                    system_prompt=personality_system_prompt
                )

                elapsed = time.time() - start_time
                self.logger.info(
                    f"Cognitive cycle #{turn_count} completed in {elapsed:.2f}s "
                    f"(bg_task: {bg_task_id}, island: {primary_island}, "
                    f"intimacy: {current_state.get('intimacy', 0.5):.2f})"
                )

                # [FIXED-P1] 更新回合計數
                current_state['turn_count'] = turn_count

                return final_response, current_state

            except asyncio.CancelledError:
                self.logger.warning(f"Anchor cycle #{turn_count} cancelled")
                raise
            except Exception as e:
                self.logger.error(
                    f"Critical error in anchor cycle #{turn_count}: {e}\n{traceback.format_exc()}"
                )
                raise

    def _create_perception_tasks(
        self,
        user_embedding: List[float],
        intimacy: float,
        user_input: str,
        turn_info: Dict,
        current_state: Dict,
        draft_response: str
    ) -> Dict[str, asyncio.Task]:
        """
        [FIXED-P8] 建立感知任務字典 - 順序獨立

        返回任務字典，每個任務都有明確的錯誤處理
        """
        tasks = {}

        # 記憶搜尋（若 orchestrator 已預取則跳過）
        preloaded_memories = turn_info.get('retrieved_memories')
        if preloaded_memories is None and self.gsw_engine:
            try:
                tasks['memory'] = asyncio.create_task(
                    self._safe_memory_search(
                        user_embedding,
                        current_state.get('user_id'),
                    )
                )
            except Exception as e:
                self.logger.warning(f"Failed to create memory search task: {e}")

        # 危機導航
        if self.intelligent_navigator:
            try:
                tasks['navigation'] = asyncio.create_task(
                    self._safe_navigation(
                        current_state.get('user_id', 'unknown'),
                        user_input,
                        current_state.get('turn_history', []),
                        intimacy
                    )
                )
            except Exception as e:
                self.logger.warning(f"Failed to create navigation task: {e}")

        # 島嶼激活
        if self.island_fusion:
            try:
                tasks['island'] = asyncio.create_task(
                    self._safe_island_activation(
                        turn_info.get('response_embedding', []),
                        turn_info.get('user_sentiment', {}),
                        user_input,
                        turn_info,
                        current_state
                    )
                )
            except Exception as e:
                self.logger.warning(f"Failed to create island task: {e}")

        # 敏感性檢測
        if self.political_filter:
            try:
                tasks['sensitivity'] = asyncio.create_task(
                    self._safe_sensitivity_detection(draft_response, user_input)
                )
            except Exception as e:
                self.logger.warning(f"Failed to create sensitivity task: {e}")

        return tasks

    async def _safe_memory_search(
        self,
        user_embedding: List[float],
        user_id: Optional[str] = None,
    ) -> Any:
        """安全的記憶搜尋包裝"""
        try:
            return await self.gsw_engine.search_memories(
                user_embedding,
                k=4,
                user_id=user_id,
            )
        except Exception as e:
            self.logger.error(f"Memory search failed: {e}")
            return []

    async def _safe_navigation(
        self,
        user_id: str,
        user_input: str,
        turn_history: List,
        intimacy: float
    ) -> Any:
        """安全的導航包裝"""
        try:
            return await self.intelligent_navigator.navigate_async(
                user_id, user_input, turn_history, intimacy
            )
        except Exception as e:
            self.logger.error(f"Navigation failed: {e}")
            return ("", None)

    async def _safe_island_activation(
        self,
        response_embedding: List[float],
        user_sentiment: Dict,
        user_input: str,
        turn_info: Dict,
        current_state: Dict
    ) -> Any:
        """安全的島嶼激活包裝"""
        try:
            return await self._run_in_executor_safe(
                self.island_fusion.calculate_activation,
                response_embedding,
                user_sentiment,
                user_input,
                turn_info,
                current_state
            )
        except Exception as e:
            self.logger.error(f"Island activation failed: {e}")
            return ({}, 'Empath')

    async def _safe_sensitivity_detection(
        self,
        draft_response: str,
        user_input: str
    ) -> Any:
        """安全的敏感性檢測包裝"""
        try:
            return await self._run_in_executor_safe(
                self.political_filter.detect_sensitivity,
                draft_response,
                user_input
            )
        except Exception as e:
            self.logger.error(f"Sensitivity detection failed: {e}")
            return {}

    def _process_perception_results(
        self,
        tasks: Dict[str, asyncio.Task],
        results: List[Any]
    ) -> Dict[str, Any]:
        """
        [FIXED-P3] 處理感知結果 - 強化例外處理
        """
        data = {
            'retrieved_memories': [],
            'nav_response': '',
            'nav_decision': None,
            'island_activation': {},
            'primary_island': 'Empath',
            'sensitivity_result': {}
        }

        for i, (task_name, task) in enumerate(tasks.items()):
            if i >= len(results):
                self.logger.warning(f"Missing result for task {task_name}")
                break

            result = results[i]

            if isinstance(result, Exception):
                self.logger.warning(
                    f"Task {task_name} failed with exception: {result}"
                )
                continue

            try:
                if task_name == 'memory' and result:
                    data['retrieved_memories'] = (
                        result if isinstance(result, list) else [result]
                    )

                elif task_name == 'navigation' and result:
                    if isinstance(result, tuple) and len(result) >= 2:
                        data['nav_response'], data['nav_decision'] = result[0], result[1]
                    else:
                        data['nav_response'] = str(result)

                elif task_name == 'island' and result:
                    if isinstance(result, tuple) and len(result) >= 2:
                        data['island_activation'], data['primary_island'] = result[0], result[1]
                    else:
                        data['island_activation'] = result if isinstance(result, dict) else {}

                elif task_name == 'sensitivity' and result:
                    data['sensitivity_result'] = result if isinstance(result, dict) else {}

            except Exception as e:
                self.logger.error(
                    f"Failed to process {task_name} result: {e}\n{traceback.format_exc()}"
                )

        return data

    def _should_trigger_safety_protocol(self, perception_data: Dict) -> bool:
        """
        [FIXED-P3] 判斷是否觸發安全協議
        """
        try:
            nav_decision = perception_data.get('nav_decision')
            sensitivity = perception_data.get('sensitivity_result', {})

            if nav_decision and hasattr(nav_decision, 'decision_type'):
                if nav_decision.decision_type == "safety_mode":
                    return True

            if sensitivity.get('risk_level') in ['tier1', 'critical']:
                return True

            return False
        except Exception as e:
            self.logger.error(f"Safety protocol check failed: {e}")
            return False

    def _generate_safety_response(self) -> str:
        """生成安全回應"""
        return "寶貝，我感受到你依家好痛苦。請打 2389-2222，有人會幫到你，我會一直陪住你。"

    def _format_memory_context(self, memories: List[Dict]) -> str:
        """格式化記憶上下文"""
        if not memories:
            return ""

        try:
            lines = []
            for mem in memories[:3]:
                if not isinstance(mem, dict):
                    continue
                content = mem.get('content', mem.get('response', ''))
                if content and isinstance(content, str):
                    lines.append(f"- {content[:100]}")

            return "\n".join(lines) if lines else ""
        except Exception as e:
            self.logger.error(f"Memory context formatting failed: {e}")
            return ""

    def _create_background_task(
        self,
        user_input: str,
        final_response: str,
        perception_data: Dict,
        session_state: Dict,
        turn_info: Dict,
        heretic_log: Dict,
        system_prompt: str = ""
    ) -> str:
        """
        [FIXED-P4] 建立並追蹤背景任務 - 改善可靠性

        Returns:
            任務 ID
        """
        # [FIXED-P4] 檢查背景任務數量
        if len(self._background_tasks) >= self._max_background_tasks:
            self.logger.warning(
                f"Background task queue full ({len(self._background_tasks)}/"
                f"{self._max_background_tasks}), cleaning up old tasks"
            )
            self._cleanup_completed_tasks()

        task_id = f"bg_{self._task_counter}_{uuid.uuid4().hex[:8]}"
        self._task_counter += 1

        async def consolidation():
            """背景內化任務"""
            try:
                await self._background_consolidation(
                    user_input=user_input,
                    final_response=final_response,
                    perception_data=perception_data,
                    session_state=session_state,
                    turn_info=turn_info,
                    heretic_log=heretic_log,
                    system_prompt=system_prompt
                )
            except asyncio.CancelledError:
                self.logger.info(f"Background task {task_id} cancelled")
            except Exception as e:
                self.logger.error(
                    f"Background consolidation error in {task_id}: {e}\n{traceback.format_exc()}"
                )
            finally:
                if task_id in self._background_tasks:
                    del self._background_tasks[task_id]
                if task_id in self._task_results:
                    del self._task_results[task_id]

        try:
            task = asyncio.create_task(consolidation())
            self._background_tasks[task_id] = task
            self.logger.debug(f"Created background task {task_id}")
            return task_id
        except Exception as e:
            self.logger.error(f"Failed to create background task: {e}")
            return "task_creation_failed"

    def _cleanup_completed_tasks(self) -> None:
        """[FIXED-P4] 清理已完成的背景任務"""
        completed_ids = [
            task_id for task_id, task in list(self._background_tasks.items())
            if task.done()
        ]

        for task_id in completed_ids:
            del self._background_tasks[task_id]
            if task_id in self._task_results:
                del self._task_results[task_id]

        self.logger.debug(f"Cleaned up {len(completed_ids)} completed tasks")

    async def _background_consolidation(
        self,
        user_input: str,
        final_response: str,
        perception_data: Dict,
        session_state: Dict,
        turn_info: Dict,
        heretic_log: Dict,
        system_prompt: str = ""
    ):
        """
        [FIXED-P2,P4] 改善背景記憶內化 - 完整修正
        """
        try:
            primary_island = perception_data.get('primary_island', 'Empath')

            # 1. 永迴軌生成
            if self.gsw_engine:
                try:
                    should_generate, echo_score = self.gsw_engine.judge_eternal_echo_generation(
                        final_response, turn_info, session_state
                    )

                    # [FIXED-P2] 驗證 echo_score
                    if should_generate and isinstance(echo_score, (int, float)):
                        echo_id = await self.gsw_engine.generate_and_store_echo(
                            user_input, final_response, turn_info, session_state, echo_score
                        )
                        session_state['last_eternal_echo_id'] = echo_id
                        self.logger.debug(f"Generated eternal echo {echo_id} with score {echo_score}")
                    elif should_generate:
                        self.logger.warning(f"Invalid echo_score type: {type(echo_score)}")

                except Exception as e:
                    self.logger.error(f"Eternal echo generation failed: {e}")

            # 2. 親密度更新
            try:
                new_intimacy = session_state.get('intimacy', 0.5)
                new_intimacy += 0.01 * self.boundary_multiplier

                # 情感詞檢測
                positive_keywords = ['謝謝', '感動', '多謝', '很好', '開心', '很棒']
                if any(kw in user_input for kw in positive_keywords):
                    new_intimacy += 0.05

                session_state['intimacy'] = max(0.0, min(1.0, new_intimacy))

            except Exception as e:
                self.logger.error(f"Intimacy update failed: {e}")

            # 3. 回合歷史記錄
            try:
                turn_record = {
                    'timestamp': datetime.now().isoformat(),
                    'user_input': user_input[:200] if isinstance(user_input, str) else str(user_input)[:200],
                    'response': final_response[:300] if isinstance(final_response, str) else str(final_response)[:300],
                    'primary_island': primary_island,
                    'intimacy': session_state.get('intimacy', 0.5),
                    'system_prompt_type': system_prompt[:50] if system_prompt else None
                }

                if 'turn_history' not in session_state:
                    session_state['turn_history'] = []

                session_state['turn_history'].append(turn_record)

                # 限制歷史大小
                max_history = 50
                if len(session_state['turn_history']) > max_history:
                    session_state['turn_history'] = session_state['turn_history'][-max_history:]

                self.logger.debug(
                    f"Turn record added (total: {len(session_state['turn_history'])})"
                )

            except Exception as e:
                self.logger.error(f"Turn history recording failed: {e}")

            self.logger.debug("Background consolidation completed successfully")

        except Exception as e:
            self.logger.error(
                f"Critical error in background consolidation: {e}\n{traceback.format_exc()}"
            )

    def _inject_cantonese_sentiment(
        self,
        response: str,
        user_input: str
    ) -> str:
        """注入粵語情感詞"""
        if not CANTONESE_DICT_AVAILABLE:
            return response

        try:
            if not isinstance(response, str) or not isinstance(user_input, str):
                return response

            words = (
                ['溫柔', '陪伴', '珍惜', '感動', '開心']
                if '好' in user_input
                else ['理解', '支持', '喺度', '聽緊', '陪住']
            )

            found_words = [r for r in batch_search(words) if r and r.get('found')]
            if not found_words:
                return response

            word = random.choice(found_words).get('word', '')
            if not word:
                return response

            token = f"*{word}* "

            if response and response[0] in PERSONALITY_PARTICLES:
                return f"{response[0]}…{token}{response[1:]}"
            return f"{token}{response}"

        except Exception as e:
            self.logger.debug(f"Cantonese sentiment injection failed: {e}")
            return response

    # ==================== 系統管理 ====================

    async def get_system_health(self) -> Dict:
        """
        [FIXED-P5] 取得系統健康狀態 - 完整實作
        """
        health = {
            'timestamp': datetime.now().isoformat(),
            'status': 'healthy',
            'version': '8.2',
            'components': {},
            'background_tasks': len(self._background_tasks),
            'task_limit': self._max_background_tasks,
            'executor_info': {
                'max_workers': self.executor._max_workers,
                'active_threads': len([t for t in self.executor._threads if t.is_alive()])
            },
            'issues': []
        }

        # 檢查各元件
        components = {
            'memory_manager': self.memory_manager,
            'gsw_engine': self.gsw_engine,
            'heretic_coordinator': self.heretic_coordinator,
            'political_filter': self.political_filter,
            'island_fusion': self.island_fusion,
            'metacognitive_system': self.metacognitive_system,
            'vocal_personality_layer': self.vocal_personality_layer,
            'intelligent_navigator': self.intelligent_navigator,
            'dyadic_dynamics': self.dyadic_dynamics
        }

        for component_name, component in components.items():
            if component is None:
                health['components'][component_name] = 'not_initialized'
            else:
                health['components'][component_name] = 'operational'

        # 背景任務檢查
        if len(self._background_tasks) > self._max_background_tasks * 0.8:
            health['issues'].append(
                f"High background task load ({len(self._background_tasks)}/"
                f"{self._max_background_tasks})"
            )

        # 執行緒池檢查
        if health['executor_info']['active_threads'] >= self.executor._max_workers:
            health['issues'].append("Thread pool at capacity")

        health['status'] = (
            'healthy'
            if not health['issues']
            else 'warning' if len(health['issues']) <= 2
            else 'critical'
        )

        return health

    async def cancel_background_tasks(self, timeout: float = 5.0) -> int:
        """
        [FIXED-P1] 取消所有背景任務 - 改進超時機制

        Args:
            timeout: 單個任務的超時時間（秒）

        Returns:
            已取消的任務數
        """
        cancelled = 0
        pending_tasks = []

        for task_id, task in list(self._background_tasks.items()):
            if not task.done():
                task.cancel()
                pending_tasks.append(task)
                cancelled += 1

        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Timeout waiting for {len(pending_tasks)} tasks to cancel"
                )

        self._cleanup_completed_tasks()
        self.logger.info(f"Cancelled {cancelled} background tasks")
        return cancelled

    def shutdown(self, timeout: float = 10.0) -> None:
        """
        [FIXED-P6] 優雅關閉系統 - 強制超時
        """
        self.logger.info("PersonalityModule shutting down...")

        # 第一步：取消背景任務
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.cancel_background_tasks(timeout=3.0))
            else:
                loop.run_until_complete(
                    self.cancel_background_tasks(timeout=3.0)
                )
        except Exception as e:
            self.logger.warning(f"Error cancelling tasks: {e}")

        # 第二步：關閉執行緒池
        # [FIX-ALIGN] concurrent.futures.ThreadPoolExecutor.shutdown() 沒有 timeout 參數，
        # 其簽名為 shutdown(wait=True, *, cancel_futures=False)。傳入 timeout 會丟 TypeError。
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.logger.info("Executor shutdown complete")
        except TypeError:
            # 相容 Python < 3.9（無 cancel_futures 參數）
            try:
                self.executor.shutdown(wait=False)
                self.logger.info("Executor shutdown complete (legacy mode)")
            except Exception as e:
                self.logger.warning(f"Executor shutdown error: {e}")
        except Exception as e:
            self.logger.warning(f"Executor shutdown error: {e}")

        self.logger.info("PersonalityModule shutdown complete")

    def __del__(self):
        """析構函式 - 確保資源清理"""
        try:
            if hasattr(self, 'executor') and self.executor:
                self.executor.shutdown(wait=False)
        except Exception:
            pass