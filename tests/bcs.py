"""Run the published 0.2.3 server once, leaving ~/.bcs as it writes it."""

from __future__ import annotations

lazy import asyncio
lazy import os
lazy from pathlib import Path

import tomli_w


async def legacy(home: Path, port: int) -> None:
    environment = home.parent / "bcs-0.2.3"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    for command in (
        ("uv", "venv", "--python", "3.14", str(environment)),
        ("uv", "pip", "install", "--python", str(python), "bazaar-compute-node==0.2.3"),
    ):
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        assert process.returncode == 0, output.decode()
    data = home / ".bcs"
    await asyncio.to_thread(data.mkdir, parents=True)
    await asyncio.to_thread(
        (data / "config.toml").write_text,
        tomli_w.dumps({"listen": f"127.0.0.1:{port}", "storage": "sqlite"}),
    )
    # The interpreter itself, not the launcher Windows puts in front of it, gets stopped.
    process = await asyncio.create_subprocess_exec(
        str(python),
        "-c",
        "import sys; from bazaar_compute_server.cli import main; sys.exit(main(['run']))",
        env=dict(os.environ) | {"HOME": str(home), "USERPROFILE": str(home)},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stderr is not None
    try:
        while b"Application startup complete" not in (
            line := await process.stderr.readline()
        ):
            assert line, "bcs run ended before it was ready"
    finally:
        process.terminate()
        await process.wait()
