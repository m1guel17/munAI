"""Tool policy enforcement: allow/deny, workspace containment, output redaction."""
from __future__ import annotations

from ..config import ToolsConfig


class PolicyViolation(Exception):
    """Raised when a tool call violates the configured policy."""


class ToolPolicyEnforcer:
    """Checks tool calls against the configured ToolsConfig policy.

    Responsibilities:
    - Verify the tool is in the allow list and not in the deny list.
    - Enforce the workspace_only restriction (via PathSandbox, called by each tool).
    - Apply output length truncation.
    """

    def __init__(self, config: ToolsConfig) -> None:
        self._config = config

    def check_allowed(self, tool_name: str) -> None:
        """Raise PolicyViolation if the tool is not permitted.

        Deny list takes priority over allow list.
        """
        if tool_name in self._config.deny:
            raise PolicyViolation(
                f"Tool '{tool_name}' is explicitly denied by policy."
            )
        if self._config.allow and tool_name not in self._config.allow:
            raise PolicyViolation(
                f"Tool '{tool_name}' is not in the allow list: {self._config.allow}."
            )

    def truncate_output(self, output: str) -> str:
        """Truncate tool output to the configured maximum character count."""
        limit = self._config.max_output_chars
        if len(output) > limit:
            return output[:limit] + f"\n[... output truncated at {limit} chars]"
        return output

    @property
    def workspace_only(self) -> bool:
        return self._config.workspace_only

    @property
    def shell_approval_mode(self) -> str:
        return self._config.shell_approval_mode
