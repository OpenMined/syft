import json
from functools import partial
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from syftbox.server.server import app
from syftbox.server.server import app as server_app
from syftbox.server.server import lifespan as server_lifespan
from syftbox.server.settings import ServerSettings

TEST_DATASITE_NAME = "test_datasite@openmined.org"
TEST_FILE = "test_file.txt"
PERMFILE_FILE = "_.syftperm"
PERMFILE_DICT = {
    "admin": [TEST_DATASITE_NAME],
    "read": [TEST_DATASITE_NAME],
    "write": [TEST_DATASITE_NAME],
}


@pytest.fixture(scope="function")
def client(monkeypatch, tmp_path):
    """Every client gets their own snapshot folder at `tmp_path`"""
    snapshot_folder = tmp_path / "snapshot"
    settings = ServerSettings.from_data_folder(snapshot_folder)
    monkeypatch.setenv("SYFTBOX_DATA_FOLDER", str(settings.data_folder))
    monkeypatch.setenv("SYFTBOX_SNAPSHOT_FOLDER", str(settings.snapshot_folder))
    monkeypatch.setenv("SYFTBOX_USER_FILE_PATH", str(settings.user_file_path))

    datasite_name = TEST_DATASITE_NAME
    datasite = settings.snapshot_folder / datasite_name
    datasite.mkdir(parents=True)

    datafile = datasite / TEST_FILE
    datafile.touch()
    datafile.write_bytes(b"Hello, World!")

    datafile = datasite / TEST_DATASITE_NAME / TEST_FILE
    datafile.parent.mkdir(parents=True)

    datafile.touch()
    datafile.write_bytes(b"Hello, World!")

    permfile = datasite / PERMFILE_FILE
    permfile.touch()
    permfile.write_text(json.dumps(PERMFILE_DICT))

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def client_without_perms(monkeypatch, tmp_path):
    """Every client gets their own snapshot folder at `tmp_path`"""
    settings = ServerSettings.from_data_folder(tmp_path)
    monkeypatch.setenv("SYFTBOX_DATA_FOLDER", str(settings.data_folder))
    monkeypatch.setenv("SYFTBOX_SNAPSHOT_FOLDER", str(settings.snapshot_folder))
    monkeypatch.setenv("SYFTBOX_USER_FILE_PATH", str(settings.user_file_path))

    datasite_name = TEST_DATASITE_NAME
    datasite = settings.snapshot_folder / datasite_name
    datasite.mkdir(parents=True)

    datafile = datasite / TEST_FILE
    datafile.touch()
    datafile.write_bytes(b"Hello, World!")

    permfile = datasite / PERMFILE_FILE
    permfile.touch()
    permfile.write_text("")

    with TestClient(app) as client:
        yield client


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
