# # app/services/memory_store.py

import redis
import json
import time
from typing import List, Dict
from app.config import Config

class MemoryStore:
    def __init__(self):
        try:
            # decode_responses=True 確保拿出來是字串不是 bytes
            self.r = redis.from_url(Config.REDIS_URL, decode_responses=True)
            self.r.ping()
            print("OK Redis Memory Store Connected.")
        except redis.exceptions.ConnectionError as e:
            print(f"X Redis Connection Error: {e}. Falling back to No-Op memory.")
            self.r = None

    def _get_key(self, user_id: str) -> str:
        return f"chat_history:{user_id}"

    def push_context(self, user_id: str, role: str, content: str):
        """將訊息推入歷史 (尾部追加，保持時間順序)"""
        if not self.r: return

        key = self._get_key(user_id)
        message = {
            "role": role,
            "content": content,
            "timestamp": int(time.time())
        }
        # 使用 rpush (Right Push) 保持 [舊消息 ... 新消息]
        self.r.rpush(key, json.dumps(message, ensure_ascii=False))
        
        # 只保留最近 50 條
        self.r.ltrim(key, -50, -1) 
        self.r.expire(key, Config.REDIS_TTL_SECONDS)

    def get_context(self, user_id: str, limit: int = 10) -> List[Dict]:
        """獲取最近 limit 條對話"""
        if not self.r: return []

        key = self._get_key(user_id)
        # 拿取最後 limit 條
        raw_list = self.r.lrange(key, -limit, -1)
        
        history = []
        for item in raw_list:
            try:
                msg = json.loads(item)
                history.append({
                    "role": msg.get("role"),
                    "content": msg.get("content")
                })
            except:
                continue
        return history