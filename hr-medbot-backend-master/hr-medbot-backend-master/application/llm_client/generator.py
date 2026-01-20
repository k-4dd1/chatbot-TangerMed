from typing import List, Generator, Dict, Tuple
import openai
import os
import urllib.parse
import requests


ENV_GENERATOR_BASE_URL = os.getenv("GENERATOR_BASE_URL")
ENV_GENERATOR_MODEL = os.getenv("GENERATOR_MODEL")
ENV_GENERATOR_KEY = os.getenv("GENERATOR_KEY", "default_key")




class Generator:
    def __init__(self, base_url: str = ENV_GENERATOR_BASE_URL, model: str = ENV_GENERATOR_MODEL, key: str = ENV_GENERATOR_KEY, temperature: float = 0.7, max_tokens: int = 1000):
        self.base_url = base_url
        self.client = openai.OpenAI(base_url=urllib.parse.urljoin(base_url, "v1"), api_key=key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.key = key
        # Raw requests session for auxiliary endpoints not covered by the OpenAI SDK
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
        #         raise RuntimeError(f"Generator server is not available at {health_url}: {response.status_code}")
        # except requests.RequestException as e:
        #     raise RuntimeError(f"Generator server is not available at {health_url}: {e}")

    @staticmethod
    def __stream_response(response: Generator[openai.ChatCompletion, None, None]) -> Generator[str, None, None]:
        for chunk in response:
            if chunk.choices[0].finish_reason == "stop":
                break
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @staticmethod
    def __stream_response_invoke(response: Generator[openai.Completion, None, None]) -> Generator[str, None, None]:
        """Yield tokens from a text-completion streaming response (no delta field)."""
        for chunk in response:
            choice = chunk.choices[0]
            if choice.finish_reason == "stop":
                break
            if choice.text:
                yield choice.text
    
    def chat_completion(self, messages: List[Dict[str, str]], stream: bool = False) -> Generator[str, None, None] | str:
        response = self.client.chat.completions.create(model=self.model,
                                                       messages=messages,
                                                       stream=stream,
                                                       temperature=self.temperature,
                                                       max_tokens=self.max_tokens,
                                                       )
        if stream:
            return self.__stream_response(response)
        else:
            return response.choices[0].message.content
    
    def __call__(self, messages: List[Dict[str, str]], stream: bool = False) -> Generator[str, None, None] | str:
        return self.chat_completion(messages, stream)

    def invoke(self, prompt: str, stream: bool = False) -> Generator[str, None, None] | str:
        response = self.client.completions.create(model=self.model,
                                                  prompt=prompt,
                                                  stream=stream,
                                                  temperature=self.temperature,
                                                  max_tokens=self.max_tokens,
                                                  )
        if stream:
            return self.__stream_response_invoke(response)
        else:
            return response.choices[0].text

    def count_conversation_tokens(self, messages: List[Dict[str, str]]) -> Tuple[int, int]:
        response = self.session.post(urllib.parse.urljoin(self.base_url, "tokenize"), json={
                "model": self.model,
                "messages": messages
        })
        try:
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"Token count request failed: {e}")
        data = response.json()
        if "count" not in data or "max_model_len" not in data:
            raise ValueError(f"Unexpected token count response format: {data}")
        return data["count"], data["max_model_len"]

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
