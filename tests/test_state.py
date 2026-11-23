import asyncio
import json
import os
from pathlib import Path

import pytest

from whisper_anywhere.state import DaemonState, DaemonStatus, StatusServer

TIMEOUT = 2


class _Client:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read_status(self) -> DaemonStatus:
        line: bytes = await asyncio.wait_for(self._reader.readline(), TIMEOUT)
        return DaemonStatus.decode(line)

    async def send(self, line: str) -> None:
        self._writer.write((line + "\n").encode())
        await self._writer.drain()

    def close(self) -> None:
        self._writer.close()


async def _connect(path: str) -> _Client:
    reader, writer = await asyncio.open_unix_connection(path)
    return _Client(reader, writer)


async def _served(path: Path):
    server = StatusServer(str(path))
    await server.start()
    return server


@pytest.mark.asyncio
class TestStatusSocket:
    async def test_client_receives_the_idle_snapshot_on_connect(
        self, tmp_path: Path
    ) -> None:
        server = await _served(tmp_path / "state.sock")
        client = await _connect(server.path)
        try:
            assert await client.read_status() == DaemonStatus(DaemonState.IDLE)
        finally:
            client.close()
            await server.close()

    async def test_client_connecting_mid_dictation_receives_current_state(
        self, tmp_path: Path
    ) -> None:
        server = await _served(tmp_path / "state.sock")
        server.publish(DaemonState.RECORDING)
        client = await _connect(server.path)
        try:
            assert await client.read_status() == DaemonStatus(DaemonState.RECORDING)
        finally:
            client.close()
            await server.close()

    async def test_each_transition_reaches_a_connected_client(
        self, tmp_path: Path
    ) -> None:
        server = await _served(tmp_path / "state.sock")
        client = await _connect(server.path)
        try:
            assert (await client.read_status()).state == DaemonState.IDLE

            for state in (
                DaemonState.RECORDING,
                DaemonState.PROCESSING,
                DaemonState.IDLE,
            ):
                server.publish(state)
                assert (await client.read_status()).state == state
        finally:
            client.close()
            await server.close()

    async def test_a_late_client_receives_snapshot_then_later_changes(
        self, tmp_path: Path
    ) -> None:
        server = await _served(tmp_path / "state.sock")
        early = await _connect(server.path)
        assert (await early.read_status()).state == DaemonState.IDLE
        server.publish(DaemonState.RECORDING)
        assert (await early.read_status()).state == DaemonState.RECORDING

        late = await _connect(server.path)
        try:
            assert (await late.read_status()).state == DaemonState.RECORDING
            server.publish(DaemonState.PROCESSING)
            assert (await late.read_status()).state == DaemonState.PROCESSING
            assert (await early.read_status()).state == DaemonState.PROCESSING
        finally:
            late.close()
            early.close()
            await server.close()

    async def test_payload_is_one_json_object_per_line(self, tmp_path: Path) -> None:
        server = await _served(tmp_path / "state.sock")
        server.publish(DaemonState.PROCESSING, "Last dictation failed")
        reader, writer = await asyncio.open_unix_connection(server.path)
        try:
            line: bytes = await asyncio.wait_for(reader.readline(), TIMEOUT)
            assert json.loads(line) == {
                "state": "processing",
                "note": "Last dictation failed",
            }
        finally:
            writer.close()
            await server.close()

    async def test_quit_command_raises_the_quit_request(self, tmp_path: Path) -> None:
        server = await _served(tmp_path / "state.sock")
        client = await _connect(server.path)
        try:
            await client.read_status()
            await client.send('{"command": "quit"}')
            await asyncio.wait_for(server.quit_requested.wait(), TIMEOUT)
        finally:
            client.close()
            await server.close()

    async def test_other_commands_do_not_quit(self, tmp_path: Path) -> None:
        server = await _served(tmp_path / "state.sock")
        client = await _connect(server.path)
        try:
            await client.read_status()
            await client.send("hello")
            assert not server.quit_requested.is_set()
        finally:
            client.close()
            await server.close()

    async def test_close_removes_the_socket(self, tmp_path: Path) -> None:
        path = tmp_path / "state.sock"
        server = await _served(path)
        assert path.exists()

        await server.close()

        assert not path.exists()

    async def test_a_stale_socket_is_replaced(self, tmp_path: Path) -> None:
        path = tmp_path / "state.sock"
        path.write_text("stale")

        server = await _served(path)
        try:
            assert os.path.exists(path)
            assert server.status == DaemonStatus()
            client = await _connect(server.path)
            assert (await client.read_status()).state == DaemonState.IDLE
            client.close()
        finally:
            await server.close()

    async def test_a_departed_client_does_not_block_later_publishes(
        self, tmp_path: Path
    ) -> None:
        server = await _served(tmp_path / "state.sock")
        client = await _connect(server.path)
        await client.read_status()
        client.close()
        await asyncio.sleep(0.05)

        try:
            server.publish(DaemonState.RECORDING)
            survivor = await _connect(server.path)
            assert (await survivor.read_status()).state == DaemonState.RECORDING
            server.publish(DaemonState.IDLE)
            assert (await survivor.read_status()).state == DaemonState.IDLE
            survivor.close()
        finally:
            await server.close()
