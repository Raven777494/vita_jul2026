# app/startup_checks.py - 修正版 v2.6 (無刪減，修復 HTTP 404 與 401 視為可用)
"""
Vita 應用啟動檢查清單
確保所有關鍵組件都就緒
"""

import logging
from pathlib import Path
from typing import Dict, Tuple, Optional
from sqlalchemy.pool import NullPool

from app.config import config, IS_PRODUCTION, IS_STAGING

logger = logging.getLogger("vita.startup")


class StartupChecker:
    """啟動檢查器 - 完整版"""
    
    def __init__(self):
        self.checks: Dict[str, Tuple[bool, str]] = {}
        self.warning_count = 0
        self.error_count = 0
    
    def check_python_version(self) -> bool:
        """檢查 Python 版本"""
        import sys
        MIN_VERSION = (3, 9)
        
        if sys.version_info >= MIN_VERSION:
            msg = f"Python {sys.version_info.major}.{sys.version_info.minor}"
            self.checks['Python Version'] = (True, msg)
            return True
        else:
            msg = f"Python {MIN_VERSION[0]}.{MIN_VERSION[1]}+ required"
            self.checks['Python Version'] = (False, msg)
            self.error_count += 1
            return False
    
    def check_directories(self) -> bool:
        """檢查必要目錄"""
        required_dirs =[
            config.LOGS_DIR,
            config.DATA_DIR,
            config.CACHE_DIR,
            config.MODELS_DIR,
        ]
        
        all_ok = True
        
        for dir_path in required_dirs:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                self.checks[f'Directory: {dir_path.name}'] = (True, str(dir_path))
            except Exception as e:
                self.checks[f'Directory: {dir_path.name}'] = (False, str(e))
                self.error_count += 1
                all_ok = False
        
        return all_ok
    
    def check_config_attributes(self) -> bool:
        """檢查配置屬性完整性"""
        logger.info("[CONFIG] Verifying configuration attributes...")
        
        required_attrs =[
            'DATABASE_URL',
            'DB_POOL_SIZE',
            'DB_MAX_OVERFLOW',
            'DB_POOL_TIMEOUT',
            'DB_POOL_RECYCLE',
            'JWT_SECRET',
            'ENCRYPT_KEY',
            'API_KEY',
            'LOGS_DIR',
            'DATA_DIR',
            'CACHE_DIR',
            'MODELS_DIR'
        ]
        
        missing_attrs =[]
        
        for attr in required_attrs:
            if not hasattr(config, attr):
                missing_attrs.append(attr)
                logger.warning(f"[CONFIG] Missing attribute: {attr}")
        
        if missing_attrs:
            self.checks['Config Attributes'] = (
                False,
                f"Missing: {', '.join(missing_attrs)}"
            )
            self.error_count += 1
            return False
        
        self.checks['Config Attributes'] = (True, "All required attributes present")
        return True
    
    def check_database(self) -> bool:
        """檢查數據庫配置與連接"""
        logger.info("[DATABASE] Checking database configuration...")
        
        if not hasattr(config, 'DATABASE_URL') or not config.DATABASE_URL:
            self.checks['Database URL'] = (False, "DATABASE_URL not configured")
            self.error_count += 1
            return False
        
        if 'postgresql' not in config.DATABASE_URL.lower():
            self.checks['Database URL'] = (False, "Not PostgreSQL format")
            self.error_count += 1
            return False
        
        masked = self._mask_url(config.DATABASE_URL)
        self.checks['Database URL'] = (True, masked)
        
        pool_config_valid = True
        if config.DB_POOL_SIZE < 1:
            logger.warning("[DATABASE] DB_POOL_SIZE < 1, using default")
            pool_config_valid = False
        if config.DB_POOL_TIMEOUT < 1:
            logger.warning("[DATABASE] DB_POOL_TIMEOUT < 1, using default")
            pool_config_valid = False
        
        if not pool_config_valid:
            self.warning_count += 1
        
        try:
            from sqlalchemy import create_engine, text
            
            test_engine = create_engine(
                config.DATABASE_URL,
                echo=False,
                poolclass=NullPool,
                connect_args={'connect_timeout': config.DB_POOL_TIMEOUT}
            )
            
            with test_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self.checks['Database Connection'] = (True, "Connected successfully")
            logger.info("[DATABASE] Connection test passed")
            return True
        
        except ImportError as e:
            self.checks['Database Connection'] = (False, f"SQLAlchemy import failed: {e}")
            self.error_count += 1
            logger.error(f"[DATABASE] Import error: {e}")
            return False
        
        except Exception as e:
            error_msg = str(e)
            self.checks['Database Connection'] = (False, f"Connection failed: {error_msg}")
            self.error_count += 1
            logger.error(f"[DATABASE] Connection error: {error_msg}")
            return False

    def check_platform_engine(self) -> bool:
        """Verify Docker Postgres Platform extensions (vector, age, pg_cron)."""
        if not getattr(config, "DB_PLATFORM_ENGINE_REQUIRED", False):
            self.checks["Platform Engine"] = (True, "Not required (DB_PLATFORM_ENGINE_REQUIRED=false)")
            return True

        logger.info("[DATABASE] Checking Platform Engine extensions...")
        try:
            from app.services.platform_engine_check import verify_platform_engine_or_skip

            status, report = verify_platform_engine_or_skip(require_age_graph=True)
            detail = "; ".join(report.checked[:3]) if report.checked else "No details"
            if status == "PASS":
                self.checks["Platform Engine"] = (True, detail)
                logger.info("[DATABASE] Platform Engine extensions verified")
                return True
            if status == "SKIP":
                self.checks["Platform Engine"] = (False, "; ".join(report.issues) or "Database unreachable")
                self.warning_count += 1
                logger.warning("[DATABASE] Platform Engine check skipped (DB unreachable)")
                return False

            self.checks["Platform Engine"] = (False, "; ".join(report.issues))
            self.error_count += 1
            logger.error(f"[DATABASE] Platform Engine check failed: {'; '.join(report.issues)}")
            return False
        except Exception as exc:
            self.checks["Platform Engine"] = (False, str(exc))
            self.warning_count += 1
            logger.warning(f"[DATABASE] Platform Engine check error: {exc}")
            return False
    
    def check_config_security(self) -> bool:
        """檢查配置安全性"""
        logger.info("[SECURITY] Checking configuration security...")
        
        if not (IS_PRODUCTION or IS_STAGING):
            self.checks['Config Security'] = (True, "Dev mode - relaxed checks")
            logger.info("[SECURITY] Dev mode, relaxed security checks")
            return True
        
        errors =[]
        
        if not hasattr(config, 'JWT_SECRET') or not config.JWT_SECRET:
            errors.append("JWT_SECRET not set")
        elif len(config.JWT_SECRET) < 32:
            errors.append("JWT_SECRET too short (<32 chars)")
        
        if not hasattr(config, 'ENCRYPT_KEY') or not config.ENCRYPT_KEY:
            errors.append("ENCRYPT_KEY not set")
        elif len(config.ENCRYPT_KEY) < 32:
            errors.append("ENCRYPT_KEY too short (<32 chars)")
        
        if hasattr(config, 'API_KEY') and config.API_KEY.startswith("dev_"):
            errors.append("API_KEY uses development value")
        
        if errors:
            self.checks['Config Security'] = (False, "; ".join(errors))
            self.error_count += 1
            logger.warning(f"[SECURITY] Issues found: {'; '.join(errors)}")
            return False
        
        self.checks['Config Security'] = (True, "All secrets valid")
        logger.info("[SECURITY] All security checks passed")
        return True
    
    def check_redis(self) -> bool:
        """檢查 Redis 連接"""
        logger.info("[REDIS] Checking Redis connection...")
        
        try:
            import redis
            
            redis_client = redis.from_url(
                config.REDIS_URL,
                socket_timeout=config.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=config.REDIS_SOCKET_CONNECT_TIMEOUT,
                decode_responses=True
            )
            
            redis_client.ping()
            self.checks['Redis Connection'] = (True, "Connected successfully")
            logger.info("[REDIS] Connection test passed")
            return True
        
        except ImportError:
            self.checks['Redis Connection'] = (False, "redis-py not installed")
            self.warning_count += 1
            logger.warning("[REDIS] redis-py not installed, caching disabled")
            return False
        
        except Exception as e:
            self.checks['Redis Connection'] = (False, str(e))
            self.warning_count += 1
            logger.warning(f"[REDIS] Connection failed: {str(e)}")
            return False
    
    def check_llm_services(self) -> Dict[str, bool]:
        """檢查 LLM 服務"""
        logger.info("[LLM] Checking LLM services...")

        from app.utils.llm_health import probe_llm_service

        services = config.get_startup_llm_services()

        available_services = {}
        available_count = 0
        api_key = getattr(config, 'API_KEY', None)

        for name, url in services.items():
            is_available, detail = probe_llm_service(url, timeout=3.0, api_key=api_key)
            available_services[name] = is_available

            if is_available:
                self.checks[f'LLM: {name}'] = (True, detail)
                available_count += 1
                logger.info(f"[LLM] {name}: Available ({detail})")
            else:
                self.checks[f'LLM: {name}'] = (False, detail)
                self.warning_count += 1
                logger.warning(f"[LLM] {name}: {detail}")

        logger.info(f"[LLM] Summary: {available_count}/{len(services)} services available")
        return available_services
    
    def _mask_url(self, url: str) -> str:
        """遮蔽 URL 中的密碼"""
        if '://' not in url:
            return url[:60] + "..." if len(url) > 60 else url
        parts = url.split('://')
        protocol = parts[0]
        rest = parts[1]
        if '@' in rest:
            credentials, host = rest.rsplit('@', 1)
            if ':' in credentials:
                user = credentials.split(':')[0]
                credentials = f"{user}:****"
            rest = f"{credentials}@{host}"
        masked = f"{protocol}://{rest}"
        if len(masked) > 60:
            masked = masked[:60] + "..."
        return masked
    
    def run_all(self) -> bool:
        logger.info("\n" + "="*70)
        logger.info("Running startup checks...")
        logger.info("="*70)
        
        self.check_python_version()
        self.check_directories()
        self.check_config_attributes()
        self.check_database()
        self.check_platform_engine()
        self.check_config_security()
        self.check_redis()
        llm_services = self.check_llm_services()
        
        logger.info("\nStartup Checks Results:")
        logger.info("-"*70)
        
        critical_failed = False
        
        for check_name, (status, message) in self.checks.items():
            status_str = "OK" if status else "FAIL"
            logger.info(f"  [{status_str}] {check_name}: {message}")
            if not status:
                if any(keyword in check_name for keyword in['Database', 'Config Security', 'Config Attributes', 'Python']):
                    if IS_PRODUCTION:
                        critical_failed = True
        
        logger.info("-"*70)
        
        available_llm_count = sum(1 for v in llm_services.values() if v)
        logger.info(f"\nSummary:")
        logger.info(f"  Errors: {self.error_count}")
        logger.info(f"  Warnings: {self.warning_count}")
        logger.info(f"  LLM Services: {available_llm_count}/{len(llm_services)} available")
        
        if available_llm_count == 0:
            logger.warning("[!] No LLM services available - chat will fail")
        else:
            logger.info(f"[OK] {available_llm_count} LLM service(s) available")
        
        logger.info("="*70)
        
        if critical_failed:
            logger.critical("[ERROR] Critical checks failed in production mode!")
            return False
        if self.error_count > 0:
            logger.error("[ERROR] Configuration validation failed")
            return False
        
        logger.info("[OK] All critical checks passed\n")
        return True


def run_startup_checks() -> bool:
    checker = StartupChecker()
    return checker.run_all()