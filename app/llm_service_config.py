# app/llm_service_config.py - v10.1.0

"""

LLM 服務配置工廠類 - 統一管理所有 LLM 服務

單一信源，支持動態查詢和驗證

"""



import json

from pathlib import Path

from typing import Dict, Optional, List, Tuple

from dataclasses import dataclass

from enum import Enum

import logging



logger = logging.getLogger(__name__)



class LLMServiceType(Enum):

    """LLM 服務類型枚舉"""

    MAIN = "main_llm"

    REVISE = "revise_llm"

    LOGIC = "logic_llm"

    MEMORY = "memory_llm"

    EMOTION = "emobloom_llm"



@dataclass

class LLMServiceInfo:

    """LLM 服務信息"""

    service_id: str

    service_type: LLMServiceType

    display_name: str

    description: str

    port: int

    model_name: str

    model_path: str

    timeout_seconds: float

    docker_hostname: str

    gpu_layers: int

    n_threads: int

    n_ctx: int

    priority: int

    priority_level: str

    service_type_str: str



class LLMServiceConfig:

    """LLM 服務配置管理器 - 單一信源"""



    SEELE_SERVICE_NAME_MAP = {

        'main_llm': 'main_llm',

        'revise_llm': 'revise_llm',

        'logic_llm': 'logic_llm',

        'memory_llm': 'memory_llm',

        'emobloom_llm': 'emobloom_llm',

        # Legacy Seele / env names (deprecated)

        'critic_llm': 'revise_llm',

        'mainlmm': 'main_llm',

        'criticallmm': 'revise_llm',

        'logiclmm': 'logic_llm',

        'memorylmm': 'memory_llm',

        'emobloomplmm': 'emobloom_llm',

    }

    

    # 靜態服務定義

    _SERVICES: Dict[str, LLMServiceInfo] = {}

    

    @classmethod

    def initialize(cls) -> None:

        """初始化服務配置"""

        from app.config import AIServiceRegistry

        

        registry_services = AIServiceRegistry.get_all_services()

        

        cls._SERVICES = {

            'main_llm': LLMServiceInfo(

                service_id='main_llm',

                service_type=LLMServiceType.MAIN,

                display_name=registry_services['main_llm'].display_name,

                description=registry_services['main_llm'].description,

                port=registry_services['main_llm'].port,

                model_name=registry_services['main_llm'].model_name,

                model_path=registry_services['main_llm'].model_path,

                timeout_seconds=registry_services['main_llm'].timeout_seconds,

                docker_hostname=registry_services['main_llm'].docker_hostname,

                gpu_layers=registry_services['main_llm'].gpu_layers,

                n_threads=registry_services['main_llm'].n_threads,

                n_ctx=registry_services['main_llm'].n_ctx,

                priority=registry_services['main_llm'].priority,

                priority_level=registry_services['main_llm'].priority_level,

                service_type_str='llm'

            ),

            'revise_llm': LLMServiceInfo(

                service_id='revise_llm',

                service_type=LLMServiceType.REVISE,

                display_name=registry_services['revise_llm'].display_name,

                description=registry_services['revise_llm'].description,

                port=registry_services['revise_llm'].port,

                model_name=registry_services['revise_llm'].model_name,

                model_path=registry_services['revise_llm'].model_path,

                timeout_seconds=registry_services['revise_llm'].timeout_seconds,

                docker_hostname=registry_services['revise_llm'].docker_hostname,

                gpu_layers=registry_services['revise_llm'].gpu_layers,

                n_threads=registry_services['revise_llm'].n_threads,

                n_ctx=registry_services['revise_llm'].n_ctx,

                priority=registry_services['revise_llm'].priority,

                priority_level=registry_services['revise_llm'].priority_level,

                service_type_str='llm'

            ),

            'logic_llm': LLMServiceInfo(

                service_id='logic_llm',

                service_type=LLMServiceType.LOGIC,

                display_name=registry_services['logic_llm'].display_name,

                description=registry_services['logic_llm'].description,

                port=registry_services['logic_llm'].port,

                model_name=registry_services['logic_llm'].model_name,

                model_path=registry_services['logic_llm'].model_path,

                timeout_seconds=registry_services['logic_llm'].timeout_seconds,

                docker_hostname=registry_services['logic_llm'].docker_hostname,

                gpu_layers=registry_services['logic_llm'].gpu_layers,

                n_threads=registry_services['logic_llm'].n_threads,

                n_ctx=registry_services['logic_llm'].n_ctx,

                priority=registry_services['logic_llm'].priority,

                priority_level=registry_services['logic_llm'].priority_level,

                service_type_str='llm'

            ),

            'memory_llm': LLMServiceInfo(

                service_id='memory_llm',

                service_type=LLMServiceType.MEMORY,

                display_name=registry_services['memory_llm'].display_name,

                description=registry_services['memory_llm'].description,

                port=registry_services['memory_llm'].port,

                model_name=registry_services['memory_llm'].model_name,

                model_path=registry_services['memory_llm'].model_path,

                timeout_seconds=registry_services['memory_llm'].timeout_seconds,

                docker_hostname=registry_services['memory_llm'].docker_hostname,

                gpu_layers=registry_services['memory_llm'].gpu_layers,

                n_threads=registry_services['memory_llm'].n_threads,

                n_ctx=registry_services['memory_llm'].n_ctx,

                priority=registry_services['memory_llm'].priority,

                priority_level=registry_services['memory_llm'].priority_level,

                service_type_str='embedding'

            ),

            'emobloom_llm': LLMServiceInfo(

                service_id='emobloom_llm',

                service_type=LLMServiceType.EMOTION,

                display_name=registry_services['emobloom_llm'].display_name,

                description=registry_services['emobloom_llm'].description,

                port=registry_services['emobloom_llm'].port,

                model_name=registry_services['emobloom_llm'].model_name,

                model_path=registry_services['emobloom_llm'].model_path,

                timeout_seconds=registry_services['emobloom_llm'].timeout_seconds,

                docker_hostname=registry_services['emobloom_llm'].docker_hostname,

                gpu_layers=registry_services['emobloom_llm'].gpu_layers,

                n_threads=registry_services['emobloom_llm'].n_threads,

                n_ctx=registry_services['emobloom_llm'].n_ctx,

                priority=registry_services['emobloom_llm'].priority,

                priority_level=registry_services['emobloom_llm'].priority_level,

                service_type_str='emotion_proxy'

            ),

        }

    

    @classmethod

    def get_service(cls, service_id: str) -> Optional[LLMServiceInfo]:

        """獲取特定服務配置"""

        if not cls._SERVICES:

            cls.initialize()

        mapped = cls.SEELE_SERVICE_NAME_MAP.get(service_id, service_id)

        return cls._SERVICES.get(mapped)

    

    @classmethod

    def get_all_services(cls) -> Dict[str, LLMServiceInfo]:

        """獲取所有服務配置"""

        if not cls._SERVICES:

            cls.initialize()

        return cls._SERVICES.copy()

    

    @classmethod

    def get_service_url(cls, service_id: str, is_docker: bool = False) -> Optional[str]:

        """獲取服務 URL"""

        service = cls.get_service(service_id)

        if not service:

            return None

        

        if is_docker:

            return f"http://{service.docker_hostname}:{service.port}"

        else:

            return f"http://127.0.0.1:{service.port}"

    

    @classmethod

    def get_service_by_priority(cls) -> List[LLMServiceInfo]:

        """按優先級排序返回所有服務"""

        services = cls.get_all_services().values()

        return sorted(services, key=lambda s: s.priority)

    

    @classmethod

    def get_critical_services(cls) -> List[LLMServiceInfo]:

        """獲取所有關鍵優先級服務"""

        services = cls.get_all_services().values()

        return [s for s in services if s.priority_level == 'critical']

    

    @classmethod

    def get_important_services(cls) -> List[LLMServiceInfo]:

        """獲取所有重要優先級服務"""

        services = cls.get_all_services().values()

        return [s for s in services if s.priority_level == 'important']

    

    @classmethod

    def validate(cls) -> Tuple[bool, List[str]]:

        """驗證所有服務配置"""

        if not cls._SERVICES:

            cls.initialize()

        

        errors = []

        ports_seen = set()

        hostnames_seen = set()

        

        for service_id, service in cls._SERVICES.items():

            if not (1024 <= service.port <= 65535):

                errors.append(f"{service_id}: Invalid port {service.port}")

            

            if service.port in ports_seen:

                errors.append(f"{service_id}: Duplicate port {service.port}")

            ports_seen.add(service.port)

            

            if not service.docker_hostname:

                errors.append(f"{service_id}: Missing Docker hostname")

            

            if service.docker_hostname in hostnames_seen:

                errors.append(f"{service_id}: Duplicate hostname {service.docker_hostname}")

            hostnames_seen.add(service.docker_hostname)

            

            if not service.model_path:

                errors.append(f"{service_id}: Missing model_path")

            

            if service.timeout_seconds <= 0:

                errors.append(f"{service_id}: Invalid timeout {service.timeout_seconds}")

        

        return len(errors) == 0, errors



    @classmethod

    def validate_config_json_alignment(

        cls,

        config_json_path: Optional[Path] = None

    ) -> Tuple[bool, List[str]]:

        """驗證 config.json（Seele 部署）與 AIServiceRegistry 的埠號/模型路徑對齊"""

        if not cls._SERVICES:

            cls.initialize()



        project_root = Path(__file__).resolve().parent.parent

        config_path = config_json_path or (project_root / 'config.json')

        errors: List[str] = []



        if not config_path.exists():

            return False, [f"config.json not found: {config_path}"]



        try:

            with open(config_path, 'r', encoding='utf-8') as f:

                payload = json.load(f)

        except Exception as e:

            return False, [f"Failed to read config.json: {e}"]



        for entry in payload.get('services', []):

            seele_name = entry.get('name', '')

            registry_id = cls.SEELE_SERVICE_NAME_MAP.get(seele_name)

            if not registry_id:

                errors.append(f"Unknown Seele service name in config.json: {seele_name}")

                continue



            registry = cls._SERVICES.get(registry_id)

            if not registry:

                errors.append(f"Registry service missing: {registry_id}")

                continue



            if entry.get('port') != registry.port:

                errors.append(

                    f"{seele_name}: port mismatch "

                    f"(config.json={entry.get('port')}, registry={registry.port})"

                )



            if entry.get('model_path') != registry.model_path:

                errors.append(

                    f"{seele_name}: model_path mismatch "

                    f"(config.json={entry.get('model_path')}, registry={registry.model_path})"

                )



            for field in ('gpu_layers', 'n_threads', 'n_ctx'):

                cfg_val = entry.get(field)

                reg_val = getattr(registry, field, None)

                if cfg_val is not None and reg_val is not None and cfg_val != reg_val:

                    errors.append(

                        f"{seele_name}: {field} mismatch "

                        f"(config.json={cfg_val}, registry={reg_val})"

                    )



        try:

            from hardware_profile_loader import validate_services_alignment

            errors.extend(

                validate_services_alignment(

                    payload.get('services', []),

                    source_label='config.json',

                )

            )

        except ImportError:

            pass



        return len(errors) == 0, errors

    

    @classmethod

    def get_health_check_config(cls) -> Dict[str, Dict[str, any]]:

        """獲取所有服務的健康檢查配置"""

        health_config = {}

        

        for service_id, service in cls.get_all_services().items():

            health_config[service_id] = {

                'url': f"http://{service.docker_hostname}:{service.port}/health",

                'timeout_seconds': 10,

                'interval_seconds': 30,

                'retries': 3,

            }

        

        return health_config



# 初始化

LLMServiceConfig.initialize()



# 驗證配置

_valid, _errors = LLMServiceConfig.validate()

if not _valid:

    logger.error("LLM Service Config validation failed:")

    for error in _errors:

        logger.error(f"  - {error}")

else:

    logger.info("LLM Service Config validation passed")



_json_valid, _json_errors = LLMServiceConfig.validate_config_json_alignment()

if not _json_valid:

    logger.error("config.json alignment validation failed:")

    for error in _json_errors:

        logger.error(f"  - {error}")

else:

    logger.info("config.json alignment validation passed")

