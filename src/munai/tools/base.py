"""Tool dependency container and shared types for pydantic-ai tool integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..audit.logger import AuditLogger
from ..config import ToolsConfig
from .policy import ToolPolicyEnforcer
from .sandbox import PathSandbox

# Type for the emit callback (event_name, payload) -> None
EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]

# Type for the approval callback (approval_id, command, session_id) -> bool
ApprovalFn = Callable[[str, list[str], str], Awaitable[bool]]


@dataclass
class ToolDeps:
    """Dependency container injected into all pydantic-ai tool functions via RunContext.

    Contains everything a tool needs to:
    - Enforce workspace path containment
    - Check against the policy
    - Log to audit
    - Request shell command approval
    - Emit events to the connected client
    """
    workspace_path: Path
    sandbox: PathSandbox
    policy: ToolPolicyEnforcer
    audit: AuditLogger
    session_id: str
    channel: str
    emit: EmitFn
    request_approval: ApprovalFn
    # Tool call counter for this turn (used to generate request IDs)
    _call_count: int = field(default=0, repr=False)

    def next_request_id(self) -> str:
        self._call_count += 1
        return f"tc_{self.session_id[:8]}_{self._call_count:03d}"
