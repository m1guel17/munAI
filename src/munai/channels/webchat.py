"""WebChat channel adapter — passive, messages arrive via Gateway WebSocket."""
from __future__ import annotations

from datetime import datetime, timezone

from .base import ChannelAdapter, UnifiedMessage

CHANNEL_NAME = "webchat"


class WebchatAdapter(ChannelAdapter):
    """WebChat is a passive adapter: it doesn't maintain an external connection.

    Messages arrive directly over the Gateway's WebSocket from the browser UI.
    This adapter translates gateway protocol messages into UnifiedMessage objects.
    """

    async def connect(self) -> None:
        # No external connection to establish.
        pass

    async def disconnect(self) -> None:
        pass

    def message_from_request(
        self,
        client_id: str,
        text: str,
        request_id: str,
    ) -> UnifiedMessage:
        """Convert a WebSocket 'agent' request into a UnifiedMessage.

        session_key = "webchat:{client_id}" where client_id is the UUID
        provided by the client in its connect handshake.
        """
        return UnifiedMessage(
            channel=CHANNEL_NAME,
            channel_message_id=request_id,
            sender_id=client_id,
            session_key=f"{CHANNEL_NAME}:{client_id}",
            text=text,
            timestamp=datetime.now(timezone.utc),
            is_group=False,
            raw={"client_id": client_id, "text": text},
        )
