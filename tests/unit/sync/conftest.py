import os
from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from syftbox.client.base import SyftClientInterface
from syftbox.lib.client_config import SyftClientConfig
from syftbox.lib.datasite import create_datasite
from syftbox.lib.workspace import SyftWorkspace
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings


class MockClient(SyftClientInterface):
    def __init__(self, config, workspace, server_client):
        self.config = config
        self.workspace = workspace
        self.server_client = server_client

    @property
    def email(self):
        return self.config.email

    @property
    def datasite(self):
        return Path(self.workspace.datasites, self.config.email)

    @property
    def all_datasites(self) -> list[str]:
        """List all datasites in the workspace"""
        return [d.name for d in self.workspace.datasites.iterdir() if (d.is_dir() and "@" in d.name)]


def setup_datasite(tmp_path: Path, server_client: TestClient, email: str) -> SyftClientInterface:
    syft_path = tmp_path / email
    config = SyftClientConfig(
        path=syft_path / "config.json",
        data_dir=syft_path,
        email=email,
        server_url=str(server_client.base_url),
        client_url="http://localhost:8080",
    )
    config.save()
    ws = SyftWorkspace(config.data_dir)
    ws.mkdirs()
    create_datasite(ws.datasites, email)
    server_client.headers["email"] = email
    server_client.headers["Authorization"] = f"Bearer {config.token}"
    return MockClient(config, ws, server_client)


@pytest.fixture()
def datasite_1(tmp_path: Path, server_client: TestClient) -> SyftClientInterface:
    email = "user_1@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture()
def datasite_2(tmp_path: Path, server_client: TestClient) -> SyftClientInterface:
    email = "user_2@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture(scope="function")
def server_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    print("Using test dir", tmp_path)
    path = tmp_path / "server"
    path.mkdir()

    settings = ServerSettings.from_data_folder(path)
    access_token = os.getenv("SYFTBOX_ACCESS_TOKEN", None)
    if not access_token:
        settings.no_auth = True
    lifespan_with_settings = partial(server_lifespan, settings=settings)
    server_app.router.lifespan_context = lifespan_with_settings

    with TestClient(server_app, base_url="http://localhost:5001") as client:
        yield client
