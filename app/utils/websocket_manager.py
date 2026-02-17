from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Any
from uuid import uuid4

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Metadata describing a single WebSocket connection."""

    id: str
    websocket: WebSocket
    user_id: Optional[str] = None

    async def send_json(self, message: Dict[str, Any]) -> None:
        """Proxy to the underlying WebSocket send_json method."""
        await self.websocket.send_json(message)


class WebSocketManager:
    def __init__(self):
        # Key: meeting_id, Value: {connection_id: ConnectionInfo}
        self.active_connections: Dict[str, Dict[str, ConnectionInfo]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        meeting_id: str,
        *,
        user_id: Optional[str] = None,
    ) -> str:
        """Add a new WebSocket connection for a meeting and return its id."""
        await websocket.accept()
        connection_id = str(uuid4())
        connection = ConnectionInfo(
            id=connection_id,
            websocket=websocket,
            user_id=user_id,
        )
        meeting_connections = self.active_connections.setdefault(meeting_id, {})
        meeting_connections[connection_id] = connection
        logger.debug(
            "WebSocket connected: meeting_id=%s connection_id=%s user_id=%s",
            meeting_id,
            connection_id,
            user_id,
        )
        return connection_id

    def disconnect(self, meeting_id: str, connection_id: str) -> None:
        """Remove a WebSocket connection for a meeting."""
        meeting_connections = self.active_connections.get(meeting_id)
        if not meeting_connections:
            return

        if connection_id in meeting_connections:
            meeting_connections.pop(connection_id, None)
            logger.debug(
                "WebSocket disconnected: meeting_id=%s connection_id=%s",
                meeting_id,
                connection_id,
            )

        if not meeting_connections:
            self.active_connections.pop(meeting_id, None)

    async def broadcast(
        self,
        meeting_id: str,
        message: Dict[str, Any],
        *,
        skip_connection: Optional[str] = None,
    ) -> None:
        """Broadcast a message to all connected clients in a meeting."""
        meeting_connections = self.active_connections.get(meeting_id, {})
        disconnected: list[str] = []

        # Iterate over a snapshot to avoid mutation-during-iteration when
        # disconnect() runs concurrently in other request handlers.
        for connection_id, connection in list(meeting_connections.items()):
            if skip_connection and connection_id == skip_connection:
                continue

            try:
                await connection.send_json(message)
            except Exception:  # pragma: no cover - depends on network
                disconnected.append(connection_id)

        for connection_id in disconnected:
            self.disconnect(meeting_id, connection_id)

    async def send_personal_message(
        self,
        meeting_id: str,
        connection_id: str,
        message: Dict[str, Any],
    ) -> None:
        """Send a message to a specific connection in a meeting."""
        connection = self.active_connections.get(meeting_id, {}).get(connection_id)
        if not connection:
            return
        try:
            await connection.send_json(message)
        except Exception:  # pragma: no cover - depends on network
            self.disconnect(meeting_id, connection_id)

    def active_users(self, meeting_id: str) -> Dict[str, ConnectionInfo]:
        """Return the active connection metadata for a meeting."""
        return self.active_connections.get(meeting_id, {}).copy()

    def update_user(
        self,
        meeting_id: str,
        connection_id: str,
        *,
        user_id: Optional[str],
    ) -> None:
        """Update the user metadata for a connection."""
        connection = self.active_connections.get(meeting_id, {}).get(connection_id)
        if connection:
            connection.user_id = user_id
            logger.debug(
                "Updated WebSocket user: meeting_id=%s connection_id=%s user_id=%s",
                meeting_id,
                connection_id,
                user_id,
            )


# Create a singleton instance
websocket_manager = WebSocketManager()
