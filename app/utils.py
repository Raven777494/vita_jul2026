# app/utils.py 修正為 FastAPI 寫法
import time
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from app.config import config

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

async def require_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != config.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized or invalid API Key"
        )
    return api_key

class Stopwatch:
    def __init__(self):
        self.t0 = time.time()

    def ms(self) -> int:
        return int((time.time() - self.t0) * 1000)