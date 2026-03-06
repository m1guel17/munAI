"""Tests for ToolPolicyEnforcer."""
from __future__ import annotations

import pytest

from munai.config import ToolsConfig
from munai.tools.policy import PolicyViolation, ToolPolicyEnforcer


@pytest.fixture
def default_policy() -> ToolPolicyEnforcer:
    return ToolPolicyEnforcer(ToolsConfig())


def test_allowed_tool_passes(default_policy: ToolPolicyEnforcer):
    # No exception raised
    default_policy.check_allowed("file_read")
    default_policy.check_allowed("shell_exec")


def test_denied_tool_raises(default_policy: ToolPolicyEnforcer):
    policy = ToolPolicyEnforcer(ToolsConfig(deny=["shell_exec"]))
    with pytest.raises(PolicyViolation, match="explicitly denied"):
        policy.check_allowed("shell_exec")


def test_tool_not_in_allow_list_raises():
    policy = ToolPolicyEnforcer(ToolsConfig(allow=["file_read"]))
    with pytest.raises(PolicyViolation, match="not in the allow list"):
        policy.check_allowed("shell_exec")


def test_deny_takes_priority_over_allow():
    policy = ToolPolicyEnforcer(ToolsConfig(
        allow=["file_read", "shell_exec"],
        deny=["shell_exec"],
    ))
    with pytest.raises(PolicyViolation, match="explicitly denied"):
        policy.check_allowed("shell_exec")
    policy.check_allowed("file_read")  # should not raise


def test_truncate_output_within_limit(default_policy: ToolPolicyEnforcer):
    text = "a" * 100
    assert default_policy.truncate_output(text) == text


def test_truncate_output_over_limit():
    policy = ToolPolicyEnforcer(ToolsConfig(max_output_chars=10))
    result = policy.truncate_output("a" * 20)
    assert len(result) > 10  # includes the truncation message
    assert "truncated" in result
    assert result.startswith("a" * 10)


def test_workspace_only_property(default_policy: ToolPolicyEnforcer):
    assert default_policy.workspace_only is True


def test_shell_approval_mode(default_policy: ToolPolicyEnforcer):
    assert default_policy.shell_approval_mode == "always"
