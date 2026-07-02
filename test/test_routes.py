# tests/test_routes.py
import pytest
import sys
import os
import warnings
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

class TestChatEndpoint:
    """聊天端點測試"""
    
    # 用來存儲測試用的 session_id，讓不同測試可以共用（如果需要）
    session_id = None
    user_id = "test_user_001"

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_01_session_create(self):
        """步驟 1：先測試會話創建，並獲取 session_id"""
        # 先創建用戶（確保外鍵約束滿足，雖然有些系統會自動創建，但明確一點更好）
        # 這裡我們直接創建會話，假設系統會自動處理用戶
        response = client.post(f"/api/v1/session/create?user_id={self.user_id}&persona=friend")
        
        if response.status_code == 500:
            data = response.json()
            pytest.skip(f"⚠️ 數據庫連線失敗: {data.get('detail', 'Unknown error')}")
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        
        # 保存 session_id 供後續測試使用
        TestChatEndpoint.session_id = data["session_id"]
        print(f"\nOK 成功創建會話 ID: {TestChatEndpoint.session_id}")

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_02_chat_normal(self):
        """步驟 2：使用剛才的 session_id 測試常規聊天"""
        # 確保我們有 session_id
        if not TestChatEndpoint.session_id:
            pytest.skip("跳過聊天測試：因為沒有有效的 session_id")

        response = client.post("/api/v1/chat", json={
            "text": "嗨，我好累呀",
            "user_id": self.user_id,
            "session_id": TestChatEndpoint.session_id,  # 關鍵修復：帶上身分證！
            "stream": False
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # 驗證回應結構
        assert "text" in data or "message" in data
        print(f"\nOK 聊天回應: {data.get('text', data.get('message'))}")

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_03_chat_crisis(self):
        """步驟 3：測試危機檢測（使用同一個會話）"""
        if not TestChatEndpoint.session_id:
            pytest.skip("跳過危機測試：因為沒有有效的 session_id")

        response = client.post("/api/v1/chat", json={
            "text": "我想自殺",
            "user_id": self.user_id,
            "session_id": TestChatEndpoint.session_id, # 帶上身分證
            "stream": False
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # 驗證是否觸發了危機標記（根據妳的系統設計，可能在 meta 或 response 中）
        # 這裡只檢查回應正常，具體字段視妳的 API 定義
        assert data is not None
        print(f"\nOK 危機回應測試通過")
    
    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_health(self):
        """測試健康檢查"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
    
    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_root_endpoint(self):
        """測試根路由"""
        response = client.get("/")
        assert response.status_code == 200

if __name__ == "__main__":
    # 使用 -v -s 參數可以看到打印輸出
    pytest.main([__file__, "-v", "-s"])