import json

import pytest
from fastapi.testclient import TestClient

from syftbox.server.server import app
from syftbox.server.settings import ServerSettings

TEST_DATASITE_NAME = "test_datasite@openmined.org"
TEST_FILE = "test_file.txt"
PERMFILE_FILE = "_.syftperm"
PERMFILE_DICT = {
    "admin": [TEST_DATASITE_NAME],
    "read": [TEST_DATASITE_NAME],
    "write": [TEST_DATASITE_NAME],
}


def get_access_token(client: TestClient, email: str) -> str:
    response = client.post("/auth/request_email_token", json={"email": email})
    email_token = response.json()["email_token"]
    response = client.post(
        "/auth/validate_email_token",
        headers={"Authorization": f"Bearer {email_token}"},
        params={"email": email},
    )
    if response.status_code != 200:
        raise ValueError(f"Failed to get access token, {response.text}")
    return response.json()["access_token"]


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
        access_token = get_access_token(client, TEST_DATASITE_NAME)
        client.headers["Authorization"] = f"Bearer {access_token}"
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
        access_token = get_access_token(client, TEST_DATASITE_NAME)
        client.headers["Authorization"] = f"Bearer {access_token}"
        yield client
