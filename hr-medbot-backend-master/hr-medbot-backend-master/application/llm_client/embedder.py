from typing import List
import openai
import os
import urllib.parse
import requests
from typing import Tuple

ENV_EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL")
ENV_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
ENV_EMBEDDING_KEY = os.getenv("EMBEDDING_KEY", "default_key")



class Embedder:
    def __init__(self, base_url: str = ENV_EMBEDDING_BASE_URL, model: str = ENV_EMBEDDING_MODEL, key: str = ENV_EMBEDDING_KEY):
        self.base_url = base_url
        self.client = openai.OpenAI(base_url=urllib.parse.urljoin(base_url, "v1"), api_key=key)
        self.model = model
        self.key = key
        # Initialize a raw requests session for auxiliary endpoints that are not covered by the OpenAI SDK
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

        # # Check if server is up upon initialization
        # health_url = urllib.parse.urljoin(self.base_url, "health")
        # try:
        #     response = requests.get(health_url, timeout=5)
        #     if response.status_code != 200:
        #         raise RuntimeError(f"Embedder server is not available at {health_url}: {response.status_code}")
        # except requests.RequestException as e:
        #     raise RuntimeError(f"Embedder server is not available at {health_url}: {e}")

    def embed_batch(self, batch: List[str]) -> List[List[float]]:
        response = self.client.embeddings.create(
            model=self.model,
            input=batch,
        )
        return [embedding.embedding for embedding in response.data]

    def embed(self, batch: List[str] | str) -> List[List[float]] | List[float]:
        if isinstance(batch, str):
            return self.embed_batch([batch])[0]
        else:
            return self.embed_batch(batch)

    def __call__(self, batch: List[str] | str) -> List[List[float]] | List[float]:
        return self.embed(batch)

    def count_tokens(self, text: str) -> Tuple[int, int]:
        response = self.session.post(urllib.parse.urljoin(self.base_url, "tokenize"), json={
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
