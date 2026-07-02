# test_emobloom_raw.py
import requests
import json
import time

print("=" * 80)
print("Emobloom 原始输出诊断")
print("=" * 80)

test_prompts = [
    "你是誰",
    "我感到很難過",
    "這是一個很長的句子，用來測試模型在處理更長文本時的情感分析能力。",
]

for prompt in test_prompts:
    print(f"\n【Test】 Prompt: {prompt}")
    print("-" * 80)
    
    try:
        response = requests.post(
            "http://127.0.0.1:65413/v1/analyze",
            json={"prompt": prompt},
            timeout=10
        )
        
        print(f"Status: {response.status_code}")
        print(f"Raw Response:\n{response.text}\n")
        
        try:
            data = response.json()
            print(f"Parsed JSON: {json.dumps(data, indent=2, ensure_ascii=False)}\n")
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}\n")
        
        time.sleep(1)
        
    except requests.Timeout:
        print(f"TIMEOUT after 10 seconds\n")
    except Exception as e:
        print(f"Error: {e}\n")

print("=" * 80)