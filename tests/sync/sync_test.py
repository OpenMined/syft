"""
edge cases:
- if i locally modify something I dont have write access to, should sync revert my changes?
    - currently: it won't sync the changes to server, but it won't revert local changes
- why does delete take 5 seconds?
- what do we do when a permission file is corrupted?
"""

import json
import time
from collections.abc import Generator
from functools import partial
from pathlib import Path
from typing import Mapping, Union

import faker
import httpx
import pytest
from fastapi.testclient import TestClient

from syftbox.client.plugins.create_datasite import run as run_create_datasite_plugin
from syftbox.client.plugins.init import run as run_init_plugin
from syftbox.client.plugins.sync import do_sync
from syftbox.lib.lib import ClientConfig, SharedState, SyftPermission, perm_file_path
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings

fake = faker.Faker()

DirTree = Mapping[str, Union[str, "DirTree"]]


def create_local_tree(base_path: Path, tree: DirTree) -> None:
    print(f"creating tree at {base_path}, {type(base_path)}")
    for name, content in tree.items():
        local_path = base_path / name

        if isinstance(content, str):
            local_path.write_text(content)
        elif isinstance(content, SyftPermission):
            content.save(path=str(local_path))
        elif isinstance(content, dict):
            local_path.mkdir(parents=True, exist_ok=True)
            create_local_tree(local_path, content)


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


def assert_dirtree_exists(base_path: Path, tree: DirTree) -> None:
    for name, content in tree.items():
        local_path = base_path / name

        if isinstance(content, str):
            assert local_path.read_text() == content
        elif isinstance(content, SyftPermission):
            assert json.loads(local_path.read_text()) == content.to_dict()
        elif isinstance(content, dict):
            assert local_path.is_dir()
            assert_dirtree_exists(local_path, content)


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


def test_move_file(
    server_client: TestClient, datasite_1: ClientConfig, datasite_2: ClientConfig
):
    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "file1.txt": "content1",
        },
    }

    create_local_tree(Path(datasite_1.datasite_path), tree)

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    assert_dirtree_exists(Path(datasite_2.sync_folder) / datasite_1.email, tree)

    # move file1 to new folder
    file1 = Path(datasite_1.datasite_path) / "folder1" / "file1.txt"

    new_tree = {
        "folder2": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
        },
    }

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    # wait for delete
    time.sleep(5)

    create_local_tree(Path(datasite_1.datasite_path), new_tree)
    file1.rename(Path(datasite_1.datasite_path) / "folder2" / "file1.txt")

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    assert_files_not_on_datasite(
        datasite_2, [Path(datasite_1.email) / "folder1" / "file1.txt"]
    )
    assert_dirtree_exists(Path(datasite_2.sync_folder) / datasite_1.email, new_tree)


def test_sync_with_permissions(
    server_client: TestClient, datasite_1: ClientConfig, datasite_2: ClientConfig
):
    # TODO split in multiple tests
    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    snapshot_folder = server_client.app_state["server_settings"].snapshot_folder
    snapshot_datasite_1 = snapshot_folder / datasite_1.email

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    tree = {
        "public_read": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "public_read.json": "content1",
        },
        "private": {
            "_.syftperm": SyftPermission.mine_no_permission(datasite_1.email),
            "private.json": "content2",
        },
        "public_write": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "public_write.json": "content3",
        },
        "no_permission": {
            "no_permission.json": "content4",
        },
    }

    # Trees filtered by permission for datasite 2
    public_read_folders = ["public_read", "public_write"]
    public_read_tree = {k: v for k, v in tree.items() if k in public_read_folders}

    create_local_tree(Path(datasite_1.datasite_path), tree)
    assert_dirtree_exists(Path(datasite_1.datasite_path), tree)

    do_sync(datasite_1_shared_state)
    assert_dirtree_exists(snapshot_datasite_1, tree)

    do_sync(datasite_2_shared_state)
    # public files exist, private files do not
    assert_dirtree_exists(
        Path(datasite_2.sync_folder) / datasite_1.email, public_read_tree
    )
    assert_files_not_on_datasite(
        datasite_2,
        [
            Path(datasite_1.email) / "private" / "private.json",
            Path(datasite_1.email) / "no_permission" / "no_permission.json",
        ],
    )

    # DS2 writes to public write file
    public_write_file = (
        Path(datasite_2.sync_folder)
        / datasite_1.email
        / "public_write"
        / "public_write.json"
    )
    public_write_file.write_text("modified")

    do_sync(datasite_2_shared_state)
    do_sync(datasite_1_shared_state)

    assert (
        Path(datasite_1.datasite_path) / "public_write" / "public_write.json"
    ).read_text() == "modified"

    # DS2 writes to public read file, should not be synced
    public_read_file = (
        Path(datasite_2.sync_folder)
        / datasite_1.email
        / "public_read"
        / "public_read.json"
    )
    public_read_file.write_text("modified")

    do_sync(datasite_2_shared_state)
    do_sync(datasite_1_shared_state)

    # Server and datasite 1 should not have the modification
    assert (
        snapshot_datasite_1 / "public_read" / "public_read.json"
    ).read_text() == "content1"
    assert (
        Path(datasite_1.datasite_path) / "public_read" / "public_read.json"
    ).read_text() == "content1"


def test_corrupted_permissions(
    server_client: TestClient, datasite_1: ClientConfig, datasite_2: ClientConfig
):
    datasite_1_shared_state = SharedState(client_config=datasite_1)
    datasite_2_shared_state = SharedState(client_config=datasite_2)

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    dir_tree = {
        "corrupted_folder": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "file.txt": "content",
            "corrupted_subfolder": {
                "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
                "file.txt": "content",
            },
        },
        "normal_folder": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "file.txt": "content",
        },
    }

    create_local_tree(Path(datasite_1.datasite_path), dir_tree)

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    # Corrupt the permission file and do an update
    permission_file = Path(datasite_1.datasite_path) / "corrupted_folder" / "_.syftperm"
    permission_file.write_text("corrupted")

    # Make local changes
    # expected behaviour: files under corrupted permissions are not synced, other files are
    corrupted_file_to_update = (
        Path(datasite_1.datasite_path) / "corrupted_folder" / "file.txt"
    )
    corrupted_subfolder_file_to_update = (
        Path(datasite_1.datasite_path)
        / "corrupted_folder"
        / "corrupted_subfolder"
        / "file.txt"
    )
    normal_file_to_update = (
        Path(datasite_1.datasite_path) / "normal_folder" / "file.txt"
    )
    corrupted_file_to_update.write_text("updated")
    corrupted_subfolder_file_to_update.write_text("updated")
    normal_file_to_update.write_text("updated")

    # NOTE fix this, need to sleep in order to detect faulty deletes
    time.sleep(5)

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    # Corrupted folders and subfolders are not synced
    assert (
        Path(datasite_2.sync_folder)
        / datasite_1.email
        / "corrupted_folder"
        / "file.txt"
    ).read_text() == "content"
    assert (
        Path(datasite_2.sync_folder)
        / datasite_1.email
        / "corrupted_folder"
        / "corrupted_subfolder"
        / "file.txt"
    ).read_text() == "content"

    # Normal folder is synced
    assert (
        Path(datasite_2.sync_folder) / datasite_1.email / "normal_folder" / "file.txt"
    ).read_text() == "updated"

    # Fix the corrupted permission file
    SyftPermission.mine_with_public_read(datasite_1.email).save(
        path=str(permission_file)
    )

    do_sync(datasite_1_shared_state)
    do_sync(datasite_2_shared_state)

    # Corrupted folders and subfolders are now synced
    assert (
        Path(datasite_2.sync_folder)
        / datasite_1.email
        / "corrupted_folder"
        / "file.txt"
    ).read_text() == "updated"
    assert (
        Path(datasite_2.sync_folder)
        / datasite_1.email
        / "corrupted_folder"
        / "corrupted_subfolder"
        / "file.txt"
    ).read_text() == "updated"
