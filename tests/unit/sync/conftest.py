import time
from collections.abc import Generator
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from syftbox import Client
from syftbox.client.plugins.create_datasite import run as run_create_datasite_plugin
from syftbox.client.plugins.init import run as run_init_plugin
from syftbox.lib.lib import SharedState, perm_file_path
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings


def wait_for_datasite_setup(client: Client, timeout=5):
    print("waiting for datasite setup...")

    perm_file = perm_file_path(str(client.datasite_path))

    t0 = time.time()
    while time.time() - t0 < timeout:
        perm_file_exists = Path(perm_file).exists()
        is_registered = client.is_registered
        if perm_file_exists and is_registered:
            print("Datasite setup complete")
            return
        time.sleep(1)

    raise TimeoutError("Datasite setup took too long")


def setup_datasite(tmp_path: Path, server_client: TestClient, email: str) -> Client:
    client_path = tmp_path / email
    client_path.unlink(missing_ok=True)
    client_path.mkdir(parents=True)

    client = Client(
        config_path=str(client_path / "client_config.json"),
        sync_folder=str(client_path / "sync"),
        email=email,
        server_url=str(server_client.base_url),
        autorun_plugins=[],
    )

    client._server_client = server_client

    shared_state = SharedState(client=client)
    run_init_plugin(shared_state)
    run_create_datasite_plugin(shared_state)
    wait_for_datasite_setup(client)
    return client


@pytest.fixture(scope="function")
def datasite_1(tmp_path: Path, server_client: TestClient) -> Client:
    email = "user_1@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture(scope="function")
def datasite_2(tmp_path: Path, server_client: TestClient) -> Client:
    email = "user_2@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture(scope="function")
def server_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    print("Using test dir", tmp_path)
    path = tmp_path / "server"
    path.mkdir()

    settings = ServerSettings.from_data_folder(path)
    lifespan_with_settings = partial(server_lifespan, settings=settings)
    server_app.router.lifespan_context = lifespan_with_settings

    with TestClient(server_app) as client:
        yield client
