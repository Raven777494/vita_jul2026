# main.py

import sys
import os

# 添加項目路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.logger import setup_logging
from app.config import Config
from app.services.db import init_db
import logging

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    import uvicorn
    
    # 初始化日誌
    setup_logging()
    
    # 初始化數據庫
    try:
        logger.info("Initializing database schema...")
        init_db()
        logger.info("OK Database schema initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        # 可以選擇繼續或退出
    
    # 啟動 FastAPI
    logger.info(f"Starting Vita 2.0 on {Config.HOST}:{Config.PORT}")
    
    uvicorn.run(
        "app.main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=Config.DEBUG,
        log_level="info"
    )