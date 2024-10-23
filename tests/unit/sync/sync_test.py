import json
from pathlib import Path

import faker
from fastapi.testclient import TestClient

from syftbox import Client
from syftbox.client.plugins.sync.manager import SyncManager, SyncQueueItem
from syftbox.client.plugins.sync.sync import is_permission_file
from syftbox.client.utils.dir_tree import DirTree, create_dir_tree
from syftbox.lib.lib import SyftPermission
from syftbox.server.settings import ServerSettings

fake = faker.Faker()


def create_random_file(client: Client, sub_path: str = "") -> Path:
    relative_path = Path(sub_path) / fake.file_name(extension="json")
    file_path = client.datasite_path / relative_path
    content = {"body": fake.text()}
    file_path.write_text(json.dumps(content))

    path_in_datasite = file_path.relative_to(client.sync_folder)
    return path_in_datasite


def assert_files_not_on_datasite(datasite: Client, files: list[Path]):
    for file in files:
        assert not (datasite.sync_folder / file).exists(), f"File {file} exists on datasite {datasite.email}"


def assert_files_on_datasite(datasite: Client, files: list[Path]):
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

    datasites = sync_service.get_datasites()
    assert {datasites[0].email, datasites[1].email} == emails


def test_enqueue_changes(datasite_1: Client):
    sync_service = SyncManager(datasite_1)
    datasites = sync_service.get_datasites()

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

    assert all(is_permission_file(item.data.path) for item in should_be_permissions)
    assert all(not is_permission_file(item.data.path) for item in should_be_files)

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
    for datasite in sync_service.get_datasites():
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
    datasite_states = sync_client_2.get_datasites()
    ds1_state = datasite_states[0]
    assert ds1_state.email == datasite_1.email

    print(ds1_state.get_out_of_sync_files())

    print(f"datasites {[d.email for d in sync_client_2.get_datasites()]}")
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
    remote_state_1 = sync_service_1.get_datasites()[0].get_remote_state()
    remote_paths = {metadata.path for metadata in remote_state_1}
    assert Path(datasite_1.email) / "folder1" / "file.txt" not in remote_paths
