"""
TODO:

# Testing
- Easy way to setup one server with two clients
    - replace sync server calls with httpx client so we can use fastapi test client
- Declarative way to set up a client, with files and permissions

- test ignore files
- test sync files
    - create
    - modify
    - delete
- test sync folders
    - create/delete empty folder
    - create/delete folder with files
- test permissions

Case 1: unit
- we only have 1 client, fire some events and check if the resulting sync is correct
- we can do this later

Case 2: integration
- we have 2 clients, change some state and check if both clients have consistent state
- we start here

# Rewrite sync prototype
- Prototype we have now is hard to extend
- add httpx client
- we want to swap out pieces independent of eachother
"""

import json
import time
from collections.abc import Generator
from functools import partial
from pathlib import Path

import faker
import httpx
import pytest
from fastapi.testclient import TestClient

from syftbox.client.client import app as client_app
from syftbox.client.client import lifespan as client_lifespan
from syftbox.client.plugins.sync import do_sync
from syftbox.lib.lib import ClientConfig, perm_file_path
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings

fake = faker.Faker()


@pytest.fixture(scope="function")
def datasite_1(
    tmp_path: Path, server_client: TestClient
) -> Generator[TestClient, None, None]:
    email = "user_1@openmined.org"
    client_path = tmp_path / "client_1"
    client_path.unlink(missing_ok=True)
    client_path.mkdir(parents=True)
    print("client_path", client_path)

    client_config = ClientConfig(
        config_path=str(client_path / "client_config.json"),
        sync_folder=str(client_path / "sync"),
        email=email,
        server_url=str(server_client.base_url),
        autorun_plugins=["init", "create_datasite"],
    )

    client_config._server_client = server_client

    lifespan_with_settings = partial(client_lifespan, client_config=client_config)
    client_app.router.lifespan_context = lifespan_with_settings
    with TestClient(client_app) as client:
        yield client


@pytest.fixture(scope="function")
def server_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    path = tmp_path / "server"
    path.mkdir()

    settings = ServerSettings.from_data_folder(path)
    lifespan_with_settings = partial(server_lifespan, settings=settings)
    server_app.router.lifespan_context = lifespan_with_settings

    with TestClient(server_app) as client:
        yield client


@pytest.fixture(scope="function")
def http_server_client():
    with httpx.Client(base_url="http://localhost:5001") as client:
        yield client


def wait_for_datasite_setup(datasite: TestClient, timeout=20):
    print("waiting for datasite setup...")

    client_config: ClientConfig = datasite.app.shared_state.client_config
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


def create_random_file(datasite_client: TestClient) -> Path:
    client_config: ClientConfig = datasite_client.app.shared_state.client_config
    file_path = Path(client_config.datasite_path) / fake.file_name(extension="json")
    content = {"body": fake.text()}
    file_path.write_text(json.dumps(content))
    return file_path


def test_sync_file_to_server_snapshot(
    tmp_path: Path, server_client: TestClient, datasite_1: TestClient
):
    print(datasite_1.app.shared_state.client_config)

    wait_for_datasite_setup(datasite_1)

    do_sync(datasite_1.app.shared_state)

    print(server_client.app_state["server_settings"].snapshot_folder)

    file_path = create_random_file(datasite_1)

    do_sync(datasite_1.app.shared_state)

    snapshot_file_path = (
        server_client.app_state["server_settings"].snapshot_folder
        / datasite_1.app.shared_state.client_config.email
        / file_path.name
    )

    assert snapshot_file_path.exists()

    print("test done")
