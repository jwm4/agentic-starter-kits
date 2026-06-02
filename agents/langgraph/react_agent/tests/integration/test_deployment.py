"""Deployment smoke test for react_agent.

This file intentionally validates only deployment health/readiness. The auth
matrix was moved into `test_auth.py` to keep deployment checks simple and keep
identity/audience authorization coverage in a dedicated auth-focused test.
"""

import pytest
from integration.utils import health_check


@pytest.mark.integration
def test_health_endpoint(deployed_agent):
    route_url = deployed_agent
    result = health_check(f"{route_url}/health", retries=12, backoff=5.0)

    assert result["status"] == "healthy"
    assert result["agent_initialized"] is True
