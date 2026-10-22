import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.deps import AgentDeps
from app.agent.graph import build_graph
from app.api import auth as auth_api
from app.api import graph, health, links, notes, reviews, sessions, voice
from app.auth import AuthService, LoginLimiter, require_auth
from app.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.embeddings import get_embedder
from app.llm import UsageTracker, get_llm
from app.tracks import sync_tracks
from app.voice import get_voice_provider

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    app.state.sessionmaker = sessionmaker
    async with sessionmaker() as db:
        await sync_tracks(db)

    app.state.auth = AuthService(settings)
    app.state.login_limiter = LoginLimiter()
    app.state.usage = UsageTracker()
    app.state.deps = AgentDeps(
        settings=settings,
        sessionmaker=sessionmaker,
        llm=get_llm(settings, app.state.usage),
        embedder=get_embedder(settings),
    )
    app.state.graph = build_graph(app.state.deps)

    # A voice provider with missing keys must not stop the API: report it over the socket.
    app.state.voice, app.state.voice_error = None, None
    try:
        app.state.voice = get_voice_provider(settings)
    except (ValueError, NotImplementedError) as exc:
        log.error("voice provider unavailable: %s", exc)
        app.state.voice_error = str(exc)

    yield
    if app.state.voice is not None:
        await app.state.voice.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Recall", version="0.5.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    guarded = [Depends(require_auth)]
    app.include_router(health.router)
    app.include_router(auth_api.router)
    app.include_router(sessions.router, dependencies=guarded)
    app.include_router(notes.router, dependencies=guarded)
    app.include_router(links.router, dependencies=guarded)
    app.include_router(graph.router, dependencies=guarded)
    app.include_router(reviews.router, dependencies=guarded)
    app.include_router(voice.router)  # authenticates its own WebSocket handshake
    return app


app = create_app()
