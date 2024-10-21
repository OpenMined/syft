import json
import os
import shutil
from types import SimpleNamespace

import pytest

from syftbox.app.install import (
    check_os_compatibility,
    clone_repository,
    load_config,
    sanitize_git_path,
)


def test_valid_git_path():
    path = "Example/Repository"
    output_path = sanitize_git_path(path)
    assert path == output_path


def test_valid_git_url():
    path = "Example/Repository"
    http_url = f"http://github.com/{path}"
    output_path = sanitize_git_path(http_url)
    assert path == output_path

    https_url = f"https://github.com/{path}"
    output_path = sanitize_git_path(https_url)
    assert path == output_path


def test_invalid_git_path():
    path = "..Example/../Repository"
    with pytest.raises(ValueError) as excpt:
        _ = sanitize_git_path(path)
        assert excpt.value == "Invalid Git repository path format."


def test_second_invalid_git_path():
    path = "http://example.com"
    with pytest.raises(ValueError) as excpt:
        _ = sanitize_git_path(path)
        assert excpt.value == "Invalid Git repository path format."


def test_clone_valid_repository():
    path = "OpenMined/logged_in"
    temp_path = clone_repository(path)
    assert os.path.exists(temp_path)
    shutil.rmtree(temp_path)


def test_clone_repository_to_an_existent_path():
    # First call will make the repository path exist
    path = "OpenMined/logged_in"
    temp_path = clone_repository(path)
    assert os.path.exists(temp_path)

    # Second call must clone it again without any exception (replaces the old one).
    temp_path = clone_repository(path)
    shutil.rmtree(temp_path)


def test_clone_invalid_repository():
    path = "InvalidUser/InvalidRepo"
    with pytest.raises(ValueError) as excpt:
        _ = clone_repository(path)
        assert (
            excpt.value
            == "The provided repository path doesn't seems to be accessible. Please check it out."
        )


def test_load_app_config():
    valid_json_config = {
        "version": "0.1.0",
        "app": {
            "version": "0.1.0",
            "run": {"command": ["python", "main.py"], "interval": "10"},
            "env": {},
            "platforms": ["linux"],
            "pre_install": ["pip", "install", "psutil"],
            "post_install": [],
            "pre_update": [],
            "post_update": [],
        },
    }
    with open("app.json", "w") as app_json_file:
        json.dump(valid_json_config, app_json_file, indent=4)

    app_config = load_config("app.json")
    assert app_config.version == valid_json_config["version"]
    assert app_config.app.version == valid_json_config["app"]["version"]
    assert app_config.app.run.command == valid_json_config["app"]["run"]["command"]
    assert vars(app_config.app.env) == valid_json_config["app"]["env"]
    assert app_config.app.platforms == valid_json_config["app"]["platforms"]
    assert app_config.app.pre_install == valid_json_config["app"]["pre_install"]
    assert app_config.app.pre_update == valid_json_config["app"]["pre_update"]
    assert app_config.app.post_update == valid_json_config["app"]["post_update"]
    os.remove("app.json")


def test_load_invalid_app_config():
    with open("app.json", "w") as app_json_file:
        json.dump("\nHello World: \n Test", app_json_file, indent=4)

    with pytest.raises(ValueError) as expt:
        load_config("app.json")
        assert expt.value == "File isn't in JSON format"

    os.remove("app.json")


def test_load_inexistent_app_config():
    with pytest.raises(ValueError) as expt:
        load_config("inexistent_app.json")
        assert expt.value == "Couln't find the json config file for this path."


def test_os_compatibility_compatible():
    app_config_mock = SimpleNamespace(
        **{
            "app": SimpleNamespace(
                **{
                    "platforms": ["darwin", "linux"],
                }
            ),
        }
    )

    check_os_compatibility(app_config_mock)


def test_os_compatibility_incompatible():
    app_config_mock = SimpleNamespace(
        **{
            "app": SimpleNamespace(
                **{
                    "platforms": ["different_os"],
                }
            ),
        }
    )
    with pytest.raises(OSError) as e:
        check_os_compatibility(app_config_mock)
        assert e.value == "Your OS isn't supported by this app."


def test_os_compatibility_without_config():
    app_config_mock = SimpleNamespace(**{"app": {}})

    check_os_compatibility(app_config_mock)
