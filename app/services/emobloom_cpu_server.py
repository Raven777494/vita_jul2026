# emobloom_cpu_server.py - v2.0 完全修復版

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json
import re
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("emobloom")

app = FastAPI(title="VITA Emobloom CPU Sensor")

model = None

class EmotionRequest(BaseModel):
    text: str

@app.on_event("startup")
async def startup_event():
    """啟動時載入模型"""
    global model
    try:
        from llama_cpp import Llama
        logger.info("[INIT] Loading Emobloom-7b on CPU...")
        model = Llama(
            model_path=r"D:\Desktop\engine7b\models\Emobloom-7b.i1-Q5_K_M.gguf",
            n_gpu_layers=0,
            n_ctx=512,
            n_threads=8,
            verbose=False
        )
        logger.info("[OK] Emobloom loaded successfully.")
    except Exception as e:
        logger.error(f"[FATAL] Failed to load model: {e}")

@app.get("/health")
async def health():
    """健康檢查"""
    if model is None:
        return {"status": "loading"}
    return {"status": "healthy"}

# 【【修復】新增 /v1/models 路由（用於 docker-compose healthcheck）
@app.get("/v1/models")
async def list_models():
    """列出可用模型（Docker healthcheck 用）"""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "object": "list",
        "data": [
            {
                "id": "emobloom",
                "object": "model",
                "owned_by": "vita",
                "permission": []
            }
        ]
    }

@app.post("/v1/analyze")
async def analyze_emotion(req: EmotionRequest):
    """【保留】舊的 /v1/analyze 路由"""
    global model
    
    if not model:
        logger.warning("[WARN] Model not loaded.")
        return {
            "valence": 0.0,
            "arousal": 0.0,
            "dominance": 0.0,
            "dominant_emotion": "neutral"
        }

    prompt = f"""Analyze the emotion of the following text and output ONLY a JSON object containing valence (-1.0 to 1.0), arousal (0.0 to 1.0), dominance (-1.0 to 1.0), and dominant_emotion (string).
Text: "{req.text}"
JSON:"""
    
    try:
        response = model(
            prompt,
            max_tokens=64,
            temperature=0.1,
            stop=["}"]
        )
        
        output = response['choices'][0]['text'].strip()
        if not output.endswith('}'):
            output += "}"
        
        # 【修復】極具強健性的 JSON 解析邏輯
        try:
            # 1. 嘗試標準解析
            json_match = re.search(r'\{.*\}', output, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    # 2. 嘗試處理單引號 (Python dict 格式)
                    import ast
                    data = ast.literal_eval(json_str)
                
                logger.info(f"[ANALYZE] Emotion: {data.get('dominant_emotion')}")
                return data
            else:
                raise ValueError("No JSON block found")
                
        except Exception as e:
            logger.error(f"[ERROR] JSON parse failed: {e}. Raw: {output[:100]}")
            return {
                "valence": 0.0,
                "arousal": 0.5,
                "dominance": 0.0,
                "dominant_emotion": "neutral"
            }
            
    except Exception as e:
        logger.error(f"[ERROR] Inference failed: {e}")
        return {
            "error": str(e),
            "valence": 0.0,
            "arousal": 0.5,
            "dominance": 0.0,
            "dominant_emotion": "neutral"
        }

# 【【修復】新增 /v1/chat/completions 路由（用於 emotion_service.py）
@app.post("/v1/chat/completions")
async def chat_completions(request_data: dict):
    """
    vLLM 相容路由 - 供 emotion_service.py 調用
    """
    global model
    
    if not model:
        logger.warning("[WARN] Model not loaded.")
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"valence": 0.0, "arousal": 0.0, "dominance": 0.0}'
                    }
                }
            ]
        }
    
    try:
        messages = request_data.get('messages', [])
        if not messages:
            raise ValueError("No messages provided")
        
        # 簡化版：只取最後一條用戶消息
        last_message = next(
            (m['content'] for m in reversed(messages) if m.get('role') == 'user'),
            None
        )
        
        if not last_message:
            raise ValueError("No user message found")
        
        # 情緒分析提示
        system_prompt = (
            "You are an emotion analyzer. Respond with ONLY a JSON object "
            "containing 'valence' (-1.0 to 1.0), 'arousal' (0.0 to 1.0), "
            "and 'dominance' (-1.0 to 1.0). Example: "
            '{"valence": 0.5, "arousal": 0.3, "dominance": 0.1}'
        )
        
        full_prompt = f"{system_prompt}\n\nAnalyze: {last_message}\n\nJSON:"
        
        response = model(
            full_prompt,
            max_tokens=64,
            temperature=0.1,
            stop=["}"]
        )
        
        content = response['choices'][0]['text'].strip()
        if not content.endswith('}'):
            content += "}"
        
        # 【修復】極具強健性的 JSON 解析邏輯
        try:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                # 預驗證能否解析 (支援單引號)
                try:
                    json.loads(json_str)
                except json.JSONDecodeError:
                    import ast
                    # 轉換為標準 JSON 格式字串再返回，確保調用端能解析
                    recovered_data = ast.literal_eval(json_str)
                    json_str = json.dumps(recovered_data)
                
                logger.info(f"[CHAT] Generated emotion response")
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json_str
                            }
                        }
                    ]
                }
            else:
                raise ValueError("No JSON block found")
                
        except Exception as e:
            logger.warning(f"[WARN] JSON parse failed: {e}. Raw: {content[:100]}")
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"valence": 0.0, "arousal": 0.5, "dominance": 0.0}'
                        }
                    }
                ]
            }
        
    except Exception as e:
        logger.error(f"[ERROR] Chat completion failed: {e}")
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"valence": 0.0, "arousal": 0.5, "dominance": 0.0}'
                    }
                }
            ]
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8085)