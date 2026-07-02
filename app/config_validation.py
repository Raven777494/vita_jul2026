# app/config_validation.py - v10.0.0
"""
配置驗證工具 - 確保系統配置正確性
"""

import sys
import logging
from typing import Dict, List, Tuple
from app.config import Config, AIServiceRegistry
from app.llm_service_config import LLMServiceConfig

logger = logging.getLogger(__name__)

class ConfigValidator:
    """配置驗證器"""
    
    @staticmethod
    def validate_all() -> Tuple[bool, Dict[str, List[str]]]:
        """執行所有驗證"""
        results = {
            'config': [],
            'services': [],
            'urls': [],
            'security': [],
            'database': [],
            'hardware': [],
        }
        
        # 驗證主配置
        config_valid, config_errors = Config.validate()
        results['config'] = config_errors
        
        # 驗證服務註冊表
        services_valid, services_errors = AIServiceRegistry.validate_all()
        results['services'] = services_errors
        
        # 驗證 LLM 服務配置
        llm_valid, llm_errors = LLMServiceConfig.validate()
        results['services'].extend(llm_errors)
        
        # 驗證 URL 格式
        url_errors = ConfigValidator._validate_urls()
        results['urls'] = url_errors
        
        # 驗證安全設置
        security_errors = ConfigValidator._validate_security()
        results['security'] = security_errors
        
        # 驗證數據庫配置
        db_errors = ConfigValidator._validate_database()
        results['database'] = db_errors

        # 驗證硬體配置對齊
        hw_errors = ConfigValidator._validate_hardware_profile()
        results['hardware'] = hw_errors
        
        all_valid = all(len(v) == 0 for v in results.values())
        return all_valid, results
    
    @staticmethod
    def _validate_urls() -> List[str]:
        """驗證所有 URL"""
        errors = []
        config = Config()
        
        urls = [
            ('MAIN_LLM_URL', config.MAIN_LLM_URL),
            ('REVISE_LLM_URL', config.REVISE_LLM_URL),
            ('LOGIC_LLM_URL', config.LOGIC_LLM_URL),
            ('MEMORY_LLM_URL', config.MEMORY_LLM_URL),
            ('EMOBLOOM_LLM_URL', config.EMOBLOOM_LLM_URL),
        ]
        
        for url_name, url_value in urls:
            if not url_value:
                errors.append(f"{url_name} is empty")
            elif not url_value.startswith('http'):
                errors.append(f"{url_name} must start with http: {url_value}")
        
        return errors
    
    @staticmethod
    def _validate_security() -> List[str]:
        """驗證安全設置"""
        errors = []
        config = Config()
        
        if config.IS_PRODUCTION or config.IS_STAGING:
            if not config.JWT_SECRET or len(config.JWT_SECRET) < 32:
                errors.append("JWT_SECRET too short for production")
            
            if not config.API_KEY or len(config.API_KEY) < 32:
                errors.append("API_KEY too short for production")
            
            if not config.DB_PASSWORD:
                errors.append("DB_PASSWORD must be set in production")
            
            if config.DEBUG:
                errors.append("DEBUG should be false in production")
        
        return errors
    
    @staticmethod
    def _validate_database() -> List[str]:
        """驗證數據庫配置"""
        errors = []
        config = Config()
        
        if not config.DB_HOST:
            errors.append("DB_HOST is not set")
        
        if not config.DB_PORT:
            errors.append("DB_PORT is not set")
        
        try:
            int(config.DB_PORT)
        except ValueError:
            errors.append(f"DB_PORT must be an integer: {config.DB_PORT}")
        
        if not config.DATABASE_URL:
            errors.append("DATABASE_URL is not set")
        
        return errors
    
    @staticmethod
    def _validate_hardware_profile() -> List[str]:
        """驗證 config.json / AIServiceRegistry 與 hardware_profile.json 對齊"""
        errors: List[str] = []
        try:
            import json
            from pathlib import Path
            from hardware_profile_loader import (
                load_hardware_profile,
                validate_services_alignment,
                validate_registry_alignment,
            )
        except ImportError as exc:
            return [f"hardware_profile_loader unavailable: {exc}"]

        if not load_hardware_profile():
            return ["hardware_profile.json not found or unreadable"]

        project_root = Path(__file__).resolve().parent.parent
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            errors.extend(
                validate_services_alignment(
                    payload.get("services", []),
                    source_label="config.json",
                )
            )

        registry_items = [
            (sid, cfg.gpu_layers, cfg.n_threads, cfg.n_ctx)
            for sid, cfg in AIServiceRegistry.get_all_services().items()
        ]
        errors.extend(validate_registry_alignment(registry_items))
        return errors
    
    @staticmethod
    def print_report(results: Dict[str, List[str]]) -> None:
        """打印驗證報告"""
        print("\n" + "=" * 80)
        print("VITA 2.0 CONFIGURATION VALIDATION REPORT")
        print("=" * 80 + "\n")
        
        total_errors = sum(len(v) for v in results.values())
        
        if total_errors == 0:
            print("STATUS: PASSED")
            print("\nAll configuration checks passed successfully.")
        else:
            print(f"STATUS: FAILED ({total_errors} errors found)\n")
        
        for section, errors in results.items():
            if errors:
                print(f"[{section.upper()}]")
                for i, error in enumerate(errors, 1):
                    print(f"  {i}. {error}")
                print()
        
        print("=" * 80 + "\n")

def main():
    """主驗證函數"""
    logging.basicConfig(level=logging.INFO)
    
    valid, results = ConfigValidator.validate_all()
    ConfigValidator.print_report(results)
    
    return 0 if valid else 1

if __name__ == '__main__':
    sys.exit(main())