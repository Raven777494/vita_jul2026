# system_alignment_checker.py
# 系統對齊檢查工具 v2.0 - 真正的反射式驗證（Zero-Truncation）
#
# 設計目標：
#   先前版本（v1.x）的 _check_* 全部寫死回傳 PASS，且 CHECKS 內宣稱的方法名
#   （_inject_particles / _enforce_short_sentences / _apply_island_tone）與實際
#   程式碼不符，因此會給出「全部對齊」的虛假信心。
#
# 本版本改為真正以 importlib / inspect 反射驗證：
#   1. 模組可被匯入
#   2. 類別存在
#   3. 必要方法存在且可呼叫
#   4. 指定方法為非同步（async def）
#   5. 方法簽名包含預期參數
#   6. 類別 / 模組層級常量存在
#   7. 原始碼包含預期整合片段（source_contains）
#   8. 原始碼不含已知 bug 片段（source_absent，用以偵測回歸）
#
# 注意：輸出一律使用純文字標記（[OK] / [FAIL] / [--]），不使用任何 emoji 或符號圖示。

import importlib
import inspect
from datetime import datetime
from typing import Any, Dict, List


class SystemAlignmentChecker:
    """系統一致性檢查工具（反射式實裝）"""

    # ==================== 檢查規格定義 ====================
    #
    # 每個規格欄位說明：
    #   group            : 群組鍵
    #   name             : 顯示名稱
    #   module           : 要匯入的模組路徑
    #   class            : 要驗證的類別名稱（可為 None，僅做模組層級檢查）
    #   methods          : 必須存在且可呼叫的方法名稱
    #   async_methods    : 必須為 async def 的方法名稱
    #   signatures       : { 方法名: [預期參數名, ...] }（不含 self）
    #   class_attributes : 類別層級必須存在的屬性/常量
    #   module_attributes: 模組層級必須存在的屬性/常量
    #   source_contains  : 類別原始碼必須包含的片段
    #   source_absent    : 類別原始碼不應包含的片段（偵測已知 bug 回歸）

    CHECKS: List[Dict[str, Any]] = [
        {
            'group': 'vocal_personality_layer',
            'name': 'VocalPersonalityLayer 對齊',
            'module': 'PersonalityModule.vocal_personality_layer',
            'class': 'VocalPersonalityLayer',
            'methods': [
                '__init__',
                'finalize_voice',
                '_smart_particle_injection',
                '_detect_existing_particle',
                '_select_contextual_particle',
                '_safe_sentence_structure',
                '_intelligent_sentence_split',
                '_natural_sentence_break',
                '_enhance_fluency',
                '_final_cleanup',
                'setup_dependencies',
                'get_stats',
            ],
            'async_methods': [
                'finalize_voice',
                '_safe_sentence_structure',
            ],
            'signatures': {
                'finalize_voice': ['draft_response', 'context'],
                'setup_dependencies': ['island_fusion', 'heretic_coordinator'],
            },
            'class_attributes': [
                'PERSONALITY_PARTICLES',
                'ISLAND_SIGNATURE_WORDS',
                'SENTENCE_TERMINATORS',
            ],
        },
        {
            'group': 'personality_module',
            'name': 'PersonalityModule 集成',
            'module': 'PersonalityModule.personality_module',
            'class': 'PersonalityModule',
            'methods': [
                '__init__',
                'setup_dependencies',
                'anchor',
                'shutdown',
                'get_system_health',
                'cancel_background_tasks',
            ],
            'async_methods': [
                'anchor',
                'get_system_health',
                'cancel_background_tasks',
            ],
            'signatures': {
                'anchor': ['draft_response', 'user_input', 'session_state', 'turn_info'],
            },
            'module_attributes': [
                'PERSONALITY_PARTICLES',
                'CRISIS_KEYWORDS',
            ],
            # 確認 anchor 確實調用聲音層的 finalize_voice，且使用注入的 navigator
            'source_contains': [
                'finalize_voice',
                "dependencies.get('intelligent_navigator')",
            ],
            # 偵測回歸：不應再出現無參數重建 navigator 的舊寫法
            'source_absent': [
                'self.intelligent_navigator = IntelligentNavigator()',
            ],
        },
        {
            'group': 'intelligent_navigator',
            'name': 'IntelligentNavigator 對齊',
            'module': 'app.services.fracture_map.intelligent_navigator',
            'class': 'IntelligentNavigator',
            'methods': [
                '__init__',
                'navigate_async',
                'navigate',
                'detect_fractures',
                'get_stats',
                'close',
            ],
            'async_methods': [
                'navigate_async',
            ],
            'signatures': {
                'navigate_async': ['user_id', 'user_input', 'session_history', 'intimacy'],
            },
        },
        {
            'group': 'navigation_decision',
            'name': 'NavigationDecision 資料結構對齊',
            'module': 'app.services.fracture_map.intelligent_navigator',
            'class': 'NavigationDecision',
            'methods': [],
            'class_attributes': [
                '__dataclass_fields__',
            ],
            # orchestrator 讀取的欄位必須存在於 dataclass
            'dataclass_fields': [
                'decision_id',
                'user_id',
                'detected_fractures',
                'decision_type',
                'intimacy_level',
                'total_time',
                'final_response',
            ],
        },
        {
            'group': 'gsw_engine',
            'name': 'GSWEngine 對齊',
            'module': 'PersonalityModule.gsw_engine',
            'class': 'GSWEngine',
            'methods': [
                'search_memories',
                'detect_drift',
                'judge_eternal_echo_generation',
                'generate_and_store_echo',
                'shutdown',
            ],
            'async_methods': [
                'search_memories',
                'detect_drift',
                'generate_and_store_echo',
            ],
        },
        {
            'group': 'orchestrator',
            'name': 'Orchestrator 整合對齊',
            'module': 'app.orchestrator',
            'class': 'Orchestrator',
            'methods': [
                '__init__',
                'process',
                'process_user_message_async',
                'shutdown',
                'wait_for_background_tasks',
                '_resolve_session_id',
            ],
            'async_methods': [
                'process',
                'process_user_message_async',
                'wait_for_background_tasks',
            ],
            'signatures': {
                'process': ['request', 'language_hint'],
                '__init__': ['redis_config', 'shared_services'],
            },
            # 確認核心委派鏈與正確的 DB API
            'source_contains': [
                'self.personality.anchor',
                'navigate_async',
                'self.db.get_session_state(session_id)',
            ],
            # 偵測回歸：db_manager.get_session 不接受 session_id 參數
            'source_absent': [
                'self.db.get_session(session_id)',
            ],
        },
        {
            'group': 'db_manager',
            'name': 'DatabaseManager 介面對齊',
            'module': 'app.services.db_manager',
            'class': 'DatabaseManager',
            'methods': [
                'get_session',
                'get_session_state',
                'find_active_session_by_user',
                'create_session',
                'store_turn',
                'execute_query',
                'health_check',
                'close',
            ],
            'signatures': {
                'get_session_state': ['session_id'],
                'store_turn': ['session_id', 'user_id', 'role', 'text'],
            },
            # 確認 store_turn 使用正確的模型屬性名（metadata_dict 而非 metadata）
            'source_contains': [
                'metadata_dict=metadata or {}',
            ],
            'source_absent': [
                'metadata=metadata or {}',
            ],
        },
        {
            'group': 'companion_language',
            'name': 'CompanionLanguagePolicy 對齊',
            'module': 'app.clinical.companion_language_policy',
            'class': None,
            'module_attributes': [
                'COMPANION_SAFE_REPLIES',
                'FORBIDDEN_PATTERNS',
                'get_companion_reply',
                'validate_user_facing_text',
                'validate_crisis_companion_text',
            ],
            'source_absent': [
                '2389-2222',
                '撒瑪利亞',
                '求助熱線',
            ],
        },
    ]

    RUNTIME_CHECKS: List[Dict[str, Any]] = [
        {
            'group': 'platform_engine',
            'name': 'Platform Engine (Docker Postgres: vector + AGE + pg_cron)',
            'runtime': 'platform_engine',
        },
    ]

    # ==================== 主流程 ====================

    def run_all_checks(self) -> Dict[str, Any]:
        """執行所有檢查並回傳結果"""
        results: Dict[str, Any] = {
            'timestamp': self._get_timestamp(),
            'status': 'PASS',
            'checks': {},
            'summary': {},
        }

        for spec in self.CHECKS:
            group_result = self._check_group(spec)
            results['checks'][spec['group']] = group_result
            # 只有真正的 FAIL 才會讓整體狀態變為 FAIL；SKIP（環境/依賴缺失）不算對齊失敗
            if group_result['status'] == 'FAIL':
                results['status'] = 'FAIL'

        for spec in self.RUNTIME_CHECKS:
            group_result = self._check_runtime(spec)
            results['checks'][spec['group']] = group_result
            if group_result['status'] == 'FAIL':
                results['status'] = 'FAIL'

        memory_result = self._check_memory_model_alignment()
        results['checks']['memory_model'] = memory_result
        if memory_result['status'] == 'FAIL':
            results['status'] = 'FAIL'

        results['summary'] = self._generate_summary(results['checks'])
        return results

    def _check_memory_model_alignment(self) -> Dict[str, Any]:
        """Verify ADR-002 primary path and no runtime AGE dual-write (P4-4)."""
        try:
            from app.governance.memory_model_alignment import verify_memory_model_alignment
        except Exception as exc:
            return {
                'name': 'Memory model alignment (ADR-002)',
                'status': 'FAIL',
                'checked': [],
                'issues': [f"Cannot import memory_model_alignment: {exc}"],
            }

        report = verify_memory_model_alignment()
        return {
            'name': 'Memory model alignment (ADR-002)',
            'status': 'PASS' if report.ok else 'FAIL',
            'checked': list(report.checked),
            'issues': list(report.issues),
        }

    def _check_runtime(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Execute live environment checks (database, extensions, etc.)."""
        runtime_key = spec.get('runtime')
        if runtime_key == 'platform_engine':
            return self._check_platform_engine_runtime(spec)
        return {
            'name': spec.get('name', runtime_key or 'runtime'),
            'status': 'FAIL',
            'checked': [],
            'issues': [f"Unknown runtime check: {runtime_key}"],
        }

    def _check_platform_engine_runtime(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Verify PostgreSQL has vector, age, pg_cron and vita_memory_graph."""
        try:
            from app.config import config
            from app.services.platform_engine_check import verify_platform_engine_or_skip
        except Exception as exc:
            return {
                'name': spec['name'],
                'status': 'SKIP',
                'checked': [],
                'issues': [f"略過（環境問題）：無法載入 Platform Engine 檢查模組: {exc}"],
            }

        if not getattr(config, 'DB_PLATFORM_ENGINE_REQUIRED', True):
            return {
                'name': spec['name'],
                'status': 'SKIP',
                'checked': [],
                'issues': ['略過：DB_PLATFORM_ENGINE_REQUIRED=false'],
            }

        status, report = verify_platform_engine_or_skip(require_age_graph=True)
        checked = list(report.checked)
        checked.append(
            f"DB target: {report.db_host}:{report.db_port}/{report.db_name}"
        )
        if report.server_version:
            checked.append(f"Server: {report.server_version[:80]}")

        if status == 'SKIP':
            return {
                'name': spec['name'],
                'status': 'SKIP',
                'checked': checked,
                'issues': report.issues or ['Database unreachable; start docker compose postgres'],
            }

        return {
            'name': spec['name'],
            'status': 'PASS' if status == 'PASS' else 'FAIL',
            'checked': checked,
            'issues': report.issues,
        }

    def _check_group(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """對單一規格執行反射式檢查"""
        issues: List[str] = []
        checked: List[str] = []

        # 1. 匯入模組
        target = spec['module']
        try:
            module = importlib.import_module(target)
        except ModuleNotFoundError as e:
            missing = getattr(e, 'name', '') or ''
            # 區分兩種情況：
            #   (a) 目標模組本身不存在        -> 真正的對齊失敗 (FAIL)
            #   (b) 目標所依賴的第三方套件缺失 -> 環境問題，非對齊問題 (SKIP)
            is_target_itself = (
                missing == target
                or target == missing
                or target.startswith(missing + '.')
            )
            if missing and not is_target_itself:
                return {
                    'name': spec['name'],
                    'status': 'SKIP',
                    'checked': [],
                    'issues': [
                        f"略過（環境問題，非對齊問題）：缺少第三方依賴 '{missing}'。"
                        f"請在正確的虛擬環境安裝專案依賴（pip install -r requirements.txt）後重試。"
                    ],
                }
            return {
                'name': spec['name'],
                'status': 'FAIL',
                'checked': [],
                'issues': [f"無法匯入目標模組 {target}（模組本身缺失）: {e}"],
            }
        except Exception as e:
            return {
                'name': spec['name'],
                'status': 'FAIL',
                'checked': [],
                'issues': [f"匯入模組 {target} 時發生非預期錯誤: {e}"],
            }
        checked.append(f"模組可匯入: {target}")

        # 2. 模組層級屬性
        for attr in spec.get('module_attributes', []):
            if hasattr(module, attr):
                checked.append(f"模組屬性存在: {attr}")
            else:
                issues.append(f"模組缺少屬性: {attr}")

        cls = None
        class_name = spec.get('class')
        if class_name:
            cls = getattr(module, class_name, None)
            if cls is None:
                issues.append(f"找不到類別: {class_name}")
            else:
                checked.append(f"類別存在: {class_name}")

        if cls is not None:
            self._check_class(cls, spec, issues, checked)

        return {
            'name': spec['name'],
            'status': 'PASS' if not issues else 'FAIL',
            'checked': checked,
            'issues': issues,
        }

    def _check_class(
        self,
        cls: Any,
        spec: Dict[str, Any],
        issues: List[str],
        checked: List[str],
    ) -> None:
        """檢查類別的方法、async、簽名、屬性與原始碼片段"""

        # 方法存在且可呼叫
        for method_name in spec.get('methods', []):
            fn = getattr(cls, method_name, None)
            if fn is None or not callable(fn):
                issues.append(f"缺少方法: {method_name}")
            else:
                checked.append(f"方法存在: {method_name}")

        # 非同步方法
        for method_name in spec.get('async_methods', []):
            fn = getattr(cls, method_name, None)
            if fn is None:
                issues.append(f"缺少非同步方法: {method_name}")
            elif not inspect.iscoroutinefunction(fn):
                issues.append(f"方法應為非同步(async def): {method_name}")
            else:
                checked.append(f"非同步方法正確: {method_name}")

        # 方法簽名
        for method_name, expected_params in spec.get('signatures', {}).items():
            fn = getattr(cls, method_name, None)
            if fn is None:
                issues.append(f"簽名檢查失敗，方法不存在: {method_name}")
                continue
            try:
                sig = inspect.signature(fn)
                param_names = [p for p in sig.parameters.keys() if p != 'self']
                missing = [p for p in expected_params if p not in param_names]
                if missing:
                    issues.append(
                        f"方法 {method_name} 缺少預期參數: {missing} "
                        f"(實際: {param_names})"
                    )
                else:
                    checked.append(
                        f"方法簽名對齊: {method_name}({', '.join(expected_params)})"
                    )
            except (ValueError, TypeError) as e:
                issues.append(f"無法解析 {method_name} 簽名: {e}")

        # 類別層級屬性
        for attr in spec.get('class_attributes', []):
            if hasattr(cls, attr):
                checked.append(f"類別屬性存在: {attr}")
            else:
                issues.append(f"類別缺少屬性: {attr}")

        # dataclass 欄位
        expected_fields = spec.get('dataclass_fields', [])
        if expected_fields:
            dc_fields = getattr(cls, '__dataclass_fields__', None)
            if not dc_fields:
                issues.append(f"{cls.__name__} 不是 dataclass 或缺少欄位資訊")
            else:
                for field_name in expected_fields:
                    if field_name in dc_fields:
                        checked.append(f"dataclass 欄位存在: {field_name}")
                    else:
                        issues.append(f"dataclass 缺少欄位: {field_name}")

        # 原始碼片段檢查
        need_source = spec.get('source_contains') or spec.get('source_absent')
        source = None
        if need_source:
            try:
                source = inspect.getsource(cls)
            except (OSError, TypeError) as e:
                issues.append(f"無法取得 {cls.__name__} 原始碼: {e}")

        if source is not None:
            for token in spec.get('source_contains', []):
                if token in source:
                    checked.append(f"原始碼包含預期片段: {token}")
                else:
                    issues.append(f"原始碼缺少預期片段: {token}")
            for token in spec.get('source_absent', []):
                if token in source:
                    issues.append(
                        f"原始碼包含不應存在的片段（疑似 bug 回歸）: {token}"
                    )
                else:
                    checked.append(f"原始碼未含禁用片段: {token}")

    # ==================== 摘要與報告 ====================

    def _generate_summary(self, checks: Dict[str, Any]) -> Dict[str, Any]:
        """生成總結"""
        total = len(checks)
        passed = sum(1 for c in checks.values() if c['status'] == 'PASS')
        failed = sum(1 for c in checks.values() if c['status'] == 'FAIL')
        skipped = sum(1 for c in checks.values() if c['status'] == 'SKIP')
        total_issues = sum(len(c['issues']) for c in checks.values() if c['status'] == 'FAIL')
        # 通過率以「實際可驗證」的群組為分母（排除環境略過者）
        verifiable = total - skipped

        return {
            'total_groups': total,
            'passed_groups': passed,
            'failed_groups': failed,
            'skipped_groups': skipped,
            'total_issues': total_issues,
            'pass_rate': (
                f"{(passed / verifiable * 100):.1f}%" if verifiable else "N/A (全部因環境略過)"
            ),
        }

    def _get_timestamp(self) -> str:
        """取得時間戳"""
        return datetime.now().isoformat()

    def print_report(self, results: Dict[str, Any]) -> None:
        """列印檢查報告（純文字，不使用 emoji）"""
        print("\n" + "=" * 70)
        print("系統一致性檢查報告 v2.0")
        print("=" * 70)

        print(f"\n整體狀態: [{results['status']}]")
        print(f"時間戳: {results['timestamp']}")

        print("\n摘要:")
        for key, value in results['summary'].items():
            print(f"  {key}: {value}")

        print("\n詳細檢查:")
        status_markers = {'PASS': "[OK]", 'FAIL': "[FAIL]", 'SKIP': "[SKIP]"}
        for group_name, group_result in results['checks'].items():
            marker = status_markers.get(group_result['status'], "[FAIL]")
            print(f"\n{marker} {group_result['name']} ({group_name})")

            for item in group_result.get('checked', []):
                print(f"    [--] {item}")

            for issue in group_result.get('issues', []):
                prefix = "[~]" if group_result['status'] == 'SKIP' else "[X] "
                print(f"    {prefix} {issue}")

        print("\n" + "=" * 70 + "\n")
        # 確保緩衝區刷新（避免與 logging stderr 交錯造成顯示截斷）
        import sys as _sys
        _sys.stdout.flush()


def run() -> int:
    """執行檢查並回傳 process exit code（0 = PASS, 1 = FAIL）"""
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    checker = SystemAlignmentChecker()
    results = checker.run_all_checks()
    checker.print_report(results)
    return 0 if results['status'] == 'PASS' else 1


if __name__ == "__main__":
    import sys
    sys.exit(run())
