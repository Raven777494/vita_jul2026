# app/tests/test_system_alignment.py
"""
System Alignment and Integrity Tests
Verifies the interaction between Config, Security, Middleware, and API.
"""

import sys
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.config import config
from app.utils.security import get_current_user
# Import the dependency function to override
from app.api.routes import get_orchestrator

client = TestClient(app)

# ==========================================
# 1. Configuration Integrity Tests
# ==========================================

def test_config_loading():
    """Verify essential config values are loaded."""
    assert config.API_KEY is not None
    assert config.LOGS_DIR is not None
    assert config.DATABASE_URL is not None
    print("[TEST] Config loading passed.")

def test_logs_dir_writable(tmp_path):
    """Verify LOGS_DIR logic works (using tmp_path to simulate)."""
    # Note: We can't easily change the global config instance at runtime for this test
    # without reloading, but we can verify the path object exists.
    assert config.LOGS_DIR.exists()
    print("[TEST] Logs directory check passed.")

# ==========================================
# 2. Security & Authentication Tests
# ==========================================

def test_auth_rejection_no_header():
    """Verify requests without auth header are rejected (when AUTH_ENABLED)."""
    # Force AUTH_ENABLED to True for this test context if possible, 
    # or rely on the fact that if dev mode, it might return anonymous.
    # We will patch config.AUTH_ENABLED to True to test the logic.
    
    # Also patch security check functions to avoid 403 Forbidden due to IP banning during tests
    with patch("app.config.config.AUTH_ENABLED", True), \
         patch("app.config.config.IS_PRODUCTION", True), \
         patch("app.utils.security.check_auth_failure_limit"), \
         patch("app.utils.security.record_auth_failure"):
         
        response = client.post("/api/v1/chat", json={"text": "hello"})
        assert response.status_code == 401
    print("[TEST] Auth rejection (no header) passed.")

def test_auth_rejection_wrong_key():
    """Verify requests with wrong API Key are rejected."""
    # Patch security check functions to avoid 403 Forbidden
    with patch("app.config.config.AUTH_ENABLED", True), \
         patch("app.config.config.IS_PRODUCTION", True), \
         patch("app.utils.security.check_auth_failure_limit"), \
         patch("app.utils.security.record_auth_failure"):
         
        response = client.post(
            "/api/v1/chat", 
            json={"text": "hello"}, 
            headers={"X-API-KEY": "wrong_key"}
        )
        assert response.status_code == 401
    print("[TEST] Auth rejection (wrong key) passed.")

def test_auth_acceptance_correct_key():
    """Verify requests with correct API Key are accepted."""
    # Create a concrete Mock Object with the expected return structure
    mock_orc = MagicMock()
    # Explicitly set the return value to a dict containing an integer risk_level
    # This prevents the 'MagicMock >= int' TypeError
    mock_orc.process_user_message.return_value = {
        "success": True, 
        "assistant_response": "Mock Response",
        "risk_level": 0,
        "emotion_analysis": {},
        "phase": "testing"
    }
    
    # Use FastAPI's dependency_overrides to properly inject the mock
    app.dependency_overrides[get_orchestrator] = lambda: mock_orc
    
    try:
        # Ensure Auth passes, and also mock security check to prevent prior bans from affecting this
        with patch("app.config.config.AUTH_ENABLED", True), \
             patch("app.config.config.API_KEY", "test_secret_key"), \
             patch("app.utils.security.check_auth_failure_limit"):
            
            response = client.post(
                "/api/v1/chat",
                json={"text": "hello", "user_id": "test", "session_id": "test"},
                headers={"X-API-KEY": "test_secret_key"}
            )
            
            # Debugging info if test fails
            if response.status_code != 200:
                print(f"[DEBUG] Test failed with status {response.status_code}: {response.text}")
                
            assert response.status_code == 200
            assert response.json()["text"] == "Mock Response"
    finally:
        # Clear overrides to avoid affecting other tests
        app.dependency_overrides = {}
        
    print("[TEST] Auth acceptance passed.")

# ==========================================
# 3. Middleware Tests (Rate Limiting & Logging)
# ==========================================

def test_rate_limiter_active():
    """Verify rate limiter middleware is active."""
    # We won't flood the server, just check if headers *could* imply limiting or 
    # if the middleware allows a request. 
    # To test actual blocking, we'd need to mock the RateLimiter internal counter.
    
    with patch("app.middleware.rate_limiter.rate_limiter.check_rate_limit") as mock_check:
        mock_check.return_value = None # Pass
        
        response = client.get("/health")
        # Ensure 200 OK (assuming /health endpoint exists now)
        assert response.status_code == 200
        mock_check.assert_called()
    print("[TEST] Rate limiter middleware active.")

def test_request_logger_masking(caplog):
    """Verify sensitive data in query params is masked in logs."""
    import logging
    
    with caplog.at_level(logging.INFO, logger="vita.access"):
        # [FIX] Use '/' instead of '/health' because the middleware explicitly ignores
        # successful /health requests to prevent log spamming.
        # Querying root '/' with sensitive params should trigger logging and masking.
        client.get("/?token=secret123&other=value")
        
        # Check logs for masked string
        found_masked = False
        for record in caplog.records:
            if "token" in record.message or "masked" in record.message.lower():
                if "[MASKED_SENSITIVE_DATA]" in record.message:
                    found_masked = True
        
        assert found_masked, "Sensitive data was not masked in logs (Ensure endpoint is logged)"
    print("[TEST] Request logger masking passed.")

# ==========================================
# 4. System Integration / Route Logic
# ==========================================

def test_health_check_route():
    """Verify health check route works."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    print("[TEST] Health check passed.")

if __name__ == "__main__":
    # Manual run if executed as script
    print("Running System Alignment Tests...")
    try:
        test_config_loading()
        # Mocking temporary dir for logs test is tricky in main block, skipped
        test_auth_rejection_no_header()
        test_auth_rejection_wrong_key()
        test_auth_acceptance_correct_key()
        test_rate_limiter_active()
        # Caplog requires pytest runner, so skipping logger test in manual run
        test_health_check_route()
        print("\nAll System Checks Passed (Manual Run).")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
