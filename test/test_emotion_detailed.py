# save as: test_emotion_detailed.py
import requests
import json
import time

def test_emotion_with_various_inputs():
    """用多种输入测试 Emotion Service，捕捉格式问题"""
    
    test_cases = [
        ("你是誰", "Chinese query - simple"),
        ("我感到很難過", "Chinese - emotional"),
        ("這是一個很長的句子，用來測試模型在處理更長文本時的情感分析能力。", "Long Chinese text"),
        ("I am sad", "English"),
        ("", "Empty"),
        ("😢😢😢", "Emoji only"),
        ("你好你好你好" * 10, "Repetitive text"),
    ]
    
    for text, description in test_cases:
        print(f"\n📝 Testing: {description}")
        print(f"   Input: {text[:50]}")
        
        try:
            resp = requests.post(
                "http://127.0.0.1:8085/v1/analyze",
                json={"prompt": text},
                timeout=10
            )
            
            print(f"   Status: {resp.status_code}")
            
            # 嘗試解析
            try:
                data = resp.json()
                print(f"   ✅ Valid JSON")
                print(f"   Fields: {list(data.keys())}")
                if "valence" in data:
                    print(f"   Valence: {data['valence']}")
            except json.JSONDecodeError as e:
                print(f"   ❌ JSON ERROR: {e}")
                print(f"   Raw response (first 200 chars): {resp.text[:200]}")
                
        except requests.Timeout:
            print(f"   ⏱️ TIMEOUT")
        except Exception as e:
            print(f"   🔴 ERROR: {e}")
        
        time.sleep(0.5)

def capture_raw_emotion_output():
    """直接查看原始 Emotion Service 进程输出"""
    import subprocess
    
    print("\n" + "="*60)
    print("获取 Emotion Service 进程的最近输出...")
    print("="*60)
    
    try:
        # Windows: 使用 tasklist 和 wmic
        result = subprocess.run(
            ["tasklist", "/v", "/fo", "csv"],
            capture_output=True,
            text=True
        )
        
        lines = result.stdout.split('\n')
        for line in lines:
            if 'emotion' in line.lower() or 'emobloom' in line.lower():
                print(f"Found process: {line}")
    except Exception as e:
        print(f"Could not capture process info: {e}")

if __name__ == "__main__":
    print("="*60)
    print("EMOTION SERVICE 深度诊断")
    print("="*60)
    
    test_emotion_with_various_inputs()
    
    print("\n" + "="*60)
    print("诊断完成")
    print("="*60)