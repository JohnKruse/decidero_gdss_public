import pytest

from app.utils.websocket_manager import ConnectionInfo, WebSocketManager


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeSocket:
    def __init__(self, *, on_send=None, should_fail: bool = False):
        self._on_send = on_send
        self._should_fail = should_fail

    async def send_json(self, _message):
        if self._on_send:
            self._on_send()
        if self._should_fail:
            raise RuntimeError("send failed")


@pytest.mark.anyio("asyncio")
async def test_broadcast_uses_snapshot_when_connections_change():
    manager = WebSocketManager()
    meeting_id = "MTG-WS-1"

    def _disconnect_peer():
        manager.disconnect(meeting_id, "conn-b")

    manager.active_connections[meeting_id] = {
        "conn-a": ConnectionInfo(
            id="conn-a", websocket=_FakeSocket(on_send=_disconnect_peer)
        ),
        "conn-b": ConnectionInfo(id="conn-b", websocket=_FakeSocket()),
    }

    await manager.broadcast(meeting_id, {"type": "state_update"})

    assert "conn-a" in manager.active_connections[meeting_id]
    assert "conn-b" not in manager.active_connections[meeting_id]


@pytest.mark.anyio("asyncio")
async def test_broadcast_drops_failed_connections():
    manager = WebSocketManager()
    meeting_id = "MTG-WS-2"
    manager.active_connections[meeting_id] = {
        "conn-ok": ConnectionInfo(id="conn-ok", websocket=_FakeSocket()),
        "conn-fail": ConnectionInfo(
            id="conn-fail", websocket=_FakeSocket(should_fail=True)
        ),
    }

    await manager.broadcast(meeting_id, {"type": "ping"})

    assert "conn-ok" in manager.active_connections[meeting_id]
    assert "conn-fail" not in manager.active_connections[meeting_id]
