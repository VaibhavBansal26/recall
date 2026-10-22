import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx

from app.config import EMBEDDING_DIM, Settings


class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder(Embedder):
    """Hashed bag-of-words. Similar wording gives high cosine similarity, so dedup is demoable."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = int.from_bytes(hashlib.md5(word.encode()).digest()[:4], "big") % EMBEDDING_DIM
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class VoyageEmbedder(Embedder):
    def __init__(self, settings: Settings) -> None:
        if not settings.embedding_api_key:
            raise ValueError("EMBEDDING_PROVIDER=voyage needs EMBEDDING_API_KEY")
        self._model = settings.embedding_model
        self._http = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            timeout=30,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._http.post(
            "/embeddings", json={"input": texts, "model": self._model, "output_dimension": 1024}
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "fake":
        return FakeEmbedder()
    return VoyageEmbedder(settings)
