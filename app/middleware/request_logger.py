# app/middleware/request_logger.py

from fastapi import Request
import logging
import time
from app.logger import get_logger

logger = get_logger("vita.access")

async def log_requests_middleware(request: Request, call_next):
    """
    請求日誌與監控中間件
    
    記錄：
    - 請求方法與路徑
    - 處理時間 (Latency)
    - 狀態碼
    - 客戶端 IP
    - Body Size
    """
    start_time = time.time()
    
    # 處理請求
    try:
        response = await call_next(request)
    except Exception as e:
        # 記錄異常並重新拋出，交由 Exception Handler 處理
        duration = (time.time() - start_time)
        logger.error(f"[REQUEST FAILED] {request.method} {request.url.path} - {duration:.4f}s - Error: {e}")
        raise e
        
    duration = (time.time() - start_time)
    
    # 忽略健康檢查的詳細日誌（避免刷屏），除非出錯
    if request.url.path == "/health" and response.status_code == 200:
        return response

    # 敏感資料遮罩
    url_path = str(request.url.path)
    query_params = str(request.query_params)
    
    # Mask sensitive keywords in query params
    sensitive_keys = ['password', 'token', 'key', 'secret', 'auth']
    masked_params = query_params
    masked_flag = ""
    
    for key in sensitive_keys:
        if key in query_params.lower():
            masked_params = "[MASKED_SENSITIVE_DATA]"
            masked_flag = " | Sensitive params masked"
            break
            
    full_path = f"{url_path}?{masked_params}" if masked_params else url_path
    
    # Get content length
    content_length = request.headers.get('content-length', '0')

    log_msg = (
        f"[ACCESS] {request.method} {full_path} | "
        f"Status: {response.status_code} | "
        f"Time: {duration:.4f}s | "
        f"Size: {content_length}b | "
        f"IP: {request.client.host if request.client else 'unknown'}"
        f"{masked_flag}"
    )
    
    if response.status_code >= 400:
        logger.warning(log_msg)
    else:
        logger.info(log_msg)
        
    return response
