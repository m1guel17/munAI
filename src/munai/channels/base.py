"""Abstract base class and shared types for channel adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Attachment(BaseModel):
    mime_type: str
    url: str | None = None
    data: bytes | None = None


class UnifiedMessage(BaseModel):
    """Normalized message from any channel adapter."""
    channel: str                   # "telegram" | "webchat" | "cli"
    channel_message_id: str        # platform-specific message ID
    sender_id: str                 # platform-specific sender ID
    sender_name: str | None = None
    session_key: str               # "{channel}:{sender_id}"
    text: str | None = None
    attachments: list[Attachment] = []
    timestamp: datetime
    is_group: bool = False
    raw: dict[str, Any] = {}


class ChannelAdapter(ABC):
    """Abstract base for all channel adapters.

    Each adapter:
    1. Connects to the external platform (or is passive, like WebChat).
    2. Produces UnifiedMessage objects from incoming messages.
    3. Sends OutboundMessage objects back to the platform.

    Adding a new channel requires implementing this class with three methods.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the channel connection."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        ...
