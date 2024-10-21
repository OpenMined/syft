from collections.abc import Generator
from functools import partial
from pathlib import Path
import time
from typing import Generator
import shutil

import pytest
from fastapi.testclient import TestClient

from syftbox.client.plugins.create_datasite import run as run_create_datasite_plugin
from syftbox.client.plugins.init import run as run_init_plugin
from syftbox.lib.lib import ClientConfig, SharedState,perm_file_path
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings

@pytest.fixture(scope="function")
def datasite_1(tmp_path: Path, server_client: TestClient) -> ClientConfig:
    email = "alice@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture(scope="function")
def datasite_2(tmp_path: Path, server_client: TestClient) -> ClientConfig:
    email = "bob@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture(scope="function")
def datasite_3(tmp_path: Path, server_client: TestClient) -> ClientConfig:
    email = "charlie@openmined.org"
    return setup_datasite(tmp_path, server_client, email)



def setup_datasite(
    tmp_path: Path, server_client: TestClient, email: str
) -> ClientConfig:
    client_path = tmp_path / email
    if client_path.exists():
        if client_path.is_dir():
            shutil.rmtree(client_path)
        else:
            client_path.unlink()
    client_path.mkdir(parents=True)

    client_config = ClientConfig(
        config_path=str(client_path / "client_config.json"),
        sync_folder=str(client_path / "sync"),
        email=email,
        server_url=str(server_client.base_url),
        autorun_plugins=[],
    )

    client_config._server_client = server_client

    shared_state = SharedState(client_config=client_config)
    run_init_plugin(shared_state)
    run_create_datasite_plugin(shared_state)
    wait_for_datasite_setup(client_config)
    return client_config

@pytest.fixture(scope="function")
def server_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    print("Using test dir", tmp_path)
    path = tmp_path / "server"
    path.mkdir()

    print("Server Path", path)

    settings = ServerSettings.from_data_folder(path)
    lifespan_with_settings = partial(server_lifespan, settings=settings)
    server_app.router.lifespan_context = lifespan_with_settings

    with TestClient(server_app) as client:
        yield client


def wait_for_datasite_setup(client_config: ClientConfig, timeout: int = 5):
    print("waiting for datasite setup...")

    perm_file = perm_file_path(str(client_config.datasite_path))

    t0 = time.time()
    while time.time() - t0 < timeout:
        perm_file_exists = Path(perm_file).exists()
        is_registered = client_config.is_registered
        if perm_file_exists and is_registered:
            print("Datasite setup complete")
            return
        time.sleep(1)

    raise TimeoutError("Datasite setup took too long")