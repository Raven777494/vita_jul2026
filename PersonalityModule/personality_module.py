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

PERSONALITY_PARTICLES = ['嗯', '其實', '天啊', '真的', '我覺得', '你知道嗎']
AUTOBIOGRAPHY_MARKERS = [
    '我爸爸', '我媽媽', '我出世', '我細個', '我童年',
    '我以前住', '我家人', '我讀幼稚園', '我讀小學', '我讀中學',
]

# 趣事／鬧向記憶標記（crisis／high 閘門用）
ANECDOTE_MARKERS = (
    '趣事', '好笑', '搞笑', '玩笑', '開玩笑', '幽默', '開心事',
    '輕鬆事', '玩嘢', '惡作劇', '鬧交笑', '講笑', '笑死',
)
PLAYFUL_MARKERS = (
    '打鬧', '嬉戲', '惡作劇', '整蠱', '開玩笑', '玩嘢', '鬧著玩', '講笑',
)
ANECDOTE_META_TAGS = {
    'anecdote', '趣事', 'playful', 'play', '鬧', 'humor', 'funny', 'joke',
}

# P3.3：Orchestrator 可選接點白名單（只傳遞，不做 ABCD 分類）
ORCHESTRATOR_HINT_WHITELIST = (
    'user_mode_hint',
    'skip_echo_consolidation',
    'expression_preference',
    'force_quiet_presence',
    'decision_correlation_id',
)

# P3.4：不可被 echo／consolidation 改寫的正史／核心 id 前綴
IMMUTABLE_SOUL_ID_PREFIXES = (
    'memory_',
    'core_',
    'gold_hk_',
    'canon_',
)


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
        self.persona_graph = None
        self.conflict_repair = None

        # [NEW] 執行緒池配置
        max_workers = config.get('thread_pool_workers', 6)
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='PersonalityBrain'
        )

        self.boundary_multiplier = config.get('boundary_multiplier', 1.0)
        self._max_background_tasks = config.get('max_background_tasks', 20)
        self._soul_memory_candidates_cache: Optional[List[Dict[str, Any]]] = None

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

        # [NEW] PersonaGraph 最小骨架（draft 前置島嶼/政策解析）
        self.persona_graph = dependencies.get('persona_graph')
        if not self.persona_graph:
            try:
                from .persona_graph import PersonaGraph
                self.persona_graph = PersonaGraph(
                    config=self.config,
                    island_fusion=self.island_fusion,
                )
                self.logger.debug("Created new PersonaGraph instance")
            except Exception as e:
                self.logger.warning(f"Failed to create PersonaGraph: {e}")

        # [NEW] P4 衝突修復（取代否認／發火防衛）
        self.conflict_repair = dependencies.get('conflict_repair')
        if not self.conflict_repair:
            try:
                from .conflict_repair import ConflictRepair
                self.conflict_repair = ConflictRepair(config=self.config)
                self.logger.debug("Created new ConflictRepair instance")
            except Exception as e:
                self.logger.warning(f"Failed to create ConflictRepair: {e}")

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

    # ==================== Draft 前置（Layer 1） ====================

    @staticmethod
    def apply_context_hooks(
        turn_info: Optional[Dict[str, Any]] = None,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        P3.3：只讀取 orchestrator 白名單 hints，不做 ABCD 用戶分類。
        來源優先：turn_info['orchestrator_hints'] > turn_info 頂層 > session_state。
        """
        info = turn_info if isinstance(turn_info, dict) else {}
        state = session_state if isinstance(session_state, dict) else {}
        raw_hints = info.get('orchestrator_hints')
        if not isinstance(raw_hints, dict):
            raw_hints = {}

        merged: Dict[str, Any] = {}
        for key in ORCHESTRATOR_HINT_WHITELIST:
            if key in raw_hints and raw_hints[key] is not None:
                merged[key] = raw_hints[key]
            elif key in info and info[key] is not None and key != 'orchestrator_hints':
                merged[key] = info[key]
            elif key in state and state[key] is not None:
                merged[key] = state[key]
        return merged

    @staticmethod
    def is_immutable_soul_memory_id(memory_id: Any) -> bool:
        mid = str(memory_id or '').strip()
        if not mid:
            return False
        return any(mid.startswith(prefix) for prefix in IMMUTABLE_SOUL_ID_PREFIXES)

    def _should_skip_echo_consolidation(
        self,
        *,
        turn_info: Dict[str, Any],
        session_state: Dict[str, Any],
        final_response: str,
        drift_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """
        P3.4：分級決定是否跳過永迴軌沉澱。
        echo 永不可改寫童年正史；高風險／明示 skip 時直接跳過。
        """
        hooks = self.apply_context_hooks(turn_info, session_state)
        if bool(hooks.get('skip_echo_consolidation')):
            return True, 'orchestrator_hint_skip'

        drift = drift_info if isinstance(drift_info, dict) else {}
        alert = str(
            drift.get('alert_level')
            or turn_info.get('narrative_drift_alert_level')
            or 'none'
        ).lower()
        if alert == 'critical':
            return True, 'critical_narrative_drift'

        pre = turn_info.get('pre_draft_guidance')
        if not isinstance(pre, dict):
            pre = {}
        intensity = str(
            pre.get('intensity')
            or turn_info.get('intensity')
            or session_state.get('intensity')
            or ''
        ).lower()
        if intensity == 'crisis' and any(
            m in (final_response or '') for m in AUTOBIOGRAPHY_MARKERS
        ):
            return True, 'crisis_autobiography_response'

        return False, ''

    def prepare_draft_guidance(
        self,
        user_input: str,
        session_state: Dict,
        turn_info: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Layer 1 前置個性：PersonaGraph.resolve + SystemPromptBuilder。

        必須在 LLM draft 之前呼叫，使初稿已帶希兒島嶼/關係階段/政策約束。
        回傳完整 system_prompt（Zero-Truncation：不截斷提示本體）。
        """
        if not self._initialization_done:
            self.logger.error("PersonalityModule not properly initialized")
            raise RuntimeError("Dependencies not setup")

        current_state = (
            session_state[0]
            if isinstance(session_state, tuple)
            else session_state
        )
        if not isinstance(current_state, dict):
            raise TypeError("session_state must be a dictionary")

        info = turn_info if isinstance(turn_info, dict) else {}
        hooks = self.apply_context_hooks(info, current_state)
        if hooks:
            info = dict(info)
            info['orchestrator_hints'] = hooks
            for key, value in hooks.items():
                info.setdefault(key, value)

        intimacy = self._safe_float(
            current_state.get('intimacy', 0.0),
            default=0.0,
            min_value=0.0,
            max_value=1.0,
        )
        risk_level = 0
        try:
            risk_level = int(info.get('risk_level', current_state.get('risk_level', 0)) or 0)
        except (TypeError, ValueError):
            risk_level = 0

        user_sentiment = info.get('user_sentiment')
        if not isinstance(user_sentiment, dict):
            user_sentiment = {}

        resolution_dict: Dict[str, Any] = {}
        primary_island = str(current_state.get('primary_island') or 'Empath')
        relationship_stage = "普通人"
        intensity = "medium"
        active_policies: List[str] = []
        island_activation: Dict[str, float] = {}
        prompt_fragment = ""

        if self.persona_graph:
            try:
                resolution = self.persona_graph.resolve(
                    user_input=user_input or "",
                    intimacy=intimacy,
                    user_sentiment=user_sentiment,
                    session_state=current_state,
                    risk_level=risk_level,
                )
                resolution_dict = resolution.to_public_dict()
                primary_island = resolution.primary_island
                relationship_stage = resolution.relationship_stage
                intensity = resolution.intensity
                active_policies = list(resolution.active_policies)
                island_activation = dict(resolution.island_activation)
                prompt_fragment = resolution.prompt_fragment
            except Exception as e:
                self.logger.warning(f"PersonaGraph.resolve failed: {e}")

        # P3.3：force_quiet_presence 只調政策／強度標籤，不做用戶分類
        if bool(hooks.get('force_quiet_presence')):
            if 'no_playful_teasing' not in active_policies:
                active_policies.append('no_playful_teasing')
            if intensity not in {'crisis', 'high'}:
                intensity = 'high'

        system_prompt = ""
        if self.system_prompt_builder:
            try:
                system_prompt = self.system_prompt_builder.build_system_prompt(
                    primary_island=primary_island,
                    user_input=user_input or "",
                    context={
                        'intimacy': intimacy,
                        'turn_count': current_state.get('turn_count', 0),
                        'user_sentiment': user_sentiment,
                        'intensity': intensity,
                        'persona_resolution': resolution_dict,
                        'persona_prompt_fragment': prompt_fragment,
                        'trait_labels': resolution_dict.get('trait_labels', []),
                        'trait_volumes': {},
                        'expression_budget': {},
                        'risk_level': risk_level,
                        'soul_memory_guidance': '',
                        'orchestrator_hints': hooks,
                        'expression_preference': hooks.get('expression_preference'),
                    },
                )
            except Exception as e:
                self.logger.warning(f"Failed to build pre-draft system prompt: {e}")
                system_prompt = ""

        if not system_prompt and prompt_fragment:
            system_prompt = prompt_fragment

        # P1: 過去／童年觸發 → 雙庫檢索最多 1 段正史（Zero-Truncation）
        soul_memory = self._select_soul_memory(
            user_input or "",
            primary_island=primary_island,
            intensity=intensity,
        )
        soul_guidance = self._format_soul_memory_guidance(soul_memory) if soul_memory else ""
        if soul_guidance:
            system_prompt = (
                f"{system_prompt}\n\n{soul_guidance}"
                if system_prompt
                else soul_guidance
            )

        memory_context = info.get('memory_context') or ""
        if not memory_context and info.get('retrieved_memories') is not None:
            memory_context = self._format_memory_context(
                info.get('retrieved_memories') or [],
                intensity=intensity,
            )
        memory_context = self._sanitize_memory_context(
            memory_context,
            intensity=intensity,
        )
        if memory_context:
            system_prompt = (
                f"{system_prompt}\n\n相關記憶:\n{memory_context}"
                if system_prompt
                else f"相關記憶:\n{memory_context}"
            )

        guidance = {
            'system_prompt': system_prompt or "",
            'primary_island': primary_island,
            'relationship_stage': relationship_stage,
            'intimacy': intimacy,
            'intensity': intensity,
            'active_policies': active_policies,
            'island_activation': island_activation,
            'trait_labels': resolution_dict.get('trait_labels', []),
            'trait_volumes': {},
            'expression_budget': {},
            'memory_context': memory_context,
            'soul_memory': soul_memory,
            'soul_memory_id': (
                str(soul_memory.get('memory_id') or soul_memory.get('id') or '')
                if isinstance(soul_memory, dict)
                else ''
            ),
            'soul_memory_source': (
                str(soul_memory.get('source') or '')
                if isinstance(soul_memory, dict)
                else ''
            ),
            'orchestrator_hints': hooks,
            'prompt_contract': 'pre_draft_full_no_truncation',
            'persona_resolution': resolution_dict,
            'graph_version': resolution_dict.get('graph_version', '0.3.0'),
            'source': 'prepare_draft_guidance',
        }
        self.logger.info(
            "Pre-draft guidance ready "
            f"(island={primary_island}, stage={relationship_stage}, "
            f"intensity={intensity}, prompt_chars={len(system_prompt or '')}, "
            f"soul_id={guidance.get('soul_memory_id') or '-'})"
        )
        return guidance

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
                decision_correlation_id = turn_info.get('decision_correlation_id')
                if not isinstance(decision_correlation_id, str) or not decision_correlation_id.strip():
                    decision_correlation_id = self._new_decision_correlation_id(turn_count)
                turn_info['decision_correlation_id'] = decision_correlation_id

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

                # ========== 階段 2a: 個性提示詞（優先重用 draft 前置結果） ==========
                self.logger.debug("Phase 2a: Personality prompt generation")

                pre_draft = turn_info.get('pre_draft_guidance')
                if not isinstance(pre_draft, dict):
                    pre_draft = {}

                primary_island = (
                    pre_draft.get('primary_island')
                    or perception_data.get('primary_island')
                    or current_state.get('primary_island')
                    or 'Empath'
                )
                personality_system_prompt = str(
                    pre_draft.get('system_prompt')
                    or turn_info.get('personality_system_prompt')
                    or ""
                )
                prompt_reused = bool(str(personality_system_prompt).strip())

                # P3.1：若 draft 前置已產出完整 prompt，禁止重算，避免雙路徑不一致。
                if not prompt_reused and self.system_prompt_builder:
                    try:
                        persona_resolution = pre_draft.get('persona_resolution') or {}
                        personality_system_prompt = self.system_prompt_builder.build_system_prompt(
                            primary_island=primary_island,
                            user_input=user_input,
                            context={
                                'intimacy': intimacy,
                                'turn_count': turn_count,
                                'user_sentiment': turn_info.get('user_sentiment', {}),
                                'persona_resolution': persona_resolution,
                                'persona_prompt_fragment': persona_resolution.get(
                                    'prompt_fragment', ''
                                ),
                            }
                        )
                        memory_context = (
                            turn_info.get('memory_context')
                            or self._format_memory_context(
                                perception_data.get('retrieved_memories', []),
                                intensity=str(
                                    pre_draft.get('intensity')
                                    or persona_resolution.get('intensity')
                                    or 'medium'
                                ),
                            )
                        )
                        memory_context = self._sanitize_memory_context(
                            memory_context,
                            intensity=str(
                                pre_draft.get('intensity')
                                or persona_resolution.get('intensity')
                                or 'medium'
                            ),
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
                elif prompt_reused:
                    self.logger.debug(
                        f"Reusing pre-draft system prompt for island: {primary_island} "
                        f"(chars={len(personality_system_prompt)})"
                    )
                    current_state['prompt_reused'] = True
                else:
                    current_state['prompt_reused'] = False

                if primary_island:
                    current_state['primary_island'] = primary_island
                if pre_draft.get('relationship_stage'):
                    current_state['relationship_stage'] = pre_draft['relationship_stage']

                # ========== 階段 2b: 元認知與危機處理 ==========
                self.logger.debug("Phase 2b: Metacognition & Crisis intercept")
                drift_info = await self._monitor_drift(
                    draft_response=draft_response,
                    user_input=user_input,
                    current_state=current_state,
                    turn_info=turn_info,
                    correlation_id=decision_correlation_id,
                )
                meta_control = self._monitor_metacognition(
                    user_input=user_input,
                    perception_data=perception_data,
                    turn_info=turn_info,
                    current_state=current_state,
                    drift_info=drift_info,
                )
                drift_info = await self._monitor_drift(
                    draft_response=draft_response,
                    user_input=user_input,
                    current_state=current_state,
                    turn_info=turn_info,
                    memory_policy=meta_control,
                    correlation_id=decision_correlation_id,
                )
                drift_info = self._apply_meta_drift_alert(drift_info, meta_control)
                controlled_memories = await self._apply_meta_memory_controls(
                    user_embedding=user_embedding,
                    user_id=current_state.get('user_id'),
                    preloaded_memories=perception_data.get('retrieved_memories'),
                    meta_control=meta_control,
                )
                perception_data['retrieved_memories'] = controlled_memories
                turn_info['retrieved_memories'] = controlled_memories
                perception_data['drift_info'] = drift_info
                turn_info['narrative_drift_signal'] = drift_info.get('drift_score', 0.0)
                turn_info['narrative_drift_alert_level'] = drift_info.get('alert_level', 'none')
                turn_info['metacognitive_control'] = meta_control
                turn_info['memory_policy_level'] = (
                    'critical'
                    if drift_info.get('alert_level') == 'critical'
                    else 'strict'
                    if (drift_info.get('alert_level') == 'warning'
                        or bool(meta_control.get('restrict_memory', False)))
                    else 'normal'
                )
                drift_info['decision_correlation_id'] = decision_correlation_id
                metadata_overrides = turn_info.get('metadata_overrides', {})
                if not isinstance(metadata_overrides, dict):
                    metadata_overrides = {}
                metadata_overrides.update({
                    'decision_correlation_id': decision_correlation_id,
                    'memory_policy_level': turn_info.get('memory_policy_level', 'normal'),
                })
                turn_info['metadata_overrides'] = metadata_overrides

                if drift_info.get('alert_level') in {'warning', 'critical'}:
                    guardrail_line = (
                        "DRIFT / CONFLICT REPAIR GUARDRAIL:\n"
                        "Keep autobiography strictly consistent with locked canon.\n"
                        "Do not invent new personal childhood facts.\n"
                        "If uncertain or challenged: clarify gently; "
                        "never deny, rationalize, or get angry to protect persona."
                    )
                    personality_system_prompt = (
                        f"{personality_system_prompt}\n\n{guardrail_line}"
                        if personality_system_prompt
                        else guardrail_line
                    )

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
                                drift_info=drift_info,
                                sensitivity_result=perception_data.get('sensitivity_result', {}),
                                extracted_info={
                                    'narrative_drift_signal': drift_info.get('drift_score', 0.0),
                                    'narrative_drift_alert_level': drift_info.get('alert_level', 'none'),
                                    'decision_correlation_id': decision_correlation_id,
                                },
                                session_state=current_state
                            )
                            self.logger.debug(
                                f"Heretic correction applied: {heretic_log.get('correction_count', 0)} corrections"
                            )
                        except Exception as e:
                            self.logger.error(f"Heretic coordination failed: {e}")
                            heretic_log['error'] = str(e)

                    heretic_log['drift_alert_level'] = drift_info.get('alert_level', 'none')
                    heretic_log['drift_score'] = drift_info.get('drift_score', 0.0)

                    # ========== 階段 4: 聲音個性層 ==========
                    self.logger.debug("Phase 4: Vocal personality finalization")

                    if self.vocal_personality_layer and drift_info.get('alert_level') != 'critical':
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
                    elif drift_info.get('alert_level') == 'critical':
                        heretic_log['vocal_personality_applied'] = False
                        heretic_log['vocal_skip_reason'] = 'critical_drift_guardrail'

                    final_response = self._enforce_drift_guardrail_text(
                        final_response,
                        drift_info=drift_info,
                    )

                    # ========== 階段 4b: P4 衝突修復 ==========
                    soul_memory = None
                    if isinstance(pre_draft, dict):
                        soul_memory = pre_draft.get('soul_memory')
                    repair_result = self._apply_conflict_repair(
                        response=final_response,
                        user_input=user_input,
                        drift_info=drift_info,
                        soul_memory=soul_memory if isinstance(soul_memory, dict) else None,
                    )
                    final_response = repair_result.get('text', final_response)
                    heretic_log['conflict_repair'] = repair_result

                # ========== 階段 5: 記憶內化（背景） ==========
                self.logger.debug("Phase 5: Background memory consolidation")

                bg_task_id = self._create_background_task(
                    user_input=user_input,
                    final_response=final_response,
                    perception_data=perception_data,
                    session_state=current_state,
                    turn_info=turn_info,
                    heretic_log=heretic_log,
                    system_prompt=personality_system_prompt,
                    drift_info=drift_info
                )

                elapsed = time.time() - start_time
                self.logger.info(
                    f"Cognitive cycle #{turn_count} completed in {elapsed:.2f}s "
                    f"(bg_task: {bg_task_id}, island: {primary_island}, "
                    f"intimacy: {current_state.get('intimacy', 0.5):.2f})"
                )

                # [FIXED-P1] 更新回合計數
                current_state['turn_count'] = turn_count
                current_state['last_drift_info'] = drift_info
                current_state['last_decision_correlation_id'] = decision_correlation_id
                if 'drift_history' not in current_state:
                    current_state['drift_history'] = []
                current_state['drift_history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'score': drift_info.get('drift_score', 0.0),
                    'alert_level': drift_info.get('alert_level', 'none'),
                    'decision_correlation_id': decision_correlation_id,
                })
                if len(current_state['drift_history']) > 50:
                    current_state['drift_history'] = current_state['drift_history'][-50:]

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
        k: int = 4,
    ) -> Any:
        """安全的記憶搜尋包裝"""
        try:
            search_k = max(1, min(20, int(k)))
            return await self.gsw_engine.search_memories(
                user_embedding,
                k=search_k,
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
        return (
            "我感受到你依家好痛苦。我會喺度陪住你，我哋先慢慢呼吸一下，"
            "再一齊搵一位你信得過、可以即刻聯絡到嘅人。"
        )

    def _get_memory_snippet_limits(self) -> Tuple[int, int]:
        """
        回憶注入上限。
        - 每輪最多 1 段
        - max_chars<=0 表示 Zero-Truncation：不裁切正文
        """
        max_items = 1
        max_chars = 0
        try:
            max_items = int(self.config.get('max_memory_snippet_per_turn', 1) or 1)
        except (TypeError, ValueError):
            max_items = 1
        try:
            raw_chars = self.config.get('max_memory_snippet_chars', 0)
            max_chars = int(raw_chars) if raw_chars is not None else 0
        except (TypeError, ValueError):
            max_chars = 0

        rules = self.config.get('communication_rules')
        if isinstance(rules, dict):
            try:
                if rules.get('max_memory_snippet_per_turn') is not None:
                    max_items = int(rules.get('max_memory_snippet_per_turn'))
                if rules.get('max_memory_snippet_chars') is not None:
                    max_chars = int(rules.get('max_memory_snippet_chars'))
            except (TypeError, ValueError):
                pass

        # 亦讀 persona profile（若已載入到 config）
        profile = self.config.get('persona_profile')
        if isinstance(profile, dict):
            profile_rules = profile.get('communication_rules')
            if isinstance(profile_rules, dict):
                try:
                    if profile_rules.get('max_memory_snippet_per_turn') is not None:
                        max_items = int(profile_rules.get('max_memory_snippet_per_turn'))
                    if profile_rules.get('max_memory_snippet_chars') is not None:
                        max_chars = int(profile_rules.get('max_memory_snippet_chars'))
                except (TypeError, ValueError):
                    pass

        max_items = max(0, min(1, max_items))
        max_chars = max(0, max_chars)
        return max_items, max_chars

    def _memory_gate_blocks_anecdote(
        self,
        *,
        intensity: Optional[str] = None,
        expression_budget: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """crisis／high 阻擋趣事型記憶（不依賴音量分數）。"""
        del expression_budget  # 保留參數以相容舊呼叫
        level = str(intensity or '').strip().lower()
        return level in {'crisis', 'high'}

    def _memory_gate_blocks_play(
        self,
        *,
        intensity: Optional[str] = None,
        expression_budget: Optional[Dict[str, Any]] = None,
    ) -> bool:
        del expression_budget
        level = str(intensity or '').strip().lower()
        return level in {'crisis', 'high'}

    def _is_anecdote_or_playful_memory(
        self,
        text: str,
        memory: Optional[Dict] = None,
    ) -> Tuple[bool, bool]:
        """
        回傳 (is_anecdote, is_playful)。
        以 metadata 為優先，其次標題／正文標記。
        """
        is_anecdote = False
        is_playful = False
        blob_parts = [str(text or '')]

        if isinstance(memory, dict):
            blob_parts.append(str(memory.get('title', '') or ''))
            blob_parts.append(str(memory.get('content', '') or ''))
            meta = memory.get('metadata')
            if isinstance(meta, dict):
                for key in (
                    'expression', 'expression_type', 'tone', 'memory_type',
                    'category', 'style',
                ):
                    blob_parts.append(str(meta.get(key, '') or ''))
                for key in ('expression', 'expression_type', 'tone', 'category', 'style'):
                    tag = str(meta.get(key, '') or '').strip().lower()
                    if tag in ANECDOTE_META_TAGS:
                        is_anecdote = True
                    if tag in {'play', 'playful', '鬧'}:
                        is_playful = True

        blob = ' '.join(blob_parts)
        if any(marker in blob for marker in ANECDOTE_MARKERS):
            is_anecdote = True
        if any(marker in blob for marker in PLAYFUL_MARKERS):
            is_playful = True
        return is_anecdote, is_playful

    def _should_skip_memory_for_expression_gate(
        self,
        text: str,
        memory: Optional[Dict] = None,
        *,
        intensity: Optional[str] = None,
        expression_budget: Optional[Dict[str, Any]] = None,
    ) -> bool:
        is_anecdote, is_playful = self._is_anecdote_or_playful_memory(text, memory)
        if is_anecdote and self._memory_gate_blocks_anecdote(
            intensity=intensity,
            expression_budget=expression_budget,
        ):
            return True
        if is_playful and self._memory_gate_blocks_play(
            intensity=intensity,
            expression_budget=expression_budget,
        ):
            return True
        return False

    def _clip_memory_snippet(self, text: str, max_chars: int) -> str:
        """
        回憶片段處理。
        max_chars<=0：Zero-Truncation，不裁切。
        """
        body = str(text or '').strip()
        if not body:
            return ""
        if max_chars <= 0 or len(body) <= max_chars:
            return body
        # 僅在明確配置上限時裁切（預設關閉）
        return f"{body[:max_chars].rstrip()}…"

    PAST_TOPIC_MARKERS = (
        '童年', '細個', '細細個', '小時候', '兒時', '往事', '過去',
        '以前', '當年', '回憶', '出世', '讀幼稚園', '讀小學', '讀中學',
        '我爸', '我媽', '我爸爸', '我媽媽', '屋企以前', '舊時',
        'childhood', 'when i was', 'growing up',
    )

    def _is_past_or_childhood_topic(self, user_input: str) -> bool:
        text = str(user_input or '').strip().lower()
        if not text:
            return False
        return any(marker.lower() in text for marker in self.PAST_TOPIC_MARKERS)

    def _data_root_path(self) -> Path:
        raw = (
            self.config.get('data_path')
            or self.config.get('data_dir')
            or Path(__file__).parent / 'data'
        )
        return Path(raw)

    def _load_json_data_file(self, filename: str) -> Dict[str, Any]:
        path = self._data_root_path() / filename
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return loaded
                if isinstance(loaded, list):
                    return {"items": loaded}
        except Exception as exc:
            self.logger.warning(f"Failed to load {filename}: {exc}")
        return {}

    TIER_ISLAND_AFFINITY = {
        'attachment': {'Mother': 0.9, 'Empath': 0.75, 'Friend': 0.35, 'Self': 0.3},
        'repair': {'Empath': 0.9, 'Mother': 0.7, 'Friend': 0.4, 'Self': 0.35},
        'identity': {'Self': 0.85, 'Friend': 0.45, 'Empath': 0.4, 'Mother': 0.35},
        'joy': {'Friend': 0.85, 'Self': 0.4, 'Empath': 0.35, 'Mother': 0.3},
        'shadow': {'Self': 0.8, 'Empath': 0.7, 'Mother': 0.4, 'Friend': 0.3},
        'empathy': {'Empath': 0.9, 'Friend': 0.55, 'Mother': 0.5, 'Self': 0.35},
        'self': {'Self': 0.9, 'Empath': 0.5, 'Friend': 0.35, 'Mother': 0.3},
    }

    def _normalize_soul_weight(self, raw: Any) -> float:
        """
        對齊雙庫 weight 尺度：canon ~0–1；core orb 常見 5.0。
        回傳 0–1，避免 orb 權重碾壓正史。
        """
        try:
            w = float(raw or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if w > 1.0:
            w = w / 5.0
        return max(0.0, min(1.0, w))

    def _derive_trigger_keywords(self, memory: Dict[str, Any]) -> List[str]:
        existing = memory.get('trigger_keywords')
        if isinstance(existing, list) and existing:
            return [str(x).strip() for x in existing if str(x).strip()]
        parts: List[str] = []
        for field in ('trigger', 'anchor', 'title'):
            raw = str(memory.get(field) or '')
            for part in re.split(r'[、,，/；;|\s]+', raw):
                token = part.strip()
                if len(token) >= 2:
                    parts.append(token)
        # 去重保序
        seen = set()
        out = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def _derive_island_affinity(self, memory: Dict[str, Any]) -> Dict[str, float]:
        affinity = memory.get('island_affinity')
        if isinstance(affinity, dict) and affinity:
            cleaned = {}
            for k in ('Mother', 'Friend', 'Empath', 'Self'):
                try:
                    cleaned[k] = max(0.0, min(1.0, float(affinity.get(k, 0.0) or 0.0)))
                except (TypeError, ValueError):
                    cleaned[k] = 0.0
            if any(v > 0 for v in cleaned.values()):
                return cleaned
        tier = str(memory.get('tier') or '').strip().lower()
        mapped = self.TIER_ISLAND_AFFINITY.get(tier)
        if mapped:
            return dict(mapped)
        return {'Mother': 0.25, 'Friend': 0.25, 'Empath': 0.25, 'Self': 0.25}

    def _normalize_soul_candidate(self, memory: Dict[str, Any], *, source: str) -> Dict[str, Any]:
        """統一雙庫候選欄位（不刪減 content）。"""
        item = dict(memory)
        item['source'] = source
        item['memory_id'] = str(memory.get('id') or memory.get('memory_id') or '')
        item['trigger_keywords'] = self._derive_trigger_keywords(item)
        item['island_affinity'] = self._derive_island_affinity(item)
        item['weight_norm'] = self._normalize_soul_weight(item.get('weight'))
        # 確保敘事欄位鍵存在（空字串可接受）
        for key in ('lesson', 'tendency', 'repair_path', 'companion_line', 'title', 'content', 'trigger'):
            if key not in item or item.get(key) is None:
                item[key] = ''
            else:
                item[key] = str(item.get(key) or '')
        return item

    def _iter_soul_memory_candidates(self) -> List[Dict[str, Any]]:
        """雙庫展開為統一候選（不刪減原文）；結果快取於實例。"""
        if self._soul_memory_candidates_cache is not None:
            return self._soul_memory_candidates_cache

        candidates: List[Dict[str, Any]] = []

        canon = self._load_json_data_file('seele_childhood_canon.json')
        for mem in canon.get('memories') or []:
            if not isinstance(mem, dict):
                continue
            # 不帶入非敘事巨型欄位
            slim = {
                k: mem.get(k)
                for k in (
                    'id', 'year', 'age', 'tier', 'title', 'content',
                    'emotion_blend', 'trigger', 'trigger_keywords', 'anchor',
                    'lesson', 'tendency', 'repair_path', 'companion_line',
                    'island_affinity', 'weight',
                )
                if k in mem or k in {
                    'id', 'title', 'content', 'trigger', 'lesson', 'tendency',
                    'repair_path', 'companion_line', 'weight', 'tier', 'anchor',
                }
            }
            candidates.append(
                self._normalize_soul_candidate(slim, source='seele_childhood_canon')
            )

        core = self._load_json_data_file('core_memories.json')
        for key in ('gray_orbs', 'gold_orbs', 'childhood_roots', 'permanent_values'):
            for mem in core.get(key) or []:
                if not isinstance(mem, dict):
                    continue
                slim = {
                    'id': mem.get('id'),
                    'title': mem.get('title', ''),
                    'content': mem.get('content', ''),
                    'trigger': mem.get('trigger') or '',
                    'trigger_keywords': list(mem.get('trigger_keywords') or []),
                    'lesson': mem.get('lesson', ''),
                    'tendency': mem.get('tendency', ''),
                    'repair_path': mem.get('repair_path', ''),
                    'companion_line': mem.get('companion_line', ''),
                    'weight': mem.get('weight', 1.0),
                    'island_affinity': dict(mem.get('island_affinity') or {}),
                    'tier': mem.get('tier', ''),
                    'anchor': mem.get('anchor', ''),
                    'orb_bucket': key,
                }
                candidates.append(
                    self._normalize_soul_candidate(slim, source='core_memories')
                )

        self._soul_memory_candidates_cache = candidates
        return candidates

    def _score_soul_memory(
        self,
        memory: Dict[str, Any],
        user_input: str,
        *,
        primary_island: str,
        intensity: str,
    ) -> float:
        text = str(user_input or '')
        score = 0.0
        title = str(memory.get('title') or '')
        content = str(memory.get('content') or '')
        trigger = str(memory.get('trigger') or '')
        lesson = str(memory.get('lesson') or '')
        tendency = str(memory.get('tendency') or '')
        companion = str(memory.get('companion_line') or '')
        repair = str(memory.get('repair_path') or '')

        keywords = memory.get('trigger_keywords') or []
        if isinstance(keywords, list):
            for kw in keywords:
                token = str(kw or '').strip()
                if token and token in text:
                    score += 1.2
        for token in (trigger, title):
            for part in re.split(r'[、,，/\s]+', str(token)):
                part = part.strip()
                if len(part) >= 2 and part in text:
                    score += 0.9

        for marker in (
            '爸爸', '媽媽', '舊', '學校', '考試', '成績', '陪伴', '擁抱',
            '風扇', '霓虹', '發脾氣', '想靜', '空間', '小事', '記得',
        ):
            if marker in text and marker in (title + content + trigger + companion):
                score += 0.35

        score += 0.08 * float(memory.get('weight_norm') or self._normalize_soul_weight(memory.get('weight')))

        affinity = memory.get('island_affinity')
        if isinstance(affinity, dict) and primary_island:
            try:
                score += 0.35 * float(affinity.get(primary_island, 0.0) or 0.0)
            except (TypeError, ValueError):
                pass

        if intensity in {'crisis', 'high'}:
            blob = f"{title} {content} {lesson} {tendency} {companion} {repair} {memory.get('tier', '')}"
            if any(k in blob for k in (
                '陪伴', '在場', '安撫', '被接住', '安全', '空間', '唔迫',
                'repair', 'attachment', '靜',
            )):
                score += 0.9
            if self._is_anecdote_or_playful_memory(content, memory)[0]:
                score -= 2.0
            if self._is_anecdote_or_playful_memory(content, memory)[1]:
                score -= 2.0

        if memory.get('source') == 'seele_childhood_canon':
            score += 0.08
        return score

    def _select_soul_memory(
        self,
        user_input: str,
        *,
        primary_island: str = 'Empath',
        intensity: str = 'medium',
    ) -> Optional[Dict[str, Any]]:
        """
        過去／童年話題觸發時，雙庫一齊檢索，最多回傳 1 段。
        未觸發則回傳 None。
        """
        if not self._is_past_or_childhood_topic(user_input):
            return None

        best: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for mem in self._iter_soul_memory_candidates():
            content = str(mem.get('content') or '').strip()
            if not content:
                continue
            if self._should_skip_memory_for_expression_gate(
                content,
                mem,
                intensity=intensity,
            ):
                continue
            score = self._score_soul_memory(
                mem,
                user_input,
                primary_island=primary_island,
                intensity=intensity,
            )
            if score > best_score:
                best_score = score
                best = mem

        if best is None or best_score <= 0.0:
            fallback_pool = []
            for mem in self._iter_soul_memory_candidates():
                content = str(mem.get('content') or '').strip()
                if not content:
                    continue
                if self._should_skip_memory_for_expression_gate(
                    content, mem, intensity=intensity
                ):
                    continue
                fallback_pool.append(mem)
            if not fallback_pool:
                return None
            # 話題觸發但無命中：優先 canon，避免 core weight=5 碾壓
            canon_pool = [
                m for m in fallback_pool
                if m.get('source') == 'seele_childhood_canon'
            ]
            pool = canon_pool or fallback_pool
            pool.sort(
                key=lambda m: float(
                    m.get('weight_norm')
                    or self._normalize_soul_weight(m.get('weight'))
                ),
                reverse=True,
            )
            best = pool[0]
            best_score = float(
                best.get('weight_norm')
                or self._normalize_soul_weight(best.get('weight'))
            )

        if best is None:
            return None
        selected = dict(best)
        selected['retrieval_score'] = best_score
        return selected

    def _format_soul_memory_guidance(self, memory: Dict[str, Any]) -> str:
        """將正史／核心記憶格式化為完整指導（Zero-Truncation）。"""
        if not isinstance(memory, dict):
            return ""
        memory_id = str(memory.get('memory_id') or memory.get('id') or '')
        source = str(memory.get('source') or '')
        title = str(memory.get('title') or '').strip()
        content = str(memory.get('content') or '').strip()
        lesson = str(memory.get('lesson') or '').strip()
        tendency = str(memory.get('tendency') or '').strip()
        repair = str(memory.get('repair_path') or '').strip()
        companion = str(memory.get('companion_line') or '').strip()

        lines = [
            "SOUL MEMORY (past topic triggered; use at most this one segment):",
            f"- memory_id: {memory_id}",
            f"- source: {source}",
        ]
        if title:
            lines.append(f"- title: {title}")
        if content:
            lines.append(f"- content: {content}")
        if lesson:
            lines.append(f"- lesson: {lesson}")
        if tendency:
            lines.append(f"- tendency: {tendency}")
        if repair:
            lines.append(f"- repair_path: {repair}")
        if companion:
            lines.append(f"- companion_line: {companion}")
        lines.append(
            "- Rule: let this memory color presence; do not invent conflicting autobiography."
        )
        return "\n".join(lines)

    def _format_memory_context(
        self,
        memories: List[Dict],
        *,
        intensity: Optional[str] = None,
        expression_budget: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        格式化外部／回聲記憶上下文。
        每輪最多 1 段；預設 Zero-Truncation 不裁切正文。
        crisis／high 跳過趣事／鬧向記憶。
        """
        if not memories:
            return ""

        try:
            max_items, max_chars = self._get_memory_snippet_limits()
            if max_items <= 0:
                return ""

            lines = []
            for mem in memories:
                if len(lines) >= max_items:
                    break
                if not isinstance(mem, dict):
                    continue
                content = mem.get('content', mem.get('response', ''))
                if not content or not isinstance(content, str):
                    continue
                if self._is_autobiography_conflict(content, mem):
                    continue
                if self._should_skip_memory_for_expression_gate(
                    content,
                    mem,
                    intensity=intensity,
                    expression_budget=expression_budget,
                ):
                    self.logger.debug(
                        f"Memory injection gate skipped anecdote/playful memory "
                        f"id={mem.get('id', '')} intensity={intensity}"
                    )
                    continue
                snippet = self._clip_memory_snippet(content, max_chars)
                if snippet:
                    lines.append(f"- {snippet}")

            return "\n".join(lines) if lines else ""
        except Exception as e:
            self.logger.error(f"Memory context formatting failed: {e}")
            return ""

    def _sanitize_memory_context(
        self,
        memory_context: str,
        *,
        intensity: Optional[str] = None,
        expression_budget: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        清洗外部注入的記憶上下文：
        - 自傳衝突過濾
        - crisis／high 趣事／鬧向閘門
        - 每輪最多 1 段；預設不裁切正文
        """
        if not memory_context or not isinstance(memory_context, str):
            return ""
        max_items, max_chars = self._get_memory_snippet_limits()
        if max_items <= 0:
            return ""

        safe_lines = []
        for raw_line in memory_context.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            body = line[2:].strip() if line.startswith("- ") else line
            if self._is_autobiography_conflict(body):
                continue
            if self._should_skip_memory_for_expression_gate(
                body,
                None,
                intensity=intensity,
                expression_budget=expression_budget,
            ):
                continue
            body = self._clip_memory_snippet(body, max_chars)
            if not body:
                continue
            safe_lines.append(f"- {body}")
            if len(safe_lines) >= max_items:
                break
        return "\n".join(safe_lines)

    def _is_canonical_memory(self, memory: Optional[Dict] = None) -> bool:
        """
        統一 canonical 判定：與 restrict_memory 白名單對齊，避免 core_ 被誤擋。
        """
        if not isinstance(memory, dict):
            return False

        memory_id = str(memory.get("id", ""))
        if memory_id.startswith(("memory_", "core_", "gold_hk_")):
            return True

        metadata = memory.get("metadata", {})
        if isinstance(metadata, dict):
            memory_type = str(metadata.get("memory_type", "")).lower()
            source = str(metadata.get("source", "")).lower()
            if memory_type in {"core", "canonical"}:
                return True
            if source in {"core", "canonical", "seele_childhood_canon", "core_memories"}:
                return True

        record_type = str(memory.get("record_type", "")).upper()
        if record_type in {"CORE", "CANON"}:
            return True

        return bool(memory.get("protected") or memory.get("locked"))

    def _is_autobiography_conflict(self, text: str, memory: Optional[Dict] = None) -> bool:
        """
        阻擋可能造成「希兒自傳漂移」的內容，僅放行明確 canonical 記憶。
        """
        if not text:
            return False

        if any(marker in text for marker in AUTOBIOGRAPHY_MARKERS) and not self._is_canonical_memory(memory):
            return True
        return False

    async def _monitor_drift(
        self,
        draft_response: str,
        user_input: str,
        current_state: Dict,
        turn_info: Dict,
        memory_policy: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        監測回應漂移，回傳統一 drift 資訊供閉環控制。
        """
        threshold = float(self.config.get('drift_threshold', 0.65))
        critical_threshold = min(0.95, threshold + 0.2)
        baseline = {
            'drift_score': 0.0,
            'alert_level': 'none',
            'available': False,
            'threshold': threshold,
            'critical_threshold': critical_threshold,
            'closest_core_memory': None,
            'restrict_memory': False,
            'candidate_k': 5,
            'correlation_id': correlation_id,
        }
        if not self.gsw_engine:
            return baseline

        response_vector = turn_info.get('response_embedding')
        if not response_vector and self.vector_service and draft_response:
            try:
                response_vector = await self._run_in_executor_safe(
                    self.vector_service.get_semantic_embedding,
                    draft_response,
                )
            except Exception as exc:
                self.logger.warning(f"Drift embedding generation failed: {exc}")
                response_vector = []

        if not response_vector:
            return baseline

        if not isinstance(memory_policy, dict):
            memory_policy = {}
        restrict_memory = bool(memory_policy.get('restrict_memory', False))
        candidate_k = int(self._safe_float(
            memory_policy.get('gsw_top_k', 5),
            default=5,
            min_value=1,
            max_value=20,
        ))

        try:
            try:
                raw = await self.gsw_engine.detect_drift(
                    response_vector=response_vector,
                    user_input=user_input,
                    session_state=current_state,
                    restrict_memory=restrict_memory,
                    candidate_k=candidate_k,
                    correlation_id=correlation_id,
                )
            except TypeError:
                # 相容舊版 detect_drift 簽名
                raw = await self.gsw_engine.detect_drift(
                    response_vector=response_vector,
                    user_input=user_input,
                    session_state=current_state,
                )
            drift_score = max(0.0, min(1.0, float(raw.get('drift_score', 0.0))))
            alert_level = self._classify_drift_alert(
                drift_score,
                threshold=threshold,
                critical_threshold=critical_threshold,
            )
            result = {
                'drift_score': drift_score,
                'alert_level': alert_level,
                'available': True,
                'threshold': threshold,
                'critical_threshold': critical_threshold,
                'closest_core_memory': raw.get('closest_core_memory'),
                'restrict_memory': restrict_memory,
                'candidate_k': candidate_k,
                'correlation_id': correlation_id,
            }
            if alert_level != 'none':
                self.logger.warning(
                    f"[DRIFT] alert={alert_level} score={drift_score:.3f} "
                    f"(threshold={threshold:.2f})"
                )
            return result
        except Exception as exc:
            self.logger.error(f"Drift monitoring failed: {exc}")
            return baseline

    def _classify_drift_alert(
        self,
        drift_score: float,
        *,
        threshold: float,
        critical_threshold: float,
    ) -> str:
        if drift_score >= critical_threshold:
            return 'critical'
        if drift_score >= threshold:
            return 'warning'
        return 'none'

    def _monitor_metacognition(
        self,
        *,
        user_input: str,
        perception_data: Dict[str, Any],
        turn_info: Dict[str, Any],
        current_state: Dict[str, Any],
        drift_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        呼叫 metacognitive_system 取得控制參數，並回傳可用結果。
        """
        if not self.metacognitive_system:
            return {}
        try:
            extracted_info = dict(turn_info)
            extracted_info['retrieved_memories'] = perception_data.get('retrieved_memories', [])
            extracted_info['narrative_drift_signal'] = drift_info.get('drift_score', 0.0)
            return self.metacognitive_system.monitor_process(
                user_input=user_input,
                island_activation=perception_data.get('island_activation', {}),
                extracted_info=extracted_info,
                session_state=current_state,
                dyadic_dynamics=self.dyadic_dynamics,
            )
        except Exception as exc:
            self.logger.warning(f"Metacognitive monitor failed: {exc}")
            return {}

    def _apply_meta_drift_alert(
        self,
        drift_info: Dict[str, Any],
        meta_control: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        將 metacognitive drift_alert_level 合併回 drift_info。
        """
        if not drift_info:
            drift_info = {}
        if not meta_control:
            return drift_info

        meta_level = str(meta_control.get('drift_alert_level', 'none'))
        current_level = str(drift_info.get('alert_level', 'none'))
        priority = {'none': 0, 'warning': 1, 'critical': 2}
        merged_level = meta_level
        if priority.get(current_level, 0) > priority.get(meta_level, 0):
            merged_level = current_level

        merged = dict(drift_info)
        merged['alert_level'] = merged_level
        merged['metacognitive_drift_alert_level'] = meta_level
        return merged

    async def _apply_meta_memory_controls(
        self,
        *,
        user_embedding: List[float],
        user_id: Optional[str],
        preloaded_memories: Any,
        meta_control: Dict[str, Any],
    ) -> List[Dict]:
        """
        將 metacognitive 的 gsw_top_k / restrict_memory 套用到實際記憶檢索路徑。
        """
        if not isinstance(meta_control, dict):
            meta_control = {}

        gsw_top_k = int(self._safe_float(meta_control.get('gsw_top_k', 4), default=4, min_value=1, max_value=20))
        restrict_memory = bool(meta_control.get('restrict_memory', False))

        memories: List[Dict] = []
        if isinstance(preloaded_memories, list):
            memories = [m for m in preloaded_memories if isinstance(m, dict)]
        elif self.gsw_engine and user_embedding:
            memories = await self._safe_memory_search(
                user_embedding=user_embedding,
                user_id=user_id,
                k=gsw_top_k,
            )
            if not isinstance(memories, list):
                memories = []

        memories = [m for m in memories if isinstance(m, dict)]
        memories = memories[:gsw_top_k]
        if restrict_memory:
            memories = [m for m in memories if self._is_allowed_under_restrict_memory(m)]

        return memories

    def _is_allowed_under_restrict_memory(self, memory: Dict[str, Any]) -> bool:
        """
        restrict_memory 開啟時只允許核心/正史/永迴軌類記憶來源。
        """
        memory_id = str(memory.get('id', ''))
        if memory_id.startswith(('core_', 'memory_', 'echo_')):
            return True

        metadata = memory.get('metadata', {})
        if isinstance(metadata, dict):
            memory_type = str(metadata.get('memory_type', '')).lower()
            source = str(metadata.get('source', '')).lower()
            if memory_type in {'core', 'canonical', 'eternal_echo'}:
                return True
            if source in {'core', 'canonical', 'eternal_echo', 'seele_childhood_canon'}:
                return True

        record_type = str(memory.get('record_type', '')).upper()
        if record_type in {'CORE', 'CANON', 'ETERNAL_ECHO'}:
            return True

        return False

    def _apply_conflict_repair(
        self,
        response: str,
        *,
        user_input: str = "",
        drift_info: Optional[Dict[str, Any]] = None,
        soul_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """P4：衝突偵測＋軟修復；失敗時安全回退原文。"""
        if not response:
            return {"text": response or "", "repaired": False, "actions": [], "findings": []}
        if not self.conflict_repair:
            return {"text": response, "repaired": False, "actions": [], "findings": []}
        try:
            result = self.conflict_repair.assess_and_repair(
                response,
                user_input=user_input,
                drift_info=drift_info,
                soul_memory=soul_memory,
            )
            public = result.to_public_dict()
            public["text"] = result.text
            return public
        except Exception as exc:
            self.logger.warning(f"Conflict repair failed: {exc}")
            return {"text": response, "repaired": False, "actions": [], "findings": [], "error": str(exc)}

    def _enforce_drift_guardrail_text(self, response: str, drift_info: Dict[str, Any]) -> str:
        """
        告警時做最小侵入式文本限制，避免新增自傳敘事漂移。
        若已注入 ConflictRepair，交由後續 _apply_conflict_repair 統一處理（避免雙重前置句）。
        """
        if not response:
            return response
        if self.conflict_repair:
            return response

        level = drift_info.get('alert_level', 'none') if isinstance(drift_info, dict) else 'none'
        if level == 'none':
            return response

        stabilized = response
        for marker in AUTOBIOGRAPHY_MARKERS:
            if marker in stabilized:
                stabilized = stabilized.replace(marker, "我記得")

        if level == 'critical' and stabilized != response:
            prefix = "我想先核對返記憶一致性，免得講錯。"
            if not stabilized.startswith(prefix):
                stabilized = f"{prefix}{stabilized}"

        return stabilized

    def _safe_float(
        self,
        value: Any,
        *,
        default: float,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> float:
        """安全轉 float 並套用邊界。"""
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        if min_value is not None:
            number = max(min_value, number)
        if max_value is not None:
            number = min(max_value, number)
        return number

    def _new_decision_correlation_id(self, turn_count: int) -> str:
        """生成可追蹤的 decision correlation id。"""
        return f"dec_{turn_count}_{uuid.uuid4().hex[:10]}"

    def _create_background_task(
        self,
        user_input: str,
        final_response: str,
        perception_data: Dict,
        session_state: Dict,
        turn_info: Dict,
        heretic_log: Dict,
        system_prompt: str = "",
        drift_info: Optional[Dict] = None,
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
                    system_prompt=system_prompt,
                    drift_info=drift_info,
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
        system_prompt: str = "",
        drift_info: Optional[Dict] = None,
    ):
        """
        [FIXED-P2,P4] 改善背景記憶內化 - 完整修正
        """
        try:
            primary_island = perception_data.get('primary_island', 'Empath')

            # 1. 永迴軌生成（P3.4：不可改寫正史；可分級跳過）
            skip_echo, skip_reason = self._should_skip_echo_consolidation(
                turn_info=turn_info,
                session_state=session_state,
                final_response=final_response,
                drift_info=drift_info,
            )
            if skip_echo:
                self.logger.info(
                    f"Skip eternal echo consolidation: {skip_reason}"
                )
                session_state['echo_consolidation_skipped'] = skip_reason
            elif self.gsw_engine:
                try:
                    should_generate, echo_score = self.gsw_engine.judge_eternal_echo_generation(
                        final_response, turn_info, session_state
                    )

                    # [FIXED-P2] 驗證 echo_score
                    if should_generate and isinstance(echo_score, (int, float)):
                        echo_id = await self.gsw_engine.generate_and_store_echo(
                            user_input, final_response, turn_info, session_state, echo_score
                        )
                        # 防呆：若回傳正史 id，拒絕寫入狀態
                        if self.is_immutable_soul_memory_id(echo_id):
                            self.logger.error(
                                f"Rejected echo id colliding with immutable soul id: {echo_id}"
                            )
                            echo_id = ""
                        session_state['last_eternal_echo_id'] = echo_id
                        self.logger.debug(f"Generated eternal echo {echo_id} with score {echo_score}")
                    elif should_generate:
                        self.logger.warning(f"Invalid echo_score type: {type(echo_score)}")

                except Exception as e:
                    self.logger.error(f"Eternal echo generation failed: {e}")

            # 2. 親密度更新
            try:
                old_intimacy = float(session_state.get('intimacy', 0.5))
                new_intimacy = old_intimacy
                meta_control = turn_info.get('metacognitive_control', {})
                if not isinstance(meta_control, dict):
                    meta_control = {}

                meta_multiplier = self._safe_float(
                    meta_control.get('boundary_multiplier', 1.0),
                    default=1.0,
                    min_value=0.0,
                    max_value=1.0,
                )
                force_reflection = bool(meta_control.get('force_reflection', False))
                meta_alert_level = str(meta_control.get('drift_alert_level', 'none'))

                effective_multiplier = self.boundary_multiplier * meta_multiplier
                base_delta = 0.01 * effective_multiplier

                # 情感詞檢測
                positive_keywords = ['謝謝', '感動', '多謝', '很好', '開心', '很棒']
                positive_delta = 0.0
                if any(kw in user_input for kw in positive_keywords):
                    positive_delta = 0.05
                    if force_reflection:
                        positive_delta *= 0.3 * max(0.25, meta_multiplier)
                    else:
                        positive_delta *= max(0.5, meta_multiplier)

                delta = base_delta + positive_delta

                # metacognitive force_reflection 會收緊單回合親密增長上限
                if force_reflection:
                    max_delta = max(0.005, 0.02 * max(0.25, meta_multiplier))
                    delta = min(delta, max_delta)

                # critical drift 告警時，禁止正向親密跳增
                if meta_alert_level == 'critical':
                    delta = min(delta, 0.002)

                new_intimacy += delta

                session_state['intimacy'] = max(0.0, min(1.0, new_intimacy))
                session_state['last_intimacy_delta'] = round(
                    session_state['intimacy'] - old_intimacy,
                    6,
                )

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
                    'intimacy_delta': session_state.get('last_intimacy_delta', 0.0),
                    'system_prompt_type': system_prompt[:50] if system_prompt else None,
                    'drift_score': (drift_info or {}).get('drift_score', 0.0),
                    'drift_alert_level': (drift_info or {}).get('alert_level', 'none'),
                    'decision_correlation_id': turn_info.get('decision_correlation_id'),
                    'meta_boundary_multiplier': (
                        turn_info.get('metacognitive_control', {}).get('boundary_multiplier')
                        if isinstance(turn_info.get('metacognitive_control', {}), dict)
                        else None
                    ),
                    'meta_force_reflection': (
                        bool(turn_info.get('metacognitive_control', {}).get('force_reflection', False))
                        if isinstance(turn_info.get('metacognitive_control', {}), dict)
                        else False
                    ),
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