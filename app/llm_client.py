# app/llm_client.py - v10.0.0
"""
統一 LLM 客戶端 - 支持所有 LLM 服務
使用統一的配置系統，自動重試和錯誤處理
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
import aiohttp
from app.config import Config
from app.llm_service_config import LLMServiceConfig, LLMServiceType

logger = logging.getLogger(__name__)

class LLMClient:
    """統一的 LLM 客戶端"""
    
    def __init__(self, service_type: LLMServiceType):
        self.service_type = service_type
        self.config = Config()
        self.service_config = LLMServiceConfig.get_service(service_type.value)
        
        if not self.service_config:
            raise ValueError(f"Unknown service type: {service_type}")
        
        # 根據環境選擇 URL
        self.url = self.config.get_llm_service_url(service_type.value)
        self.timeout = self.config.get_llm_service_timeout(service_type.value)
        self.model_name = self.config.get_llm_service_model(service_type.value)
        
        logger.info(
            f"Initialized LLM Client: {service_type.value} "
            f"(URL: {self.url}, Timeout: {self.timeout}s)"
        )
    
    async def call(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        retry_count: int = 0
    ) -> Optional[str]:
        """調用 LLM 服務"""
        
        if retry_count >= self.config.LLM_MAX_RETRIES:
            logger.error(
                f"LLM {self.service_type.value} failed after "
                f"{self.config.LLM_MAX_RETRIES} retries"
            )
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "prompt": prompt,
                    "temperature": temperature,
                    "top_p": top_p,
                }
                
                if max_tokens:
                    payload["max_tokens"] = max_tokens
                
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                
                async with session.post(
                    f"{self.url}/generate",
                    json=payload,
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get("text") or data.get("result")
                        logger.info(
                            f"LLM {self.service_type.value} call succeeded"
                        )
                        return result
                    else:
                        error_msg = await response.text()
                        logger.warning(
                            f"LLM {self.service_type.value} returned status "
                            f"{response.status}: {error_msg}"
                        )
                        raise Exception(f"HTTP {response.status}: {error_msg}")
        
        except asyncio.TimeoutError:
            logger.warning(
                f"LLM {self.service_type.value} call timed out "
                f"(timeout: {self.timeout}s)"
            )
            if retry_count < self.config.LLM_MAX_RETRIES - 1:
                await asyncio.sleep(self.config.LLM_RETRY_DELAY_SECONDS)
                return await self.call(
                    prompt, max_tokens, temperature, top_p,
                    retry_count + 1
                )
        
        except Exception as e:
            logger.error(
                f"LLM {self.service_type.value} call failed: {str(e)}"
            )
            if retry_count < self.config.LLM_MAX_RETRIES - 1:
                await asyncio.sleep(self.config.LLM_RETRY_DELAY_SECONDS)
                return await self.call(
                    prompt, max_tokens, temperature, top_p,
                    retry_count + 1
                )
        
        return None
    
    async def health_check(self) -> bool:
        """檢查服務健康狀態"""
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(
                    f"{self.url}/health",
                    timeout=timeout
                ) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(
                f"Health check failed for {self.service_type.value}: {str(e)}"
            )
            return False

class LLMClientPool:
    """LLM 客戶端池 - 管理所有服務"""
    
    def __init__(self):
        self.clients: Dict[str, LLMClient] = {}
        self._initialize_clients()
    
    def _initialize_clients(self):
        """初始化所有客戶端"""
        for service_type in LLMServiceType:
            try:
                self.clients[service_type.value] = LLMClient(service_type)
            except Exception as e:
                logger.error(f"Failed to initialize {service_type.value}: {str(e)}")
    
    def get_client(self, service_type: LLMServiceType) -> Optional[LLMClient]:
        """獲取特定服務的客戶端"""
        return self.clients.get(service_type.value)
    
    async def health_check_all(self) -> Dict[str, bool]:
        """檢查所有服務的健康狀態"""
        results = {}
        
        for service_type, client in self.clients.items():
            results[service_type] = await client.health_check()
        
        return results

# 全局客戶端池
llm_client_pool = LLMClientPool()