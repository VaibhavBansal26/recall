from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.embeddings import Embedder
from app.llm.client import LLMClient


@dataclass
class AgentDeps:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    llm: LLMClient
    embedder: Embedder
