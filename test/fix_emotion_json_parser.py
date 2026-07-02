# save as: fix_emotion_json_parser.py
"""
增强的 Emotion Service JSON 解析器
这是对 seele_v8_5.py 中 _build_emotion_cmd 的改进
"""

import json
import re
import ast

def parse_emotion_output_robust(text_output: str) -> dict:
    """
    鲁棒的情感输出解析器
    处理多种格式异常
    """
    
    print(f"[PARSE] Input: {text_output[:100]}")
    
    # Step 1: 尝试直接 JSON 解析
    try:
        res = json.loads(text_output)
        print("[PARSE] ✅ Direct JSON parsing succeeded")
        return res
    except json.JSONDecodeError as e:
        print(f"[PARSE] ❌ Direct JSON failed: {e}")
    
    # Step 2: 清理和修复
    cleaned = text_output.strip()
    
    # 移除前后的非 JSON 字符
    if not cleaned.startswith('{'):
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            cleaned = match.group()
            print(f"[PARSE] 🔧 Extracted JSON from text")
    
    # Step 3: 修复数字键（Python 字典格式）
    # 问题: {-1.0: 0.0, 0.0: 0.5, ...}
    # 解决: {"-1.0": 0.0, "0.0": 0.5, ...}
    try:
        # 匹配 "浮点数:" 或 "整数:" 的模式
        fixed = re.sub(
            r'(-?\d+\.?\d*)\s*:',  # 匹配 -1.0: 或 0: 的格式
            r'"\1":',               # 替换为 "-1.0": 或 "0":
            cleaned
        )
        print(f"[PARSE] 🔧 Fixed numeric keys")
        res = json.loads(fixed)
        print("[PARSE] ✅ JSON parsing succeeded after key fixing")
        return res
    except json.JSONDecodeError as e:
        print(f"[PARSE] ❌ After key fixing still failed: {e}")
    
    # Step 4: 使用 ast.literal_eval（处理 Python 字典）
    try:
        res = ast.literal_eval(cleaned)
        print("[PARSE] ✅ Successfully parsed as Python literal")
        
        # 如果结果是字典，转换为标准格式
        if isinstance(res, dict):
            return res
    except (ValueError, SyntaxError) as e:
        print(f"[PARSE] ❌ ast.literal_eval failed: {e}")
    
    # Step 5: 提取数值（最后手段）
    print("[PARSE] 🚨 Using emergency fallback - extracting numbers")
    
    numbers = re.findall(r'-?\d+\.?\d*', cleaned)
    if len(numbers) >= 3:
        return {
            "valence": float(numbers[0]),
            "arousal": float(numbers[1]) if len(numbers) > 1 else 0.5,
            "dominance": float(numbers[2]) if len(numbers) > 2 else 0.0,
            "dominant_emotion": "unknown",
            "confidence": 0.3  # Low confidence for fallback
        }
    
    # Step 6: 终极 fallback
    print("[PARSE] 🔴 All parsing failed, returning default")
    return {
        "valence": 0.0,
        "arousal": 0.5,
        "dominance": 0.0,
        "dominant_emotion": "neutral",
        "confidence": 0.0
    }


# 测试用例
test_cases = [
    # 正常 JSON
    '{"valence": 0.5, "arousal": 0.3, "dominance": 0.2, "dominant_emotion": "happy"}',
    
    # Python 字典格式（数字键）
    '{-1.0: 0.0, 0.0: 0.0, -1.0: 0.0, ""}',
    
    # 单引号格式
    "{'valence': 0.5, 'arousal': 0.3}",
    
    # 混乱的格式
    'valence: 0.5, arousal: 0.3, dominance: 0.2',
]

if __name__ == "__main__":
    print("="*60)
    print("EMOTION JSON 解析器测试")
    print("="*60)
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n【Test {i}】")
        result = parse_emotion_output_robust(test)
        print(f"Result: {result}\n")