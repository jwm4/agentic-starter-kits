from __future__ import annotations

import pytest
from integration.utils import chat_completion_request, health_check


@pytest.mark.integration
def test_auth_enforcement_matrix(
    deployed_agent: str, auth_headers: dict[str, dict[str, str]]
):
    messages = [{"role": "user", "content": "say hi"}]

    unauthenticated = chat_completion_request(deployed_agent, messages)
    assert unauthenticated.status_code == 401

    authenticated = chat_completion_request(
        deployed_agent, messages, headers=auth_headers["allowed"]
    )
    assert authenticated.status_code == 200

    denied = chat_completion_request(
        deployed_agent, messages, headers=auth_headers["denied"]
    )
    assert denied.status_code == 403

    wrong_audience = chat_completion_request(
        deployed_agent,
        messages,
        headers=auth_headers["wrong_audience"],
    )
    assert wrong_audience.status_code == 401

    health_result = health_check(f"{deployed_agent}/health", retries=12, backoff=5.0)
    assert health_result["status"] == "healthy"
    assert health_result["agent_initialized"] is True
