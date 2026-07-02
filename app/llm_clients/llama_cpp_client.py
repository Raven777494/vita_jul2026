import requests
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

class LlamaCppClient:
    def __init__(self, base_url: str, default_decode: Optional[Dict[str, Any]] = None, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.default_decode = default_decode or {}
        self.timeout = timeout

    @retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(0.5, 2))
    def chat(self, prompt: str, decode: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": (decode or self.default_decode).get("temperature", 0.6),
            "top_p": (decode or self.default_decode).get("top_p", 0.9),
            "top_k": (decode or self.default_decode).get("top_k", 40),
            "repeat_penalty": (decode or self.default_decode).get("repeat_penalty", 1.1),
            "max_tokens": (decode or self.default_decode).get("max_tokens", 256),
            "stream": False,
        }
        r = requests.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        # llama.cpp server v1 compatibility
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
        # fallback older schema
        return data.get("content", "")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential_jitter(0.5, 2))
    def embed(self, input_texts):
        url = f"{self.base_url}/v1/embeddings"
        payload = {"input": input_texts}
        r = requests.post(url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return [d["embedding"] for d in data.get("data", [])]