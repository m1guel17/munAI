"""Gateway authentication: token validation for WebSocket handshakes."""
from __future__ import annotations

import hmac

from .protocol import ConnectMessage


class GatewayAuth:
    """Validates WebSocket handshake tokens.

    Uses constant-time comparison (hmac.compare_digest) to prevent
    timing side-channel attacks on token validation.

    If no token is configured (expected_token is None), all connections
    are accepted — suitable for loopback-only deployments.
    """

    def __init__(self, expected_token: str | None) -> None:
        self._token = expected_token

    def validate_connect(self, msg: ConnectMessage) -> tuple[bool, str | None]:
        """Validate a connect handshake message.

        Returns:
            (is_valid, error_reason) — error_reason is None when valid.
        """
        # external_app clients must always use a token, even on loopback
        if self._token is None:
            if msg.client_type == "external_app":
                return False, (
                    "external_app clients require a gateway auth token. "
                    "Set token_env in the [gateway] config and export that env var."
                )
            return True, None

        provided = msg.auth.token
        if provided is None:
            return False, "Token required but not provided"

        if not hmac.compare_digest(
            provided.encode("utf-8"),
            self._token.encode("utf-8"),
        ):
            return False, "Token mismatch"

        return True, None
