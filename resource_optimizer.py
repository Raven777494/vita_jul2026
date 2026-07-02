# resource_optimizer.py - 媽媽的資源優化工具
# 日後開發增加LLM用

"""
優化策略：
1. 動態 GPU 層分配（不同服務用不同層數）
2. Redis 快取重覆回應
3. 定期清理記憶
4. 並行度控制
"""

import json
from pathlib import Path
from typing import Dict, Optional
from hardware_profile_loader import (
    load_hardware_profile,
    merge_config_services,
    vram_reserve_mb,
    estimate_gpu_memory_mb,
)


def load_hardware_profile_from_disk() -> Optional[Dict]:
    """Backward-compatible alias."""
    return load_hardware_profile()


class ResourceOptimizer:
    """資源優化器"""
    
    @staticmethod
    def get_optimized_config() -> Dict:
        """獲取優化後的配置（對齊 hardware_profile.json）"""
        profile = load_hardware_profile()
        svc = (profile or {}).get('services', {})

        def _layers(name: str, default: int = 0) -> int:
            return int(svc.get(name, {}).get('gpu_layers', default))

        def _threads(name: str, default: int = 4) -> int:
            return int(svc.get(name, {}).get('n_threads', default))

        return {
            "hardware": profile or {},
            "main_llm": {
                "n_gpu_layers": _layers("main_llm", 40),
                "n_threads": _threads("main_llm", 8),
                "n_ctx": 2048,
            },
            "revise_llm": {
                "n_gpu_layers": _layers("revise_llm", 0),
                "n_threads": _threads("revise_llm", 6),
                "n_ctx": 1024,
            },
            "logic_llm": {
                "n_gpu_layers": _layers("logic_llm", 0),
                "n_threads": _threads("logic_llm", 4),
                "n_ctx": 2048,
            },
            "memory_llm": {
                "n_gpu_layers": _layers("memory_llm", 0),
                "n_threads": _threads("memory_llm", 4),
                "n_ctx": 1024,
            },
            "emobloom_llm": {
                "n_gpu_layers": _layers("emobloom_llm", 0),
                "n_threads": _threads("emobloom_llm", 6),
                "n_ctx": 1024,
            },
            "redis": {
                "max_memory": "8gb",
                "maxmemory-policy": "allkeys-lru",
                "save": "300 10",
            },
            "db": {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_recycle": 3600,
            },
            "concurrency": {
                "max_concurrent_requests": 4,
                "queue_size": 20,
            },
        }
    
    @staticmethod
    def generate_docker_compose_optimized() -> str:
        """Return the project docker-compose.yml (single source of truth for credentials)."""
        compose_path = Path(__file__).resolve().parent / "docker-compose.yml"
        if compose_path.is_file():
            return compose_path.read_text(encoding="utf-8")
        return "# docker-compose.yml not found\n"

# 用法
if __name__ == "__main__":
    optimizer = ResourceOptimizer()
    config = optimizer.get_optimized_config()
    print(json.dumps(config, indent=2))