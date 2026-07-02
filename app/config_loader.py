# app/config_loader.py
"""統一配置加載器 - 單一信源"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

class LLMServiceLoader:
    """從 llm_services.yml 讀取統一配置"""
    
    _config: Optional[Dict[str, Any]] = None
    _env: Optional[str] = None
    
    @classmethod
    def load(cls, env: str = "development", reload: bool = False) -> Dict[str, Any]:
        """
        加載 LLM 服務配置
        
        Args:
            env: 環境類型 (development/production/docker)
            reload: 強制重新加載
        
        Returns:
            配置字典
        """
        if cls._config and not reload:
            return cls._config
        
        config_path = Path(__file__).parent.parent / "config" / "llm_services.yml"
        
        if not config_path.exists():
            raise FileNotFoundError(f"LLM services config not found: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            cls._config = yaml.safe_load(f)
        
        cls._env = env
        return cls._config
    
    @classmethod
    def get_service_url(cls, service_name: str, env: str = "development") -> str:
        """
        獲取服務 URL
        
        Args:
            service_name: 服務名稱 (main_llm/revise_llm/logic_llm/memory_llm/emobloom_llm)
            env: 環境類型
        
        Returns:
            完整 URL
        """
        config = cls.load(env=env)
        service = config['services'].get(service_name)
        
        if not service:
            raise ValueError(f"Service not found: {service_name}")
        
        port = service['port']
        
        if env == "docker":
            host = service['docker']['hostname']
        else:
            host = config['global']['base_host_local']
        
        return f"http://{host}:{port}"
    
    @classmethod
    def get_all_services(cls, env: str = "development") -> Dict[str, Dict[str, Any]]:
        """獲取所有服務配置"""
        config = cls.load(env=env)
        return config['services']
    
    @classmethod
    def get_service_config(cls, service_name: str) -> Dict[str, Any]:
        """獲取特定服務的完整配置"""
        config = cls.load()
        return config['services'].get(service_name, {})

# 環境偵測
IS_DOCKER = os.path.exists('/.dockerenv')
ENVIRONMENT = "docker" if IS_DOCKER else os.getenv("ENV", "development")