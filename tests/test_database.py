"""The server's database beside the node's, new and taken over from 0.2's server."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy import socket
lazy import sqlite3
lazy from collections.abc import AsyncIterator
lazy from contextlib import closing
lazy from pathlib import Path
lazy from typing import Any

import pytest
from bazaar_contrib_storage import DB, Database, Select
from bazaar_core import (
    Context,
    Contrib,
    ContribEntry,
    ContribHub,
    ContribSpec,
    ServiceKey,
    Stopping,
    load,
)
from bcs import legacy

from bazaar_contrib_server_database import SERVER_DB

NODE = (
    ("timer-wheel", {}),
    ("storage", {}),
    ("sqlite", {}),
    ("database", {"backend": "sqlite"}),
    ("schema", {}),
)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BCN_HOME", str(tmp_path))
    return tmp_path


@asynccontextmanager
async def running(
    *specs: tuple[str, dict[str, Any]],
) -> AsyncIterator[tuple[ContribHub, dict[str, Database]]]:
    """Enable the entries with one consumer of the node's and one of the server's database."""
    databases: dict[str, Database] = {}

    def consumer(key: ServiceKey[Database], name: str) -> ContribEntry:
        @asynccontextmanager
        async def accept(ctx: Context):
            databases[name] = ctx.accept(key)
            yield

        return ContribEntry(
            name=name, definition=Contrib(accepts=[key], lifespan=accept)
        )

    composition = await asyncio.to_thread(
        load, [ContribSpec(contrib=name, config=config) for name, config in specs]
    )
    composition = composition.model_copy(
        update={
            "entries": (
                *composition.entries,
                consumer(DB, "node"),
                consumer(SERVER_DB, "server"),
            )
        }
    )
    async with ContribHub() as hub, hub.enable(composition):
        yield hub, databases


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def test_a_new_server_database_opens_its_own_file(home: Path):
    async with running(*NODE, ("server-database", {})) as (_, databases):
        assert await databases["server"].table_exists("contrib_schema_migrations")
        assert await asyncio.to_thread((home / ".bcn" / "bcs.sqlite3").exists)
        assert await asyncio.to_thread((home / ".bcn" / "bcn.sqlite3").exists)


async def test_a_02_server_comes_over_once_beside_the_node(home: Path):
    await legacy(home, await asyncio.to_thread(free_port))
    original = await asyncio.to_thread(files, home / ".bcs")
    async with running(*NODE, ("server-database", {})) as (_, databases):
        accounts = await databases["server"].select(Select(table="accounts"))
        assert "admin" in {row["name"] for row in accounts}
        assert not await databases["node"].table_exists("accounts")
    key = await asyncio.to_thread((home / ".bcn" / "session.key").read_bytes)
    assert key == original["session.key"]
    assert await asyncio.to_thread(files, home / ".bcs") == original

    rotated = bytes(len(key))
    await asyncio.to_thread((home / ".bcn" / "session.key").write_bytes, rotated)

    def mark() -> None:
        with closing(sqlite3.connect(home / ".bcn" / "bcs.sqlite3")) as connection:
            connection.execute("CREATE TABLE marker (id INTEGER)")
            connection.commit()

    await asyncio.to_thread(mark)
    async with running(*NODE, ("server-database", {})) as (_, databases):
        assert await databases["server"].table_exists("marker")
    assert await asyncio.to_thread((home / ".bcn" / "session.key").read_bytes) == (
        rotated
    )
    assert await asyncio.to_thread(files, home / ".bcs") == original


async def test_a_missing_backend_fails_the_server_database_alone(home: Path):
    async with running(*NODE, ("server-database", {"storage": "missing"})) as (
        hub,
        databases,
    ):
        assert await databases["node"].table_exists("contrib_schema_migrations")
        assert "server" not in databases
        assert any(
            record.name == "server-database"
            and isinstance(record.state, Stopping)
            and record.state.error
            for record in hub.snapshots
        )
    assert not await asyncio.to_thread((home / ".bcn" / "bcs.sqlite3").exists)
