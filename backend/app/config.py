import uuid
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Single-user v1: every row belongs to this user, but the column exists everywhere.
LOCAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Fixed by the `notes.embedding` / `source_chunks.embedding` column type (migration 0002).
EMBEDDING_DIM = 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: Literal["development", "production"] = "development"

    # --- auth (empty passphrase = no login, fine for localhost only) ---
    auth_passphrase: str = ""
    session_secret: str = ""
    session_days: int = 30
    cookie_secure: bool = False  # true behind HTTPS

    database_url: str = "postgresql+psycopg://recall:recall@localhost:5433/recall"
    default_track: str = "ai-eng"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # --- voice ---
    voice_provider: Literal["fake", "pipeline", "realtime"] = "fake"
    deepgram_api_key: str = ""
    stt_model: str = "nova-3"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    tts_model: str = "eleven_flash_v2_5"
    tts_speed: float = 1.0

    # --- LLM ---
    llm_provider: Literal["fake", "anthropic"] = "fake"
    anthropic_api_key: str = ""
    llm_fast_model: str = ""  # live voice turns
    llm_deep_model: str = ""  # note structuring, diagrams, ingestion

    # --- embeddings ---
    embedding_provider: Literal["fake", "voyage"] = "fake"
    embedding_model: str = "voyage-3"  # 1024 dims, matches EMBEDDING_DIM
    embedding_api_key: str = ""

    # --- capture ---
    dedup_similarity: float = 0.88
    max_notes_per_turn: int = 5

    # --- recall ---
    quiz_batch: int = 5  # questions per quiz session
    max_review_items_per_note: int = 2
    max_review_items_per_session: int = 20  # so a long talk does not flood the queue
    confusion_silence_s: float = 25.0  # silence after an explanation counts as confusion; 0 = off

    # --- links ---
    link_similarity: float = 0.35  # candidates for the LLM to judge; it may still say "no link"
    max_links_per_note: int = 3

    # Artificial per-step delay in the fake providers (tests tune this for barge-in).
    fake_delay_s: float = 0.05

    @model_validator(mode="after")
    def _check_auth(self) -> "Settings":
        if self.environment == "production":
            if len(self.auth_passphrase) < 12:
                raise ValueError("production needs AUTH_PASSPHRASE of at least 12 characters")
            if not self.cookie_secure:
                raise ValueError("production needs COOKIE_SECURE=true (serve over HTTPS)")
        if self.auth_passphrase and len(self.session_secret) < 32:
            raise ValueError(
                "AUTH_PASSPHRASE is set, so SESSION_SECRET (32+ characters) is required"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
