import requests
import os
from typing import List, Tuple
import urllib.parse


ENV_RERANKER_BASE_URL = os.getenv("RERANKER_BASE_URL")
ENV_RERANKER_MODEL = os.getenv("RERANKER_MODEL")
ENV_RERANKER_KEY = os.getenv("RERANKER_KEY", "default_key")

class Reranker:
    def __init__(self, base_url: str = ENV_RERANKER_BASE_URL, model: str = ENV_RERANKER_MODEL, key: str = ENV_RERANKER_KEY):
        self.base_url = base_url        
        self.rerank_url = urllib.parse.urljoin(self.base_url, "v1/rerank")
        self.model = model
        self.key = key
        self.client = requests.Session()
        self.client.headers.update({
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

        # # Check if server is up upon initialization
        # health_url = urllib.parse.urljoin(self.base_url, "health")
        # try:
        #     response = requests.get(health_url, timeout=5)
        #     if response.status_code != 200:
        #         raise RuntimeError(f"Reranker server is not available at {health_url}: {response.status_code}")
        # except requests.RequestException as e:
        #     raise RuntimeError(f"Reranker server is not available at {health_url}: {e}")

    def _rerank(self, query: str, candidates: List[str], batch_idx: int) -> List[Tuple[int, float]]:
        response = self.client.post(
            self.rerank_url,
            json={
                "model": self.model,
                "query": query,
                "documents": candidates
            }
        )
        try:
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"Rerank request failed: {e}")

        data = response.json()
        if "results" not in data:
            raise ValueError(f"Unexpected rerank response format: {data}")

        return [(batch_idx + c['index'], c['relevance_score']) for c in data["results"]]

    def rerank(self, query: str, candidates: List[str], batch_size: int = 128) -> List[Tuple[int, float]]:
        results = []
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i+batch_size]
            results.extend(self._rerank(query, batch, i))
        # keep the original order of the candidates
        return sorted(results, key=lambda x: x[0])
    
    def count_tokens(self, text: str) -> Tuple[int, int]:
        response = self.client.post(urllib.parse.urljoin(self.base_url, "tokenize"), json={
            "model": self.model,
            "prompt": text
        })
        try:
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"Token count request failed: {e}")
        data = response.json()
        if "count" not in data or "max_model_len" not in data:
            raise ValueError(f"Unexpected token count response format: {data}")
        return data["count"], data["max_model_len"]

    def __call__(self, query: str, candidates: List[str], batch_size: int = 128) -> List[Tuple[int, float]]:
        return self.rerank(query, candidates, batch_size)

