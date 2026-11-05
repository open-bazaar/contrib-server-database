"""The server's own database beside the node's, as the node's database entry is."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy import os
lazy import shutil
lazy import sqlite3
lazy from contextlib import closing
lazy from pathlib import Path
lazy from tempfile import TemporaryDirectory
lazy from typing import Any

from bazaar_contrib_schema import SCHEMA, Schema
from bazaar_contrib_storage import DB, STORAGE, Database, backend_key
from bazaar_core import Contrib, ServiceKey
from pydantic import BaseModel, ConfigDict, Field
lazy from bazaar_core import Context, ContribEntry, ContribSpec, load

__all__ = ["SERVER_DB", "SERVER_SCHEMA", "ServerDatabaseConfig", "server_database"]

SERVER_DB = ServiceKey[Database]("server.database")
SERVER_SCHEMA = ServiceKey[Schema]("server.schema")
DATABASE = "bcs.sqlite3"


class ServerDatabaseConfig(BaseModel):
    """0.2's storage selection, where a storage's own settings sit beside its name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    storage: str = Field(default="sqlite", min_length=1)
    storage_options: dict[str, Any] = Field(default_factory=dict)


def _copy(source: Path, target: Path) -> None:
    """Copy the signing key, then the database, reading the original files only."""
    target.mkdir(parents=True, exist_ok=True)
    key = os.open(target / "session.key", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(key, "wb") as handle:
        handle.write((source / "session.key").read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    with TemporaryDirectory(prefix=".bcs-import-", dir=target) as directory:
        staged = Path(directory) / DATABASE
        for suffix in ("", "-wal"):
            if (path := source / f"{DATABASE}{suffix}").exists():
                shutil.copyfile(path, f"{staged}{suffix}")
        imported = Path(directory) / f"imported-{DATABASE}"
        with (
            closing(sqlite3.connect(staged)) as original,
            closing(sqlite3.connect(imported)) as copy,
        ):
            original.backup(copy)
        os.replace(imported, target / DATABASE)


@asynccontextmanager
async def lifespan(ctx: Context, config: ServerDatabaseConfig):
    home = Path(os.environ.get("BCN_HOME") or await asyncio.to_thread(Path.home))
    source, target = home / ".bcs", home / ".bcn"
    # The database comes over last, so an interrupted import runs again.
    if await asyncio.to_thread(source.is_dir) and not await asyncio.to_thread(
        (target / DATABASE).exists
    ):
        await asyncio.to_thread(_copy, source, target)
    opened: list[tuple[Database, Schema]] = []

    @asynccontextmanager
    async def connect(ctx: Context):
        opened.append((ctx.accept(DB), ctx.accept(SCHEMA)))
        yield

    backend = config.storage_options | (
        {"name": DATABASE} if config.storage == "sqlite" else {}
    )
    composition = await asyncio.to_thread(
        load,
        [
            ContribSpec(contrib="storage"),
            ContribSpec(contrib=config.storage, config=backend),
            ContribSpec(contrib="database", config={"backend": config.storage}),
            ContribSpec(contrib="schema"),
        ],
    )
    composition = composition.model_copy(
        update={
            "entries": (
                *composition.entries,
                ContribEntry(
                    name=f"{ctx.name}/connect",
                    definition=Contrib(accepts=[DB, SCHEMA], lifespan=connect),
                ),
            ),
            # Every part is needed; a missing one fails the server database as a whole.
            "isolate_errors": False,
        }
    )
    async with ctx.enable(
        composition, local=(STORAGE, backend_key(config.storage), DB, SCHEMA)
    ):
        database, schema = opened[0]
        ctx.offer(SERVER_DB, database)
        ctx.offer(SERVER_SCHEMA, schema)
        yield


server_database = Contrib(
    config=ServerDatabaseConfig, offers=[SERVER_DB, SERVER_SCHEMA], lifespan=lifespan
)
