import json
import os
import shutil
import time
from pathlib import Path

import faker
import pytest
from fastapi.testclient import TestClient
from loguru import logger

from syftbox.client.plugins.sync.constants import MAX_FILE_SIZE_MB
from syftbox.client.plugins.sync.manager import DatasiteState, SyncManager, SyncQueueItem
from syftbox.client.utils.dir_tree import DirTree, create_dir_tree
from syftbox.lib import Client
from syftbox.lib.lib import ClientConfig, SyftPermission
from syftbox.server.settings import ServerSettings
from tests.unit.sync.conftest import setup_datasite

fake = faker.Faker()


def create_random_file(client_config: ClientConfig, sub_path: str = "") -> Path:
    relative_path = Path(sub_path) / fake.file_name(extension="json")
    file_path = client_config.datasite_path / relative_path
    content = {"body": fake.text()}
    file_path.write_text(json.dumps(content))

    path_in_datasite = file_path.relative_to(client_config.sync_folder)
    return path_in_datasite


def assert_files_not_on_datasite(datasite: ClientConfig, files: list[Path]):
    for file in files:
        assert not (datasite.sync_folder / file).exists(), f"File {file} exists on datasite {datasite.email}"


def assert_files_on_datasite(datasite: ClientConfig, files: list[Path]):
    for file in files:
        assert (datasite.sync_folder / file).exists(), f"File {file} does not exist on datasite {datasite.email}"


def assert_files_on_server(server_client: TestClient, files: list[Path]):
    server_settings: ServerSettings = server_client.app_state["server_settings"]
    for file in files:
        assert (server_settings.snapshot_folder / file).exists(), f"File {file} does not exist on server"


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


def test_get_datasites(datasite_1: Client, datasite_2: Client):
    emails = {datasite_1.email, datasite_2.email}
    sync_service = SyncManager(datasite_1)
    sync_service2 = SyncManager(datasite_2)
    sync_service.run_single_thread()
    sync_service2.run_single_thread()

    datasites = sync_service.get_datasite_states()
    assert {datasites[0].email, datasites[1].email} == emails


def test_enqueue_changes(datasite_1: Client):
    sync_service = SyncManager(datasite_1)
    datasites = sync_service.get_datasite_states()

    out_of_sync_permissions, out_of_sync_files = datasites[0].get_out_of_sync_files()
    num_files_after_setup = len(out_of_sync_files) + len(out_of_sync_permissions)

    # Create two files in datasite_1
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "large.txt": fake.text(max_nb_chars=1000),
            "small.txt": fake.text(max_nb_chars=10),
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)
    out_of_sync_permissions, out_of_sync_files = datasites[0].get_out_of_sync_files()
    num_out_of_sync_files = len(out_of_sync_files) + len(out_of_sync_permissions)
    # 3 new files
    assert num_out_of_sync_files - num_files_after_setup == 3

    # Enqueue the changes + verify order
    for change in out_of_sync_permissions + out_of_sync_files:
        sync_service.enqueue(change)

    items_from_queue: list[SyncQueueItem] = []
    while not sync_service.queue.empty():
        items_from_queue.append(sync_service.queue.get())

    should_be_permissions = items_from_queue[: len(out_of_sync_permissions)]
    should_be_files = items_from_queue[len(out_of_sync_permissions) :]

    assert all(SyftPermission.is_permission_file(item.data.path) for item in should_be_permissions)
    assert all(not SyftPermission.is_permission_file(item.data.path) for item in should_be_files)

    for item in should_be_files:
        print(item.priority, item.data)


def test_create_file(server_client: TestClient, datasite_1: Client, datasite_2: Client):
    server_settings: ServerSettings = server_client.app_state["server_settings"]
    sync_service = SyncManager(datasite_1)

    # Create a file in datasite_1
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "file.txt": fake.text(max_nb_chars=1000),
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)

    # changes are pushed to server
    sync_service.run_single_thread()

    # check if no changes are left
    for datasite in sync_service.get_datasite_states():
        out_of_sync_permissions, out_of_sync_files = datasite.get_out_of_sync_files()
        assert not out_of_sync_files
        assert not out_of_sync_permissions

    # check if file exists on server
    print(datasite_2.sync_folder)
    datasite_snapshot = server_settings.snapshot_folder / datasite_1.email
    assert_dirtree_exists(datasite_snapshot, tree)

    # check if file exists on datasite_2
    sync_client_2 = SyncManager(datasite_2)
    sync_client_2.run_single_thread()
    datasite_states = sync_client_2.get_datasite_states()
    ds1_state = datasite_states[0]
    assert ds1_state.email == datasite_1.email

    print(ds1_state.get_out_of_sync_files())

    print(f"datasites {[d.email for d in sync_client_2.get_datasite_states()]}")
    sync_client_2.run_single_thread()

    assert_files_on_datasite(datasite_2, [Path(datasite_1.email) / "folder1" / "file.txt"])


def test_modify(server_client: TestClient, datasite_1: Client):
    server_settings: ServerSettings = server_client.app_state["server_settings"]
    sync_service_1 = SyncManager(datasite_1)

    # Setup initial state
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "file.txt": "content",
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)
    sync_service_1.run_single_thread()

    # modify the file
    file_path = datasite_1.datasite_path / "folder1" / "file.txt"
    new_content = "modified"
    file_path.write_text(new_content)
    assert file_path.read_text() == new_content

    sync_service_1.run_single_thread()

    assert file_path.read_text() == new_content
    assert (server_settings.snapshot_folder / datasite_1.email / "folder1" / "file.txt").read_text() == new_content


def test_modify_and_pull(server_client: TestClient, datasite_1: Client, datasite_2: Client):
    server_settings: ServerSettings = server_client.app_state["server_settings"]
    sync_service_1 = SyncManager(datasite_1)
    sync_service_2 = SyncManager(datasite_2)

    # Setup initial state
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "file.txt": "content1",
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)
    sync_service_1.run_single_thread()
    sync_service_2.run_single_thread()

    # modify the file
    file_path = datasite_1.datasite_path / "folder1" / "file.txt"
    new_content = fake.text(max_nb_chars=100_000)
    file_path.write_text(new_content)

    assert file_path.read_text() == new_content

    sync_service_1.run_single_thread()

    assert file_path.read_text() == new_content
    assert (server_settings.snapshot_folder / datasite_1.email / "folder1" / "file.txt").read_text() == new_content

    sync_service_2.run_single_thread()

    assert file_path.read_text() == new_content
    assert (Path(datasite_2.sync_folder) / datasite_1.email / "folder1" / "file.txt").read_text() == new_content


def test_modify_with_conflict(server_client: TestClient, datasite_1: Client, datasite_2: Client):
    sync_service_1 = SyncManager(datasite_1)
    sync_service_2 = SyncManager(datasite_2)

    # Setup initial state
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "file.txt": "content1",
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)
    sync_service_1.run_single_thread()
    sync_service_2.run_single_thread()

    # modify the file both clients
    file_path_1 = datasite_1.datasite_path / "folder1" / "file.txt"
    new_content_1 = "modified1"
    file_path_1.write_text(new_content_1)

    file_path_2 = Path(datasite_2.sync_folder) / datasite_1.email / "folder1" / "file.txt"
    new_content_2 = "modified2"
    file_path_2.write_text(new_content_2)

    assert new_content_1 != new_content_2
    assert file_path_1.read_text() == new_content_1
    assert file_path_2.read_text() == new_content_2

    # first to server wins
    sync_service_1.run_single_thread()
    sync_service_2.run_single_thread()

    assert file_path_1.read_text() == new_content_1
    assert file_path_2.read_text() == new_content_1

    # modify again, 2 syncs first
    new_content_1 = fake.text(max_nb_chars=1000)
    new_content_2 = fake.text(max_nb_chars=1000)
    file_path_1.write_text(new_content_1)
    file_path_2.write_text(new_content_2)
    assert new_content_1 != new_content_2

    assert file_path_1.read_text() == new_content_1
    assert file_path_2.read_text() == new_content_2

    sync_service_2.run_single_thread()
    sync_service_1.run_single_thread()

    assert file_path_1.read_text() == new_content_2
    assert file_path_2.read_text() == new_content_2


def test_delete_file(server_client: TestClient, datasite_1: Client, datasite_2: Client):
    server_settings: ServerSettings = server_client.app_state["server_settings"]
    sync_service_1 = SyncManager(datasite_1)
    sync_service_2 = SyncManager(datasite_2)

    # Setup initial state
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "file.txt": fake.text(max_nb_chars=1000),
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)
    sync_service_1.run_single_thread()
    sync_service_2.run_single_thread()

    # delete the file
    file_path = datasite_1.datasite_path / "folder1" / "file.txt"
    file_path.unlink()

    sync_service_1.run_single_thread()

    # file is deleted on server
    assert (server_settings.snapshot_folder / datasite_1.email / "folder1" / "file.txt").exists() is False

    sync_service_2.run_single_thread()
    assert (datasite_2.datasite_path / datasite_1.email / "folder1" / "file.txt").exists() is False

    # Check if the metadata is gone
    remote_state_1 = sync_service_1.get_datasite_states()[0].get_remote_state()
    remote_paths = {metadata.path for metadata in remote_state_1}
    assert Path(datasite_1.email) / "folder1" / "file.txt" not in remote_paths


def test_invalid_sync_to_remote(server_client: TestClient, datasite_1: Client):
    sync_service_1 = SyncManager(datasite_1)
    sync_service_1.run_single_thread()

    # random bytes 1 byte too large
    too_large_content = os.urandom((MAX_FILE_SIZE_MB * 1024 * 1024) + 1)
    tree = {
        "valid": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "file.txt": "valid content",
        },
        "invalid_on_modify": {
            "_.syftperm": SyftPermission.mine_with_public_write(datasite_1.email),
            "file.txt": "valid content",
        },
        "invalid_on_create": {
            "_.syftperm": "invalid permission",
            "file.txt": too_large_content,
        },
    }

    create_dir_tree(Path(datasite_1.datasite_path), tree)
    sync_service_1.enqueue_datasite_changes(datasite=DatasiteState(datasite_1, email=datasite_1.email))

    queue = sync_service_1.queue
    consumer = sync_service_1.consumer

    items_to_sync = []
    while not queue.empty():
        items_to_sync.append(queue.get())
    assert len(items_to_sync) == 6  # 3 files + 3 permissions

    for item in items_to_sync:
        decision_tuple = consumer.get_decisions(item)
        abs_path = item.data.local_abs_path

        should_be_valid = item.data.path.parent.name in ["valid", "invalid_on_modify"]
        print(f"path: {abs_path}, should_be_valid: {should_be_valid}, parent: {item.data.path.parent}")

        is_valid = decision_tuple.remote_decision.is_valid(abs_path=abs_path, show_warnings=True)
        assert is_valid == should_be_valid, f"path: {abs_path}, is_valid: {is_valid}"

    sync_service_1.run_single_thread()

    # Modify invalid_on_modify to be invalid
    file_path = datasite_1.datasite_path / "invalid_on_modify" / "file.txt"
    file_path.write_bytes(too_large_content)
    permission_path = datasite_1.datasite_path / "invalid_on_modify" / "_.syftperm"
    permission_path.write_text("invalid permission")

    sync_service_1.enqueue_datasite_changes(datasite=DatasiteState(datasite_1, email=datasite_1.email))
    items_to_sync = []
    while not queue.empty():
        items_to_sync.append(queue.get())
    assert len(items_to_sync) == 4  # 2 invalid files + 2 invalid permissions

    for item in items_to_sync:
        decision_tuple = consumer.get_decisions(item)
        abs_path = item.data.local_abs_path

        is_valid = decision_tuple.remote_decision.is_valid(abs_path=abs_path, show_warnings=True)
        assert not is_valid, f"path: {abs_path}, is_valid: {is_valid}"


def test_sync_invalid_local_environment(datasite_1: Client):
    sync_service = SyncManager(datasite_1)
    sync_service.sync_interval = 0.1
    sync_folder = Path(datasite_1.sync_folder)

    # Create a file in datasite_1
    tree = {
        "folder1": {
            "_.syftperm": SyftPermission.mine_with_public_read(datasite_1.email),
            "file.txt": fake.text(max_nb_chars=1000),
        },
    }
    create_dir_tree(Path(datasite_1.datasite_path), tree)

    # Start syncing in separate thread
    sync_service.start()
    time.sleep(sync_service.sync_interval * 2)
    assert sync_service.is_alive()
    # Deleting the previous state file stops the sync
    shutil.rmtree(sync_folder.as_posix())
    time.sleep(sync_service.sync_interval * 2)

    assert not sync_service.is_alive()

    # Restarting is not possible
    sync_service.start()
    time.sleep(sync_service.sync_interval * 2)
    assert not sync_service.is_alive()


@pytest.mark.skip("This is for manual testing")
def test_n_datasites(tmp_path: Path, server_client: TestClient, datasite_1: Client):
    n = 10
    files_per_datasite = 32

    logger.debug(f"Creating {n} datasites")

    emails = [f"datasite_{i}@openmined.org" for i in range(n)]
    other_datasites: list[Client] = [setup_datasite(tmp_path, server_client, email) for email in emails]

    other_datasite_trees = [
        {
            "folder": {
                "_.syftperm": SyftPermission.mine_with_public_read(email),
            }
        }
        for email in emails
    ]

    for tree in other_datasite_trees:
        tree["folder"].update({f"file_{i}.txt": fake.text(max_nb_chars=10_000) for i in range(files_per_datasite - 1)})

    for datasite, tree in zip(other_datasites, other_datasite_trees):
        create_dir_tree(Path(datasite.datasite_path), tree)

    logger.debug("Syncing datasites")
    for datasite in other_datasites:
        sync_service = SyncManager(datasite)
        sync_service.run_single_thread()

    logger.debug("syncing main datasite")
    sync_service_1 = SyncManager(datasite_1)
    sync_service_1.run_single_thread()
