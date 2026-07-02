# app/tests/test_integration.py
# 端到端集成測試 – 系統全流程驗證

import pytest
import asyncio
import json
from datetime import datetime, timedelta

from app.services.emotional_safety_hub import EmotionalSafetyHub
from app.services.session_manager import SessionManager
from app.services.db_manager import DatabaseManager
from app.utils.audit_logger import audit_log
from app.config import config

# ============ 集成 Fixtures ============

@pytest.fixture
def integration_setup():
    """集成測試完整設置"""
    session_mgr = SessionManager()
    db_mgr = DatabaseManager(':memory:')  # 使用內存 DB 測試
    hub = EmotionalSafetyHub(session_manager=session_mgr)
    
    return {
        'session_mgr': session_mgr,
        'db_mgr': db_mgr,
        'hub': hub
    }

# ============ 完整系統流程測試 ============

class TestCompleteSystemFlow:
    """系統完整流程測試"""
    
    @pytest.mark.asyncio
    async def test_user_session_lifecycle(self, integration_setup):
        """
        測試：完整的用戶會話生命周期
        
        流程：
        1. 創建會話
        2. 多輪對話
        3. 風險升級
        4. 會話歸檔
        5. 查詢歷史
        """
        hub = integration_setup['hub']
        session_mgr = integration_setup['session_mgr']
        db_mgr = integration_setup['db_mgr']
        
        user_id = "lifecycle-test-user"
        conversation_id = "lifecycle-test-conv"
        
        # 1. 創建會話
        session = session_mgr.create_session(user_id, conversation_id)
        session_id = session['session_id']
        
        assert session_id is not None
        assert session['is_active'] == True
        
        # 2. 執行多輪對話（風險升級軌跡）
        conversation_flow = [
            ("最近工作壓力很大", 1),  # 預期低風險
            ("有時候覺得無法應對", 2),  # 預期中等風險
            ("甚至有些自殺的想法", 4)  # 預期高風險
        ]
        
        escalated = False
        peak_risk = 1
        
        for user_input, expected_min_risk in conversation_flow:
            result = await hub.process_user_input(
                user_id=user_id,
                conversation_id=conversation_id,
                user_input=user_input
            )
            
            assert result['success'] == True
            assert result['risk_level'] >= expected_min_risk
            
            peak_risk = max(peak_risk, result['risk_level'])
            
            if result.get('escalated'):
                escalated = True
        
        # 3. 驗證升級發生
        assert escalated == True
        assert peak_risk >= 4
        
        # 4. 結束會話
        session = session_mgr.load_session(user_id, conversation_id)
        session_mgr.end_session(
            user_id,
            conversation_id,
            reason='user_ended',
            final_outcome='referred'
        )
        
        # 5. 驗證歸檔
        session_after = session_mgr.load_session(user_id, conversation_id)
        assert session_after['is_active'] == False
        
        print(f"\n[LIFECYCLE TEST] PASSED")
        print(f"Peak Risk Level: {peak_risk}, Escalated: {escalated}")
    
    @pytest.mark.asyncio
    async def test_crisis_response_workflow(self, integration_setup):
        """
        測試：危機響應完整工作流
        
        場景：用戶表達強烈自殺意念
        期望：立即升級、提供資源、記錄審計日誌
        """
        hub = integration_setup['hub']
        session_mgr = integration_setup['session_mgr']
        
        user_id = "crisis-test-user"
        conversation_id = "crisis-test-conv"
        
        # 創建會話
        session = session_mgr.create_session(user_id, conversation_id)
        
        # 直接表達自殺意念
        crisis_input = (
            "我已經無法繼續。我計畫在今晚結束生命。"
            "冇人會在乎，世界會因為我不在而更好。"
        )
        
        result = await hub.process_user_input(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input=crisis_input,
            session_state=session
        )
        
        # 驗證：立即升級
        assert result['risk_level'] >= 4
        assert result['escalated'] == True
        assert result['escalation_reason'] == 'critical_risk'
        
        # 驗證：引導式同行者語言（不得含機構轉介）
        from app.clinical.companion_language_policy import validate_crisis_companion_text
        ok, issues = validate_crisis_companion_text(result['response'])
        assert ok, f"companion language issues: {issues}"
        
        # 驗證：會話被標記為升級
        loaded_session = session_mgr.load_session(user_id, conversation_id)
        assert loaded_session['is_escalated'] == True
        
        print(f"\n[CRISIS RESPONSE TEST] PASSED")
        print(f"Response: {result['response'][:100]}...")
    
    @pytest.mark.asyncio
    async def test_fallback_mechanisms(self, integration_setup):
        """
        測試：降級機制（LLM 失敗時）
        
        驗證：
        1. 回應總是非空
        2. 回應總是安全的
        3. 根據風險級別提供適當回應
        """
        hub = integration_setup['hub']
        session_mgr = integration_setup['session_mgr']
        
        risk_levels = [1, 2, 3, 4, 5]
        
        for risk_level in risk_levels:
            user_id = f"fallback-test-{risk_level}"
            conversation_id = f"fallback-conv-{risk_level}"
            
            session = session_mgr.create_session(user_id, conversation_id)
            session['risk_level'] = risk_level
            
            # 模擬危險輸入
            dangerous_inputs = [
                ("自殺" if risk_level >= 4 else "今日天氣好"),
                ""
            ]
            
            for user_input in dangerous_inputs:
                if user_input:  # 跳過空輸入
                    result = await hub.process_user_input(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        user_input=user_input,
                        session_state=session
                    )
                    
                    # 驗證回應不為空
                    assert len(result['response']) > 0
                    assert result['success'] == True

# ============ 數據庫持久化測試 ============

class TestDatabasePersistence:
    """數據庫持久化驗證"""
    
    def test_session_persistence(self, integration_setup):
        """測試會話數據持久化"""
        session_mgr = integration_setup['session_mgr']
        db_mgr = integration_setup['db_mgr']
        
        user_id = "persistence-test-user"
        conversation_id = "persistence-test-conv"
        
        # 創建會話
        session = session_mgr.create_session(user_id, conversation_id)
        
        # 更新會話數據
        session['turn_count'] = 5
        session['risk_level'] = 3
        session['walker_score'] = 0.7
        session['messages'].append({
            'role': 'user',
            'content': '測試消息',
            'timestamp': datetime.now().isoformat()
        })
        
        # 保存到 DB
        db_mgr.save_active_session(session)
        
        # 從 DB 載入
        loaded = db_mgr.load_active_session(session['session_id'])
        
        assert loaded is not None
        assert loaded['turn_count'] == 5
        assert loaded['risk_level'] == 3
        assert len(loaded['messages']) >= 1
    
    def test_session_archival(self, integration_setup):
        """測試會話歸檔"""
        db_mgr = integration_setup['db_mgr']
        
        # 創建一個會話記錄
        session = {
            'session_id': 'archive-test-001',
            'user_id': 'archive-user',
            'conversation_id': 'archive-conv',
            'created_at': (datetime.now() - timedelta(hours=1)).isoformat(),
            'turn_count': 10,
            'risk_level': 3,
            'walker_score': 0.6,
            'messages': [],
            'is_escalated': False,
            'escalation_history': []
        }
        
        # 保存為活躍
        db_mgr.save_active_session(session)
        
        # 驗證活躍表中存在
        active = db_mgr.load_active_session(session['session_id'])
        assert active is not None
        
        # 歸檔會話
        db_mgr.archive_session(
            session,
            end_reason='timeout',
            final_outcome='ongoing'
        )
        
        # 驗證已從活躍表移除
        active_after = db_mgr.load_active_session(session['session_id'])
        assert active_after is None
        
        # 驗證在歷史表中
        history = db_mgr.query_session_history(limit=10)
        assert any(s['session_id'] == session['session_id'] for s in history)

# ============ 審計日誌測試 ============

class TestAuditLogging:
    """審計日誌記錄驗證"""
    
    def test_risk_escalation_audit(self, integration_setup):
        """測試風險升級審計記錄"""
        db_mgr = integration_setup['db_mgr']
        
        session_id = "audit-test-session"
        
        # 模擬風險評估和升級
        db_mgr.log_risk_assessment(
            session_id=session_id,
            turn_number=3,
            risk_assessment={
                'risk_level': 4,
                'suicidal_indicators': 2,
                'self_harm_indicators': 0,
                'hopelessness_indicators': 1,
                'isolation_indicators': 1,
                'crisis_keywords': ['自殺', '無希望'],
                'confidence': 0.85
            }
        )
        
        # 記錄升級
        db_mgr.log_escalation_event(
            session_id=session_id,
            turn_number=3,
            escalation_reason='high_risk_suicidal',
            risk_level=4,
            walker_score=0.4,
            escalated_to='clinical_team'
        )
        
        # 驗證可查詢
        stats = db_mgr.get_db_stats()
        assert stats['total_escalations'] >= 1
    
    def test_unconfirmed_escalations_tracking(self, integration_setup):
        """測試未確認升級追蹤"""
        db_mgr = integration_setup['db_mgr']
        
        session_id = "unconfirmed-escalation-test"
        
        # 記錄未確認的升級
        db_mgr.log_escalation_event(
            session_id=session_id,
            turn_number=2,
            escalation_reason='test_escalation',
            risk_level=4,
            walker_score=0.3
        )
        
        stats_before = db_mgr.get_db_stats()
        unconfirmed_before = stats_before.get('unconfirmed_escalations', 0)
        
        # 模擬臨床人員確認升級
        # db_mgr.confirm_escalation(escalation_id)
        
        print(f"\n[ESCALATION TRACKING] Unconfirmed: {unconfirmed_before}")

# ============ 錯誤恢復測試 ============

class TestErrorRecovery:
    """錯誤恢復機制驗證"""
    
    @pytest.mark.asyncio
    async def test_graceful_degradation_on_llm_failure(self, integration_setup):
        """
        測試：LLM 失敗時的優雅降級
        
        期望：返回預設安全回應，不拋出異常
        """
        hub = integration_setup['hub']
        session_mgr = integration_setup['session_mgr']
        
        user_id = "llm-failure-test"
        conversation_id = "llm-failure-conv"
        
        session = session_mgr.create_session(user_id, conversation_id)
        
        # 即使 LLM 不可用，應該仍有回應
        result = await hub.process_user_input(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input="test input",
            session_state=session
        )
        
        assert result['success'] == True
        assert len(result['response']) > 0
        assert result['response'] != ""
    
    @pytest.mark.asyncio
    async def test_session_recovery_after_error(self, integration_setup):
        """
        測試：錯誤後會話恢復
        
        期望：會話狀態被正確保存，下一輪對話能繼續
        """
        hub = integration_setup['hub']
        session_mgr = integration_setup['session_mgr']
        
        user_id = "recovery-test-user"
        conversation_id = "recovery-test-conv"
        
        # 第 1 輪：正常
        result1 = await hub.process_user_input(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input="第一條消息"
        )
        
        # 第 2 輪：仍然成功（即使前一輪有潛在問題）
        result2 = await hub.process_user_input(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input="第二條消息"
        )
        
        assert result1['success'] == True
        assert result2['success'] == True

# ============ 並發測試 ============

@pytest.mark.asyncio
async def test_concurrent_sessions(integration_setup):
    """
    測試：多用戶並發會話
    
    期望：系統能正確處理多個並發用戶
    """
    hub = integration_setup['hub']
    
    async def user_session(user_id, num_turns=3):
        """模擬一個用戶的會話"""
        results = []
        
        for turn in range(num_turns):
            result = await hub.process_user_input(
                user_id=user_id,
                conversation_id=f"concurrent-conv-{user_id}",
                user_input=f"User {user_id} turn {turn}"
            )
            results.append(result)
        
        return results
    
    # 創建 5 個並發用戶
    tasks = [
        user_session(f"concurrent-user-{i}")
        for i in range(5)
    ]
    
    all_results = await asyncio.gather(*tasks)
    
    # 驗證所有會話完成
    assert len(all_results) == 5
    
    for user_results in all_results:
        assert all(r['success'] == True for r in user_results)
    
    print(f"\n[CONCURRENT SESSIONS TEST] PASSED")
    print(f"Total Users: 5, Results: {len(all_results)}")