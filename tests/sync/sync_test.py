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

from syftbox.client.config import ClientConfig
from syftbox.client.plugins.create_datasite import run as run_create_datasite_plugin
from syftbox.client.plugins.init import run as run_init_plugin
from syftbox.client.plugins.sync import do_sync
from syftbox.lib.lib import SharedState, perm_file_path
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings

fake = faker.Faker()


@pytest.fixture(scope="function")
def datasite_1(tmp_path: Path, server_client: TestClient) -> ClientConfig:
    email = "user_1@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


@pytest.fixture(scope="function")
def datasite_2(tmp_path: Path, server_client: TestClient) -> ClientConfig:
    email = "user_2@openmined.org"
    return setup_datasite(tmp_path, server_client, email)


def setup_datasite(
    tmp_path: Path, server_client: TestClient, email: str
) -> ClientConfig:
    client_path = tmp_path / email
    client_path.unlink(missing_ok=True)
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

    settings = ServerSettings.from_data_folder(path)
    lifespan_with_settings = partial(server_lifespan, settings=settings)
    server_app.router.lifespan_context = lifespan_with_settings

    with TestClient(server_app) as client:
        yield client


@pytest.fixture(scope="function")
def http_server_client():
    with httpx.Client(base_url="http://localhost:5001") as client:
        yield client


def wait_for_datasite_setup(client_config: ClientConfig, timeout=5):
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


def create_random_file(client_config: ClientConfig, sub_path: str = "") -> Path:
    relative_path = Path(sub_path) / fake.file_name(extension="json")
    file_path = client_config.datasite_path / relative_path
    content = {"body": fake.text()}
    file_path.write_text(json.dumps(content))

    path_in_datasite = file_path.relative_to(client_config.sync_folder)
    return path_in_datasite


def assert_files_not_on_datasite(datasite: ClientConfig, files: list[Path]):
    for file in files:
        assert not (
            datasite.sync_folder / file
        ).exists(), f"File {file} exists on datasite {datasite.email}"


def assert_files_on_datasite(datasite: ClientConfig, files: list[Path]):
    for file in files:
        assert (
            datasite.sync_folder / file
        ).exists(), f"File {file} does not exist on datasite {datasite.email}"


def assert_files_on_server(server_client: TestClient, files: list[Path]):
    server_settings: ServerSettings = server_client.app_state["server_settings"]
    for file in files:
        assert (
            server_settings.snapshot_folder / file
        ).exists(), f"File {file} does not exist on server"


def test_create_public_file(
    server_client: TestClient, datasite_1: ClientConfig, datasite_2: ClientConfig
):
    # Two datasites create and sync a random file each

    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    file_path_1 = create_random_file(datasite_1, "public")
    file_path_2 = create_random_file(datasite_2, "public")
    assert_files_on_datasite(datasite_1, [file_path_1])
    assert_files_on_datasite(datasite_2, [file_path_2])

    # client 1 syncs
    do_sync(datasite_1_shared_state)
    assert_files_on_server(server_client, [file_path_1])
    assert_files_on_datasite(datasite_1, [file_path_1])

    # client 2 syncs
    do_sync(datasite_2_shared_state)
    assert_files_on_server(server_client, [file_path_1, file_path_2])
    assert_files_on_datasite(datasite_1, [file_path_1])
    assert_files_on_datasite(datasite_2, [file_path_1, file_path_2])

    # client 1 syncs again
    do_sync(datasite_1_shared_state)
    assert_files_on_server(server_client, [file_path_1, file_path_2])
    assert_files_on_datasite(datasite_1, [file_path_1, file_path_2])


def test_modify_public_file(
    server_client: TestClient, datasite_1: ClientConfig, datasite_2: ClientConfig
):
    # Two datasites create and sync a random file each

    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    file_path_1 = create_random_file(datasite_1, "public")
    assert_files_on_datasite(datasite_1, [file_path_1])

    # client 1 syncs
    do_sync(datasite_1_shared_state)
    assert_files_on_server(server_client, [file_path_1])

    # client 2 syncs
    do_sync(datasite_2_shared_state)
    assert_files_on_datasite(datasite_2, [file_path_1])

    # client 1 modifies
    (datasite_1.sync_folder / file_path_1).write_text("modified")
    do_sync(datasite_1_shared_state)

    # client 2 gets the modification
    do_sync(datasite_2_shared_state)
    assert (datasite_2.sync_folder / file_path_1).read_text() == "modified"


@pytest.mark.skip("Delete works after a few seconds, is this intended behaviour?")
def test_delete_public_file(
    server_client: TestClient, datasite_1: ClientConfig, datasite_2: ClientConfig
):
    # Two datasites create and sync a random file each
    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    file_path_1 = create_random_file(datasite_1, "public")
    assert_files_on_datasite(datasite_1, [file_path_1])

    # client 1 syncs
    do_sync(datasite_1_shared_state)
    assert_files_on_server(server_client, [file_path_1])

    # client 2 syncs
    do_sync(datasite_2_shared_state)
    assert_files_on_datasite(datasite_2, [file_path_1])

    # client 1 deletes
    (datasite_1.sync_folder / file_path_1).unlink()

    # deletion is only synced after a few seconds, so first sync does not delete
    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)
    assert_files_on_datasite(datasite_2, [file_path_1])

    # after a few seconds the file is deleted
    time.sleep(5)
    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)
    assert_files_on_datasite(datasite_2, [file_path_1])
