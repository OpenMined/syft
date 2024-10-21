import os
from pathlib import Path

from syftbox.server.settings import ServerSettings


def test_server_settings_from_env():
    os.environ["SYFTBOX_DATA_FOLDER"] = "data_folder"
    os.environ["SYFTBOX_SNAPSHOT_FOLDER"] = "data_folder/snapshot_folder"
    os.environ["SYFTBOX_USER_FILE_PATH"] = "data_folder/user_file_path.json"

    settings = ServerSettings()
    print(settings)
    assert settings.data_folder == Path("data_folder")
    assert settings.snapshot_folder == Path("data_folder/snapshot_folder")
    assert settings.user_file_path == Path("data_folder/user_file_path.json")
