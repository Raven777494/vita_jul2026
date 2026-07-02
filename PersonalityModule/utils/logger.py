# D:\DESKTOP\ENGINE7B\PersonalityModule\utils\logger.py

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

class PersonalityLogger:
    """
    統一日誌系統，支持多檔案輸出
    - personality_YYYY-MM-DD.log：主日誌（所有級別）
    - eternal_echo_YYYY-MM-DD.log：永迴軌特化日誌
    - heretic_YYYY-MM-DD.log：Heretic矯正日誌
    - session_YYYY-MM-DD_[session_id].log：單會話日誌
    """
    
    _loggers = {}
    _log_dir = None
    
    @classmethod
    def initialize(cls, log_base_dir: str = None) -> None:
        """初始化日誌系統，設定基礎目錄"""
        if log_base_dir is None:
            log_base_dir = Path("D:/DESKTOP/ENGINE7B/logs/PersonalityModule")
        
        cls._log_dir = Path(log_base_dir)
        cls._log_dir.mkdir(parents=True, exist_ok=True)
        
    @classmethod
    def get_logger(cls, 
                   name: str,
                   log_file: str = None,
                   file_level: int = logging.DEBUG,
                   console_level: int = logging.INFO,
                   session_id: str = None) -> logging.Logger:
        """
        獲取或創建logger
        
        Args:
            name: logger名稱（如'personality', 'eternal_echo', 'heretic'）
            log_file: 指定日誌檔案名（不含.log），若None則用name生成
            file_level: 文件記錄級別，默認DEBUG
            console_level: 控制台記錄級別，默認INFO
            session_id: 會話ID（用於session日誌）
            
        Returns:
            配置好的logger實例
        """
        if cls._log_dir is None:
            cls.initialize()
        
        # 確定logger key
        logger_key = f"{name}_{session_id}" if session_id else name
        
        # 若已存在則返回
        if logger_key in cls._loggers:
            return cls._loggers[logger_key]
        
        # 創建新logger
        logger = logging.getLogger(logger_key)
        logger.setLevel(logging.DEBUG)  # logger自身接收所有級別
        
        # 清空現有handler（避免重複）
        logger.handlers.clear()
        
        # 1. FileHandler：文件記錄所有細節
        if log_file is None:
            if session_id:
                log_file = f"session_{datetime.now().strftime('%Y-%m-%d')}_{session_id}"
            else:
                log_file = f"{name}_{datetime.now().strftime('%Y-%m-%d')}"
        
        log_path = cls._log_dir / f"{log_file}.log"
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(file_level)
        
        # 2. StreamHandler：控制台輸出（級別可控）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        
        # 3. Formatter：統一格式
        detailed_formatter = logging.Formatter(
            fmt='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_formatter = logging.Formatter(
            fmt='[%(levelname)s] %(message)s'
        )
        
        file_handler.setFormatter(detailed_formatter)
        console_handler.setFormatter(console_formatter)
        
        # 添加handler到logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        # 緩存
        cls._loggers[logger_key] = logger
        
        return logger
    
    @classmethod
    def get_personality_logger(cls) -> logging.Logger:
        """獲取主日誌"""
        return cls.get_logger('personality', file_level=logging.DEBUG, console_level=logging.INFO)
    
    @classmethod
    def get_eternal_echo_logger(cls) -> logging.Logger:
        """獲取永迴軌日誌"""
        return cls.get_logger('eternal_echo', file_level=logging.DEBUG, console_level=logging.INFO)
    
    @classmethod
    def get_heretic_logger(cls) -> logging.Logger:
        """獲取Heretic日誌"""
        return cls.get_logger('heretic', file_level=logging.DEBUG, console_level=logging.INFO)
    
    @classmethod
    def get_session_logger(cls, session_id: str) -> logging.Logger:
        """獲取單會話日誌"""
        return cls.get_logger(
            'session',
            file_level=logging.DEBUG,
            console_level=logging.INFO,
            session_id=session_id
        )


# 便利函數
def get_logger(name: str = 'personality', session_id: str = None) -> logging.Logger:
    """簡化API"""
    if session_id:
        return PersonalityLogger.get_session_logger(session_id)
    elif name == 'personality':
        return PersonalityLogger.get_personality_logger()
    elif name == 'eternal_echo':
        return PersonalityLogger.get_eternal_echo_logger()
    elif name == 'heretic':
        return PersonalityLogger.get_heretic_logger()
    else:
        return PersonalityLogger.get_logger(name)