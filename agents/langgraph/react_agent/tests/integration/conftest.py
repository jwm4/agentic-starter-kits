from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from integration.utils import (
    MakeTargetError,
    RouteNotFoundError,
    create_sa_token,
    create_serviceaccount,
    delete_serviceaccount,
    get_route,
    load_agent_name,
    run_make,
)

logger = logging.getLogger(__name__)
pytest_plugins = ("integration.conftest",)

INTERNAL_REGISTRY = "image-registry.openshift-image-registry.svc:5000"
ALLOWED_CALLER_SA = "langgraph-react-agent-caller"
DENIED_CALLER_SA = "langgraph-react-agent-denied"
AUDIENCE = "langgraph-react-agent"
WRONG_AUDIENCE = "langgraph-react-agent-wrong"


@pytest.fixture(scope="module")
def agent_dir(repo_root: Path) -> Path:
    return repo_root / "agents" / "langgraph" / "react_agent"


@pytest.fixture(scope="module")
def agent_name(agent_dir: Path) -> str:
    return load_agent_name(agent_dir)


def _write_env_file(
    *,
    agent_dir: Path,
    container_image: str,
    namespace: str,
    allowed_caller_sa: str,
) -> Path:
    """Write a .env file so Makefile targets can source it."""
    missing = [v for v in ("BASE_URL", "MODEL_ID") if v not in os.environ]
    if missing:
        pytest.fail(
            f"Missing required env vars: {', '.join(missing)}. "
            "Set them in the CI workflow or export locally."
        )
    env_path = agent_dir / ".env"
    env_path.write_text(
        f"API_KEY={os.environ.get('API_KEY', 'not-needed')}\n"
        f"BASE_URL={os.environ['BASE_URL']}\n"
        f"MODEL_ID={os.environ['MODEL_ID']}\n"
        f"CONTAINER_IMAGE={container_image}\n"
        f"AUTH_ALLOWED_SERVICEACCOUNT={namespace}:{allowed_caller_sa}\n",
        encoding="utf-8",
    )
    return env_path


@pytest.fixture(scope="module")
def auth_callers(cluster_auth: dict[str, str]) -> dict[str, str]:
    namespace = cluster_auth["namespace"]
    create_serviceaccount(ALLOWED_CALLER_SA, namespace)
    create_serviceaccount(DENIED_CALLER_SA, namespace)
    try:
        yield {"allowed": ALLOWED_CALLER_SA, "denied": DENIED_CALLER_SA}
    finally:
        delete_serviceaccount(ALLOWED_CALLER_SA, namespace)
        delete_serviceaccount(DENIED_CALLER_SA, namespace)


@pytest.fixture(scope="module")
def deployed_agent(
    cluster_auth: dict[str, str],
    agent_dir: Path,
    agent_name: str,
    auth_callers: dict[str, str],
) -> str:
    namespace = cluster_auth["namespace"]
    container_image = f"{INTERNAL_REGISTRY}/{namespace}/{agent_name}:latest"
    env_path = _write_env_file(
        agent_dir=agent_dir,
        container_image=container_image,
        namespace=namespace,
        allowed_caller_sa=auth_callers["allowed"],
    )

    deployed = False
    try:
        logger.info("Building image on cluster via build-openshift...")
        run_make("build-openshift", cwd=agent_dir, timeout=1200)

        logger.info("Deploying to cluster...")
        run_make("deploy", cwd=agent_dir, timeout=300)
        deployed = True

        route_url = get_route(agent_name, namespace=namespace)
        logger.info("Agent deployed at %s", route_url)
        yield route_url
    except (MakeTargetError, RouteNotFoundError) as exc:
        pytest.fail(f"Deployment failed: {exc}")
    finally:
        if deployed:
            logger.info("Tearing down deployment...")
            try:
                run_make("undeploy", cwd=agent_dir, timeout=120)
            except MakeTargetError:
                logger.warning(
                    "Cleanup failed — manual undeploy may be needed", exc_info=True
                )
        env_path.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def auth_headers(
    cluster_auth: dict[str, str],
    auth_callers: dict[str, str],
) -> dict[str, dict[str, str]]:
    namespace = cluster_auth["namespace"]
    allowed = create_sa_token(
        service_account=auth_callers["allowed"],
        namespace=namespace,
        audience=AUDIENCE,
    )
    denied = create_sa_token(
        service_account=auth_callers["denied"],
        namespace=namespace,
        audience=AUDIENCE,
    )
    wrong_audience = create_sa_token(
        service_account=auth_callers["allowed"],
        namespace=namespace,
        audience=WRONG_AUDIENCE,
    )
    return {
        "allowed": {"Authorization": f"Bearer {allowed}"},
        "denied": {"Authorization": f"Bearer {denied}"},
        "wrong_audience": {"Authorization": f"Bearer {wrong_audience}"},
    }
