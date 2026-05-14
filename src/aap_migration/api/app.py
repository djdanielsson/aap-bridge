import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aap_migration.api.dependencies import set_app_state
from aap_migration.api.models import Base
from aap_migration.api.routers import connections, jobs, migration, operations, resources
from aap_migration.api.services.job_service import JobService
from aap_migration.api.websocket import router as ws_router

_db_url: str = ""
_logger = logging.getLogger(__name__)


@dataclass
class AppState:
    db_session_factory: sessionmaker[Session] = field(init=False)
    job_service: JobService = field(init=False)
    loop: asyncio.AbstractEventLoop = field(init=False)
    db_url: str = field(init=False)

    def __post_init__(self) -> None:
        self.job_service = JobService()


def _ensure_encryption_key() -> None:
    if os.environ.get("AAP_BRIDGE_ENCRYPTION_KEY"):
        return
    key = Fernet.generate_key().decode()
    os.environ["AAP_BRIDGE_ENCRYPTION_KEY"] = key
    env_path = Path(".env")
    with open(env_path, "a") as f:
        f.write(f"\nAAP_BRIDGE_ENCRYPTION_KEY={key}\n")
    _logger.warning(
        "AAP_BRIDGE_ENCRYPTION_KEY was not set. Generated and saved to %s",
        env_path.resolve(),
    )
    from aap_migration.api.crypto import reset_fernet

    reset_fernet()


def _migrate_plaintext_tokens(engine: Engine) -> None:
    key = os.environ.get("AAP_BRIDGE_ENCRYPTION_KEY", "")
    if not key:
        return
    f = Fernet(key.encode())
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, token FROM connections WHERE token IS NOT NULL")
        ).fetchall()
        migrated = 0
        for row in rows:
            token = row.token
            try:
                f.decrypt(token.encode("utf-8"))
                continue
            except (InvalidToken, Exception):
                pass
            encrypted = f.encrypt(token.encode("utf-8")).decode("utf-8")
            conn.execute(
                text("UPDATE connections SET token = :token WHERE id = :id"),
                {"token": encrypted, "id": row.id},
            )
            migrated += 1
        if migrated:
            conn.commit()
            _logger.info("Migrated %d plaintext token(s) to encrypted storage", migrated)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _ensure_encryption_key()
    engine = create_engine(_db_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)

    from aap_migration.migration.models import Base as MigrationBase

    MigrationBase.metadata.create_all(engine)
    _migrate_plaintext_tokens(engine)

    state = AppState()
    state.db_session_factory = sessionmaker(bind=engine)
    state.loop = asyncio.get_running_loop()
    state.db_url = _db_url
    set_app_state(state)
    yield
    engine.dispose()


def create_app(db_url: str = "") -> FastAPI:
    global _db_url
    _db_url = db_url

    app = FastAPI(
        title="AAP Bridge",
        description="Web API for AAP Bridge migration tool",
        version="0.1.0",
        lifespan=lifespan,
    )

    import os

    cors_origins = os.environ.get("AAP_BRIDGE_CORS_ORIGINS", "http://localhost:8080").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(connections.router, prefix="/api")
    app.include_router(resources.router, prefix="/api")
    app.include_router(operations.router, prefix="/api")
    app.include_router(migration.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(ws_router)

    return app
