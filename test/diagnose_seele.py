# save as: diagnose_seele.py
import subprocess
import socket
import requests
import json

def check_redis():
    """检查 Redis"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex(('127.0.0.1', 6379))
        s.close()
        return result == 0
    except:
        return False

def check_service_health(port, name):
    """检查 LLM 服务"""
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=3)
        return resp.status_code == 200
    except:
        return False

def test_emotion_service():
    """测试 Emotion Service JSON 输出"""
    try:
        payload = {
            "prompt": "测试文本"
        }
        resp = requests.post(
            "http://127.0.0.1:8085/v1/analyze",
            json=payload,
            timeout=5
        )
        data = resp.json()
        # 检查返回的字段
        required = ["valence", "arousal", "dominance", "dominant_emotion"]
        missing = [f for f in required if f not in data]
        return {"status": "ok" if not missing else "warning", "missing_fields": missing}
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    print("=" * 60)
    print("SEELE 系统诊断")
    print("=" * 60)
    
    print(f"\nRedis: {'Connected' if check_redis() else 'Not available'}")
    
    services = {
        8081: "main_llm / Soul (Mistral-Nemo)",
        8082: "revise_llm / Revise (Llama-3.2-3B, REVISE_LLM_URL)",
        8083: "logic_llm / Logic (Distil-NPC-gemma)",
        8084: "memory_llm / embedding (BAAI/bge-m3)",
        8085: "emobloom_llm / emotion (Emobloom-7b)",
    }
    
    print("\nLLM Services:")
    for port, name in services.items():
        status = "🟢 OK" if check_service_health(port, name) else "🔴 Failed"
        print(f"  {name}: {status}")
    
    print("\n⚙️ Emotion Service JSON Test:")
    result = test_emotion_service()
    if result["status"] == "ok":
        print(f"  🟢 Response valid")
    elif result["status"] == "warning":
        print(f"  🟡 Missing fields: {result['missing_fields']}")
    else:
        print(f"  🔴 Error: {result['error']}")
    
    print("\n" + "=" * 60)