import os
from pathlib import Path

from syftbox.server.settings import ServerSettings


def test_server_settings_from_env():
    os.environ["SYFTBOX_DATA_FOLDER"] = "data_folder"

    settings = ServerSettings()
    print(settings)
    assert settings.data_folder == Path("data_folder")
    assert settings.snapshot_folder == Path("data_folder/snapshot")
    assert settings.user_file_path == Path("data_folder/users.json")
