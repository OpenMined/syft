from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from syftbox.client.base import Plugins, SyftClientInterface
from syftbox.client.client2 import SyftClientContext
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.datasite import create_datasite
from syftbox.lib.workspace import SyftWorkspace
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings
from tests.unit.server.conftest import get_access_token


def authenticate_testclient(client: TestClient, email: str) -> None:
    access_token = get_access_token(client, email)
    client.headers["email"] = email
    client.headers["Authorization"] = f"Bearer {access_token}"


class MockPluginManager(Plugins):
    pass


def setup_datasite(tmp_path: Path, server_client: TestClient, email: str) -> SyftClientInterface:
    data_dir = tmp_path / email
    config = SyftClientConfig(
        path=data_dir / "config.json",
        data_dir=data_dir,
        email=email,
        server_url=str(server_client.base_url),
        client_url="http://localhost:8080",
    )
    config.save()
    ws = SyftWorkspace(config.data_dir)
    ws.mkdirs()
    create_datasite(ws.datasites, email)
    authenticate_testclient(server_client, email)
    return SyftClientContext(
        config,
        ws,
        server_client,
        MockPluginManager(),
    )


@pytest.fixture(scope="function")
def server_app_with_lifespan(tmp_path: Path) -> FastAPI:
    """
    NOTE we are spawning a new server thread for each datasite,
    this is not ideal but it is the same as using multiple uvicorn workers
    """
    path = tmp_path / "server"
    path.mkdir()

    settings = ServerSettings.from_data_folder(path)
    lifespan_with_settings = partial(server_lifespan, settings=settings)
    server_app.router.lifespan_context = lifespan_with_settings

    return server_app


@pytest.fixture()
def datasite_1(tmp_path: Path, server_app_with_lifespan: FastAPI) -> SyftClientInterface:
    email = "user_1@openmined.org"
    with TestClient(server_app_with_lifespan) as client:
        return setup_datasite(tmp_path, client, email)


@pytest.fixture()
def datasite_2(tmp_path: Path, server_app_with_lifespan: FastAPI) -> SyftClientInterface:
    email = "user_2@openmined.org"
    with TestClient(server_app_with_lifespan) as client:
        return setup_datasite(tmp_path, client, email)


@pytest.fixture(scope="function")
def server_client(server_app_with_lifespan: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(server_app_with_lifespan) as client:
        yield client
